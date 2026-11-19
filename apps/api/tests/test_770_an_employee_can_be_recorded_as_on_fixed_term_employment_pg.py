"""Migration 770 — an employee can be recorded as on fixed-term employment (POST-A-526).

Two additive, nullable columns on public.payroll_employees: `fixed_term_employment` (NULL = never recorded, TRUE = recorded, FALSE =
withdrawn) and `fixed_term_end_date`, which a CHECK allows only beside a fixed-term employee. Proved against real PostgreSQL because the
mock suite cannot tell whether a column exists or whether a CHECK bites.
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
FORWARD = API_ROOT / "migrations" / "770_an_employee_can_be_recorded_as_on_fixed_term_employment.sql"
ROLLBACK = API_ROOT / "migrations" / "770_an_employee_can_be_recorded_as_on_fixed_term_employment_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="migration 770 proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000770"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000770"


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
    name = f"m770_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert FORWARD.name not in pg_template.failed, "migration 770 did not apply: everything below would pass vacuously"
        for sql in (
            f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}','F770','f770@t.in');",
            f"INSERT INTO clients (id, firm_id, client_name, entity_type, pan) VALUES "
            f"('{CLIENT}','{FIRM}','C770','Private Limited','AAACA1234E');",
        ):
            r = _psql(dsn, sql)
            assert r.returncode == 0, r.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _emp(name: str, employment: str = "NULL", end: str = "NULL") -> str:
    end_sql = "NULL" if end == "NULL" else f"DATE '{end}'"
    return f"INSERT INTO payroll_employees (firm_id, client_id, name, fixed_term_employment, fixed_term_end_date) VALUES ('{FIRM}','{CLIENT}','{name}',{employment},{end_sql});"


def test_the_columns_exist_nullable_with_their_types(db):
    out = _psql(db, "SELECT string_agg(column_name || ':' || data_type || ':' || is_nullable, ',' ORDER BY column_name) "
                    "FROM information_schema.columns WHERE table_schema='public' AND table_name='payroll_employees' "
                    "AND column_name IN ('fixed_term_employment','fixed_term_end_date');", tuples=True)
    assert out.stdout.strip() == "fixed_term_employment:boolean:YES,fixed_term_end_date:date:YES"


def test_an_employee_with_neither_still_inserts_and_reads_null(db):
    assert _psql(db, f"INSERT INTO payroll_employees (firm_id, client_id, name) VALUES ('{FIRM}','{CLIENT}','Plain');").returncode == 0
    row = _psql(db, "SELECT (fixed_term_employment IS NULL)::text || (fixed_term_end_date IS NULL)::text "
                    "FROM payroll_employees WHERE name='Plain';", tuples=True)
    assert row.stdout.strip() == "truetrue"


def test_a_fixed_term_employee_may_carry_an_end_date_or_none(db):
    assert _psql(db, _emp("A", "TRUE", "2026-12-31")).returncode == 0
    assert _psql(db, _emp("B", "TRUE")).returncode == 0


@pytest.mark.parametrize("employment", ["NULL", "FALSE"])
def test_an_end_date_without_a_fixed_term_is_refused_by_the_database(db, employment):
    refused = _psql(db, _emp("C", employment, "2026-12-31"))
    assert refused.returncode != 0
    assert "payroll_employees_fixed_term_end_needs_a_fixed_term" in refused.stderr


def test_withdrawing_must_clear_the_end_date_in_the_same_statement(db):
    assert _psql(db, _emp("D", "TRUE", "2026-12-31")).returncode == 0
    assert _psql(db, "UPDATE payroll_employees SET fixed_term_employment = FALSE WHERE name='D';").returncode != 0
    assert _psql(db, "UPDATE payroll_employees SET fixed_term_employment = FALSE, fixed_term_end_date = NULL WHERE name='D';").returncode == 0


def test_the_comments_say_what_each_column_means(db):
    out = _psql(db, """
        SELECT string_agg(col_description('public.payroll_employees'::regclass, a.attnum), ' | ')
          FROM pg_attribute a WHERE a.attrelid = 'public.payroll_employees'::regclass
           AND a.attname IN ('fixed_term_employment','fixed_term_end_date');
    """, tuples=True)
    assert "one year of service" in out.stdout and "rule 33(1)(a)" in out.stdout and "Never inferred" in out.stdout


def test_the_migration_can_run_twice(db):
    assert _psql_file(db, FORWARD).returncode == 0


def test_the_rollback_removes_the_columns_and_the_migration_comes_back(db):
    assert _psql_file(db, ROLLBACK).returncode == 0
    gone = _psql(db, "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='payroll_employees' "
                     "AND column_name IN ('fixed_term_employment','fixed_term_end_date');", tuples=True)
    assert gone.stdout.strip() == "0"
    assert _psql_file(db, FORWARD).returncode == 0
