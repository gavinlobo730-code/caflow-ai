"""Migration 497 — the invite secret of a client's portal contact cannot be read by signed-in staff.

THE BUG THIS PINS (ledger POST-B-027, the half migration 484 left)
    `client_portal_users.invite_token` is a live, single-use invite secret (accepting an invite also needs the signed-in
    account's e-mail to match the contact's, which the code calls defence in depth, so the token is the credential and the
    e-mail match a second lock). Migration 484 confined a staff member's SELECT to the clients they can reach, but the
    table-level SELECT grant stayed, so every staff member who can reach a client could read the token of a contact who
    had not yet accepted, with their own sign-in. Nothing in the product reads it that way.

WHAT IS ASSERTED, AS A REAL AUTHENTICATED SESSION
    * no staff role (Partner, assigned Manager, assigned Executive) can read `invite_token`: selecting it, `select *`, and
      naming it in a WHERE (which would be a yes/no oracle for a guessed token) are all permission errors;
    * every other column is still readable, and the row policies still decide WHICH rows (an assigned Manager sees the
      client's contacts, an unassigned Executive sees none);
    * the portal contact still reads their own row, minus the secret;
    * the SET of columns a signed-in user cannot read is exactly {invite_token}, so a column added later is noticed;
    * the service role (what the API uses) still reads the token;
    * the migration is idempotent, and its own rollback puts the hole back (the negative control).

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATIONS = API_ROOT / "migrations"
MIGRATION = MIGRATIONS / "497_the_invite_secret_of_a_client_portal_contact_cannot_be_read_by_signed_in_staff.sql"
ROLLBACK = MIGRATIONS / "497_the_invite_secret_of_a_client_portal_contact_cannot_be_read_by_signed_in_staff_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the invite-secret proofs require HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000497"
CLIENT = "cccccccc-0000-0000-0000-00000000a497"
SECRET = "tok-497-live-invite-secret"
STAFF = {"partner": "Partner", "manager": "Manager", "executive": "Executive", "exec_unassigned": "Executive"}
ASSIGNED = ("manager", "executive")        # the Partner is firm-wide; exec_unassigned is deliberately not assigned
AUTH = {k: f"11111111-1111-1111-1111-{i:012d}" for i, k in enumerate([*STAFF, "portal"], start=1)}
USER = {k: f"bbbbbbbb-1111-1111-1111-{i:012d}" for i, k in enumerate(STAFF, start=1)}


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _as(dsn: str, who: str, sql: str) -> subprocess.CompletedProcess:
    claims = json.dumps({"sub": AUTH[who], "role": "authenticated"})
    return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")


def _as_service(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return _psql(dsn, f"SET ROLE service_role; {sql}")


def _denied(r: subprocess.CompletedProcess) -> bool:
    return r.returncode != 0 and "permission denied" in r.stderr


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"portalsecret_m497_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        auth_rows = ", ".join(f"('{v}', '{k}@m497.test')" for k, v in AUTH.items())
        users = ", ".join(f"('{USER[k]}', '{FIRM}', '{AUTH[k]}', '{k}@m497.test', '{k}', '{role}', true)"
                          for k, role in STAFF.items())
        assigned = ", ".join(f"('{FIRM}', '{USER[k]}', '{CLIENT}')" for k in ASSIGNED)
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES {auth_rows};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M497 Firm','m497@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {users};
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','Client A','Private Limited');
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES {assigned};
            INSERT INTO client_portal_users (firm_id, client_id, email, name, status, invite_token, invite_expires_at)
              VALUES ('{FIRM}', '{CLIENT}', 'pending@m497.test', 'Pending Contact', 'invited', '{SECRET}', now() + interval '7 days');
            INSERT INTO client_portal_users (firm_id, client_id, email, name, status, auth_user_id)
              VALUES ('{FIRM}', '{CLIENT}', 'bound@m497.test', 'Bound Contact', 'active', '{AUTH["portal"]}');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _apply(dsn: str, path: Path) -> None:
    r = _psql(dsn, path.read_text(), tuples=False)
    assert r.returncode == 0, r.stderr


# ── staff cannot read the secret, three ways ─────────────────────────────────────────────────────
@pytest.mark.parametrize("who", ["partner", "manager", "executive"])
def test_staff_cannot_select_the_invite_token(db, who):
    assert _denied(_as(db, who, "SELECT invite_token FROM client_portal_users;"))


@pytest.mark.parametrize("who", ["partner", "manager", "executive"])
def test_select_star_is_a_permission_error_for_staff(db, who):
    """The intended failure: the next reader that forgets the secret is there fails on the day it is written."""
    assert _denied(_as(db, who, "SELECT * FROM client_portal_users;"))


@pytest.mark.parametrize("who", ["partner", "manager", "executive"])
def test_staff_cannot_use_the_token_as_a_yes_no_oracle(db, who):
    """Naming the column in a WHERE also needs the privilege, so a guessed token cannot be tested for."""
    assert _denied(_as(db, who, f"SELECT id FROM client_portal_users WHERE invite_token = '{SECRET}';"))


# ── everything else is still readable, and the rows are still scoped ─────────────────────────────
READABLE = "id, firm_id, client_id, email, name, auth_user_id, status, invited_by, invited_at, activated_at, " \
           "deactivated_at, created_at, updated_at, invite_expires_at"


@pytest.mark.parametrize("who", ["partner", "manager", "executive"])
def test_staff_still_read_every_other_column_of_their_clients_contacts(db, who):
    r = _as(db, who, f"SELECT count(*) FROM (SELECT {READABLE} FROM client_portal_users) s;")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "2"


def test_an_unassigned_executive_still_sees_no_contacts(db):
    r = _as(db, "exec_unassigned", f"SELECT count(*) FROM (SELECT {READABLE} FROM client_portal_users) s;")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "0"


def test_the_portal_contact_reads_their_own_row_but_not_the_secret(db):
    r = _as(db, "portal", f"SELECT email FROM client_portal_users WHERE auth_user_id = '{AUTH['portal']}';")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "bound@m497.test"
    assert _denied(_as(db, "portal", "SELECT invite_token FROM client_portal_users;"))


def test_the_only_column_a_signed_in_user_cannot_read_is_the_secret(db):
    """So a column added later is noticed: it is unreadable until a migration grants it, and this names the set."""
    unreadable = _ok(db, """
        SELECT coalesce(string_agg(column_name, ',' ORDER BY column_name), '')
          FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = 'client_portal_users'
           AND NOT has_column_privilege('authenticated', 'public.client_portal_users', column_name, 'SELECT');""")
    assert unreadable == "invite_token", unreadable


# ── the API's door is unaffected ─────────────────────────────────────────────────────────────────
def test_the_service_role_still_reads_the_token(db):
    r = _as_service(db, f"SELECT count(*) FROM client_portal_users WHERE invite_token = '{SECRET}';")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "1"


# ── the migration itself ─────────────────────────────────────────────────────────────────────────
def test_497_is_idempotent(db):
    _apply(db, MIGRATION)
    _apply(db, MIGRATION)
    assert _denied(_as(db, "manager", "SELECT invite_token FROM client_portal_users;"))


def test_its_own_rollback_puts_the_hole_back(db):
    """The negative control: without it the assertions above would pass on a database that never had a hole."""
    _apply(db, ROLLBACK)
    r = _as(db, "manager", "SELECT invite_token FROM client_portal_users;")
    assert r.returncode == 0 and SECRET in r.stdout, "an assigned Manager reads the live token again"
    _apply(db, MIGRATION)
    assert _denied(_as(db, "manager", "SELECT invite_token FROM client_portal_users;"))
