"""
Migration 568, proved against real PostgreSQL (POST-A-272).

WHAT IS BEING PROVED
    1. `tds_challans.journal_entry_id` exists, is nullable and is NULL on every row that predates it: no backfill, because which entry
       paid which challan is the CA's answer.
    2. It is a real foreign key to `journal_entries`: an id that is not an entry is refused at the column.
    3. ON DELETE SET NULL: removing the entry unlinks the challan and leaves the challan (the record that the tax was deposited), as
       `statutory_remittances` has done since 365.
    4. The conditional update the service makes ("no link yet") ties a challan once and matches no row the second time, and the one that
       takes a link back names the link it read and matches no row once it has changed.
    5. The file is re-runnable and its rollback takes the column and its index away.

NEGATIVE CONTROL
    Drop the REFERENCES from the migration and the not-an-entry case writes straight in; drop `ON DELETE SET NULL` and deleting the entry
    is refused while a challan points at it.

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
MIGRATION = next((API_ROOT / "migrations").glob("568_a_recorded_tds_challan_can_be_tied_to_the_ledger_entry_that_paid_it.sql"))
ROLLBACK = next((API_ROOT / "migrations").glob("568_*_rollback.sql"))
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the TDS challan link proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000568"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000568"
JE1 = "e0000000-0000-0000-0000-000000000001"
JE2 = "e0000000-0000-0000-0000-000000000002"
CH1 = "c0000000-0000-0000-0000-000000000001"


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
    name = f"m568_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert MIGRATION.name not in pg_template.failed, "migration 568 did not apply — everything below would pass vacuously"
        for sql in (
            f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F568', 'f568@t.in');",
            f"INSERT INTO clients (id, firm_id, client_name, entity_type, pan) VALUES "
            f"('{CLIENT}', '{FIRM}', 'C568', 'Private Limited', 'AAACA1234E');",
            f"INSERT INTO journal_entries (id, firm_id, client_id, entry_date, narration, entry_type, is_posted, status) VALUES "
            f"('{JE1}', '{FIRM}', '{CLIENT}', '2026-07-05', 'tds paid', 'Payment', true, 'posted'), "
            f"('{JE2}', '{FIRM}', '{CLIENT}', '2026-07-06', 'tds paid again', 'Payment', true, 'posted');",
            f"INSERT INTO tds_challans (id, firm_id, client_id, bsr_code, challan_no, payment_date, quarter, financial_year, "
            f"tds_paise, total_paise, section) VALUES ('{CH1}', '{FIRM}', '{CLIENT}', '0510001', '00045', '2026-07-05', 'Q1', "
            f"'2026-27', 1250000, 1250000, '194C');",
        ):
            r = _psql(dsn, sql)
            assert r.returncode == 0, f"{sql[:70]}… → {r.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _link(db) -> str:
    return _one(db, f"SELECT coalesce(journal_entry_id::text, 'NULL') FROM tds_challans WHERE id = '{CH1}';")


# ── 1. the column ────────────────────────────────────────────────────────────

def test_a_challan_recorded_before_the_column_is_tied_to_nothing(db):
    assert _link(db) == "NULL"
    assert _one(db, "SELECT is_nullable FROM information_schema.columns WHERE table_name = 'tds_challans' "
                    "AND column_name = 'journal_entry_id';") == "YES"


# ── 2. the foreign key ───────────────────────────────────────────────────────

def test_an_id_that_is_not_an_entry_is_refused(db):
    r = _psql(db, f"UPDATE tds_challans SET journal_entry_id = '{uuid.uuid4()}' WHERE id = '{CH1}';")
    assert r.returncode != 0 and "violates foreign key constraint" in r.stderr
    assert _link(db) == "NULL"


def test_an_entry_can_be_tied(db):
    assert _psql(db, f"UPDATE tds_challans SET journal_entry_id = '{JE1}' WHERE id = '{CH1}';").returncode == 0
    assert _link(db) == JE1


# ── 3. what deleting the entry does ──────────────────────────────────────────

def test_removing_the_entry_unlinks_the_challan_and_keeps_it(db):
    assert _psql(db, f"UPDATE tds_challans SET journal_entry_id = '{JE1}' WHERE id = '{CH1}';").returncode == 0
    # The ledger forbids deleting a posted entry through the API; a hard delete is the database's own housekeeping, run here with the
    # table's USER triggers (the ones that guard posted entries) off inside one transaction. NOT `session_replication_role = replica`:
    # that switches the foreign key's own actions off too, which is the thing under test.
    r = _psql(db, "BEGIN; ALTER TABLE journal_entries DISABLE TRIGGER USER; "
                  f"DELETE FROM journal_entries WHERE id = '{JE1}'; ALTER TABLE journal_entries ENABLE TRIGGER USER; COMMIT;")
    assert r.returncode == 0, r.stderr
    assert _one(db, f"SELECT count(*) FROM tds_challans WHERE id = '{CH1}';") == "1", "the challan went with the entry"
    assert _link(db) == "NULL"


# ── 4. the conditional updates the service makes ─────────────────────────────

def test_the_link_is_made_once_and_the_second_attempt_matches_no_row(db):
    sql = ("WITH t AS (UPDATE tds_challans SET journal_entry_id = '{je}' WHERE id = '" + CH1 + "' AND journal_entry_id IS NULL "
           "RETURNING 1) SELECT count(*) FROM t;")
    assert _one(db, sql.format(je=JE1)) == "1"
    assert _one(db, sql.format(je=JE2)) == "0", "the second link tied the challan again"
    assert _link(db) == JE1


def test_taking_the_link_back_names_the_link_it_read(db):
    assert _psql(db, f"UPDATE tds_challans SET journal_entry_id = '{JE1}' WHERE id = '{CH1}';").returncode == 0
    sql = ("WITH t AS (UPDATE tds_challans SET journal_entry_id = NULL WHERE id = '" + CH1 + "' AND journal_entry_id = '{read}' "
           "RETURNING 1) SELECT count(*) FROM t;")
    assert _one(db, sql.format(read=JE2)) == "0", "a stale read took back a link it never saw"
    assert _one(db, sql.format(read=JE1)) == "1"
    assert _link(db) == "NULL"


# ── 5. re-runnable, and reversible ───────────────────────────────────────────

def test_the_file_can_be_run_again(db):
    for _ in range(2):
        r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(MIGRATION)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_the_rollback_takes_the_column_and_its_index_away(db):
    r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(ROLLBACK)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert _one(db, "SELECT count(*) FROM information_schema.columns WHERE table_name = 'tds_challans' "
                    "AND column_name = 'journal_entry_id';") == "0"
    assert _one(db, "SELECT count(*) FROM pg_indexes WHERE indexname = 'idx_tds_challans_journal_entry';") == "0"
