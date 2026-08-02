"""
Migration 251 — posted journal LINES are immutable, on real PostgreSQL.

Why this test exists
--------------------
Migration 055 was written to make posted journal lines immutable and was never
applied: the migration ledger consumed the number 055 for a different file, so
`prevent_posted_journal_line_modification` simply did not exist in the database.
Nothing noticed for roughly two hundred migrations. The gap let migration 248
rewrite and delete lines of already-posted entries, which desynced the reporting
passbook and put a phantom "Round Off" row on the Profit & Loss until migration
249 repaired it by hand.

The lesson is not "restore the trigger" — that is one line. It is that a
guard's ABSENCE was invisible. These tests run against a database built by
replaying every migration from scratch, so if this trigger is ever dropped,
renamed, or lost to another numbering collision, CI fails loudly here instead of
a data migration quietly rewriting the ledger years later.

Runs only when HARNESS_PG is set + psql on PATH (same gate as the other
real-Postgres tests); skips in the mock-mode CI job. The `migrations` CI job
runs it against its Postgres service.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
CASH = "33333333-3333-3333-3333-333333333333"
SALES = "44444444-4444-4444-4444-444444444444"
POSTED = "55555555-5555-5555-5555-555555555555"
DRAFT = "66666666-6666-6666-6666-666666666666"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
        capture_output=True, text=True,
    )


def _scalar(dsn: str, sql: str) -> str:
    """Single value, unaligned and header-less (-tA)."""
    r = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture()
def migrated_db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"r251_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
            VALUES ('{CLIENT}', '{FIRM}', 'C1', 'Private Limited');
            INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type, is_active)
            VALUES ('{CASH}',  '{FIRM}', '{CLIENT}', '1000', 'Cash',  'Asset',   true),
                   ('{SALES}', '{FIRM}', '{CLIENT}', '4000', 'Sales', 'Revenue', true);

            -- A POSTED entry: Dr Cash 1,000.00 / Cr Sales 1,000.00
            INSERT INTO journal_entries (id, firm_id, client_id, entry_date, narration, entry_type, is_posted)
            VALUES ('{POSTED}', '{FIRM}', '{CLIENT}', DATE '2026-04-10', 'posted', 'Journal', true);
            INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise)
            VALUES ('{POSTED}', '{CASH}', 100000, 0),
                   ('{POSTED}', '{SALES}', 0, 100000);

            -- A DRAFT entry, whose lines must stay editable.
            INSERT INTO journal_entries (id, firm_id, client_id, entry_date, narration, entry_type, is_posted)
            VALUES ('{DRAFT}', '{FIRM}', '{CLIENT}', DATE '2026-04-11', 'draft', 'Journal', false);
            INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise)
            VALUES ('{DRAFT}', '{CASH}', 50000, 0),
                   ('{DRAFT}', '{SALES}', 0, 50000);
        """)
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _line_count(dsn: str, entry: str) -> int:
    return int(_scalar(dsn, f"SELECT count(*) FROM journal_lines WHERE journal_entry_id = '{entry}';"))


# ── the guard exists at all ─────────────────────────────────────────────────

def test_the_trigger_is_actually_installed(migrated_db):
    """The regression that started this: the trigger was missing from a
    database built by replaying every migration, and nothing said so."""
    found = _scalar(migrated_db, """
        SELECT count(*) FROM pg_trigger t
          JOIN pg_class c ON c.oid = t.tgrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relname = 'journal_lines'
           AND NOT t.tgisinternal
           AND t.tgname = 'trg_prevent_posted_journal_line_update';
    """)
    assert found == "1", "posted journal lines are unprotected — see migration 251"


# ── posted lines are immutable ──────────────────────────────────────────────

def test_cannot_change_a_posted_line_amount(migrated_db):
    """Exactly what migration 248 did to Trade Receivables."""
    r = _psql(migrated_db, f"""
        UPDATE journal_lines SET debit_paise = 99000
         WHERE journal_entry_id = '{POSTED}' AND account_id = '{CASH}';
    """)
    assert r.returncode != 0, "a posted line amount was rewritten"
    assert "posted journal entry" in r.stderr.lower()
    amount = _psql(migrated_db,
                   f"SELECT debit_paise FROM journal_lines "
                   f"WHERE journal_entry_id = '{POSTED}' AND account_id = '{CASH}';")
    assert "100000" in amount.stdout


def test_cannot_delete_a_posted_line(migrated_db):
    """Exactly what migration 248 did to the Round Off contra line — and the
    reason a posted entry could be left with Dr <> Cr."""
    r = _psql(migrated_db, f"""
        DELETE FROM journal_lines
         WHERE journal_entry_id = '{POSTED}' AND account_id = '{SALES}';
    """)
    assert r.returncode != 0, "a leg of a posted entry was deleted"
    assert _line_count(migrated_db, POSTED) == 2


def test_cannot_repoint_a_posted_line_to_another_account(migrated_db):
    r = _psql(migrated_db, f"""
        UPDATE journal_lines SET account_id = '{SALES}'
         WHERE journal_entry_id = '{POSTED}' AND account_id = '{CASH}';
    """)
    assert r.returncode != 0


# ── drafts stay editable ────────────────────────────────────────────────────

def test_draft_lines_can_still_be_edited(migrated_db):
    r = _psql(migrated_db, f"""
        UPDATE journal_lines SET debit_paise = 60000
         WHERE journal_entry_id = '{DRAFT}' AND account_id = '{CASH}';
    """)
    assert r.returncode == 0, r.stderr


def test_draft_lines_can_still_be_deleted(migrated_db):
    """Guards the bug in migration 055's own function: it returned NEW on every
    path, and NEW is NULL in a BEFORE DELETE trigger, which cancels the delete
    silently. A permitted delete must actually remove the row."""
    r = _psql(migrated_db, f"DELETE FROM journal_lines WHERE journal_entry_id = '{DRAFT}';")
    assert r.returncode == 0, r.stderr
    assert _line_count(migrated_db, DRAFT) == 0, (
        "the delete reported success but removed nothing — BEFORE DELETE returned NULL"
    )


def test_lines_can_still_be_inserted_into_a_posted_entry(migrated_db):
    """INSERT stays allowed by design — 'insert posted entry, then its lines' is
    a real posting path (migration 228 trigger A depends on it)."""
    r = _psql(migrated_db, f"""
        INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise)
        VALUES ('{POSTED}', '{CASH}', 1, 0);
    """)
    assert r.returncode == 0, r.stderr


# ── the passbook repair tools ───────────────────────────────────────────────

def test_apb_assert_no_drift_passes_on_a_consistent_cache(migrated_db):
    r = _psql(migrated_db, "SELECT apb_assert_no_drift();")
    assert r.returncode == 0, r.stderr


def test_apb_rebuild_repairs_a_tampered_cache(migrated_db):
    """The 249 scenario, reduced: corrupt a bucket, prove apb_assert_no_drift
    catches it and apb_rebuild_drifted fixes it."""
    seeded = _psql(migrated_db, f"""
        UPDATE account_period_balances SET debit_paise = debit_paise + 12345
         WHERE firm_id = '{FIRM}' AND client_id = '{CLIENT}' AND account_id = '{CASH}';
    """)
    assert seeded.returncode == 0, seeded.stderr

    caught = _psql(migrated_db, "SELECT apb_assert_no_drift();")
    assert caught.returncode != 0, "drift went undetected"
    assert "disagrees with the posted ledger" in caught.stderr

    fixed = _psql(migrated_db, "SELECT apb_rebuild_drifted();")
    assert fixed.returncode == 0, fixed.stderr
    assert _psql(migrated_db, "SELECT apb_assert_no_drift();").returncode == 0


def test_apb_rebuild_drifted_is_idempotent(migrated_db):
    assert _scalar(migrated_db, "SELECT apb_rebuild_drifted();") == "0", (
        "rebuilt clients that had not drifted"
    )


def test_repair_tools_are_not_callable_by_authenticated(migrated_db):
    """These rewrite the reporting cache — service-role/maintenance only."""
    r = _psql(migrated_db, "SET ROLE authenticated; SELECT apb_rebuild_drifted();")
    assert r.returncode != 0 and "permission denied" in r.stderr.lower(), (
        f"authenticated could rebuild the passbook: rc={r.returncode} {r.stderr}"
    )
