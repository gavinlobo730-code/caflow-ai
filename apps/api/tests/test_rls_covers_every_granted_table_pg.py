"""
A table the `authenticated` role can reach must have row-level security on.

WHY THIS IS AN INVARIANT AND NOT A LIST

The application reaches Postgres two ways. The backend uses the service-role
key, which BYPASSES row-level security, so isolation there is the app-layer
`.eq("firm_id", …)` filter. The frontend is a static export that talks to
PostgREST DIRECTLY with the caller's JWT — roughly 320 `.from(…)` calls over
~83 tables — and on that path RLS is the only thing standing between one firm
and another's rows.

So for any table granted to `authenticated`, two switches have to agree: the
GRANT says the role may touch the table, and RLS says which rows. Turn RLS off
and the grant is unconditional. Postgres does not warn; the reads simply
succeed and return everybody's data.

WHAT WENT WRONG, AND WHY A LIST WOULD NOT HAVE CAUGHT IT

Migration 062 enabled RLS on 28 tables, each guarded by

    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = t)

Twenty of those tables are created by migrations 063-069 — after 062 runs — so
on a replay the guard finds nothing and skips them SILENTLY. Most were rescued
later by accident. Six were not, and two more were never in 062's list.

062 said in its own header why that was survivable:

    "the `authenticated` role holds no table GRANT on any of them, so
     PostgreSQL already denies direct access before RLS is evaluated ...
     should a future migration ever GRANT these tables to `authenticated`
     ... access stays correctly firm-scoped instead of leaking."

Migrations 095 and 287 granted exactly that. The premise expired and nothing
re-checked it — the fix (317) and the drift comparison both work per table,
and a per-table check cannot notice that a REASON stopped being true.

This test is the reason itself, asserted. It needs no list to maintain: add a
table, grant it, forget the RLS, and it fails here.

WHAT IT DELIBERATELY DOES NOT ASSERT

That the policies are correct, or that there are any. RLS on with no policy is
fail-CLOSED — safe, if surprising — and `purchase_bill_lines` is in that state
on purpose. Whether each policy scopes to the right firm is what
`test_guards_match_production_pg.py` compares against production.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

_HARNESS_PG = os.environ.get("HARNESS_PG")
_NEEDS_PG = pytest.mark.skipif(
    not _HARNESS_PG or shutil.which("psql") is None,
    reason="real-Postgres harness requires HARNESS_PG + psql")

# The migration runner's own bookkeeping. It creates these itself, no migration
# declares them, and it grants them to nobody.
_RUNNER_TABLES = {"schema_migrations", "schema_migration_failures"}

_QUERY = """
SELECT json_agg(x ORDER BY x.tbl) FROM (
  SELECT c.relname::text AS tbl,
         string_agg(DISTINCT g.privilege_type, ',' ORDER BY g.privilege_type) AS grants
  FROM pg_class c
  JOIN information_schema.role_table_grants g
    ON g.table_schema = 'public' AND g.table_name = c.relname
   AND g.grantee = 'authenticated'
  WHERE c.relnamespace = 'public'::regnamespace
    AND c.relkind = 'r'
    AND NOT c.relrowsecurity
  GROUP BY c.relname
) x;
"""


@pytest.fixture(scope="module")
def granted_but_unprotected(pg_template):
    out = subprocess.run(
        ["psql", f"{_HARNESS_PG.strip()} dbname={pg_template.name}",
         "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _QUERY],
        capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip() or "null") or []


@_NEEDS_PG
def test_no_table_granted_to_authenticated_has_rls_disabled(granted_but_unprotected):
    offenders = [r for r in granted_but_unprotected if r["tbl"] not in _RUNNER_TABLES]
    assert not offenders, (
        "These tables grant the `authenticated` role table privileges and have "
        "row-level security switched OFF. On the direct PostgREST path — which "
        "the frontend uses for ~83 tables — that is no isolation at all: any "
        "signed-in user reads every firm's rows, and writes them wherever the "
        "grant includes INSERT/UPDATE/DELETE.\n"
        "Either enable RLS and declare a firm-scoped policy (migration 317 is "
        "the pattern), or revoke the grant.\n  "
        + "\n  ".join(f"{r['tbl']}  [{r['grants']}]" for r in offenders))


@_NEEDS_PG
def test_the_query_actually_finds_granted_tables(pg_template):
    """A typo in the grants join would return nothing and pass forever."""
    out = subprocess.run(
        ["psql", f"{_HARNESS_PG.strip()} dbname={pg_template.name}", "-X", "-tA", "-c",
         "SELECT count(DISTINCT table_name) FROM information_schema.role_table_grants "
         "WHERE table_schema='public' AND grantee='authenticated';"],
        capture_output=True, text=True, check=True)
    assert int(out.stdout.strip()) > 50, (
        "almost no table is granted to `authenticated` — the introspection is "
        "wrong, and the assertion above is passing by looking at nothing")
