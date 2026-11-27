"""The older migrations that guard on "does this table exist yet" are checked against the schema they ended up building (POST-A-167).

WHY THIS FILE EXISTS
    Migration 062 carried `IF EXISTS (SELECT 1 FROM information_schema.tables ...)` around each table it meant to put
    under row security and silently skipped eight that did not exist when it ran (fixed by 317, with an invariant test).
    The same shape stands in 074, 076, 078 and 154. A guard of that kind cannot fail: a table it did not find is a table it
    did not protect, and nothing says so. What can be checked is the END STATE, on a database built from the migrations
    from scratch, for every name the guard was given. This reads each guard's own list out of the migration text, so a
    name added to a list later is checked without anyone remembering to add it here.

WHAT THE READING FOUND (27-11-2026)
    074 (the internal practice is a Partner's alone): 45 names. 39 carry the policy. Three have no `client_id` column
        (attendance, document_extractions, leave_balances), so there is no client for the policy to ask about; one
        (compliance_tasks) does not exist in any database built from the migrations. Two (bank_accounts, salary_structures)
        were created AFTER 074 ran and so never got `<table>_internal_partner_only`; both carry the assignment-scope policy
        (bank_accounts_assignment_scope; salary_structures' read and write tiers), and the internal practice cannot be
        assigned to a signed-in member (tests/test_an_assignment_to_the_practice_grants_a_non_partner_nothing.py), so a
        non-Partner reaches neither table's internal rows through either door. They are listed below as covered BY THAT
        RULE, not by 074's policy, and the test fails if either loses it.
    076 and 078: the one foreign key each adds exists.
    154: 43 names; 40 carry `<table>_firm_isolation`. Three (ai_memory_triggers, pattern_anomalies, year_end_reports) are
        names no migration ever creates a table for, so the guard skipped nothing real.
    062 is the one this replaced (317 and its test).

THE LISTS BELOW ONLY SHRINK. Each name is on a list with its reason, and the test asserts the reason still holds (a table
that has since gained a `client_id`, or been created, is no longer an exception and must be taken off the list and given
its policy).

Skipped without HARNESS_PG and psql.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

# 074: named, and why 074's own policy is not on it.
NO_CLIENT_COLUMN = {"attendance", "document_extractions", "leave_balances"}
NEVER_EXISTED_074 = {"compliance_tasks"}
CREATED_AFTER_074_COVERED_BY_THE_ASSIGNMENT_SCOPE = {"bank_accounts", "salary_structures"}
# 154: names no migration builds a table for.
NEVER_EXISTED_154 = {"ai_memory_triggers", "pattern_anomalies", "year_end_reports"}


def _list_in(migration: str, opener: str) -> list[str]:
    """The quoted names of the array that starts at `opener` in a migration, up to its closing bracket."""
    text = (MIGRATIONS / migration).read_text(encoding="utf-8")
    start = text.index(opener)
    end = text.index("];", start)
    body = re.sub(r"--[^\n]*", "", text[start:end])
    return re.findall(r"'([a-z_0-9]+)'", body)


def _lists() -> tuple[list[str], list[str]]:
    return (_list_in("074_internal_client_rls_guardrails.sql", "tbls text[] := ARRAY["),
            _list_in("154_fix_jwt_claim_rls_predicate.sql", "tables text[] := ARRAY["))


def test_each_guards_list_is_read_whole():
    """The lists are read out of the migrations, so a reader that found a few names would pass everything below."""
    t074, t154 = _lists()
    assert len(t074) >= 45 and len(set(t074)) == len(t074)
    assert len(t154) >= 43 and len(set(t154)) == len(t154)
    assert "bank_accounts" in t074 and "year_end_engagements" in t154


def test_the_exceptions_are_names_the_guards_were_given():
    t074, t154 = _lists()
    assert (NO_CLIENT_COLUMN | NEVER_EXISTED_074 | CREATED_AFTER_074_COVERED_BY_THE_ASSIGNMENT_SCOPE) <= set(t074)
    assert NEVER_EXISTED_154 <= set(t154)


pg = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the end-state proof requires HARNESS_PG + psql",
)


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-F", "|", "-c", sql],
                          capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"guards_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    try:
        yield f"{admin} dbname={name}"
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return [line.split("|") for line in r.stdout.strip().splitlines() if line]


def _facts(dsn: str, names: list[str]) -> dict[str, dict]:
    arr = "ARRAY[" + ",".join(f"'{n}'" for n in names) + "]"
    rows = _rows(dsn, f"""
        SELECT t.n,
               to_regclass('public.' || t.n) IS NOT NULL,
               COALESCE((SELECT relrowsecurity FROM pg_class WHERE oid = to_regclass('public.' || t.n)), false),
               EXISTS (SELECT 1 FROM information_schema.columns c
                       WHERE c.table_schema = 'public' AND c.table_name = t.n AND c.column_name = 'client_id'),
               (SELECT array_to_string(array_agg(p.policyname ORDER BY p.policyname), ',')
                  FROM pg_policies p WHERE p.schemaname = 'public' AND p.tablename = t.n)
          FROM unnest({arr}) AS t(n) ORDER BY 1""")
    return {n: {"exists": ex == "t", "rls": rls == "t", "client_id": cid == "t", "policies": set(filter(None, pol.split(",")))}
            for n, ex, rls, cid, pol in rows}


@pg
def test_074_every_table_it_named_is_protected_or_is_a_named_exception(db):
    t074, _ = _lists()
    facts = _facts(db, t074)
    for name in NO_CLIENT_COLUMN:
        assert facts[name]["exists"] and not facts[name]["client_id"], (
            f"{name} now has a client_id column: it is no longer an exception, give it 074's policy and take it off the list")
    for name in NEVER_EXISTED_074:
        assert not facts[name]["exists"], f"{name} exists now: take it off the list and give it 074's policy"
    for name in CREATED_AFTER_074_COVERED_BY_THE_ASSIGNMENT_SCOPE:
        f = facts[name]
        assert f["exists"] and f["rls"] and f["client_id"], name
        assert f"{name}_internal_partner_only" not in f["policies"], f"{name} has 074's policy now: take it off the list"
        # What covers it instead: a restrictive policy that asks the assignment (bank_accounts_assignment_scope) or
        # a per-person tier that carries the same assignment test (salary_structures_*_tier).
        assert f["policies"] & {f"{name}_assignment_scope", f"{name}_read_tier"}, (
            f"{name} lost the rule that covers the internal practice: {sorted(f['policies'])}")
    exceptions = NO_CLIENT_COLUMN | NEVER_EXISTED_074 | CREATED_AFTER_074_COVERED_BY_THE_ASSIGNMENT_SCOPE
    for name in t074:
        if name in exceptions:
            continue
        f = facts[name]
        assert f["exists"] and f["rls"] and f["client_id"], f"{name}: {f}"
        assert f"{name}_internal_partner_only" in f["policies"], f"{name} lost 074's policy: {sorted(f['policies'])}"


@pg
def test_154_every_table_it_named_is_isolated_by_firm_or_never_existed(db):
    _, t154 = _lists()
    facts = _facts(db, t154)
    for name in NEVER_EXISTED_154:
        assert not facts[name]["exists"], f"{name} exists now: take it off the list and give it a firm policy"
    for name in t154:
        if name in NEVER_EXISTED_154:
            continue
        f = facts[name]
        assert f["exists"] and f["rls"], f"{name}: {f}"
        assert f"{name}_firm_isolation" in f["policies"], f"{name} lost 154's policy: {sorted(f['policies'])}"


@pg
def test_076_and_078_each_added_the_foreign_key_their_guard_wraps(db):
    rows = _rows(db, """
        SELECT conname, conrelid::regclass::text, confrelid::regclass::text FROM pg_constraint
         WHERE conname IN ('client_sales_invoices_journal_entry_id_fkey', 'time_entries_billed_invoice_id_fkey')
         ORDER BY 1""")
    assert rows == [["client_sales_invoices_journal_entry_id_fkey", "client_sales_invoices", "journal_entries"],
                    ["time_entries_billed_invoice_id_fkey", "time_entries", "client_sales_invoices"]]
