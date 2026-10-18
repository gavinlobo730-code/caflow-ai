"""Migration 507 — a signed-in session writes none of the insight and memory tables (ledger POST-A-257).

THE RULE
    `ai_insights` and the memory repository's tables (`ai_memory_triggers`, `client_profiles`, `client_profile_history`,
    `firm_profiles`, `year_end_reports`, `pattern_anomalies`) are written by the API with the privileged client, never from a
    signed-in session: no screen in `apps/web` touches them, and a write from a member's own session could change another
    member's insight status, resolve a trigger, rewrite a client's compliance profile or plant a report. Migration 507
    revokes INSERT, UPDATE, DELETE and TRUNCATE from `authenticated`, `anon` and PUBLIC on the seven; the row policies stay
    as the second lock. (Migration 505 did the same for the seven copilot tables.)

WHAT IS HELD
    * (no database) no file in `apps/web` names any of the seven tables in code;
    * (database) a signed-in role effectively holds NO write privilege (table level, column level or through PUBLIC) on any of
      the seven, and `service_role`, which the API uses, keeps INSERT, UPDATE and DELETE on all of them;
    * (database) a Manager who belongs to the firm and is assigned to the client is refused a direct insert by the PRIVILEGE
      ("permission denied for table <the table>") on each of the seven, and an update of an existing row too; reading is
      unaffected;
    * (database) the migration REMOVES what the hosting platform's defaults give (TRUNCATE for `authenticated` and `anon`,
      and a write through PUBLIC or a column grant), its closing check fails the migration when a write cannot be revoked,
      it is idempotent, and its own rollback puts the grants back on the six tables that ever had them (the negative
      control: every statement refused above then goes through, so each refusal was the privilege and not a malformed
      statement; `pattern_anomalies` was granted SELECT alone, so it has no write to put back and is only asserted).

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
_STEM = "507_a_signed_in_session_writes_none_of_the_insight_and_memory_tables"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

AI_TABLES = ("ai_insights", "ai_memory_triggers", "client_profiles", "client_profile_history", "firm_profiles",
             "year_end_reports", "pattern_anomalies")
#: The tables migration 507's rollback gives a write back on (every one of them but `pattern_anomalies`).
HAD_A_WRITE = tuple(t for t in AI_TABLES if t != "pattern_anomalies")

_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the insight and memory write-privilege proofs require HARNESS_PG + psql",
)


# ── no database ────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_browser_writes_none_of_the_seven_tables():
    """The ai-insights screen READS `ai_insights` over PostgREST (the `select` grant stays); nothing in `apps/web` writes any
    of the seven. A screen that starts to has to decide, in the open, instead of finding the privilege already gone."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_direct_write_tables_are_role_guarded import _direct_write_tables
    found = {t for t in _direct_write_tables() if t in AI_TABLES}
    assert found == set(), f"a screen writes an insight or memory table directly: {sorted(found)}"


def test_the_migration_names_the_seven_tables_and_the_test_agrees():
    import re
    sql = MIGRATION.read_text(encoding="utf-8")
    block = sql.split("tables text[] := ARRAY[", 1)[1].split("]", 1)[0]
    assert tuple(re.findall(r"'([a-z_]+)'", block)) == AI_TABLES


# ── the database ───────────────────────────────────────────────────────────────────────────────────────────────────────
FIRM = "aaaaaaaa-0000-0000-0000-000000000507"
CLIENT = "cccccccc-0000-0000-0000-00000000a507"
MANAGER_AUTH = "11111111-1111-1111-1111-000000000507"
MANAGER_USER = "bbbbbbbb-1111-1111-1111-000000000507"


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _present(dsn: str) -> set[str]:
    """The tables of the seven that exist in THIS database. Migration 070 creates `ai_memory_triggers`, `pattern_anomalies` and
    `year_end_reports` and is on the runner's `BASELINE_FAILURES` list, so a database built from scratch has the other four
    only; production has all seven. The migration asks `to_regclass` for each and this test follows it."""
    have = set(_ok(dsn, "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace "
                        "AND relkind = 'r';").splitlines())
    return {t for t in AI_TABLES if t in have}


def _as_manager(dsn: str, sql: str) -> subprocess.CompletedProcess:
    claims = json.dumps({"sub": MANAGER_AUTH, "role": "authenticated"})
    return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"memwrite_m507_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{MANAGER_AUTH}', 'manager@m507.test');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M507 Firm','m507@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{MANAGER_USER}', '{FIRM}', '{MANAGER_AUTH}', 'manager@m507.test', 'M', 'Manager', true);
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','Client A','Private Limited');
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES ('{FIRM}', '{MANAGER_USER}', '{CLIENT}');
            INSERT INTO ai_insights (id, firm_id, client_id, insight_type, severity, title, description)
                 VALUES ('dddddddd-0000-0000-0000-000000000507', '{FIRM}', '{CLIENT}', 'OTHER', 'low', 't', 'd');
            INSERT INTO client_profiles (id, firm_id, client_id, profile_version, is_current)
                 VALUES ('eeeeeeee-0000-0000-0000-000000000507', '{FIRM}', '{CLIENT}', 1, false);
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _writable_by_a_signed_in_role(dsn: str) -> set[str]:
    """Tables of the seven on which `authenticated` or `anon` EFFECTIVELY holds a write privilege: table level, column level,
    or through PUBLIC (has_table_privilege / has_any_column_privilege see all three)."""
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
def test_the_tables_a_scratch_database_has_are_the_four_and_the_rule_is_not_vacuous(db):
    assert _present(db) >= {"ai_insights", "client_profiles", "client_profile_history", "firm_profiles"}, _present(db)


@_NEEDS_PG
def test_no_signed_in_role_holds_a_write_on_any_of_them(db):
    assert _writable_by_a_signed_in_role(db) == set(), sorted(_writable_by_a_signed_in_role(db))


@_NEEDS_PG
def test_the_api_keeps_its_write_privileges_on_every_one_of_them(db):
    lacking = [f"{t}:{v}" for t in sorted(_present(db)) for v in ("INSERT", "UPDATE", "DELETE")
               if _ok(db, f"SELECT has_table_privilege('service_role', 'public.{t}', '{v}');") != "t"]
    assert not lacking, f"service_role lacks a write privilege the API needs: {lacking}"


PROBES = {
    "ai_insights": ("INSERT INTO ai_insights (firm_id, client_id, insight_type, severity, title, description) "
                    "VALUES ('{f}', '{c}', 'OTHER', 'low', 't', 'd');"),
    "ai_memory_triggers": ("INSERT INTO ai_memory_triggers (firm_id, trigger_type, title, what_detected, "
                           "why_it_matters, recommended_action) VALUES ('{f}', 'repeat_issue', 't', 'w', 'y', 'a');"),
    "client_profiles": "INSERT INTO client_profiles (firm_id, client_id, profile_version, is_current) VALUES ('{f}', '{c}', 2, true);",
    "client_profile_history": ("INSERT INTO client_profile_history (firm_id, client_id, profile_id, profile_version, snapshot) "
                               "VALUES ('{f}', '{c}', 'eeeeeeee-0000-0000-0000-000000000507', 1, '{{}}');"),
    "firm_profiles": "INSERT INTO firm_profiles (firm_id) VALUES ('{f}');",
    "year_end_reports": "INSERT INTO year_end_reports (firm_id, client_id, financial_year) VALUES ('{f}', '{c}', '2025-26');",
    "pattern_anomalies": ("INSERT INTO pattern_anomalies (firm_id, client_id, anomaly_type, metric_name, period) "
                          "VALUES ('{f}', '{c}', 'late_filing', 'm', '2026-09');"),
}


def test_there_is_a_probe_for_every_table():
    assert set(PROBES) == set(AI_TABLES)


@_NEEDS_PG
@pytest.mark.parametrize("table", AI_TABLES)
def test_an_assigned_manager_of_the_firm_is_refused_by_the_privilege(db, table):
    if table not in _present(db):
        pytest.skip(f"{table} is not built by the migration chain on a scratch database (migration 070 stops part-way)")
    r = _as_manager(db, PROBES[table].format(f=FIRM, c=CLIENT))
    assert r.returncode != 0 and f"permission denied for table {table}" in r.stderr, (
        f"{table}: a signed-in Manager wrote the table directly: {r.stderr or 'it succeeded'}")


@_NEEDS_PG
def test_an_existing_insight_cannot_be_changed_directly_either(db):
    r = _as_manager(db, "UPDATE ai_insights SET status = 'dismissed' WHERE id = 'dddddddd-0000-0000-0000-000000000507';")
    assert r.returncode != 0 and "permission denied for table ai_insights" in r.stderr, r.stderr
    assert _ok(db, "SELECT status FROM ai_insights WHERE id = 'dddddddd-0000-0000-0000-000000000507';") == "open"


@_NEEDS_PG
def test_reading_is_unaffected(db):
    r = _as_manager(db, "SELECT count(*) FROM ai_insights;")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "1"


@_NEEDS_PG
def test_507_removes_what_the_hosting_platform_grants_and_what_reaches_a_role_another_way(db):
    _ok(db, """
        GRANT TRUNCATE, REFERENCES, TRIGGER ON public.ai_insights, public.client_profiles TO authenticated, anon;
        GRANT INSERT, UPDATE, DELETE, TRUNCATE ON public.client_profile_history TO anon;
        GRANT INSERT ON public.firm_profiles TO PUBLIC;
        GRANT UPDATE (status) ON public.ai_insights TO authenticated;
    """)
    before = _writable_by_a_signed_in_role(db)
    assert {"ai_insights", "client_profiles", "client_profile_history", "firm_profiles"} <= before, before
    r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    assert _writable_by_a_signed_in_role(db) == set()
    assert _ok(db, "SELECT has_table_privilege('anon', 'public.client_profiles', 'REFERENCES');") == "t"


@_NEEDS_PG
def test_the_closing_check_fails_the_migration_when_a_write_cannot_be_revoked(db):
    grantor = f"m507_g_{uuid.uuid4().hex[:8]}"
    _ok(db, f"""
        CREATE ROLE {grantor} NOLOGIN;
        GRANT INSERT ON public.firm_profiles TO {grantor} WITH GRANT OPTION;
        SET ROLE {grantor};
        GRANT INSERT ON public.firm_profiles TO authenticated;
        RESET ROLE;
    """)
    try:
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
        assert r.returncode != 0 and "migration 507: authenticated still holds INSERT on firm_profiles" in r.stderr, (
            r.stdout, r.stderr)
    finally:
        _psql(db, f"DROP OWNED BY {grantor}; DROP ROLE IF EXISTS {grantor};")


@_NEEDS_PG
def test_507_is_idempotent(db):
    for _ in range(2):
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
        assert r.returncode == 0, r.stderr
    assert _writable_by_a_signed_in_role(db) == set()


@_NEEDS_PG
def test_its_own_rollback_puts_the_grants_back_and_the_refused_statements_go_through(db):
    """The negative control: with the grants back, every probe above goes through for the Manager (so each refusal was the
    privilege and not a malformed statement). `pattern_anomalies` never had a write granted, so it stays refused."""
    r = _psql(db, ROLLBACK.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    present = _present(db)
    assert _writable_by_a_signed_in_role(db) == {t for t in HAD_A_WRITE if t in present}
    for table in sorted(t for t in HAD_A_WRITE if t in present):
        again = _as_manager(db, PROBES[table].format(f=FIRM, c=CLIENT))
        assert again.returncode == 0, (table, again.stderr)
    if "pattern_anomalies" in present:
        still = _as_manager(db, PROBES["pattern_anomalies"].format(f=FIRM, c=CLIENT))
        assert still.returncode != 0 and "permission denied for table pattern_anomalies" in still.stderr
