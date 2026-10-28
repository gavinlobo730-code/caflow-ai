"""Migration 554 — the two declaration guard triggers ask the per-person grid who is staff (ledger POST-A-219, the part 519 left open).

WHAT IS HELD
    * A Manager whom a Partner has blocked from payroll:write, and who is ALSO the linked principal of an employee row, is refused when
      they write the verified columns of their OWN declaration or of one of its items (the finding: the triggers opened with
      `my_role_at_least('Manager')`, so the guard did not run for them while the policies, which ask the grid since 519, let them write
      through the employee arm). The rollback puts the old answer back, which is the negative control.
    * THE FLOOR IS UNCHANGED: a Manager with no grid row is staff to the guard and may write those columns, as before; the employee
      who is not staff is refused, as before; the service role (no auth.uid(), which is how the API and the migrations write) is let
      through, as before.
    * The other direction, stated so nobody is surprised by it: someone BELOW Manager whom the grid grants payroll:write is staff to
      the guard, as they are to the policies.
    * Neither function mentions the role any more.

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

from tests._signed_in_payroll_writes import give_the_signed_in_payroll_access_back

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_STEM = "554_the_declaration_guard_triggers_ask_the_grid_for_staff"
MIGRATION = API_ROOT / "migrations" / f"{_STEM}.sql"
ROLLBACK = API_ROOT / "migrations" / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the trigger proofs require HARNESS_PG + psql",
)

FIRM = "55400000-0000-0000-0000-000000000001"
CLIENT = "55400000-0000-0000-0000-0000000000c1"
PARTNER, MANAGER, EXECUTIVE = (f"55400000-0000-0000-0000-00000000000{c}" for c in "abe")
AUTH_PARTNER, AUTH_MANAGER, AUTH_EXECUTIVE, AUTH_EMPLOYEE = (f"55400000-1111-0000-0000-00000000000{c}" for c in "abef")
# Three employee rows: a plain employee, the Manager as an employee, the Executive as an employee, each with a declaration and a line.
EMP = {"plain": "55400000-0000-0000-0000-0000000000e1", "manager": "55400000-0000-0000-0000-0000000000e2",
       "executive": "55400000-0000-0000-0000-0000000000e3"}
DECL = {"plain": "55400000-0000-0000-0000-0000000000d1", "manager": "55400000-0000-0000-0000-0000000000d2",
        "executive": "55400000-0000-0000-0000-0000000000d3"}
ITEM = {"plain": "55400000-0000-0000-0000-0000000000f1", "manager": "55400000-0000-0000-0000-0000000000f2",
        "executive": "55400000-0000-0000-0000-0000000000f3"}
WHO = {"plain": AUTH_EMPLOYEE, "manager": AUTH_MANAGER, "executive": AUTH_EXECUTIVE}


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-f", "-"], input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _as(dsn: str, auth: str, sql: str) -> subprocess.CompletedProcess:
    claims = json.dumps({"sub": auth, "role": "authenticated"})
    return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"decl_m554_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        assert f"{_STEM}.sql" not in pg_template.failed, "migration 554 did not apply, so everything below would pass vacuously"
        rows = "".join(f"""
            INSERT INTO payroll_employees (id, firm_id, client_id, name, auth_user_id, portal_enabled)
              VALUES ('{EMP[k]}','{FIRM}','{CLIENT}','Employee {k}','{WHO[k]}',true);
            INSERT INTO payroll_it_declarations (id, firm_id, client_id, employee_id, fy, regime, status, rent_paid_declared_paise)
              VALUES ('{DECL[k]}','{FIRM}','{CLIENT}','{EMP[k]}','2026-27','old','submitted',100);
            INSERT INTO payroll_it_declaration_items (id, firm_id, declaration_id, section, label, amount_declared_paise)
              VALUES ('{ITEM[k]}','{FIRM}','{DECL[k]}','80C','PPF',100);""" for k in EMP)
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES
              ('{AUTH_PARTNER}','p@m554.test'), ('{AUTH_MANAGER}','m@m554.test'),
              ('{AUTH_EXECUTIVE}','e@m554.test'), ('{AUTH_EMPLOYEE}','emp@m554.test');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M554 Firm','m554@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES
              ('{PARTNER}','{FIRM}','{AUTH_PARTNER}','p@m554.test','P','Partner',true),
              ('{MANAGER}','{FIRM}','{AUTH_MANAGER}','m@m554.test','M','Manager',true),
              ('{EXECUTIVE}','{FIRM}','{AUTH_EXECUTIVE}','e@m554.test','E','Executive',true);
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','Client A','Private Limited');
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES
              ('{FIRM}','{PARTNER}','{CLIENT}'), ('{FIRM}','{MANAGER}','{CLIENT}'), ('{FIRM}','{EXECUTIVE}','{CLIENT}');
            {rows}
        """)
        assert seed.returncode == 0, seed.stderr
        give_the_signed_in_payroll_access_back(dsn)
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _block(dsn: str, user: str, granted: bool) -> None:
    _ok(dsn, f"""INSERT INTO user_permissions (firm_id, user_id, resource, action, granted)
                 VALUES ('{FIRM}','{user}','payroll','write',{str(granted).lower()})
                 ON CONFLICT (user_id, resource, action) DO UPDATE SET granted = EXCLUDED.granted;""")


def _verify_header(k: str) -> str:
    return (f"UPDATE payroll_it_declarations SET rent_paid_verified_paise = 50 WHERE id = '{DECL[k]}'; "
            f"SELECT count(*) FROM payroll_it_declarations WHERE rent_paid_verified_paise = 50;")


def _verify_line(k: str) -> str:
    return (f"UPDATE payroll_it_declaration_items SET amount_verified_paise = 50 WHERE id = '{ITEM[k]}'; "
            f"SELECT count(*) FROM payroll_it_declaration_items WHERE amount_verified_paise = 50;")


def _refused_by_the_guard(r: subprocess.CompletedProcess) -> bool:
    return r.returncode != 0 and "may declare an amount but not verify it" in r.stderr


def _landed(r: subprocess.CompletedProcess) -> bool:
    return r.returncode == 0 and r.stdout.strip().splitlines()[-1].strip() == "1"


@_NEEDS_PG
@pytest.mark.parametrize("write", [_verify_header, _verify_line], ids=["declaration", "line"])
def test_a_manager_the_grid_has_blocked_is_not_staff_to_the_guard_on_their_own_row(db, write):
    _block(db, MANAGER, False)
    r = _as(db, AUTH_MANAGER, write("manager"))
    assert _refused_by_the_guard(r), r.stderr or r.stdout


@_NEEDS_PG
@pytest.mark.parametrize("write", [_verify_header, _verify_line], ids=["declaration", "line"])
def test_the_floor_is_unchanged_a_manager_with_no_grid_row_is_staff_to_the_guard(db, write):
    assert _landed(_as(db, AUTH_MANAGER, write("manager")))


@_NEEDS_PG
@pytest.mark.parametrize("write", [_verify_header, _verify_line], ids=["declaration", "line"])
def test_an_employee_who_is_not_staff_is_refused_as_before_and_the_service_role_is_let_through(db, write):
    assert _refused_by_the_guard(_as(db, AUTH_EMPLOYEE, write("plain")))
    r = _psql(db, write("plain"))                       # no JWT: the role the API and the migrations write as
    assert _landed(r), r.stderr


@_NEEDS_PG
@pytest.mark.parametrize("write", [_verify_header, _verify_line], ids=["declaration", "line"])
def test_someone_below_manager_is_staff_to_the_guard_only_while_the_grid_says_they_may_write_payroll(db, write):
    assert _refused_by_the_guard(_as(db, AUTH_EXECUTIVE, write("executive"))), "no grid row: an Executive is not staff"
    _block(db, EXECUTIVE, True)
    assert _landed(_as(db, AUTH_EXECUTIVE, write("executive"))), "the grid grants payroll:write, as it does for the policies"


@_NEEDS_PG
def test_a_blocked_manager_still_declares_their_own_amounts(db):
    """The guard stops VERIFYING, not declaring: the employee arm of the policy is what lets a blocked Manager declare."""
    _block(db, MANAGER, False)
    r = _as(db, AUTH_MANAGER, f"UPDATE payroll_it_declarations SET rent_paid_declared_paise = 777 WHERE id = '{DECL['manager']}'; "
                              f"SELECT count(*) FROM payroll_it_declarations WHERE rent_paid_declared_paise = 777;")
    assert _landed(r), r.stderr


@_NEEDS_PG
def test_neither_function_asks_the_role_any_more(db):
    for fn in ("payroll_declaration_guard_verified_columns", "payroll_declaration_item_guard_verified_columns"):
        body = _ok(db, f"SELECT pg_get_functiondef('public.{fn}()'::regprocedure);")
        assert "my_permission('payroll'" in body and "my_role_at_least" not in body, fn


@_NEEDS_PG
@pytest.mark.parametrize("write", [_verify_header, _verify_line], ids=["declaration", "line"])
def test_the_rollback_puts_the_old_answer_back_which_is_the_negative_control(db, write):
    _block(db, MANAGER, False)
    assert _refused_by_the_guard(_as(db, AUTH_MANAGER, write("manager")))
    _ok(db, ROLLBACK.read_text(encoding="utf-8"))
    assert _landed(_as(db, AUTH_MANAGER, write("manager"))), "the rollback restores the hole"
    _ok(db, MIGRATION.read_text(encoding="utf-8"))
    _ok(db, "UPDATE payroll_it_declarations SET rent_paid_verified_paise = 0; UPDATE payroll_it_declaration_items SET amount_verified_paise = 0;")
    assert _refused_by_the_guard(_as(db, AUTH_MANAGER, write("manager"))), "and the migration is idempotent"


@_NEEDS_PG
def test_the_migration_keeps_the_functions_owner_security_and_grants(db):
    fn = "payroll_declaration_guard_verified_columns"
    row = _ok(db, f"SELECT p.prosecdef::text || '|' || r.rolname FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner "
                  f"WHERE p.oid = 'public.{fn}()'::regprocedure;")
    assert row.startswith("true|")
