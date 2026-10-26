"""A client table the browser reads directly must be assignment-scoped.

WHY THIS IS AN INVARIANT AND NOT A LIST

The frontend is a static export that talks to PostgREST DIRECTLY with the
caller's JWT — roughly 320 `.from(…)` calls across ~83 tables. `rbac()` never
runs on that path and `core.authz`'s assignment scoping never runs either, so
row-level security is the only thing deciding which CLIENTS a Manager,
Executive or Reviewer can see. A Partner is firm-wide by design
(`_FIRMWIDE_ROLES`), and `can_access_client` short-circuits to TRUE for one.

Migration 084 built that: a RESTRICTIVE `<table>_assignment_scope` policy on
every table carrying a `client_id`. It did it with a one-shot `DO` loop over
`information_schema.columns`, AND THE LOOP HAS NEVER RUN AGAIN. Every
`client_id` table created since carries only its firm-wide PERMISSIVE policy,
which scopes to the firm and stops there.

WHAT THAT COST, MEASURED

Six such tables are read straight from the browser today, and migration 370
closes them: `bank_accounts` (093), `debit_notes` (145),
`purchase_credit_notes` and `sales_debit_notes` (210), `gstr2b_reconciliations`
(341), `tds_lower_deduction_certificates` (359). Until then any signed-in user
of the firm, assigned to nothing, could read and write every client's bank
account numbers, both kinds of note, every 2B reconciliation and every §197
certificate.

Roughly 44 further `client_id` tables were in the same state, left on the premise that nothing reaches them from the browser. THAT PREMISE WAS
WRONG TWICE (PostgREST answers for every table `authenticated` is granted, and the API runs as the caller when USE_USER_JWT is on). The
14-10-2026 decision (POST-B-016) left them and deferred the question to the extension of the role-by-table matrix (POST-A-008);
`test_every_client_table_is_assignment_scoped_or_says_why_pg` is that settlement: it holds the whole population with a shrink-only list of
what is left and why, and migration 527 closed the bank's children first. THIS file still holds the narrower, older rule for the tables the
browser reads: add a `.from("payroll_loans")` to a screen and it fails until the policy exists.

WHY THE FIX IS NOT "RUN 084'S LOOP AGAIN"

Migration 262 deliberately REPLACED `payroll_employees_assignment_scope` and
`payroll_runs_assignment_scope` with four per-command policies each so the
employee portal can read a payslip. A blind DROP/CREATE would destroy that.
Which is also why the two exceptions below exist: a PORTAL principal — a client
portal user, an employee — has no `users` row and no `user_client_assignments`
row, so `can_access_client` returns FALSE for them and a RESTRICTIVE policy
would lock them out of their own record.

WHAT THIS DELIBERATELY DOES NOT ASSERT

That the policy is correct, only that an assignment rule exists.
`test_guards_match_production_pg.py` compares the policy set against
production; `test_role_write_policies_pg.py` covers the role tiers.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_HARNESS_PG = os.environ.get("HARNESS_PG")
_NEEDS_PG = pytest.mark.skipif(
    not _HARNESS_PG or shutil.which("psql") is None,
    reason="real-Postgres harness requires HARNESS_PG + psql")

_WEB = Path(__file__).resolve().parents[2] / "web"
_SCAN_DIRS = ("app", "components", "lib", "hooks")
_FROM = re.compile(r'\.from\(\s*["\']([a-z0-9_]+)["\']\s*\)')

# A PORTAL principal is not an internal user. A client portal user and an
# employee have no `public.users` row and no `user_client_assignments` row, so
# `can_access_client` answers FALSE for them — a RESTRICTIVE assignment policy
# on these two would deny each of them their OWN record. The same reason
# migration 262 split payroll_employees/payroll_runs into per-command policies
# instead of leaving 084's single FOR ALL one.
#
# The client portal's table is scoped another way and is covered by its own test:
# test_r3_0_client_portal_users_rls_pg.py. The employee portal's declaration table
# (`payroll_it_declarations`, scoped by `_own_employee`, test_297_employee_declaration_rls_pg.py)
# was the second entry until 25-10-2026: POST-A-010 moved the employee portal behind the API,
# so no screen reads it and this rule, which is about the tables the browser reads, no longer
# has anything to except.
_PORTAL_SIDE = {
    "client_portal_users": "portal login; scoped by _own_firm + _self (SELECT only)",
}

# Every `client_id` base table the `authenticated` role is granted, with the
# names of its assignment-related policies. Migration 079's gate on
# knowledge_articles / client_instructions is named `_assignment` rather than
# `_assignment_scope`, and 262's payroll policies carry a per-command suffix,
# so the match is on the word.
_QUERY = """
SELECT coalesce(json_agg(x ORDER BY x.tbl), '[]'::json) FROM (
  SELECT c.relname::text AS tbl,
         coalesce((
           SELECT string_agg(p.policyname, ',' ORDER BY p.policyname)
           FROM pg_policies p
           WHERE p.schemaname = 'public' AND p.tablename = c.relname
             AND p.policyname LIKE '%assignment%'
             AND p.permissive = 'RESTRICTIVE'
         ), '') AS assignment_policies
  FROM pg_class c
  JOIN information_schema.columns col
    ON col.table_schema = 'public' AND col.table_name = c.relname
   AND col.column_name = 'client_id'
  WHERE c.relnamespace = 'public'::regnamespace
    AND c.relkind = 'r'
    AND (EXISTS (
      SELECT 1 FROM information_schema.role_table_grants g
      WHERE g.table_schema = 'public' AND g.table_name = c.relname
        AND g.grantee = 'authenticated'
    )
    -- A table granted COLUMN BY COLUMN is just as readable from the browser (migration 497 hides one column of
    -- client_portal_users this way), and a check that only saw table-level grants dropped it from the rule.
    OR has_any_column_privilege('authenticated', c.oid, 'SELECT, INSERT, UPDATE, REFERENCES'))
  GROUP BY c.relname
) x;
"""


def _browser_tables() -> set[str]:
    """Every table name the frontend passes to `.from(...)`.

    Source only — `.next/` and `node_modules/` are build output and would
    match the same strings back out of a bundle, which is how a scanner comes
    to assert nothing after a `pnpm build`.
    """
    out: set[str] = set()
    for d in _SCAN_DIRS:
        root = _WEB / d
        if not root.is_dir():
            continue
        for f in root.rglob("*.ts*"):
            if "node_modules" in f.parts or ".next" in f.parts:
                continue
            out.update(_FROM.findall(f.read_text(errors="ignore")))
    return out


@pytest.fixture(scope="module")
def client_tables(pg_template):
    out = subprocess.run(
        ["psql", f"{_HARNESS_PG.strip()} dbname={pg_template.name}",
         "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _QUERY],
        capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip() or "[]")


# ── the scanners have to actually find something ────────────────────────────

def test_the_frontend_scan_finds_the_tables_it_is_supposed_to():
    """An empty set would make the assertion below pass against any schema."""
    found = _browser_tables()
    assert len(found) > 40, f"only found {len(found)}: {sorted(found)}"
    # The five of migration 370's six that the browser still reads, named so a
    # rename shows up here rather than silently emptying the check.
    # `bank_accounts` is the sixth and was taken off this list when its four
    # readers moved behind GET /api/banking/accounts (POST-A-010); it stays
    # scoped in the database, which the test below keeps asserting.
    for t in ("debit_notes", "purchase_credit_notes",
              "sales_debit_notes", "gstr2b_reconciliations",
              "tds_lower_deduction_certificates"):
        assert t in found, f"{t} is no longer read from the browser — if that "\
                           "is deliberate, drop it from this list"


@_NEEDS_PG
def test_the_query_actually_finds_client_tables(client_tables):
    assert len(client_tables) > 40, (
        "almost no client_id table is granted to `authenticated` — the "
        "introspection is wrong and the rule below is looking at nothing")


# ── the rule ────────────────────────────────────────────────────────────────

@_NEEDS_PG
def test_every_client_table_the_browser_reads_is_assignment_scoped(client_tables):
    read = _browser_tables()
    offenders = [
        r["tbl"] for r in client_tables
        if r["tbl"] in read
        and r["tbl"] not in _PORTAL_SIDE
        and not r["assignment_policies"]
    ]
    assert not offenders, (
        "These tables carry a client_id, are granted to `authenticated`, are "
        "read straight from the browser over PostgREST — and have no "
        "RESTRICTIVE assignment-scope policy. On that path RLS is the only "
        "control, so a Manager, Executive or Reviewer assigned to NOTHING "
        "reads and writes every client's rows.\n"
        "Add the policy (migration 370 is the pattern; migration 084 has the "
        "helper), or, if the table is portal-side and a RESTRICTIVE policy "
        "would deny a portal user their own record, add it to _PORTAL_SIDE "
        "with the reason.\n  " + "\n  ".join(sorted(offenders)))


@_NEEDS_PG
def test_the_six_that_migration_370_closes_are_closed(client_tables, pg_template):
    """Named, because the rule above passes if the frontend stops reading them
    — and a table dropping off a screen is not the same as being scoped.

    `bank_accounts` is asked of the catalogue and not of `client_tables`: migration 550 (POST-A-339) took every signed-in
    privilege from it, so it is no longer granted to `authenticated` and that list does not carry it. Its policy stays as the
    second lock, and a regrant would put it back to work, which is why it is still held."""
    by_tbl = {r["tbl"]: r["assignment_policies"] for r in client_tables}
    for t in ("debit_notes", "purchase_credit_notes",
              "sales_debit_notes", "gstr2b_reconciliations",
              "tds_lower_deduction_certificates"):
        assert by_tbl.get(t), f"{t} has no RESTRICTIVE assignment policy"
    out = subprocess.run(
        ["psql", f"{_HARNESS_PG.strip()} dbname={pg_template.name}", "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
         "SELECT count(*) FROM pg_policies WHERE schemaname = 'public' AND tablename = 'bank_accounts' "
         "AND policyname LIKE '%assignment%' AND permissive = 'RESTRICTIVE';"],
        capture_output=True, text=True, check=True)
    assert int(out.stdout.strip()) >= 1, "bank_accounts has no RESTRICTIVE assignment policy"


@_NEEDS_PG
def test_migration_370_did_not_disturb_the_payroll_portal_policies(pg_template):
    """262's per-command split is what a re-run of 084's loop would destroy.
    Four policies each, not one FOR ALL.

    The policies are asked of the catalogue and not of `client_tables`: migration 549 (POST-A-339) took every signed-in
    privilege from the two tables, so they are no longer granted to `authenticated` and that list does not carry them. The
    policies stay as the second lock and a regrant would put them back to work, which is why they are still held."""
    out = subprocess.run(
        ["psql", f"{_HARNESS_PG.strip()} dbname={pg_template.name}", "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "|", "-c",
         "SELECT tablename, string_agg(policyname, ',' ORDER BY policyname) FROM pg_policies "
         "WHERE schemaname = 'public' AND tablename IN ('payroll_employees', 'payroll_runs') "
         "AND policyname LIKE '%assignment%' AND permissive = 'RESTRICTIVE' GROUP BY tablename;"],
        capture_output=True, text=True, check=True)
    by_tbl = dict(line.split("|", 1) for line in out.stdout.strip().splitlines())
    for t in ("payroll_employees", "payroll_runs"):
        names = (by_tbl.get(t) or "").split(",")
        for cmd in ("select", "insert", "update", "delete"):
            assert f"{t}_assignment_scope_{cmd}" in names, (t, cmd, names)
        assert f"{t}_assignment_scope" not in names, (
            f"{t} is back on a single FOR ALL policy — the employee portal "
            "cannot read a payslip through it")


@_NEEDS_PG
def test_the_portal_exceptions_are_still_needed(client_tables):
    """A dead exception is a hole nobody is looking at. If one of these grows
    an assignment policy of its own, take it off the list."""
    by_tbl = {r["tbl"]: r["assignment_policies"] for r in client_tables}
    read = _browser_tables()
    for t, why in _PORTAL_SIDE.items():
        assert t in by_tbl, f"{t} no longer exists or is not granted — {why}"
        assert t in read, f"{t} is no longer read from the browser — {why}"
        assert not by_tbl[t], (
            f"{t} now has an assignment policy ({by_tbl[t]}); remove it from "
            "_PORTAL_SIDE so the rule covers it")
