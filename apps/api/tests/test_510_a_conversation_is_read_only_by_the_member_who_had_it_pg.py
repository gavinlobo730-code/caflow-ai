"""Migration 510 — an AI conversation, and its messages, are read only by the member who had the conversation (POST-A-258).

THE RULE
    The API serves a conversation to its owner alone (migration 505's repository, POST-A-250). The database now agrees: a
    RESTRICTIVE SELECT policy on `ai_conversations` (`user_id = auth.uid()`, the sign-in id the API stores) and one on
    `ai_messages` (the message's conversation is the caller's) sit beside the firm-isolation policies, which stay.

WHAT IS HELD (real Postgres)
    * the owner reads their conversation and its messages through their own JWT;
    * another member of the SAME firm reads neither, and neither does the Partner of that firm, and neither does a member of
      another firm (the Partner case is a decision, written in the migration);
    * the API's role (`service_role`) reads both;
    * the migration is idempotent and its rollback gives the firm-wide read back (the negative control: the refusals above
      were the policies and not an empty table).
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
_STEM = "510_a_conversation_is_read_only_by_the_member_who_had_it"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the conversation read proofs require HARNESS_PG + psql",
)

FIRM, OTHER_FIRM = "aaaaaaaa-0000-0000-0000-000000000510", "aaaaaaaa-0000-0000-0000-0000000005f0"
OWNER_AUTH, OTHER_AUTH, PARTNER_AUTH, STRANGER_AUTH = (f"1111111{i}-1111-1111-1111-000000000510" for i in range(4))
OWNER_USER, OTHER_USER, PARTNER_USER, STRANGER_USER = (f"bbbbbbb{i}-1111-1111-1111-000000000510" for i in range(4))
CONVERSATION = "cccccccc-0000-0000-0000-000000000510"
MESSAGE = "dddddddd-0000-0000-0000-000000000510"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-f", "-"],
                          input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _count(dsn: str, auth_id: str, table: str) -> int:
    claims = json.dumps({"sub": auth_id, "role": "authenticated"})
    out = _ok(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; SELECT count(*) FROM {table};")
    return int(out.splitlines()[-1])


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"convread_m510_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M510 Firm','a@m510.in'), ('{OTHER_FIRM}','Other','b@m510.in');
            INSERT INTO auth.users (id, email) VALUES ('{OWNER_AUTH}','o@m510.test'), ('{OTHER_AUTH}','m@m510.test'),
                   ('{PARTNER_AUTH}','p@m510.test'), ('{STRANGER_AUTH}','s@m510.test');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES
                   ('{OWNER_USER}','{FIRM}','{OWNER_AUTH}','o@m510.test','Owner','Manager',true),
                   ('{OTHER_USER}','{FIRM}','{OTHER_AUTH}','m@m510.test','Other','Manager',true),
                   ('{PARTNER_USER}','{FIRM}','{PARTNER_AUTH}','p@m510.test','Partner','Partner',true),
                   ('{STRANGER_USER}','{OTHER_FIRM}','{STRANGER_AUTH}','s@m510.test','Stranger','Partner',true);
            INSERT INTO ai_conversations (id, firm_id, user_id, title) VALUES ('{CONVERSATION}','{FIRM}','{OWNER_AUTH}','mine');
            INSERT INTO ai_messages (id, conversation_id, firm_id, role, content)
                 VALUES ('{MESSAGE}','{CONVERSATION}','{FIRM}','user','a private question');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


@pytest.mark.parametrize("table", ["ai_conversations", "ai_messages"])
def test_the_owner_reads_their_own_conversation_and_messages(db, table):
    assert _count(db, OWNER_AUTH, table) == 1


@pytest.mark.parametrize("who,auth", [("another member", OTHER_AUTH), ("the Partner of the firm", PARTNER_AUTH),
                                       ("a member of another firm", STRANGER_AUTH)])
@pytest.mark.parametrize("table", ["ai_conversations", "ai_messages"])
def test_nobody_else_reads_it(db, who, auth, table):
    assert _count(db, auth, table) == 0, f"{who} read {table}"


def test_the_api_role_still_reads_both(db):
    out = _ok(db, "SET ROLE service_role; SELECT (SELECT count(*) FROM ai_conversations) || '|' || "
                  "(SELECT count(*) FROM ai_messages);")
    assert out.splitlines()[-1] == "1|1"


def test_the_two_policies_are_restrictive_selects_and_the_firm_policies_are_untouched(db):
    rows = _ok(db, "SELECT tablename || ':' || policyname || ':' || cmd || ':' || permissive FROM pg_policies "
                   "WHERE tablename IN ('ai_conversations','ai_messages') ORDER BY 1;").splitlines()
    assert "ai_conversations:ai_conversations_owner_only:SELECT:RESTRICTIVE" in rows
    assert "ai_messages:ai_messages_owner_only:SELECT:RESTRICTIVE" in rows
    assert "ai_conversations:ai_conversations_firm_isolation:ALL:PERMISSIVE" in rows
    assert "ai_messages:ai_messages_firm_isolation:ALL:PERMISSIVE" in rows


def test_the_migration_is_idempotent(db):
    assert _psql(db, MIGRATION.read_text(encoding="utf-8")).returncode == 0
    assert _psql(db, MIGRATION.read_text(encoding="utf-8")).returncode == 0
    assert _count(db, OTHER_AUTH, "ai_conversations") == 0
    assert _count(db, OWNER_AUTH, "ai_conversations") == 1


def test_the_rollback_gives_the_firm_wide_read_back_so_each_refusal_was_the_policy(db):
    assert _psql(db, ROLLBACK.read_text(encoding="utf-8")).returncode == 0
    assert _count(db, OTHER_AUTH, "ai_conversations") == 1
    assert _count(db, OTHER_AUTH, "ai_messages") == 1
    assert _count(db, STRANGER_AUTH, "ai_conversations") == 0, "another firm must stay shut out either way"
    assert _psql(db, MIGRATION.read_text(encoding="utf-8")).returncode == 0
    assert _count(db, OTHER_AUTH, "ai_conversations") == 0
