"""
R3.0 — proves migration 163's client_portal_users RLS/grant hardening on real
PostgreSQL.

Migration 109's client_portal_users_own_firm policy was FOR ALL, scoped only
by firm_id — combined with a table-level GRANT INSERT/UPDATE/DELETE TO
authenticated, ANY authenticated firm staff member could directly mutate any
client_portal_users row for their own firm from the browser, bypassing
services/portal_access_service.py's invite_contact() (its token/TTL/audit
trail) entirely. This file proves, against a real Postgres 16 instance with
every migration applied: an authenticated firm-staff session can still SELECT
its own firm's contacts, but INSERT/UPDATE/DELETE are all rejected with
"permission denied" — and that a different firm's row is invisible to SELECT
too (the pre-existing, unchanged firm_id scoping).

Simulates an authenticated PostgREST session the same way
_supabase_compat_bootstrap.sql's auth.uid()/auth.jwt() shims expect:
`SET request.jwt.claims = '{"sub": "<auth_user_id>"}'` + `SET ROLE
authenticated` in one psql session, matching how a real Supabase connection
pooler sets up an authenticated request.

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
    reason="client_portal_users RLS proof requires HARNESS_PG + psql",
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
    dbname = f"r30_{uuid.uuid4().hex[:12]}"
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
        assert "109_portal_multi_contact.sql" not in failed
        assert "163_harden_client_portal_users_rls.sql" not in failed
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


@pytest.fixture()
def seeded(migrated_db):
    """Seeds firm F1 (with an authenticated staff user), firm F2, and one
    client_portal_users row owned by F1. Returns a dict of the ids."""
    dsn = migrated_db
    firm1 = str(uuid.uuid4())
    firm2 = str(uuid.uuid4())
    client1 = str(uuid.uuid4())
    staff_auth_id = str(uuid.uuid4())
    contact = str(uuid.uuid4())
    seed = _psql(dsn, f"""
        INSERT INTO auth.users (id, email) VALUES ('{staff_auth_id}', 'staff1@test.in');
        INSERT INTO firms (id, name, email) VALUES
          ('{firm1}','R3.0 Firm 1','r30-f1@test.in'),
          ('{firm2}','R3.0 Firm 2','r30-f2@test.in');
        INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
          ('{client1}','{firm1}','R3.0 Client','Private Limited');
        INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES
          (gen_random_uuid(), '{firm1}', '{staff_auth_id}', 'Staff One', 'staff1@test.in', 'Manager');
        INSERT INTO client_portal_users
          (id, firm_id, client_id, email, name, status, invite_token, invite_expires_at)
          VALUES ('{contact}','{firm1}','{client1}','contact@client.in','Contact One',
                  'invited','tok-abc123', now() + interval '7 days');
    """)
    assert seed.returncode == 0, seed.stderr
    return {
        "dsn": dsn, "firm1": firm1, "firm2": firm2,
        "client1": client1, "staff_auth_id": staff_auth_id, "contact": contact,
    }


def _as_authenticated(auth_user_id: str) -> str:
    """SQL prelude that simulates a PostgREST request from this auth_user_id,
    matching _supabase_compat_bootstrap.sql's auth.jwt()/auth.uid() shims."""
    return (
        f"SET request.jwt.claims = '{{\"sub\": \"{auth_user_id}\"}}'; "
        f"SET ROLE authenticated; "
    )


def test_own_firm_staff_can_still_select_contacts(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"SELECT email FROM client_portal_users WHERE id = '{seeded['contact']}';",
              tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "contact@client.in"


def test_cross_firm_staff_cannot_select_contact(seeded):
    """A different firm's staff member (no users row at all here — simulates
    an authenticated identity with no matching firm) sees nothing; RLS still
    filters by firm_id even though this migration only narrowed the verb."""
    dsn = seeded["dsn"]
    stranger_auth_id = str(uuid.uuid4())
    r = _psql(dsn, _as_authenticated(stranger_auth_id) +
              f"SELECT count(*) FROM client_portal_users WHERE id = '{seeded['contact']}';",
              tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "0"


def test_authenticated_insert_is_denied(seeded):
    """The core R3.0 fix: a staff member can no longer self-activate an
    arbitrary contact by inserting a row directly."""
    dsn = seeded["dsn"]
    new_id = str(uuid.uuid4())
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"INSERT INTO client_portal_users (id, firm_id, client_id, email, status) "
              f"VALUES ('{new_id}','{seeded['firm1']}','{seeded['client1']}',"
              f"'attacker@evil.in','active');")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_authenticated_update_is_denied(seeded):
    """A staff member can no longer self-activate an existing invited
    contact, or read/rotate its invite_token, by updating it directly."""
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"UPDATE client_portal_users SET status = 'active' "
              f"WHERE id = '{seeded['contact']}';")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_authenticated_delete_is_denied(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"DELETE FROM client_portal_users WHERE id = '{seeded['contact']}';")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_service_role_can_still_do_everything(seeded):
    """The backend's actual mutation path (get_service_supabase(), the
    service_role Postgres role) must be completely unaffected — it bypasses
    RLS and was never subject to the authenticated grants this migration
    revokes."""
    dsn = seeded["dsn"]
    new_id = str(uuid.uuid4())
    r = _psql(dsn,
              f"SET ROLE service_role; "
              f"INSERT INTO client_portal_users (id, firm_id, client_id, email, status) "
              f"VALUES ('{new_id}','{seeded['firm1']}','{seeded['client1']}',"
              f"'invited-by-backend@client.in','invited'); "
              f"UPDATE client_portal_users SET status = 'active' WHERE id = '{new_id}'; "
              f"DELETE FROM client_portal_users WHERE id = '{new_id}';")
    assert r.returncode == 0, r.stderr
