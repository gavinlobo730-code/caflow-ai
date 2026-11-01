"""
Migration 569, proved against real PostgreSQL (POST-A-362).

WHAT IS BEING PROVED
    1. `compliance_records.closing_tds_challan_ids` exists, is nullable and is NULL on every row that predates it: no backfill, because
       which challans closed a past month is what the register's order says today and not what was true when it was closed.
    2. It holds a JSON array or nothing: a string, a number or an object is refused at the column.
    3. The statement the repository makes ("write the ids of a row that is now filed, in this firm") writes an array that reads back as
       the ids, matches no row of another firm and none that is not filed, and a containment query finds the months that name a
       challan, including one whose challan has since been deleted (there is deliberately no foreign key).
    4. The file is re-runnable and its rollback takes the constraint and the column away.

NEGATIVE CONTROL
    Drop the CHECK from the migration and the not-an-array case writes straight in; add a foreign key and a retracted challan's id
    could not stay on the month it closed.

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
MIGRATION = next((API_ROOT / "migrations").glob("569_a_monthly_tds_deposit_obligation_records_the_challans_that_closed_it.sql"))
ROLLBACK = next((API_ROOT / "migrations").glob("569_*_rollback.sql"))
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the closing-challans record proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000569"
OTHER_FIRM = "aaaaaaaa-0000-0000-0000-000000000570"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000569"
OB_FILED = "d0000000-0000-0000-0000-000000000001"
OB_OPEN = "d0000000-0000-0000-0000-000000000002"
CHALLAN_A = "c0000000-0000-0000-0000-00000000000a"
CHALLAN_B = "c0000000-0000-0000-0000-00000000000b"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _one(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql, tuples=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m569_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert MIGRATION.name not in pg_template.failed, "migration 569 did not apply — everything below would pass vacuously"
        for sql in (
            f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F569', 'f569@t.in'), ('{OTHER_FIRM}', 'F570', 'f570@t.in');",
            f"INSERT INTO clients (id, firm_id, client_name, entity_type, pan) VALUES "
            f"('{CLIENT}', '{FIRM}', 'C569', 'Private Limited', 'AAACA1234E');",
            f"INSERT INTO compliance_records (id, firm_id, client_id, compliance_type, obligation_type, period_label, period_start, "
            f"period_end, due_date, status) VALUES "
            f"('{OB_FILED}', '{FIRM}', '{CLIENT}', 'TDS', 'TDS_NON_SALARY_DEPOSIT', 'July 2025', '2025-07-01', '2025-07-31', "
            f"'2025-08-07', 'Filed'), "
            f"('{OB_OPEN}', '{FIRM}', '{CLIENT}', 'TDS', 'TDS_NON_SALARY_DEPOSIT', 'August 2025', '2025-08-01', '2025-08-31', "
            f"'2025-09-07', 'Ready To File');",
        ):
            r = _psql(dsn, sql)
            assert r.returncode == 0, f"{sql[:70]}… → {r.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _ids(db, ob=OB_FILED) -> str:
    return _one(db, f"SELECT coalesce(closing_tds_challan_ids::text, 'NULL') FROM compliance_records WHERE id = '{ob}';")


# ── 1. the column ────────────────────────────────────────────────────────────

def test_an_obligation_recorded_before_the_column_names_no_challans(db):
    assert _ids(db) == "NULL"
    assert _one(db, "SELECT is_nullable FROM information_schema.columns WHERE table_name = 'compliance_records' "
                    "AND column_name = 'closing_tds_challan_ids';") == "YES"
    assert _one(db, "SELECT data_type FROM information_schema.columns WHERE table_name = 'compliance_records' "
                    "AND column_name = 'closing_tds_challan_ids';") == "jsonb"


# ── 2. an array or nothing ───────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["'\"c1\"'", "'3'", "'{\"a\": 1}'", "'true'"])
def test_a_value_that_is_not_an_array_is_refused(db, bad):
    r = _psql(db, f"UPDATE compliance_records SET closing_tds_challan_ids = {bad}::jsonb WHERE id = '{OB_FILED}';")
    assert r.returncode != 0 and "compliance_records_closing_tds_challan_ids_is_array" in r.stderr
    assert _ids(db) == "NULL"


def test_an_array_and_the_empty_array_and_null_are_accepted(db):
    for value, shown in (("'[\"x\"]'::jsonb", '["x"]'), ("'[]'::jsonb", "[]"), ("NULL", "NULL")):
        assert _psql(db, f"UPDATE compliance_records SET closing_tds_challan_ids = {value} WHERE id = '{OB_FILED}';").returncode == 0
        assert _ids(db) == shown


# ── 3. the statement the repository makes ────────────────────────────────────

def _stamp(db, ob, firm, ids) -> str:
    arr = "'[" + ",".join(f'"{i}"' for i in ids) + "]'::jsonb"
    return _one(db, f"WITH t AS (UPDATE compliance_records SET closing_tds_challan_ids = {arr} WHERE id = '{ob}' AND firm_id = '{firm}' "
                    f"AND status IN ('Filed', 'Completed') RETURNING 1) SELECT count(*) FROM t;")


def test_the_stamp_writes_a_filed_row_of_the_firm_and_no_other(db):
    assert _stamp(db, OB_FILED, OTHER_FIRM, [CHALLAN_A]) == "0", "another firm's row was written"
    assert _stamp(db, OB_OPEN, FIRM, [CHALLAN_A]) == "0", "a row that is not filed was written"
    assert _ids(db) == "NULL" and _ids(db, OB_OPEN) == "NULL"
    assert _stamp(db, OB_FILED, FIRM, [CHALLAN_A, CHALLAN_B]) == "1"
    assert _ids(db) == f'["{CHALLAN_A}", "{CHALLAN_B}"]'


def test_a_containment_query_finds_the_months_that_name_a_challan_that_no_longer_exists(db):
    # No challan with this id exists anywhere: the record outlives the challan, which is how a retraction finds the month it closed.
    assert _stamp(db, OB_FILED, FIRM, [CHALLAN_A]) == "1"
    found = _one(db, f"SELECT count(*) FROM compliance_records WHERE closing_tds_challan_ids @> '[\"{CHALLAN_A}\"]'::jsonb;")
    assert found == "1"
    assert _one(db, f"SELECT count(*) FROM compliance_records WHERE closing_tds_challan_ids @> '[\"{CHALLAN_B}\"]'::jsonb;") == "0"


# ── 4. re-runnable, and reversible ───────────────────────────────────────────

def test_the_file_can_be_run_again(db):
    for _ in range(2):
        r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(MIGRATION)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_the_rollback_takes_the_constraint_and_the_column_away(db):
    r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(ROLLBACK)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert _one(db, "SELECT count(*) FROM information_schema.columns WHERE table_name = 'compliance_records' "
                    "AND column_name = 'closing_tds_challan_ids';") == "0"
    assert _one(db, "SELECT count(*) FROM pg_constraint WHERE conname = 'compliance_records_closing_tds_challan_ids_is_array';") == "0"
