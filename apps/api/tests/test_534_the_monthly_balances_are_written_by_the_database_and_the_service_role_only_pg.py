"""Migration 534 — the monthly balances the reports read are written by the database's own triggers and the service role, never
by a signed-in session (ledger POST-A-318).

WHAT WAS WRONG
    `account_period_balances` is one row per client, account and month: the debit and credit totals of the posted ledger. The
    trial balance, profit and loss, balance sheet, ratios, budgets and the year-end statements read it DIRECTLY, so it is what
    the CA sees. It was granted INSERT, UPDATE and DELETE to `authenticated` and its only policy was the firm-and-client one,
    with no role tier, and `apb_apply_posted_line` carried the default PUBLIC execute right. An Executive assigned to a client
    could rewrite a bucket of a CLOSED year (UPDATE 1) with no journal entry, no closure check and no audit row, and one
    member's forgery made `apb_assert_no_drift()` (compares EVERY firm's buckets with its ledger; called by the manual-journal
    edit and discard functions) refuse for every firm until the nightly audit healed it.

WHAT THIS HOLDS (real Postgres, as each person)
    * a signed-in role effectively holds NO write privilege (table, column or through PUBLIC) on the table, `service_role`
      keeps INSERT, UPDATE and DELETE, and `authenticated` still READS it (the reports do), scoped to the caller's clients;
    * `apb_apply_posted_line` is executable by the service role and by no signed-in role, and no other `apb_` function with
      arguments is executable by one;
    * a Partner, a Manager, an Executive and a Reviewer assigned to the client are each refused INSERT, UPDATE, DELETE and the
      function call BY THE PRIVILEGE, and the bucket (a closed year's included) is untouched, `apb_drifted_clients()` empty;
    * NOTHING THE PRODUCT DOES BREAKS (these cases pass without the migration too, on purpose: they prove the revoke breaks no
      flow, and the privilege and refusal cases above are the ones that prove it does its work): posting as an assigned Executive, a manual journal edited and discarded and a reversal
      posted as a Manager, a receipt settled, and a journal written directly by the service role all keep the buckets equal to
      the ledger (the triggers run as the posting function's owner, or as the service role, which keeps its execute right), and
      the service role's rebuild still works;
    * the rollback gives the verbs back and the forgery works again (the negative control, with `apb_drifted_clients()` seeing
      it), a re-apply refuses it again, and applying the migration twice is harmless.

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
_STEM = "534_the_monthly_balances_the_reports_read_are_written_by_the_database_and_the_service_role_only"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the balance-cache proof requires HARNESS_PG + psql",
)

FIRM = "53400000-0000-0000-0000-000000000001"
CLIENT_A = "53400000-0000-0000-0000-0000000000a1"
CLIENT_B = "53400000-0000-0000-0000-0000000000b2"
BANK_A, AR_A = "53400000-0000-0000-0000-0000000000a5", "53400000-0000-0000-0000-0000000000a6"
BANK_B, AR_B = "53400000-0000-0000-0000-0000000000b5", "53400000-0000-0000-0000-0000000000b6"
CUSTOMER_A = "53400000-0000-0000-0000-0000000000d1"
INVOICE_A = "53400000-0000-0000-0000-0000000000e1"
PEOPLE = {            # name: (users.id, auth id, role)
    "partner": ("53400000-0000-0000-0000-00000000000a", "53400000-1111-0000-0000-000000000001", "Partner"),
    "manager_a": ("53400000-0000-0000-0000-00000000000b", "53400000-1111-0000-0000-000000000002", "Manager"),
    "executive_a": ("53400000-0000-0000-0000-00000000000e", "53400000-1111-0000-0000-000000000004", "Executive"),
    "reviewer_a": ("53400000-0000-0000-0000-000000000011", "53400000-1111-0000-0000-000000000007", "Reviewer"),
    "executive_b": ("53400000-0000-0000-0000-000000000013", "53400000-1111-0000-0000-000000000009", "Executive"),
    "manager_none": ("53400000-0000-0000-0000-00000000000c", "53400000-1111-0000-0000-000000000003", "Manager"),
}
TABLE = "account_period_balances"
CLOSED_DAY = "2024-09-30"                 # client A's 2024-25 is finalised below
OPEN_DAY = "2025-09-30"
DENIED = f"permission denied for table {TABLE}"
FN = "public.apb_apply_posted_line(uuid, uuid, uuid, date, bigint, bigint)"
MAINTENANCE = ["public.apb_rebuild_client(uuid, uuid)", "public.apb_drifted_clients()", "public.apb_rebuild_drifted()",
               "public.apb_assert_no_drift()"]


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
    if who == "backend":
        return ""
    if who == "service":
        return "SET ROLE service_role; "
    return f"SET request.jwt.claims = '{{\"sub\": \"{PEOPLE[who][1]}\", \"role\": \"authenticated\"}}'; SET ROLE authenticated; "


def _call(dsn: str, who: str, sql: str) -> tuple[bool, str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _prefix(who) + sql], capture_output=True, text=True)
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


def _post(dsn: str, who: str, client: str, day: str, ref: str, **extra) -> tuple[bool, str]:
    e, ls = json.dumps(_entry(client, day, ref, **extra)).replace("'", "''"), json.dumps(_lines(client)).replace("'", "''")
    return _call(dsn, who, f"SELECT public.post_journal_atomic('{e}'::jsonb, '{ls}'::jsonb);")


def _drifted(dsn: str) -> list[list[str]]:
    return _rows(dsn, "SELECT firm_id, client_id FROM public.apb_drifted_clients()")


def _bucket(dsn: str, client: str, day: str) -> tuple[int, int]:
    month = day[:7] + "-01"
    row = _rows(dsn, f"SELECT coalesce(sum(debit_paise), 0), coalesce(sum(credit_paise), 0) FROM {TABLE} "
                     f"WHERE client_id = '{client}' AND period_month = '{month}'")[0]
    return int(row[0]), int(row[1])


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e534_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r) in PEOPLE.items())
        members = ", ".join(f"('{i}', '{FIRM}', '{a}', '{n}@t.in', '{n}', '{r}', true)" for n, (i, a, r) in PEOPLE.items())
        seed = _psql(d, f"""
            INSERT INTO auth.users (id, email) VALUES {auth};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
                 VALUES ('{CLIENT_A}', '{FIRM}', 'A', 'Proprietorship'), ('{CLIENT_B}', '{FIRM}', 'B', 'Proprietorship');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {members};
            INSERT INTO user_client_assignments (firm_id, user_id, client_id)
                 VALUES ('{FIRM}', '{PEOPLE["manager_a"][0]}', '{CLIENT_A}'), ('{FIRM}', '{PEOPLE["executive_a"][0]}', '{CLIENT_A}'),
                        ('{FIRM}', '{PEOPLE["reviewer_a"][0]}', '{CLIENT_A}'), ('{FIRM}', '{PEOPLE["executive_b"][0]}', '{CLIENT_B}');
            INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER_A}', '{FIRM}', '{CLIENT_A}', 'Cust');
            INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type) VALUES
                ('{BANK_A}', '{FIRM}', '{CLIENT_A}', 'BANK-1', 'Bank Account', 'Asset'),
                ('{AR_A}', '{FIRM}', '{CLIENT_A}', 'AR-1', 'Trade Receivables', 'Asset'),
                ('{BANK_B}', '{FIRM}', '{CLIENT_B}', 'BANK-2', 'Bank Account B', 'Asset'),
                ('{AR_B}', '{FIRM}', '{CLIENT_B}', 'AR-2', 'Trade Receivables B', 'Asset');
            INSERT INTO client_sales_invoices
                (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status, paid_paise, credited_paise)
                VALUES ('{INVOICE_A}', '{FIRM}', '{CLIENT_A}', '{CUSTOMER_A}', 'SINV-1', '2024-04-01', 100000, 'issued', 0, 0);
        """)
        assert seed.returncode == 0, seed.stderr
        # a posted entry in each client's books, in a year that is then finalised for A (the closed year the review forged)
        assert _post(d, "service", CLIENT_A, CLOSED_DAY, "SEED-A")[0] and _post(d, "service", CLIENT_B, CLOSED_DAY, "SEED-B")[0]
        assert _psql(d, f"INSERT INTO client_year_locks (firm_id, client_id, financial_year, reason) "
                        f"VALUES ('{FIRM}', '{CLIENT_A}', '2024-25', 'test');").returncode == 0
        assert _drifted(d) == [], "the seed must start clean"
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── PRIVILEGES ──────────────────────────────────────────────────────────────────

def _signed_in_roles() -> tuple[str, str]:
    return "authenticated", "anon"


def test_no_signed_in_role_holds_a_write_on_the_table_at_any_level(dsn):
    for role in _signed_in_roles():
        for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            assert _one(dsn, f"SELECT has_table_privilege('{role}', 'public.{TABLE}', '{verb}')") == "f", (role, verb)
        for verb in ("INSERT", "UPDATE"):
            assert _one(dsn, f"SELECT has_any_column_privilege('{role}', 'public.{TABLE}', '{verb}')") == "f", (role, verb)
    # and through PUBLIC (grantee 0 in the ACL): the pseudo-role every role inherits holds no write either
    held = _rows(dsn, f"""SELECT a.privilege_type FROM pg_class c, aclexplode(c.relacl) a
                           WHERE c.oid = 'public.{TABLE}'::regclass AND a.grantee = 0 AND a.privilege_type IN
                                 ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')""")
    assert held == [], held


def test_the_migration_takes_every_privilege_away_from_a_database_that_granted_them_all(dsn):
    """Production's platform defaults grant a good deal more than a database built from the migrations does (anon and PUBLIC
    included), so the revocation is proved from the worst case: grant everything first, then apply the migration."""
    grants = "\n".join(f"GRANT EXECUTE ON FUNCTION {f} TO PUBLIC, anon, authenticated;" for f in MAINTENANCE)
    assert _psql(dsn, f"""GRANT ALL ON public.{TABLE} TO PUBLIC, anon, authenticated;
                         GRANT EXECUTE ON FUNCTION {FN} TO PUBLIC, anon, authenticated;
                         {grants}""").returncode == 0
    assert _one(dsn, f"SELECT has_table_privilege('anon', 'public.{TABLE}', 'UPDATE')") == "t", "the fixture must start open"
    done = _psql_file(dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    for role in ("authenticated", "anon"):
        for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            assert _one(dsn, f"SELECT has_table_privilege('{role}', 'public.{TABLE}', '{verb}')") == "f", (role, verb)
        assert _one(dsn, f"SELECT has_function_privilege('{role}', '{FN}', 'EXECUTE')") == "f", role
    held = _rows(dsn, f"""SELECT a.privilege_type FROM pg_class c, aclexplode(c.relacl) a
                           WHERE c.oid = 'public.{TABLE}'::regclass AND a.grantee = 0 AND a.privilege_type IN
                                 ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')""")
    assert held == [], held
    assert _one(dsn, f"SELECT has_function_privilege('service_role', '{FN}', 'EXECUTE')") == "t"
    for verb in ("INSERT", "UPDATE", "DELETE"):
        assert _one(dsn, f"SELECT has_table_privilege('service_role', 'public.{TABLE}', '{verb}')") == "t", verb
    for f in MAINTENANCE:       # the four 251 left to the service role, which only a revoke by NAME keeps from a platform default
        for role in ("authenticated", "anon"):
            assert _one(dsn, f"SELECT has_function_privilege('{role}', '{f}', 'EXECUTE')") == "f", (role, f)
        assert _one(dsn, f"SELECT has_function_privilege('service_role', '{f}', 'EXECUTE')") == "t", f


def test_the_service_role_keeps_its_writes_and_a_signed_in_member_keeps_the_read(dsn):
    for verb in ("INSERT", "UPDATE", "DELETE", "SELECT"):
        assert _one(dsn, f"SELECT has_table_privilege('service_role', 'public.{TABLE}', '{verb}')") == "t", verb
    assert _one(dsn, f"SELECT has_table_privilege('authenticated', 'public.{TABLE}', 'SELECT')") == "t"
    assert _one(dsn, f"SELECT has_table_privilege('anon', 'public.{TABLE}', 'SELECT')") == "f"


def test_apply_posted_line_is_the_service_roles_and_no_other_function_with_arguments_is_a_signed_ins(dsn):
    assert _one(dsn, f"SELECT has_function_privilege('service_role', '{FN}', 'EXECUTE')") == "t"
    for role in ("authenticated", "anon"):
        assert _one(dsn, f"SELECT has_function_privilege('{role}', '{FN}', 'EXECUTE')") == "f", role
    reachable = _rows(dsn, """SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                               WHERE n.nspname = 'public' AND p.proname LIKE 'apb\\_%' AND p.prorettype <> 'trigger'::regtype
                                 AND (has_function_privilege('authenticated', p.oid, 'EXECUTE')
                                      OR has_function_privilege('anon', p.oid, 'EXECUTE'))""")
    assert reachable == [], reachable


# ── THE FORGERY THE REVIEW FOUND ────────────────────────────────────────────────

@pytest.mark.parametrize("who", ["partner", "manager_a", "executive_a", "reviewer_a"])
def test_every_write_is_refused_by_the_privilege_and_the_closed_years_bucket_is_untouched(dsn, who):
    before = _bucket(dsn, CLIENT_A, CLOSED_DAY)
    assert before == (10000, 10000)
    month = CLOSED_DAY[:7] + "-01"
    statements = {
        "update the closed year": f"UPDATE {TABLE} SET debit_paise = 99999999 WHERE client_id = '{CLIENT_A}' AND period_month = '{month}'",
        "delete it": f"DELETE FROM {TABLE} WHERE client_id = '{CLIENT_A}'",
        "insert a bucket": f"INSERT INTO {TABLE} (firm_id, client_id, account_id, period_month, debit_paise, credit_paise) "
                           f"VALUES ('{FIRM}', '{CLIENT_A}', '{BANK_A}', '2024-10-01', 5, 0)",
    }
    for label, sql in statements.items():
        ok, msg = _call(dsn, who, sql)
        assert not ok and DENIED in msg, (who, label, msg)
    ok, msg = _call(dsn, who, f"SELECT public.apb_apply_posted_line('{FIRM}', '{CLIENT_A}', '{BANK_A}', '{CLOSED_DAY}'::date, 99999999, 0)")
    assert not ok and "permission denied for function apb_apply_posted_line" in msg, (who, msg)
    assert _bucket(dsn, CLIENT_A, CLOSED_DAY) == before
    assert _drifted(dsn) == []


# ── READS ARE UNCHANGED ─────────────────────────────────────────────────────────

def test_the_reports_still_read_the_buckets_of_the_callers_clients_and_nobody_elses(dsn):
    def count(who: str, client: str) -> int:
        ok, out = _call(dsn, who, f"SELECT count(*) FROM {TABLE} WHERE client_id = '{client}'")
        assert ok, out
        return int(out)

    assert count("partner", CLIENT_A) > 0 and count("partner", CLIENT_B) > 0
    assert count("executive_a", CLIENT_A) > 0 and count("executive_a", CLIENT_B) == 0
    assert count("reviewer_a", CLIENT_A) > 0 and count("reviewer_a", CLIENT_B) == 0
    assert count("executive_b", CLIENT_B) > 0 and count("executive_b", CLIENT_A) == 0
    assert count("manager_none", CLIENT_A) == 0 and count("manager_none", CLIENT_B) == 0


# ── NOTHING THE PRODUCT DOES BREAKS ─────────────────────────────────────────────

def _ledger_sum(dsn: str, client: str) -> tuple[int, int]:
    row = _rows(dsn, f"""SELECT coalesce(sum(jl.debit_paise), 0), coalesce(sum(jl.credit_paise), 0)
                           FROM journal_lines jl JOIN journal_entries je ON je.id = jl.journal_entry_id
                          WHERE je.client_id = '{client}' AND je.is_posted AND je.deleted_at IS NULL""")[0]
    return int(row[0]), int(row[1])


def _cache_sum(dsn: str, client: str) -> tuple[int, int]:
    row = _rows(dsn, f"SELECT coalesce(sum(debit_paise), 0), coalesce(sum(credit_paise), 0) FROM {TABLE} WHERE client_id = '{client}'")[0]
    return int(row[0]), int(row[1])


def test_posting_as_an_assigned_executive_moves_the_bucket_with_the_ledger(dsn):
    ok, msg = _post(dsn, "executive_a", CLIENT_A, OPEN_DAY, "EX-1")
    assert ok, msg
    assert _bucket(dsn, CLIENT_A, OPEN_DAY) == (10000, 10000)
    assert _cache_sum(dsn, CLIENT_A) == _ledger_sum(dsn, CLIENT_A) == (20000, 20000)
    assert _drifted(dsn) == []


def test_a_manual_journal_edited_and_discarded_by_a_manager_and_a_reversal_keep_the_buckets_equal_to_the_ledger(dsn):
    ok, entry_id = _post(dsn, "manager_a", CLIENT_A, OPEN_DAY, "MJ-1", source_type="manual")
    assert ok, entry_id
    new_lines = json.dumps([{"account_id": BANK_A, "debit_paise": 25000, "credit_paise": 0, "narration": "d"},
                            {"account_id": AR_A, "debit_paise": 0, "credit_paise": 25000, "narration": "c"}]).replace("'", "''")
    ok, msg = _call(dsn, "manager_a", f"SELECT public.edit_posted_journal('{FIRM}', '{CLIENT_A}', '{entry_id}', '{new_lines}'::jsonb, "
                                      f"'edited', NULL, NULL, '{PEOPLE['manager_a'][0]}')")
    assert ok, msg
    assert _bucket(dsn, CLIENT_A, OPEN_DAY) == (25000, 25000)
    assert _drifted(dsn) == []
    ok, rev = _post(dsn, "partner", CLIENT_A, OPEN_DAY, "MJ-REV", reversal_of=entry_id)
    assert ok, rev
    assert _drifted(dsn) == []
    ok, msg = _post(dsn, "manager_a", CLIENT_A, OPEN_DAY, "MJ-2", source_type="manual")
    assert ok, msg
    ok, msg = _call(dsn, "manager_a", f"SELECT public.discard_posted_journal('{FIRM}', '{CLIENT_A}', '{msg}', '{PEOPLE['manager_a'][0]}', false)")
    assert ok, msg
    assert _drifted(dsn) == []
    assert _cache_sum(dsn, CLIENT_A) == _ledger_sum(dsn, CLIENT_A)


def test_a_receipt_settled_by_an_assigned_executive_moves_the_bucket(dsn):
    receipt = {"id": str(uuid.uuid4()), "firm_id": FIRM, "client_id": CLIENT_A, "customer_id": CUSTOMER_A, "receipt_no": "RC-534",
               "receipt_date": OPEN_DAY, "amount_paise": 10000, "tds_paise": 0, "unallocated_paise": 0, "payment_mode": "bank",
               "reference_no": "", "notes": ""}
    p = [json.dumps(x).replace("'", "''") for x in (receipt, _entry(CLIENT_A, OPEN_DAY, "RC-534", entry_type="Receipt"),
                                                  _lines(CLIENT_A), [{"sales_invoice_id": INVOICE_A, "allocated_paise": 10000}])]
    ok, msg = _call(dsn, "executive_a", f"SELECT public.settle_receipt_atomic('{p[0]}'::jsonb, '{p[1]}'::jsonb, '{p[2]}'::jsonb, '{p[3]}'::jsonb)")
    assert ok, msg
    assert _bucket(dsn, CLIENT_A, OPEN_DAY) == (10000, 10000)
    assert _drifted(dsn) == []


def test_a_journal_written_directly_by_the_service_role_still_moves_the_bucket_and_the_rebuild_still_works(dsn):
    """The triggers run as the service role here, so it must keep its execute right on the function they call."""
    entry = str(uuid.uuid4())
    done = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", f"""SET ROLE service_role;
        INSERT INTO journal_entries (id, firm_id, client_id, entry_date, reference_no, narration, entry_type, is_posted, status)
             VALUES ('{entry}', '{FIRM}', '{CLIENT_B}', '{OPEN_DAY}', 'SVC-1', 'o', 'Journal', true, 'posted');
        INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise)
             VALUES ('{entry}', '{BANK_B}', 7000, 0), ('{entry}', '{AR_B}', 0, 7000);"""], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert _bucket(dsn, CLIENT_B, OPEN_DAY) == (7000, 7000)
    assert _drifted(dsn) == []
    # forge the bucket as the administrator, then heal it as the service role: the rebuild is the service role's
    assert _psql(dsn, f"UPDATE {TABLE} SET debit_paise = 1 WHERE client_id = '{CLIENT_B}' AND period_month = '{OPEN_DAY[:7]}-01'").returncode == 0
    assert _drifted(dsn) != []
    ok, msg = _call(dsn, "service", f"SELECT public.apb_rebuild_client('{FIRM}', '{CLIENT_B}')")
    assert ok, msg
    assert _drifted(dsn) == []


# ── THE ROLLBACK, THE DEFECT AND A SECOND APPLY ─────────────────────────────────

def test_the_rollback_brings_the_forgery_back_and_a_reapply_ends_it_again_and_twice_is_harmless(dsn):
    month = CLOSED_DAY[:7] + "-01"
    forge = f"UPDATE {TABLE} SET debit_paise = 99999999 WHERE client_id = '{CLIENT_A}' AND period_month = '{month}'"
    assert not _call(dsn, "executive_a", forge)[0]
    done = _psql_file(dsn, ROLLBACK)
    assert done.returncode == 0, done.stderr
    ok, msg = _call(dsn, "executive_a", forge)
    assert ok, f"after the rollback the Executive's forgery works again (the negative control): {msg}"
    assert _drifted(dsn) != [], "and the drift check sees it"
    ok, msg = _call(dsn, "reviewer_a", f"SELECT public.apb_apply_posted_line('{FIRM}', '{CLIENT_A}', '{BANK_A}', '{CLOSED_DAY}'::date, 1, 0)")
    assert ok, msg
    healed = _call(dsn, "service", f"SELECT public.apb_rebuild_client('{FIRM}', '{CLIENT_A}')")
    assert healed[0], healed
    assert _drifted(dsn) == []
    for _ in range(2):                                    # a re-apply, then once more
        done = _psql_file(dsn, MIGRATION)
        assert done.returncode == 0, done.stderr
    ok, msg = _call(dsn, "executive_a", forge)
    assert not ok and DENIED in msg, msg
