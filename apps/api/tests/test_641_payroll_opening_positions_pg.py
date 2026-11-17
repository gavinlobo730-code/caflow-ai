"""Migration 641 on real Postgres: the opening-position table holds what the API validates, one row per employee and year, and a
signed-in session holds no privilege on it (POST-A-082)."""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest

_ADMIN = os.environ.get("HARNESS_PG")
pytestmark = pytest.mark.skipif(not _ADMIN or not shutil.which("psql"), reason="needs HARNESS_PG and psql on PATH")

FIRM = "64100000-0000-0000-0000-000000000001"
CLIENT = "64100000-0000-0000-0000-0000000000c1"
EMP = "64100000-0000-0000-0000-0000000000e1"


def _psql(dsn, sql):
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"c5_op641_{uuid.uuid4().hex[:12]}"
    if _psql(f"{admin} dbname=postgres", f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
          INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
          INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}', '{FIRM}', 'C', 'Proprietorship');
          INSERT INTO payroll_employees (id, firm_id, client_id, name, status) VALUES ('{EMP}', '{FIRM}', '{CLIENT}', 'Asha', 'active');""")
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(f"{admin} dbname=postgres", f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _row(**o):
    v = dict(fy="2026-27", first="2026-10-01", months=6, gross=6000000, tds=120000)
    v.update(o)
    return (f"INSERT INTO payroll_opening_positions (firm_id, client_id, employee_id, financial_year, first_month_here, months_paid, "
            f"gross_paise, tds_paise, pf_employee_paise, pf_employer_paise, esi_employee_paise, esi_employer_paise, pt_paise) "
            f"VALUES ('{FIRM}','{CLIENT}','{EMP}','{v['fy']}','{v['first']}',{v['months']},{v['gross']},{v['tds']},0,0,0,0,0);")


def test_a_valid_position_goes_in_once_per_employee_and_year(db):
    assert _psql(db, _row()).returncode == 0
    again = _psql(db, _row())
    assert again.returncode != 0 and "payroll_opening_positions_one_per_year" in again.stderr
    assert _psql(db, _row(fy="2027-28", first="2027-10-01")).returncode == 0


@pytest.mark.parametrize("bad,constraint", [
    (dict(months=12), "payroll_opening_positions_months"),
    (dict(months=0, gross=5), "payroll_opening_positions_months_and_gross"),
    (dict(first="2026-10-15"), "payroll_opening_positions_a_month"),
    (dict(fy="2026"), "payroll_opening_positions_fy_label"),
    (dict(gross=-1), "payroll_opening_positions_amounts"),
])
def test_what_the_table_cannot_hold(db, bad, constraint):
    r = _psql(db, _row(**bad))
    assert r.returncode != 0 and constraint in r.stderr


def test_a_signed_in_session_holds_no_privilege_and_the_service_role_all_four(db):
    for role in ("authenticated", "anon"):
        for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert _psql(db, f"SELECT has_table_privilege('{role}', 'public.payroll_opening_positions', '{verb}')").stdout.strip() == "f"
    for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert _psql(db, f"SELECT has_table_privilege('service_role', 'public.payroll_opening_positions', '{verb}')").stdout.strip() == "t"


def test_deleting_the_employee_takes_the_position_with_it(db):
    assert _psql(db, _row()).returncode == 0
    assert _psql(db, f"DELETE FROM payroll_employees WHERE id = '{EMP}'").returncode == 0
    assert _psql(db, "SELECT count(*) FROM payroll_opening_positions").stdout.strip() == "0"
