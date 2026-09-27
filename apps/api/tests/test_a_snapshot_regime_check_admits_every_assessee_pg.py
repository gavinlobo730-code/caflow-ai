"""Migration 427 — the regime CHECK admits every assessee, on real Postgres.

The mock store has no CHECK, which is how every company, firm and LLP snapshot
could fail in production while the mock suite saved them happily. This runs the
INSERT the handler runs against a database the migrations built.

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
CLIENT = "22222222-2222-2222-2222-222222222222"
USER = "66666666-6666-6666-6666-666666666666"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"snapregime_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO users (id, firm_id, full_name, email, role)
            VALUES ('{USER}', '{FIRM}', 'U', 'u@t.in', 'Partner');
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
            VALUES ('{CLIENT}', '{FIRM}', 'C1', 'Private Limited', 'AAACA1234A');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _snapshot(regime: str, version: int) -> str:
    return ("INSERT INTO tax_computation_snapshots "
            "(firm_id, client_id, financial_year, assessment_year, version, regime, "
            "status, created_by) VALUES "
            f"('{FIRM}', '{CLIENT}', '2025-26', '2026-27', {version}, '{regime}', "
            f"'draft', '{USER}')")


@pytest.mark.parametrize("version, regime", list(enumerate(
    ["new", "old", "normal", "115BAA", "115BAB", "firm", "llp"], start=1)))
def test_every_regime_the_engine_answers_is_admitted(db, version, regime):
    got = _psql(db, _snapshot(regime, version))
    assert got.returncode == 0, got.stderr


def test_a_regime_nobody_is_taxed_under_is_still_refused(db):
    """Widened, not removed: 'company' is an assessee KIND, not a regime."""
    got = _psql(db, _snapshot("company", 1))
    assert got.returncode != 0
    assert "tax_computation_snapshots_regime_check" in got.stderr
