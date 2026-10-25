"""Migration 499 — a signed-in session writes none of the payroll tables the browser never writes.

THE RULE, NOT A LIST OF TODAY'S TABLES (ledger POST-A-234)
    A payroll table is written from a signed-in session only if a screen in `apps/web` writes it. Today that is
    exactly two: an employee's own tax declaration with its items (the portal's declaration tab). It was three until
    migration 515 (POST-A-235): the attendance screen's leave-allotment upsert went behind `PUT /api/payroll/leave-balance`
    and `leave_balances` lost its signed-in write in that migration, which this file's database half now proves with the
    rest. Every other payroll table is read from the browser and written by the payroll router with the privileged
    client. Migration 499 revokes the write privileges on sixteen of them; before it, an assigned Manager could write a
    draft run and its payslips directly, and the finalise journal is built from the run's totals.

WHAT IS HELD
    * (no database) the browser's direct writes to payroll tables are exactly the two, so a new screen that writes a
      fourth fails here and has to decide, in the open, instead of finding the privilege already gone or already there;
    * (database) the payroll tables on which a signed-in role EFFECTIVELY holds a write privilege (table level, column
      level, or reaching the role through PUBLIC) are exactly those two, so a payroll table whose own migration grants
      a write to a signed-in role fails this, naming itself. It cannot see the privilege a hosting platform's default
      privileges would give a table created in production (the migration-built database carries none), so a new payroll
      table needs its own REVOKE in its migration;
    * (database) `service_role`, which the API uses, keeps INSERT, UPDATE and DELETE on every payroll table, and INSERT on
      the append-only release log;
    * (database) an assigned Manager is refused a direct write by the PRIVILEGE ("permission denied for table <the
      table>"), and reads are unaffected; the explicit-grid-grant variant of this is in
      test_the_per_person_grid_reaches_the_database_pg.py;
    * (database) the two tables the browser writes still hold INSERT and UPDATE for a signed-in role, and a Manager can
      still insert into the declaration table;
    * (database) the migration is idempotent, REMOVES what the hosting platform's defaults give (TRUNCATE for
      `authenticated` and `anon`, and a write reaching a role through PUBLIC or through a column grant), and its own
      rollback puts the holes back (the negative control).

Runs only when HARNESS_PG is set + psql on PATH (the source scan runs always).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))      # a sibling test module, imported by name as others do
from test_direct_write_tables_are_role_guarded import _direct_write_tables  # noqa: E402

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATIONS = API_ROOT / "migrations"
_STEM = "499_a_signed_in_session_writes_none_of_the_payroll_tables_the_browser_never_writes"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

#: What the browser writes among the payroll tables. Add to it only with a decision about who may write the table and
#: why it cannot go through the API. EMPTY since 25-10-2026 (POST-A-010): the employee portal's tax-declaration tab was the
#: last writer and now files through `PUT /api/portal/employee/tax-declaration`.
WRITTEN_BY_THE_BROWSER: set[str] = set()

#: The payroll tables a signed-in role still holds a write privilege on. It is the two declaration tables, left granted by
#: migration 499 because the browser wrote them, and NO SCREEN USES IT NOW: the privilege and the employee-own-record policies
#: behind it are revoked by POST-A-339, which is a migration this change does not make. Until then a hand-made PostgREST call
#: with an employee's own token can still write their own declaration, exactly as before, and these tests keep saying so.
STILL_GRANTED_TO_A_SIGNED_IN_ROLE = {"payroll_it_declarations", "payroll_it_declaration_items"}

#: The payroll family: every `payroll_*` table, plus the ones named for their job and not their prefix.
_FAMILY = re.compile(r"^(payroll_.+|attendance|leave_balances|bonus_declarations|bonus_disqualifications|"
                     r"salary_structures|statutory_remittances|epfo_ecr_filings)$")

_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the payroll write-privilege proofs require HARNESS_PG + psql",
)


# ── no database: the browser's own writes ─────────────────────────────────────────────────────────────────────────
def test_the_browser_writes_exactly_these_payroll_tables():
    found = {t for t in _direct_write_tables() if _FAMILY.match(t)}
    assert found == WRITTEN_BY_THE_BROWSER, (
        f"the payroll tables apps/web writes straight over PostgREST are {sorted(found)}, not "
        f"{sorted(WRITTEN_BY_THE_BROWSER)}. A table the browser writes needs its signed-in write privilege and a role "
        "rule, a table it does not write should have neither (migration 499). Decide which, and change this set, the "
        "migration and the Team screen's notice together.")


def test_the_family_pattern_names_the_tables_the_migration_revokes():
    sql = MIGRATION.read_text(encoding="utf-8")
    revoked = set(re.findall(r"'([a-z_]+)'", sql.split("tables text[] := ARRAY[", 1)[1].split("]", 1)[0]))
    assert len(revoked) == 17, revoked
    assert all(_FAMILY.match(t) for t in revoked), sorted(t for t in revoked if not _FAMILY.match(t))
    assert not revoked & STILL_GRANTED_TO_A_SIGNED_IN_ROLE


# ── the database ────────────────────────────────────────────────────────────────────────────────────────────────────
FIRM = "aaaaaaaa-0000-0000-0000-000000000499"
CLIENT = "cccccccc-0000-0000-0000-00000000a499"
MANAGER_AUTH = "11111111-1111-1111-1111-000000000499"
MANAGER_USER = "bbbbbbbb-1111-1111-1111-000000000499"


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _as_manager(dsn: str, sql: str) -> subprocess.CompletedProcess:
    claims = json.dumps({"sub": MANAGER_AUTH, "role": "authenticated"})
    return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"payrollwrite_m499_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{MANAGER_AUTH}', 'manager@m499.test');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M499 Firm','m499@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{MANAGER_USER}', '{FIRM}', '{MANAGER_AUTH}', 'manager@m499.test', 'M', 'Manager', true);
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','Client A','Private Limited');
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES ('{FIRM}', '{MANAGER_USER}', '{CLIENT}');
            INSERT INTO payroll_employees (firm_id, client_id, name) VALUES ('{FIRM}', '{CLIENT}', 'Employee');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _writable_by_a_signed_in_role(dsn: str) -> set[str]:
    """Payroll-family tables on which `authenticated` or `anon` EFFECTIVELY holds a write privilege: at table level, at
    column level, or through PUBLIC (has_table_privilege / has_any_column_privilege see all three; a look at
    information_schema.role_table_grants for the two role names sees only the first)."""
    rows = _ok(dsn, """
        SELECT c.relname
          FROM pg_class c
          CROSS JOIN (VALUES ('authenticated'), ('anon')) AS r(name)
         WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
           AND (has_table_privilege(r.name, c.oid, 'INSERT') OR has_table_privilege(r.name, c.oid, 'UPDATE')
                OR has_table_privilege(r.name, c.oid, 'DELETE') OR has_table_privilege(r.name, c.oid, 'TRUNCATE')
                OR has_any_column_privilege(r.name, c.oid, 'INSERT') OR has_any_column_privilege(r.name, c.oid, 'UPDATE'))
         GROUP BY c.relname;""").splitlines()
    return {r for r in rows if _FAMILY.match(r)}


@_NEEDS_PG
def test_a_signed_in_role_writes_exactly_the_payroll_tables_the_browser_writes(db):
    got = _writable_by_a_signed_in_role(db)
    assert got == STILL_GRANTED_TO_A_SIGNED_IN_ROLE, (
        f"signed-in roles hold a write privilege on {sorted(got - STILL_GRANTED_TO_A_SIGNED_IN_ROLE)} and lack it on "
        f"{sorted(STILL_GRANTED_TO_A_SIGNED_IN_ROLE - got)}. A payroll table the browser does not write must not be writable "
        "from a signed-in session: REVOKE it (migration 499 is the pattern), or declare the browser write.")


@_NEEDS_PG
def test_the_family_pattern_finds_the_tables_it_is_meant_to_guard(db):
    """Vacuity guard: the rule above is only as wide as the pattern."""
    family = set(_ok(db, "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace "
                         "AND relkind = 'r';").splitlines())
    family = {t for t in family if _FAMILY.match(t)}
    assert len(family) >= 20, sorted(family)
    assert {"payroll_runs", "payroll_slips", "payroll_employees", "attendance", "leave_balances"} <= family


@_NEEDS_PG
def test_the_api_keeps_its_write_privileges_on_every_payroll_table(db):
    """Migration 499 names `authenticated`, `anon` and PUBLIC, so the API's own privileges are untouched. The release log
    is asked INSERT alone because that is all the API does to it (it is append-only by design; migration 328 revoked UPDATE
    and DELETE from `authenticated`, and `service_role` holds them through migration 269's default privileges)."""
    tables = sorted(t for t in _ok(db, "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace "
                                       "AND relkind = 'r';").splitlines() if _FAMILY.match(t))
    lacking = []
    for t in tables:
        verbs = ("INSERT",) if t == "payroll_run_transitions" else ("INSERT", "UPDATE", "DELETE")
        for verb in verbs:
            if _ok(db, f"SELECT has_table_privilege('service_role', 'public.{t}', '{verb}');") != "t":
                lacking.append(f"{t}:{verb}")
    assert not lacking, f"service_role lacks a write privilege the API needs: {lacking}"


PROBES = {
    "payroll_runs": "INSERT INTO payroll_runs (firm_id, client_id, month) VALUES ('{f}', '{c}', '2026-05');",
    "payroll_slips": ("INSERT INTO payroll_slips (run_id, employee_id, gross_paise, net_paise) "
                      "SELECT 'dddddddd-0000-0000-0000-000000000499', id, 1, 1 FROM payroll_employees;"),
    "payroll_employees": "INSERT INTO payroll_employees (firm_id, client_id, name) VALUES ('{f}', '{c}', 'E2');",
    "payroll_run_transitions": ("INSERT INTO payroll_run_transitions (firm_id, run_id, to_status) "
                                "SELECT '{f}', id, 'draft' FROM payroll_runs LIMIT 1;"),
    "salary_structures": "INSERT INTO salary_structures (firm_id, client_id, name) VALUES ('{f}', '{c}', 'S');",
    "attendance": ("INSERT INTO attendance (firm_id, employee_id, month, year) "
                   "SELECT '{f}', id, 4, 2026 FROM payroll_employees;"),
}


@_NEEDS_PG
@pytest.mark.parametrize("table", sorted(PROBES))
def test_a_manager_inside_the_tier_is_refused_by_the_privilege(db, table):
    # the run is seeded as the admin, so every probe is ONE statement and reaches the table it names
    _ok(db, f"INSERT INTO payroll_runs (id, firm_id, client_id, month) VALUES "
            f"('dddddddd-0000-0000-0000-000000000499', '{FIRM}', '{CLIENT}', '2026-04');")
    r = _as_manager(db, PROBES[table].format(f=FIRM, c=CLIENT))
    assert r.returncode != 0 and f"permission denied for table {table}" in r.stderr, (
        f"{table}: a signed-in Manager wrote a payroll table the browser never writes: {r.stderr or 'it succeeded'}")


@_NEEDS_PG
def test_reading_is_unaffected(db):
    r = _as_manager(db, "SELECT count(*) FROM payroll_employees;")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "1"


@_NEEDS_PG
def test_the_tables_the_browser_does_write_are_still_writable_by_a_manager(db):
    decl = _as_manager(db, f"INSERT INTO payroll_it_declarations (firm_id, client_id, employee_id, fy) "
                           f"SELECT '{FIRM}', '{CLIENT}', id, '2026-27' FROM payroll_employees;")
    assert decl.returncode == 0, decl.stderr


@_NEEDS_PG
def test_the_tables_the_browser_writes_still_hold_insert_and_update_for_a_signed_in_role(db):
    """The revoke did not overreach: an employee's own declaration needs INSERT and UPDATE on the declaration and its
    items. (`leave_balances` is no longer one of them: migration 515, proved in its own test file.)"""
    for t in sorted(STILL_GRANTED_TO_A_SIGNED_IN_ROLE):
        for verb in ("INSERT", "UPDATE"):
            assert _ok(db, f"SELECT has_table_privilege('authenticated', 'public.{t}', '{verb}');") == "t", (t, verb)


@_NEEDS_PG
def test_499_removes_what_the_hosting_platform_grants_and_what_reaches_a_role_another_way(db):
    """The throwaway database holds none of the platform's default privileges, so the TRUNCATE half and the `anon` half of
    the REVOKE would otherwise be exercised by nothing. Give them, plus a write through PUBLIC and one through a column
    grant (neither visible to a look at the two role names), then apply the migration."""
    _ok(db, """
        GRANT TRUNCATE, REFERENCES, TRIGGER ON public.payroll_runs, public.attendance, public.epfo_ecr_filings
              TO authenticated, anon;
        GRANT INSERT, UPDATE, DELETE, TRUNCATE ON public.payroll_loans TO anon;
        GRANT INSERT ON public.payroll_slips TO PUBLIC;
        GRANT UPDATE (net_paise) ON public.payroll_slips TO authenticated;
    """)
    before = _writable_by_a_signed_in_role(db) - STILL_GRANTED_TO_A_SIGNED_IN_ROLE
    assert {"payroll_runs", "attendance", "epfo_ecr_filings", "payroll_loans", "payroll_slips"} <= before, before
    r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    assert _writable_by_a_signed_in_role(db) == STILL_GRANTED_TO_A_SIGNED_IN_ROLE
    # what is not a write is left alone
    assert _ok(db, "SELECT has_table_privilege('anon', 'public.payroll_runs', 'REFERENCES');") == "t"


@_NEEDS_PG
def test_the_closing_check_fails_the_migration_when_a_write_cannot_be_revoked(db):
    """A privilege the migration's own REVOKE cannot remove must fail the migration, not let it finish green with a table
    still writable. The REVOKE runs as the object's owner and removes what the OWNER granted; a grant made by another
    grantor (a role holding GRANT OPTION) is not the owner's to take back."""
    grantor = f"m499_g_{uuid.uuid4().hex[:8]}"
    _ok(db, f"""
        CREATE ROLE {grantor} NOLOGIN;
        GRANT INSERT ON public.payroll_runs TO {grantor} WITH GRANT OPTION;
        SET ROLE {grantor};
        GRANT INSERT ON public.payroll_runs TO authenticated;
        RESET ROLE;
    """)
    try:
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
        assert r.returncode != 0 and "migration 499: authenticated still holds INSERT on payroll_runs" in r.stderr, (
            r.stdout, r.stderr)
    finally:
        _psql(db, f"DROP OWNED BY {grantor}; DROP ROLE IF EXISTS {grantor};")


@_NEEDS_PG
def test_499_is_idempotent(db):
    for _ in range(2):
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
        assert r.returncode == 0, r.stderr
    assert _writable_by_a_signed_in_role(db) == STILL_GRANTED_TO_A_SIGNED_IN_ROLE


@_NEEDS_PG
def test_its_own_rollback_puts_the_holes_back(db):
    """The negative control: without the revoke the statements refused above go through."""
    r = _psql(db, ROLLBACK.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    reopened = _writable_by_a_signed_in_role(db) - STILL_GRANTED_TO_A_SIGNED_IN_ROLE
    assert len(reopened) == 17, sorted(reopened)
    # EVERY probe goes through once the privilege is back, so each refusal above is the privilege and not a statement
    # that was malformed or stopped by a policy on the way
    _ok(db, f"INSERT INTO payroll_runs (id, firm_id, client_id, month) VALUES "
            f"('dddddddd-0000-0000-0000-000000000499', '{FIRM}', '{CLIENT}', '2026-04');")
    for table in sorted(PROBES):
        again = _as_manager(db, PROBES[table].format(f=FIRM, c=CLIENT))
        assert again.returncode == 0, (table, again.stderr)
