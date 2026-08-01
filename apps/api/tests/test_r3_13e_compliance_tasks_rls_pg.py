"""
R3.13e — proves migration 170's RLS/grant hardening on compliance_tasks
(System B) on real PostgreSQL.

compliance_tasks is retired as part of the R3.13 compliance data-model
consolidation: compliance_records (System A) is now the canonical
obligation entity, and every real frontend consumer has been migrated onto
it (R3.13c/R3.13d/R3.13e). compliance_tasks itself was never written to
directly from the browser (unlike R3.3's sales_invoices/fixed_assets) — its
only backend reader, routers/compliance.py, has zero live frontend callers
— so this hardening is precautionary hygiene (closing the direct-write
surface before the table is eventually dropped) rather than a fix for an
active exploit, but follows the exact same pattern as every other
authenticated-write-revocation in this project.

Proves, against a real Postgres 16 instance with every migration applied:
an authenticated firm-staff session can still SELECT its own firm's rows,
but INSERT/UPDATE/DELETE are all rejected with "permission denied" — and
the service_role-backed backend path is unaffected.

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
    reason="compliance_tasks RLS proof requires HARNESS_PG + psql",
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
    dbname = f"r313e_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        # Schema comes from the session-scoped template (conftest.pg_template),
        # applied once instead of once per test. `failed` is that run's report.
        failed = pg_template.failed
        assert "001_initial_schema.sql" not in failed
        assert "170_harden_compliance_tasks_rls.sql" not in failed
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


@pytest.fixture()
def seeded(migrated_db):
    # compliance_tasks predates migration 084 (assignment-scoped RLS), so it
    # ALSO carries an "AS RESTRICTIVE" can_access_client() policy requiring
    # Partner (firm-wide) or an explicit assignment row — same subtlety
    # documented in test_r3_1b_capital_gains_rls_pg.py. Using role='Partner'
    # keeps this test focused on this migration's actual fix.
    dsn = migrated_db
    firm1 = str(uuid.uuid4())
    client1 = str(uuid.uuid4())
    staff_auth_id = str(uuid.uuid4())
    task = str(uuid.uuid4())
    seed = _psql(dsn, f"""
        INSERT INTO auth.users (id, email) VALUES ('{staff_auth_id}', 'staff1@test.in');
        INSERT INTO firms (id, name, email) VALUES ('{firm1}','R3.13e Firm','r313e@test.in');
        INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
          ('{client1}','{firm1}','R3.13e Client','Private Limited');
        INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES
          (gen_random_uuid(), '{firm1}', '{staff_auth_id}', 'Staff One', 'staff1@test.in', 'Partner');
        INSERT INTO compliance_tasks (id, firm_id, client_id, compliance_type,
          period_start, period_end, due_date, status)
          VALUES ('{task}','{firm1}','{client1}','GSTR1','2026-05-01','2026-05-31','2026-06-11','pending');
    """)
    assert seed.returncode == 0, seed.stderr
    return {"dsn": dsn, "firm1": firm1, "client1": client1,
            "staff_auth_id": staff_auth_id, "task": task}


def _as_authenticated(auth_user_id: str) -> str:
    return (
        f"SET request.jwt.claims = '{{\"sub\": \"{auth_user_id}\"}}'; "
        f"SET ROLE authenticated; "
    )


def test_own_firm_staff_can_still_select(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"SELECT compliance_type FROM compliance_tasks WHERE id = '{seeded['task']}';",
              tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "GSTR1"


def test_authenticated_insert_is_denied(seeded):
    dsn = seeded["dsn"]
    new_id = str(uuid.uuid4())
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"INSERT INTO compliance_tasks (id, firm_id, client_id, compliance_type, "
              f"period_start, period_end, due_date, status) "
              f"VALUES ('{new_id}','{seeded['firm1']}','{seeded['client1']}','GSTR3B',"
              f"'2026-05-01','2026-05-31','2026-06-20','pending');")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_authenticated_update_is_denied(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"UPDATE compliance_tasks SET status = 'filed' WHERE id = '{seeded['task']}';")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_authenticated_delete_is_denied(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"DELETE FROM compliance_tasks WHERE id = '{seeded['task']}';")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_service_role_can_still_do_everything(seeded):
    dsn = seeded["dsn"]
    new_id = str(uuid.uuid4())
    r = _psql(dsn,
              f"SET ROLE service_role; "
              f"INSERT INTO compliance_tasks (id, firm_id, client_id, compliance_type, "
              f"period_start, period_end, due_date, status) "
              f"VALUES ('{new_id}','{seeded['firm1']}','{seeded['client1']}','GSTR9',"
              f"'2025-04-01','2026-03-31','2026-12-31','pending'); "
              f"UPDATE compliance_tasks SET status = 'filed' WHERE id = '{new_id}'; "
              f"DELETE FROM compliance_tasks WHERE id = '{new_id}';")
    assert r.returncode == 0, r.stderr
