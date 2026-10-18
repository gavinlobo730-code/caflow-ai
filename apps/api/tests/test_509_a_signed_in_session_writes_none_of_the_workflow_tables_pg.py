"""Migration 509 — a signed-in session writes none of the workflow tables (ledger POST-A-248).

THE RULE
    The eleven `workflow_*` tables are written by the API with the privileged client, never from a signed-in session: no file
    in `apps/web` touches them, and a write from a member's own session could edit a template, change a run, mark an approval
    decided or forge a failure row without `rbac()`. Migration 509 revokes INSERT, UPDATE, DELETE and TRUNCATE from
    `authenticated`, `anon` and PUBLIC on the eleven; the row policies stay as the second lock. (Migrations 499, 505 and 507
    did the same for payroll, the copilot and the insight tables.)

WHAT IS HELD
    * (no database) no file in `apps/web` writes any of the eleven tables;
    * (no database) the migration names the eleven tables and this test agrees;
    * (database) a signed-in role effectively holds NO write privilege (table level, column level or through PUBLIC) on any
      of them, and `service_role`, which the API uses, keeps INSERT, UPDATE and DELETE on all of them;
    * (database) a Manager of the firm is refused INSERT, UPDATE and DELETE on each table by the PRIVILEGE ("permission
      denied for table <the table>"), whatever the row; the probes need no knowledge of a table's columns because a privilege
      is checked before a constraint is;
    * (database) the policies are untouched by the migration, it is idempotent, and its own rollback puts the grants back
      (the negative control: every statement refused above then goes on to fail on something else, or succeed, so each
      refusal was the privilege and not a malformed statement).

Runs only when HARNESS_PG is set + psql on PATH (the source scans run always).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATIONS = API_ROOT / "migrations"
_STEM = "509_a_signed_in_session_writes_none_of_the_workflow_tables"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

WORKFLOW_TABLES = (
    "workflows", "workflow_templates", "workflow_steps", "workflow_instances", "workflow_approvals",
    "workflow_executions", "workflow_failures", "workflow_schedules", "workflow_triggers", "workflow_conditions",
    "workflow_action_logs",
)

_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the workflow write-privilege proofs require HARNESS_PG + psql",
)


# ── no database ────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_browser_writes_none_of_the_eleven_tables():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_direct_write_tables_are_role_guarded import _direct_write_tables
    found = {t for t in _direct_write_tables() if t in WORKFLOW_TABLES}
    assert found == set(), f"a screen writes a workflow table directly: {sorted(found)}"


def test_the_migration_names_the_eleven_tables_and_the_test_agrees():
    sql = MIGRATION.read_text(encoding="utf-8")
    block = sql.split("tables text[] := ARRAY[", 1)[1].split("]", 1)[0]
    assert tuple(re.findall(r"'([a-z_]+)'", block)) == WORKFLOW_TABLES
    rollback = ROLLBACK.read_text(encoding="utf-8")
    assert set(re.findall(r"'(workflow[a-z_]*)'", rollback)) == set(WORKFLOW_TABLES)


# ── the database ───────────────────────────────────────────────────────────────────────────────────────────────────────
FIRM = "aaaaaaaa-0000-0000-0000-000000000509"
MANAGER_AUTH = "11111111-1111-1111-1111-000000000509"
MANAGER_USER = "bbbbbbbb-1111-1111-1111-000000000509"


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _present(dsn: str) -> set[str]:
    have = set(_ok(dsn, "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace "
                        "AND relkind = 'r';").splitlines())
    return {t for t in WORKFLOW_TABLES if t in have}


def _as_manager(dsn: str, sql: str) -> subprocess.CompletedProcess:
    claims = json.dumps({"sub": MANAGER_AUTH, "role": "authenticated"})
    return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"wfwrite_m509_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{MANAGER_AUTH}', 'manager@m509.test');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M509 Firm','m509@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{MANAGER_USER}', '{FIRM}', '{MANAGER_AUTH}', 'manager@m509.test', 'M', 'Manager', true);
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _writable_by_a_signed_in_role(dsn: str) -> set[str]:
    rows = _ok(dsn, """
        SELECT c.relname
          FROM pg_class c
          CROSS JOIN (VALUES ('authenticated'), ('anon')) AS r(name)
         WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
           AND (has_table_privilege(r.name, c.oid, 'INSERT') OR has_table_privilege(r.name, c.oid, 'UPDATE')
                OR has_table_privilege(r.name, c.oid, 'DELETE') OR has_table_privilege(r.name, c.oid, 'TRUNCATE')
                OR has_any_column_privilege(r.name, c.oid, 'INSERT') OR has_any_column_privilege(r.name, c.oid, 'UPDATE'))
         GROUP BY c.relname;""").splitlines()
    return {r for r in rows if r in WORKFLOW_TABLES}


@_NEEDS_PG
def test_the_rule_is_not_vacuous_the_core_tables_exist_on_a_scratch_database(db):
    assert _present(db) >= {"workflow_templates", "workflow_steps", "workflow_instances", "workflow_approvals",
                            "workflow_schedules", "workflow_action_logs"}, _present(db)


@_NEEDS_PG
def test_no_signed_in_role_holds_a_write_on_any_of_them(db):
    assert _writable_by_a_signed_in_role(db) == set(), sorted(_writable_by_a_signed_in_role(db))


@_NEEDS_PG
def test_the_api_keeps_its_write_privileges_on_every_one_of_them(db):
    lacking = [f"{t}:{v}" for t in sorted(_present(db)) for v in ("INSERT", "UPDATE", "DELETE")
               if _ok(db, f"SELECT has_table_privilege('service_role', 'public.{t}', '{v}');") != "t"]
    assert not lacking, f"service_role lacks a write privilege the API needs: {lacking}"


@_NEEDS_PG
def test_a_signed_in_member_can_still_read_the_tables(db):
    for t in sorted(_present(db)):
        assert _ok(db, f"SELECT has_table_privilege('authenticated', 'public.{t}', 'SELECT');") == "t", t


VERBS = {
    "INSERT": "INSERT INTO {t} DEFAULT VALUES;",
    "UPDATE": "UPDATE {t} SET id = id WHERE false;",
    "DELETE": "DELETE FROM {t} WHERE false;",
}


@_NEEDS_PG
@pytest.mark.parametrize("verb", sorted(VERBS))
def test_a_manager_of_the_firm_is_refused_by_the_privilege_on_every_table(db, verb):
    """`workflow_triggers` and `workflow_conditions` have no `id` column? They do; if a table ever lacks it the UPDATE probe
    would fail on the column, which this assertion reports as a different error, not a pass."""
    wrong = []
    for t in sorted(_present(db)):
        r = _as_manager(db, VERBS[verb].format(t=t))
        if r.returncode == 0 or f"permission denied for table {t}" not in r.stderr:
            wrong.append((t, (r.stderr or "it succeeded").strip().splitlines()[-1][:120]))
    assert not wrong, f"{verb} was not refused by the privilege on: {wrong}"


@_NEEDS_PG
def test_the_rollback_gives_the_grants_back_so_each_refusal_above_was_the_privilege(db):
    assert _psql(db, ROLLBACK.read_text(encoding="utf-8")).returncode == 0
    assert _writable_by_a_signed_in_role(db) >= {"workflow_templates", "workflow_instances"}, \
        "the rollback did not restore the write grants"
    for t in sorted(_present(db)):
        r = _as_manager(db, VERBS["INSERT"].format(t=t))
        assert f"permission denied for table {t}" not in r.stderr, (
            f"{t}: still refused by the privilege after the rollback: {r.stderr.strip()[:160]}")
    assert _psql(db, MIGRATION.read_text(encoding="utf-8")).returncode == 0
    assert _writable_by_a_signed_in_role(db) == set(), "the migration did not revoke again after the rollback"


@_NEEDS_PG
def test_the_migration_is_idempotent_and_leaves_the_policies_alone(db):
    def policies() -> str:
        return _ok(db, "SELECT string_agg(tablename || ':' || policyname || ':' || cmd || ':' || permissive, ',' "
                       "ORDER BY tablename, policyname) FROM pg_policies WHERE schemaname='public' "
                       "AND tablename LIKE 'workflow%';")
    before = policies()
    assert before, "no workflow policy to compare: the check would be vacuous"
    assert _psql(db, MIGRATION.read_text(encoding="utf-8")).returncode == 0
    assert policies() == before
    assert _writable_by_a_signed_in_role(db) == set()
