"""Migration 562 — seventeen firm-level tables are written by the API only (ledger POST-A-329).

WHAT WAS WRONG
    The writer map of 22-10-2026 found tables the API wrote on the caller's own session behind a role lower than their data deserves,
    with no tier at the database: a member who could only READ wrote them over PostgREST (read from production on 29-10-2026:
    `authenticated` held INSERT and UPDATE on all seventeen and DELETE on sixteen). The browser touches none of them.

WHAT THIS HOLDS (real Postgres)
    * THE PRIVILEGES: a signed-in role effectively holds no INSERT, UPDATE, DELETE or TRUNCATE on the seventeen (table level, column
      level, or through PUBLIC), still SELECTs, and the service role keeps its writes. `fx_rates` is not this migration's.
    * AN ASSIGNED MANAGER is refused an INSERT, an UPDATE and a DELETE of each table BY THE PRIVILEGE ("permission denied for table
      <the table>"), and still reads each one. The statements match no row, so the refusal can only be the privilege.
    * THE SERVICE ROLE, which the API's privileged client uses, runs the same three statements.
    * THE WORST CASE: a database that granted everything to PUBLIC, anon and authenticated (a write through a column grant included)
      and then applied the migration holds none of it after; a grant the owner cannot take back fails the migration in its own words.
    * IT IS IDEMPOTENT, and its own rollback gives the verbs production held back, so the refusals above go through (the negative
      control); `firm_hsn_rate_history` never held DELETE for the signed-in role and the rollback does not invent it.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
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
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

_STEM = "562_seventeen_firm_level_tables_are_written_by_the_api_only"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"

SEVENTEEN = ("account_group_mappings", "firm_hsn_library", "firm_hsn_rate_history", "assignment_rules", "entities",
             "entity_relationships", "entity_to_entity_relationships", "leads", "dsc_records", "automation_rules",
             "automation_executions", "reminder_settings", "engagement_templates", "recurring_invoice_templates",
             "recurring_purchase_bill_templates", "recurring_journal_templates", "task_escalations")
#: Never held DELETE for the signed-in role in production, so the rollback does not give it.
NEVER_DELETABLE = {"firm_hsn_rate_history"}
WRITES = ("INSERT", "UPDATE", "DELETE")

FIRM = "56200000-0000-0000-0000-000000000001"
CLIENT = "56200000-0000-0000-0000-0000000000a1"
MANAGER_AUTH = "56200000-1111-0000-0000-000000000001"
MANAGER_USER = "56200000-0000-0000-0000-00000000000b"

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the closed-firm-table privilege proof requires HARNESS_PG + psql",
)


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-f", "-"],
                          input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _as(role: str, sql: str, dsn: str) -> subprocess.CompletedProcess:
    if role == "authenticated":
        claims = json.dumps({"sub": MANAGER_AUTH, "role": "authenticated"})
        return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")
    return _psql(dsn, f"SET ROLE {role}; {sql}")


def _present(dsn: str) -> list[str]:
    """The listed tables that exist in this database. A table that production has and the migrations do not build (`assignment_rules`
    is one: migration 045 does not leave it in a database built from scratch) is skipped by the checks and passed over by the migration."""
    return [t for t in SEVENTEEN if _ok(dsn, f"SELECT to_regclass('public.{t}') IS NOT NULL;") == "t"]


def _first_column(dsn: str, table: str) -> str:
    return _ok(dsn, f"SELECT attname FROM pg_attribute WHERE attrelid = 'public.{table}'::regclass AND attnum > 0 "
                    "AND NOT attisdropped ORDER BY attnum LIMIT 1;")


def _statement(dsn: str, table: str, verb: str) -> str:
    """A statement of the given verb that names the table and matches NO row, so a refusal can only be the privilege: the
    privilege check of a statement happens before it looks at a row, and a statement that matches none cannot meet a constraint,
    a trigger or a row policy."""
    col = _first_column(dsn, table)
    return {
        "INSERT": f"INSERT INTO public.{table} ({col}) SELECT {col} FROM public.{table} WHERE false;",
        "UPDATE": f"UPDATE public.{table} SET {col} = {col} WHERE false;",
        "DELETE": f"DELETE FROM public.{table} WHERE false;",
    }[verb]


def _effective_writes(dsn: str) -> set[str]:
    """`table:ROLE:VERB` for every write a signed-in role EFFECTIVELY holds on the seventeen: at table level, at column level, or
    through PUBLIC (has_table_privilege and has_any_column_privilege see all three; role_table_grants sees only the first)."""
    rows = _ok(dsn, f"""
        SELECT c.relname || ':' || r.name || ':' || v.verb
          FROM unnest(ARRAY[{', '.join(repr(t) for t in _present(dsn))}]) AS c(relname)
          CROSS JOIN (VALUES ('authenticated'), ('anon')) AS r(name)
          CROSS JOIN (VALUES ('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE')) AS v(verb)
         WHERE has_table_privilege(r.name, 'public.' || c.relname, v.verb)
            OR (v.verb IN ('INSERT', 'UPDATE') AND has_any_column_privilege(r.name, 'public.' || c.relname, v.verb));""")
    return set(rows.splitlines())


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m562_{uuid.uuid4().hex[:10]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{MANAGER_AUTH}', 'manager@m562.test');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'M562 Firm', 'm562@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{MANAGER_USER}', '{FIRM}', '{MANAGER_AUTH}', 'manager@m562.test', 'M', 'Manager', true);
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}', '{FIRM}', 'Client A', 'Private Limited');
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES ('{FIRM}', '{MANAGER_USER}', '{CLIENT}');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── no database: the file names exactly the seventeen ──────────────────────────────────────────────────────────────────
def test_the_migration_names_exactly_the_seventeen_tables_and_not_fx_rates():
    sql = MIGRATION.read_text(encoding="utf-8")
    named = set(re.findall(r"'([a-z_]+)'", sql.split("tables text[] := ARRAY[", 1)[1].split("]", 1)[0]))
    assert named == set(SEVENTEEN), sorted(named ^ set(SEVENTEEN))
    assert "fx_rates" not in named, "fx_rates has its own policies and writer (migration 470); this migration must not claim it"


# ── the privileges ────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_signed_in_role_holds_no_write_on_the_seventeen_and_still_reads_them(db):
    assert _effective_writes(db) == set()
    for t in _present(db):
        assert _ok(db, f"SELECT has_table_privilege('authenticated', 'public.{t}', 'SELECT');") == "t", t


def test_the_service_role_keeps_its_writes_on_the_seventeen(db):
    for t in _present(db):
        for verb in WRITES:
            assert _ok(db, f"SELECT has_table_privilege('service_role', 'public.{t}', '{verb}');") == "t", (t, verb)


@pytest.mark.parametrize("table", SEVENTEEN)
@pytest.mark.parametrize("verb", WRITES)
def test_an_assigned_manager_is_refused_by_the_privilege(db, table, verb):
    if table not in _present(db):
        pytest.skip(f"{table} is not built by the migrations")
    r = _as("authenticated", _statement(db, table, verb), db)
    assert r.returncode != 0 and f"permission denied for table {table}" in r.stderr, (
        f"{verb} {table}: a signed-in Manager was not refused by the privilege: {r.stderr or 'it succeeded'}")


@pytest.mark.parametrize("table", SEVENTEEN)
def test_an_assigned_manager_still_reads_each_table(db, table):
    if table not in _present(db):
        pytest.skip(f"{table} is not built by the migrations")
    r = _as("authenticated", f"SELECT count(*) FROM public.{table};", db)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("table", SEVENTEEN)
@pytest.mark.parametrize("verb", WRITES)
def test_the_service_role_runs_the_same_statement(db, table, verb):
    if table not in _present(db):
        pytest.skip(f"{table} is not built by the migrations")
    r = _as("service_role", _statement(db, table, verb), db)
    assert r.returncode == 0, f"{verb} {table}: the API's privileged client was refused: {r.stderr}"


# ── the worst case, the closing check, idempotence, the rollback ──────────────────────────────────────────────────
def test_what_the_platform_grants_and_what_reaches_a_role_another_way_is_removed(db):
    """The throwaway database holds none of the platform's default privileges, so the TRUNCATE half, the `anon` half, a write
    through PUBLIC and one through a column grant are each given first, then the migration is applied."""
    _ok(db, """
        GRANT INSERT, UPDATE, DELETE, TRUNCATE ON public.leads, public.dsc_records, public.entities TO authenticated, anon;
        GRANT TRUNCATE ON public.automation_rules, public.reminder_settings TO authenticated;
        GRANT INSERT ON public.firm_hsn_library TO PUBLIC;
        GRANT UPDATE (id) ON public.engagement_templates TO authenticated;
    """)
    before = {t.split(":")[0] for t in _effective_writes(db)}
    assert before == {"leads", "dsc_records", "entities", "automation_rules", "reminder_settings", "firm_hsn_library",
                      "engagement_templates"}, before
    r = _psql(db, MIGRATION.read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    assert _effective_writes(db) == set()


def test_the_closing_check_fails_the_migration_when_a_write_cannot_be_revoked(db):
    """A privilege the migration's own REVOKE cannot remove must fail the migration and not let it finish green with a table
    still writable. The REVOKE removes what the OWNER granted; a grant made by a role holding GRANT OPTION is not the owner's."""
    grantor = f"m562_g_{uuid.uuid4().hex[:8]}"
    _ok(db, f"""
        CREATE ROLE {grantor} NOLOGIN;
        GRANT INSERT ON public.leads TO {grantor} WITH GRANT OPTION;
        SET ROLE {grantor};
        GRANT INSERT ON public.leads TO authenticated;
        RESET ROLE;
    """)
    try:
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"))
        assert r.returncode != 0 and "migration 562: authenticated still holds INSERT on leads" in r.stderr, (
            r.stdout, r.stderr)
    finally:
        _psql(db, f"DROP OWNED BY {grantor}; DROP ROLE IF EXISTS {grantor};")


def test_562_is_idempotent(db):
    for _ in range(2):
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"))
        assert r.returncode == 0, r.stderr
    assert _effective_writes(db) == set()


def test_its_own_rollback_gives_the_verbs_back_and_the_refusals_stop(db):
    """The negative control: without the revoke the very statements refused above go through."""
    r = _psql(db, ROLLBACK.read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    reopened = {t.split(":")[0] for t in _effective_writes(db)}
    assert reopened == set(_present(db)), sorted(set(_present(db)) ^ reopened)
    for table in _present(db):
        for verb in WRITES:
            again = _as("authenticated", _statement(db, table, verb), db)
            if verb == "DELETE" and table in NEVER_DELETABLE:
                assert again.returncode != 0, (table, "the rollback invented a DELETE production never granted")
            else:
                assert again.returncode == 0, (table, verb, again.stderr)
