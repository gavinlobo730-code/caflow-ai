"""
Migration 253 — the reopen columns and their guards, on real PostgreSQL.

The reason and history constraints are enforced in the DATABASE, not only in the
service, so no code path can reopen a certified period anonymously or lose a
certification along the way. That is only worth claiming if it is tested against
a real Postgres — the mock-mode FakeDB has no CHECK constraints at all and would
happily accept every one of the rows this file expects to be rejected.

Runs only when HARNESS_PG is set + psql on PATH (same gate as the other
real-Postgres tests); skips in the mock-mode CI job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

FIRM = "bbbbbbbb-0000-0000-0000-000000000001"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000002"
BA = "bbbbbbbb-0000-0000-0000-000000000003"
RECON = "bbbbbbbb-0000-0000-0000-000000000004"
REASON = "April rent was reconciled into March by mistake"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
        capture_output=True, text=True,
    )


def _scalar(dsn: str, sql: str) -> str:
    r = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture()
def migrated_db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"r253_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
            VALUES ('{CLIENT}', '{FIRM}', 'C', 'Private Limited');
            INSERT INTO bank_accounts (id, firm_id, client_id, bank_name, account_no)
            VALUES ('{BA}', '{FIRM}', '{CLIENT}', 'HDFC', '0001');
            INSERT INTO bank_reconciliations
              (id, firm_id, client_id, bank_account_id, account_no,
               period_start, period_end, opening_balance_paise, closing_balance_paise,
               status, completed_at, snapshot)
            VALUES ('{RECON}', '{FIRM}', '{CLIENT}', '{BA}', '0001',
                    DATE '2025-04-01', DATE '2025-04-30', 100000, 160000,
                    'completed', now(), '{{"summary":{{"reconciles":true}}}}'::jsonb);
        """)
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


# ── columns exist and default sensibly ──────────────────────────────────────

def test_reopen_columns_default_to_never_reopened(migrated_db):
    row = _scalar(migrated_db, f"""
        SELECT reopen_count || '|' || reopen_history::text || '|' ||
               coalesce(reopen_reason, 'NULL')
          FROM bank_reconciliations WHERE id = '{RECON}';
    """)
    assert row == "0|[]|NULL"


# ── the reason guard ────────────────────────────────────────────────────────

def test_a_reopen_without_a_reason_is_rejected_by_the_database(migrated_db):
    r = _psql(migrated_db, f"""
        UPDATE bank_reconciliations
           SET status='in_progress', reopen_count=1,
               reopen_history='[{{"reopened_at":"now"}}]'::jsonb
         WHERE id='{RECON}';
    """)
    assert r.returncode != 0, "a certified period was reopened with no reason"
    assert "reopen_reason_required" in r.stderr


def test_a_thin_reason_is_rejected(migrated_db):
    r = _psql(migrated_db, f"""
        UPDATE bank_reconciliations
           SET reopen_count=1, reopen_reason='typo',
               reopen_history='[{{"reopened_at":"now"}}]'::jsonb
         WHERE id='{RECON}';
    """)
    assert r.returncode != 0 and "reopen_reason_required" in r.stderr


def test_a_whitespace_only_reason_is_rejected(migrated_db):
    """btrim, not length — spaces are not a reason."""
    r = _psql(migrated_db, f"""
        UPDATE bank_reconciliations
           SET reopen_count=1, reopen_reason='             ',
               reopen_history='[{{"reopened_at":"now"}}]'::jsonb
         WHERE id='{RECON}';
    """)
    assert r.returncode != 0 and "reopen_reason_required" in r.stderr


def test_a_substantive_reason_is_accepted(migrated_db):
    r = _psql(migrated_db, f"""
        UPDATE bank_reconciliations
           SET status='in_progress', completed_at=NULL, reopen_count=1,
               reopen_reason='{REASON}', reopened_at=now(),
               reopen_history='[{{"reason":"{REASON}","snapshot":{{"summary":{{}}}}}}]'::jsonb
         WHERE id='{RECON}';
    """)
    assert r.returncode == 0, r.stderr
    assert _scalar(migrated_db, f"SELECT status FROM bank_reconciliations WHERE id='{RECON}';") == "in_progress"


# ── the history guard ───────────────────────────────────────────────────────

def test_reopen_count_must_match_the_history_length(migrated_db):
    """The count is a summary of the history. Letting them disagree would let a
    reopen be recorded without preserving the certification it replaced —
    exactly the loss this design exists to prevent."""
    r = _psql(migrated_db, f"""
        UPDATE bank_reconciliations
           SET reopen_count=3, reopen_reason='{REASON}',
               reopen_history='[{{"reason":"{REASON}"}}]'::jsonb
         WHERE id='{RECON}';
    """)
    assert r.returncode != 0 and "reopen_count_matches_history" in r.stderr


def test_recording_a_reopen_without_preserving_the_snapshot_is_rejected(migrated_db):
    """count=1 with an empty history is the shape a 'forgot to keep the
    snapshot' bug would produce."""
    r = _psql(migrated_db, f"""
        UPDATE bank_reconciliations
           SET reopen_count=1, reopen_reason='{REASON}', reopen_history='[]'::jsonb
         WHERE id='{RECON}';
    """)
    assert r.returncode != 0 and "reopen_count_matches_history" in r.stderr


def test_two_reopens_with_two_preserved_snapshots_is_accepted(migrated_db):
    r = _psql(migrated_db, f"""
        UPDATE bank_reconciliations
           SET reopen_count=2, reopen_reason='{REASON}',
               reopen_history='[{{"snapshot":{{"a":1}}}},{{"snapshot":{{"b":2}}}}]'::jsonb
         WHERE id='{RECON}';
    """)
    assert r.returncode == 0, r.stderr
    assert _scalar(migrated_db,
                   f"SELECT jsonb_array_length(reopen_history) FROM bank_reconciliations "
                   f"WHERE id='{RECON}';") == "2"
