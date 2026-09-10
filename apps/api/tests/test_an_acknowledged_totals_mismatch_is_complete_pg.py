"""
Migration 354 — the CHECKs on an acknowledged totals mismatch, in Postgres.

WHY THIS NEEDS A REAL DATABASE
    The mock suite can prove the ROUTER refuses a scribbled reason. It cannot
    prove the database does, and the database is the half that has to hold when
    somebody writes the row another way — a script, a backfill, the PostgREST
    path the frontend uses for ~83 tables (CLAUDE.md, "The frontend's second data
    path"). BANK-05 is the cautionary case in this same subsystem:
    `adjustments_paise` is a plug any Executive can write with no reason and no
    audit row, and there is no constraint anywhere that would have stopped it.

WHAT IS PINNED
    The three rules that make the record readable a year later, each with the
    row that must be rejected:

      * a reason must be substantive — ten characters, the same floor migration
        253 puts on reopening a completed reconciliation;
      * the reason and the two differences it excused travel TOGETHER, in both
        directions: a reason with no figures cannot be judged, figures with no
        reason are a plug;
      * and it has to be an actual disagreement. A reason recorded against two
        zeroes is an explanation for nothing, which is how a box becomes
        something people tick out of habit.

    Plus the control: an ordinary import, with all five columns NULL, is
    accepted. "Nothing was overridden" must remain the easy row to write.
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

FIRM = "f9400000-0000-0000-0000-000000000001"
CLIENT = "c9400000-0000-0000-0000-000000000001"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-c", sql],
                          capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"ackchk_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email)
              VALUES ('{FIRM}', 'Ack Firm', 'ack@test.local');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
              VALUES ('{CLIENT}', '{FIRM}', 'Ack Client', 'Private Limited');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _insert(dsn: str, extra_cols: str = "", extra_vals: str = "") -> subprocess.CompletedProcess:
    return _psql(dsn, f"""
        INSERT INTO bank_statements
          (firm_id, client_id, bank_name, statement_from, statement_to{extra_cols})
        VALUES ('{FIRM}', '{CLIENT}', 'Cosmos Co-op Bank',
                '2026-04-01', '2026-04-30'{extra_vals});
    """)


REASON = "the export was filtered to UPI only; the printed total covers the month"
_FULL_COLS = (", totals_mismatch_reason, totals_mismatch_debit_difference_paise, "
              "totals_mismatch_credit_difference_paise, "
              "totals_mismatch_acknowledged_at")


def test_an_ordinary_statement_needs_none_of_it(db):
    """The control. NULL in all five is what "nothing was overridden" looks
    like, and it must stay the easy row to write."""
    assert _insert(db).returncode == 0


def test_a_complete_acknowledgement_is_accepted(db):
    got = _insert(db, _FULL_COLS, f", '{REASON}', -2000000, 0, NOW()")
    assert got.returncode == 0, got.stderr


def test_a_scribbled_reason_is_rejected(db):
    got = _insert(db, _FULL_COLS, ", 'fine', -2000000, 0, NOW()")
    assert got.returncode != 0
    assert "reason_substantive" in got.stderr


def test_a_reason_with_no_figures_beside_it_is_rejected(db):
    """An assertion, not a record: nobody can judge the reason against the
    difference it excused."""
    got = _insert(db, ", totals_mismatch_reason", f", '{REASON}'")
    assert got.returncode != 0
    assert "is_complete" in got.stderr


def test_figures_with_no_reason_are_rejected(db):
    """The other direction, and the BANK-05 shape exactly: a number that
    reconciles by assertion."""
    got = _psql(db, f"""
        INSERT INTO bank_statements
          (firm_id, client_id, bank_name, statement_from, statement_to,
           totals_mismatch_debit_difference_paise,
           totals_mismatch_credit_difference_paise)
        VALUES ('{FIRM}', '{CLIENT}', 'Cosmos Co-op Bank',
                '2026-04-01', '2026-04-30', -2000000, 0);
    """)
    assert got.returncode != 0
    assert "is_complete" in got.stderr


def test_an_acknowledgement_of_nothing_is_rejected(db):
    """Both differences zero is a check that PASSED. A reason recorded against
    it puts an explanation on the record for nothing."""
    got = _insert(db, _FULL_COLS, f", '{REASON}', 0, 0, NOW()")
    assert got.returncode != 0
    assert "is_a_mismatch" in got.stderr


def test_the_acknowledger_must_be_a_real_internal_user(db):
    """The column FKs public.users(id) — the INTERNAL id, not the Supabase auth
    id (CLAUDE.md). This module already carries one scar from passing the wrong
    one, in the column-mapping save."""
    got = _insert(db, _FULL_COLS + ", totals_mismatch_acknowledged_by",
                  f", '{REASON}', -2000000, 0, NOW(), "
                  f"'99999999-0000-0000-0000-000000000001'")
    assert got.returncode != 0
    assert "foreign key" in got.stderr.lower()
