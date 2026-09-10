"""
Migration 355 — the CHECKs on a reconciliation adjustment, in Postgres.

WHY A REAL DATABASE
    The mock suite proves the SERVICE refuses an unexplained plug. It cannot
    prove the database does, and the database is the half that has to hold when
    the row is written another way — a script, a backfill, or the PostgREST path
    the frontend uses for ~83 tables (CLAUDE.md, "The frontend's second data
    path"), where rbac() never runs at all.

    That matters more here than usual, because the defect being closed is
    precisely a figure that reached a certified document with nothing checking
    it. A rule enforced only in the service is a rule with a way round it.

WHAT IS PINNED
    The figure and its explanation are inseparable in BOTH directions —
    a non-zero adjustment must carry a substantive reason, and a reason cannot
    outlive the figure it explained — and an explanation must have an author's
    timestamp. Plus the control: a session with no adjustment at all, which is
    every ordinary one, is written exactly as before.
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
    reason="the constraint proof requires HARNESS_PG + psql",
)

FIRM = "f3550000-0000-0000-0000-000000000001"
CLIENT = "c3550000-0000-0000-0000-000000000001"
ACCOUNT = "b3550000-0000-0000-0000-000000000001"
REASON = "bank charges debited on 30 April, not yet entered in the books"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-c", sql],
                          capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"adjchk_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email)
              VALUES ('{FIRM}', 'Adj Firm', 'adj@test.local');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
              VALUES ('{CLIENT}', '{FIRM}', 'Adj Client', 'Private Limited');
            INSERT INTO bank_accounts (id, firm_id, client_id, bank_name, account_no)
              VALUES ('{ACCOUNT}', '{FIRM}', '{CLIENT}', 'HDFC', '000111');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _insert(dsn: str, cols: str = "", vals: str = "") -> subprocess.CompletedProcess:
    return _psql(dsn, f"""
        INSERT INTO bank_reconciliations
          (firm_id, client_id, bank_account_id, period_start, period_end{cols})
        VALUES ('{FIRM}', '{CLIENT}', '{ACCOUNT}', '2025-04-01', '2025-04-30'{vals});
    """)


def test_a_session_with_no_adjustment_is_the_easy_row(db):
    assert _insert(db).returncode == 0


def test_an_explained_adjustment_is_accepted(db):
    got = _insert(db, ", adjustments_paise, adjustments_reason, adjustments_set_at",
                  f", 5000, '{REASON}', NOW()")
    assert got.returncode == 0, got.stderr


def test_a_bare_plug_is_rejected(db):
    """The defect itself: a number that reconciles by assertion."""
    got = _insert(db, ", adjustments_paise", ", 4730000")
    assert got.returncode != 0
    assert "adjustment_is_explained" in got.stderr


def test_a_scribbled_reason_is_rejected(db):
    got = _insert(db, ", adjustments_paise, adjustments_reason, adjustments_set_at",
                  ", 5000, 'ok', NOW()")
    assert got.returncode != 0
    assert "adjustment_is_explained" in got.stderr


def test_a_reason_left_behind_after_the_figure_was_zeroed_is_rejected(db):
    """It would describe money that is no longer in the tie-out."""
    got = _insert(db, ", adjustments_paise, adjustments_reason, adjustments_set_at",
                  f", 0, '{REASON}', NOW()")
    assert got.returncode != 0
    assert "adjustment_is_explained" in got.stderr


def test_zeroing_the_figure_without_clearing_the_reason_is_rejected(db):
    """The UPDATE direction, which is how it would actually happen."""
    assert _insert(db, ", adjustments_paise, adjustments_reason, adjustments_set_at",
                   f", 5000, '{REASON}', NOW()").returncode == 0
    got = _psql(db, "UPDATE bank_reconciliations SET adjustments_paise = 0;")
    assert got.returncode != 0
    assert "adjustment_is_explained" in got.stderr
    ok = _psql(db, "UPDATE bank_reconciliations SET adjustments_paise = 0, "
                   "adjustments_reason = NULL, adjustments_set_at = NULL;")
    assert ok.returncode == 0, ok.stderr


def test_an_explanation_with_no_timestamp_is_rejected(db):
    got = _insert(db, ", adjustments_paise, adjustments_reason",
                  f", 5000, '{REASON}'")
    assert got.returncode != 0
    assert "adjustment_is_attributed" in got.stderr


def test_the_author_must_be_a_real_internal_user(db):
    """The column FKs public.users(id) — the INTERNAL id, not the Supabase auth
    id (CLAUDE.md)."""
    got = _insert(db, ", adjustments_paise, adjustments_reason, adjustments_set_at, "
                      "adjustments_set_by",
                  f", 5000, '{REASON}', NOW(), '99999999-0000-0000-0000-000000000001'")
    assert got.returncode != 0
    assert "foreign key" in got.stderr.lower()
