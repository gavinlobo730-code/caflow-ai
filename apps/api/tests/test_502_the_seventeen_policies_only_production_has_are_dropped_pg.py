"""Migration 502 — the seventeen `firm_iso_*` policies that only production has are dropped (ledger POST-A-015).

A database built from the migrations never had them (migration 319 deliberately declared none), so the proof recreates them
from the rollback file, which holds production's exact predicates as read from its catalogue on 17-10-2026, and then applies
the migration. Two of the seventeen tables, `workflow_conditions` and `workflow_triggers`, exist in production and NOT in a
database built from the migrations; the fixture creates them (row security on, no policy, as migration 062 declares them) so
every path is exercised.

WHAT IS HELD
    * a migration-built database has none, and the rollback recreates exactly seventeen: seven `firm_iso_ai_*` and ten
      `firm_iso_wf_*`, PERMISSIVE and for every command;
    * applying 502 over them leaves every table with exactly the policies a migration-built database gives it (so no table
      loses its real firm-isolation policy, and `workflow_conditions` and `workflow_triggers`, which migration 062 declares
      fail-closed, end with none);
    * WHAT THE TRAP WAS: while one of them exists, a session that sets `app.current_firm_id` to ANOTHER firm's id and signs in
      as an ordinary member reads that firm's rows through it; after 502 it does not;
    * the closing check fails the migration when a `firm_iso_*` policy it does not know is left, and the migration is
      idempotent.

Runs only when HARNESS_PG is set + psql on PATH.
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
_STEM = "502_the_seventeen_policies_only_production_has_are_dropped"
MIGRATION = API_ROOT / "migrations" / f"{_STEM}.sql"
ROLLBACK = API_ROOT / "migrations" / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the policy-drop proofs require HARNESS_PG + psql",
)

AI = ["ai_actions", "ai_context_windows", "ai_conversations", "ai_feedback", "ai_messages", "ai_recommendations",
      "ai_summaries"]
WF = ["workflow_action_logs", "workflow_approvals", "workflow_conditions", "workflow_executions", "workflow_failures",
      "workflow_instances", "workflow_schedules", "workflow_steps", "workflow_templates", "workflow_triggers"]
FIRM1, FIRM2 = "aaaaaaaa-0000-0000-0000-000000000502", "aaaaaaaa-0000-0000-0000-000000000512"
MEMBER_AUTH = "11111111-1111-1111-1111-000000000502"


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _policies(dsn: str, tables: list[str]) -> list[str]:
    names = ",".join(f"'{t}'" for t in tables)
    return _ok(dsn, f"SELECT tablename || '.' || policyname FROM pg_policies WHERE schemaname = 'public' "
                    f"AND tablename IN ({names}) ORDER BY 1;").splitlines()


def _firm_iso(dsn: str) -> list[str]:
    return _ok(dsn, "SELECT tablename || '.' || policyname FROM pg_policies WHERE schemaname = 'public' "
                    "AND policyname LIKE 'firm\\_iso\\_%' ORDER BY 1;").splitlines()


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"fi_m502_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        _ok(dsn, """
            CREATE TABLE IF NOT EXISTS public.workflow_triggers (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), template_id uuid);
            CREATE TABLE IF NOT EXISTS public.workflow_conditions (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), step_id uuid);
            ALTER TABLE public.workflow_triggers ENABLE ROW LEVEL SECURITY;
            ALTER TABLE public.workflow_conditions ENABLE ROW LEVEL SECURITY;
        """)
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _put_production_back(dsn: str) -> None:
    r = _psql(dsn, ROLLBACK.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr


def test_a_database_built_from_the_migrations_has_none_of_them(db):
    assert _firm_iso(db) == []


def test_the_rollback_names_all_seventeen_and_recreates_exactly_them(db):
    text = ROLLBACK.read_text(encoding="utf-8")
    assert sorted(set(re.findall(r"'(firm_iso_[a-z_]+)'", text))) == sorted(
        [f"firm_iso_{t}" for t in AI] + ["firm_iso_wf_" + n for n in (
            "action_logs", "approvals", "conditions", "executions", "failures", "instances", "schedules", "steps",
            "templates", "triggers")])
    _put_production_back(db)
    assert sorted(_firm_iso(db)) == sorted([f"{t}.firm_iso_{t}" for t in AI] + [
        "workflow_action_logs.firm_iso_wf_action_logs", "workflow_approvals.firm_iso_wf_approvals",
        "workflow_conditions.firm_iso_wf_conditions", "workflow_executions.firm_iso_wf_executions",
        "workflow_failures.firm_iso_wf_failures", "workflow_instances.firm_iso_wf_instances",
        "workflow_schedules.firm_iso_wf_schedules", "workflow_steps.firm_iso_wf_steps",
        "workflow_templates.firm_iso_wf_templates", "workflow_triggers.firm_iso_wf_triggers"])
    assert _ok(db, "SELECT count(*) FROM pg_policies WHERE schemaname = 'public' AND policyname LIKE 'firm\\_iso\\_%' "
                   "AND permissive = 'PERMISSIVE' AND cmd = 'ALL';") == "17"


def test_dropping_them_leaves_every_table_with_exactly_the_policies_the_migrations_give_it(db):
    before = sorted(_policies(db, AI + WF))
    _put_production_back(db)
    assert sorted(_policies(db, AI + WF)) != before
    r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    assert sorted(_policies(db, AI + WF)) == before, "502 changed a policy that is not one of the seventeen"
    # the two child tables migration 062 declares fail-closed end with no policy at all
    assert [p for p in before if p.startswith(("workflow_conditions.", "workflow_triggers."))] == []


def test_the_trap_a_setting_nothing_sets_admits_another_firms_rows_until_502(db):
    """With one of them in place, any signed-in member who can cause `app.current_firm_id` to be set reads that firm's rows."""
    _ok(db, f"""
        INSERT INTO auth.users (id, email) VALUES ('{MEMBER_AUTH}', 'm@m502.test');
        INSERT INTO firms (id, name, email) VALUES ('{FIRM1}','M502 One','a@m502.test'), ('{FIRM2}','M502 Two','b@m502.test');
        INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
          VALUES (gen_random_uuid(), '{FIRM1}', '{MEMBER_AUTH}', 'm@m502.test', 'M', 'Partner', true);
        INSERT INTO ai_actions (firm_id, action_type) VALUES ('{FIRM2}', 'other-firm-action');
    """)
    claims = json.dumps({"sub": MEMBER_AUTH, "role": "authenticated"})

    def other_firms_rows() -> str:
        r = _psql(db, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; "
                      f"SET app.current_firm_id = '{FIRM2}'; SELECT count(*) FROM ai_actions;")
        assert r.returncode == 0, r.stderr
        return r.stdout.strip().splitlines()[-1]

    assert other_firms_rows() == "0"                      # a migration-built database: no such policy
    _put_production_back(db)
    assert other_firms_rows() == "1", "the production-only policy should admit the other firm's row"
    r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    assert other_firms_rows() == "0"


def test_the_closing_check_fails_when_a_firm_iso_policy_it_does_not_know_is_left(db):
    _ok(db, "CREATE POLICY firm_iso_something_new ON public.ai_summaries FOR ALL "
            "USING (firm_id = (current_setting('app.current_firm_id', true))::uuid);")
    r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode != 0 and "migration 502: firm_iso policies are still in place: ai_summaries.firm_iso_something_new" \
        in r.stderr, (r.stdout, r.stderr)


def test_502_is_idempotent(db):
    _put_production_back(db)
    for _ in range(2):
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
        assert r.returncode == 0, r.stderr
    assert _firm_iso(db) == []
