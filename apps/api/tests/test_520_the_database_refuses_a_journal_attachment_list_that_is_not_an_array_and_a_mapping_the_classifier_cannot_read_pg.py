"""Migration 520 — two shapes the application insists on are now insisted on by the database (POST-A-163, POST-A-164).

WHAT IS HELD
    * `journal_entries.attachments` must be a JSON array of at most twenty elements: a string, an object, a number and a 21-element
      array are each refused on INSERT and on UPDATE (of a DRAFT: a posted entry is refused earlier, by the immutability trigger), an empty array and twenty elements are accepted, and the sibling bank column's
      limit (migration 259) is the same number;
    * `chart_of_accounts.schedule_iii_mapping` must be NULL or something `canonical_caption` can read: every caption the engine
      presents, the five older spellings and the 'Fixed Assets' heading are accepted; a made-up caption, an empty string and a
      padded one are refused on INSERT and on UPDATE;
    * the SQL list IS the Python vocabulary: the accepted set read back from the constraint in a migration-built database equals
      `CAPTIONS | CAPTION_ALIASES | {heading}` exactly (a caption added to Python without a migration fails here);
    * an OLD row that violates a constraint does not fail the deploy: the constraint is added NOT VALID, VALIDATE finds the row, a
      NOTICE says so and the constraint stays NOT VALID and still binds new rows;
    * idempotent, and its rollback drops both.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from domain.reporting import schedule_iii

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_STEM = "520_the_database_refuses_a_journal_attachment_list_that_is_not_an_array_and_a_mapping_the_classifier_cannot_read"
MIGRATION = API_ROOT / "migrations" / f"{_STEM}.sql"
ROLLBACK = API_ROOT / "migrations" / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the constraint proofs require HARNESS_PG + psql",
)

FIRM = "52000000-0000-0000-0000-000000000001"
CLIENT = "52000000-0000-0000-0000-0000000000c1"
ACCOUNT = "52000000-0000-0000-0000-0000000000a1"
ENTRY = "52000000-0000-0000-0000-0000000000e1"
READABLE = set(schedule_iii.CAPTIONS) | set(schedule_iii.CAPTION_ALIASES) | {schedule_iii._FIXED_ASSETS_HEADING}


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _refused(dsn: str, sql: str, constraint: str) -> bool:
    r = _psql(dsn, sql)
    return r.returncode != 0 and constraint in r.stderr


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"chk_m520_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        assert f"{_STEM}.sql" not in pg_template.failed, "migration 520 did not apply, so everything below would pass vacuously"
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'M520 Firm', 'm520@test.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}', '{FIRM}', 'Client A', 'Private Limited');
            INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type)
              VALUES ('{ACCOUNT}', '{FIRM}', '{CLIENT}', '1001', 'Cash', 'Asset');
            INSERT INTO journal_entries (id, firm_id, client_id, entry_date, reference_no, narration, entry_type, is_posted, status)
              VALUES ('{ENTRY}', '{FIRM}', '{CLIENT}', '2026-06-15', 'M520-1', 'n', 'Journal', false, 'draft');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


ATT = "journal_entries_attachments_check"
MAP = "chart_of_accounts_schedule_iii_mapping_check"


def _insert_entry(attachments_sql: str) -> str:
    return (f"INSERT INTO journal_entries (firm_id, client_id, entry_date, reference_no, narration, entry_type, attachments) "
            f"VALUES ('{FIRM}', '{CLIENT}', '2026-06-16', 'M520-' || gen_random_uuid()::text, 'n', 'Journal', {attachments_sql});")


# ── journal attachments ─────────────────────────────────────────────────────────────────────────────

@_NEEDS_PG
@pytest.mark.parametrize("value", ["'[]'::jsonb", "'[{\"name\":\"a\",\"url\":\"https://x.test/a\"}]'::jsonb",
                                   "(SELECT jsonb_agg(jsonb_build_object('name', n)) FROM generate_series(1, 20) n)"])
def test_an_array_of_up_to_twenty_is_accepted(db, value):
    assert _psql(db, _insert_entry(value)).returncode == 0


@_NEEDS_PG
@pytest.mark.parametrize("value", ["'\"a string\"'::jsonb", "'{\"name\":\"a\"}'::jsonb", "'7'::jsonb", "'null'::jsonb",
                                   "(SELECT jsonb_agg(jsonb_build_object('name', n)) FROM generate_series(1, 21) n)"])
def test_anything_else_is_refused_on_insert_and_on_update(db, value):
    assert _refused(db, _insert_entry(value), ATT)
    assert _refused(db, f"UPDATE journal_entries SET attachments = {value} WHERE id = '{ENTRY}';", ATT)


@_NEEDS_PG
def test_the_limit_is_the_bank_columns_limit(db):
    bank = _ok(db, "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'bank_transactions_attachments_check';")
    journal = _ok(db, f"SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = '{ATT}';")
    assert "<= 20" in bank and "<= 20" in journal, (bank, journal)


# ── the chart-of-accounts mapping ───────────────────────────────────────────────────────────────────

def _set_mapping(value: str) -> str:
    return f"UPDATE chart_of_accounts SET schedule_iii_mapping = {value} WHERE id = '{ACCOUNT}';"


@_NEEDS_PG
def test_the_accepted_set_in_sql_is_exactly_what_python_can_read(db):
    definition = _ok(db, f"SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = '{MAP}';")
    in_sql = set(re.findall(r"'((?:[^']|'')*)'::text", definition))
    in_sql = {v.replace("''", "'") for v in in_sql}
    assert in_sql == READABLE, (sorted(in_sql - READABLE), sorted(READABLE - in_sql))


@_NEEDS_PG
def test_every_readable_spelling_is_accepted_and_null_too(db):
    for value in sorted(READABLE):
        quoted = "'" + value.replace("'", "''") + "'"
        assert _psql(db, _set_mapping(quoted)).returncode == 0, value
    assert _psql(db, _set_mapping("NULL")).returncode == 0


@_NEEDS_PG
@pytest.mark.parametrize("value", ["'Miscellaneous'", "''", "' Other Expenses'", "'Other Expenses '", "'other expenses'"])
def test_a_caption_the_classifier_cannot_read_is_refused_on_update_and_on_insert(db, value):
    assert _refused(db, _set_mapping(value), MAP)
    assert _refused(db, (f"INSERT INTO chart_of_accounts (firm_id, client_id, account_code, account_name, account_type, schedule_iii_mapping) "
                         f"VALUES ('{FIRM}', '{CLIENT}', 'X-' || gen_random_uuid()::text, 'n', 'Asset', {value});"), MAP)


def test_the_python_reader_agrees_that_what_is_refused_is_unreadable():
    for value in ("Miscellaneous", "", " Other Expenses", "Other Expenses ", "other expenses"):
        assert value not in READABLE
    # canonical_caption strips, so a padded spelling would be READ by Python and is refused by SQL: the writers strip first.
    assert schedule_iii.canonical_caption(" Other Expenses") == "Other Expenses"


# ── an old violating row does not fail the deploy ──────────────────────────────────────────────────

@_NEEDS_PG
def test_an_old_violating_row_leaves_the_constraint_not_valid_and_still_binding(db):
    _ok(db, f"ALTER TABLE chart_of_accounts DROP CONSTRAINT {MAP};")
    _ok(db, f"UPDATE chart_of_accounts SET schedule_iii_mapping = 'Legacy Garbage' WHERE id = '{ACCOUNT}';")
    r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    assert "left NOT VALID" in r.stderr, r.stderr
    assert _ok(db, f"SELECT convalidated FROM pg_constraint WHERE conname = '{MAP}';") == "f"
    # it still binds NEW values, and the old row can be repaired in place
    assert _refused(db, f"UPDATE chart_of_accounts SET schedule_iii_mapping = 'More Garbage' WHERE id = '{ACCOUNT}';", MAP)
    assert _psql(db, _set_mapping("'Other Expenses'")).returncode == 0


@_NEEDS_PG
def test_a_clean_database_has_both_constraints_valid(db):
    assert _ok(db, f"SELECT count(*) FROM pg_constraint WHERE conname IN ('{ATT}', '{MAP}') AND convalidated;") == "2"


# ── idempotent, reversible ──────────────────────────────────────────────────────────────────────────

@_NEEDS_PG
def test_it_is_idempotent(db):
    for _ in range(2):
        assert _psql(db, MIGRATION.read_text(encoding="utf-8")).returncode == 0
    assert _ok(db, f"SELECT count(*) FROM pg_constraint WHERE conname IN ('{ATT}', '{MAP}');") == "2"


@_NEEDS_PG
def test_the_rollback_drops_both_and_the_garbage_is_accepted_again(db):
    assert _psql(db, ROLLBACK.read_text(encoding="utf-8")).returncode == 0
    assert _ok(db, f"SELECT count(*) FROM pg_constraint WHERE conname IN ('{ATT}', '{MAP}');") == "0"
    assert _psql(db, _set_mapping("'Miscellaneous'")).returncode == 0
    assert _psql(db, _insert_entry("'\"a string\"'::jsonb")).returncode == 0
