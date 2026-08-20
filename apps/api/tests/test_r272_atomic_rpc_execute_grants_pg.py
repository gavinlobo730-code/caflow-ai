"""
Migration 272 — the published anon key must not be able to execute the
SECURITY DEFINER write RPCs.

THE EXPOSURE THIS PINS
    numbered_document_atomic, settle_receipt_atomic and record_fee_receipt_atomic
    are all SECURITY DEFINER and all granted EXECUTE to PUBLIC — the first two
    via `=X/postgres` in their acl, the third via a NULL acl (which is PUBLIC by
    default). PUBLIC includes `anon`, and the anon key is inlined into the
    browser bundle on purpose, because RLS is what protects the data. RLS does
    not run inside a SECURITY DEFINER function, so that reasoning did not hold
    for these three.

    numbered_document_atomic is the sharpest of them: the caller names the
    TABLE, so it is an arbitrary INSERT into any table in the public schema, as
    the owner, with RLS off.

WHAT IS ASSERTED
    Per function: anon cannot execute, `authenticated` can (the API runs as the
    end user under USE_USER_JWT), service_role can (background jobs).
    post_journal_atomic is included as a no-regression guard for 271.

    Plus a vacuity guard — a privilege test that silently stops finding its
    functions would pass forever while asserting nothing.

Runs only when HARNESS_PG is set + psql is on PATH. The `migrations` CI job runs
it against its real Postgres 16.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="RPC execute-grant proof requires HARNESS_PG + psql",
)

# Identity signatures, exactly as pg_get_function_identity_arguments reports
# them — has_function_privilege needs the argument types to resolve an overload.
RPCS = {
    "numbered_document_atomic":  "public.numbered_document_atomic(text,jsonb,text,jsonb,text)",
    "settle_receipt_atomic":     "public.settle_receipt_atomic(jsonb,jsonb,jsonb,jsonb)",
    "record_fee_receipt_atomic": "public.record_fee_receipt_atomic(uuid,uuid,date,bigint,text,text,text)",
    # 271's function. Not what this migration changes — here so a later edit
    # that re-widens it fails in the same place as the three it accompanies.
    "post_journal_atomic":       "public.post_journal_atomic(jsonb,jsonb)",
}


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


@pytest.fixture()
def migrated_db(pg_template):
    """The session-scoped migrated template, read-only for these assertions."""
    return f"{_ADMIN.strip()} dbname={pg_template.name}"


def test_the_functions_all_exist(migrated_db):
    """Vacuity guard. Every assertion below reads a privilege on a named
    signature; if a signature stopped resolving, has_function_privilege would
    error rather than return false — but a typo'd test that skipped silently
    would look identical to a passing one. Pin the set first."""
    r = _psql(migrated_db, """
        SELECT p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')'
          FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public'
           AND p.proname IN ('numbered_document_atomic','settle_receipt_atomic',
                             'record_fee_receipt_atomic','post_journal_atomic')
         ORDER BY 1;
    """, tuples=True)
    found = [line for line in r.stdout.strip().splitlines() if line]
    assert len(found) == 4, f"expected all 4 atomic write RPCs, found: {found}"


@pytest.mark.parametrize("name", sorted(RPCS))
def test_anon_cannot_execute(migrated_db, name):
    """The whole point. anon is reachable by anyone who loaded the app."""
    sig = RPCS[name]
    r = _psql(migrated_db,
              f"SELECT has_function_privilege('anon', '{sig}', 'EXECUTE');", tuples=True)
    assert r.returncode == 0, f"privilege lookup failed for {name}: {r.stderr}"
    assert r.stdout.strip() == "f", (
        f"anon can execute {name} — it is SECURITY DEFINER, so this is an "
        f"unauthenticated write into the database with RLS bypassed"
    )


@pytest.mark.parametrize("name", sorted(RPCS))
def test_the_api_roles_can_still_execute(migrated_db, name):
    """The revoke must not take the callers with it. `authenticated` is what the
    API runs as with USE_USER_JWT on; service_role is what the nightly sweep and
    every background job run as."""
    sig = RPCS[name]
    r = _psql(migrated_db, f"""
        SELECT has_function_privilege('authenticated', '{sig}', 'EXECUTE'),
               has_function_privilege('service_role',  '{sig}', 'EXECUTE');
    """, tuples=True)
    authed, service = r.stdout.strip().split("|")
    assert authed == "t", f"the API cannot execute {name} — journal/invoice/receipt writes would 500"
    assert service == "t", f"background jobs cannot execute {name}"


@pytest.mark.parametrize("name", sorted(RPCS))
def test_execute_is_granted_explicitly_not_inherited_from_public(migrated_db, name):
    """`=X/postgres` in an acl is a grant to PUBLIC. Relying on it would mean a
    future REVOKE ... FROM PUBLIC anywhere silently removes the API's access, and
    it is the exact shape this migration exists to remove."""
    sig = RPCS[name]
    # ::regprocedure resolves the exact overload from a type-only signature.
    # Matching on pg_get_function_identity_arguments() would not: it renders
    # PARAMETER NAMES too ("p_entry jsonb, p_lines jsonb"), so the comparison
    # silently found nothing and the assertions below read an empty string.
    r = _psql(migrated_db, f"""
        SELECT coalesce(array_to_string(proacl, ' | '), 'NULL')
          FROM pg_proc WHERE oid = '{sig}'::regprocedure;
    """, tuples=True)
    assert r.returncode == 0, f"could not resolve {sig}: {r.stderr}"
    acl = r.stdout.strip()
    assert acl, f"no pg_proc row resolved for {sig} — the assertions below would be vacuous"
    assert acl != "NULL", f"{name} has no explicit acl — that is PUBLIC EXECUTE by default"

    # An aclitem is `grantee=privs/grantor`. The PUBLIC grant is the one with an
    # EMPTY grantee, so it renders as `=X/postgres` — it is identified by the
    # leading '=', not by containing "=X/", which every ordinary entry
    # ("postgres=X/postgres") also contains.
    items = [i.strip() for i in acl.split("|")]
    public_grants = [i for i in items if i.startswith("=")]
    assert not public_grants, (
        f"{name} still grants EXECUTE to PUBLIC — and PUBLIC includes anon "
        f"(acl item: {public_grants}, full acl: {acl})"
    )
    assert any(i.startswith("authenticated=") for i in items), (
        f"{name} must grant EXECUTE to authenticated explicitly (acl: {acl})")
    assert any(i.startswith("service_role=") for i in items), (
        f"{name} must grant EXECUTE to service_role explicitly (acl: {acl})")
