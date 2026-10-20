"""Every table with a `client_id` that a signed-in person can reach is assignment-scoped, or is on a list that says why not.

WHY THIS EXISTS
    `test_a_table_the_browser_reads_is_assignment_scoped_pg` holds the rule for the tables the BROWSER reads, and
    `test_a_client_table_a_migration_creates_is_assignment_scoped` for a table a NEW migration creates. The ones in
    between - a `client_id` table that exists, that no screen reads through PostgREST, and that carries a firm policy and
    nothing per client - were left on a stated premise: "nothing reaches them from the browser, and the backend bypasses
    row security". Neither half holds. PostgREST answers for every table `authenticated` is granted whatever the browser
    reads (the anon key and the person's own JWT are all it takes), and the API runs under the caller's sign-in when
    USE_USER_JWT is on, which is the production default. So a Manager assigned to no client could read and change another
    client's rows in those tables with their own sign-in.

    Migration 527 closed the bank's children. This test is the ratchet for the rest: the list in
    `tests/fixtures/assignment_scope_exceptions.json` is exactly the tables that still carry no RESTRICTIVE policy asking
    `my_assigned_client_ids()` / `can_access_client`, with the reason each is not done, and it can only shrink.

WHAT THIS HOLDS
    * A table with a `client_id` and a grant to `authenticated` is SCOPED, or is on the list. Scoped means that for EACH
      command `authenticated` is granted (select, insert, update, delete; a column grant counts) a RESTRICTIVE policy
      asks the assignment scope for that command or for ALL. A policy for SELECT alone does not scope a table whose
      writes are granted, which is the shape a looser rule would have waved through.
    * A table on the list that has since gained the scope is removed from it (a stale entry hides the next gap), and a
      table on the list that no longer exists, or no longer reaches `authenticated`, is removed too.
    * A `parent` entry is verified (a policy of the table asks the parent table named), an `own` entry is verified (the
      policy it names exists), and a `pending` entry names the ledger item that closes it. A new table cannot be added as
      'pending' without that.

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

_HARNESS_PG = os.environ.get("HARNESS_PG")
pytestmark = pytest.mark.skipif(
    not _HARNESS_PG or shutil.which("psql") is None,
    reason="real-Postgres harness requires HARNESS_PG + psql")

EXCEPTIONS = Path(__file__).resolve().parent / "fixtures" / "assignment_scope_exceptions.json"

# Every `client_id` base table the `authenticated` role can reach (a table grant, or a column grant: migration 497 hides
# one column of client_portal_users that way), with whether every command it is granted is covered by a RESTRICTIVE policy
# that asks the assignment scope, and the text of every policy so a `parent` / `own` entry can be checked.
_QUERY = """
SELECT coalesce(json_agg(x ORDER BY x.tbl), '[]'::json) FROM (
  SELECT c.relname::text AS tbl,
         NOT EXISTS (
           SELECT 1 FROM (VALUES ('r', 'SELECT'), ('a', 'INSERT'), ('w', 'UPDATE'), ('d', 'DELETE')) AS k(cmd, priv)
            WHERE (has_table_privilege('authenticated', c.oid, k.priv)
                   OR (k.priv <> 'DELETE' AND has_any_column_privilege('authenticated', c.oid, k.priv)))
              AND NOT EXISTS (SELECT 1 FROM pg_policy p
                               WHERE p.polrelid = c.oid AND NOT p.polpermissive AND p.polcmd IN ('*', k.cmd::"char")
                                 AND (coalesce(pg_get_expr(p.polqual, p.polrelid), '') || ' ' ||
                                      coalesce(pg_get_expr(p.polwithcheck, p.polrelid), ''))
                                     ~ 'my_assigned_client_ids|can_access_client')) AS scoped,
         coalesce((SELECT json_agg(json_build_object('name', p.polname,
                                                     'expr', coalesce(pg_get_expr(p.polqual, p.polrelid), '') || ' ' ||
                                                             coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '')))
                     FROM pg_policy p WHERE p.polrelid = c.oid), '[]'::json) AS policies
    FROM pg_class c
   WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
     AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attname = 'client_id' AND NOT a.attisdropped)
     AND (EXISTS (SELECT 1 FROM information_schema.role_table_grants g
                   WHERE g.table_schema = 'public' AND g.table_name = c.relname AND g.grantee = 'authenticated')
          OR has_any_column_privilege('authenticated', c.oid, 'SELECT, INSERT, UPDATE, REFERENCES'))
) x;
"""


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], capture_output=True, text=True)


@pytest.fixture(scope="module")
def population(pg_template):
    admin = _HARNESS_PG.strip()
    name = f"e527c_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        r = _psql(f"{admin} dbname={name}", _QUERY)
        assert r.returncode == 0, r.stderr
        return {row["tbl"]: row for row in json.loads(r.stdout)}
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


@pytest.fixture(scope="module")
def listed() -> dict:
    return json.loads(EXCEPTIONS.read_text())["tables"]


def test_the_population_is_not_vacuous(population):
    assert len(population) > 150, f"only {len(population)} tables with a client_id reach authenticated: the scan reads nothing"
    assert sum(1 for t in population.values() if t["scoped"]) > 140


def test_every_client_table_asks_the_assignment_scope_or_is_on_the_list(population, listed):
    gaps = sorted(t for t, row in population.items() if not row["scoped"] and t not in listed)
    assert not gaps, (
        f"{len(gaps)} tables with a client_id carry no RESTRICTIVE policy asking the assignment scope and are not on "
        "tests/fixtures/assignment_scope_exceptions.json. A member of the firm assigned to no client can read and write "
        "them over PostgREST with their own sign-in. Add a `<table>_assignment_scope` policy written as migrations 526 "
        "and 527 write it (COALESCE(client_id::text IS NULL OR (SELECT get_my_role()) = 'Partner' OR client_id::text IN "
        "(SELECT my_assigned_client_ids()), false) in the USING and the WITH CHECK), or say why not in the list: "
        + ", ".join(gaps))


def test_a_table_that_gained_the_scope_or_left_the_schema_is_removed_from_the_list(population, listed):
    stale = sorted(t for t in listed if t not in population)
    assert not stale, f"these listed tables no longer have a client_id or no longer reach authenticated: {stale}"
    gained = sorted(t for t in listed if population[t]["scoped"])
    assert not gained, f"these listed tables now carry the assignment scope; remove them from the list: {gained}"


def test_every_entry_is_verified_for_the_reason_it_gives(population, listed):
    problems: list[str] = []
    for table, entry in sorted(listed.items()):
        kind, why = entry.get("kind"), (entry.get("why") or "").strip()
        if not why:
            problems.append(f"{table}: no reason")
        policies = population[table]["policies"] if table in population else []
        if kind == "parent":
            via = entry.get("via", "")
            if not any(re.search(rf"\b{re.escape(via)}\b", p["expr"]) for p in policies):
                problems.append(f"{table}: no policy of the table asks its parent {via!r}")
        elif kind == "own":
            if not any(p["name"] == entry.get("policy") for p in policies):
                problems.append(f"{table}: the policy {entry.get('policy')!r} does not exist")
        elif kind == "source":
            if table != "user_client_assignments":
                problems.append(f"{table}: only user_client_assignments is the assignment source")
        elif kind == "pending":
            if not re.fullmatch(r"POST-A-\d+", entry.get("ledger", "")):
                problems.append(f"{table}: a pending entry names the ledger item that closes it")
        else:
            problems.append(f"{table}: unknown kind {kind!r}")
    assert not problems, "\n".join(problems)


def test_a_pending_entry_names_a_ledger_item_that_exists(listed):
    ledger = "\n".join(p.read_text() for p in (Path(__file__).resolve().parents[3] / "docs" / "open-items").glob("*.md"))
    missing = sorted({e["ledger"] for e in listed.values() if e.get("kind") == "pending"
                      if not re.search(rf"\*\*{re.escape(e['ledger'])}\*\*", ledger)})
    assert not missing, f"the ledger holds no open item {missing}: close the table's entry when the item closes"
