"""A posting into a closed year is refused by the two database functions that write the ledger (migration 533, POST-A-316).

WHAT WAS WRONG
    The posting kernel in the API asks `period_closure_reason` before every posting. The two database functions the ledger is
    actually written through did not ask it: `post_journal_atomic` (a SECURITY DEFINER function every signed-in user may call
    with their own token) and `settle_receipt_atomic` (migration 486's guarded wrapper, which the API's plain rupee customer
    receipt posts through and the kernel never sees). So a receipt dated inside a year the CA had finalised was accepted for
    everyone, and a signed-in person could call either function directly and post a dated entry into a closed year. And
    `post_journal_atomic` was the one definer function migration 486 did not wrap with a role-pair check, so a Reviewer
    assigned to a client, whom the API refuses on every route that posts, could post.

WHAT THIS HOLDS (real Postgres, as each person, through the wrapper's real grants)
    * BOTH FUNCTIONS REFUSE A CLOSED YEAR: the client's finalised year-end and the firm's locked year, for a Partner, an
      assigned Manager and an assigned Executive, for the service role and for a connection with no JWT (the backend), with the
      closure's own sentence; and admit an open year of the same client, the year after a closed one, and another client's open
      year on the same date while this client's own is closed (and refuse the other client's closed year on a date open here).
    * NOTHING IS WRITTEN WHEN IT REFUSES: no entry, no line, no receipt, no allocation, the invoice and the original entry
      untouched (a reversal refused for its date does not stamp the original).
    * THE ROLE PAIR: a Reviewer and a Client-role member, however assigned, are refused even on an open day; an Executive is
      admitted (banking writes are theirs); an unassigned Manager, a suspended Partner and a Partner of
      another firm are refused; the per-person grid counts both ways (a Reviewer granted a pair is admitted, an Executive denied
      banking:write is refused, a Manager denied it still posts through accounting:write; each of the six pairs is live and eleven
      pairs that guard something else admit nobody).
    * THE DATE: an unreadable or missing date is a refusal and not a reason to skip the check; an empty payload keeps the old
      sentence; a duplicate in an open year still answers with the existing entry.
    * THE SHAPE: the original name is the SECURITY DEFINER wrapper executable by signed-in users and the service role and not
      by `anon`; `__unguarded` is the service role's alone and carries migration 418's body unchanged; the receipt wrapper is
      migration 486's with the closure block added and nothing else changed.
    * THE ROLLBACK restores the previous functions exactly, and with it the defect is reproduced (a signed-in Partner posts into
      the finalised year; a Reviewer posts); a re-apply closes both again.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the closed-year proof requires HARNESS_PG + psql",
)

FIRM = "53300000-0000-0000-0000-000000000001"
OTHER_FIRM = "53300000-0000-0000-0000-000000000002"
CLIENT_A = "53300000-0000-0000-0000-0000000000a1"
CLIENT_B = "53300000-0000-0000-0000-0000000000b2"
INTERNAL = "53300000-0000-0000-0000-0000000000c3"
CUSTOMER_A = "53300000-0000-0000-0000-0000000000d1"
BANK_A, AR_A = "53300000-0000-0000-0000-0000000000a5", "53300000-0000-0000-0000-0000000000a6"
BANK_B, AR_B = "53300000-0000-0000-0000-0000000000b5", "53300000-0000-0000-0000-0000000000b6"
INVOICE_A = "53300000-0000-0000-0000-0000000000e1"
PEOPLE = {            # name: (users.id, auth id, role, firm, active)
    "partner": ("53300000-0000-0000-0000-00000000000a", "53300000-1111-0000-0000-000000000001", "Partner", FIRM, True),
    "manager_a": ("53300000-0000-0000-0000-00000000000b", "53300000-1111-0000-0000-000000000002", "Manager", FIRM, True),
    "manager_none": ("53300000-0000-0000-0000-00000000000c", "53300000-1111-0000-0000-000000000003", "Manager", FIRM, True),
    "executive_a": ("53300000-0000-0000-0000-00000000000e", "53300000-1111-0000-0000-000000000004", "Executive", FIRM, True),
    "reviewer_a": ("53300000-0000-0000-0000-000000000011", "53300000-1111-0000-0000-000000000007", "Reviewer", FIRM, True),
    "client_a": ("53300000-0000-0000-0000-000000000012", "53300000-1111-0000-0000-000000000008", "Client", FIRM, True),
    "suspended": ("53300000-0000-0000-0000-00000000000f", "53300000-1111-0000-0000-000000000005", "Partner", FIRM, False),
    "other_firm": ("53300000-0000-0000-0000-000000000010", "53300000-1111-0000-0000-000000000006", "Partner", OTHER_FIRM, True),
}
STRANGER = "53300000-1111-0000-0000-0000000000ff"          # authenticated, no users row (an employee, a portal contact)

# Client A: its 2024-25 year is finalised; the firm has locked 2023-24 for everyone; 2025-26 is open.
# Client B: its 2025-26 year is finalised; 2024-25 is open.
FINALISED_A = "2024-09-30"
FIRM_LOCKED = "2023-09-30"
OPEN = "2025-09-30"
CLOSED_A = "is closed for this client"
LOCKED = "is locked"
MIGRATION = next(p for p in MIGRATIONS.glob("533_a_posting_into_a_closed_year_is_refused_by_the_two_ledger_functions_that_never_asked*.sql")
                 if not p.name.endswith("_rollback.sql"))
ROLLBACK = next(MIGRATIONS.glob("533_a_posting_into_a_closed_year_is_refused_by_the_two_ledger_functions_that_never_asked*_rollback.sql"))
M486 = next(p for p in MIGRATIONS.glob("486_*.sql") if not p.name.endswith("_rollback.sql"))
POST = "public.post_journal_atomic(jsonb, jsonb)"
POST_RAW = "public.post_journal_atomic__unguarded(jsonb, jsonb)"
SETTLE = "public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb)"
SETTLE_RAW = "public.settle_receipt_atomic__unguarded(jsonb, jsonb, jsonb, jsonb)"


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
    """`who` is a name in PEOPLE, `stranger`, `service` (the service role) or `backend` (a connection with no JWT)."""
    if who == "backend":
        return ""
    if who == "service":
        return "SET ROLE service_role; "
    sub = STRANGER if who == "stranger" else PEOPLE[who][1]
    return f"SET request.jwt.claims = '{{\"sub\": \"{sub}\", \"role\": \"authenticated\"}}'; SET ROLE authenticated; "


def _call(dsn: str, who: str, select: str) -> tuple[bool, str]:
    """Run one `SELECT <call>` as `who`: (True, result) or (False, the database's message)."""
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _prefix(who) + select],
                       capture_output=True, text=True)
    if r.returncode != 0:
        m = re.search(r"ERROR:\s+(.*)", r.stderr)
        return False, (m.group(1) if m else r.stderr).strip()
    out = [l for l in r.stdout.splitlines() if l.strip() and l.strip() != "SET"]
    return True, (out[-1].strip() if out else "")


def _entry(client: str, day: str, ref: str, **extra) -> dict:
    return {"firm_id": FIRM, "client_id": client, "entry_date": day, "reference_no": ref, "narration": "t",
            "entry_type": "Journal", "is_posted": True, "status": "posted", **extra}


def _lines(client: str, paise: int = 10000) -> list[dict]:
    bank, ar = (BANK_A, AR_A) if client == CLIENT_A else (BANK_B, AR_B)
    return [{"account_id": bank, "debit_paise": paise, "credit_paise": 0, "narration": "d"},
            {"account_id": ar, "debit_paise": 0, "credit_paise": paise, "narration": "c"}]


def _post(dsn: str, who: str, client: str, day: str, ref: str, *, fn: str = "public.post_journal_atomic", **extra) -> tuple[bool, str]:
    e, ls = json.dumps(_entry(client, day, ref, **extra)).replace("'", "''"), json.dumps(_lines(client)).replace("'", "''")
    return _call(dsn, who, f"SELECT {fn}('{e}'::jsonb, '{ls}'::jsonb);")


def _settle(dsn: str, who: str, client: str, day: str, ref: str, *, receipt_day: str | None = None,
            allocated: int = 10000) -> tuple[bool, str]:
    receipt = {"id": str(uuid.uuid4()), "firm_id": FIRM, "client_id": client, "customer_id": CUSTOMER_A, "receipt_no": ref,
               "receipt_date": day if receipt_day is None else receipt_day, "amount_paise": 10000, "tds_paise": 0,
               "unallocated_paise": 10000 - allocated, "payment_mode": "bank", "reference_no": "", "notes": ""}
    alloc = [{"sales_invoice_id": INVOICE_A, "allocated_paise": allocated}] if allocated else []
    p = [json.dumps(x).replace("'", "''") for x in (receipt, _entry(client, day, ref, entry_type="Receipt"), _lines(client), alloc)]
    return _call(dsn, who, f"SELECT public.settle_receipt_atomic('{p[0]}'::jsonb, '{p[1]}'::jsonb, '{p[2]}'::jsonb, '{p[3]}'::jsonb);")


def _text(dsn: str, sql: str) -> str:
    """A multi-line value (a function body) whole, which `_one` would cut at its first line."""
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.rstrip("\n")


def _count(dsn: str, table: str, where: str) -> int:
    return int(_one(dsn, f"SELECT count(*) FROM {table} WHERE {where}"))


def _written(dsn: str, ref: str) -> int:
    return _count(dsn, "journal_entries", f"reference_no = '{ref}'")


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e533_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r, _f, _act) in PEOPLE.items()) + f", ('{STRANGER}', 'employee@t.in')"
        members = ", ".join(f"('{i}', '{f}', '{a}', '{n}@t.in', '{n}', '{r}', {str(act).lower()})"
                            for n, (i, a, r, f, act) in PEOPLE.items())
        seed = _psql(d, f"""
            INSERT INTO auth.users (id, email) VALUES {auth};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
                 VALUES ('{CLIENT_A}', '{FIRM}', 'A', 'Proprietorship'), ('{CLIENT_B}', '{FIRM}', 'B', 'Proprietorship');
            INSERT INTO clients (id, firm_id, client_name, entity_type, is_internal)
                 VALUES ('{INTERNAL}', '{FIRM}', 'The practice', 'Proprietorship', true);
            UPDATE firms SET internal_client_id = '{INTERNAL}', locked_financial_years = ARRAY['2023-24'] WHERE id = '{FIRM}';
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {members};
            INSERT INTO user_client_assignments (firm_id, user_id, client_id)
                 VALUES ('{FIRM}', '{PEOPLE["manager_a"][0]}', '{CLIENT_A}'),
                        ('{FIRM}', '{PEOPLE["executive_a"][0]}', '{CLIENT_A}'),
                        ('{FIRM}', '{PEOPLE["reviewer_a"][0]}', '{CLIENT_A}'),
                        ('{FIRM}', '{PEOPLE["client_a"][0]}', '{CLIENT_A}');
            INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER_A}', '{FIRM}', '{CLIENT_A}', 'Cust');
            INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type) VALUES
                ('{BANK_A}', '{FIRM}', '{CLIENT_A}', 'BANK-1', 'Bank Account', 'Asset'),
                ('{AR_A}', '{FIRM}', '{CLIENT_A}', 'AR-1', 'Trade Receivables', 'Asset'),
                ('{BANK_B}', '{FIRM}', '{CLIENT_B}', 'BANK-2', 'Bank Account B', 'Asset'),
                ('{AR_B}', '{FIRM}', '{CLIENT_B}', 'AR-2', 'Trade Receivables B', 'Asset');
            INSERT INTO client_sales_invoices
                (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status, paid_paise, credited_paise)
                VALUES ('{INVOICE_A}', '{FIRM}', '{CLIENT_A}', '{CUSTOMER_A}', 'SINV-1', '2024-04-01', 100000, 'issued', 0, 0);
            INSERT INTO client_year_locks (firm_id, client_id, financial_year, reason)
                 VALUES ('{FIRM}', '{CLIENT_A}', '2024-25', 'test'), ('{FIRM}', '{CLIENT_B}', '2025-26', 'test');
        """)
        assert seed.returncode == 0, seed.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── THE SHAPE ───────────────────────────────────────────────────────────────────

def _acl(dsn: str, sig: str) -> dict[str, bool]:
    return {r: _one(dsn, f"SELECT has_function_privilege('{r}', '{sig}'::regprocedure, 'EXECUTE')") == "t"
            for r in ("anon", "authenticated", "service_role")}


def test_the_original_names_are_the_definer_wrappers_and_the_originals_are_the_service_roles(dsn):
    for sig, raw in ((POST, POST_RAW), (SETTLE, SETTLE_RAW)):
        assert _one(dsn, f"SELECT prosecdef FROM pg_proc WHERE oid = '{sig}'::regprocedure") == "t"
        assert _one(dsn, f"SELECT prosecdef FROM pg_proc WHERE oid = '{raw}'::regprocedure") == "t"
        assert _acl(dsn, sig) == {"anon": False, "authenticated": True, "service_role": True}, sig
        assert _acl(dsn, raw) == {"anon": False, "authenticated": False, "service_role": True}, raw
    for sig in (POST, SETTLE):
        body = _text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{sig}'::regprocedure")
        assert "period_closure_reason" in body and "assert_caller_acts_for" in body, sig


def _normalise(sql: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", sql)).strip()


def _body(sql_file: Path, name: str, *, exclude: str = "") -> str:
    text = sql_file.read_text()
    m = re.search(rf"CREATE (?:OR REPLACE )?FUNCTION public\.{name}\(.*?\n(\$\w*\$)(?:;|\n)", text, re.S)
    assert m, f"{sql_file.name} does not define {name}"
    block = m.group(0)
    return _normalise(block.split(m.group(1), 1)[1].rsplit(m.group(1), 1)[0])


def test_the_unguarded_post_function_is_the_body_the_last_defining_migration_wrote(dsn):
    """Derived by scanning the migration directory, so it cannot be pointed at a stale ancestor: the highest-numbered
    migration that defines the original name (not a rollback, not this one)."""
    definers = sorted(p for p in MIGRATIONS.glob("*.sql")
                      if not p.name.endswith("_rollback.sql") and p.name < MIGRATION.name       # (migrations after 533 redefine the wrapper, not this body)
                      and re.search(r"FUNCTION\s+public\.post_journal_atomic\s*\(", p.read_text()))
    last = definers[-1]
    assert last.name.startswith("418_"), f"the last definer of post_journal_atomic is now {last.name}: derive from it"
    live = _normalise(_text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{POST_RAW}'::regprocedure"))
    assert live == _body(last, "post_journal_atomic")


def test_the_receipt_wrapper_is_migration_486s_with_the_closure_block_added_and_nothing_else_changed(dsn):
    live = _text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{SETTLE}'::regprocedure")
    stripped = re.sub(r"-- THE CLOSURE \(migration 533\).*?END LOOP;\n", "", live, flags=re.S)
    stripped = stripped.replace("    v_reason text;\n    v_date   text;\n    v_day    date;\n", "    -- (nothing to declare)\n")
    assert stripped != live, "the closure block was not found"
    stripped = re.sub(r"    -- MIGRATION 545:.*?    PERFORM public\.carry_audit_actor\([^\n]*\n", "", stripped, flags=re.S)           # migration 545: the audit actor carried
    stripped = stripped.replace(" - 'audit_actor'", "")                              # ...and the reserved payload key removed again
    assert _normalise(stripped) == _body(M486, "settle_receipt_atomic")


# ── THE CLOSED YEAR, FOR EVERY PERSON WHO MAY POST ───────────────────────────────

@pytest.mark.parametrize("who", ["partner", "manager_a", "executive_a", "service", "backend"])
def test_post_journal_atomic_refuses_a_finalised_year_and_the_firm_locked_year_and_admits_an_open_one(dsn, who):
    ok, msg = _post(dsn, who, CLIENT_A, FINALISED_A, f"CL-{who}-1")
    assert not ok and CLOSED_A in msg and "2024-25" in msg, (who, msg)
    ok, msg = _post(dsn, who, CLIENT_A, FIRM_LOCKED, f"CL-{who}-2")
    assert not ok and "2023-24" in msg and LOCKED in msg, (who, msg)
    assert _written(dsn, f"CL-{who}-1") == 0 and _written(dsn, f"CL-{who}-2") == 0
    ok, msg = _post(dsn, who, CLIENT_A, OPEN, f"CL-{who}-3")
    assert ok and re.fullmatch(r"[0-9a-f-]{36}", msg), (who, msg)
    assert _written(dsn, f"CL-{who}-3") == 1 and _count(dsn, "journal_lines", f"journal_entry_id = '{msg}'") == 2


@pytest.mark.parametrize("who", ["partner", "service", "backend"])
def test_one_clients_closed_year_is_not_another_clients(dsn, who):
    """A's finalised year is 2024-25 and B's is 2025-26: the same two dates, opposite answers, per client."""
    assert _post(dsn, who, CLIENT_B, FINALISED_A, f"PC-{who}-1")[0], "B's 2024-25 is open"
    ok, msg = _post(dsn, who, CLIENT_B, OPEN, f"PC-{who}-2")
    assert not ok and CLOSED_A in msg and "2025-26" in msg, msg
    assert _post(dsn, who, CLIENT_A, OPEN, f"PC-{who}-3")[0], "A's 2025-26 is open"
    ok, msg = _post(dsn, who, CLIENT_A, FINALISED_A, f"PC-{who}-4")
    assert not ok and "2024-25" in msg
    assert _post(dsn, who, CLIENT_A, "2026-03-31", f"PC-{who}-5")[0], "the last day of the open year"
    assert not _post(dsn, who, CLIENT_A, "2025-03-31", f"PC-{who}-6")[0], "the last day of the finalised year"
    assert _post(dsn, who, CLIENT_A, "2025-04-01", f"PC-{who}-7")[0], "the day after it"


@pytest.mark.parametrize("who", ["partner", "manager_a", "executive_a", "service", "backend"])
def test_settle_receipt_atomic_refuses_a_finalised_year_and_the_firm_locked_year_and_admits_an_open_one(dsn, who):
    ok, msg = _settle(dsn, who, CLIENT_A, FINALISED_A, f"RC-{who}-1")
    assert not ok and CLOSED_A in msg and "2024-25" in msg, (who, msg)
    ok, msg = _settle(dsn, who, CLIENT_A, FIRM_LOCKED, f"RC-{who}-2")
    assert not ok and "2023-24" in msg and LOCKED in msg, (who, msg)
    for ref in (f"RC-{who}-1", f"RC-{who}-2"):
        assert _written(dsn, ref) == 0 and _count(dsn, "receipts", f"receipt_no = '{ref}'") == 0
    assert _count(dsn, "receipt_allocations", "true") == 0
    assert _one(dsn, f"SELECT paid_paise FROM client_sales_invoices WHERE id = '{INVOICE_A}'") == "0"
    ok, msg = _settle(dsn, who, CLIENT_A, OPEN, f"RC-{who}-3")
    assert ok, (who, msg)
    assert _written(dsn, f"RC-{who}-3") == 1 and _count(dsn, "receipts", f"receipt_no = 'RC-{who}-3'") == 1
    assert _one(dsn, f"SELECT paid_paise FROM client_sales_invoices WHERE id = '{INVOICE_A}'") == "10000"


def test_a_receipt_is_refused_when_either_of_its_two_dates_is_in_a_closed_year(dsn):
    """The journal's date and the receipt's own date are each asked: a payload whose journal is dated in an open year and
    whose receipt is dated inside the finalised one, or the reverse, is refused."""
    ok, msg = _settle(dsn, "partner", CLIENT_A, OPEN, "TWO-1", receipt_day=FINALISED_A)
    assert not ok and CLOSED_A in msg, msg
    ok, msg = _settle(dsn, "partner", CLIENT_A, FINALISED_A, "TWO-2", receipt_day=OPEN)
    assert not ok and CLOSED_A in msg, msg
    assert _written(dsn, "TWO-1") == 0 and _written(dsn, "TWO-2") == 0
    assert _count(dsn, "receipts", "receipt_no IN ('TWO-1', 'TWO-2')") == 0


def test_a_receipt_with_no_allocations_is_refused_in_a_closed_year_too(dsn):
    ok, msg = _settle(dsn, "executive_a", CLIENT_A, FINALISED_A, "NOA-1", allocated=0)
    assert not ok and CLOSED_A in msg, msg
    assert _settle(dsn, "executive_a", CLIENT_A, OPEN, "NOA-2", allocated=0)[0]


# ── A FILED RETURN IS NOT A CLOSURE ───────────────────────────────────────────────

def test_a_posting_dated_in_a_month_whose_return_is_filed_is_admitted_by_both_functions(dsn):
    """The kernel deliberately asks the closures and not the filed-return branch (migration 361's header: June's bank
    reconciliation happens after June's returns are filed, every month, for every client). These two functions are the
    kernel's and the receipt's database half, so a filed GSTR-1 covering the date must not stop them."""
    assert _psql(dsn, f"""INSERT INTO filings (client_id, firm_id, filing_type, period_start, period_end, filed_date, status)
                          VALUES ('{CLIENT_A}', '{FIRM}', 'gstr1', '2025-09-01', '2025-09-30', '2025-10-11', 'filed');""").returncode == 0
    assert _one(dsn, f"SELECT public.period_lock_reason('{FIRM}', '{CLIENT_A}', '{OPEN}'::date) IS NOT NULL") == "t", \
        "the fixture is wrong: the filed return must close the date for the documents that feed a return"
    assert _one(dsn, f"SELECT public.period_closure_reason('{FIRM}', '{CLIENT_A}', '{OPEN}'::date) IS NULL") == "t"
    for who in ("partner", "executive_a", "service"):
        assert _post(dsn, who, CLIENT_A, OPEN, f"FILED-{who}")[0], who
        assert _settle(dsn, who, CLIENT_A, OPEN, f"FILEDR-{who}", allocated=0)[0], who


SIX_PAIRS = [("banking", "write"), ("accounting", "write"), ("client", "write"), ("year_end", "approve"),
             ("accounting", "approve"), ("payroll", "finalize")]


@pytest.mark.parametrize("pair", SIX_PAIRS)
def test_each_pair_in_the_list_is_live_a_reviewer_granted_only_that_pair_may_post(dsn, pair):
    """Each of the six pairs admits a person who holds only it (a Reviewer has none by role), so a pair that is mistyped or
    dropped from the list is noticed, which the union semantics would otherwise hide behind the other five."""
    assert not _post(dsn, "reviewer_a", CLIENT_A, OPEN, "PAIR-0")[0]
    assert _psql(dsn, f"INSERT INTO user_permissions (firm_id, user_id, resource, action, granted) "
                      f"VALUES ('{FIRM}', '{PEOPLE['reviewer_a'][0]}', '{pair[0]}', '{pair[1]}', true);").returncode == 0
    ok, msg = _post(dsn, "reviewer_a", CLIENT_A, OPEN, f"PAIR-{pair[0]}-{pair[1]}")
    assert ok, (pair, msg)


@pytest.mark.parametrize("pair", [("invoice", "write"), ("year_end", "write"), ("payroll", "write"), ("billing", "write"),
                                  ("banking", "approve"), ("report", "write"), ("task", "write"), ("document", "approve"),
                                  ("gst", "compute"), ("tds", "compute"), ("income_tax", "compute")])
def test_a_pair_that_guards_something_else_does_not_admit_a_reviewer(dsn, pair):
    """The first reading of the routes over-collected: invoice:write guards SENDING a document, year_end:write drafting an
    adjustment, payroll:write the payroll masters, billing:write fee billing and banking:approve a reconciliation adjustment,
    and none of them posts. A person holding one of them and none of the six must be refused."""
    assert _psql(dsn, f"INSERT INTO user_permissions (firm_id, user_id, resource, action, granted) "
                      f"VALUES ('{FIRM}', '{PEOPLE['reviewer_a'][0]}', '{pair[0]}', '{pair[1]}', true);").returncode == 0
    ok, msg = _post(dsn, "reviewer_a", CLIENT_A, OPEN, f"NOPAIR-{pair[0]}-{pair[1]}")
    assert not ok and "does not allow this" in msg, (pair, msg)


# ── THE ROLE PAIR ────────────────────────────────────────────────────────────────

REFUSED_WHO = ("does not allow this|not the caller's firm|no live user record|not one the caller can reach|"
               "no signed-in person|only a Partner may act")


@pytest.mark.parametrize("who", ["reviewer_a", "client_a"])
def test_a_reviewer_and_a_client_role_member_cannot_post_even_into_an_open_year(dsn, who):
    ok, msg = _post(dsn, who, CLIENT_A, OPEN, f"RV-{who}")
    assert not ok and "does not allow this" in msg, (who, msg)
    assert _written(dsn, f"RV-{who}") == 0
    ok, msg = _settle(dsn, who, CLIENT_A, OPEN, f"RVS-{who}")
    assert not ok and "does not allow this" in msg, (who, msg)
    assert _written(dsn, f"RVS-{who}") == 0 and _count(dsn, "receipts", f"receipt_no = 'RVS-{who}'") == 0


@pytest.mark.parametrize("who", ["manager_none", "suspended", "other_firm", "stranger"])
def test_a_person_who_cannot_reach_the_client_or_the_firm_cannot_post(dsn, who):
    ok, msg = _post(dsn, who, CLIENT_A, OPEN, f"NR-{who}")
    assert not ok and re.search(REFUSED_WHO, msg), (who, msg)
    assert _written(dsn, f"NR-{who}") == 0


def test_the_internal_practice_is_a_partners(dsn):
    ok, msg = _post(dsn, "manager_a", INTERNAL, OPEN, "INT-1", fn="public.post_journal_atomic")
    assert not ok and re.search(REFUSED_WHO, msg), msg


def _deny(dsn: str, who: str, *pairs: tuple[str, str]) -> None:
    uid = PEOPLE[who][0]
    rows = ", ".join(f"('{FIRM}', '{uid}', '{r}', '{a}', false)" for r, a in pairs)
    assert _psql(dsn, f"INSERT INTO user_permissions (firm_id, user_id, resource, action, granted) VALUES {rows};").returncode == 0


def test_the_per_person_grid_counts_in_both_directions(dsn):
    # An Executive's only pair by role is banking:write: denied it, they are refused. A Manager denied it is still admitted
    # by accounting:write (the union), and denied that as well is refused.
    _deny(dsn, "executive_a", ("banking", "write"))
    ok, msg = _post(dsn, "executive_a", CLIENT_A, OPEN, "GR-1")
    assert not ok and "does not allow this" in msg, msg
    _deny(dsn, "manager_a", ("banking", "write"))
    assert _post(dsn, "manager_a", CLIENT_A, OPEN, "GR-2")[0], "accounting:write is left"
    _deny(dsn, "manager_a", ("accounting", "write"), ("client", "write"), ("year_end", "approve"))
    ok, msg = _post(dsn, "manager_a", CLIENT_A, OPEN, "GR-2b")
    assert not ok and "does not allow this" in msg, msg
    # A Reviewer the Partner has granted accounting:write is admitted to an open year and still refused a closed one.
    uid = PEOPLE["reviewer_a"][0]
    assert _psql(dsn, f"INSERT INTO user_permissions (firm_id, user_id, resource, action, granted) "
                      f"VALUES ('{FIRM}', '{uid}', 'accounting', 'write', true);").returncode == 0
    assert _post(dsn, "reviewer_a", CLIENT_A, OPEN, "GR-3")[0]
    ok, msg = _post(dsn, "reviewer_a", CLIENT_A, FINALISED_A, "GR-4")
    assert not ok and CLOSED_A in msg, msg


def test_an_executive_who_may_settle_a_bank_receipt_still_may(dsn):
    """Migration 486's pair (banking:write) is unchanged by the closure check."""
    assert _settle(dsn, "executive_a", CLIENT_A, OPEN, "EXB-1")[0]


# ── THE DATE, THE PAYLOAD, THE DUPLICATE, THE REVERSAL ────────────────────────────

@pytest.mark.parametrize("bad", ["not-a-date", "2025-13-45", ""])
def test_a_date_that_cannot_be_read_is_a_refusal_not_a_reason_to_skip_the_check(dsn, bad):
    for who in ("partner", "service", "backend"):
        ok, msg = _post(dsn, who, CLIENT_A, bad, f"BD-{who}")
        assert not ok and "is not a posting date" in msg, (who, bad, msg)
        assert _written(dsn, f"BD-{who}") == 0
    ok, msg = _settle(dsn, "partner", CLIENT_A, bad, "BD-S")
    assert not ok and "is not a posting date" in msg, msg
    ok, msg = _settle(dsn, "partner", CLIENT_A, OPEN, "BD-S2", receipt_day=bad)
    assert not ok and "is not a posting date" in msg, msg
    assert _written(dsn, "BD-S") == 0 and _written(dsn, "BD-S2") == 0


def test_a_missing_date_is_a_refusal(dsn):
    e = _entry(CLIENT_A, OPEN, "MD-1")
    del e["entry_date"]
    ok, msg = _call(dsn, "partner", f"SELECT public.post_journal_atomic('{json.dumps(e)}'::jsonb, '{json.dumps(_lines(CLIENT_A))}'::jsonb);")
    assert not ok and "is not a posting date" in msg, msg


@pytest.mark.parametrize("payload", ["'{}'::jsonb", "NULL::jsonb"])
def test_an_empty_payload_keeps_its_old_sentence(dsn, payload):
    for who in ("service", "backend"):
        ok, msg = _call(dsn, who, f"SELECT public.post_journal_atomic({payload}, '[]'::jsonb);")
        assert not ok and "empty entry payload" in msg, (who, msg)


def test_a_duplicate_in_an_open_year_still_answers_with_the_existing_entry(dsn):
    ok1, first = _post(dsn, "partner", CLIENT_A, OPEN, "DUP-1")
    ok2, second = _post(dsn, "partner", CLIENT_A, OPEN, "DUP-1")
    assert ok1 and ok2 and first == second
    assert _written(dsn, "DUP-1") == 1


def test_a_reversal_dated_in_an_open_year_of_an_entry_in_a_closed_year_is_admitted_and_stamps_it(dsn):
    """The remedy the closure's own sentence offers ('post a reversal in an open year')."""
    orig = str(uuid.uuid4())
    assert _psql(dsn, f"""
        INSERT INTO journal_entries (id, firm_id, client_id, entry_date, reference_no, narration, entry_type, is_posted, status)
             VALUES ('{orig}', '{FIRM}', '{CLIENT_A}', '{FINALISED_A}', 'ORIG-1', 'o', 'Journal', true, 'posted');
        INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise)
             VALUES ('{orig}', '{BANK_A}', 10000, 0), ('{orig}', '{AR_A}', 0, 10000);""").returncode == 0
    ok, msg = _post(dsn, "partner", CLIENT_A, OPEN, "REV-OK", reversal_of=orig)
    assert ok, msg
    assert _one(dsn, f"SELECT is_reversed FROM journal_entries WHERE id = '{orig}'") == "t"


def _entry_of(dsn: str, entry_id: str, client: str, day: str, ref: str) -> None:
    assert _psql(dsn, f"""
        INSERT INTO journal_entries (id, firm_id, client_id, entry_date, reference_no, narration, entry_type, is_posted, status)
             VALUES ('{entry_id}', '{FIRM}', '{client}', '{day}', '{ref}', 'o', 'Journal', true, 'posted');
        INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise)
             VALUES ('{entry_id}', '{BANK_A if client == CLIENT_A else BANK_B}', 10000, 0),
                    ('{entry_id}', '{AR_A if client == CLIENT_A else AR_B}', 0, 10000);""").returncode == 0


@pytest.mark.parametrize("who", ["partner", "executive_a", "service", "backend"])
def test_a_reversal_can_only_stamp_an_entry_of_its_own_client(dsn, who):
    """The body flips is_reversed on the entry named in reversal_of for the payload's firm and asked nothing about its client:
    a person assigned to A could hide B's entry from every statement, block its real reversal and free its reference number."""
    theirs = str(uuid.uuid4())
    _entry_of(dsn, theirs, CLIENT_B, FINALISED_A, f"B-ORIG-{who}")          # B's 2024-25 is open, so the entry is B's own
    ok, msg = _post(dsn, who, CLIENT_A, OPEN, f"HIDE-{who}", reversal_of=theirs)
    assert not ok and "not an entry of this client" in msg, (who, msg)
    assert _one(dsn, f"SELECT is_reversed FROM journal_entries WHERE id = '{theirs}'") == "f"
    assert _written(dsn, f"HIDE-{who}") == 0


def test_a_reversal_of_an_entry_of_the_same_client_in_a_closed_year_still_stamps_it(dsn):
    mine = str(uuid.uuid4())
    _entry_of(dsn, mine, CLIENT_A, FINALISED_A, "A-ORIG")
    ok, msg = _post(dsn, "executive_a", CLIENT_A, OPEN, "A-REV", reversal_of=mine)
    assert ok, msg
    assert _one(dsn, f"SELECT is_reversed FROM journal_entries WHERE id = '{mine}'") == "t"


@pytest.mark.parametrize("bad", ["infinity", "-infinity"])
def test_an_infinite_date_is_a_refusal_with_the_posting_date_sentence(dsn, bad):
    for who in ("partner", "service"):
        ok, msg = _post(dsn, who, CLIENT_A, bad, f"INF-{who}")
        assert not ok and "is not a posting date" in msg, (who, bad, msg)
    for kwargs in ({}, {"receipt_day": bad}):
        ok, msg = _settle(dsn, "partner", CLIENT_A, bad if not kwargs else OPEN, f"INFS-{len(kwargs)}", **kwargs)
        assert not ok and "is not a posting date" in msg, (bad, kwargs, msg)


def test_a_reversal_dated_in_the_closed_year_is_refused_and_does_not_stamp_the_original(dsn):
    orig = str(uuid.uuid4())
    assert _psql(dsn, f"""
        INSERT INTO journal_entries (id, firm_id, client_id, entry_date, reference_no, narration, entry_type, is_posted, status)
             VALUES ('{orig}', '{FIRM}', '{CLIENT_A}', '{OPEN}', 'ORIG-2', 'o', 'Journal', true, 'posted');
        INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise)
             VALUES ('{orig}', '{BANK_A}', 10000, 0), ('{orig}', '{AR_A}', 0, 10000);""").returncode == 0
    ok, msg = _post(dsn, "partner", CLIENT_A, FINALISED_A, "REV-NO", reversal_of=orig)
    assert not ok and CLOSED_A in msg, msg
    assert _one(dsn, f"SELECT is_reversed FROM journal_entries WHERE id = '{orig}'") == "f"
    assert _written(dsn, "REV-NO") == 0


def test_the_sentence_is_the_one_the_period_function_gives(dsn):
    """No second wording: the refusal is `period_closure_reason`'s own text, which names the remedy."""
    for day, client in ((FINALISED_A, CLIENT_A), (FIRM_LOCKED, CLIENT_A), (OPEN, CLIENT_B)):
        expected = _one(dsn, f"SELECT public.period_closure_reason('{FIRM}', '{client}', '{day}'::date)")
        assert expected
        # and the API recognises it inside an error message, so a refusal the database gives reaches the person as a 422
        from services.period_lock_service import closure_sentence_in
        assert closure_sentence_in(f"{{'message': '{expected}', 'code': 'P0001'}}") == expected
        assert _post(dsn, "partner", client, day, f"SAME-{day}-{client[-2:]}") == (False, expected)
        assert _settle(dsn, "partner", client, day, f"SAMES-{day}-{client[-2:]}")[1] == expected


# ── THE ROLLBACK, AND THE DEFECT IT BRINGS BACK ───────────────────────────────────

def _definitions(dsn: str) -> dict[str, str]:
    rows = _rows(dsn, """SELECT p.proname, md5(p.prosrc) || ' ' || p.prosecdef::text || ' ' || coalesce(p.proacl::text, '')
                           FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                          WHERE n.nspname = 'public' AND p.proname IN ('post_journal_atomic', 'post_journal_atomic__unguarded',
                                'settle_receipt_atomic', 'settle_receipt_atomic__unguarded') ORDER BY 1""")
    return {r[0]: r[1] for r in rows}


def test_the_rollback_restores_the_previous_functions_and_reproduces_the_defect_and_a_reapply_closes_it(dsn):
    after = _definitions(dsn)
    unguarded_body = _one(dsn, f"SELECT md5(prosrc) FROM pg_proc WHERE oid = '{POST_RAW}'::regprocedure")
    done = _psql_file(dsn, ROLLBACK)
    assert done.returncode == 0, done.stderr
    rolled = _definitions(dsn)
    assert "post_journal_atomic__unguarded" not in rolled
    assert rolled["post_journal_atomic"].split()[0] == unguarded_body, "the original body is back under its own name"
    assert _acl(dsn, POST) == {"anon": False, "authenticated": True, "service_role": True}
    # the previous receipt wrapper is migration 486's, text for text
    live = _normalise(_text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{SETTLE}'::regprocedure"))
    assert live == _body(M486, "settle_receipt_atomic")
    # THE DEFECT, reproduced: a signed-in Partner posts into the finalised year through either function, and a Reviewer posts
    assert _post(dsn, "partner", CLIENT_A, FINALISED_A, "RB-1")[0]
    assert _settle(dsn, "partner", CLIENT_A, FINALISED_A, "RB-2")[0]
    assert _post(dsn, "reviewer_a", CLIENT_A, OPEN, "RB-3")[0]
    # re-apply: both close again and the definitions are exactly what they were. The migrations after 533 that redefine the wrappers
    # (545 carries the audit actor) are applied again, in order, because 533's own re-apply gives back 533's text alone.
    done = _psql_file(dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    later = sorted(p for p in MIGRATIONS.glob("*.sql") if not p.name.endswith("_rollback.sql") and p.name > MIGRATION.name
                   and re.search(r"CREATE (?:OR REPLACE )?FUNCTION\s+public\.(post_journal_atomic|settle_receipt_atomic)\s*\(", p.read_text()))
    for path in later:
        done = _psql_file(dsn, path)
        assert done.returncode == 0, (path.name, done.stderr)
    assert _definitions(dsn) == after
    assert not _post(dsn, "partner", CLIENT_A, FINALISED_A, "RB-4")[0]
    assert not _post(dsn, "reviewer_a", CLIENT_A, OPEN, "RB-5")[0]
