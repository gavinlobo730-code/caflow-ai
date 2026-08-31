"""
Migration 293 — the 17 column types that differed from the live database.

WHY THIS TEST EXISTS AND WHAT IT ACTUALLY PROVES

The session template already has 293 applied, so simply introspecting it would
prove nothing: the conversions that matter are the ten that are a no-op HERE and
do real work in PRODUCTION, on tables holding 45,893 and 8,027 rows.

So every test below first rebuilds production's shape — the columns back to
text/integer, the two RLS policies back to their uncast form — and only then
runs 293 against it. That is the state the migration will actually meet.

THE FAILURE THIS CAUGHT

Postgres refuses ALTER COLUMN ... TYPE on a column named in a policy
expression. Two RESTRICTIVE policies on client_timeline_events name client_id.
The first draft of 293 had no drop/recreate and died on the fourth conversion
with exit 3 — and because the whole file is one DO block, that aborts all
seventeen, the runner never records 293, and every later push to main retries
and fails again. test_the_policy_is_genuinely_in_the_way pins that: it is the
negative control, kept as a test rather than run once by hand.

WHAT IS DELIBERATELY ASSERTED ABOUT THE RESTORED POLICIES

That they come back RESTRICTIVE. Recreating a restrictive policy as the default
permissive one turns a security check into an access grant, silently, on a table
with 8,027 rows belonging to many firms. The text asserted is migration 084's
and 074's own, cast with client_id::text so one policy fits either column type.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = API_ROOT / "migrations" / "293_reconcile_column_types_with_production.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not MIGRATION.exists(),
    reason="migration 293 proof requires HARNESS_PG + psql",
)

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
ACTOR = "33333333-3333-3333-3333-333333333333"
ENTITY = "44444444-4444-4444-4444-444444444444"

# The 17 rows of migration 293's VALUES list, as (table, column, type this
# migration must leave behind). Written out rather than parsed back out of the
# .sql, so that deleting a row from the migration fails here instead of
# quietly shrinking what the test checks.
EXPECTED_TYPES = [
    ("account_group_mappings", "account_id", "uuid"),
    ("year_end_adjustments", "credit_account_id", "uuid"),
    ("year_end_adjustments", "debit_account_id", "uuid"),
    ("tally_migration_jobs", "source_file_size_bytes", "bigint"),
    ("financial_statement_versions", "financial_year", "character varying"),
    ("year_end_engagements", "financial_year", "character varying"),
    ("year_end_exports", "financial_year", "character varying"),
    ("audit_log", "actor_id", "uuid"),
    ("client_timeline_events", "actor_id", "uuid"),
    ("client_timeline_events", "client_id", "uuid"),
    ("client_timeline_events", "entity_id", "uuid"),
    ("client_timeline_events", "deleted_by", "uuid"),
    ("pending_invites", "invited_by", "uuid"),
    ("client_timeline_events", "actor_type", "text"),
    ("client_timeline_events", "category", "text"),
    ("client_timeline_events", "severity", "text"),
    ("client_timeline_events", "visibility", "text"),
]

# Undo 293 on a fresh clone of the template, so the migration meets the shape it
# meets in production. The FK on client_id has to go too: production does not
# have client_timeline_events_client_id_fkey at all, and a uuid FK cannot
# survive its column becoming text.
_TO_PRODUCTION_SHAPE = """
ALTER TABLE public.client_timeline_events DROP CONSTRAINT IF EXISTS client_timeline_events_client_id_fkey;
DROP POLICY IF EXISTS client_timeline_events_assignment_scope ON public.client_timeline_events;
DROP POLICY IF EXISTS client_timeline_events_internal_partner_only ON public.client_timeline_events;
ALTER TABLE public.client_timeline_events ALTER COLUMN client_id  TYPE text USING client_id::text;
ALTER TABLE public.client_timeline_events ALTER COLUMN actor_id   TYPE text USING actor_id::text;
ALTER TABLE public.client_timeline_events ALTER COLUMN entity_id  TYPE text USING entity_id::text;
ALTER TABLE public.client_timeline_events ALTER COLUMN deleted_by TYPE text USING deleted_by::text;
ALTER TABLE public.client_timeline_events ALTER COLUMN actor_type TYPE text USING actor_type::text;
ALTER TABLE public.client_timeline_events ALTER COLUMN category   TYPE text USING category::text;
ALTER TABLE public.client_timeline_events ALTER COLUMN severity   TYPE text USING severity::text;
ALTER TABLE public.client_timeline_events ALTER COLUMN visibility TYPE text USING visibility::text;
ALTER TABLE public.audit_log      ALTER COLUMN actor_id   TYPE text USING actor_id::text;
ALTER TABLE public.pending_invites ALTER COLUMN invited_by TYPE text USING invited_by::text;
ALTER TABLE public.tally_migration_jobs ALTER COLUMN source_file_size_bytes TYPE integer;
ALTER TABLE public.financial_statement_versions ALTER COLUMN financial_year TYPE text;
ALTER TABLE public.year_end_engagements       ALTER COLUMN financial_year TYPE text;
ALTER TABLE public.year_end_exports           ALTER COLUMN financial_year TYPE text;
ALTER TABLE public.account_group_mappings ALTER COLUMN account_id        TYPE text USING account_id::text;
ALTER TABLE public.year_end_adjustments   ALTER COLUMN credit_account_id TYPE text USING credit_account_id::text;
ALTER TABLE public.year_end_adjustments   ALTER COLUMN debit_account_id  TYPE text USING debit_account_id::text;
-- production's policies, without the ::text cast, which is what blocks the ALTER
CREATE POLICY client_timeline_events_assignment_scope ON public.client_timeline_events
  AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id)) WITH CHECK (public.can_access_client(client_id));
CREATE POLICY client_timeline_events_internal_partner_only ON public.client_timeline_events
  AS RESTRICTIVE FOR ALL
  USING (get_my_role() = 'Partner' OR client_id IS DISTINCT FROM my_internal_client_id()::text)
  WITH CHECK (get_my_role() = 'Partner' OR client_id IS DISTINCT FROM my_internal_client_id()::text);
"""

# Rows shaped like the ones production holds — including category 'lifecycle'
# and severity 'high', which are OUTSIDE the enums the migrations declared. They
# are the reason group D relaxes the declaration to text instead of tightening
# production to the enum: the enum cannot represent what the app already writes.
_SEED = f"""
INSERT INTO public.firms (id, name, email)
VALUES ('{FIRM}', 'Repro Firm', 'repro@example.test');
INSERT INTO public.client_timeline_events
  (id, client_id, firm_id, financial_year, period, category, event_type, severity,
   title, actor_id, entity_id, actor_type, visibility)
VALUES
  ('aaaaaaaa-0000-0000-0000-000000000001', '{CLIENT}', '{FIRM}', '2025-26', '2025-08',
   'lifecycle', 'test', 'high', 'value outside the declared enum',
   '{ACTOR}', '{ENTITY}', 'user', 'all'),
  ('aaaaaaaa-0000-0000-0000-000000000002', '{CLIENT}', '{FIRM}', '2025-26', '2025-08',
   'accounting', 'test', 'success', 'nulls must stay null',
   NULL, NULL, 'user', 'all');
INSERT INTO public.audit_log (id, firm_id, actor_id, action, entity_type, entity_id)
VALUES ('bbbbbbbb-0000-0000-0000-000000000001', '{FIRM}', '{ACTOR}', 'test', 'client', '{ENTITY}');
"""


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-f", str(path)],
        capture_output=True, text=True)


@pytest.fixture()
def production_shaped(pg_template):
    """A throwaway database rolled BACK to the pre-293 production shape, seeded."""
    admin = _ADMIN.strip()
    dbname = f"r293_{uuid.uuid4().hex[:12]}"
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


def _types(dsn: str) -> dict:
    r = _psql(dsn,
              "SELECT table_name||'.'||column_name||'='||data_type "
              "FROM information_schema.columns WHERE table_schema='public';",
              tuples=True)
    assert r.returncode == 0, r.stderr
    return dict(line.split("=", 1) for line in r.stdout.strip().splitlines() if line)


# ── the negative control, kept as a test ─────────────────────────────────────

def test_the_policy_is_genuinely_in_the_way(production_shaped):
    """Without dropping the policy first, the conversion cannot happen at all.

    This is what the first draft of 293 did. If Postgres ever stopped refusing
    this, the drop/recreate in 293 would be dead weight and should go — so the
    refusal is asserted, not assumed.
    """
    r = _psql(production_shaped,
              "ALTER TABLE public.client_timeline_events "
              "ALTER COLUMN client_id TYPE uuid USING NULLIF(client_id, '')::uuid;")
    assert r.returncode != 0, "expected Postgres to refuse; it did not"
    assert "used in a policy definition" in r.stderr, r.stderr


# ── what 293 does ────────────────────────────────────────────────────────────

def test_every_one_of_the_seventeen_columns_lands_on_its_intended_type(production_shaped):
    run = _psql_file(production_shaped, MIGRATION)
    assert run.returncode == 0, run.stderr

    types = _types(production_shaped)
    wrong = [f"{t}.{c}: expected {want}, got {types.get(f'{t}.{c}')}"
             for t, c, want in EXPECTED_TYPES if types.get(f"{t}.{c}") != want]
    assert not wrong, "\n  ".join(["293 left these columns on the wrong type:"] + wrong)


def test_the_conversion_does_not_touch_the_data(production_shaped):
    """45,893 audit_log rows and 8,027 timeline rows go through this in
    production. Values must survive byte-for-byte, and NULL must stay NULL —
    NULLIF(col, '')::uuid turns an empty string into NULL, never into a row."""
    assert _psql_file(production_shaped, MIGRATION).returncode == 0

    r = _psql(production_shaped,
              "SELECT id::text||'|'||category||'|'||severity||'|'||client_id::text||'|'"
              "||coalesce(actor_id::text,'-')||'|'||coalesce(entity_id::text,'-') "
              "FROM public.client_timeline_events ORDER BY id;", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines() == [
        f"aaaaaaaa-0000-0000-0000-000000000001|lifecycle|high|{CLIENT}|{ACTOR}|{ENTITY}",
        f"aaaaaaaa-0000-0000-0000-000000000002|accounting|success|{CLIENT}|-|-",
    ]

    a = _psql(production_shaped, "SELECT actor_id::text FROM public.audit_log;", tuples=True)
    assert a.returncode == 0, a.stderr
    assert a.stdout.strip() == ACTOR


def test_a_value_outside_the_declared_enum_survives(production_shaped):
    """Group D's whole argument in one assertion. category='lifecycle' and
    severity='high' are written by live code and are not in event_category /
    event_severity. Converting production TO the enums would reject these rows;
    relaxing the declaration to text keeps them."""
    assert _psql_file(production_shaped, MIGRATION).returncode == 0

    kept = _psql(production_shaped,
                 "SELECT count(*) FROM public.client_timeline_events "
                 "WHERE category='lifecycle' AND severity='high';", tuples=True)
    assert kept.stdout.strip() == "1"

    rejected = _psql(production_shaped, "SELECT 'lifecycle'::public.event_category;")
    assert rejected.returncode != 0, (
        "event_category now accepts 'lifecycle' — if the enum was widened, group D's "
        "reasoning changed and migration 293's comment needs revisiting")


# ── the policies must come back exactly as they went ─────────────────────────

def test_both_policies_are_restored_and_still_restrictive(production_shaped):
    assert _psql_file(production_shaped, MIGRATION).returncode == 0

    r = _psql(production_shaped,
              "SELECT p.polname||'|'||p.polpermissive::text||'|'||p.polcmd::text "
              "FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid "
              "JOIN pg_namespace n ON n.oid=c.relnamespace "
              "WHERE n.nspname='public' AND c.relname='client_timeline_events' "
              "AND p.polname IN ('client_timeline_events_assignment_scope',"
              "'client_timeline_events_internal_partner_only') ORDER BY 1;", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines() == [
        "client_timeline_events_assignment_scope|false|*",
        "client_timeline_events_internal_partner_only|false|*",
    ], "a restrictive policy came back permissive, which would widen access"


def test_the_restored_policies_still_scope_by_client_and_firm(production_shaped):
    """Restored with client_id::text — migration 084's and 074's own text, which
    is why it fits the column whichever type it is."""
    assert _psql_file(production_shaped, MIGRATION).returncode == 0

    r = _psql(production_shaped,
              "SELECT policyname||' :: '||qual FROM pg_policies "
              "WHERE schemaname='public' AND tablename='client_timeline_events' "
              "AND policyname IN ('client_timeline_events_assignment_scope',"
              "'client_timeline_events_internal_partner_only') ORDER BY 1;", tuples=True)
    scope, partner = r.stdout.strip().splitlines()
    assert "can_access_client((client_id)::text)" in scope, scope
    assert "(client_id)::text IS DISTINCT FROM (my_internal_client_id())::text" in partner, partner
    assert "get_my_role() = 'Partner'::text" in partner, partner


# ── re-running it must change nothing ────────────────────────────────────────

def test_running_it_twice_is_the_same_as_running_it_once(production_shaped):
    """The runner retries any migration it did not record. 293 must survive
    that: the second pass has to convert nothing and restore nothing."""
    assert _psql_file(production_shaped, MIGRATION).returncode == 0
    after_first = _types(production_shaped)

    second = _psql_file(production_shaped, MIGRATION)
    assert second.returncode == 0, second.stderr
    assert "converted" not in second.stderr, (
        "the second pass converted something; the type guard is not holding:\n" + second.stderr)
    assert "restored policy" not in second.stderr, second.stderr
    assert _types(production_shaped) == after_first


def test_it_is_also_a_no_op_on_a_database_that_never_had_the_drift(pg_template):
    """The session template already has 293 applied. Running it again there must
    do nothing at all — that is the CI path, and the path every developer's
    local database takes."""
    admin = _ADMIN.strip()
    dbname = f"r293clean_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        before = _types(dsn)
        run = _psql_file(dsn, MIGRATION)
        assert run.returncode == 0, run.stderr
        assert "converted" not in run.stderr, run.stderr
        assert _types(dsn) == before
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')
