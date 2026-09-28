"""Migration 433 — two entities with no PAN are not duplicates, on real Postgres.

059 declared the PAN key NULLS NOT DISTINCT, so a firm could hold only ONE
entity without a PAN. 433 keeps one-PAN-one-entity and lets absences coexist.
Runs only when HARNESS_PG is set + psql on PATH, like every other *_pg test.
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

FIRM = "11111111-1111-1111-1111-111111111111"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"ent433_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert _psql(dsn, f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');").returncode == 0
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _entity(pan: str) -> str:
    return (f"INSERT INTO entities (firm_id, entity_type, full_name, pan) "
            f"VALUES ('{FIRM}', 'Individual', 'P', {pan})")


def test_two_entities_with_no_pan_coexist(db):
    assert _psql(db, _entity("NULL")).returncode == 0
    second = _psql(db, _entity("NULL"))
    assert second.returncode == 0, second.stderr


def test_one_pan_is_still_one_entity(db):
    assert _psql(db, _entity("'ABCDE1234F'")).returncode == 0
    again = _psql(db, _entity("'ABCDE1234F'"))
    assert again.returncode != 0
    assert "entities_pan_unique" in again.stderr
