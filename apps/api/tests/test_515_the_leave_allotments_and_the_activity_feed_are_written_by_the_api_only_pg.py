"""Migration 515 — the leave allotments and the client activity feed are written by the API, and by nobody signed in.

WHAT IS HELD (ledger POST-A-235 and POST-A-228)
    * a signed-in role EFFECTIVELY holds no INSERT, UPDATE, DELETE or TRUNCATE on `leave_balances`, and no INSERT or TRUNCATE
      on `client_timeline_events`, at table level, at column level or through PUBLIC; reading both is unaffected, and the
      feed's pin button (a column-level UPDATE on `is_pinned`, migration 494) is still there;
    * `service_role`, which the API uses, keeps its writes;
    * an assigned Manager is refused a direct write by the PRIVILEGE ("permission denied for table ..."), not by a policy;
    * the migration removes what the hosting platform's defaults give and what reaches a role another way, fails itself when
      a write cannot be revoked, skips a table that does not exist, and is idempotent;
    * its own rollback puts the grants back, which is the negative control: with them back the same statements go through.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_STEM = "515_the_leave_allotments_and_the_activity_feed_are_written_by_the_api_only"
MIGRATION = API_ROOT / "migrations" / f"{_STEM}.sql"
ROLLBACK = API_ROOT / "migrations" / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the privilege proofs require HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000515"
CLIENT = "cccccccc-0000-0000-0000-00000000a515"
MANAGER_AUTH = "11111111-1111-1111-1111-000000000515"
MANAGER_USER = "bbbbbbbb-1111-1111-1111-000000000515"
EMPLOYEE = "eeeeeeee-0000-0000-0000-000000000515"
EVENT = "dddddddd-0000-0000-0000-000000000515"
LEAVE_WRITES = ("INSERT", "UPDATE", "DELETE", "TRUNCATE")
FEED_WRITES = ("INSERT", "TRUNCATE")


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
    dbname = f"leavefeed_m515_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{MANAGER_AUTH}', 'manager@m515.test');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M515 Firm','m515@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{MANAGER_USER}', '{FIRM}', '{MANAGER_AUTH}', 'manager@m515.test', 'M', 'Manager', true);
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','Client A','Private Limited');
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES ('{FIRM}', '{MANAGER_USER}', '{CLIENT}');
            INSERT INTO payroll_employees (id, firm_id, client_id, name) VALUES ('{EMPLOYEE}', '{FIRM}', '{CLIENT}', 'Employee');
            INSERT INTO leave_balances (firm_id, employee_id, year, casual_leave_balance) VALUES ('{FIRM}', '{EMPLOYEE}', 2026, 12);
            INSERT INTO client_timeline_events (id, firm_id, client_id, financial_year, category, event_type, title)
              VALUES ('{EVENT}','{FIRM}','{CLIENT}','2026-27','general','note','Original title');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _holds(dsn: str, role: str, table: str, verb: str) -> bool:
    return _ok(dsn, f"SELECT has_table_privilege('{role}', 'public.{table}', '{verb}');") == "t"


def _holds_a_column_write(dsn: str, role: str, table: str, verb: str) -> bool:
    return _ok(dsn, f"SELECT has_any_column_privilege('{role}', 'public.{table}', '{verb}');") == "t"


@_NEEDS_PG
@pytest.mark.parametrize("role", ["authenticated", "anon"])
def test_a_signed_in_role_holds_no_write_on_the_leave_allotments(db, role):
    for verb in LEAVE_WRITES:
        assert not _holds(db, role, "leave_balances", verb), (role, verb)
    assert not _holds_a_column_write(db, role, "leave_balances", "INSERT")
    assert not _holds_a_column_write(db, role, "leave_balances", "UPDATE")


@_NEEDS_PG
@pytest.mark.parametrize("role", ["authenticated", "anon"])
def test_a_signed_in_role_cannot_insert_into_the_feed(db, role):
    for verb in FEED_WRITES:
        assert not _holds(db, role, "client_timeline_events", verb), (role, verb)
    assert not _holds_a_column_write(db, role, "client_timeline_events", "INSERT")


@_NEEDS_PG
def test_the_pin_button_and_reading_are_unaffected(db):
    """The revoke did not overreach: the feed's pin is a column-level UPDATE on is_pinned (migration 494) and both tables are
    still read by a signed-in session."""
    assert _ok(db, "SELECT has_column_privilege('authenticated','public.client_timeline_events','is_pinned','UPDATE');") == "t"
    assert not _holds(db, "authenticated", "client_timeline_events", "UPDATE")
    pinned = _as_manager(db, f"UPDATE client_timeline_events SET is_pinned = true WHERE id = '{EVENT}';")
    assert pinned.returncode == 0, pinned.stderr
    assert _ok(db, f"SELECT is_pinned FROM client_timeline_events WHERE id = '{EVENT}';") == "t"
    for table in ("leave_balances", "client_timeline_events"):
        assert _holds(db, "authenticated", table, "SELECT"), table
    seen = _as_manager(db, "SELECT count(*) FROM leave_balances;")
    assert seen.returncode == 0 and seen.stdout.strip().splitlines()[-1] == "1", seen.stderr


@_NEEDS_PG
def test_the_api_keeps_its_writes(db):
    for verb in ("INSERT", "UPDATE", "DELETE"):
        assert _holds(db, "service_role", "leave_balances", verb), verb
    assert _holds(db, "service_role", "client_timeline_events", "INSERT")


PROBES = {
    "leave_balances": ("INSERT INTO leave_balances (firm_id, employee_id, year, sick_leave_balance) "
                       f"VALUES ('{FIRM}', '{EMPLOYEE}', 2027, 10);"),
    "leave_balances (update)": "UPDATE leave_balances SET casual_leave_balance = 99;",
    "leave_balances (delete)": "DELETE FROM leave_balances;",
    "client_timeline_events": ("INSERT INTO client_timeline_events (firm_id, client_id, financial_year, category, event_type, "
                               f"title, actor_name) VALUES ('{FIRM}','{CLIENT}','2026-27','general','note','Forged','Somebody else');"),
}


@_NEEDS_PG
@pytest.mark.parametrize("probe", sorted(PROBES))
def test_an_assigned_manager_is_refused_by_the_privilege(db, probe):
    table = probe.split(" ")[0]
    r = _as_manager(db, PROBES[probe])
    assert r.returncode != 0 and f"permission denied for table {table}" in r.stderr, (probe, r.stderr or "it succeeded")


@_NEEDS_PG
def test_515_removes_what_the_platform_grants_and_what_reaches_a_role_another_way(db):
    """The throwaway database holds none of the platform's default privileges, and a write through PUBLIC or through a column
    grant is invisible to a look at the two role names. Give them all, then apply the migration."""
    _ok(db, """
        GRANT TRUNCATE ON public.leave_balances, public.client_timeline_events TO authenticated, anon;
        GRANT INSERT, UPDATE, DELETE ON public.leave_balances TO anon;
        GRANT INSERT ON public.client_timeline_events TO PUBLIC;
        GRANT UPDATE (year) ON public.leave_balances TO authenticated;
        GRANT INSERT (title) ON public.client_timeline_events TO anon;
    """)
    assert _holds(db, "authenticated", "client_timeline_events", "INSERT")
    r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    for role in ("authenticated", "anon"):
        for verb in LEAVE_WRITES:
            assert not _holds(db, role, "leave_balances", verb), (role, verb)
        for verb in FEED_WRITES:
            assert not _holds(db, role, "client_timeline_events", verb), (role, verb)
        assert not _holds_a_column_write(db, role, "leave_balances", "UPDATE")
        assert not _holds_a_column_write(db, role, "client_timeline_events", "INSERT")
    # the pin button survived
    assert _ok(db, "SELECT has_column_privilege('authenticated','public.client_timeline_events','is_pinned','UPDATE');") == "t"


@_NEEDS_PG
def test_the_closing_check_fails_the_migration_when_a_write_cannot_be_revoked(db):
    """A grant the migration's own REVOKE cannot remove (made by another grantor holding GRANT OPTION) must fail the
    migration, not let it finish green with a table still writable."""
    grantor = f"m515_g_{uuid.uuid4().hex[:8]}"
    _ok(db, f"""
        CREATE ROLE {grantor} NOLOGIN;
        GRANT INSERT ON public.client_timeline_events TO {grantor} WITH GRANT OPTION;
        SET ROLE {grantor};
        GRANT INSERT ON public.client_timeline_events TO authenticated;
        RESET ROLE;
    """)
    try:
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
        assert r.returncode != 0 and "migration 515: authenticated still holds INSERT on client_timeline_events" in r.stderr, (
            r.stdout, r.stderr)
    finally:
        _psql(db, f"DROP OWNED BY {grantor}; DROP ROLE IF EXISTS {grantor};")


@_NEEDS_PG
def test_a_table_that_does_not_exist_is_skipped_not_fatal(db):
    """A scratch database that stops part-way (070, 071 and 095 are on the runner's baseline-failure list) may lack a table;
    the migration asks to_regclass first."""
    _ok(db, "DROP TABLE public.leave_balances CASCADE;")
    r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr


@_NEEDS_PG
def test_515_is_idempotent(db):
    for _ in range(2):
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
        assert r.returncode == 0, r.stderr
    assert not _holds(db, "authenticated", "leave_balances", "INSERT")


@_NEEDS_PG
def test_its_own_rollback_puts_the_grants_back(db):
    """The negative control: with the grants back, the statements refused above go through, so each refusal was the
    privilege and not a statement that was malformed or stopped by a policy."""
    r = _psql(db, ROLLBACK.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    leave = _as_manager(db, PROBES["leave_balances"])
    assert leave.returncode == 0, leave.stderr
    feed = _as_manager(db, PROBES["client_timeline_events"])
    assert feed.returncode == 0, feed.stderr
