"""
R3.5e (indexes half) — proves migration 173 actually creates the 4 missing
composite indexes on real PostgreSQL, with the exact column order and partial
predicates that match the hot-path filter chains found in routers/health.py,
routers/analytics.py, and domain/compliance_record_service.py (see migration
173's header comment for the file:line grep that identified each gap).

A clean migration-runner exit code only proves the SQL didn't error — it does
not prove the indexes exist with the intended shape (e.g. a typo'd column
name or wrong column order would still apply cleanly). This asserts against
pg_indexes directly.

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
    reason="migration 173 index proof requires HARNESS_PG + psql",
)


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


@pytest.fixture()
def migrated_db():
    admin = _ADMIN.strip()
    dbname = f"r35e_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        proc = subprocess.run(
            [sys.executable, str(RUNNER), "--dsn", dsn,
             "--with-compat", "--only-schema", "--continue-on-error", "--json"],
            capture_output=True, text=True, cwd=str(API_ROOT),
        )
        report = json.loads(proc.stdout)
        failed = {f["file"] for f in report["failed"]}
        assert "173_r35e_missing_indexes.sql" not in failed
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _indexdef(dsn: str, indexname: str) -> str:
    r = _psql(dsn, f"SELECT indexdef FROM pg_indexes WHERE indexname = '{indexname}';", tuples=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_government_notices_composite_index_exists(migrated_db):
    d = _indexdef(migrated_db, "idx_government_notices_firm_client_status")
    assert d == (
        "CREATE INDEX idx_government_notices_firm_client_status "
        "ON public.government_notices USING btree (firm_id, client_id, status)"
    )


def test_document_requests_composite_index_exists(migrated_db):
    d = _indexdef(migrated_db, "idx_document_requests_firm_client_status_created")
    assert d == (
        "CREATE INDEX idx_document_requests_firm_client_status_created "
        "ON public.document_requests USING btree (firm_id, client_id, status, created_at)"
    )


def test_tasks_composite_index_exists_with_soft_delete_predicate(migrated_db):
    d = _indexdef(migrated_db, "idx_tasks_firm_status_updated")
    assert d == (
        "CREATE INDEX idx_tasks_firm_status_updated "
        "ON public.tasks USING btree (firm_id, status, updated_at) "
        "WHERE (deleted_at IS NULL)"
    )


def test_compliance_records_composite_index_exists_with_soft_delete_predicate(migrated_db):
    d = _indexdef(migrated_db, "idx_compliance_records_firm_client_due")
    assert d == (
        "CREATE INDEX idx_compliance_records_firm_client_due "
        "ON public.compliance_records USING btree (firm_id, client_id, due_date) "
        "WHERE (deleted_at IS NULL)"
    )


def test_migration_is_idempotent_on_rerun(migrated_db):
    """CREATE INDEX IF NOT EXISTS must no-op cleanly on a second apply (matches
    every other migration's re-run guarantee enforced by the runner's tracking
    table in normal use, and defends against a future hand-run psql replay)."""
    path = API_ROOT / "migrations" / "173_r35e_missing_indexes.sql"
    r = _psql(migrated_db, path.read_text())
    assert r.returncode == 0, r.stderr
