"""
Migration 331, proved against real PostgreSQL.

WHAT IS BEING PROVED
    1. The three statutory booleans are NOT NULL WITH NO DEFAULT. Each is a
       different Act asking a different question — EPF s.2(b), ESI s.2(22),
       IT s.17(1) — and a default would answer one of them silently, in a place
       nobody looks until an ECR fails to reconcile months later.

    2. A zero amount is REFUSED, and a negative one is not. Zero is a row
       somebody started and did not finish; negative is a recovery of an
       earlier overpayment, which is a real thing a bureau does and which must
       reduce the same bases it inflated rather than appear as a deduction.

    3. `month` is pinned to the first of the month. Payroll's grain everywhere
       else in this schema is the month, and a stray day-of-month would split
       one month's earnings into two buckets the run would never find.

    4. Only Manager+ may write, RESTRICTIVE. The frontend reaches ~83 tables
       directly through PostgREST where rbac() never runs, so RLS is the only
       control on a table that decides what somebody is paid.

    5. Deleting an employee takes their earnings with them; the client-month
       scoping is by FK, not by convention.

NEGATIVE CONTROL
    Give pf_wages a DEFAULT false and test_an_unanswered_statutory_question_is_refused
    passes vacuously. Drop the amount CHECK and
    test_a_zero_amount_is_refused fails. Loosen the month CHECK and
    test_a_mid_month_date_is_refused fails. Make the role policies PERMISSIVE
    and test_a_reviewer_cannot_record_an_earning fails — they would OR with the
    firm policy and widen access, which reads identically in pg_policies.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="one-time earnings proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000331"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000331"
EMP = "cccccccc-0000-0000-0000-000000000331"
MANAGER = "dddddddd-0000-0000-0000-000000000331"
REVIEWER = "eeeeeeee-0000-0000-0000-000000000331"
MIGRATION = "331_a_month_is_not_a_pure_repeat.sql"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m331_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert MIGRATION not in pg_template.failed, (
            "migration 331 did not apply — everything below would pass vacuously")
        stmts = [
            f"INSERT INTO auth.users (id, email) VALUES "
            f"('{MANAGER}','mgr331@t.in'), ('{REVIEWER}','rev331@t.in');",
            f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}','F331','f331@t.in');",
            f"INSERT INTO clients (id, firm_id, client_name, entity_type, pan) VALUES "
            f"('{CLIENT}','{FIRM}','C331','Private Limited','AAACA1234E');",
            f"INSERT INTO payroll_employees (id, firm_id, client_id, name) VALUES "
            f"('{EMP}','{FIRM}','{CLIENT}','Asha');",
            # auth_user_id, not id: get_my_firm_id() resolves auth.uid(), which
            # is the Supabase auth id and not the internal users.id. Seeding them
            # equal keeps the claim readable in the tests below.
            f"INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role) "
            f"VALUES ('{MANAGER}','{FIRM}','{MANAGER}','mgr331@t.in','Mgr','Manager');",
            f"INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role) "
            f"VALUES ('{REVIEWER}','{FIRM}','{REVIEWER}','rev331@t.in','Rev','Reviewer');",
        ]
        for sql in stmts:
            r = _psql(dsn, sql)
            assert r.returncode == 0, f"{sql[:70]}… → {r.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _insert(cols: str = "", vals: str = "", month: str = "2026-08-01",
            amount: str = "5000000") -> str:
    base_cols = "firm_id, client_id, employee_id, month, kind, amount_paise"
    base_vals = f"'{FIRM}','{CLIENT}','{EMP}','{month}','bonus',{amount}"
    if cols:
        base_cols += ", " + cols
        base_vals += ", " + vals
    return (f"INSERT INTO payroll_one_time_earnings ({base_cols}) "
            f"VALUES ({base_vals});")


_ANSWERED = ("pf_wages, esi_wages, taxable", "false, false, true")


# ─── 1. the three questions have no default ──────────────────────────────────

@pytest.mark.parametrize("omitted,kept,vals", [
    ("pf_wages",  "esi_wages, taxable", "false, true"),
    ("esi_wages", "pf_wages, taxable",  "false, true"),
    ("taxable",   "pf_wages, esi_wages", "false, false"),
])
def test_an_unanswered_statutory_question_is_refused(db, omitted, kept, vals):
    """NOT NULL with NO DEFAULT. A default would answer one Act's question
    silently, and the wrong answer is invisible on a payslip — it surfaces in an
    ECR or an ESIC return that does not reconcile, months later."""
    r = _psql(db, _insert(kept, vals))
    assert r.returncode != 0, f"{omitted} was defaulted rather than required"
    assert "null value" in r.stderr.lower() or "not-null" in r.stderr.lower()


def test_a_fully_answered_row_is_accepted(db):
    assert _psql(db, _insert(*_ANSWERED)).returncode == 0


# ─── 2. the amount ───────────────────────────────────────────────────────────

def test_a_zero_amount_is_refused(db):
    """A zero-rupee earning is a row somebody started and did not finish."""
    r = _psql(db, _insert(*_ANSWERED, amount="0"))
    assert r.returncode != 0
    assert "payroll_one_time_earning_is_an_amount" in r.stderr


def test_a_negative_amount_is_allowed_because_it_is_a_recovery(db):
    """Signed on purpose. Recovering an overpaid bonus is the same earning
    undone, so it must reduce the very bases it inflated — recording it as a
    deduction elsewhere would leave PF and ESI wages overstated."""
    assert _psql(db, _insert(*_ANSWERED, amount="-400000")).returncode == 0


# ─── 3. the month is a month ─────────────────────────────────────────────────

def test_a_mid_month_date_is_refused(db):
    """Payroll's grain is the month everywhere else in this schema. A stray day
    would split one month's earnings into a bucket the run never looks in."""
    r = _psql(db, _insert(*_ANSWERED, month="2026-08-15"))
    assert r.returncode != 0
    assert "payroll_one_time_earning_month_is_a_month" in r.stderr


def test_an_unknown_kind_is_refused(db):
    r = _psql(db, "INSERT INTO payroll_one_time_earnings "
                  "(firm_id, client_id, employee_id, month, kind, amount_paise, "
                  " pf_wages, esi_wages, taxable) VALUES "
                  f"('{FIRM}','{CLIENT}','{EMP}','2026-08-01','diwali',100,"
                  " false, false, true);")
    assert r.returncode != 0
    assert "payroll_one_time_earning_kind_is_known" in r.stderr


def test_an_interval_outside_one_to_twelve_is_refused(db):
    """ESI Act s.2(22)'s test reads this column; 0 and 13 are not intervals."""
    for bad in ("0", "13"):
        r = _psql(db, _insert("pf_wages, esi_wages, taxable, payment_interval_months",
                              f"false, false, true, {bad}"))
        assert r.returncode != 0, f"interval {bad} was accepted"
    assert _psql(db, _insert("pf_wages, esi_wages, taxable, payment_interval_months",
                             "false, true, true, 2")).returncode == 0


# ─── 4. who may write it ─────────────────────────────────────────────────────

def _as(dsn: str, who: str, sql: str) -> subprocess.CompletedProcess:
    """As the signed-in user, the way the frontend reaches this table.

    SET LOCAL ROLE authenticated matters: the table is owned by postgres and an
    owner BYPASSES RLS, so running these as the migration user would make every
    assertion below pass whatever the policies said. Rolled back so one test
    leaves nothing for the next.
    """
    return _psql(dsn, f"BEGIN; SET LOCAL ROLE authenticated; "
                      f"SET LOCAL request.jwt.claims = '{{\"sub\":\"{who}\"}}'; "
                      f"{sql} ROLLBACK;")


def _rows_changed(dsn: str, who: str, statement: str) -> int:
    r = _psql(dsn, f"BEGIN; SET LOCAL ROLE authenticated; "
                   f"SET LOCAL request.jwt.claims = '{{\"sub\":\"{who}\"}}'; "
                   f"WITH t AS ({statement} RETURNING 1) SELECT count(*) FROM t; "
                   f"ROLLBACK;", tuples=True)
    assert r.returncode == 0, r.stderr
    return int([ln for ln in r.stdout.strip().splitlines() if ln.strip()][-1])


def test_a_manager_can_record_an_earning(db):
    r = _as(db, MANAGER, _insert(*_ANSWERED))
    assert r.returncode == 0, r.stderr


def test_a_reviewer_cannot_record_an_earning(db):
    """RESTRICTIVE, so the role policy NARROWS the firm policy. A permissive one
    would OR with it and widen access — and read identically in pg_policies."""
    r = _as(db, REVIEWER, _insert(*_ANSWERED))
    assert r.returncode != 0, "a Reviewer wrote a row that decides somebody's pay"
    assert "row-level security" in r.stderr.lower() or "policy" in r.stderr.lower()


def test_a_reviewer_cannot_delete_an_earning(db):
    """A denied DELETE does not RAISE — PostgreSQL silently skips the rows that
    fail USING — so this asserts the ROW COUNT, not the return code. A test that
    asserted the return code here would pass against no policy at all."""
    assert _psql(db, _insert(*_ANSWERED)).returncode == 0
    assert _rows_changed(db, REVIEWER, "DELETE FROM payroll_one_time_earnings") == 0
    assert _rows_changed(db, MANAGER, "DELETE FROM payroll_one_time_earnings") == 1


# ─── 5. the slip carries what the run applied ────────────────────────────────

def test_the_slip_stores_the_total_and_both_statutory_bases(db):
    """Stored, not recomputed: the earning rows can be edited or deleted after a
    run and a released payslip has to keep saying what it said."""
    out = _psql(db,
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'payroll_slips' AND column_name IN "
                "('one_time_earnings_paise','one_time_pf_wages_paise',"
                " 'one_time_esi_wages_paise','one_time_taxable_paise') "
                "ORDER BY column_name;", tuples=True)
    assert out.stdout.split() == [
        "one_time_earnings_paise", "one_time_esi_wages_paise",
        "one_time_pf_wages_paise", "one_time_taxable_paise"]


def test_the_run_carries_the_month_s_one_time_total(db):
    out = _psql(db, "SELECT column_default, is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'payroll_runs' "
                    "AND column_name = 'total_one_time_paise';", tuples=True)
    assert out.stdout.strip() == "0|NO"


def test_deleting_an_employee_takes_their_earnings(db):
    """Scoped by foreign key, not by convention — an orphaned earning would be
    picked up by no run and reconciled by nobody."""
    assert _psql(db, _insert(*_ANSWERED)).returncode == 0
    assert _psql(db, f"DELETE FROM payroll_employees WHERE id = '{EMP}';").returncode == 0
    assert _psql(db, "SELECT count(*) FROM payroll_one_time_earnings;",
                 tuples=True).stdout.strip() == "0"
