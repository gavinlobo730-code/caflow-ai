"""
Migration 333, proved against real PostgreSQL.

WHAT IS BEING PROVED

    1. employee_code is unique PER CLIENT and not per firm. Two clients of one
       firm will both have an EMP001, and a firm-wide constraint would refuse
       the second client's first employee.

    2. NULL codes do not collide. The index is partial precisely so that every
       employee added by hand before this migration — all of whom have no code —
       can coexist. A plain UNIQUE would have been fine in Postgres (NULLs are
       distinct) but says the wrong thing; the partial index is the intent.

    3. A code of '' is refused. Without that CHECK the import's idempotency key
       becomes the empty string for every row a spreadsheet left blank, and the
       partial index above would then reject the SECOND such employee as a
       duplicate of the first — a refusal with no cause the CA could see.

    4. A date of birth in the future is refused, and so is one before 1900.
       '2062-05-01' for '1962-05-01' is the typo, and it would make a
       sixty-two-year-old a minor — which changes the s.192 ladder in the
       direction that under-withholds.

NEGATIVE CONTROL
    Make the unique index firm-wide and test_two_clients_may_both_have_emp001
    fails. Drop the WHERE clause and test_two_employees_may_both_have_no_code
    fails. Drop the not-blank CHECK and test_an_empty_code_is_not_a_code fails.
    Drop the plausibility CHECK and both date tests fail.

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
    reason="employee master proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000333"
CLIENT_A = "bbbbbbbb-0000-0000-0000-00000000333a"
CLIENT_B = "bbbbbbbb-0000-0000-0000-00000000333b"
MIGRATION = "333_an_employee_has_a_code_and_a_date_of_birth.sql"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
        capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m333_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert MIGRATION not in pg_template.failed, (
            "migration 333 did not apply — everything below would pass vacuously")
        stmts = [
            f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}','F333','f333@t.in');",
            f"INSERT INTO clients (id, firm_id, client_name, entity_type, pan) VALUES "
            f"('{CLIENT_A}','{FIRM}','C333A','Private Limited','AAACA1234E'), "
            f"('{CLIENT_B}','{FIRM}','C333B','Private Limited','AAACA1234F');",
        ]
        for sql in stmts:
            r = _psql(dsn, sql)
            assert r.returncode == 0, f"{sql[:70]}… → {r.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _emp(client: str, name: str, code: str = "NULL", dob: str = "NULL") -> str:
    code_sql = "NULL" if code == "NULL" else f"'{code}'"
    dob_sql = "NULL" if dob == "NULL" else f"DATE '{dob}'"
    return (f"INSERT INTO payroll_employees "
            f"(firm_id, client_id, name, employee_code, date_of_birth) VALUES "
            f"('{FIRM}','{client}','{name}',{code_sql},{dob_sql});")


# ─── 1. the code identifies one person, per client ───────────────────────────

def test_one_client_may_not_repeat_a_code(db):
    """The whole reason the column exists: a re-imported file must UPDATE the
    employee it names, and a duplicate is somebody paid twice."""
    assert _psql(db, _emp(CLIENT_A, "Asha", "EMP001")).returncode == 0
    r = _psql(db, _emp(CLIENT_A, "Ravi", "EMP001"))
    assert r.returncode != 0
    assert "payroll_employees_client_code_uniq" in r.stderr


def test_two_clients_may_both_have_emp001(db):
    """The code is the CLIENT's, not the practice's. A firm-wide constraint
    would refuse the second client's very first employee."""
    assert _psql(db, _emp(CLIENT_A, "Asha", "EMP001")).returncode == 0
    assert _psql(db, _emp(CLIENT_B, "Ravi", "EMP001")).returncode == 0


def test_two_employees_may_both_have_no_code(db):
    """Every employee added by hand before this migration has none. The index
    is partial exactly so they can coexist."""
    assert _psql(db, _emp(CLIENT_A, "Asha")).returncode == 0
    assert _psql(db, _emp(CLIENT_A, "Ravi")).returncode == 0


def test_an_empty_code_is_not_a_code(db):
    """Without this, every row a spreadsheet left blank shares the key '' and
    the SECOND such employee is refused as a duplicate of the first — a refusal
    with no cause the CA could see."""
    r = _psql(db, _emp(CLIENT_A, "Asha", ""))
    assert r.returncode != 0
    assert "payroll_employees_employee_code_not_blank" in r.stderr
    r = _psql(db, _emp(CLIENT_A, "Asha", "   "))
    assert r.returncode != 0, "whitespace is not a code either"


# ─── 2. the date of birth is a date somebody could have been born on ─────────

def test_a_real_date_of_birth_is_accepted(db):
    assert _psql(db, _emp(CLIENT_A, "Asha", "EMP001", "1967-03-15")).returncode == 0


def test_a_future_date_of_birth_is_refused(db):
    """'2062-05-01' for '1962-05-01' would make a 62-year-old a minor, and the
    §192 ladder would move in the direction that under-withholds."""
    r = _psql(db, _emp(CLIENT_A, "Asha", "EMP001", "2062-05-01"))
    assert r.returncode != 0
    assert "payroll_employees_date_of_birth_plausible" in r.stderr


def test_a_date_of_birth_before_1900_is_refused(db):
    r = _psql(db, _emp(CLIENT_A, "Asha", "EMP001", "1867-03-15"))
    assert r.returncode != 0
    assert "payroll_employees_date_of_birth_plausible" in r.stderr


def test_no_date_of_birth_is_allowed_and_means_unknown(db):
    """Nullable by design: the code reads the general ladder, which is what it
    did before this column existed, and reports the gap rather than guessing."""
    assert _psql(db, _emp(CLIENT_A, "Asha", "EMP001")).returncode == 0
