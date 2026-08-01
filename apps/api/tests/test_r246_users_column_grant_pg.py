"""
R246 — proves migration 246's fix on real PostgreSQL: an authenticated user
may rename themselves (full_name) but cannot escalate their own role or
move themselves to another firm.

Migration 153 (secure_invite_flows) deliberately revoked whole-table
UPDATE on users from `authenticated` and granted back only
`UPDATE (full_name)`, specifically because its own RLS policy
("users_own_row_rename", WITH CHECK auth_user_id = auth.uid()) only
constrains WHICH ROW may be touched, never which COLUMNS or VALUES —
without the column-level grant, a user could set their own `role` to
'Partner' or `firm_id` to a different firm and the RLS check would still
pass (it's still "their own row"). Migration 194's grant-gap sweep
restored the whole-table grant, silently reopening exactly that
escalation; migration 246 re-narrows it back to `full_name` only.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode
CI job.
"""
from __future__ import annotations

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
    reason="users column-grant proof requires HARNESS_PG + psql",
)

FIRM = "f0000000-0000-0000-0000-0000000000f1"
OTHER_FIRM = "f0000000-0000-0000-0000-0000000000f2"
AUTH_UID = "a0000000-0000-0000-0000-00000000a001"
USER_ID = "b0000000-0000-0000-0000-00000000b001"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
        capture_output=True, text=True,
    )


def _as_user(dsn: str, sql: str) -> subprocess.CompletedProcess:
    """Simulates an authenticated PostgREST session — same technique as
    test_r3_1b_capital_gains_rls_pg.py / test_r3_3_legacy_invoice_fixed_asset_rls_pg.py."""
    return _psql(
        dsn,
        f"SET request.jwt.claims = '{{\"sub\": \"{AUTH_UID}\"}}'; SET ROLE authenticated; {sql}",
    )


@pytest.fixture()
def migrated_db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"r246_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        # Schema comes from the session-scoped template (conftest.pg_template),
        # applied once instead of once per test.
        seed = _psql(
            dsn,
            f"""
            INSERT INTO auth.users (id, email) VALUES ('{AUTH_UID}', 'u@t.in');
            INSERT INTO firms (id, name, email) VALUES
              ('{FIRM}', 'F1', 'f1@t.in'), ('{OTHER_FIRM}', 'F2', 'f2@t.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES
              ('{USER_ID}', '{FIRM}', '{AUTH_UID}', 'u@t.in', 'Original Name', 'Executive', true);
            """,
        )
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _role(dsn: str) -> str:
    r = _psql(dsn, f"SELECT role FROM users WHERE id = '{USER_ID}';")
    return r.stdout


def test_authenticated_user_can_still_rename_themselves(migrated_db):
    r = _as_user(migrated_db, f"UPDATE users SET full_name = 'New Name' WHERE id = '{USER_ID}';")
    assert r.returncode == 0, r.stderr
    check = _psql(migrated_db, f"SELECT full_name FROM users WHERE id = '{USER_ID}';")
    assert "New Name" in check.stdout


def test_authenticated_user_cannot_escalate_own_role(migrated_db):
    r = _as_user(migrated_db, f"UPDATE users SET role = 'Partner' WHERE id = '{USER_ID}';")
    assert r.returncode != 0 and "permission denied" in r.stderr.lower(), (
        f"expected permission denied, got rc={r.returncode} stderr={r.stderr}"
    )
    assert "Partner" not in _role(migrated_db)


def test_authenticated_user_cannot_move_self_to_another_firm(migrated_db):
    r = _as_user(migrated_db, f"UPDATE users SET firm_id = '{OTHER_FIRM}' WHERE id = '{USER_ID}';")
    assert r.returncode != 0 and "permission denied" in r.stderr.lower(), (
        f"expected permission denied, got rc={r.returncode} stderr={r.stderr}"
    )
    check = _psql(migrated_db, f"SELECT firm_id FROM users WHERE id = '{USER_ID}';")
    assert OTHER_FIRM not in check.stdout


def test_authenticated_user_cannot_reactivate_or_touch_other_columns(migrated_db):
    r = _as_user(migrated_db, f"UPDATE users SET is_active = false WHERE id = '{USER_ID}';")
    assert r.returncode != 0 and "permission denied" in r.stderr.lower()


def test_service_role_can_still_do_everything(migrated_db):
    r = _psql(migrated_db, f"UPDATE users SET role = 'Partner', firm_id = '{OTHER_FIRM}' WHERE id = '{USER_ID}';")
    assert r.returncode == 0, r.stderr
