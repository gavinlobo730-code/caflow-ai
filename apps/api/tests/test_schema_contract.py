"""
Schema contract test (database-free).

Purpose
-------
Statically prove that every Supabase table and RPC the backend references in
`.table("X")` / `.rpc("Y")` calls is actually defined by SOME migration in
apps/api/migrations/. This is the guard that would have caught audit finding
F5 (~13 tax/compliance tables — einvoice_records, eway_bill_records,
xbrl_packages, itr_filings, … — used by code but created by no migration, so
every production call 500s with "relation does not exist") and the missing
`increment_message_count` RPC from F19.

It needs no database: it greps the migration DDL text, so it is immune to
migration apply-ordering drift (a separate concern covered by
test_migrations_apply.py). It runs in the normal CI job.

How it works
------------
1. Collect every table name from `.table("...")` calls in apps/api (excluding
   tests and this file's own tooling).
2. Collect every table created by any migration: CREATE TABLE, plus
   CREATE VIEW / CREATE MATERIALIZED VIEW (code reads views like table()), and
   ALTER TABLE targets (defensive).
3. Assert code-referenced tables ⊆ created tables, allowing a small,
   EXPLICITLY DOCUMENTED baseline of known-missing tables (the F5 backlog) so
   the test is green today but fails the moment a NEW phantom table is
   introduced. The baseline is expected to shrink to empty as R2.2 lands.
4. Same for `.rpc("...")` vs CREATE FUNCTION.

Postgres/Supabase built-in tables (auth.*, storage.*, pg_*) are ignored.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"

# Directories whose .table()/.rpc() calls define the contract.
CODE_DIRS = ["routers", "services", "repositories", "domain", "jobs", "core"]

# ── Known gaps (documented drift backlog) ────────────────────────────────────
# Tables/RPCs the code references that NO migration creates. Each is a real
# defect (audit F5 / F19) scheduled under roadmap R2.2 (create the missing
# tables) / R2.8 (create the missing RPC). This test PINS the current set so it
# stays green while blocking any NEW phantom reference; shrink these lists as
# the backing migrations land. DO NOT add to these lists to make a new failure
# pass — add the migration instead.
KNOWN_MISSING_TABLES: set[str] = {
    # F5 — tax/compliance record tables with no CREATE TABLE anywhere.
    "itr_filings",
    "itr_filing_versions",
    "tax_computation_snapshots",
    "tax_disallowances",
    "tax_deduction_claims",
    "brought_forward_losses",
    "einvoice_records",
    "eway_bill_records",
    "xbrl_packages",
    "gst_sync_jobs",
    "gst_portal_snapshots",
    "form_26as_records",
    "form_26as_reconciliations",
    # F9 — year-end routers target tables the migration (067) never creates; it
    # created year_end_checklists / notes_to_accounts instead. R2.1 reconciles.
    "year_end_checklist_items",
    "year_end_notes",
    "year_end_review_events",
    # Tally migration (audit: broken in prod) — jobs/items tables never created.
    "tally_migration_jobs",
    "tally_migration_items",
    # Onboarding checklist + invite tables referenced by routers, never created.
    "onboarding_checklists",
    "onboarding_checklist_steps",
    "pending_invites",
    # Health-dashboard aggregation reads over tables that don't exist under
    # these names (gst_returns vs gstr1_returns/gstr3b_returns; notices vs
    # government_notices; work_items). These health endpoints 500 in prod.
    "gst_returns",
    "notices",
    "work_items",
    # Relationship-intelligence reads over non-existent tables.
    "entity_to_entity_relationships",
    "properties",
    # Portal session tracking table referenced by health router, never created.
    "client_portal_sessions",
}
KNOWN_MISSING_RPCS: set[str] = {
    # F19 — copilot message-count increment RPC referenced but never defined.
    "increment_message_count",
    # F5 — cash-payment threshold RPC referenced by the ITR computation workspace.
    "get_cash_payments_above_threshold",
}

# Supabase/Postgres-managed schemas and internal relations code may touch.
_IGNORE_TABLE_PREFIXES = ("auth.", "storage.", "pg_", "information_schema.", "realtime.")
_IGNORE_TABLES = {
    "pg_class", "pg_tables", "pg_catalog", "pg_stat_activity",
}

_TABLE_CALL = re.compile(r"""\.table\(\s*["']([a-zA-Z0-9_.]+)["']""")
_RPC_CALL = re.compile(r"""\.rpc\(\s*["']([a-zA-Z0-9_.]+)["']""")
_CREATE_TABLE = re.compile(
    r"""create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?["']?([a-zA-Z0-9_]+)["']?""",
    re.IGNORECASE,
)
_CREATE_VIEW = re.compile(
    r"""create\s+(?:or\s+replace\s+)?(?:materialized\s+)?view\s+(?:if\s+not\s+exists\s+)?(?:public\.)?["']?([a-zA-Z0-9_]+)["']?""",
    re.IGNORECASE,
)
_CREATE_FUNC = re.compile(
    r"""create\s+(?:or\s+replace\s+)?function\s+(?:public\.)?["']?([a-zA-Z0-9_]+)["']?""",
    re.IGNORECASE,
)


def _iter_code_files():
    for d in CODE_DIRS:
        yield from (API_ROOT / d).rglob("*.py")


def _referenced(pattern: re.Pattern) -> dict[str, list[str]]:
    """name -> list of 'file:line' where it is referenced."""
    out: dict[str, list[str]] = {}
    for f in _iter_code_files():
        try:
            text = f.read_text()
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for name in pattern.findall(line):
                out.setdefault(name, []).append(f"{f.relative_to(API_ROOT)}:{i}")
    return out


def _defined(patterns: list[re.Pattern]) -> set[str]:
    names: set[str] = set()
    for f in MIGRATIONS.glob("*.sql"):
        if "rollback" in f.name:
            continue
        text = f.read_text()
        for pat in patterns:
            names.update(n.lower() for n in pat.findall(text))
    return names


def _is_ignored_table(name: str) -> bool:
    low = name.lower()
    if low in _IGNORE_TABLES:
        return True
    return any(low.startswith(p) for p in _IGNORE_TABLE_PREFIXES)


def test_all_referenced_tables_have_a_migration():
    referenced = _referenced(_TABLE_CALL)
    created = _defined([_CREATE_TABLE, _CREATE_VIEW])

    missing: dict[str, list[str]] = {}
    for name, sites in referenced.items():
        if _is_ignored_table(name):
            continue
        base = name.split(".")[-1].lower()
        if base in created:
            continue
        if base in {t.lower() for t in KNOWN_MISSING_TABLES}:
            continue
        missing[name] = sites[:3]

    assert not missing, (
        "Code references tables that NO migration creates (new schema drift — add "
        "a CREATE TABLE migration, do not extend KNOWN_MISSING_TABLES):\n"
        + "\n".join(f"  {t}  <- {', '.join(sites)}" for t, sites in sorted(missing.items()))
    )


def test_all_referenced_rpcs_have_a_migration():
    referenced = _referenced(_RPC_CALL)
    created = _defined([_CREATE_FUNC])

    missing: dict[str, list[str]] = {}
    for name, sites in referenced.items():
        base = name.split(".")[-1].lower()
        if base in created:
            continue
        if base in {r.lower() for r in KNOWN_MISSING_RPCS}:
            continue
        missing[name] = sites[:3]

    assert not missing, (
        "Code calls RPCs that NO migration defines (add a CREATE FUNCTION "
        "migration, do not extend KNOWN_MISSING_RPCS):\n"
        + "\n".join(f"  {r}  <- {', '.join(sites)}" for r, sites in sorted(missing.items()))
    )


def test_known_missing_baseline_is_still_missing():
    """Ratchet: once a backlog table/RPC gets a migration, it must be REMOVED
    from the KNOWN_MISSING_* set (not left to rot). This test fails if a
    baselined name is now actually created, forcing the list to shrink."""
    created_tables = _defined([_CREATE_TABLE, _CREATE_VIEW])
    created_funcs = _defined([_CREATE_FUNC])

    resurrected_tables = {t for t in KNOWN_MISSING_TABLES if t.lower() in created_tables}
    resurrected_rpcs = {r for r in KNOWN_MISSING_RPCS if r.lower() in created_funcs}

    assert not resurrected_tables and not resurrected_rpcs, (
        "These are now created by a migration — remove them from the KNOWN_MISSING "
        f"baseline: tables={sorted(resurrected_tables)} rpcs={sorted(resurrected_rpcs)}"
    )
