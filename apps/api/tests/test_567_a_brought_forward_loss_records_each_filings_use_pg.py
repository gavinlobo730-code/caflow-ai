"""
Migration 567, proved against real PostgreSQL (POST-A-073).

WHAT IS BEING PROVED
    1. `brought_forward_losses.utilisations` exists, is NOT NULL and defaults to an empty object, so every row that predates the column reads
       as "no filing has used it", which is exactly what it was.
    2. The CHECK keeps it an object: an array, a string or a number is refused at the column, because the rule in
       `domain/income_tax/loss_utilisation.py` reads an object and a screen or a hand-made request can reach the table by other doors. A
       second CHECK keeps the entries together within `utilized_amount_paise` (the difference is the hand-recorded baseline and cannot be
       negative), through an IMMUTABLE function, so a direct write cannot leave the entries larger than the total.
    3. What the rule returns is accepted by the table's EXISTING checks (`chk_remaining_consistency`, `chk_utilized_lte_original`) for the
       cases that matter, and a write that moves one total without the other is refused, which is the second lock behind the rule's
       "written together".
    4. The compare `store_bf_loss_use` makes (the totals as they were read) matches no row once a hand edit has landed first.
    5. The file is re-runnable, and its rollback takes the column away.

NEGATIVE CONTROL
    Drop the CHECKs from the migration and the malformed-value and the over-the-total cases write straight in. Drop the NOT NULL and the
    NULL case does.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from domain.income_tax.loss_utilisation import after_filing, available_for_year_paise

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATION = next((API_ROOT / "migrations").glob("567_a_brought_forward_loss_records_what_each_filed_return_used_of_it.sql"))
ROLLBACK = next((API_ROOT / "migrations").glob("567_*_rollback.sql"))
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the brought-forward loss proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000567"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000567"
USER = "c0000000-0000-0000-0000-000000000567"
L = 1_00_000_00


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _one(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql, tuples=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m567_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert MIGRATION.name not in pg_template.failed, "migration 567 did not apply — everything below would pass vacuously"
        for sql in (
            f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F567', 'f567@t.in');",
            f"INSERT INTO clients (id, firm_id, client_name, entity_type, pan) VALUES "
            f"('{CLIENT}', '{FIRM}', 'C567', 'Private Limited', 'AAACA1234E');",
            f"INSERT INTO auth.users (id, email) VALUES ('{USER}', 'u567@t.in');",
            f"INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES "
            f"('{USER}', '{FIRM}', '{USER}', 'U567', 'u567@t.in', 'Partner');",
        ):
            r = _psql(dsn, sql)
            assert r.returncode == 0, f"{sql[:70]}… → {r.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _loss(dsn: str, original: int = 10 * L, utilized: int = 0) -> str:
    loss_id = str(uuid.uuid4())
    r = _psql(dsn, (
        "INSERT INTO brought_forward_losses (id, firm_id, client_id, assessment_year, loss_type, original_amount_paise, "
        f"utilized_amount_paise, remaining_amount_paise, expiry_assessment_year, created_by) VALUES ('{loss_id}', '{FIRM}', '{CLIENT}', '2024-25', "
        f"'business', {original}, {utilized}, {original - utilized}, '2032-33', '{USER}');"))
    assert r.returncode == 0, r.stderr
    return loss_id


def _row(dsn: str, loss_id: str) -> dict:
    out = _one(dsn, f"SELECT row_to_json(t) FROM (SELECT * FROM brought_forward_losses WHERE id = '{loss_id}') t;")
    return json.loads(out)


def _store(dsn: str, loss_id: str, columns: dict) -> subprocess.CompletedProcess:
    return _psql(dsn, (
        f"UPDATE brought_forward_losses SET utilisations = '{json.dumps(columns['utilisations'])}'::jsonb, "
        f"utilized_amount_paise = {columns['utilized_amount_paise']}, remaining_amount_paise = {columns['remaining_amount_paise']} "
        f"WHERE id = '{loss_id}';"))


# ── 1. the column and its default ────────────────────────────────────────────

def test_a_row_written_before_the_column_reads_as_never_used(db):
    row = _row(db, _loss(db, utilized=3 * L))
    assert row["utilisations"] == {}
    assert available_for_year_paise(row, "2025-26") == 7 * L, "the hand-recorded 3 lakh is the baseline and is not offered back"


def test_the_column_is_not_null(db):
    r = _psql(db, f"UPDATE brought_forward_losses SET utilisations = NULL WHERE id = '{_loss(db)}';")
    assert r.returncode != 0 and "null value" in r.stderr


# ── 2. an object, and nothing else ───────────────────────────────────────────

@pytest.mark.parametrize("bad", ["'[]'", "'\"x\"'", "'5'", "'true'"])
def test_the_column_is_refused_anything_but_an_object(db, bad):
    r = _psql(db, f"UPDATE brought_forward_losses SET utilisations = {bad}::jsonb WHERE id = '{_loss(db)}';")
    assert r.returncode != 0 and ("brought_forward_losses_utilisations_is_an_object" in r.stderr
                                  or "brought_forward_losses_entries_within_utilized" in r.stderr)


# ── 3. what the rule returns is accepted, and the pair is held together ──────

def test_what_a_filing_writes_is_accepted_by_the_tables_own_checks(db):
    loss_id = _loss(db, utilized=3 * L)                                  # 3 lakh by hand
    row = _row(db, loss_id)
    r = _store(db, loss_id, after_filing(row, "f-2025", "2025-26", 4 * L))
    assert r.returncode == 0, r.stderr
    after = _row(db, loss_id)
    assert (after["utilized_amount_paise"], after["remaining_amount_paise"]) == (7 * L, 3 * L)
    assert after["utilisations"] == {"f-2025": {"financial_year": "2025-26", "amount_paise": 4 * L, "return_type": "original"}}
    # the same year again is offered the loss back, less only the hand-recorded part
    assert available_for_year_paise(after, "2025-26") == 7 * L
    assert available_for_year_paise(after, "2026-27") == 3 * L
    # a revised return replaces the year's entry and the checks still hold
    r = _store(db, loss_id, after_filing(after, "f-rev", "2025-26", 6 * L, "revised"))
    assert r.returncode == 0, r.stderr
    assert _row(db, loss_id)["remaining_amount_paise"] == 1 * L


def test_a_use_beyond_the_loss_is_capped_by_the_rule_and_refused_by_the_table(db):
    loss_id = _loss(db, utilized=8 * L)
    row = _row(db, loss_id)
    assert _store(db, loss_id, after_filing(row, "f", "2025-26", 9 * L)).returncode == 0
    assert _row(db, loss_id)["remaining_amount_paise"] == 0
    # the table's own check, if a caller bypasses the rule
    r = _psql(db, f"UPDATE brought_forward_losses SET utilized_amount_paise = {11 * L}, remaining_amount_paise = {-1 * L} WHERE id = '{loss_id}';")
    assert r.returncode != 0 and "chk_" in r.stderr


def test_one_total_cannot_move_without_the_other(db):
    r = _psql(db, f"UPDATE brought_forward_losses SET utilized_amount_paise = {4 * L} WHERE id = '{_loss(db)}';")
    assert r.returncode != 0 and "chk_remaining_consistency" in r.stderr


# ── 3b. the entries stay within the total, whoever writes ───────────────────

def test_the_entries_cannot_exceed_the_total_that_holds_them(db):
    loss_id = _loss(db, utilized=3 * L)
    entries = json.dumps({"f1": {"financial_year": "2025-26", "amount_paise": 2 * L}, "f2": {"financial_year": "2026-27", "amount_paise": 2 * L}})
    r = _psql(db, f"UPDATE brought_forward_losses SET utilisations = '{entries}'::jsonb WHERE id = '{loss_id}';")
    assert r.returncode != 0 and "brought_forward_losses_entries_within_utilized" in r.stderr
    ok = json.dumps({"f1": {"financial_year": "2025-26", "amount_paise": 2 * L}, "f2": {"financial_year": "2026-27", "amount_paise": 1 * L}})
    assert _psql(db, f"UPDATE brought_forward_losses SET utilisations = '{ok}'::jsonb WHERE id = '{loss_id}';").returncode == 0, "3 lakh in entries under a 3 lakh total is allowed"


def test_an_entry_whose_amount_is_not_a_number_is_refused(db):
    r = _psql(db, f"UPDATE brought_forward_losses SET utilisations = '{{\"f\": {{\"amount_paise\": \"lots\"}}}}'::jsonb WHERE id = '{_loss(db, utilized=L)}';")
    assert r.returncode != 0


def test_the_hand_edit_route_still_works_beside_the_entries(db):
    """A write that raises the total only (what the removed route that typed a use in with no year did) is still let through by the new check."""
    loss_id = _loss(db, utilized=2 * L)
    assert _store(db, loss_id, after_filing(_row(db, loss_id), "f", "2025-26", 3 * L)).returncode == 0
    r = _psql(db, f"UPDATE brought_forward_losses SET utilized_amount_paise = {6 * L}, remaining_amount_paise = {4 * L} WHERE id = '{loss_id}';")
    assert r.returncode == 0, r.stderr


# ── 4. the compare the store makes ───────────────────────────────────────────

def test_a_write_that_names_the_totals_it_read_matches_nothing_once_a_hand_edit_landed(db):
    loss_id = _loss(db)
    read = _row(db, loss_id)
    assert _psql(db, f"UPDATE brought_forward_losses SET utilized_amount_paise = {L}, remaining_amount_paise = {9 * L} "
                     f"WHERE id = '{loss_id}';").returncode == 0                       # a hand edit lands first
    out = _one(db, (
        "WITH t AS (UPDATE brought_forward_losses SET utilisations = '{}'::jsonb WHERE id = '" + loss_id + "' "
        f"AND utilized_amount_paise = {read['utilized_amount_paise']} AND remaining_amount_paise = {read['remaining_amount_paise']} "
        "RETURNING 1) SELECT count(*) FROM t;"))
    assert out.splitlines()[-1] == "0"


# ── 5. re-runnable, and reversible ───────────────────────────────────────────

def test_the_file_can_be_run_again(db):
    for _ in range(2):
        r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(MIGRATION)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_the_rollback_takes_the_column_and_its_check_away(db):
    r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(ROLLBACK)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert _one(db, "SELECT count(*) FROM information_schema.columns WHERE table_name = 'brought_forward_losses' "
                    "AND column_name = 'utilisations';") == "0"
    assert _one(db, "SELECT count(*) FROM pg_constraint WHERE conname IN ('brought_forward_losses_utilisations_is_an_object', "
                    "'brought_forward_losses_entries_within_utilized');") == "0"
    assert _one(db, "SELECT count(*) FROM pg_proc WHERE proname = 'brought_forward_loss_entries_total';") == "0"
