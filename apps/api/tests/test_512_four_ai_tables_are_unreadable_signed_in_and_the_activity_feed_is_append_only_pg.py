"""Migration 512 — four AI tables are not readable by a signed-in session, and the client activity feed is append-only
(ledger POST-A-260 and POST-A-016).

PART 1: `ai_summaries`, `ai_context_windows`, `ai_feedback`, `ai_actions`
    `ai_summaries` caches the executive dashboard and the compliance summary under a key built from the asker's client scope; a
    Partner's firm-wide answer sits in it with no scope, so a member's own sign-in reading the table over PostgREST read
    client names and the practice's revenue the product withholds from them everywhere else. A row policy cannot narrow it (the
    key is a digest computed in Python), and nothing signed-in needs it: the one reader is `AICopilotRepository.get_summary`,
    which reads with the privileged client. The other three have no reader at all. The migration revokes every privilege on the
    four from `authenticated`, `anon` and PUBLIC. `ai_recommendations` stays readable on purpose (its restrictive
    assignment-scope policy narrows it).

PART 2: `client_timeline_events`
    A BEFORE UPDATE OR DELETE trigger refuses a delete and any update except `is_pinned`, `updated_at` and a one-way soft
    delete, for every role but the table's owner (a maintenance migration such as 437's back-fill runs as the owner).

WHAT IS HELD
    * (no database) no file in `apps/web` reads or writes any of the four tables; the API's only reader of `ai_summaries` is the
      repository's `get_summary`; nothing in `apps/api` reads `ai_context_windows`, `ai_feedback` or `ai_actions`;
    * (no database) the migration names the four tables and this test agrees;
    * (database) neither `authenticated` nor `anon` holds any privilege, at table or column level, on the four, `service_role`
      keeps SELECT, INSERT, UPDATE and DELETE, and `ai_recommendations` is still readable by `authenticated`;
    * (database) a Manager of the firm, as a real signed-in session, is refused a SELECT by the privilege on each of the four;
    * (database) as `service_role`, the API's role, a delete is refused, a rewrite of what an event says is refused (title,
      description, actor, visibility, amount, a financial-year change), the pin toggle and a first soft delete succeed, and a
      hidden event can be neither restored nor re-dated; as the table's owner a back-fill and a delete still work; a
      `platform_purge_firm` of the whole firm still removes the events; the trigger is a plain invoker function;
    * (database) the migration is idempotent and its rollback puts the privileges back and drops the trigger, which is the
      negative control for every refusal above.

Runs only when HARNESS_PG is set + psql on PATH (the source scans run always).
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATIONS = API_ROOT / "migrations"
_STEM = "512_a_signed_in_session_reads_four_ai_tables_no_more_and_the_activity_feed_is_append_only"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

FOUR = ("ai_context_windows", "ai_summaries", "ai_feedback", "ai_actions")

_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the AI-read and timeline proofs require HARNESS_PG + psql",
)


# ── no database ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _web_files():
    root = REPO_ROOT / "apps" / "web"
    for p in root.rglob("*"):
        if p.suffix in {".ts", ".tsx"} and "node_modules" not in p.parts and ".next" not in p.parts:
            yield p


def test_no_file_in_the_browser_reads_or_writes_the_four_tables():
    pattern = re.compile(r"""\.from\(\s*['"](%s)['"]""" % "|".join(FOUR))
    hits = [str(p.relative_to(REPO_ROOT)) for p in _web_files() if pattern.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert hits == [], f"a screen touches one of the four tables directly: {hits}"


def _chains(tree: ast.AST):
    """(table name, [verbs that follow `.table(name)` in the same chain]) for every `.table("x")` call."""
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "table"
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            verbs, up = [], node
            while True:
                parent = parents.get(up)
                if isinstance(parent, ast.Attribute) and isinstance(parents.get(parent), ast.Call):
                    verbs.append(parent.attr)
                    up = parents[parent]
                else:
                    break
            yield node.args[0].value, verbs


def _api_sources():
    for p in API_ROOT.rglob("*.py"):
        rel = p.relative_to(API_ROOT)
        if rel.parts[0] in {"tests", "scripts", "venv", ".venv", "migrations"}:
            continue
        yield p, ast.parse(p.read_text(encoding="utf-8"))


def test_the_only_reader_of_the_summary_cache_is_the_repositorys_get_summary():
    readers = []
    for path, tree in _api_sources():
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            for table, verbs in _chains(fn):
                if table == "ai_summaries" and "select" in verbs:
                    readers.append((str(path.relative_to(API_ROOT)), fn.name))
    assert readers == [("repositories/ai_copilot_repository.py", "get_summary")], readers


@pytest.mark.parametrize("table", ["ai_context_windows", "ai_feedback", "ai_actions"])
def test_nothing_in_the_api_reads_the_three_tables_that_have_no_reader(table):
    reads = [str(path.relative_to(API_ROOT)) for path, tree in _api_sources()
             for t, verbs in _chains(tree) if t == table and "select" in verbs]
    assert reads == [], f"{table} is read by {reads}: a reader needs the table to be reachable, decide it deliberately"


def test_the_migration_names_the_four_tables_and_the_test_agrees():
    sql = MIGRATION.read_text(encoding="utf-8")
    block = sql.split("tables text[] := ARRAY[", 1)[1].split("]", 1)[0]
    assert tuple(re.findall(r"'([a-z_]+)'", block)) == FOUR
    rollback = ROLLBACK.read_text(encoding="utf-8")
    assert all(t in rollback for t in FOUR)
    assert "ai_recommendations" not in block, "ai_recommendations is read on purpose: its assignment-scope policy narrows it"


# ── the database ───────────────────────────────────────────────────────────────────────────────────────────────────────
FIRM = "aaaaaaaa-0000-0000-0000-000000000512"
CLIENT = "cccccccc-0000-0000-0000-00000000a512"
MANAGER_AUTH = "11111111-1111-1111-1111-000000000512"
MANAGER_USER = "bbbbbbbb-1111-1111-1111-000000000512"
EVENT = "eeeeeeee-0000-0000-0000-000000000512"
SECOND_EVENT = "eeeeeeee-0000-0000-0000-000000000513"


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


def _as_service(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return _psql(dsn, f"SET ROLE service_role; {sql}")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"ai_tl_m512_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{MANAGER_AUTH}', 'manager@m512.test');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M512 Firm','m512@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{MANAGER_USER}', '{FIRM}', '{MANAGER_AUTH}', 'manager@m512.test', 'M', 'Manager', true);
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','Client A','Private Limited');
            INSERT INTO client_timeline_events (id, firm_id, client_id, financial_year, category, event_type, title, description)
              VALUES ('{EVENT}','{FIRM}','{CLIENT}','2026-27','general','note','Original title','Original description'),
                     ('{SECOND_EVENT}','{FIRM}','{CLIENT}','2026-27','general','note','Second event','x');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _held_by_a_signed_in_role(dsn: str, tables=FOUR) -> list[str]:
    names = ", ".join(f"'{t}'" for t in tables)
    return _ok(dsn, f"""
        SELECT c.relname || ':' || r.name || ':' || v.verb
          FROM pg_class c
          CROSS JOIN (VALUES ('authenticated'), ('anon')) AS r(name)
          CROSS JOIN (VALUES ('SELECT'),('INSERT'),('UPDATE'),('DELETE'),('TRUNCATE'),('REFERENCES'),('TRIGGER')) AS v(verb)
         WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r' AND c.relname IN ({names})
           AND has_table_privilege(r.name, c.oid, v.verb)
        UNION ALL
        SELECT c.relname || ':' || r.name || ':column ' || v.verb
          FROM pg_class c
          CROSS JOIN (VALUES ('authenticated'), ('anon')) AS r(name)
          CROSS JOIN (VALUES ('SELECT'),('INSERT'),('UPDATE')) AS v(verb)
         WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r' AND c.relname IN ({names})
           AND has_any_column_privilege(r.name, c.oid, v.verb)
         ORDER BY 1;""").splitlines()


@_NEEDS_PG
def test_the_rule_is_not_vacuous_the_four_tables_exist_on_a_scratch_database(db):
    have = set(_ok(db, "SELECT relname FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind='r';").splitlines())
    assert set(FOUR) <= have, sorted(set(FOUR) - have)


@_NEEDS_PG
def test_no_signed_in_role_holds_any_privilege_on_the_four(db):
    assert _held_by_a_signed_in_role(db) == []


@_NEEDS_PG
def test_the_api_keeps_its_privileges_on_the_four(db):
    lacking = [f"{t}:{v}" for t in FOUR for v in ("SELECT", "INSERT", "UPDATE", "DELETE")
               if _ok(db, f"SELECT has_table_privilege('service_role', 'public.{t}', '{v}');") != "t"]
    assert not lacking, f"service_role lacks a privilege the API needs: {lacking}"


@_NEEDS_PG
def test_recommendations_are_still_readable_because_their_scope_policy_narrows_them(db):
    assert _ok(db, "SELECT has_table_privilege('authenticated', 'public.ai_recommendations', 'SELECT');") == "t"


@_NEEDS_PG
@pytest.mark.parametrize("table", FOUR)
def test_a_manager_is_refused_a_read_by_the_privilege(db, table):
    r = _as_manager(db, f"SELECT count(*) FROM {table};")
    assert r.returncode != 0 and f"permission denied for table {table}" in r.stderr, r.stderr


# ── the activity feed ──────────────────────────────────────────────────────────────────────────────────────────────────
def _title(dsn: str, event: str = EVENT) -> str:
    return _ok(dsn, f"SELECT title FROM client_timeline_events WHERE id = '{event}';")


def _service_update(dsn: str, set_clause: str, event: str = EVENT) -> subprocess.CompletedProcess:
    return _as_service(dsn, f"UPDATE client_timeline_events SET {set_clause} WHERE id = '{event}';")


@_NEEDS_PG
def test_the_trigger_is_a_row_trigger_on_update_and_delete_and_runs_as_its_invoker(db):
    row = _ok(db, """
        SELECT (t.tgtype & 1) = 1 AS per_row, (t.tgtype & 2) = 2 AS before_, (t.tgtype & 8) = 8 AS on_delete,
               (t.tgtype & 16) = 16 AS on_update, t.tgenabled, p.prosecdef
          FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
         WHERE t.tgrelid = 'public.client_timeline_events'::regclass AND t.tgname = 'client_timeline_events_append_only';""")
    assert row == "t|t|t|t|O|f", row


@_NEEDS_PG
def test_a_delete_is_refused_to_the_api(db):
    r = _as_service(db, f"DELETE FROM client_timeline_events WHERE id = '{EVENT}';")
    assert r.returncode != 0 and "append-only" in r.stderr, r.stderr
    assert _title(db) == "Original title"


@_NEEDS_PG
@pytest.mark.parametrize("set_clause", [
    "title = 'Rewritten'", "description = 'x'", "actor_name = 'Someone else'", "visibility = 'internal'",
    "amount_paise = 1", "financial_year = '2025-26'", "client_id = gen_random_uuid()", "event_type = 'other'",
])
def test_what_an_event_says_cannot_be_rewritten_by_the_api(db, set_clause):
    r = _service_update(db, set_clause)
    assert r.returncode != 0 and "append-only" in r.stderr, (set_clause, r.stderr)
    assert _title(db) == "Original title"


@_NEEDS_PG
def test_the_pin_toggle_is_allowed_and_leaves_the_rest_alone(db):
    assert _service_update(db, "is_pinned = true").returncode == 0
    assert _ok(db, f"SELECT is_pinned FROM client_timeline_events WHERE id = '{EVENT}';") == "t"
    assert _service_update(db, "is_pinned = false").returncode == 0
    assert _title(db) == "Original title"


@_NEEDS_PG
def test_the_updated_at_stamp_is_allowed_where_the_table_has_one(db):
    """Production's table has `updated_at` (migration 187 note) and a migration-built database may not; the trigger compares
    the whole row as JSON, so it is indifferent to whether the column exists."""
    if _ok(db, "SELECT count(*) FROM information_schema.columns WHERE table_name='client_timeline_events' "
               "AND column_name='updated_at';") == "0":
        pytest.skip("this database's table has no updated_at column")
    assert _service_update(db, "is_pinned = true, updated_at = now()").returncode == 0


@_NEEDS_PG
def test_an_event_can_be_soft_deleted_once_and_not_restored_or_re_dated(db):
    assert _service_update(db, "deleted_at = '2026-10-01T10:00:00Z'").returncode == 0
    restored = _service_update(db, "deleted_at = NULL")
    assert restored.returncode != 0 and "append-only" in restored.stderr, restored.stderr
    redated = _service_update(db, "deleted_at = '2026-10-02T10:00:00Z'")
    assert redated.returncode != 0 and "append-only" in redated.stderr, redated.stderr
    assert _ok(db, f"SELECT deleted_at IS NOT NULL FROM client_timeline_events WHERE id = '{EVENT}';") == "t"


@_NEEDS_PG
def test_a_soft_delete_cannot_carry_another_change_with_it(db):
    r = _service_update(db, "deleted_at = now(), title = 'Rewritten while hiding it'")
    assert r.returncode != 0 and "append-only" in r.stderr, r.stderr
    assert _title(db) == "Original title"


@_NEEDS_PG
def test_the_tables_owner_can_still_maintain_it(db):
    """A back-fill such as migration 437's runs as the owner and must not be blocked."""
    assert _psql(db, f"UPDATE client_timeline_events SET financial_year = '2025-26' WHERE id = '{EVENT}';").returncode == 0
    assert _ok(db, f"SELECT financial_year FROM client_timeline_events WHERE id = '{EVENT}';") == "2025-26"
    assert _psql(db, f"DELETE FROM client_timeline_events WHERE id = '{SECOND_EVENT}';").returncode == 0


@_NEEDS_PG
def test_a_signed_in_staff_member_still_pins_and_still_cannot_rewrite_or_delete(db):
    """The existing grant (migration 494) is untouched: the privilege refuses first, the trigger is the second lock."""
    pinned = _as_manager(db, f"UPDATE client_timeline_events SET is_pinned = true WHERE id = '{EVENT}';")
    assert pinned.returncode == 0, pinned.stderr
    rewrite = _as_manager(db, f"UPDATE client_timeline_events SET title = 'x' WHERE id = '{EVENT}';")
    assert rewrite.returncode != 0 and "permission denied" in rewrite.stderr
    delete = _as_manager(db, f"DELETE FROM client_timeline_events WHERE id = '{EVENT}';")
    assert delete.returncode != 0 and "permission denied" in delete.stderr


@_NEEDS_PG
def test_truncate_is_not_held_by_a_signed_in_role(db):
    assert _ok(db, "SELECT has_table_privilege('authenticated','public.client_timeline_events','TRUNCATE') "
                   "OR has_table_privilege('anon','public.client_timeline_events','TRUNCATE');") == "f"


@_NEEDS_PG
def test_purging_a_whole_firm_still_removes_its_events(db):
    """`platform_purge_firm` runs as the table's owner (it is SECURITY DEFINER) and sets session_replication_role = replica
    before it deletes, which skips ordinary triggers; either is enough, and the trigger must not stand in the way of erasing a
    whole firm."""
    # The function asks `auth.role()`: the backend calls it as the service role (the router gates it on a platform admin + MFA).
    claims = json.dumps({"role": "service_role"})
    r = _psql(db, f"SET request.jwt.claims = '{claims}'; SELECT platform_purge_firm('{FIRM}');")
    assert r.returncode == 0, r.stderr
    assert _ok(db, f"SELECT count(*) FROM client_timeline_events WHERE firm_id = '{FIRM}';") == "0"


@_NEEDS_PG
def test_the_migration_is_idempotent(db):
    assert _psql(db, MIGRATION.read_text(encoding="utf-8")).returncode == 0
    assert _held_by_a_signed_in_role(db) == []
    assert _ok(db, "SELECT count(*) FROM pg_trigger WHERE tgrelid='public.client_timeline_events'::regclass "
                   "AND tgname='client_timeline_events_append_only';") == "1"


@_NEEDS_PG
def test_the_rollback_puts_everything_back_so_each_refusal_above_was_the_migration(db):
    assert _psql(db, ROLLBACK.read_text(encoding="utf-8")).returncode == 0
    assert _ok(db, "SELECT count(*) FROM pg_trigger WHERE tgrelid='public.client_timeline_events'::regclass "
                   "AND tgname='client_timeline_events_append_only';") == "0"
    assert _service_update(db, "title = 'Rewritten'").returncode == 0
    assert _title(db) == "Rewritten"
    assert _as_service(db, f"DELETE FROM client_timeline_events WHERE id = '{SECOND_EVENT}';").returncode == 0
    for table in FOUR:
        r = _as_manager(db, f"SELECT count(*) FROM {table};")
        assert f"permission denied for table {table}" not in r.stderr, (table, r.stderr)
    assert _psql(db, MIGRATION.read_text(encoding="utf-8")).returncode == 0
    assert _held_by_a_signed_in_role(db) == []
