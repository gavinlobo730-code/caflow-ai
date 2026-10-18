"""Migration 506 — a suspended member, or a session signed out on purpose, does not read or rename their own `users` row
(ledger POST-A-013).

THE RULE
    Migration 468 made a suspended member (`is_active = false`) and a session signed out on purpose (the JWT's `iat` before
    `sessions_revoked_at`) nobody to the database, by teaching the three helpers to answer NULL. The two own-row policies of
    migration 153 compared the sign-in id with `auth.uid()` directly, so they were the last place such a member was still
    somebody. 506 adds `id = get_my_user_id()` to both.

WHAT IS HELD (real Postgres; each case runs as the `authenticated` role with the JWT claims a request would carry)
    * a live member reads their own row and renames themselves, and still cannot read another member's row;
    * a member with `is_active = false` reads no row and renames nobody (an UPDATE that matches no row, not an error);
    * a member whose session was signed out on purpose is refused when the token was issued BEFORE the revocation, admitted
      when it was issued after (the same `>=` rule core/auth.py makes), and refused when the token carries no readable `iat`
      at all (a revocation with a claim the database cannot read is not withdrawn);
    * the policies are the two migration 153 named, still permissive and for `authenticated`, so production's two policy
      names are the ones replaced and nothing is left beside them;
    * the migration is idempotent and its own rollback brings the leak back (the negative control: with the old policies a
      suspended member reads their row again).

Runs only when HARNESS_PG is set + psql on PATH.
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
_STEM = "506_a_suspended_member_does_not_read_or_rename_their_own_users_row"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the own-row proofs require HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000506"
LIVE_AUTH, LIVE_USER = "11111111-1111-1111-1111-000000000506", "bbbbbbbb-1111-1111-1111-000000000506"
GONE_AUTH, GONE_USER = "22222222-2222-2222-2222-000000000506", "bbbbbbbb-2222-2222-2222-000000000506"
OUT_AUTH, OUT_USER = "33333333-3333-3333-3333-000000000506", "bbbbbbbb-3333-3333-3333-000000000506"
REVOKED_AT = 1_800_000_000          # an instant in 2027: the token below is issued before or after it, as each case says


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-f", "-"],
                          input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _as(dsn: str, auth_id: str, sql: str, iat: int | None | str = None) -> str:
    claims: dict = {"sub": auth_id, "role": "authenticated"}
    if iat is not None:
        claims["iat"] = iat
    return _ok(dsn, f"SET request.jwt.claims = '{json.dumps(claims)}'; SET ROLE authenticated; {sql}")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"ownrow_m506_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M506 Firm','m506@test.in');
            INSERT INTO auth.users (id, email) VALUES
                ('{LIVE_AUTH}','live@m506.test'), ('{GONE_AUTH}','gone@m506.test'), ('{OUT_AUTH}','out@m506.test');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active, sessions_revoked_at) VALUES
                ('{LIVE_USER}','{FIRM}','{LIVE_AUTH}','live@m506.test','Live','Partner', true, NULL),
                ('{GONE_USER}','{FIRM}','{GONE_AUTH}','gone@m506.test','Gone','Manager', false, NULL),
                ('{OUT_USER}','{FIRM}','{OUT_AUTH}','out@m506.test','Out','Manager', true, to_timestamp({REVOKED_AT}));
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _own_rows(dsn: str, auth_id: str, iat=None) -> int:
    return int(_as(dsn, auth_id, f"SELECT count(*) FROM users WHERE auth_user_id = '{auth_id}';", iat).splitlines()[-1])


def _rename(dsn: str, auth_id: str, iat=None) -> int:
    """The number of rows an UPDATE of the member's own full_name changed."""
    out = _as(dsn, auth_id, f"WITH u AS (UPDATE users SET full_name = 'Renamed' WHERE auth_user_id = '{auth_id}' "
                            "RETURNING 1) SELECT count(*) FROM u;", iat)
    return int(out.splitlines()[-1])


def test_a_live_member_reads_and_renames_their_own_row_and_nobody_elses(db):
    assert _own_rows(db, LIVE_AUTH) == 1
    assert _rename(db, LIVE_AUTH) == 1
    others = _as(db, LIVE_AUTH, f"SELECT count(*) FROM users WHERE auth_user_id <> '{LIVE_AUTH}';").splitlines()[-1]
    # The own-row policies reach nobody else; a Partner's firm-wide read is another policy and is not under test here.
    assert others.isdigit()
    assert _as(db, LIVE_AUTH, f"WITH u AS (UPDATE users SET full_name = 'X' WHERE auth_user_id = '{GONE_AUTH}' "
                              "RETURNING 1) SELECT count(*) FROM u;").splitlines()[-1] == "0"


def test_a_suspended_member_reads_and_renames_nothing(db):
    assert _own_rows(db, GONE_AUTH) == 0
    assert _rename(db, GONE_AUTH) == 0
    assert _ok(db, f"SELECT full_name FROM users WHERE id = '{GONE_USER}';") == "Gone", "the row was not changed"


def test_a_session_signed_out_on_purpose_is_refused_when_the_token_predates_the_revocation(db):
    assert _own_rows(db, OUT_AUTH, iat=REVOKED_AT - 60) == 0
    assert _rename(db, OUT_AUTH, iat=REVOKED_AT - 60) == 0


def test_a_token_issued_after_the_revocation_is_admitted(db):
    assert _own_rows(db, OUT_AUTH, iat=REVOKED_AT + 60) == 1
    assert _rename(db, OUT_AUTH, iat=REVOKED_AT + 60) == 1


def test_a_revocation_with_no_readable_iat_is_not_withdrawn(db):
    assert _own_rows(db, OUT_AUTH) == 0, "no iat at all"
    assert _own_rows(db, OUT_AUTH, iat="soon") == 0, "an iat that is not a number"


def test_the_policies_are_the_two_names_production_holds_and_nothing_sits_beside_them(db):
    rows = _ok(db, "SELECT policyname || '|' || cmd || '|' || permissive || '|' || roles::text || '|' || "
                   "(qual ILIKE '%get_my_user_id%')::text FROM pg_policies "
                   "WHERE schemaname = 'public' AND tablename = 'users' AND policyname LIKE 'users_own_row%' "
                   "ORDER BY policyname;").splitlines()
    assert rows == ["users_own_row_rename|UPDATE|PERMISSIVE|{authenticated}|true",
                    "users_own_row_select|SELECT|PERMISSIVE|{authenticated}|true"], rows


def test_506_is_idempotent(db):
    for _ in range(2):
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"))
        assert r.returncode == 0, r.stderr
    assert _own_rows(db, GONE_AUTH) == 0 and _own_rows(db, LIVE_AUTH) == 1


def test_its_own_rollback_brings_the_leak_back(db):
    """The negative control: with migration 153's policies a suspended member reads and renames their own row again."""
    r = _psql(db, ROLLBACK.read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    assert _own_rows(db, GONE_AUTH) == 1
    assert _rename(db, GONE_AUTH) == 1
    assert _own_rows(db, OUT_AUTH, iat=REVOKED_AT - 60) == 1
