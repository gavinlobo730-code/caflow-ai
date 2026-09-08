"""The published anon key cannot execute the SECURITY DEFINER functions that
would hand it a tenant's data.

WHY THIS FILE EXISTS
    Twelve SECURITY DEFINER functions in `public` were executable by `anon`,
    almost all of them through the EXECUTE-to-PUBLIC that CREATE FUNCTION gives
    away by default. `anon` is the key inlined into the browser bundle, and RLS
    does not run inside a SECURITY DEFINER function, so for the ones that take a
    tenant as an ARGUMENT the anon key was enough on its own:

        get_cash_payments_above_threshold(p_firm_id, p_client_id, p_threshold)

    returns a client's cash payments — narration, date, amount, counterparty
    account. Client UUIDs appear in URLs.

WHY A REAL DATABASE
    The bug is a privilege, not a line of code. Nothing in Python can observe
    it, and migration 141 already recorded the way it hides: `REVOKE ... FROM
    anon` against a privilege that came from PUBLIC is a no-op that reads
    exactly like a successful revoke in a migration log. Only
    has_function_privilege can tell the difference.

WHAT IS DELIBERATELY NOT ASSERTED
    That the five RLS predicates STAY reachable by anon. They are left alone by
    migration 337 for reasons written in its header — they answer questions
    about the caller, they leak nothing to an unauthenticated one, and the
    policies that call them were written with no TO clause so every role
    evaluates them. But that is a judgement, and pinning a judgement in a test
    turns "we decided not to" into "you may not", which is more than was
    decided. The reachability is asserted only for `anon` on the ones that were
    revoked, and for `authenticated`/`service_role` on all seven, because those
    two are the callers the product actually has.
"""
from __future__ import annotations

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
    reason="function-privilege proof requires HARNESS_PG + psql",
)

# The seven migration 337 revokes, by identity signature.
REVOKED = [
    "public.get_cash_payments_above_threshold(uuid, uuid, bigint)",
    "public.get_public_columns()",
    "public.get_public_schema_columns()",
    "public.increment_message_count(uuid)",
    "public.is_client_fy_locked(uuid, uuid, date)",
    "public.payroll_declaration_guard_verified_columns()",
    "public.payroll_declaration_item_guard_verified_columns()",
]


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA", "-F", "|"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"anonexec_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _privilege(dsn: str, role: str, sig: str) -> str:
    r = _psql(dsn,
              f"SELECT CASE WHEN to_regprocedure('{sig}') IS NULL THEN 'missing' "
              f"WHEN has_function_privilege('{role}', '{sig}', 'EXECUTE') "
              f"THEN 'yes' ELSE 'no' END;", tuples=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.mark.parametrize("sig", REVOKED)
def test_anon_cannot_execute(db, sig):
    """The revoke has to bite through PUBLIC, not merely be written down."""
    assert _privilege(db, "anon", sig) == "no", (
        f"anon can still EXECUTE {sig}. If the migration only revoked FROM anon "
        "and the grant came from PUBLIC, the revoke was a no-op — migration 141 "
        "documents that exact failure.")


@pytest.mark.parametrize("sig", REVOKED)
def test_the_api_roles_keep_it(db, sig):
    """Revoking PUBLIC takes the privilege away from `authenticated` and
    `service_role` too, since theirs came from PUBLIC on several of these. The
    re-grant is not tidiness — without it, core/schema_guard.py's boot check and
    the §40A(3) scan stop working."""
    assert _privilege(db, "authenticated", sig) == "yes", sig
    assert _privilege(db, "service_role", sig) == "yes", sig


def test_the_cash_payment_scan_is_the_one_that_mattered(db):
    """Stated on its own so a future edit to the list above cannot quietly drop
    it. It takes firm and client as ARGUMENTS and makes no caller check, so an
    anon EXECUTE is a direct read of a named client's ledger."""
    assert _privilege(db, "anon",
                      "public.get_cash_payments_above_threshold(uuid, uuid, bigint)") == "no"


def test_role_rank_has_a_pinned_search_path(db):
    """It is SECURITY INVOKER, but my_role_at_least (SECURITY DEFINER) calls it,
    and every RESTRICTIVE write policy of migration 260 goes through the pair."""
    r = _psql(db,
              "SELECT coalesce(array_to_string(p.proconfig, ','), '') "
              "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
              "WHERE n.nspname = 'public' AND p.proname = 'role_rank';",
              tuples=True)
    assert r.returncode == 0, r.stderr
    assert "search_path=" in r.stdout, (
        f"role_rank's search_path is not pinned: {r.stdout.strip()!r}")


# A SECURITY DEFINER function that names a firm or a client in its parameters
# and is reachable by `anon` is the SHAPE of this bug, not just the instance.
# The ratchet below fails when a new one appears. Two are known and allowed,
# each for a stated reason — this list may only SHRINK.
KNOWN_TENANT_ARGUMENT_DEFINERS = {
    # DELIBERATE (migration 337's header, "what is deliberately left alone").
    # It takes the client id being ASKED ABOUT and returns a yes/no about the
    # CALLER — no row of that client's ever comes back. It is called from
    # RESTRICTIVE policies written with no TO clause (084, 260), so every role
    # evaluates it, and a role without EXECUTE gets `permission denied for
    # function` rather than the quiet denial the policy intends.
    "can_access_client(p_client_id text)",

    # NOT IN SCOPE, AND ALREADY CLOSED ON PRODUCTION — a migrations-vs-
    # production DRIFT rather than a live hole. Migration 020 created
    # is_fy_locked with the default EXECUTE-to-PUBLIC and granted
    # `authenticated`; 137 and 203 replaced and re-granted it without ever
    # revoking PUBLIC. So a database built from migrations alone — this one,
    # and CI's — lets anon execute it. The LIVE database does not: its acl is
    # {postgres,authenticated,service_role} with no PUBLIC entry, so somebody
    # revoked it out of band and the repo never learned. Reading it tells an
    # anonymous caller whether a firm has locked a financial year, which is
    # thin, but the fix is one REVOKE and it belongs in a migration that says
    # so rather than inside a security fix scoped to a different list.
    "is_fy_locked(p_firm_id uuid, p_date date)",
}


def test_no_new_definer_function_takes_a_tenant_argument_anon_can_reach(db):
    """The class, not the instance. Fails when a NEW tenant-argument SECURITY
    DEFINER function becomes anon-reachable, and fails just as loudly when one
    of the two known entries is fixed and left on the list."""
    r = _psql(db, """
        SELECT p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')'
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public'
           AND p.prosecdef
           AND has_function_privilege('anon', p.oid, 'EXECUTE')
           AND pg_get_function_identity_arguments(p.oid) ~ '(firm_id|client_id)'
         ORDER BY 1;
    """, tuples=True)
    assert r.returncode == 0, r.stderr
    found = {ln.strip() for ln in r.stdout.strip().splitlines() if ln.strip()}

    unexpected = sorted(found - KNOWN_TENANT_ARGUMENT_DEFINERS)
    assert unexpected == [], (
        "New SECURITY DEFINER functions take a tenant as an argument and are "
        f"reachable by the published anon key: {unexpected}. Either revoke "
        "EXECUTE from PUBLIC and anon, or give the function a caller check.")

    fixed = sorted(KNOWN_TENANT_ARGUMENT_DEFINERS - found)
    assert fixed == [], (
        f"{fixed} no longer reachable by anon — remove it from "
        "KNOWN_TENANT_ARGUMENT_DEFINERS. The list may only shrink, and it only "
        "shrinks when somebody deletes an entry.")
