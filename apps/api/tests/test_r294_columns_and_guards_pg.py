"""
Migration 294 — the columns production lacks, and the RLS guards that follow.

WHAT THIS PROVES, AND WHY IT HAS TO REBUILD PRODUCTION'S SHAPE FIRST

The session template already has 294 applied, so introspecting it proves
nothing: every column and policy this migration adds is already there. What
matters is what 294 does to a database shaped like PRODUCTION, where those
columns and policies are absent. So the fixture drops them first.

THE FOUR FEATURES THIS FIXES

Each is a column the migrations declare, production does not have, and the code
writes on every call — so the write is rejected there while every check here
passes, exactly as form_26as_uploads.uploaded_by was:

    year_end_adjustments.client_id           routers/year_end_adjustments.py:201
    financial_statement_versions.statement_data  routers/year_end_statements.py:149
    account_group_mappings.statement_type / account_name
                                             routers/year_end_mappings.py:348-349
    filings.firm_id                          services/gst_filing_record_service.py

The last is the worst. public.filings is what journal_period_lock_reason reads
(migrations 266 and 267), so a filings row that is never written is a period
that never locks — entries stay editable after the return covering them has
been filed. test_recording_a_filing_succeeds performs that exact insert.

THE EIGHT RESTRICTIVE POLICIES

Missing from production, not because anyone dropped them, but because 074 and
084 build them with one-shot loops over the tables that carried a client_id at
the moment they ran. A table repaired later gains its client_id afterwards and
is never revisited. 294 re-runs both loops, so the fix is the loops themselves
rather than eight hand-written policies — and it keeps working for the next
table.

A permissive policy GRANTS, so a missing one only narrows access. A missing
RESTRICTIVE one removes a check. Only the restrictive ones are asserted here.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = API_ROOT / "migrations" / "294_declare_the_columns_production_lacks_and_restore_the_guards.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not MIGRATION.exists(),
    reason="migration 294 proof requires HARNESS_PG + psql",
)

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
ENGAGEMENT = "33333333-3333-3333-3333-333333333333"

# Every column 294 adds, as (table, column). Written out rather than parsed from
# the .sql so that deleting a line from the migration fails here instead of
# quietly shrinking what is checked.
ADDED_COLUMNS = [
    ("account_group_mappings", "account_name"), ("account_group_mappings", "is_active"),
    ("account_group_mappings", "sequence_no"), ("account_group_mappings", "statement_type"),
    ("account_group_mappings", "sub_line"),
    ("automation_executions", "firm_id"),
    ("client_profiles", "last_updated_at"), ("client_profiles", "profile_data"),
    ("client_profiles", "segment"), ("client_profiles", "tags"),
    ("filings", "firm_id"),
    ("financial_statement_versions", "change_reason"),
    ("financial_statement_versions", "statement_data"),
    ("firm_profiles", "last_updated_at"), ("firm_profiles", "profile_data"),
    ("firm_profiles", "settings"),
    ("permission_grants", "firm_id"),
    ("workflow_steps", "default_assignee_role"), ("workflow_steps", "estimated_hours"),
    ("workflow_steps", "required"), ("workflow_steps", "step_description"),
    ("workflow_steps", "step_name"), ("workflow_steps", "workflow_id"),
    ("year_end_adjustments", "client_id"), ("year_end_adjustments", "reviewed_at"),
    ("year_end_adjustments", "reviewed_by"),
    ("year_end_engagements", "prepared_at"), ("year_end_engagements", "prepared_by"),
    ("year_end_engagements", "reviewed_at"), ("year_end_engagements", "reviewed_by"),
    ("year_end_exports", "version_id"),
]

# The eight RESTRICTIVE policies production is missing, on tables it has.
RESTRICTIVE_POLICIES = [
    ("client_health_overrides", "client_health_overrides_assignment_scope"),
    ("client_health_scores", "client_health_scores_assignment_scope"),
    ("government_notices", "government_notices_assignment_scope"),
    ("government_notices", "government_notices_internal_partner_only"),
    ("gstr2b_uploads", "gstr2b_uploads_assignment_scope"),
    ("gstr2b_uploads", "gstr2b_uploads_internal_partner_only"),
    ("portal_messages", "portal_messages_assignment_scope"),
    ("year_end_adjustments", "year_end_adjustments_assignment_scope"),
]

# CASCADE because a policy or index may reference the column; production's shape
# is "column absent", however it got that way.
_TO_PRODUCTION_SHAPE = "\n".join(
    [f"DROP POLICY IF EXISTS {p} ON public.{t};" for t, p in RESTRICTIVE_POLICIES]
    + [f"ALTER TABLE public.{t} DROP COLUMN IF EXISTS {c} CASCADE;" for t, c in ADDED_COLUMNS]
)

_SEED = f"""
INSERT INTO public.firms (id, name, email)
VALUES ('{FIRM}', 'Repro Firm', 'repro@example.test');
INSERT INTO public.clients (id, firm_id, client_name, entity_type, pan)
VALUES ('{CLIENT}', '{FIRM}', 'Repro Client', 'Private Limited', 'AAAAA9999A');
-- year_end_adjustments.engagement_id is a FK; the adjustment tests need a parent.
INSERT INTO public.year_end_engagements
  (id, firm_id, client_id, financial_year, fy_start, fy_end, created_by)
VALUES ('{ENGAGEMENT}', '{FIRM}', '{CLIENT}', '2025-26', '2025-04-01', '2026-03-31',
        gen_random_uuid());
"""


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _apply(dsn: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-f", str(MIGRATION)],
        capture_output=True, text=True)


@pytest.fixture()
def production_shaped(pg_template):
    admin = _ADMIN.strip()
    dbname = f"r294_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        undo = _psql(dsn, _TO_PRODUCTION_SHAPE)
        assert undo.returncode == 0, undo.stderr
        seed = _psql(dsn, _SEED)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _columns(dsn: str) -> set:
    r = _psql(dsn, "SELECT table_name||'.'||column_name FROM information_schema.columns "
                   "WHERE table_schema='public';", tuples=True)
    assert r.returncode == 0, r.stderr
    return set(r.stdout.split())


def _restrictive(dsn: str) -> set:
    r = _psql(dsn, "SELECT c.relname||'.'||p.polname FROM pg_policy p "
                   "JOIN pg_class c ON c.oid=p.polrelid "
                   "JOIN pg_namespace n ON n.oid=c.relnamespace "
                   "WHERE n.nspname='public' AND NOT p.polpermissive;", tuples=True)
    assert r.returncode == 0, r.stderr
    return set(r.stdout.split())


# ── the negative controls, kept as tests ─────────────────────────────────────

def test_the_four_writes_really_do_fail_before_294(production_shaped):
    """Without this migration the columns are absent, so the inserts the code
    actually performs are rejected. This is the production behaviour today; if
    it ever stops failing, 294 is no longer load-bearing and should go."""
    for tbl, col in [("year_end_adjustments", "client_id"),
                     ("financial_statement_versions", "statement_data"),
                     ("account_group_mappings", "statement_type"),
                     ("filings", "firm_id")]:
        r = _psql(production_shaped, f"SELECT {col} FROM public.{tbl} LIMIT 1;")
        assert r.returncode != 0, f"{tbl}.{col} still present; the fixture did not reproduce production"
        assert "does not exist" in r.stderr, r.stderr


def test_the_eight_restrictive_policies_are_absent_before_294(production_shaped):
    present = _restrictive(production_shaped)
    still_there = [f"{t}.{p}" for t, p in RESTRICTIVE_POLICIES if f"{t}.{p}" in present]
    assert not still_there, still_there


# ── what 294 does ────────────────────────────────────────────────────────────

def test_every_column_is_added(production_shaped):
    run = _apply(production_shaped)
    assert run.returncode == 0, run.stderr
    cols = _columns(production_shaped)
    missing = [f"{t}.{c}" for t, c in ADDED_COLUMNS if f"{t}.{c}" not in cols]
    assert not missing, "\n  ".join(["294 did not add these columns:"] + missing)


def test_recording_a_filing_succeeds(production_shaped):
    """The period-lock path. services/gst_filing_record_service builds a row
    carrying firm_id; public.filings is what journal_period_lock_reason reads,
    so this insert failing is a period that never locks."""
    before = _psql(production_shaped,
                   f"INSERT INTO public.filings (id, firm_id, client_id, filing_type, "
                   f"period_start, period_end) VALUES (gen_random_uuid(), '{FIRM}', "
                   f"'{CLIENT}', 'GSTR3B', '2026-04-01', '2026-04-30');")
    assert before.returncode != 0 and "does not exist" in before.stderr, before.stderr

    assert _apply(production_shaped).returncode == 0
    after = _psql(production_shaped,
                  f"INSERT INTO public.filings (id, firm_id, client_id, filing_type, "
                  f"period_start, period_end) VALUES (gen_random_uuid(), '{FIRM}', "
                  f"'{CLIENT}', 'GSTR3B', '2026-04-01', '2026-04-30');")
    assert after.returncode == 0, after.stderr


def test_a_year_end_adjustment_can_be_created(production_shaped):
    """routers/year_end_adjustments.py sets client_id on every insert."""
    assert _apply(production_shaped).returncode == 0
    r = _psql(production_shaped,
              f"INSERT INTO public.year_end_adjustments (id, engagement_id, firm_id, "
              f"client_id, adjustment_type, description, amount_paise, status, created_by) "
              f"VALUES (gen_random_uuid(), '{ENGAGEMENT}', '{FIRM}', '{CLIENT}', "
              f"'accrual', 'test', 100, 'draft', gen_random_uuid());")
    assert r.returncode == 0, r.stderr


def test_the_eight_restrictive_policies_come_back(production_shaped):
    assert _apply(production_shaped).returncode == 0
    present = _restrictive(production_shaped)
    missing = [f"{t}.{p}" for t, p in RESTRICTIVE_POLICIES if f"{t}.{p}" not in present]
    assert not missing, "\n  ".join(
        ["294 did not restore these RESTRICTIVE policies — a missing one is a "
         "check that is not applied, so a staff member reads clients they are "
         "not assigned to:"] + missing)


def test_it_leaves_the_deliberately_customised_policies_alone(production_shaped):
    """The six-test regression this migration's first draft caused.

    That draft re-ran migrations 074's and 084's loops instead of naming eight
    policies, on the reasoning that the loops are idempotent. They are
    idempotent in MECHANISM and not in INTENT:

      * 262 deliberately REPLACED payroll_employees' and payroll_runs'
        assignment_scope with per-command policies, so an employee can read
        their own payslip. Replaying 084 puts the FOR ALL version back
        ALONGSIDE the four, and restrictive policies AND together — so the
        employee is locked out again and the portal goes blank.
      * client_portal_users has a client_id and deliberately has NO
        assignment-scope policy: a portal user is not staff.

    ASSERTED ABSOLUTELY, NOT AS BEFORE-VS-AFTER. The session template is built
    from whatever these migrations currently say, so a draft that re-introduced
    the loop would put its own damage INTO the template, and a before/after
    comparison inside that database would see no change and pass. Comparing a
    thing to itself is the exact fault this whole line of work exists to fix.
    """
    assert _apply(production_shaped).returncode == 0

    r = _psql(production_shaped,
              "SELECT c.relname||'.'||p.polname FROM pg_policy p "
              "JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
              "WHERE n.nspname='public' AND c.relname IN "
              "('payroll_employees','payroll_runs','client_portal_users');", tuples=True)
    names = set(r.stdout.split())

    forbidden = {
        "payroll_employees.payroll_employees_assignment_scope",
        "payroll_runs.payroll_runs_assignment_scope",
        "client_portal_users.client_portal_users_assignment_scope",
    }
    intruders = sorted(forbidden & names)
    assert not intruders, (
        "294 created a FOR ALL assignment-scope policy on a table that must not "
        "have one. On payroll it ANDs with 262's per-command split and blanks "
        "the employee portal; on client_portal_users it locks a portal user out "
        "of their own record:\n  " + "\n  ".join(intruders))

    # And the split itself must still be all four commands.
    split = sorted(n for n in names if "_assignment_scope_" in n)
    assert len(split) == 8, split      # 4 each on payroll_employees and payroll_runs


def test_the_two_not_null_columns_are_tightened_on_an_empty_table(production_shaped):
    """Added nullable, then SET NOT NULL only where no NULL row exists. Both
    tables are empty in production, so both should end up NOT NULL."""
    assert _apply(production_shaped).returncode == 0
    r = _psql(production_shaped,
              "SELECT table_name||'.'||column_name||'='||is_nullable "
              "FROM information_schema.columns WHERE table_schema='public' AND "
              "((table_name='year_end_adjustments' AND column_name='client_id') OR "
              " (table_name='financial_statement_versions' AND column_name='statement_data')) "
              "ORDER BY 1;", tuples=True)
    assert sorted(r.stdout.split()) == [
        "financial_statement_versions.statement_data=NO",
        "year_end_adjustments.client_id=NO",
    ], r.stdout


def test_a_populated_table_is_left_nullable_rather_than_failing(production_shaped):
    """The 291 lesson: a migration that fails hard against a shape it did not
    expect blocks every later migration. With rows present and the column NULL,
    294 must leave it nullable and say so, not abort."""
    assert _psql(production_shaped, _TO_PRODUCTION_SHAPE).returncode == 0
    r = _psql(production_shaped,
              f"INSERT INTO public.year_end_adjustments (id, engagement_id, firm_id, "
              f"adjustment_type, description, amount_paise, status, created_by) "
              f"VALUES (gen_random_uuid(), '{ENGAGEMENT}', '{FIRM}', 'accrual', "
              f"'pre-existing row with no client', 100, 'draft', gen_random_uuid());")
    assert r.returncode == 0, r.stderr

    run = _apply(production_shaped)
    assert run.returncode == 0, run.stderr
    assert "left year_end_adjustments.client_id nullable" in run.stderr, run.stderr

    nullable = _psql(production_shaped,
                     "SELECT is_nullable FROM information_schema.columns "
                     "WHERE table_name='year_end_adjustments' AND column_name='client_id';",
                     tuples=True)
    assert nullable.stdout.strip() == "YES"


def test_running_it_twice_is_the_same_as_running_it_once(production_shaped):
    assert _apply(production_shaped).returncode == 0
    cols, pols = _columns(production_shaped), _restrictive(production_shaped)
    second = _apply(production_shaped)
    assert second.returncode == 0, second.stderr
    assert _columns(production_shaped) == cols
    assert _restrictive(production_shaped) == pols


def test_it_is_a_no_op_on_a_database_that_never_had_the_drift(pg_template):
    """The template already has 294. Re-running it must change nothing — that is
    the CI path and every developer's local database."""
    admin = _ADMIN.strip()
    dbname = f"r294clean_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        cols, pols = _columns(dsn), _restrictive(dsn)
        run = _apply(dsn)
        assert run.returncode == 0, run.stderr
        assert _columns(dsn) == cols
        assert _restrictive(dsn) == pols
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')
