"""Migration 521 — fixed_deposits.maturity_amount_is_estimate (POST-A-134).

WHAT IS HELD
    * the column exists, is boolean, NOT NULL and defaults to TRUE: a row written without it (every row before the column existed,
      and any writer that does not know it) is an estimate, never a receipt figure;
    * FALSE is stored as FALSE and NULL is refused;
    * the migration is idempotent, and its rollback drops the column;
    * the column carries its comment.

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
_STEM = "521_a_fixed_deposit_says_whether_its_maturity_amount_is_the_receipts_or_an_estimate"
MIGRATION = API_ROOT / "migrations" / f"{_STEM}.sql"
ROLLBACK = API_ROOT / "migrations" / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the column proofs require HARNESS_PG + psql",
)

FIRM = "52100000-0000-0000-0000-000000000001"
CLIENT = "52100000-0000-0000-0000-0000000000c1"
COLUMN = "maturity_amount_is_estimate"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-f", "-"], input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"chk_m521_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        assert f"{_STEM}.sql" not in pg_template.failed, "migration 521 did not apply, so everything below would pass vacuously"
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'M521 Firm', 'm521@test.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}', '{FIRM}', 'Client A', 'Private Limited');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _insert(extra_cols: str = "", extra_vals: str = "") -> str:
    return (f"INSERT INTO fixed_deposits (firm_id, client_id, bank_name, principal_paise, interest_rate_percent, start_date, "
            f"maturity_date, maturity_amount_paise{extra_cols}) VALUES ('{FIRM}', '{CLIENT}', 'SBI', 10000000, 7.00, "
            f"'2026-04-01', '2027-04-01', 10700000{extra_vals}) RETURNING {COLUMN};")


@_NEEDS_PG
def test_the_column_is_a_not_null_boolean_defaulting_to_true(db):
    row = _ok(db, f"SELECT data_type, is_nullable, column_default FROM information_schema.columns "
                  f"WHERE table_schema='public' AND table_name='fixed_deposits' AND column_name='{COLUMN}';")
    assert row == "boolean|NO|true", row


@_NEEDS_PG
def test_a_row_written_without_the_column_is_an_estimate(db):
    assert _ok(db, _insert()).splitlines()[0] == "t"


@_NEEDS_PG
def test_false_is_stored_as_false_and_null_is_refused(db):
    assert _ok(db, _insert(f", {COLUMN}", ", false")).splitlines()[0] == "f"
    r = _psql(db, _insert(f", {COLUMN}", ", NULL"))
    assert r.returncode != 0 and "null value" in r.stderr and COLUMN in r.stderr, r.stderr


@_NEEDS_PG
def test_it_is_idempotent(db):
    for _ in range(2):
        assert _psql(db, MIGRATION.read_text(encoding="utf-8")).returncode == 0
    assert _ok(db, f"SELECT count(*) FROM information_schema.columns WHERE table_name='fixed_deposits' AND column_name='{COLUMN}';") == "1"


@_NEEDS_PG
def test_the_column_carries_its_comment(db):
    comment = _ok(db, f"SELECT col_description('public.fixed_deposits'::regclass, "
                      f"(SELECT attnum FROM pg_attribute WHERE attrelid='public.fixed_deposits'::regclass AND attname='{COLUMN}'));")
    assert "estimate" in comment and "receipt" in comment, comment


@_NEEDS_PG
def test_the_rollback_drops_the_column_and_a_reapply_restores_it(db):
    assert _psql(db, ROLLBACK.read_text(encoding="utf-8")).returncode == 0
    assert _ok(db, f"SELECT count(*) FROM information_schema.columns WHERE table_name='fixed_deposits' AND column_name='{COLUMN}';") == "0"
    assert _psql(db, MIGRATION.read_text(encoding="utf-8")).returncode == 0
    assert _ok(db, f"SELECT count(*) FROM information_schema.columns WHERE table_name='fixed_deposits' AND column_name='{COLUMN}';") == "1"
