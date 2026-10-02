"""Migration 477, proved against real PostgreSQL (payroll-22).

WHAT IS BEING PROVED

    1. THE COLUMNS ARE NULL WITH NO DEFAULT. An employee inserted the way every
       existing row was (no election columns) reads NULL in all three, which is
       the statutory default — the ceiling. A default of false would have
       recorded "withdrawn" for everybody; a backfill would have invented an
       election nobody made.

    2. A SLIP'S FLAG IS NOT NULL AND DEFAULTS TO FALSE, the opposite call and for
       the opposite reason: the value is KNOWN for every slip that exists (nothing
       could elect before this migration), so false is true of all of them, and
       the ECR reads it as a fact.

    3. AN ELECTION NEEDS PF. `pf_on_actual_wages = true` beside `pf_applicable =
       false` is refused by the database, the second line behind the API's
       sentence.

    4. A DATE OR REFERENCE BELONGS ONLY TO AN ELECTION THAT IS TRUE — not to NULL
       and not to a withdrawn one, which is why a withdrawal clears them.

    5. THE REFERENCE IS NON-BLANK AND AT MOST 200 CHARACTERS, and the date is not
       before 1952 (the typo "1926" for "2026" would read as "every month").

    6. THE MIGRATION IS RE-RUNNABLE and its rollback removes exactly what it added.

NEGATIVE CONTROL
    Drop the first CHECK and test_an_election_needs_pf_to_apply_to fails. Drop
    the second and the two detail tests fail. Drop the third and the reference
    tests fail. Give the slip column no default and the insert in
    test_a_slip_defaults_to_not_elected fails; make it nullable and
    test_a_slips_flag_cannot_be_null fails.

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
    reason="PF election proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000477"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000477"
RUN = "cccccccc-0000-0000-0000-000000000477"
MIGRATION = "477_pf_on_actual_wages_is_an_election_the_employer_records.sql"
FORWARD = API_ROOT / "migrations" / MIGRATION
ROLLBACK = API_ROOT / "migrations" / MIGRATION.replace(".sql", "_rollback.sql")


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)],
                          capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m477_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert MIGRATION not in pg_template.failed, (
            "migration 477 did not apply — everything below would pass vacuously")
        for sql in (
            f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}','F477','f477@t.in');",
            f"INSERT INTO clients (id, firm_id, client_name, entity_type, pan) VALUES "
            f"('{CLIENT}','{FIRM}','C477','Private Limited','AAACA1234E');",
            f"INSERT INTO payroll_runs (id, firm_id, client_id, month, status) VALUES "
            f"('{RUN}','{FIRM}','{CLIENT}','2026-12','draft');",
        ):
            r = _psql(dsn, sql)
            assert r.returncode == 0, f"{sql[:70]}… → {r.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _lit(value) -> str:
    """A SQL literal for the handful of Python values these tests pass."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _emp(name: str, **cols) -> str:
    # `pf_applicable` is stated unless the test says otherwise: the column's
    # default in a database built from migration 014 is FALSE (054 and 093's
    # `DEFAULT true` were a no-op behind CREATE TABLE IF NOT EXISTS), and an
    # election beside it is exactly what the first CHECK refuses.
    cols = {"pf_applicable": True, **cols}
    names = ["firm_id", "client_id", "name", "basic_paise"] + list(cols)
    values = [_lit(FIRM), _lit(CLIENT), _lit(name), "4000000"] + [_lit(v) for v in cols.values()]
    return (f"INSERT INTO payroll_employees ({', '.join(names)}) "
            f"VALUES ({', '.join(values)});")


def _one(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql, tuples=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


# ── 1. nothing recorded is NULL, and there is no default ─────────────────────

def test_an_employee_written_the_old_way_reads_null_in_all_three(db):
    assert _psql(db, _emp("Asha")).returncode == 0
    row = _one(db, "SELECT pf_on_actual_wages IS NULL, pf_on_actual_wages_from IS NULL, "
                   "pf_on_actual_wages_reference IS NULL FROM payroll_employees "
                   "WHERE name = 'Asha';")
    assert row == "t|t|t"


def test_the_employee_columns_carry_no_default(db):
    rows = _one(db, "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='payroll_employees' "
                    "AND column_name LIKE 'pf_on_actual_wages%' "
                    "AND column_default IS NOT NULL;")
    assert rows == "0"


# ── 2. the slip's flag: NOT NULL, default false ──────────────────────────────

def test_a_slip_defaults_to_not_elected(db):
    assert _psql(db, _emp("Asha")).returncode == 0
    emp = _one(db, "SELECT id FROM payroll_employees WHERE name='Asha';")
    r = _psql(db, f"INSERT INTO payroll_slips (run_id, employee_id, gross_paise, net_paise) "
                  f"VALUES ('{RUN}','{emp}',4000000,3500000);")
    assert r.returncode == 0, r.stderr
    assert _one(db, "SELECT pf_on_actual_wages FROM payroll_slips;") == "f"


def test_a_slips_flag_cannot_be_null(db):
    assert _psql(db, _emp("Asha")).returncode == 0
    emp = _one(db, "SELECT id FROM payroll_employees WHERE name='Asha';")
    r = _psql(db, f"INSERT INTO payroll_slips (run_id, employee_id, gross_paise, "
                  f"net_paise, pf_on_actual_wages) "
                  f"VALUES ('{RUN}','{emp}',4000000,3500000,NULL);")
    assert r.returncode != 0
    assert "pf_on_actual_wages" in r.stderr


# ── 3. an election needs PF ──────────────────────────────────────────────────

def test_an_election_may_be_recorded_for_an_employee_with_pf(db):
    assert _psql(db, _emp("Asha", pf_applicable=True, pf_on_actual_wages=True)).returncode == 0


def test_an_election_needs_pf_to_apply_to(db):
    r = _psql(db, _emp("Asha", pf_applicable=False, pf_on_actual_wages=True))
    assert r.returncode != 0
    assert "payroll_employees_pf_election_needs_pf" in r.stderr


def test_switching_pf_off_beside_an_election_is_refused_on_update(db):
    assert _psql(db, _emp("Asha", pf_applicable=True, pf_on_actual_wages=True)).returncode == 0
    r = _psql(db, "UPDATE payroll_employees SET pf_applicable = false WHERE name='Asha';")
    assert r.returncode != 0
    assert "payroll_employees_pf_election_needs_pf" in r.stderr


def test_withdrawn_or_never_recorded_may_sit_beside_pf_off(db):
    assert _psql(db, _emp("A", pf_applicable=False)).returncode == 0
    assert _psql(db, _emp("B", pf_applicable=False, pf_on_actual_wages=False)).returncode == 0


# ── 4. the detail belongs to a true election ─────────────────────────────────

def test_a_date_without_an_election_is_refused(db):
    r = _psql(db, _emp("Asha", pf_on_actual_wages_from="2026-10-01"))
    assert r.returncode != 0
    assert "payroll_employees_pf_election_detail_needs_election" in r.stderr


def test_a_reference_beside_a_withdrawn_election_is_refused(db):
    r = _psql(db, _emp("Asha", pf_on_actual_wages=False,
                       pf_on_actual_wages_reference="ref"))
    assert r.returncode != 0
    assert "payroll_employees_pf_election_detail_needs_election" in r.stderr


def test_withdrawing_must_clear_the_detail_in_the_same_statement(db):
    seeded = _psql(db, _emp("Asha", pf_on_actual_wages=True,
                            pf_on_actual_wages_from="2026-10-01",
                            pf_on_actual_wages_reference="ref"))
    assert seeded.returncode == 0, seeded.stderr
    assert _psql(db, "UPDATE payroll_employees SET pf_on_actual_wages = false "
                     "WHERE name='Asha';").returncode != 0
    ok = _psql(db, "UPDATE payroll_employees SET pf_on_actual_wages = false, "
                   "pf_on_actual_wages_from = NULL, pf_on_actual_wages_reference = NULL "
                   "WHERE name='Asha';")
    assert ok.returncode == 0, ok.stderr


# ── 5. shapes ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("reference", ["", "   ", "x" * 201])
def test_a_blank_or_over_long_reference_is_refused(db, reference):
    r = _psql(db, _emp("Asha", pf_on_actual_wages=True,
                       pf_on_actual_wages_reference=reference))
    assert r.returncode != 0
    assert "payroll_employees_pf_election_reference_shape" in r.stderr


def test_a_reference_of_exactly_two_hundred_characters_is_allowed(db):
    assert _psql(db, _emp("Asha", pf_on_actual_wages=True,
                          pf_on_actual_wages_reference="x" * 200)).returncode == 0


def test_a_date_before_the_scheme_is_refused_and_a_future_date_is_allowed(db):
    bad = _psql(db, _emp("Asha", pf_on_actual_wages=True,
                         pf_on_actual_wages_from="1926-10-01"))
    assert bad.returncode != 0
    assert "payroll_employees_pf_election_date_plausible" in bad.stderr
    # An employer may record an election that starts next month.
    assert _psql(db, _emp("Ravi", pf_on_actual_wages=True,
                          pf_on_actual_wages_from="2099-01-01")).returncode == 0


# ── 6. re-runnable, and the rollback removes exactly what was added ──────────

def test_the_migration_is_rerunnable_and_changes_nothing_the_second_time(db):
    assert _psql(db, _emp("Asha", pf_on_actual_wages=True,
                          pf_on_actual_wages_from="2026-10-01")).returncode == 0
    again = _file(db, FORWARD)
    assert again.returncode == 0, again.stderr
    assert _one(db, "SELECT pf_on_actual_wages_from FROM payroll_employees;") == "2026-10-01"


def test_the_rollback_removes_the_columns_and_the_checks_and_nothing_else(db):
    r = _file(db, ROLLBACK)
    assert r.returncode == 0, r.stderr
    left = _one(db, "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema='public' AND column_name LIKE 'pf_on_actual_wages%';")
    assert left == "0"
    checks = _one(db, "SELECT count(*) FROM pg_constraint "
                      "WHERE conname LIKE 'payroll_employees_pf_election_%';")
    assert checks == "0"
    # The columns this migration did NOT add are untouched.
    assert _one(db, "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='payroll_slips' "
                    "AND column_name = 'pf_wages_paise';") == "1"
    again = _file(db, FORWARD)
    assert again.returncode == 0, again.stderr


def test_every_column_carries_a_comment_that_names_the_grade(db):
    comments = _one(db, "SELECT string_agg(col_description(c.oid, a.attnum), ' ') "
                        "FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid "
                        "WHERE c.relname IN ('payroll_employees','payroll_slips') "
                        "AND a.attname LIKE 'pf_on_actual_wages%';")
    assert comments.count("payroll-22") == 4
    assert "unverified" in comments
