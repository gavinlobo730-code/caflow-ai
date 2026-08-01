"""
R3.13b — compliance data-model consolidation, gap-close #2 (manual-create
dedup). Migration 108's uq_compliance_records_obligation only protects
auto-generated rows (WHERE obligation_type IS NOT NULL). The manual
POST /api/compliance-records path never sets obligation_type, so it was
fully unprotected against a duplicate (firm, client, compliance_type,
period_start) row — unlike the compliance_calendar table it replaces, which
had a plain UNIQUE(client_id, compliance_type, period_start). Migration 168
adds the mirror-image partial index for that path.

Proves against real Postgres 16 with every migration applied: a second
manual-shaped insert (obligation_type NULL) for the same
(firm, client, compliance_type, period_start) is rejected at the DB layer —
the backstop behind the application-level check in
compliance_record_service.create_record(). Also proves the original
migration-108 auto-generated index still independently rejects its own
duplicate shape, and that the two partial indexes don't interfere with each
other (an auto-generated row and a manual row can coexist for the same
period since they differ on obligation_type IS NULL vs NOT NULL).

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="compliance_records dedup-index proof requires HARNESS_PG + psql",
)


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


@pytest.fixture()
def migrated_db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"r313b_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        # Schema comes from the session-scoped template (conftest.pg_template),
        # applied once instead of once per test. `failed` is that run's report.
        failed = pg_template.failed
        assert "108_compliance_engagement.sql" not in failed
        assert "168_compliance_records_manual_dedup.sql" not in failed
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


@pytest.fixture()
def seeded(migrated_db):
    dsn = migrated_db
    firm1 = str(uuid.uuid4())
    client1 = str(uuid.uuid4())
    seed = _psql(dsn, f"""
        SET ROLE service_role;
        INSERT INTO firms (id, name, email) VALUES ('{firm1}','R3.13b Firm','r313b@test.in');
        INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
          ('{client1}','{firm1}','R3.13b Client','Private Limited');
    """)
    assert seed.returncode == 0, seed.stderr
    return {"dsn": dsn, "firm1": firm1, "client1": client1}


def _insert_manual(dsn, firm, client, period_start, rec_id=None) -> subprocess.CompletedProcess:
    rec_id = rec_id or str(uuid.uuid4())
    return _psql(dsn, f"""
        SET ROLE service_role;
        INSERT INTO compliance_records
          (id, firm_id, client_id, compliance_type, period_label, period_start,
           period_end, status, due_date)
        VALUES
          ('{rec_id}','{firm}','{client}','GST','Jun 2026','{period_start}',
           '{period_start}','Not Started','2026-07-11');
    """)


def _insert_generated(dsn, firm, client, obligation_type, period_start, rec_id=None) -> subprocess.CompletedProcess:
    rec_id = rec_id or str(uuid.uuid4())
    return _psql(dsn, f"""
        SET ROLE service_role;
        INSERT INTO compliance_records
          (id, firm_id, client_id, compliance_type, obligation_type, period_label,
           period_start, period_end, status, due_date)
        VALUES
          ('{rec_id}','{firm}','{client}','GST','{obligation_type}','Jun 2026','{period_start}',
           '{period_start}','Not Started','2026-07-11');
    """)


def test_duplicate_manual_record_rejected_by_db(seeded):
    dsn, firm, client = seeded["dsn"], seeded["firm1"], seeded["client1"]
    r1 = _insert_manual(dsn, firm, client, "2026-06-01")
    assert r1.returncode == 0, r1.stderr
    r2 = _insert_manual(dsn, firm, client, "2026-06-01")
    assert r2.returncode != 0
    assert "duplicate key" in r2.stderr.lower()
    assert "uq_compliance_records_manual" in r2.stderr.lower()


def test_manual_records_for_distinct_periods_both_allowed(seeded):
    dsn, firm, client = seeded["dsn"], seeded["firm1"], seeded["client1"]
    r1 = _insert_manual(dsn, firm, client, "2026-06-01")
    r2 = _insert_manual(dsn, firm, client, "2026-07-01")
    assert r1.returncode == 0 and r2.returncode == 0, (r1.stderr, r2.stderr)


def test_duplicate_generated_record_still_rejected_by_migration_108(seeded):
    """Confirms 168 didn't disturb 108's pre-existing auto-generated guard."""
    dsn, firm, client = seeded["dsn"], seeded["firm1"], seeded["client1"]
    r1 = _insert_generated(dsn, firm, client, "GSTR3B", "2026-06-01")
    assert r1.returncode == 0, r1.stderr
    r2 = _insert_generated(dsn, firm, client, "GSTR3B", "2026-06-01")
    assert r2.returncode != 0
    assert "duplicate key" in r2.stderr.lower()
    assert "uq_compliance_records_obligation" in r2.stderr.lower()


def test_manual_and_generated_rows_coexist_for_the_same_period(seeded):
    """A manual (obligation_type NULL) and an auto-generated (obligation_type
    NOT NULL) row for the same client/period are different index partitions —
    both are allowed to exist simultaneously without conflict."""
    dsn, firm, client = seeded["dsn"], seeded["firm1"], seeded["client1"]
    r1 = _insert_manual(dsn, firm, client, "2026-06-01")
    r2 = _insert_generated(dsn, firm, client, "GSTR3B", "2026-06-01")
    assert r1.returncode == 0, r1.stderr
    assert r2.returncode == 0, r2.stderr
