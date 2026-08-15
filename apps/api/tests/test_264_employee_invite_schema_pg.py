"""
Migration 264 — the invite columns, checked against real PostgreSQL.

The service tests (test_employee_portal_provisioning.py) prove the lifecycle
against a fake DB. They cannot prove the things only a real database has:

  * that the unique partial index actually stops two employees sharing one
    invite token — the property that makes a token identify ONE person
  * that RLS from migration 262 still behaves once these columns exist, and in
    particular that an INVITED-but-not-yet-activated employee can still read
    nothing (portal_enabled is false until they accept)
  * that the migration is re-runnable, per the rule migration 262 set

WHY THE INDEX MATTERS MORE THAN IT LOOKS
    accept_employee_invite() looks an invite up by token hash and takes the
    first row. If two rows could carry the same hash, "the first row" would be
    arbitrary and an invite could bind the wrong employee. The uniqueness is
    what makes that lookup meaningful, so it is asserted here rather than
    assumed from the DDL.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATION = API_ROOT / "migrations" / "264_employee_portal_invites.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="migration 264 proof requires HARNESS_PG + psql")

FIRM = "aaaaaaaa-0000-0000-0000-00000000ee01"
CLIENT = "bbbbbbbb-0000-0000-0000-00000000ee01"
EMP_A = "cccccccc-0000-0000-0000-00000000ee0a"
EMP_B = "cccccccc-0000-0000-0000-00000000ee0b"
AUTH_A = "22222222-0000-0000-0000-00000000ee0a"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def seeded(pg_template):
    admin = _ADMIN.strip()
    dbname = f"m264_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        assert "264_employee_portal_invites.sql" not in pg_template.failed
        r = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{AUTH_A}','asha@acme.test');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M264','m264@test.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
              VALUES ('{CLIENT}','{FIRM}','C','Private Limited');
            INSERT INTO payroll_employees (id, firm_id, client_id, name, portal_enabled)
              VALUES ('{EMP_A}','{FIRM}','{CLIENT}','Asha',false),
                     ('{EMP_B}','{FIRM}','{CLIENT}','Bala',false);
        """)
        assert r.returncode == 0, r.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def test_the_invite_columns_exist_with_the_right_nullability(seeded):
    r = _psql(seeded,
              "SELECT column_name||':'||is_nullable FROM information_schema.columns "
              "WHERE table_schema='public' AND table_name='payroll_employees' "
              "AND column_name IN ('email','portal_invite_token_hash',"
              "'portal_invite_expires_at','portal_invited_at','portal_invited_by',"
              "'portal_activated_at') ORDER BY 1;", tuples=True)
    assert r.returncode == 0, r.stderr
    got = set(r.stdout.split())
    assert got == {
        "email:YES", "portal_activated_at:YES", "portal_invite_expires_at:YES",
        "portal_invite_token_hash:YES", "portal_invited_at:YES", "portal_invited_by:YES",
    }, got


def test_the_raw_token_column_was_not_created(seeded):
    """The first draft stored the live token. If a `portal_invite_token` column
    ever appears, something has reverted to storing the secret."""
    r = _psql(seeded, "SELECT count(*) FROM information_schema.columns "
                      "WHERE table_schema='public' AND table_name='payroll_employees' "
                      "AND column_name='portal_invite_token';", tuples=True)
    assert r.stdout.strip() == "0"


def test_two_employees_cannot_share_an_invite_token(seeded):
    """What makes 'look the invite up by hash and take the first row' sound."""
    h = hashlib.sha256(b"the-same-token").hexdigest()
    ok = _psql(seeded, f"UPDATE payroll_employees SET portal_invite_token_hash='{h}' "
                       f"WHERE id='{EMP_A}';")
    assert ok.returncode == 0, ok.stderr

    clash = _psql(seeded, f"UPDATE payroll_employees SET portal_invite_token_hash='{h}' "
                          f"WHERE id='{EMP_B}';")
    assert clash.returncode != 0
    assert "unique" in clash.stderr.lower() or "duplicate" in clash.stderr.lower()


def test_many_employees_can_have_no_pending_invite(seeded):
    """The index is partial for this reason — NULL must not collide."""
    r = _psql(seeded, "SELECT count(*) FROM payroll_employees "
                      "WHERE portal_invite_token_hash IS NULL;", tuples=True)
    assert r.stdout.strip() == "2"


def test_an_invited_employee_still_sees_nothing_until_they_accept(seeded):
    """The window this migration opens: between invite and acceptance the row
    carries a token but portal_enabled is still false, so migration 262's
    my_employee_ids() must not match. Otherwise merely being invited would leak
    payroll before anyone proved they own the address."""
    h = hashlib.sha256(b"pending").hexdigest()
    r = _psql(seeded, f"UPDATE payroll_employees SET portal_invite_token_hash='{h}', "
                      f"auth_user_id='{AUTH_A}', portal_enabled=false WHERE id='{EMP_A}';")
    assert r.returncode == 0, r.stderr

    got = _psql(seeded,
                f"SET request.jwt.claims = '{{\"sub\": \"{AUTH_A}\"}}'; SET ROLE authenticated; "
                f"SELECT count(*) FROM payroll_employees;", tuples=True)
    assert got.returncode == 0, got.stderr
    assert got.stdout.strip() == "0", "an un-accepted invite already grants read access"


def test_acceptance_is_what_opens_access(seeded):
    """The same row, once portal_enabled flips — proves the test above fails for
    the right reason rather than because the fixture is simply invisible."""
    r = _psql(seeded, f"UPDATE payroll_employees SET auth_user_id='{AUTH_A}', "
                      f"portal_enabled=true WHERE id='{EMP_A}';")
    assert r.returncode == 0, r.stderr

    got = _psql(seeded,
                f"SET request.jwt.claims = '{{\"sub\": \"{AUTH_A}\"}}'; SET ROLE authenticated; "
                f"SELECT name FROM payroll_employees;", tuples=True)
    assert got.stdout.strip() == "Asha"


def test_the_migration_is_re_runnable(seeded):
    """Migration 262 set this rule; 264 follows it."""
    again = subprocess.run(["psql", seeded, "-v", "ON_ERROR_STOP=1", "-X", "-q",
                            "-f", str(MIGRATION)], capture_output=True, text=True)
    assert again.returncode == 0, again.stderr
