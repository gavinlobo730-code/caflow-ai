"""Issuing a sales invoice posts its entry and marks the invoice issued in ONE transaction (migration 577, POST-A-092).

WHAT THIS IS FOR
    The issue route used to post the invoice's journal entry and then, in a second statement, mark the invoice issued and link the
    entry. A failure between the two (a network blip between Singapore and Mumbai, a restart) left revenue and output tax in the ledger
    behind an invoice that was still a draft. `public.issue_sales_invoice_atomic` does both inside one function, so the failure takes
    the entry with it. The mock-mode suite proves the API's half against an in-memory twin; ONLY a real database can prove the property
    itself, and that is this file.

WHAT THIS HOLDS (real Postgres, as the roles that can reach the function)
    * AN ISSUE POSTS AND MARKS: the entry is posted with its lines and the draft is `issued`, with `issued_at` and the entry linked,
      for the service role and for a connection with no JWT alike.
    * A FAILURE AFTER THE POSTING UNDOES THE POSTING: a trigger that makes the invoice's UPDATE fail is put on the table, the call fails,
      and there is no entry, no line and the invoice is exactly the draft it was. With the trigger gone, the same call succeeds. This is
      the property the migration exists for.
    * AN INVOICE THAT IS NOT A DRAFT IS REFUSED (SQLSTATE 55000, "not a draft") and nothing is posted or changed, however many times.
    * TWO SIMULTANEOUS ISSUES: the second waits on the invoice's lock and then finds it issued; one entry exists and the second call
      is the 55000 refusal.
    * THE ENTRY MUST BE THE INVOICE'S OWN: another reference, another date, another source, another type, an unposted entry, and an
      invoice of another client of the firm are each refused (42501) with nothing written, so the function cannot post an arbitrary
      entry and mark an invoice issued on the strength of it.
    * A PRIVILEGED CALL NAMES A CLIENT OF ITS FIRM (the question of migration 546).
    * A DRAFT AN EARLIER ISSUE STRANDED IS FINISHED against the live entry it left: the entry is not posted twice and the invoice is
      issued and linked to it.
    * A CLOSED YEAR REFUSES, in post_journal_atomic's own words, with nothing written (the function does not weaken the closure).
    * THE PERSON TRAVELS: a call that names `audit_actor` writes the invoice's `update` audit row as that person, marked carried.
    * NOBODY SIGNED IN CAN CALL IT: a Partner, a Manager and `anon` are refused by the privilege; the function's grants are the
      server's alone.
    * THE SHAPE AND THE ROLLBACK: the closing check is run alone after each spoiling it is there to catch, the rollback drops the
      function, and a re-apply gives it back.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the atomic-issue proof requires HARNESS_PG + psql",
)

FIRM = "57700000-0000-0000-0000-000000000001"
OTHER_FIRM = "57700000-0000-0000-0000-000000000002"
CLIENT_A = "57700000-0000-0000-0000-0000000000a1"
CLIENT_B = "57700000-0000-0000-0000-0000000000b1"
CLIENT_OTHER = "57700000-0000-0000-0000-0000000000c1"
CUSTOMER_A = "57700000-0000-0000-0000-0000000000d1"
CUSTOMER_B = "57700000-0000-0000-0000-0000000000d2"
AR_A, SALES_A = "57700000-0000-0000-0000-0000000000a6", "57700000-0000-0000-0000-0000000000a7"
AR_B, SALES_B = "57700000-0000-0000-0000-0000000000b6", "57700000-0000-0000-0000-0000000000b7"
INVOICE = "57700000-0000-0000-0000-0000000000e1"
INVOICE_B = "57700000-0000-0000-0000-0000000000e2"
PEOPLE = {            # name: (users.id, auth id, role, firm)
    "partner": ("57700000-0000-0000-0000-00000000000a", "57700000-1111-0000-0000-000000000001", "Partner", FIRM),
    "manager_a": ("57700000-0000-0000-0000-00000000000b", "57700000-1111-0000-0000-000000000002", "Manager", FIRM),
}
MIGRATION = next(p for p in MIGRATIONS.glob("577_issuing_a_sales_invoice_posts_its_entry_and_marks_it_issued*.sql")
                 if not p.name.endswith("_rollback.sql"))
ROLLBACK = next(MIGRATIONS.glob("577_issuing_a_sales_invoice_posts_its_entry_and_marks_it_issued*_rollback.sql"))
FN = "public.issue_sales_invoice_atomic(uuid, jsonb, jsonb, timestamptz)"
INV_NO, INV_DATE = "A092-1", "2025-09-30"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(path)], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


def _one(dsn: str, sql: str) -> str:
    return _rows(dsn, sql)[0][0]


def _prefix(who: str) -> str:
    if who == "backend":                                   # a connection with no JWT, as the owner
        return ""
    if who == "service":
        return "SET ROLE service_role; "
    if who == "anon":
        return "SET request.jwt.claims = '{\"role\": \"anon\"}'; SET ROLE anon; "
    sub = PEOPLE[who][1]
    return f"SET request.jwt.claims = '{{\"sub\": \"{sub}\", \"role\": \"authenticated\"}}'; SET ROLE authenticated; "


def _call(dsn: str, who: str, sql: str) -> tuple[bool, str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _prefix(who) + sql], capture_output=True, text=True)
    if r.returncode != 0:
        m = re.search(r"ERROR:\s+(.*)", r.stderr)
        return False, (m.group(1) if m else r.stderr).strip()
    out = [l for l in r.stdout.splitlines() if l.strip() and l.strip() != "SET"]
    return True, (out[-1].strip() if out else "")


def _j(x) -> str:
    return json.dumps(x).replace("'", "''")


def _entry(**over) -> dict:
    e = {"firm_id": FIRM, "client_id": CLIENT_A, "entry_date": INV_DATE, "reference_no": INV_NO, "narration": "Sales invoice",
         "entry_type": "Sales", "is_posted": True, "status": "posted", "source_type": "sales_invoice", "source_id": INVOICE}
    e.update(over)
    return {k: v for k, v in e.items() if v is not None}


def _lines(paise: int = 118000, ar: str = AR_A, sales: str = SALES_A) -> list[dict]:
    return [{"account_id": ar, "debit_paise": paise, "credit_paise": 0, "narration": "Trade receivable on sale"},
            {"account_id": sales, "debit_paise": 0, "credit_paise": paise, "narration": "Sales revenue"}]


def _issue(dsn: str, who: str = "service", *, invoice: str = INVOICE, entry: dict | None = None, lines: list | None = None,
           issued_at: str = "2025-09-30T10:00:00+00") -> tuple[bool, str]:
    return _call(dsn, who, "SELECT public.issue_sales_invoice_atomic('%s'::uuid, '%s'::jsonb, '%s'::jsonb, '%s'::timestamptz);" % (
        invoice, _j(entry if entry is not None else _entry()), _j(lines if lines is not None else _lines()), issued_at))


def _invoice(dsn: str, invoice: str = INVOICE) -> list[str]:
    return _rows(dsn, f"SELECT status, coalesce(journal_entry_id::text, '-'), coalesce(issued_at::text, '-') "
                      f"FROM client_sales_invoices WHERE id = '{invoice}'")[0]


def _entries(dsn: str, ref: str = INV_NO) -> int:
    return int(_one(dsn, f"SELECT count(*) FROM journal_entries WHERE reference_no = '{ref}'"))


def _lines_written(dsn: str) -> int:
    return int(_one(dsn, "SELECT count(*) FROM journal_lines"))


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e577_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r, _f) in PEOPLE.items())
        members = ", ".join(f"('{i}', '{f}', '{a}', '{n}@t.in', '{n}', '{r}', true)" for n, (i, a, r, f) in PEOPLE.items())
        seed = _psql(d, f"""
            INSERT INTO auth.users (id, email) VALUES {auth};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
                ('{CLIENT_A}', '{FIRM}', 'A', 'Proprietorship'), ('{CLIENT_B}', '{FIRM}', 'B', 'Proprietorship'),
                ('{CLIENT_OTHER}', '{OTHER_FIRM}', 'Z', 'Proprietorship');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {members};
            INSERT INTO user_client_assignments (firm_id, user_id, client_id)
                 VALUES ('{FIRM}', '{PEOPLE["manager_a"][0]}', '{CLIENT_A}');
            INSERT INTO customers (id, firm_id, client_id, name) VALUES
                ('{CUSTOMER_A}', '{FIRM}', '{CLIENT_A}', 'Cust A'), ('{CUSTOMER_B}', '{FIRM}', '{CLIENT_B}', 'Cust B');
            INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type) VALUES
                ('{AR_A}', '{FIRM}', '{CLIENT_A}', 'AR-1', 'Trade Receivables', 'Asset'),
                ('{SALES_A}', '{FIRM}', '{CLIENT_A}', 'SA-1', 'Sales', 'Asset'),
                ('{AR_B}', '{FIRM}', '{CLIENT_B}', 'AR-2', 'Trade Receivables (B)', 'Asset'),
                ('{SALES_B}', '{FIRM}', '{CLIENT_B}', 'SA-2', 'Sales (B)', 'Asset');
            INSERT INTO client_sales_invoices
                (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status, paid_paise, credited_paise)
                VALUES ('{INVOICE}', '{FIRM}', '{CLIENT_A}', '{CUSTOMER_A}', '{INV_NO}', '{INV_DATE}', 118000, 'draft', 0, 0),
                       ('{INVOICE_B}', '{FIRM}', '{CLIENT_B}', '{CUSTOMER_B}', 'B092-1', '{INV_DATE}', 118000, 'draft', 0, 0);
            DELETE FROM audit_log;
        """)
        assert seed.returncode == 0, seed.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── the call posts and marks ────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("who", ["service", "backend"])
def test_an_issue_posts_the_entry_and_marks_the_invoice_issued_and_linked(dsn, who):
    ok, entry_id = _issue(dsn, who)
    assert ok, entry_id
    status, link, issued_at = _invoice(dsn)
    assert (status, link) == ("issued", entry_id) and issued_at.startswith("2025-09-30 10:00:00")
    assert _entries(dsn) == 1 and _lines_written(dsn) == 2
    assert _rows(dsn, f"SELECT entry_type, source_type, source_id::text, is_posted FROM journal_entries WHERE id = '{entry_id}'") == [
        ["Sales", "sales_invoice", INVOICE, "t"]]


# ── the property the migration exists for ───────────────────────────────────────────────────────────────
def test_a_failure_after_the_posting_takes_the_entry_with_it_and_the_invoice_is_exactly_the_draft_it_was(dsn):
    inject = _psql(dsn, """
        CREATE FUNCTION zz_refuse_issue_fn() RETURNS trigger LANGUAGE plpgsql AS
        $$ BEGIN IF NEW.status = 'issued' THEN RAISE EXCEPTION 'injected failure after the posting'; END IF; RETURN NEW; END $$;
        CREATE TRIGGER zz_refuse_issue BEFORE UPDATE ON client_sales_invoices FOR EACH ROW EXECUTE FUNCTION zz_refuse_issue_fn();""")
    assert inject.returncode == 0, inject.stderr
    before = _invoice(dsn)
    ok, msg = _issue(dsn)
    assert not ok and "injected failure after the posting" in msg, (ok, msg)
    assert _invoice(dsn) == before == ["draft", "-", "-"], "the invoice moved although the call failed"
    assert _entries(dsn) == 0 and _lines_written(dsn) == 0, "an entry (or its lines) was left behind a draft"
    assert _psql(dsn, "DROP TRIGGER zz_refuse_issue ON client_sales_invoices;").returncode == 0
    ok, entry_id = _issue(dsn)
    assert ok, entry_id
    assert _invoice(dsn)[:2] == ["issued", entry_id] and _entries(dsn) == 1


def test_the_closure_refuses_in_the_posting_functions_own_words_and_nothing_is_written(dsn):
    assert _psql(dsn, f"UPDATE firms SET locked_financial_years = ARRAY['2025-26'] WHERE id = '{FIRM}'").returncode == 0
    ok, msg = _issue(dsn)
    assert not ok and "locked" in msg, (ok, msg)
    assert _invoice(dsn)[:2] == ["draft", "-"] and _entries(dsn) == 0


# ── the draft's state ───────────────────────────────────────────────────────────────────────────────────
def test_an_invoice_that_is_not_a_draft_is_refused_and_nothing_more_is_posted(dsn):
    ok, entry_id = _issue(dsn)
    assert ok, entry_id
    for _ in range(2):
        ok, msg = _issue(dsn)
        assert not ok and "is issued and not a draft" in msg, (ok, msg)
    assert _entries(dsn) == 1 and _lines_written(dsn) == 2 and _invoice(dsn)[:2] == ["issued", entry_id]


def test_the_refusal_for_a_non_draft_carries_the_state_the_api_reads_it_by(dsn):
    assert _psql(dsn, f"UPDATE client_sales_invoices SET status = 'cancelled' WHERE id = '{INVOICE}'").returncode == 0
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-v", "VERBOSITY=verbose", "-c",
                        "SELECT public.issue_sales_invoice_atomic('%s'::uuid, '%s'::jsonb, '%s'::jsonb, now());" % (
                            INVOICE, _j(_entry()), _j(_lines()))], capture_output=True, text=True)
    assert r.returncode != 0 and "55000" in r.stderr, r.stderr


def test_two_simultaneous_issues_post_once_and_the_second_is_refused_when_it_gets_the_lock(dsn):
    sql = "SELECT public.issue_sales_invoice_atomic('%s'::uuid, '%s'::jsonb, '%s'::jsonb, now());" % (INVOICE, _j(_entry()), _j(_lines()))
    # the first holds the invoice's lock for a few seconds after it has issued (its transaction has not committed yet)
    first = subprocess.Popen(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", f"BEGIN; {sql} SELECT pg_sleep(3); COMMIT;"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.time() + 15
    while time.time() < deadline and _first_is_sleeping_in_its_transaction(dsn) == 0:
        time.sleep(0.1)
    started = time.time()
    ok, msg = _call(dsn, "service", sql)
    waited = time.time() - started
    out1, err1 = first.communicate(timeout=30)
    assert first.returncode == 0, err1
    assert not ok and "not a draft" in msg, (ok, msg)
    assert waited >= 1.0, f"the second issue did not wait for the first's lock ({waited:.2f}s)"
    assert _entries(dsn) == 1 and _lines_written(dsn) == 2 and _invoice(dsn)[0] == "issued"


def _first_is_sleeping_in_its_transaction(dsn: str) -> int:
    """Once a session is waiting in `pg_sleep`, the function before it has run and its transaction, which holds the invoice's lock,
    is still open: the second session is started only then, so it is the one that has to wait."""
    return int(_one(dsn, "SELECT count(*) FROM pg_stat_activity WHERE wait_event = 'PgSleep' AND pid <> pg_backend_pid()"))


# ── the entry must be this invoice's own ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("label,over", [
    ("another reference", {"reference_no": "SOMETHING-ELSE"}),
    ("another date", {"entry_date": "2025-10-01"}),
    ("another source", {"source_id": INVOICE_B}),
    ("no source", {"source_id": None}),
    ("another source type", {"source_type": "purchase_bill"}),
    ("another entry type", {"entry_type": "Journal"}),
    ("a draft entry", {"is_posted": False}),
])
def test_an_entry_that_is_not_the_invoices_own_is_refused_and_nothing_is_written(dsn, label, over):
    ok, msg = _issue(dsn, entry=_entry(**over))
    assert not ok and "not the posted Sales entry of this invoice" in msg, (label, ok, msg)
    assert _invoice(dsn)[:2] == ["draft", "-"] and _entries(dsn, over.get("reference_no", INV_NO)) == 0 and _lines_written(dsn) == 0, label


def test_an_invoice_of_another_client_of_the_firm_is_not_this_clients_and_is_refused(dsn):
    ok, msg = _issue(dsn, invoice=INVOICE_B)                         # the entry names client A; the invoice is client B's
    assert not ok and "is not an invoice of this client" in msg, (ok, msg)
    assert _invoice(dsn, INVOICE_B)[:2] == ["draft", "-"] and _lines_written(dsn) == 0


@pytest.mark.parametrize("label,over", [
    ("a client of another firm", {"client_id": CLIENT_OTHER}),
    ("a firm that is not the clients", {"firm_id": OTHER_FIRM}),
])
def test_a_privileged_call_must_name_a_client_of_its_firm(dsn, label, over):
    ok, msg = _issue(dsn, entry=_entry(**over))
    assert not ok and "is not a client of firm" in msg, (label, ok, msg)
    assert _lines_written(dsn) == 0


# ── what the posting hands back must be this invoice's ──────────────────────────────────────────────────
def test_an_entry_of_another_document_under_the_same_number_and_date_is_not_taken_for_the_invoices(dsn):
    """`post_journal_atomic` returns whatever live entry sits under the firm, client, reference and date, and the unique index ignores the
    entry's type and source. Marking the invoice issued against another document's entry would link it to the wrong thing."""
    foreign = _psql(dsn, f"SET ROLE service_role; SELECT public.post_journal_atomic('{_j(_entry(entry_type='Journal', source_type=None, source_id=None))}'::jsonb, "
                         f"'{_j(_lines())}'::jsonb);")
    assert foreign.returncode == 0, foreign.stderr
    ok, msg = _issue(dsn)
    assert not ok and "not this invoice's own posted Sales entry" in msg, (ok, msg)
    assert _invoice(dsn)[:2] == ["draft", "-"] and _entries(dsn) == 1 and _lines_written(dsn) == 2, "only the other document's entry exists"


def test_a_removed_draft_is_refused_as_no_longer_a_draft(dsn):
    assert _psql(dsn, f"UPDATE client_sales_invoices SET deleted_at = now() WHERE id = '{INVOICE}'").returncode == 0
    ok, msg = _issue(dsn)
    assert not ok and "has been removed" in msg, (ok, msg)
    assert _entries(dsn) == 0 and _lines_written(dsn) == 0


# ── a draft an earlier issue stranded ───────────────────────────────────────────────────────────────────
def test_a_stranded_draft_is_finished_against_the_entry_it_left_and_not_posted_twice(dsn):
    stranded = _psql(dsn, f"""
        SET ROLE service_role;
        SELECT public.post_journal_atomic('{_j(_entry())}'::jsonb, '{_j(_lines())}'::jsonb);""")
    assert stranded.returncode == 0, stranded.stderr
    assert _invoice(dsn)[:2] == ["draft", "-"] and _entries(dsn) == 1, "the premise: a live entry behind a draft"
    left = _one(dsn, f"SELECT id FROM journal_entries WHERE reference_no = '{INV_NO}'")
    ok, entry_id = _issue(dsn)
    assert ok and entry_id == left, (ok, entry_id, left)
    assert _invoice(dsn)[:2] == ["issued", left] and _entries(dsn) == 1 and _lines_written(dsn) == 2


# ── the person travels ──────────────────────────────────────────────────────────────────────────────────
def test_a_call_that_names_the_person_writes_the_invoices_audit_row_as_that_person(dsn):
    ok, entry_id = _issue(dsn, entry=_entry(audit_actor=PEOPLE["manager_a"][1]))
    assert ok, entry_id
    rows = _rows(dsn, f"SELECT action, actor_id::text, coalesce(metadata->>'actor_source', '-') FROM audit_log "
                      f"WHERE entity_type = 'client_sales_invoice' AND entity_id = '{INVOICE}'")
    assert rows == [["update", PEOPLE["manager_a"][1], "carried"]], rows


def test_a_call_that_names_nobody_writes_no_audit_row_for_the_invoice_and_still_issues(dsn):
    ok, entry_id = _issue(dsn)
    assert ok, entry_id
    assert _rows(dsn, f"SELECT 1 FROM audit_log WHERE entity_type = 'client_sales_invoice' AND entity_id = '{INVOICE}'") == []


# ── who can call it, and the shape ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("who", ["partner", "manager_a", "anon"])
def test_nobody_signed_in_can_call_it(dsn, who):
    ok, msg = _issue(dsn, who)
    assert not ok and "permission denied for function issue_sales_invoice_atomic" in msg, (who, msg)
    assert _invoice(dsn)[:2] == ["draft", "-"] and _lines_written(dsn) == 0


def test_the_grants_are_the_servers_alone(dsn):
    acl = {r: _one(dsn, f"SELECT has_function_privilege('{r}', '{FN}'::regprocedure, 'EXECUTE')") == "t"
           for r in ("anon", "authenticated", "service_role")}
    assert acl == {"anon": False, "authenticated": False, "service_role": True}


def test_the_signed_in_branch_is_still_there_if_the_grant_is_handed_back(dsn):
    """The wrapper keeps asking who is calling, as 546 left the ledger functions: a restored grant meets the same questions."""
    assert _psql(dsn, f"GRANT EXECUTE ON FUNCTION {FN} TO authenticated; "
                      "GRANT EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) TO authenticated;").returncode == 0
    ok, msg = _issue(dsn, "partner", entry=_entry(client_id=CLIENT_B, source_id=INVOICE_B, reference_no="B092-1"), invoice=INVOICE_B,
                     lines=_lines(ar=AR_B, sales=SALES_B))
    assert ok, msg                                                       # a Partner reaches every client of their firm
    ok, msg = _issue(dsn, "manager_a", entry=_entry(client_id=CLIENT_B, source_id=INVOICE_B, reference_no="B092-1"), invoice=INVOICE_B,
                     lines=_lines(ar=AR_B, sales=SALES_B))
    assert not ok and "not a draft" not in msg, "a Manager not assigned to client B was not refused for reach: " + msg


def _whole(dsn: str, sql: str) -> str:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _spoil(dsn: str, old: str, new: str) -> None:
    body = _whole(dsn, f"SELECT pg_get_functiondef('{FN}'::regprocedure)")
    assert old in body, old
    assert _psql(dsn, body.replace(old, new, 1)).returncode == 0


def _closing_check_alone() -> str:
    sql = MIGRATION.read_text(encoding="utf-8")
    return sql[sql.rindex("DO $$"):]


@pytest.mark.parametrize("old,new", [
    ("FOR UPDATE", ""),
    ("public.post_journal_atomic(p_entry, p_lines)", "NULL::uuid"),
    ("PERFORM public.assert_caller_acts_for('issue_sales_invoice_atomic', v_firm, v_client,\n        '[[\"accounting\",\"write\",\"Manager\"]]'::jsonb);", ""),
])
def test_the_closing_check_catches_each_spoiling(dsn, old, new):
    check = _closing_check_alone()
    assert _psql(dsn, check).returncode == 0, "the closing check fails on the migrated definition"
    _spoil(dsn, old, new)
    r = _psql(dsn, check)
    assert r.returncode != 0 and "migration 577" in r.stderr, (old, r.stderr)


def test_the_closing_check_catches_a_grant_handed_to_a_signed_in_role(dsn):
    assert _psql(dsn, f"GRANT EXECUTE ON FUNCTION {FN} TO authenticated;").returncode == 0
    r = _psql(dsn, _closing_check_alone())
    assert r.returncode != 0 and "executable by a signed-in user" in r.stderr


def test_the_rollback_drops_the_function_and_a_reapply_gives_it_back(dsn):
    assert _psql_file(dsn, ROLLBACK).returncode == 0
    assert _one(dsn, "SELECT count(*) FROM pg_proc WHERE proname = 'issue_sales_invoice_atomic'") == "0"
    ok, msg = _issue(dsn)
    assert not ok and "does not exist" in msg
    assert _psql_file(dsn, MIGRATION).returncode == 0
    ok, entry_id = _issue(dsn)
    assert ok, entry_id
    assert _psql_file(dsn, MIGRATION).returncode == 0, "the migration is not idempotent"
