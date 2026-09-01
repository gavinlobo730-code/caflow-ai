"""
Migration 287 — the API's own Postgres role can read itc_reversal_register,
and every other table it needs, against a real Postgres.

WHAT THIS IS ABOUT
    Migration 285 created itc_reversal_register with RLS and a policy but no
    GRANT. `authenticated` was left holding REFERENCES/TRIGGER/TRUNCATE — the
    ACL noise a table has when nobody granted it anything. With USE_USER_JWT
    on, the API *is* `authenticated` as far as Postgres is concerned, so
    itc_register_service.for_period() got SQLSTATE 42501, PostgREST turned it
    into a 403, and "Compute from Books" 500ed for every client and every
    period from the moment 285 reached production.

WHY NOTHING CAUGHT IT
    Grants do not exist in mock mode, so the ~7,000-test suite could not see
    it. The migration-apply job DOES run real Postgres — but as a superuser,
    which every grant is irrelevant to. The only thing that finds this is a
    test that assumes the role the API actually runs as. That is this file.

THE INVARIANT, NOT THE ONE TABLE
    test_every_table_the_backend_can_read_the_api_can_read_too is the one that
    matters. Naming itc_reversal_register alone would pass forever the moment
    287 lands. Migration 269 gave service_role ALTER DEFAULT PRIVILEGES, so
    every new table gets the backend grant free and only the `authenticated`
    one has to be written by hand — which means this is a hole that reopens on
    its own, every time somebody creates a table. It should fail here rather
    than in production a day later.

    269 deliberately did NOT set default privileges for `authenticated`, and
    should not: `authenticated` is the browser's role through PostgREST, and
    several tables are SELECT-only for it on purpose. Writing the grant by hand
    is the correct design. Asserting it was the missing half.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
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
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="itc_reversal_register grant proof requires HARNESS_PG + psql",
)

# Tables `authenticated` is not meant to reach. Every one of these is either
# platform-operator machinery or migration scaffolding, and none of them is
# read by apps/api on the user-JWT path or by the frontend's PostgREST calls.
NOT_FOR_THE_API = {
    "schema_migrations",     # the migration runner's own bookkeeping
    # Its sibling: which migrations failed, so a permanently-broken one is not
    # retried forever and cannot re-apply its partial effects over a later fix.
    # Same reason as schema_migrations — deploy machinery, never application
    # data, and nothing in the API reads it.
    "schema_migration_failures",
    "platform_admins",       # cross-firm operator accounts; RLS would not save us
    "platform_audit",        # what those operators did
}
# Scaffolding left behind by data migrations. Prefixed, not enumerated, because
# the next one will have a different number.
SCAFFOLD_PREFIXES = ("_backup_", "_mig")

FIRM = "f7000000-0000-0000-0000-000000000001"
OTHER_FIRM = "f7000000-0000-0000-0000-000000000002"
ASSIGNED = "c7000000-0000-0000-0000-000000000001"
UNASSIGNED = "c7000000-0000-0000-0000-000000000002"
EXEC_AUTH = "77777777-7777-7777-7777-777777777777"
EXEC_USER = "d7000000-0000-0000-0000-000000000001"
JE_ASSIGNED = "a7000000-0000-0000-0000-000000000001"
JE_UNASSIGNED = "a7000000-0000-0000-0000-000000000002"
# Two more posted journals with NO register row against them. The unique index
# uq_itc_reversal_register_journal means an insert naming an already-registered
# journal fails on the constraint, not on the policy — which would make the
# write tests below pass without ever exercising RLS.
JE_SPARE_ASSIGNED = "a7000000-0000-0000-0000-000000000004"
JE_SPARE_UNASSIGNED = "a7000000-0000-0000-0000-000000000005"

SEED = f"""
INSERT INTO auth.users (id) VALUES ('{EXEC_AUTH}') ON CONFLICT DO NOTHING;
INSERT INTO firms (id,name,email) VALUES
  ('{FIRM}','F','f7@t.in'), ('{OTHER_FIRM}','G','g7@t.in');
INSERT INTO clients (id,firm_id,client_name,entity_type) VALUES
  ('{ASSIGNED}','{FIRM}','Assigned','Proprietorship'),
  ('{UNASSIGNED}','{FIRM}','Unassigned','Proprietorship');
INSERT INTO users (id,firm_id,full_name,email,role,auth_user_id)
  VALUES ('{EXEC_USER}','{FIRM}','Exec','exec7@t.in','Executive','{EXEC_AUTH}');
INSERT INTO user_client_assignments (user_id,client_id,firm_id)
  VALUES ('{EXEC_USER}','{ASSIGNED}','{FIRM}');
INSERT INTO journal_entries
  (id, firm_id, client_id, entry_date, narration, entry_type, is_posted, status)
VALUES
  ('{JE_ASSIGNED}','{FIRM}','{ASSIGNED}','2026-03-31','Rule 37 reversal','Journal',true,'posted'),
  ('{JE_UNASSIGNED}','{FIRM}','{UNASSIGNED}','2026-03-31','Rule 37 reversal','Journal',true,'posted'),
  ('{JE_SPARE_ASSIGNED}','{FIRM}','{ASSIGNED}','2026-04-30','Spare','Journal',true,'posted'),
  ('{JE_SPARE_UNASSIGNED}','{FIRM}','{UNASSIGNED}','2026-04-30','Spare','Journal',true,'posted');
INSERT INTO itc_reversal_register
  (firm_id, client_id, journal_entry_id, kind, reason_code, period, igst_paise)
VALUES
  ('{FIRM}','{ASSIGNED}','{JE_ASSIGNED}','reversal','rule_37','032026',500000),
  ('{FIRM}','{UNASSIGNED}','{JE_UNASSIGNED}','reversal','rule_37','032026',700000);
"""


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _as_user(sql: str, auth_uid: str = EXEC_AUTH) -> str:
    """Run sql the way PostgREST does: role `authenticated`, JWT claims set."""
    claims = json.dumps({"sub": auth_uid, "role": "authenticated"}).replace("'", "''")
    return (f"SET LOCAL ROLE authenticated; "
            f"SELECT set_config('request.jwt.claims', '{claims}', true); {sql}")


@pytest.fixture()
def seeded_db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"itcg_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, SEED)
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _rows(result: subprocess.CompletedProcess) -> list[str]:
    return [line for line in result.stdout.strip().splitlines() if line]


# ── The invariant ────────────────────────────────────────────────────────────

def test_every_table_the_backend_can_read_the_api_can_read_too(seeded_db):
    """The mirror of R269's invariant, and the half that was missing.

    R269 asserts: if `authenticated` can read it, service_role must be able to.
    That direction was already covered — and it passed all the way through the
    285 outage, because service_role COULD read itc_reversal_register. It was
    `authenticated` that could not.
    """
    result = _psql(seeded_db, """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r','p')
          AND has_table_privilege('service_role', c.oid, 'SELECT')
          AND NOT has_table_privilege('authenticated', c.oid, 'SELECT')
        ORDER BY c.relname;
    """, tuples=True)
    assert result.returncode == 0, result.stderr
    unreachable = [
        t for t in _rows(result)
        if t not in NOT_FOR_THE_API and not t.startswith(SCAFFOLD_PREFIXES)
    ]
    assert not unreachable, (
        "these tables cannot be read by `authenticated`, which is the role the "
        "API runs as under USE_USER_JWT and the role every direct PostgREST "
        "call from the frontend uses. PostgREST answers 403 and the endpoint "
        "500s. Add `GRANT SELECT... TO authenticated` in the migration that "
        f"created them, or add them to NOT_FOR_THE_API with a reason: {unreachable}"
    )


def test_the_operator_tables_stay_out_of_reach(seeded_db):
    """The deny-list above is only honest if the things on it really are
    denied. If a migration ever grants `authenticated` on platform_admins, the
    invariant above would go on passing while cross-firm operator rows became
    readable by any logged-in user."""
    for table in sorted(NOT_FOR_THE_API):
        r = _psql(seeded_db,
                  f"SELECT has_table_privilege('authenticated','public.{table}','SELECT');",
                  tuples=True)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "f", (
            f"`authenticated` gained SELECT on {table} — it is on the deny-list "
            "precisely because no end user should read it"
        )


# ── The table that broke ─────────────────────────────────────────────────────

@pytest.mark.parametrize("privilege", ["SELECT", "INSERT", "UPDATE", "DELETE"])
def test_the_api_role_holds_dml_on_the_register(seeded_db, privilege):
    """The exact grant migration 285 omitted. SELECT is what 500ed; the other
    three are what recording a reversal from the UI needs, and would have been
    the next 42501 one line down."""
    r = _psql(seeded_db,
              f"SELECT has_table_privilege('authenticated','public.itc_reversal_register','{privilege}');",
              tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "t", (
        f"`authenticated` cannot {privilege} itc_reversal_register — this is the "
        "403 that broke Compute from Books"
    )


def test_the_backend_role_keeps_its_own_dml(seeded_db):
    """service_role got this free from migration 269's default privileges.
    287 states it explicitly; this pins that it is still true either way."""
    r = _psql(seeded_db, """
        SELECT has_table_privilege('service_role','public.itc_reversal_register','SELECT'),
               has_table_privilege('service_role','public.itc_reversal_register','INSERT');
    """, tuples=True)
    assert r.stdout.strip() == "t|t", r.stdout


def test_the_period_read_the_endpoint_makes_actually_returns_rows(seeded_db):
    """for_period() issues exactly this shape. Reproducing it as `authenticated`
    is the closest a test can get to the request that 500ed."""
    r = _psql(seeded_db, _as_user(f"""
        SELECT count(*) FROM itc_reversal_register
         WHERE firm_id='{FIRM}' AND client_id='{ASSIGNED}' AND period='032026';
    """), tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "1", (
        "the register read the GSTR-3B computation makes returned nothing"
    )


# ── Isolation, which 287 also rewrites to the house shape ────────────────────

def test_another_firms_reversals_are_not_visible(seeded_db):
    r = _psql(seeded_db, f"""
        INSERT INTO journal_entries
          (id, firm_id, client_id, entry_date, narration, entry_type, is_posted, status)
        VALUES ('a7000000-0000-0000-0000-000000000003','{OTHER_FIRM}','{ASSIGNED}',
                '2026-03-31','x','Journal',true,'posted');
        INSERT INTO itc_reversal_register
          (firm_id, client_id, journal_entry_id, kind, reason_code, period, igst_paise)
        VALUES ('{OTHER_FIRM}','{ASSIGNED}','a7000000-0000-0000-0000-000000000003',
                'reversal','rule_37','032026',999);
    """)
    assert r.returncode == 0, f"admin seed of the other firm's row failed: {r.stderr}"
    r = _psql(seeded_db, _as_user(
        f"SELECT count(*) FROM itc_reversal_register WHERE firm_id='{OTHER_FIRM}';"),
        tuples=True)
    assert r.stdout.strip().splitlines()[-1] == "0", (
        "one firm read another firm's ITC reversals"
    )


def test_an_unassigned_clients_reversals_are_not_visible(seeded_db):
    """Same firm, so firm isolation alone lets this through — 285's policy did.
    The RESTRICTIVE assignment scope 287 adds is what stops it."""
    r = _psql(seeded_db, _as_user(
        f"SELECT count(*) FROM itc_reversal_register WHERE client_id='{UNASSIGNED}';"),
        tuples=True)
    assert r.stdout.strip().splitlines()[-1] == "0", (
        "a staff member unassigned from this client read its ITC reversals"
    )


def test_a_write_for_an_unassigned_client_is_refused(seeded_db):
    """WITH CHECK, not just USING — otherwise a user could declare a reversal
    on a return they cannot read back."""
    r = _psql(seeded_db, _as_user(f"""
        INSERT INTO itc_reversal_register
          (firm_id, client_id, journal_entry_id, kind, reason_code, period, igst_paise)
        VALUES ('{FIRM}','{UNASSIGNED}','{JE_SPARE_UNASSIGNED}','reversal','rule_37','042026',100);
    """))
    assert r.returncode != 0, (
        "wrote an ITC reversal for a client the caller is not assigned to"
    )


def test_an_assigned_client_can_still_be_written(seeded_db):
    """The negative control for the two tests above: if the RESTRICTIVE policy
    were simply refusing everything, they would both pass for the wrong reason."""
    r = _psql(seeded_db, _as_user(f"""
        INSERT INTO itc_reversal_register
          (firm_id, client_id, journal_entry_id, kind, reason_code, period, igst_paise)
        VALUES ('{FIRM}','{ASSIGNED}','{JE_SPARE_ASSIGNED}','reversal','rule_37','042026',100);
    """))
    assert r.returncode == 0, (
        "the assignment policy is too tight — a user assigned to this client "
        f"cannot record its own reversal: {r.stderr}"
    )


def test_the_old_policy_name_is_gone(seeded_db):
    """285's policy and 287's would both be PERMISSIVE and would OR together,
    so leaving the old one in place would silently defeat the new
    assignment scope. The DROP is load-bearing."""
    r = _psql(seeded_db, """
        SELECT count(*) FROM pg_policy
         WHERE polrelid = 'public.itc_reversal_register'::regclass
           AND polname = 'firm_staff_manage_itc_reversal_register';
    """, tuples=True)
    assert r.stdout.strip() == "0", (
        "migration 285's policy is still attached alongside 287's — being "
        "PERMISSIVE it ORs with the new one and re-opens unassigned clients"
    )
