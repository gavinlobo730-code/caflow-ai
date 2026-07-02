"""
Real-Postgres migration-apply ratchet.

Purpose
-------
Apply the ENTIRE migration set to a throwaway PostgreSQL database (with the
Supabase-compat bootstrap) and assert that the set of migrations that fail to
apply cleanly equals a DOCUMENTED baseline. This is the guard that would have
caught the invalid-SQL migrations R0.1 fixed (TEXT(n), `ON CONFLICT DO NOTHING
WHERE`) and that keeps the known migration-ordering/collision drift (audit
F20 / roadmap R2.6) from silently growing.

Two ratchet directions, both failing:
  * a migration NOT in the baseline fails       -> new drift/broken SQL introduced
  * a migration IN the baseline now applies      -> R2.6 progress; remove it here

Runs only when a Postgres is available (env HARNESS_PG set to a keyword DSN
without a dbname, e.g. "host=/var/run/postgresql port=5432 user=postgres", and
`psql` on PATH). Skips otherwise — exactly like the other DB-backed tests, so
the default mock-mode CI job is unaffected. The dedicated `migrations` CI job
sets HARNESS_PG against its postgres service.

The baseline below is the drift backlog. Each entry is a real defect scheduled
under R2.6 (migration hygiene: resolve duplicate numbers, fix
create-before-referenced ordering, and the workflow_steps / client_profiles
IF-NOT-EXISTS collisions where migration 002/059 pre-create a legacy-shaped
table so a later CREATE TABLE IF NOT EXISTS no-ops and its new columns/indexes
never materialize). Shrink this set as R2.6 lands; do not grow it.
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

# ── Drift backlog (R2.6). Migrations that do not cleanly re-apply to a fresh DB.
# Verified locally against PostgreSQL 16. Each is a real ordering/collision bug.
EXPECTED_MIGRATION_FAILURES: set[str] = {
    "008_linter_fixes.sql",              # references relation "transactions" before it exists
    "045_assignment_rules.sql",          # FK -> task_recurring_configs (created later, in 063); dup 045 number
    "053_hardening.sql",                 # re-creates policy firm_client_isolation that already exists
    "054_v13_payroll_assets_banking.sql",# ALTER references chart_of_accounts.is_system before it is added
    "055_v131_hardening.sql",            # references bank_account_id before it is added
    "068_workflow_engine.sql",           # workflow_steps CREATE IF NOT EXISTS no-ops (002 pre-created it) -> template_id missing
    "070_ai_memory.sql",                 # client_profiles CREATE IF NOT EXISTS no-ops (059) -> is_current missing
    "071_rls_policies.sql",              # references workflow_instances (never created due to 068 failure)
    "095_grant_reconciliation.sql",      # references ai_memory_triggers before it exists; dup 095 number
    "113_work_page_performance_indexes.sql",  # index on tasks.assignee_id before column is added
    "144_security_search_path_and_rls.sql",   # references function prevent_snapshot_mutation() not yet defined
}

_ADMIN_DSN_ENV = "HARNESS_PG"  # keyword DSN WITHOUT dbname


def _harness_available() -> tuple[bool, str]:
    if not os.environ.get(_ADMIN_DSN_ENV):
        return False, f"{_ADMIN_DSN_ENV} not set"
    if shutil.which("psql") is None:
        return False, "psql not on PATH"
    if not RUNNER.exists():
        return False, "runner missing"
    return True, ""


_ok, _why = _harness_available()
pytestmark = pytest.mark.skipif(not _ok, reason=f"migration-apply harness unavailable: {_why}")


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
        capture_output=True, text=True,
    )


def _run_migrations(dsn: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--dsn", dsn,
         "--with-compat", "--only-schema", "--continue-on-error", "--json"],
        capture_output=True, text=True, cwd=str(API_ROOT),
    )
    # stdout is pure JSON (progress goes to stderr).
    return json.loads(proc.stdout)


@pytest.fixture()
def throwaway_db():
    admin = os.environ[_ADMIN_DSN_ENV].strip()
    dbname = f"harness_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    r = _psql(admin_dsn, f'CREATE DATABASE "{dbname}";')
    if r.returncode != 0:
        pytest.skip(f"could not create throwaway db: {r.stderr.strip()}")
    try:
        yield f"{admin} dbname={dbname}"
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def test_migration_failures_match_baseline(throwaway_db):
    report = _run_migrations(throwaway_db)
    failed = {f["file"] for f in report["failed"]}

    newly_broken = failed - EXPECTED_MIGRATION_FAILURES
    now_fixed = EXPECTED_MIGRATION_FAILURES - failed

    assert not newly_broken, (
        "NEW migrations fail to apply cleanly (invalid SQL or new ordering drift). "
        "Fix the migration; do not add to EXPECTED_MIGRATION_FAILURES:\n"
        + "\n".join(
            f"  {f['file']}: {f['error']}"
            for f in report["failed"] if f["file"] in newly_broken
        )
    )
    assert not now_fixed, (
        "These baselined migrations now apply cleanly (R2.6 progress) — REMOVE "
        f"them from EXPECTED_MIGRATION_FAILURES: {sorted(now_fixed)}"
    )


def test_duplicate_migration_numbers_are_tracked(throwaway_db):
    """Duplicate numeric prefixes are a known hygiene defect (R2.6). Assert the
    runner still detects them so the fix (renumbering) is visible when it lands."""
    report = _run_migrations(throwaway_db)
    dups = report["duplicate_numbers"]
    assert dups, "expected duplicate migration numbers to be detected (045/046/094-097)"
    # The known duplicate-numbered set at audit time.
    assert {int(k) for k in dups} >= {45, 46, 94, 95, 96, 97}
