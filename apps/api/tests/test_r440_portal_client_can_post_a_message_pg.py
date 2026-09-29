"""
R440 — proves migration 440's fix on real PostgreSQL: a portal client may
post to, and read, their own thread; nobody else's identity can touch it.

WHAT THIS REPRODUCES
    Live browser testing found every send from the client portal's Messages
    tab failing with "The server is not permitted to write this table." —
    SQLSTATE 42501 — while reads returned 200 with an empty list. That
    symptom is consistent with either a missing table-level GRANT or an RLS
    policy's WITH CHECK failing (both raise 42501; a SELECT an RLS policy
    blocks returns zero rows, not an error). This file proves which one it
    actually was, on a database built from every migration in this tree:
    `authenticated` already holds the full grant set 048/094/194 declare, and
    the INSERT was refused by `portal_messages_assignment_scope`
    (migration 084's declared policy, restored by 294's drift sweep) — a
    RESTRICTIVE policy gated on `can_access_client()`, which is TRUE only for
    a Partner or an assigned staff member and collapses to NULL (deny) for a
    portal client, who has no `users` row at all. Migration 440 is the fix,
    in the shape migration 262 already established for the same defect on
    payroll_employees/payroll_runs.

WHAT IS PROVEN HERE, AND WHY EACH CASE MATTERS
    * A portal client (via client_portal_users, the live multi-contact path)
      can now SELECT and INSERT into their own thread — this is the bug.
    * A DIFFERENT portal client sees none of the first client's messages and
      cannot insert into their thread — cross-tenant isolation is unchanged.
    * An UNASSIGNED staff member (no user_client_assignments row, not a
      Partner) still sees nothing — 294's own reason for restoring this
      policy (a non-Partner reading a client they are not assigned to) is
      still honoured; the fix widens the policy for a portal principal, not
      for staff generally.
    * An ASSIGNED staff member can still read AND reply — the staff path this
      policy exists for is untouched.
    * UPDATE and DELETE are NOT widened for a portal client — nothing in this
      codebase ever updates or deletes a portal_messages row from the portal
      side, and 262's own reasoning is that a write nobody uses should not be
      opened ahead of the feature that needs it.

Simulates an authenticated PostgREST session the same way
test_r246_users_column_grant_pg.py / test_r3_1b_capital_gains_rls_pg.py do:
`SET request.jwt.claims` + `SET ROLE authenticated` in one psql session.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI
job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="portal-messages RLS proof requires HARNESS_PG + psql",
)

FIRM = "f0000000-0000-0000-0000-0000000000f1"
CLIENT_1 = "c0000000-0000-0000-0000-0000000000c1"
CLIENT_2 = "c0000000-0000-0000-0000-0000000000c2"
PORTAL_AUTH_1 = "a0000000-0000-0000-0000-00000000a001"   # portal contact of CLIENT_1
PORTAL_AUTH_2 = "a0000000-0000-0000-0000-00000000a002"   # portal contact of CLIENT_2
UNASSIGNED_STAFF_AUTH = "a0000000-0000-0000-0000-00000000a003"
ASSIGNED_STAFF_AUTH = "a0000000-0000-0000-0000-00000000a004"
UNASSIGNED_STAFF_ID = "b0000000-0000-0000-0000-00000000b003"
ASSIGNED_STAFF_ID = "b0000000-0000-0000-0000-00000000b004"

_INSERT_C1_FROM_CLIENT = (
    f"INSERT INTO portal_messages (firm_id, client_id, sender_type, sender_name, body) "
    f"VALUES ('{FIRM}', '{CLIENT_1}', 'client', 'Client One', 'hello');"
)


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    """Runs as the admin role (no RLS in the way) — used for setup/sanity."""
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
        capture_output=True, text=True,
    )


def _count(dsn: str, sql: str) -> int:
    r = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip() or "0")


def _as(dsn: str, auth_uid: str, sql: str) -> subprocess.CompletedProcess:
    """Simulates an authenticated PostgREST session — same technique as
    test_r246_users_column_grant_pg.py / test_r3_1b_capital_gains_rls_pg.py.
    Runs with -q -c (no -tA): used where only the return code / stderr matters."""
    return _psql(
        dsn,
        f"SET request.jwt.claims = '{{\"sub\": \"{auth_uid}\"}}'; SET ROLE authenticated; {sql}",
    )


def _as_count(dsn: str, auth_uid: str, sql: str) -> int:
    """Same session simulation as `_as`, but returns a raw scalar (-tA) for a
    result-bearing SELECT. Used wherever a test checks what the RLS-scoped
    session actually sees, not just whether the statement was allowed."""
    r = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
         f"SET request.jwt.claims = '{{\"sub\": \"{auth_uid}\"}}'; SET ROLE authenticated; {sql}"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip().splitlines()[-1] or "0")


@pytest.fixture()
def migrated_db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"r440_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(
            dsn,
            f"""
            INSERT INTO auth.users (id, email) VALUES
              ('{PORTAL_AUTH_1}', 'client1@t.in'),
              ('{PORTAL_AUTH_2}', 'client2@t.in'),
              ('{UNASSIGNED_STAFF_AUTH}', 'staff1@t.in'),
              ('{ASSIGNED_STAFF_AUTH}', 'staff2@t.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan) VALUES
              ('{CLIENT_1}', '{FIRM}', 'C1', 'Private Limited', 'AAACA1234A'),
              ('{CLIENT_2}', '{FIRM}', 'C2', 'Private Limited', 'AAACB1234A');
            INSERT INTO client_portal_users (firm_id, client_id, email, auth_user_id, status) VALUES
              ('{FIRM}', '{CLIENT_1}', 'client1@t.in', '{PORTAL_AUTH_1}', 'active'),
              ('{FIRM}', '{CLIENT_2}', 'client2@t.in', '{PORTAL_AUTH_2}', 'active');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES
              ('{UNASSIGNED_STAFF_ID}', '{FIRM}', '{UNASSIGNED_STAFF_AUTH}', 'staff1@t.in', 'Unassigned', 'Executive', true),
              ('{ASSIGNED_STAFF_ID}', '{FIRM}', '{ASSIGNED_STAFF_AUTH}', 'staff2@t.in', 'Assigned', 'Executive', true);
            INSERT INTO user_client_assignments (user_id, client_id, firm_id)
              VALUES ('{ASSIGNED_STAFF_ID}', '{CLIENT_1}', '{FIRM}');
            """,
        )
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def test_a_portal_client_can_read_their_empty_thread(migrated_db):
    r = _as(migrated_db, PORTAL_AUTH_1, f"SELECT count(*) FROM portal_messages WHERE client_id='{CLIENT_1}';")
    assert r.returncode == 0, r.stderr


def test_a_portal_client_can_post_to_their_own_thread(migrated_db):
    """This is the bug. Before migration 440 this failed with:
    'new row violates row-level security policy "portal_messages_assignment_scope"'."""
    r = _as(migrated_db, PORTAL_AUTH_1, _INSERT_C1_FROM_CLIENT)
    assert r.returncode == 0, r.stderr
    assert _count(migrated_db, f"SELECT count(*) FROM portal_messages WHERE client_id='{CLIENT_1}';") == 1


def test_a_portal_client_then_sees_their_own_message(migrated_db):
    assert _as(migrated_db, PORTAL_AUTH_1, _INSERT_C1_FROM_CLIENT).returncode == 0
    n = _as_count(migrated_db, PORTAL_AUTH_1, f"SELECT count(*) FROM portal_messages WHERE client_id='{CLIENT_1}';")
    assert n == 1


def test_a_different_portal_client_sees_none_of_it(migrated_db):
    assert _psql(migrated_db, _INSERT_C1_FROM_CLIENT).returncode == 0
    # Sanity: the row is really there when read without RLS in the way.
    assert _count(migrated_db, f"SELECT count(*) FROM portal_messages WHERE client_id='{CLIENT_1}';") == 1
    # CLIENT_2's own portal contact must not see CLIENT_1's thread at all.
    n = _as_count(migrated_db, PORTAL_AUTH_2, f"SELECT count(*) FROM portal_messages WHERE client_id='{CLIENT_1}';")
    assert n == 0


def test_a_different_portal_client_cannot_post_into_someone_elses_thread(migrated_db):
    r = _as(
        migrated_db, PORTAL_AUTH_2,
        f"INSERT INTO portal_messages (firm_id, client_id, sender_type, sender_name, body) "
        f"VALUES ('{FIRM}', '{CLIENT_1}', 'client', 'Impersonator', 'should fail');",
    )
    assert r.returncode != 0 and "row-level security" in r.stderr.lower(), (
        f"expected an RLS refusal, got rc={r.returncode} stderr={r.stderr}"
    )


def test_an_unassigned_staff_member_still_sees_nothing(migrated_db):
    """294's own reason for this policy: a non-Partner must not read a client
    they are not assigned to. The portal-client exception must not widen this."""
    assert _psql(migrated_db, _INSERT_C1_FROM_CLIENT).returncode == 0
    n = _as_count(migrated_db, UNASSIGNED_STAFF_AUTH,
                  f"SELECT count(*) FROM portal_messages WHERE client_id='{CLIENT_1}';")
    assert n == 0


def test_an_assigned_staff_member_can_still_read_and_reply(migrated_db):
    assert _psql(migrated_db, _INSERT_C1_FROM_CLIENT).returncode == 0
    r = _as(migrated_db, ASSIGNED_STAFF_AUTH,
            f"INSERT INTO portal_messages (firm_id, client_id, sender_type, sender_name, body) "
            f"VALUES ('{FIRM}', '{CLIENT_1}', 'ca', 'Staff', 'reply');")
    assert r.returncode == 0, r.stderr
    n = _as_count(migrated_db, ASSIGNED_STAFF_AUTH,
                  f"SELECT count(*) FROM portal_messages WHERE client_id='{CLIENT_1}';")
    assert n == 2


def test_the_authenticated_grant_is_the_full_set(migrated_db):
    """048/094 declare SELECT, INSERT, UPDATE; 194 adds DELETE. This is the
    other half of the symptom this migration re-asserts regardless of which
    cause production actually hit."""
    got = subprocess.run(
        ["psql", migrated_db, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
         "SELECT privilege_type FROM information_schema.role_table_grants "
         "WHERE table_schema='public' AND table_name='portal_messages' "
         "AND grantee='authenticated' ORDER BY privilege_type;"],
        capture_output=True, text=True,
    )
    assert got.returncode == 0, got.stderr
    assert got.stdout.strip().splitlines() == ["DELETE", "INSERT", "SELECT", "UPDATE"]


def test_a_portal_client_still_cannot_update_or_delete(migrated_db):
    """Nothing in this codebase updates or deletes a portal_messages row from
    the portal side — the fix widens SELECT and INSERT only, per 262's own
    reasoning about not opening a write nobody uses.

    An UPDATE/DELETE a RESTRICTIVE USING clause excludes is not an ERROR —
    Postgres just finds no matching rows, so this checks the row is
    untouched (and still there) rather than expecting a raised exception,
    which is what an assignment-scope violation on a write actually looks
    like."""
    assert _psql(migrated_db, _INSERT_C1_FROM_CLIENT).returncode == 0

    r = _as(migrated_db, PORTAL_AUTH_1,
            f"UPDATE portal_messages SET body = 'edited' WHERE client_id = '{CLIENT_1}';")
    assert r.returncode == 0, r.stderr
    body = subprocess.run(
        ["psql", migrated_db, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
         f"SELECT body FROM portal_messages WHERE client_id='{CLIENT_1}';"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert body == "hello", f"the portal client's UPDATE must not have taken effect, got body={body!r}"

    r = _as(migrated_db, PORTAL_AUTH_1, f"DELETE FROM portal_messages WHERE client_id = '{CLIENT_1}';")
    assert r.returncode == 0, r.stderr
    assert _count(migrated_db, f"SELECT count(*) FROM portal_messages WHERE client_id='{CLIENT_1}';") == 1, (
        "the portal client's DELETE must not have removed the row"
    )
