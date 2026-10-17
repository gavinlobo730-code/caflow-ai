"""Migration 500 — a signed-in session reaches the Form 3CD checklist table not at all (ledger POST-A-233).

WHAT IS HELD (the route's approver rule is in test_a_form_3cd_checklist_is_finalised_only_by_an_approver.py)
    * `authenticated` and `anon` hold no privilege on `tax_audit_checklists`, and `service_role` (the API) keeps all four;
    * a signed-in Manager, inside the assignment, is refused a read and a write by the PRIVILEGE ("permission denied for
      table"), which is what a row policy alone could not say (it would have let the status through);
    * the row policies (014 and the assignment scope of 084) are still there as the second lock;
    * the migration is idempotent, and its own rollback puts the hole back (the negative control).

Runs only when HARNESS_PG is set + psql on PATH.
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
_STEM = "500_the_form_3cd_checklist_is_reached_only_through_the_server"
MIGRATION = API_ROOT / "migrations" / f"{_STEM}.sql"
ROLLBACK = API_ROOT / "migrations" / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the checklist privilege proofs require HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000500"
CLIENT = "cccccccc-0000-0000-0000-00000000a500"
MANAGER_AUTH = "11111111-1111-1111-1111-000000000500"
MANAGER_USER = "bbbbbbbb-1111-1111-1111-000000000500"
TABLE = "tax_audit_checklists"


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
    dbname = f"checklist_m500_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{MANAGER_AUTH}', 'manager@m500.test');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M500 Firm','m500@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{MANAGER_USER}', '{FIRM}', '{MANAGER_AUTH}', 'manager@m500.test', 'M', 'Manager', true);
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','Client A','Private Limited');
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES ('{FIRM}', '{MANAGER_USER}', '{CLIENT}');
            INSERT INTO {TABLE} (firm_id, client_id, financial_year, status) VALUES ('{FIRM}', '{CLIENT}', '2025-26', 'draft');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _holds(dsn: str, role: str, op: str) -> bool:
    return _ok(dsn, f"SELECT has_table_privilege('{role}', 'public.{TABLE}', '{op}');") == "t"


def test_no_signed_in_or_anonymous_role_holds_a_privilege_and_the_api_keeps_its_own(db):
    for role in ("authenticated", "anon"):
        for op in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            assert not _holds(db, role, op), f"{role} holds {op} on {TABLE}"
    for op in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert _holds(db, "service_role", op), f"service_role lost {op} on {TABLE}"


def test_a_manager_inside_the_assignment_is_refused_by_the_privilege(db):
    for sql in (f"SELECT count(*) FROM {TABLE};",
                f"UPDATE {TABLE} SET status = 'finalised';",
                f"INSERT INTO {TABLE} (firm_id, client_id, financial_year) VALUES ('{FIRM}', '{CLIENT}', '2024-25');",
                f"DELETE FROM {TABLE};"):
        r = _as_manager(db, sql)
        assert r.returncode != 0 and "permission denied for table" in r.stderr, (sql, r.stderr or "it succeeded")
    assert _ok(db, f"SELECT status FROM {TABLE};") == "draft"


def test_the_row_policies_are_still_the_second_lock(db):
    assert _ok(db, f"SELECT count(*) FROM pg_policies WHERE schemaname = 'public' AND tablename = '{TABLE}' "
                   "AND policyname IN ('tax_audit_own_firm', 'tax_audit_checklists_assignment_scope');") == "2"
    assert _ok(db, f"SELECT relrowsecurity FROM pg_class WHERE oid = 'public.{TABLE}'::regclass;") == "t"


def test_500_removes_what_the_platform_grants_and_what_reaches_a_role_another_way(db):
    """The throwaway database holds none of the platform's default privileges, so the TRUNCATE half and the `anon` half of
    the REVOKE would otherwise be exercised by nothing. Give them, plus a read through PUBLIC and a write through a column
    grant (neither visible to a look at the two role names), then apply the migration."""
    _ok(db, f"""
        GRANT TRUNCATE, REFERENCES, TRIGGER ON public.{TABLE} TO authenticated, anon;
        GRANT SELECT, INSERT, UPDATE, DELETE ON public.{TABLE} TO anon;
        GRANT SELECT ON public.{TABLE} TO PUBLIC;
        GRANT UPDATE (status) ON public.{TABLE} TO authenticated;
    """)
    assert _holds(db, "anon", "TRUNCATE") and _holds(db, "authenticated", "SELECT")
    r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    for role in ("authenticated", "anon"):
        for op in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            assert not _holds(db, role, op), f"{role} still holds {op}"
        assert _ok(db, f"SELECT has_any_column_privilege('{role}', 'public.{TABLE}', 'UPDATE');") == "f"
    assert _holds(db, "service_role", "UPDATE")


def test_the_closing_check_fails_the_migration_when_a_privilege_cannot_be_revoked(db):
    """A grant made by another grantor (a role holding GRANT OPTION) is not the owner's to take back; the migration must
    fail, and so the deploy, not finish green with the table still reachable."""
    grantor = f"m500_g_{uuid.uuid4().hex[:8]}"
    _ok(db, f"""
        CREATE ROLE {grantor} NOLOGIN;
        GRANT SELECT ON public.{TABLE} TO {grantor} WITH GRANT OPTION;
        SET ROLE {grantor};
        GRANT SELECT ON public.{TABLE} TO authenticated;
        RESET ROLE;
    """)
    try:
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
        assert r.returncode != 0 and f"migration 500: authenticated still holds SELECT on {TABLE}" in r.stderr, (
            r.stdout, r.stderr)
    finally:
        _psql(db, f"DROP OWNED BY {grantor}; DROP ROLE IF EXISTS {grantor};")


def test_500_is_idempotent(db):
    for _ in range(2):
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
        assert r.returncode == 0, r.stderr
    assert not _holds(db, "authenticated", "SELECT")


def test_its_own_rollback_puts_the_hole_back(db):
    """The negative control: without the revoke the statements refused above go through."""
    r = _psql(db, ROLLBACK.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    assert _as_manager(db, f"SELECT count(*) FROM {TABLE};").returncode == 0
    wrote = _as_manager(db, f"UPDATE {TABLE} SET status = 'finalised';")
    assert wrote.returncode == 0, wrote.stderr
    assert _ok(db, f"SELECT status FROM {TABLE};") == "finalised"
