"""Migration 454's CHECK on vendors.interest_threshold_class, against a real Postgres.

WHY THIS IS A REAL-POSTGRES TEST
    The Pydantic models refuse a made-up class and mock-mode tests prove that.
    Neither proves the DATABASE refuses it, and the vendor master is also
    written by the bulk importer and, in places, straight over PostgREST.

    A class the engine does not know raises `has no threshold class` at the
    first bill from that supplier — weeks after somebody typed it — so the CHECK
    exists to make the value storable only when the engine can answer for it.
    And the column must be NULLABLE with no backfill: every supplier that
    existed before 454 is in that state, and a NOT NULL would have made the
    whole vendor master unwritable on deploy.
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
    reason="migration 454 constraint proof requires HARNESS_PG + psql",
)

FIRM = "f4540000-0000-0000-0000-000000000001"
CLIENT = "c4540000-0000-0000-0000-000000000001"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-X", "-q"] + (["-tA"] if tuples else [])
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"v194a_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'T', 't@x.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
              VALUES ('{CLIENT}', '{FIRM}', 'T Co', 'Private Limited');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _insert_vendor(dsn: str, name: str, **cols) -> subprocess.CompletedProcess:
    keys = ", ".join(cols)
    vals = ", ".join("NULL" if v is None else f"'{v}'" for v in cols.values())
    lead = f", {keys}" if keys else ""
    tail = f", {vals}" if vals else ""
    return _psql(dsn, f"""
        INSERT INTO vendors (firm_id, client_id, name{lead})
        VALUES ('{FIRM}', '{CLIENT}', '{name}'{tail});
    """)


@pytest.mark.parametrize("value", ["ordinary", "bank_deposit", "bank_deposit_senior"])
def test_the_three_classes_the_engine_knows_are_accepted(db, value):
    assert _insert_vendor(db, f"V {value}", interest_threshold_class=value).returncode == 0


def test_a_supplier_with_no_class_is_accepted_and_stays_null(db):
    """Every row that existed before migration 454 — no backfill, so no
    supplier's withholding moved on the day it landed."""
    r = _insert_vendor(db, "Legacy Vendor")
    assert r.returncode == 0, r.stderr
    got = _psql(db, "SELECT count(*) FROM vendors WHERE interest_threshold_class IS NULL;",
                tuples=True)
    assert got.stdout.strip() == "1"


@pytest.mark.parametrize("value", ["senior", "senior_citizen", "bank", "Bank_Deposit",
                                   "BANK_DEPOSIT", "bank deposit", ""])
def test_a_class_the_engine_cannot_answer_for_is_refused_by_the_database(db, value):
    """'senior' is the one that matters: a payee's age alone is not a limit,
    and storing it would let a path that skips the Pydantic model record the
    finding's own reading — which would under-deduct."""
    r = _insert_vendor(db, f"Bad {value}", interest_threshold_class=value)
    assert r.returncode != 0, f"the database accepted interest_threshold_class={value!r}"
    assert "vendors_interest_threshold_class_check" in r.stderr


def test_the_migration_is_idempotent(db):
    """Run twice — `ADD COLUMN IF NOT EXISTS` and a constraint dropped by name
    before it is re-added, because this runs unattended on merge."""
    sql = (API_ROOT / "migrations"
           / "454_a_supplier_records_which_194a_limit_its_interest_falls_under.sql"
           ).read_text(encoding="utf-8")
    for _ in range(2):
        r = subprocess.run(["psql", db, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-f", "-"],
                           input=sql, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
