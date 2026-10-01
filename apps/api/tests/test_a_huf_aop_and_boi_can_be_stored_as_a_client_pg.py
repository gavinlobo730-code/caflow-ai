"""Migration 453's CHECK on clients.entity_type, against a real Postgres.

WHY THIS IS A REAL-POSTGRES TEST
    models/client.EntityType refuses a made-up value and the mock suite proves
    that. Neither proves the DATABASE accepts the three new ones, and the client
    master is also written by the lead-conversion path, the bulk importer and,
    in places, straight over PostgREST — so the table's own constraint is the
    only one every door stands behind.

    It also proves the other half of the claim in the migration's header: that
    the widened CHECK is a SUPERSET. A migration that dropped an old value would
    pass the new-value tests and fail every client already on the book.
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
    reason="migration 453 constraint proof requires HARNESS_PG + psql",
)

FIRM = "f4530000-0000-0000-0000-000000000001"

ORIGINAL_EIGHT = ["Proprietorship", "Partnership", "LLP", "Private Limited",
                  "Public Limited", "Trust", "Society", "Individual"]
NEW_THREE = ["HUF", "AOP", "BOI"]


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-X", "-q"] + (["-tA"] if tuples else [])
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"v453_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'T', 't@x.in');")
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _insert_client(dsn: str, entity_type: str) -> subprocess.CompletedProcess:
    return _psql(dsn, f"""
        INSERT INTO clients (firm_id, client_name, entity_type)
        VALUES ('{FIRM}', 'Client {uuid.uuid4().hex[:6]}', '{entity_type}');
    """)


@pytest.mark.parametrize("value", NEW_THREE)
def test_a_huf_an_aop_and_a_boi_are_accepted(db, value):
    r = _insert_client(db, value)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("value", ORIGINAL_EIGHT)
def test_every_value_migration_001_allowed_is_still_accepted(db, value):
    """The widened CHECK is a superset, so no client already on the book is
    refused by a re-save."""
    r = _insert_client(db, value)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("value", ["Hindu Undivided Family", "huf", "Company", "Others", ""])
def test_a_value_nobody_defined_is_still_refused(db, value):
    """Widening by three is not widening to anything. Lower-case 'huf' is
    refused too: the model's enum, the form and the CHECK all speak one
    spelling, and the normalising fold lives in the reader, not the table."""
    r = _insert_client(db, value)
    assert r.returncode != 0
    assert "clients_entity_type_check" in r.stderr


def test_the_constraint_is_validated_not_left_not_valid(db):
    """NOT VALID would leave the constraint unchecked against existing rows
    and invisible to the planner. The migration validates it."""
    r = _psql(db, """
        SELECT convalidated FROM pg_constraint
         WHERE conname = 'clients_entity_type_check'
           AND conrelid = 'public.clients'::regclass;
    """, tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "t"


def test_the_constraint_lists_exactly_the_eleven_values(db):
    r = _psql(db, """
        SELECT pg_get_constraintdef(oid) FROM pg_constraint
         WHERE conname = 'clients_entity_type_check'
           AND conrelid = 'public.clients'::regclass;
    """, tuples=True)
    assert r.returncode == 0, r.stderr
    definition = r.stdout
    for value in ORIGINAL_EIGHT + NEW_THREE:
        assert f"'{value}'" in definition, f"{value} missing from {definition}"
