"""
R3.13a — proves migration 165's advance_tax_payments RLS/grant hardening on
real PostgreSQL.

Migration 035's firm_staff_manage_advance_tax policy was FOR ALL, scoped
only by firm_id — combined with a table-level GRANT INSERT/UPDATE/DELETE TO
authenticated, ANY authenticated firm staff member could directly write an
advance_tax_payments row from the browser with self-reported
paid_amount_paise/due_date/required_percent, bypassing the Section 234C
engine entirely. This file proves, against a real Postgres 16 instance with
every migration applied: an authenticated firm-staff session can still
SELECT its own firm's advance-tax records, but INSERT/UPDATE/DELETE are all
rejected with "permission denied" — and the service_role-backed backend
path (the only real mutation path) is unaffected.

Simulates an authenticated PostgREST session the same way
test_r3_1b_capital_gains_rls_pg.py does: `SET request.jwt.claims` + `SET
ROLE authenticated` in one psql session.

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
    reason="advance_tax_payments RLS proof requires HARNESS_PG + psql",
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
    dbname = f"r313a_{uuid.uuid4().hex[:12]}"
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
        assert "035_complete_missing_pages.sql" not in failed
        assert "165_harden_advance_tax_payments_rls.sql" not in failed
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


@pytest.fixture()
def seeded(migrated_db):
    # advance_tax_payments predates migration 084 (assignment-scoped RLS,
    # Module 9.0/M5), so it ALSO carries an "AS RESTRICTIVE"
    # advance_tax_payments_assignment_scope-style policy requiring
    # can_access_client(client_id): true for Partner (firm-wide), false for
    # any other role without an explicit user_client_assignments row --
    # same subtlety documented in test_r3_1b_capital_gains_rls_pg.py. Using
    # role='Partner' keeps this test focused on R3.13a's actual fix (SELECT
    # allowed, writes denied) rather than re-exercising that separate,
    # already-covered feature.
    dsn = migrated_db
    firm1 = str(uuid.uuid4())
    client1 = str(uuid.uuid4())
    staff_auth_id = str(uuid.uuid4())
    record = str(uuid.uuid4())
    seed = _psql(dsn, f"""
        INSERT INTO auth.users (id, email) VALUES ('{staff_auth_id}', 'staff1@test.in');
        INSERT INTO firms (id, name, email) VALUES ('{firm1}','R3.13a Firm','r313a@test.in');
        INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
          ('{client1}','{firm1}','R3.13a Client','Private Limited');
        INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES
          (gen_random_uuid(), '{firm1}', '{staff_auth_id}', 'Staff One', 'staff1@test.in', 'Partner');
        INSERT INTO advance_tax_payments
          (id, firm_id, client_id, financial_year, installment_number, due_date,
           required_percent, estimated_tax_paise, paid_amount_paise)
          VALUES ('{record}','{firm1}','{client1}','2024-25',1,'2024-06-15',15,100000000,15000000);
    """)
    assert seed.returncode == 0, seed.stderr
    return {"dsn": dsn, "firm1": firm1, "client1": client1,
            "staff_auth_id": staff_auth_id, "record": record}


def _as_authenticated(auth_user_id: str) -> str:
    return (
        f"SET request.jwt.claims = '{{\"sub\": \"{auth_user_id}\"}}'; "
        f"SET ROLE authenticated; "
    )


def test_own_firm_staff_can_still_select(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"SELECT paid_amount_paise FROM advance_tax_payments WHERE id = '{seeded['record']}';",
              tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "15000000"


def test_authenticated_insert_is_denied(seeded):
    dsn = seeded["dsn"]
    new_id = str(uuid.uuid4())
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"INSERT INTO advance_tax_payments (id, firm_id, client_id, financial_year, "
              f"installment_number, due_date, required_percent, estimated_tax_paise, paid_amount_paise) "
              f"VALUES ('{new_id}','{seeded['firm1']}','{seeded['client1']}','2024-25',2,"
              f"'2024-09-15',45,1,999999999);")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_authenticated_update_is_denied(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"UPDATE advance_tax_payments SET paid_amount_paise = 0 WHERE id = '{seeded['record']}';")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_authenticated_delete_is_denied(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"DELETE FROM advance_tax_payments WHERE id = '{seeded['record']}';")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_service_role_can_still_do_everything(seeded):
    dsn = seeded["dsn"]
    new_id = str(uuid.uuid4())
    r = _psql(dsn,
              f"SET ROLE service_role; "
              f"INSERT INTO advance_tax_payments (id, firm_id, client_id, financial_year, "
              f"installment_number, due_date, required_percent, estimated_tax_paise, paid_amount_paise) "
              f"VALUES ('{new_id}','{seeded['firm1']}','{seeded['client1']}','2024-25',2,"
              f"'2024-09-15',45,100000000,45000000); "
              f"UPDATE advance_tax_payments SET paid_amount_paise = 0 WHERE id = '{new_id}'; "
              f"DELETE FROM advance_tax_payments WHERE id = '{new_id}';")
    assert r.returncode == 0, r.stderr
