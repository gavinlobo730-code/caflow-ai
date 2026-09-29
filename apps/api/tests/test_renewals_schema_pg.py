"""Migration 438 — `public.renewals` gains `service_type` and `renewal_date`
becomes nullable, checked directly against a real, migrated schema.

The application-level behaviour (create_renewal no longer drops service_type
before the INSERT, and no longer fabricates a renewal_date) is pinned in
tests/test_a_renewal_keeps_its_service_type_and_a_blank_date.py with a fake
db that inspects the INSERT payload; this file is the schema half — that the
column genuinely exists and the constraint genuinely lifted, on the database
the migration set actually produces.
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
    reason="renewals schema proof requires HARNESS_PG + psql",
)


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


@pytest.fixture()
def seeded_db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"renwl_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={dbname}"
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def test_service_type_column_exists(seeded_db):
    r = _psql(seeded_db,
              "SELECT data_type FROM information_schema.columns "
              "WHERE table_schema='public' AND table_name='renewals' "
              "AND column_name='service_type';", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "text", (
        "renewals.service_type does not exist — every renewal still reads "
        "back with a blank service type on reload"
    )


def test_renewal_date_is_nullable(seeded_db):
    r = _psql(seeded_db,
              "SELECT is_nullable FROM information_schema.columns "
              "WHERE table_schema='public' AND table_name='renewals' "
              "AND column_name='renewal_date';", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "YES", (
        "renewals.renewal_date is still NOT NULL — a blank Renewal Date can "
        "only be saved by fabricating one"
    )


def test_a_renewal_with_no_service_type_or_date_can_be_inserted(seeded_db):
    """The end-to-end proof: a row exactly as a caller who filled in neither
    optional field would produce."""
    seed = _psql(seeded_db, """
        INSERT INTO firms (id, name, email) VALUES
          ('11111111-1111-1111-1111-111111111111', 'F', 'f@t.in');
        INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
          ('22222222-2222-2222-2222-222222222222',
           '11111111-1111-1111-1111-111111111111', 'C', 'Proprietorship');
    """)
    assert seed.returncode == 0, f"fixture seed failed: {seed.stderr}"

    r = _psql(seeded_db, """
        INSERT INTO renewals (firm_id, client_id, financial_year)
        VALUES ('11111111-1111-1111-1111-111111111111',
                '22222222-2222-2222-2222-222222222222', '2026-27');
    """)
    assert r.returncode == 0, f"insert with no service_type/renewal_date failed: {r.stderr}"

    row = _psql(seeded_db,
                "SELECT coalesce(service_type, '<null>'), "
                "coalesce(renewal_date::text, '<null>') FROM renewals;",
                tuples=True)
    service_type, renewal_date = row.stdout.strip().split("|")
    assert service_type == "<null>"
    assert renewal_date == "<null>"
