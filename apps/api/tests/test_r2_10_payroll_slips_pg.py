"""
R2.10 — proves routers/payroll.py::get_run_slips's schema assumption on real
PostgreSQL.

payroll_slips has no firm_id column (migrations 014/093 — it's tenant-scoped
transitively via run_id -> payroll_runs.firm_id). The endpoint previously
filtered `.eq("firm_id", ...)` directly on payroll_slips, which PostgREST
rejects outright against a real database (an unknown-column error) — this
endpoint could never return data in production. The fix queries payroll_runs
for the ownership check and payroll_slips by run_id alone.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI
job.
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
    reason="payroll_slips schema proof requires HARNESS_PG + psql",
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
    dbname = f"r210_{uuid.uuid4().hex[:12]}"
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
        assert "014_complete_missing_tables.sql" not in failed
        assert "093_payroll_assets_banking_modernized.sql" not in failed
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def test_payroll_slips_has_no_firm_id_column(migrated_db):
    """Confirms the root cause: this column has never existed."""
    dsn = migrated_db
    r = _psql(
        dsn,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='payroll_slips' AND table_schema='public' AND column_name='firm_id';",
        tuples=True,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", "payroll_slips must NOT have a firm_id column — confirms the bug's root cause"


def test_old_query_pattern_fails_against_real_schema(migrated_db):
    """The pre-fix query — .eq('run_id', X).eq('firm_id', Y) directly on
    payroll_slips — must fail with an unknown-column error, proving the
    endpoint could never have worked in production before this fix."""
    dsn = migrated_db
    r = _psql(dsn, "SELECT * FROM payroll_slips WHERE run_id = gen_random_uuid() AND firm_id = gen_random_uuid();")
    assert r.returncode != 0
    assert "firm_id" in r.stderr.lower()
    assert "does not exist" in r.stderr.lower() or "column" in r.stderr.lower()


def test_fixed_query_pattern_succeeds_against_real_schema(migrated_db):
    """The fix's query shape: verify run ownership via payroll_runs.firm_id,
    then query payroll_slips by run_id alone — must succeed and return the
    right rows."""
    dsn = migrated_db
    firm = str(uuid.uuid4())
    client = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    employee_id = str(uuid.uuid4())
    seed = _psql(dsn, f"""
        INSERT INTO firms (id, name, email) VALUES ('{firm}','R2.10 Firm','r210@test.in');
        INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
          ('{client}','{firm}','R2.10 Client','Private Limited');
        INSERT INTO payroll_employees (id, firm_id, client_id, name, basic_paise) VALUES
          ('{employee_id}','{firm}','{client}','Test Employee',5000000);
        INSERT INTO payroll_runs (id, firm_id, client_id, month, status) VALUES
          ('{run_id}','{firm}','{client}','2026-06','draft');
        INSERT INTO payroll_slips (run_id, employee_id, gross_paise, net_paise) VALUES
          ('{run_id}','{employee_id}',5000000,4500000);
    """)
    assert seed.returncode == 0, seed.stderr

    ownership = _psql(
        dsn,
        f"SELECT id FROM payroll_runs WHERE id = '{run_id}' AND firm_id = '{firm}';",
        tuples=True,
    )
    assert ownership.returncode == 0, ownership.stderr
    assert ownership.stdout.strip() == run_id

    slips = _psql(
        dsn,
        f"SELECT gross_paise, net_paise FROM payroll_slips WHERE run_id = '{run_id}';",
        tuples=True,
    )
    assert slips.returncode == 0, slips.stderr
    assert slips.stdout.strip() == "5000000|4500000"
