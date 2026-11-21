"""Migration 776 — an employee of the firm's own payroll names the team member they are (POST-A-540).

One nullable column on public.payroll_employees, `staff_user_id`, a foreign key to users(id), and three rules the database holds
beside the API's sentences: the member is of the row's own firm (migration 566's guard, re-installed so it covers the new key), one
member is at most one employee (a partial unique index), and the employee is in the firm's OWN payroll (a trigger). Proved against
real PostgreSQL because the mock suite cannot tell whether a column exists, a trigger fires or an index is unique.
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
FORWARD = API_ROOT / "migrations" / "776_an_employee_of_the_firms_own_payroll_names_the_team_member_they_are.sql"
ROLLBACK = API_ROOT / "migrations" / "776_an_employee_of_the_firms_own_payroll_names_the_team_member_they_are_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="migration 776 proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000776"
OTHER_FIRM = "aaaaaaaa-0000-0000-0000-100000000776"
PRACTICE = "bbbbbbbb-0000-0000-0000-000000000776"
CLIENT = "bbbbbbbb-0000-0000-0000-100000000776"
ASHA = "cccccccc-0000-0000-0000-000000000776"
RAVI = "cccccccc-0000-0000-0000-100000000776"
STRANGER = "cccccccc-0000-0000-0000-200000000776"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m776_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert FORWARD.name not in pg_template.failed, "migration 776 did not apply: everything below would pass vacuously"
        for sql in (
            f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}','F776','f776@t.in'), ('{OTHER_FIRM}','G776','g776@t.in');",
            f"INSERT INTO clients (id, firm_id, client_name, entity_type, pan, is_internal) VALUES "
            f"('{PRACTICE}','{FIRM}','The practice','Partnership','AAAFP1234E', TRUE), "
            f"('{CLIENT}','{FIRM}','A client','Private Limited','AAACA1234E', FALSE);",
            f"UPDATE firms SET internal_client_id = '{PRACTICE}' WHERE id = '{FIRM}';",
            f"INSERT INTO users (id, firm_id, email, full_name, role) VALUES "
            f"('{ASHA}','{FIRM}','asha@t.in','Asha','Executive'), ('{RAVI}','{FIRM}','ravi@t.in','Ravi','Executive'), "
            f"('{STRANGER}','{OTHER_FIRM}','s@t.in','Stranger','Executive');",
        ):
            r = _psql(dsn, sql)
            assert r.returncode == 0, r.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _emp(name: str, client: str = PRACTICE, member: str | None = None) -> str:
    link = "NULL" if member is None else f"'{member}'"
    return f"INSERT INTO payroll_employees (firm_id, client_id, name, staff_user_id) VALUES ('{FIRM}','{client}','{name}',{link});"


def test_the_column_exists_nullable_and_is_a_key_to_users(db):
    out = _psql(db, "SELECT data_type || ':' || is_nullable FROM information_schema.columns WHERE table_schema='public' "
                    "AND table_name='payroll_employees' AND column_name='staff_user_id';", tuples=True)
    assert out.stdout.strip() == "uuid:YES"
    fk = _psql(db, "SELECT c.confrelid::regclass::text || ':' || c.confdeltype::text FROM pg_constraint c JOIN pg_attribute a "
                   "ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1] WHERE c.conrelid='public.payroll_employees'::regclass "
                   "AND c.contype='f' AND cardinality(c.conkey) = 1 AND a.attname='staff_user_id';", tuples=True)
    assert fk.returncode == 0, fk.stderr
    assert fk.stdout.strip() == "users:n", "the link is not a key to users that is set NULL when the member is deleted"


def test_an_employee_with_no_member_still_inserts_for_the_practice_and_for_a_client(db):
    assert _psql(db, _emp("Plain")).returncode == 0
    assert _psql(db, _emp("A clerk at a client", client=CLIENT)).returncode == 0


def test_an_employee_of_the_firms_own_payroll_is_linked_to_a_member(db):
    r = _psql(db, _emp("Asha Rao", member=ASHA))
    assert r.returncode == 0, r.stderr


def test_a_clients_employee_is_refused_a_member_on_insert_and_on_update(db):
    refused = _psql(db, _emp("Clerk", client=CLIENT, member=ASHA))
    assert refused.returncode != 0 and "only to an employee of the firm's own payroll" in refused.stderr
    assert _psql(db, _emp("Clerk", client=CLIENT)).returncode == 0
    refused = _psql(db, f"UPDATE payroll_employees SET staff_user_id = '{ASHA}' WHERE name = 'Clerk';")
    assert refused.returncode != 0 and "only to an employee of the firm's own payroll" in refused.stderr


def test_a_linked_employee_cannot_be_moved_to_a_client(db):
    assert _psql(db, _emp("Asha Rao", member=ASHA)).returncode == 0
    refused = _psql(db, f"UPDATE payroll_employees SET client_id = '{CLIENT}' WHERE name = 'Asha Rao';")
    assert refused.returncode != 0 and "only to an employee of the firm's own payroll" in refused.stderr


def test_one_member_is_at_most_one_employee(db):
    assert _psql(db, _emp("Asha Rao", member=ASHA)).returncode == 0
    refused = _psql(db, _emp("Asha again", member=ASHA))
    assert refused.returncode != 0 and "uq_payroll_employees_staff_user" in refused.stderr
    assert _psql(db, _emp("Ravi K", member=RAVI)).returncode == 0, "a second member could not be linked to a second employee"
    assert _psql(db, _emp("Nobody one")).returncode == 0 and _psql(db, _emp("Nobody two")).returncode == 0, "two unlinked employees collide"


def test_a_member_of_another_firm_is_refused_on_insert_and_on_update(db):
    assert _psql(db, _emp("A stranger", member=STRANGER)).returncode != 0
    assert _psql(db, _emp("Asha Rao")).returncode == 0
    assert _psql(db, f"UPDATE payroll_employees SET staff_user_id = '{STRANGER}' WHERE name = 'Asha Rao';").returncode != 0
    assert _psql(db, f"UPDATE payroll_employees SET staff_user_id = '{ASHA}' WHERE name = 'Asha Rao';").returncode == 0


def test_the_member_guard_covers_the_new_column(db):
    cols = _psql(db, "SELECT array_to_string(public.member_columns_of('public.payroll_employees'::regclass), ',');", tuples=True)
    assert "staff_user_id" in cols.stdout.split(",") or "staff_user_id" in cols.stdout
    trig = _psql(db, "SELECT count(*) FROM pg_trigger WHERE tgrelid='public.payroll_employees'::regclass AND NOT tgisinternal "
                     "AND tgname IN ('row_member_in_firm_ins','row_member_in_firm_upd','a_staff_link_is_on_the_firms_own_payroll');", tuples=True)
    assert trig.stdout.strip() == "3"


def test_no_signed_in_role_can_call_the_trigger_function(db):
    out = _psql(db, "SELECT has_function_privilege('authenticated', 'public.a_staff_link_is_on_the_firms_own_payroll()', 'EXECUTE')::text || "
                    "has_function_privilege('anon', 'public.a_staff_link_is_on_the_firms_own_payroll()', 'EXECUTE')::text;", tuples=True)
    assert out.stdout.strip() == "falsefalse"


def test_the_migration_can_run_twice(db):
    assert _psql(db, _emp("Asha Rao", member=ASHA)).returncode == 0
    r = _psql_file(db, FORWARD)
    assert r.returncode == 0, r.stderr
    kept = _psql(db, "SELECT staff_user_id FROM payroll_employees WHERE name='Asha Rao';", tuples=True)
    assert kept.stdout.strip() == ASHA


def test_the_rollback_removes_the_column_its_index_and_its_trigger_and_the_migration_comes_back(db):
    assert _psql(db, _emp("Asha Rao", member=ASHA)).returncode == 0
    r = _psql_file(db, ROLLBACK)
    assert r.returncode == 0, r.stderr
    gone = _psql(db, "SELECT (SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='payroll_employees' "
                     "AND column_name='staff_user_id')::text || (SELECT count(*) FROM pg_trigger WHERE tgrelid='public.payroll_employees'::regclass "
                     "AND tgname='a_staff_link_is_on_the_firms_own_payroll')::text || (SELECT count(*) FROM pg_class WHERE relname='uq_payroll_employees_staff_user')::text;",
                tuples=True)
    assert gone.stdout.strip() == "000"
    assert _psql(db, "SELECT name FROM payroll_employees WHERE name='Asha Rao';", tuples=True).stdout.strip() == "Asha Rao", "the rollback removed an employee"
    r = _psql_file(db, FORWARD)
    assert r.returncode == 0, r.stderr
