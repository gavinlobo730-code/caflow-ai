"""Migration 505 — a signed-in session writes none of the AI tables (ledger POST-A-250).

THE RULE
    The AI conversation, message, summary, recommendation, feedback, action and context-window tables are written by the
    API with the privileged client, never from a signed-in session: no screen in `apps/web` touches them, and a write from a
    member's own session could plant an `assistant` turn in another member's conversation that the next prompt replays as
    the model's own. Migration 505 revokes INSERT, UPDATE, DELETE and TRUNCATE from `authenticated`, `anon` and PUBLIC on
    the seven; the row policies stay as the second lock.

WHAT IS HELD
    * (no database) no file in `apps/web` names any of the seven tables, so a screen that starts to will fail here and have
      to decide, in the open;
    * (database) a signed-in role effectively holds NO write privilege (table level, column level or through PUBLIC) on any of
      the seven, and `service_role`, which the API uses, keeps INSERT, UPDATE and DELETE on all of them;
    * (database) a Manager who belongs to the firm is refused a direct insert by the PRIVILEGE ("permission denied for table
      <the table>"), on each of the seven; reading is unaffected;
    * (database) the migration REMOVES what the hosting platform's defaults give (TRUNCATE for `authenticated` and `anon`, and
      a write through PUBLIC or a column grant), its closing check fails the migration when a write cannot be revoked, it is
      idempotent, and its own rollback puts the holes back (the negative control: every statement refused above then goes
      through, so each refusal was the privilege and not a malformed statement).

Runs only when HARNESS_PG is set + psql on PATH (the source scan runs always).
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
WEB_ROOT = API_ROOT.parents[1] / "apps" / "web"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATIONS = API_ROOT / "migrations"
_STEM = "505_a_signed_in_session_writes_none_of_the_ai_tables"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

AI_TABLES = ("ai_conversations", "ai_messages", "ai_summaries", "ai_recommendations", "ai_feedback", "ai_actions",
             "ai_context_windows")

_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the AI write-privilege proofs require HARNESS_PG + psql",
)


# ── no database ────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_no_screen_names_an_ai_table_in_code():
    """A word in a comment is not a query (two files explain why the copilot page does not read these); a table name in a
    string literal is the way a screen reaches one."""
    import re
    hits = []
    for path in list((WEB_ROOT / "app").rglob("*.ts*")) + list((WEB_ROOT / "components").rglob("*.ts*")) \
            + list((WEB_ROOT / "lib").rglob("*.ts*")):
        if "node_modules" in path.parts or ".test." in path.name:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        code = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        code = re.sub(r"(?m)^\s*//.*$|(?<=\s)//.*$", "", code)
        for t in AI_TABLES:
            if re.search(r"""["'`]%s["'`]""" % t, code):
                hits.append(f"{path.relative_to(WEB_ROOT)} -> {t}")
    assert hits == [], f"a screen reaches an AI table directly: {hits}"


def test_the_migration_names_the_seven_tables_and_the_test_agrees():
    sql = MIGRATION.read_text(encoding="utf-8")
    block = sql.split("tables text[] := ARRAY[", 1)[1].split("]", 1)[0]
    import re
    assert tuple(re.findall(r"'([a-z_]+)'", block)) == AI_TABLES


# ── the database ───────────────────────────────────────────────────────────────────────────────────────────────────────
FIRM = "aaaaaaaa-0000-0000-0000-000000000505"
MANAGER_AUTH = "11111111-1111-1111-1111-000000000505"
MANAGER_USER = "bbbbbbbb-1111-1111-1111-000000000505"
CONV = "dddddddd-0000-0000-0000-000000000505"


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _as_manager(dsn: str, sql: str) -> subprocess.CompletedProcess:
    claims = json.dumps({"sub": MANAGER_AUTH, "role": "authenticated"})
    return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"aiwrite_m505_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{MANAGER_AUTH}', 'manager@m505.test');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M505 Firm','m505@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{MANAGER_USER}', '{FIRM}', '{MANAGER_AUTH}', 'manager@m505.test', 'M', 'Manager', true);
            INSERT INTO ai_conversations (id, firm_id, user_id) VALUES ('{CONV}', '{FIRM}', '{MANAGER_AUTH}');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _writable_by_a_signed_in_role(dsn: str) -> set[str]:
    """AI tables on which `authenticated` or `anon` EFFECTIVELY holds a write privilege: table level, column level, or
    through PUBLIC (has_table_privilege / has_any_column_privilege see all three)."""
    rows = _ok(dsn, """
        SELECT c.relname
          FROM pg_class c
          CROSS JOIN (VALUES ('authenticated'), ('anon')) AS r(name)
         WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
           AND (has_table_privilege(r.name, c.oid, 'INSERT') OR has_table_privilege(r.name, c.oid, 'UPDATE')
                OR has_table_privilege(r.name, c.oid, 'DELETE') OR has_table_privilege(r.name, c.oid, 'TRUNCATE')
                OR has_any_column_privilege(r.name, c.oid, 'INSERT') OR has_any_column_privilege(r.name, c.oid, 'UPDATE'))
         GROUP BY c.relname;""").splitlines()
    return {r for r in rows if r in AI_TABLES}


@_NEEDS_PG
def test_the_seven_tables_exist_so_the_rule_is_not_vacuous(db):
    have = set(_ok(db, "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace "
                       "AND relkind = 'r';").splitlines())
    assert set(AI_TABLES) <= have


@_NEEDS_PG
def test_no_signed_in_role_holds_a_write_on_any_ai_table(db):
    assert _writable_by_a_signed_in_role(db) == set(), sorted(_writable_by_a_signed_in_role(db))


@_NEEDS_PG
def test_the_api_keeps_its_write_privileges_on_every_ai_table(db):
    lacking = [f"{t}:{v}" for t in AI_TABLES for v in ("INSERT", "UPDATE", "DELETE")
               if _ok(db, f"SELECT has_table_privilege('service_role', 'public.{t}', '{v}');") != "t"]
    assert not lacking, f"service_role lacks a write privilege the API needs: {lacking}"


PROBES = {
    "ai_conversations": "INSERT INTO ai_conversations (firm_id, user_id) VALUES ('{f}', '{u}');",
    "ai_messages": "INSERT INTO ai_messages (conversation_id, firm_id, role, content) VALUES ('{c}', '{f}', 'assistant', 'x');",
    "ai_summaries": "INSERT INTO ai_summaries (firm_id, summary_type, title, content) VALUES ('{f}', 'executive', 't', 'c');",
    "ai_recommendations": ("INSERT INTO ai_recommendations (firm_id, recommendation_type, title, description) "
                           "VALUES ('{f}', 'risk', 't', 'd');"),
    "ai_feedback": "INSERT INTO ai_feedback (firm_id, user_id, rating) VALUES ('{f}', '{u}', 5);",
    "ai_actions": "INSERT INTO ai_actions (firm_id, action_type) VALUES ('{f}', 'create_task');",
    "ai_context_windows": "INSERT INTO ai_context_windows (conversation_id, firm_id) VALUES ('{c}', '{f}');",
}


@_NEEDS_PG
def test_there_is_a_probe_for_every_table():
    assert set(PROBES) == set(AI_TABLES)


@_NEEDS_PG
@pytest.mark.parametrize("table", AI_TABLES)
def test_a_manager_of_the_firm_is_refused_by_the_privilege(db, table):
    r = _as_manager(db, PROBES[table].format(f=FIRM, u=MANAGER_USER, c=CONV))
    assert r.returncode != 0 and f"permission denied for table {table}" in r.stderr, (
        f"{table}: a signed-in Manager wrote an AI table directly: {r.stderr or 'it succeeded'}")


@_NEEDS_PG
def test_a_manager_cannot_plant_a_turn_in_their_own_conversation_either(db):
    r = _as_manager(db, f"UPDATE ai_conversations SET title = 'x' WHERE id = '{CONV}';")
    assert r.returncode != 0 and "permission denied for table ai_conversations" in r.stderr, r.stderr


@_NEEDS_PG
def test_reading_is_unaffected(db):
    r = _as_manager(db, "SELECT count(*) FROM ai_conversations;")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "1"


@_NEEDS_PG
def test_the_api_path_still_works_the_function_the_repository_calls_runs_as_the_service_role(db):
    """`increment_message_count` is the one write the repository makes by function. It runs for the service role, and for the
    conversation's own member (migration 486 asks whose conversation it is), so moving the call to the privileged client
    loses nothing."""
    assert _ok(db, f"SET ROLE service_role; SELECT increment_message_count('{CONV}');").splitlines()[-1] == "1"
    claims = json.dumps({"sub": MANAGER_AUTH, "role": "authenticated"})
    r = _psql(db, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; SELECT increment_message_count('{CONV}');")
    assert r.returncode == 0, r.stderr


@_NEEDS_PG
def test_505_removes_what_the_hosting_platform_grants_and_what_reaches_a_role_another_way(db):
    _ok(db, """
        GRANT TRUNCATE, REFERENCES, TRIGGER ON public.ai_conversations, public.ai_messages TO authenticated, anon;
        GRANT INSERT, UPDATE, DELETE, TRUNCATE ON public.ai_actions TO anon;
        GRANT INSERT ON public.ai_summaries TO PUBLIC;
        GRANT UPDATE (title) ON public.ai_conversations TO authenticated;
    """)
    before = _writable_by_a_signed_in_role(db)
    assert {"ai_conversations", "ai_messages", "ai_actions", "ai_summaries"} <= before, before
    r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    assert _writable_by_a_signed_in_role(db) == set()
    assert _ok(db, "SELECT has_table_privilege('anon', 'public.ai_messages', 'REFERENCES');") == "t"


@_NEEDS_PG
def test_the_closing_check_fails_the_migration_when_a_write_cannot_be_revoked(db):
    grantor = f"m505_g_{uuid.uuid4().hex[:8]}"
    _ok(db, f"""
        CREATE ROLE {grantor} NOLOGIN;
        GRANT INSERT ON public.ai_messages TO {grantor} WITH GRANT OPTION;
        SET ROLE {grantor};
        GRANT INSERT ON public.ai_messages TO authenticated;
        RESET ROLE;
    """)
    try:
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
        assert r.returncode != 0 and "migration 505: authenticated still holds INSERT on ai_messages" in r.stderr, (
            r.stdout, r.stderr)
    finally:
        _psql(db, f"DROP OWNED BY {grantor}; DROP ROLE IF EXISTS {grantor};")


@_NEEDS_PG
def test_505_is_idempotent(db):
    for _ in range(2):
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
        assert r.returncode == 0, r.stderr
    assert _writable_by_a_signed_in_role(db) == set()


@_NEEDS_PG
def test_its_own_rollback_puts_the_holes_back(db):
    """The negative control: with the grants back, every probe above goes through for the Manager, so each refusal was the
    privilege and not a statement that was malformed or stopped by a policy on the way."""
    r = _psql(db, ROLLBACK.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    assert _writable_by_a_signed_in_role(db) == set(AI_TABLES)
    for table in AI_TABLES:
        again = _as_manager(db, PROBES[table].format(f=FIRM, u=MANAGER_USER, c=CONV))
        assert again.returncode == 0, (table, again.stderr)
