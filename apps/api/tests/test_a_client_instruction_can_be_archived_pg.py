"""Migration 430 — a client instruction can be archived, on real Postgres.

The archive endpoint wrote `is_archived` to `client_instructions`, a column
migration 073 never created, so PostgREST answered PGRST204 and every archive
400'd in every client workspace. 430 adds `is_archived boolean NOT NULL DEFAULT
false`; the rows already stored must read as NOT archived (none ever was).

Runs only when HARNESS_PG is set + psql on PATH, like every other *_pg test.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import uuid

import pytest

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

_MIGRATION = (pathlib.Path(__file__).resolve().parents[1] / "migrations"
              / "430_a_client_instruction_can_be_archived.sql")

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [l for l in r.stdout.strip().splitlines() if l]


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"instr430_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'Firm', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
              VALUES ('{CLIENT}', '{FIRM}', 'Client', 'Private Limited');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _apply(dsn: str) -> None:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(_MIGRATION)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_an_instruction_written_before_the_column_reads_as_not_archived(db):
    """The production case: rows that predate 430. Rebuild that state by
    dropping the column the template already carries, write a row, apply."""
    assert _psql(db, "ALTER TABLE client_instructions DROP COLUMN is_archived;").returncode == 0
    assert _psql(db, f"""INSERT INTO client_instructions (firm_id, client_id, title)
                         VALUES ('{FIRM}', '{CLIENT}', 'File GSTR-1 by the 9th');""").returncode == 0

    _apply(db)

    assert _rows(db, "SELECT is_archived FROM client_instructions") == ["f"]
    assert _rows(db, """SELECT is_nullable || '|' || column_default
                        FROM information_schema.columns
                        WHERE table_name = 'client_instructions'
                          AND column_name = 'is_archived'""") == ["NO|false"]


def test_the_archive_write_the_endpoint_sends_now_lands(db):
    assert _psql(db, f"""INSERT INTO client_instructions (id, firm_id, client_id, title)
                         VALUES ('33333333-3333-3333-3333-333333333333',
                                 '{FIRM}', '{CLIENT}', 'Old instruction');""").returncode == 0

    r = _psql(db, """UPDATE client_instructions SET is_archived = true, updated_at = now()
                     WHERE id = '33333333-3333-3333-3333-333333333333';""")

    assert r.returncode == 0, r.stderr
    assert _rows(db, "SELECT is_archived FROM client_instructions") == ["t"]


def test_rerunning_the_migration_changes_nothing(db):
    _apply(db)
    _apply(db)
    assert _rows(db, """SELECT count(*) FROM information_schema.columns
                        WHERE table_name = 'client_instructions'
                          AND column_name = 'is_archived'""") == ["1"]
