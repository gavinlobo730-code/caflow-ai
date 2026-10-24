"""The two ledger functions are executable by the server alone, and the server's own call must name a client of its firm (migration 546, POST-A-317 last step).

WHAT THIS IS FOR
    `post_journal_atomic` (the posting kernel) and `settle_receipt_atomic` (a plain rupee customer receipt) were executable by
    every signed-in user, admitted by a union of role pairs, so a member who held ANY ONE of them could post a balanced entry with
    any content for a client they reach, over PostgREST, with none of the questions the application's routes ask. The API now
    calls both through its privileged client (`services/ledger_door.py`) and migration 546 takes EXECUTE away from every
    signed-in role, and asks a privileged caller the one thing nothing asked it: that the client in the payload belongs to the firm
    in the payload.

WHAT THIS HOLDS (real Postgres, as each role)
    * NO SIGNED-IN ROLE CAN CALL EITHER FUNCTION: a Partner (who holds every role pair), an Executive with banking:write (the
      weakest pair that was enough) and `anon` are refused by the privilege, in the database's own words, and nothing is written.
      The service role and a connection with no JWT still post a journal and a receipt.
    * A PRIVILEGED CALL NAMES A CLIENT OF ITS FIRM: a client of another firm, a client that does not exist, a missing client and a
      missing firm are refused with the migration's sentence (SQLSTATE 42501) by both functions, for the service role and for a
      connection with no JWT alike, and nothing is written. The same call naming its own client still posts.
    * THE SIGNED-IN BRANCH IS STILL THERE: with the grant handed back inside the throwaway database (as a person with ownership of
      the database could, and as a restored backup might), a stranger, a member of another firm, an unassigned Manager and an
      Executive without the pair are refused exactly as migration 533 refuses them, and an assigned Manager still posts. That is the
      second lock; this migration makes it unreachable and does not weaken it.
    * THE SHAPE: each wrapper is migration 545's definition (found by scanning the migration directory) plus exactly the added
      block; the unguarded bodies are not executable by anyone signed in; `service_role` keeps its EXECUTE.
    * THE CLOSING CHECK is run alone after each spoiling it is there to catch.
    * THE ROLLBACK restores migration 545's two definitions and gives `authenticated` its EXECUTE back; a re-apply takes it away
      again and gives back the same definitions.

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
    reason="the ledger-function privilege proof requires HARNESS_PG + psql",
)

FIRM = "54600000-0000-0000-0000-000000000001"
OTHER_FIRM = "54600000-0000-0000-0000-000000000002"
CLIENT_A = "54600000-0000-0000-0000-0000000000a1"
CLIENT_B = "54600000-0000-0000-0000-0000000000b1"             # a second client of the same firm, which manager_a is not assigned to
CLIENT_OTHER = "54600000-0000-0000-0000-0000000000c1"         # a client of the OTHER firm
NO_SUCH_CLIENT = "54600000-0000-0000-0000-0000000000ee"
CUSTOMER_A = "54600000-0000-0000-0000-0000000000d1"
BANK_A, AR_A = "54600000-0000-0000-0000-0000000000a5", "54600000-0000-0000-0000-0000000000a6"
INVOICE_A = "54600000-0000-0000-0000-0000000000e1"
PEOPLE = {            # name: (users.id, auth id, role, firm)
    "partner": ("54600000-0000-0000-0000-00000000000a", "54600000-1111-0000-0000-000000000001", "Partner", FIRM),
    "manager_a": ("54600000-0000-0000-0000-00000000000b", "54600000-1111-0000-0000-000000000002", "Manager", FIRM),
    "manager_free": ("54600000-0000-0000-0000-00000000000c", "54600000-1111-0000-0000-000000000003", "Manager", FIRM),
    "executive_a": ("54600000-0000-0000-0000-00000000000d", "54600000-1111-0000-0000-000000000004", "Executive", FIRM),
    "reviewer_a": ("54600000-0000-0000-0000-00000000000e", "54600000-1111-0000-0000-000000000005", "Reviewer", FIRM),
    "other_firm": ("54600000-0000-0000-0000-000000000010", "54600000-1111-0000-0000-000000000006", "Partner", OTHER_FIRM),
}
MIGRATION = next(p for p in MIGRATIONS.glob("546_the_two_ledger_functions_are_executable_by_the_server_alone*.sql")
                 if not p.name.endswith("_rollback.sql"))
ROLLBACK = next(MIGRATIONS.glob("546_the_two_ledger_functions_are_executable_by_the_server_alone*_rollback.sql"))
POST = "public.post_journal_atomic(jsonb, jsonb)"
SETTLE = "public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb)"
POST_RAW = "public.post_journal_atomic__unguarded(jsonb, jsonb)"
SETTLE_RAW = "public.settle_receipt_atomic__unguarded(jsonb, jsonb, jsonb, jsonb)"
NOT_A_CLIENT = "is not a client of firm"


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


def _text(dsn: str, sql: str) -> str:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.rstrip("\n")


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


def _entry(day: str, ref: str, client: str | None = CLIENT_A, firm: str | None = FIRM, **extra) -> dict:
    e = {"entry_date": day, "reference_no": ref, "narration": "t", "entry_type": "Journal", "is_posted": True, "status": "posted", **extra}
    if firm is not None:
        e["firm_id"] = firm
    if client is not None:
        e["client_id"] = client
    return e


def _lines(paise: int = 10000) -> list[dict]:
    return [{"account_id": BANK_A, "debit_paise": paise, "credit_paise": 0, "narration": "d"},
            {"account_id": AR_A, "debit_paise": 0, "credit_paise": paise, "narration": "c"}]


def _j(x) -> str:
    return json.dumps(x).replace("'", "''")


def _post(dsn: str, who: str, ref: str, **kw) -> tuple[bool, str]:
    return _call(dsn, who, f"SELECT public.post_journal_atomic('{_j(_entry('2025-09-30', ref, **kw))}'::jsonb, '{_j(_lines())}'::jsonb);")


def _settle(dsn: str, who: str, ref: str, client: str | None = CLIENT_A, firm: str | None = FIRM, **extra) -> tuple[bool, str]:
    receipt = {"id": str(uuid.uuid4()), "customer_id": CUSTOMER_A, "receipt_no": ref, "receipt_date": "2025-09-30",
               "amount_paise": 10000, "tds_paise": 0, "unallocated_paise": 0, "payment_mode": "bank", "reference_no": "", "notes": ""}
    for k, v in (("firm_id", firm), ("client_id", client)):
        if v is not None:
            receipt[k] = v
    alloc = [{"sales_invoice_id": INVOICE_A, "allocated_paise": 10000}]
    return _call(dsn, who, "SELECT public.settle_receipt_atomic('%s'::jsonb, '%s'::jsonb, '%s'::jsonb, '%s'::jsonb);" % (
        _j(receipt), _j(_entry("2025-09-30", ref, client=client, firm=firm, entry_type="Receipt", **extra)), _j(_lines()), _j(alloc)))


def _hand_the_grant_back(dsn: str) -> None:
    """Hand `authenticated` its EXECUTE back in the throwaway database, so the signed-in branch of each wrapper can still be driven."""
    r = _psql(dsn, f"GRANT EXECUTE ON FUNCTION {POST} TO authenticated; GRANT EXECUTE ON FUNCTION {SETTLE} TO authenticated;")
    assert r.returncode == 0, r.stderr


def _acl(dsn: str, sig: str) -> dict[str, bool]:
    return {r: _one(dsn, f"SELECT has_function_privilege('{r}', '{sig}'::regprocedure, 'EXECUTE')") == "t"
            for r in ("anon", "authenticated", "service_role")}


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e546_{uuid.uuid4().hex[:12]}"
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
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES
                ('{FIRM}', '{PEOPLE["manager_a"][0]}', '{CLIENT_A}'), ('{FIRM}', '{PEOPLE["executive_a"][0]}', '{CLIENT_A}'),
                ('{FIRM}', '{PEOPLE["reviewer_a"][0]}', '{CLIENT_A}');
            INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER_A}', '{FIRM}', '{CLIENT_A}', 'Cust');
            INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type) VALUES
                ('{BANK_A}', '{FIRM}', '{CLIENT_A}', 'BANK-1', 'Bank Account', 'Asset'),
                ('{AR_A}', '{FIRM}', '{CLIENT_A}', 'AR-1', 'Trade Receivables', 'Asset');
            INSERT INTO client_sales_invoices
                (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status, paid_paise, credited_paise)
                VALUES ('{INVOICE_A}', '{FIRM}', '{CLIENT_A}', '{CUSTOMER_A}', 'SINV-1', '2025-04-01', 100000, 'issued', 0, 0);
        """)
        assert seed.returncode == 0, seed.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _written(dsn: str) -> tuple[str, str]:
    return (_one(dsn, "SELECT count(*) FROM journal_entries"), _one(dsn, "SELECT count(*) FROM receipts"))


# ── nobody signed in can call either function ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("who", ["partner", "manager_a", "executive_a", "other_firm", "anon"])
def test_a_signed_in_role_is_refused_by_the_privilege_and_nothing_is_written(dsn, who):
    before = _written(dsn)
    ok, msg = _post(dsn, who, f"P-{who}")
    assert not ok and "permission denied for function post_journal_atomic" in msg, (who, msg)
    ok, msg = _settle(dsn, who, f"R-{who}")
    assert not ok and "permission denied for function settle_receipt_atomic" in msg, (who, msg)
    assert _written(dsn) == before


def test_the_grants_are_the_servers_alone(dsn):
    for sig in (POST, SETTLE):
        assert _acl(dsn, sig) == {"anon": False, "authenticated": False, "service_role": True}, sig
    for sig in (POST_RAW, SETTLE_RAW):
        acl = _acl(dsn, sig)
        assert acl["anon"] is False and acl["authenticated"] is False, (sig, acl)


@pytest.mark.parametrize("who", ["service", "backend"])
def test_the_server_still_posts_a_journal_and_a_receipt(dsn, who):
    ok, jid = _post(dsn, who, f"S-{who}", created_by=PEOPLE["manager_a"][0], posted_by=PEOPLE["manager_a"][0])
    assert ok and re.fullmatch(r"[0-9a-f-]{36}", jid), jid
    assert _one(dsn, f"SELECT count(*) FROM journal_entries WHERE id = '{jid}' AND client_id = '{CLIENT_A}'") == "1"
    ok, out = _settle(dsn, who, f"SR-{who}", created_by=PEOPLE["partner"][0])
    assert ok, out
    assert _one(dsn, f"SELECT count(*) FROM receipts WHERE receipt_no = 'SR-{who}'") == "1"


# ── a privileged call names a client of its firm ──────────────────────────────────────────────────────────
CASES = [
    ("a client of another firm", {"client": CLIENT_OTHER}),
    ("a client that does not exist", {"client": NO_SUCH_CLIENT}),
    ("no client", {"client": None}),
    ("no firm", {"firm": None}),
    ("another firm's id with this firm's client", {"firm": OTHER_FIRM}),
]


@pytest.mark.parametrize("who", ["service", "backend"])
@pytest.mark.parametrize("label,kw", CASES, ids=[c[0] for c in CASES])
def test_a_journal_posting_that_names_no_client_of_its_firm_is_refused_and_writes_nothing(dsn, who, label, kw):
    before = _written(dsn)
    ok, msg = _post(dsn, who, "X-1", **kw)
    assert not ok and "post_journal_atomic: client" in msg and NOT_A_CLIENT in msg, (label, msg)
    assert _written(dsn) == before


@pytest.mark.parametrize("who", ["service", "backend"])
@pytest.mark.parametrize("label,kw", CASES, ids=[c[0] for c in CASES])
def test_a_receipt_that_names_no_client_of_its_firm_is_refused_and_writes_nothing(dsn, who, label, kw):
    before = _written(dsn)
    paid_before = _one(dsn, f"SELECT paid_paise FROM client_sales_invoices WHERE id = '{INVOICE_A}'")
    ok, msg = _settle(dsn, who, "XR-1", **kw)
    assert not ok and "settle_receipt_atomic: client" in msg and NOT_A_CLIENT in msg, (label, msg)
    assert _written(dsn) == before
    assert _one(dsn, f"SELECT paid_paise FROM client_sales_invoices WHERE id = '{INVOICE_A}'") == paid_before


def test_the_refusal_is_a_permission_error_not_a_data_error(dsn):
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-v", "VERBOSITY=verbose", "-X", "-tA", "-c",
                        _prefix("service") + f"SELECT public.post_journal_atomic('{_j(_entry('2025-09-30', 'E-1', client=CLIENT_OTHER))}'::jsonb, "
                        f"'{_j(_lines())}'::jsonb);"], capture_output=True, text=True)
    assert r.returncode != 0 and "42501" in r.stderr, r.stderr


# ── the signed-in branch is still there, behind a grant handed back ───────────────────────────────────────
def test_with_the_grant_handed_back_the_signed_in_checks_are_the_ones_533_gave(dsn):
    _hand_the_grant_back(dsn)
    before = _written(dsn)
    ok, msg = _post(dsn, "other_firm", "H-1")
    assert not ok and "is not the caller's firm" in msg, msg
    ok, msg = _post(dsn, "manager_free", "H-2")
    assert not ok and "not one the caller can reach" in msg, msg
    ok, msg = _post(dsn, "reviewer_a", "H-3")
    assert not ok and "does not allow this" in msg, msg
    ok, msg = _post(dsn, "manager_a", "H-4", client=CLIENT_B)
    assert not ok and "not one the caller can reach" in msg, msg
    assert _written(dsn) == before
    ok, jid = _post(dsn, "manager_a", "H-5")
    assert ok and re.fullmatch(r"[0-9a-f-]{36}", jid), jid
    ok, out = _settle(dsn, "manager_a", "H-6")
    assert ok, out
    ok, msg = _settle(dsn, "other_firm", "H-7")
    assert not ok and "is not the caller's firm" in msg, msg


def test_with_the_grant_handed_back_a_signed_in_caller_is_asked_the_client_by_the_older_check_and_not_the_new_one(dsn):
    """The new block is for a caller with no auth.uid(); a signed-in caller is asked by assert_caller_acts_for, in its own words."""
    _hand_the_grant_back(dsn)
    ok, msg = _post(dsn, "partner", "H-8", client=CLIENT_OTHER)
    assert not ok and "is not a client of firm" in msg and "post_journal_atomic: client" in msg, msg


# ── the shape ───────────────────────────────────────────────────────────────�
def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", sql)).strip()


def _function_body(text: str, name: str) -> str:
    m = re.search(rf"CREATE (?:OR REPLACE )?FUNCTION public\.{name}\(", text)
    assert m, name
    k = text.index("AS ", m.start())
    tag = re.match(r"AS (\$\w*\$)", text[k:]).group(1)
    start = k + 3 + len(tag)
    return text[start:text.index(tag + ";", start)]


def _last_definer(name: str, before: str) -> Path:
    cands = sorted(p for p in MIGRATIONS.glob("*.sql")
                   if not p.name.endswith("_rollback.sql") and p.name < before
                   and re.search(rf"CREATE (?:OR REPLACE )?FUNCTION\s+public\.{name}\s*\(p_", p.read_text()))
    return cands[-1]


def test_each_wrapper_is_its_last_definition_plus_exactly_the_added_block(dsn):
    for sig, name, added in (
            (POST, "post_journal_atomic",
             r"IF auth\.uid\(\) IS NULL AND NOT EXISTS \( SELECT 1 FROM public\.clients c WHERE c\.id = v_client AND c\.firm_id = v_firm\) THEN "
             r"RAISE EXCEPTION 'post_journal_atomic: client % is not a client of firm %', v_client, v_firm USING ERRCODE = '42501'; END IF; "),
            (SETTLE, "settle_receipt_atomic",
             r"IF auth\.uid\(\) IS NULL AND NOT EXISTS \( SELECT 1 FROM public\.clients c WHERE c\.id = NULLIF\(p_journal_entry->>'client_id', ''\)::uuid "
             r"AND c\.firm_id = NULLIF\(p_journal_entry->>'firm_id', ''\)::uuid\) THEN RAISE EXCEPTION 'settle_receipt_atomic: client % is not a client of firm %', "
             r"NULLIF\(p_journal_entry->>'client_id', ''\)::uuid, NULLIF\(p_journal_entry->>'firm_id', ''\)::uuid USING ERRCODE = '42501'; END IF; ")):
        ancestor = _last_definer(name, MIGRATION.name)
        assert ancestor.name.startswith("545_"), (name, ancestor.name)
        live = _norm(_text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{sig}'::regprocedure"))
        live, n = re.subn(added, "", live, count=1)
        assert n == 1, f"{name} does not carry the added block exactly once"
        assert live == _norm(_function_body(ancestor.read_text(), name)), name


# ── the closing check, run alone after each spoiling ──────────────────────────────────────────────────────
def _closing_block() -> str:
    text = MIGRATION.read_text()
    return text[text.rindex("DO $$"):]


def _ancestor_definition(name: str) -> str:
    text = _last_definer(name, MIGRATION.name).read_text()
    m = re.search(rf"CREATE (?:OR REPLACE )?FUNCTION public\.{name}\(.*?\n(\$\w*\$);", text, re.S)
    assert m, name
    return m.group(0).replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


def _stub(missing: str, fn: str = "post_journal_atomic") -> str:
    """A wrapper that still SAYS two of the three things the closing check reads and lacks the third (the text is all the check sees)."""
    words = [w for w in ("is not a client of firm", "assert_caller_acts_for", "carry_audit_actor", "''audit_actor''") if w != missing]
    args = "p_entry jsonb, p_lines jsonb" if fn == "post_journal_atomic" else "p_receipt jsonb, p_journal_entry jsonb, p_journal_lines jsonb, p_allocations jsonb"
    ret = "uuid" if fn == "post_journal_atomic" else "jsonb"
    return (f"CREATE OR REPLACE FUNCTION public.{fn}({args}) RETURNS {ret} LANGUAGE plpgsql VOLATILE SECURITY DEFINER "
            f"SET search_path = public, pg_catalog AS $x$ BEGIN RAISE EXCEPTION '{' '.join(words)}'; END; $x$;")


SPOILS = [
    ("a wrapper is executable by authenticated", f"GRANT EXECUTE ON FUNCTION {POST} TO authenticated;"),
    ("the receipt wrapper is executable by authenticated", f"GRANT EXECUTE ON FUNCTION {SETTLE} TO authenticated;"),
    ("a wrapper is executable by anon", f"GRANT EXECUTE ON FUNCTION {POST} TO anon;"),
    ("the service role lost the post wrapper", f"REVOKE EXECUTE ON FUNCTION {POST} FROM service_role;"),
    ("the service role lost the receipt wrapper", f"REVOKE EXECUTE ON FUNCTION {SETTLE} FROM service_role;"),
    ("the post wrapper lost the client check", None),
    ("the receipt wrapper lost the client check", None),
    ("the post wrapper lost the caller check", _stub("assert_caller_acts_for")),
    ("the receipt wrapper lost the caller check", _stub("assert_caller_acts_for", "settle_receipt_atomic")),
    ("the post wrapper lost the reserved-key removal", _stub("''audit_actor''")),
    ("the receipt wrapper lost the reserved-key removal", _stub("''audit_actor''", "settle_receipt_atomic")),
    ("the post wrapper lost the audit actor carrier", _stub("carry_audit_actor")),
    ("the receipt wrapper lost the audit actor carrier", _stub("carry_audit_actor", "settle_receipt_atomic")),
    ("an unguarded body is executable by authenticated", f"GRANT EXECUTE ON FUNCTION {POST_RAW} TO authenticated;"),
    ("the unguarded receipt body is executable by authenticated", f"GRANT EXECUTE ON FUNCTION {SETTLE_RAW} TO authenticated;"),
]


@pytest.mark.parametrize("label,spoil", SPOILS, ids=[s[0] for s in SPOILS])
def test_the_closing_check_fails_when_what_it_checks_is_spoiled(dsn, label, spoil):
    assert _psql(dsn, _closing_block()).returncode == 0, "the closing check should pass on the migrated database"
    if spoil is None:
        name = "post_journal_atomic" if "post" in label else "settle_receipt_atomic"
        spoil = _ancestor_definition(name)
    assert _psql(dsn, spoil).returncode == 0, label
    r = _psql(dsn, _closing_block())
    assert r.returncode != 0 and "migration 546" in r.stderr, (label, r.stderr)


# ── the rollback and the re-apply ─────────────────────────────────────────────────────────────────────────
def test_the_rollback_restores_545s_definitions_and_the_grant_and_a_reapply_takes_it_away_again(dsn):
    before = {sig: _text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{sig}'::regprocedure") for sig in (POST, SETTLE)}
    assert _psql_file(dsn, ROLLBACK).returncode == 0
    for sig, name in ((POST, "post_journal_atomic"), (SETTLE, "settle_receipt_atomic")):
        live = _norm(_text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{sig}'::regprocedure"))
        assert NOT_A_CLIENT not in live, name
        assert live == _norm(_function_body(_last_definer(name, MIGRATION.name).read_text(), name)), name
        assert _acl(dsn, sig) == {"anon": False, "authenticated": True, "service_role": True}, sig
    ok, jid = _post(dsn, "manager_a", "RB-1")
    assert ok and jid, "after the rollback an assigned Manager can post again, as before"
    assert _psql_file(dsn, MIGRATION).returncode == 0
    for sig in (POST, SETTLE):
        assert _acl(dsn, sig) == {"anon": False, "authenticated": False, "service_role": True}, sig
    after = {sig: _text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{sig}'::regprocedure") for sig in (POST, SETTLE)}
    assert after == before, "a rollback and a re-apply must give back the same definitions"


def test_applying_it_twice_changes_nothing(dsn):
    before = {sig: _text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{sig}'::regprocedure") for sig in (POST, SETTLE)}
    assert _psql_file(dsn, MIGRATION).returncode == 0
    after = {sig: _text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{sig}'::regprocedure") for sig in (POST, SETTLE)}
    assert after == before
    assert _acl(dsn, POST)["authenticated"] is False and _acl(dsn, SETTLE)["authenticated"] is False
