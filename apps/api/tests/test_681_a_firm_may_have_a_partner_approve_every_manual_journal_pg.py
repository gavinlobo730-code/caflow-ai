"""Migration 681 — a firm may have a Partner approve every manual journal (ledger POST-A-456).

WHAT THIS HOLDS (real Postgres)
    * the column exists on `firms`, is NOT NULL and defaults to FALSE, so every firm that existed reads as not requiring approval
      (no firm's work changes when the migration applies);
    * the API's own read of it (`services/journal_approval_rule.approval_required`'s select) runs against the migration-built schema;
    * it is idempotent, and its rollback drops the column (the API then reads the missing column as off, which the mock-mode file
      `test_a_manual_journal_is_posted_by_one_rule_at_every_door.py` holds).
Runs only when HARNESS_PG is set + psql on PATH (the fixture skips otherwise).
"""
from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
_STEM = "681_a_firm_may_have_a_partner_approve_every_manual_journal"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")
FIRM = "68100000-0000-0000-0000-000000000001"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-f", "-"],
                          input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture()
def db(pg_template):
    admin = (_ADMIN or "").strip()
    name = f"m681_{uuid.uuid4().hex[:10]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        _ok(dsn, f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'M681 Firm', 'm681@test.in');")
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def test_the_column_is_not_null_and_off_for_every_firm(db):
    assert _ok(db, "SELECT is_nullable || ':' || column_default FROM information_schema.columns "
                   "WHERE table_schema = 'public' AND table_name = 'firms' AND column_name = 'manual_journals_need_approval';") == "NO:false"
    assert _ok(db, f"SELECT manual_journals_need_approval FROM firms WHERE id = '{FIRM}';") == "f"
    r = _psql(db, f"UPDATE firms SET manual_journals_need_approval = NULL WHERE id = '{FIRM}';")
    assert r.returncode != 0 and "null value" in r.stderr


def test_the_apis_read_runs_against_the_schema(db):
    assert _ok(db, f"SELECT id, manual_journals_need_approval FROM firms WHERE id = '{FIRM}' LIMIT 1;") == f"{FIRM}|f"


def test_681_is_idempotent_and_its_rollback_drops_the_column(db):
    _ok(db, f"UPDATE firms SET manual_journals_need_approval = true WHERE id = '{FIRM}';")
    _ok(db, MIGRATION.read_text(encoding="utf-8"))
    assert _ok(db, f"SELECT manual_journals_need_approval FROM firms WHERE id = '{FIRM}';") == "t", "a re-apply kept the firm's choice"
    _ok(db, ROLLBACK.read_text(encoding="utf-8"))
    assert _ok(db, "SELECT count(*) FROM information_schema.columns WHERE table_name = 'firms' "
                   "AND column_name = 'manual_journals_need_approval';") == "0"
    _ok(db, ROLLBACK.read_text(encoding="utf-8"))
    _ok(db, MIGRATION.read_text(encoding="utf-8"))
    assert _ok(db, f"SELECT manual_journals_need_approval FROM firms WHERE id = '{FIRM}';") == "f"
