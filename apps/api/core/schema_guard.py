"""
Boot-time schema-drift guard (task #244).

Root cause this closes: application code and its Postgres migrations deploy
on two INDEPENDENT tracks. Render redeploys the Docker image automatically on
every push to main; nothing applies apps/api/migrations/*.sql to the live
Supabase project automatically -- that has always been a separate, manual
step. Migrations 233-241 sat committed and CI-validated (against a throwaway
Postgres, never the real one) but unapplied to production for up to 6 days,
while the code that depended on them was already live -- every affected write
silently failed behind a broad try/except and returned a generic error, with
nothing anywhere surfacing the real cause.

This module closes the "silent" half of that failure mode: it derives, from
the migration files themselves, the set of columns the currently-deployed
code expects to exist, checks them against the live database via the
get_public_columns() RPC (migration 242), and -- if anything is missing --
fails the /health endpoint. Render's healthCheckPath gates whether a new
deploy is ever cut over to live traffic, so a deploy that depends on an
unapplied migration now fails its own health check instead of going live and
silently corrupting data for weeks.

Deliberately does NOT gate the OTHER half (getting the migration applied) --
that is scripts/db/apply_migrations.py, wired into CI (see
.github/workflows/backend-ci.yml's `deploy-migrations` job) so drift should
never reach this check in the normal path. This is the defense-in-depth
backstop for when it does anyway (a hotfix pushed with --no-verify, a
migration edited after merge, the DB push step itself failing, etc).

WHY THERE IS AN EXCLUSION LIST BELOW
    "Every ADD COLUMN in the migration history is a column the deployed code
    depends on" is an approximation, and for 17 of 477 parsed columns it is
    false. Production superseded those migrations rather than applying them --
    with different table names in three cases, and with relationship-based RLS
    instead of a denormalised firm_id in three more.

    Left unlisted, they made this guard report drift on every boot, which meant
    /health returned 503 CONTINUOUSLY. A permanently-red health check is worse
    than no health check: Render's healthCheckPath can never cut a deploy over,
    and genuine new drift is indistinguishable from the standing 17. The guard
    was, in that state, protecting nothing.

    So each exclusion below states the evidence for why the column is not a
    dependency, and tests/test_schema_guard_superseded.py fails if an entry goes
    stale (the table comes back into use) or if the lists grow.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

_logger = logging.getLogger("caflow.schema_guard")

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"

# Matches one ALTER TABLE ... ; statement (possibly multi-line, possibly with
# several comma-separated ADD COLUMN clauses) and captures the table name plus
# everything up to the terminating semicolon.
_ALTER_TABLE_BLOCK = re.compile(
    r"ALTER TABLE\s+(?:public\.)?(?:ONLY\s+)?(\w+)\b(.*?);",
    re.IGNORECASE | re.DOTALL,
)
_ADD_COLUMN = re.compile(r"ADD COLUMN\s+IF NOT EXISTS\s+(\w+)", re.IGNORECASE)

# Tables some migration adds columns to that this database does not have and no
# live code queries. Every one was verified against the production catalog
# (information_schema.tables) and against a repo-wide search for
# `.table("<name>")` / `.from("<name>")` across apps/api and apps/web.
#
# Creating them to satisfy this guard would be the wrong repair: it would produce
# a second, permanently-empty copy of data that already lives elsewhere, turning
# a loud absence into a silent wrong answer.
SUPERSEDED_TABLES: dict[str, str] = {
    "notes_to_accounts":
        "Production stores year-end notes in `year_end_notes` — the name a "
        "divergent Studio migration gave the table. Migration 252's header "
        "records the decision to repoint the routers rather than create a "
        "duplicate; the last frontend query still naming the old table was "
        "fixed too. Creating it would give the Notes tab an empty second home.",
    "year_end_reviews":
        "Same divergence as notes_to_accounts: production's table is "
        "`year_end_review_events`, carrying the event_type and actor_id columns "
        "migration 155 declares here. Both readers were repointed at it, so the "
        "old name is queried by nothing in apps/api or apps/web.",
    "transactions":
        "Never created in this database. The posted ledger is journal_entries + "
        "journal_lines, which every report, the passbook and the GST engine read; "
        "the columns migration 006/007 declare here (supply_type, invoice_type, "
        "cess_paise …) live on client_sales_invoices and purchase_bills instead. "
        "No code names this table.",
    "transaction_lines":
        "The child half of the same superseded design — journal_lines is the live "
        "line table. Its cess_paise equivalent is on the invoice/bill line tables. "
        "No code names this table.",
}

# "table.column" pairs where the TABLE is live and correct but the column was
# superseded. All three are migration 008's denormalised firm_id: production
# isolates each of these tables by relationship instead, which cannot go stale
# the way a copied firm_id can. The policies below were read from pg_policy on
# the live database, not inferred from migration files.
SUPERSEDED_COLUMNS: dict[str, str] = {
    "filings.firm_id":
        "Isolated by relationship, not by a copied firm_id. Live policy "
        "`firm_isolation` is EXISTS(clients c WHERE c.id = filings.client_id AND "
        "c.firm_id = get_my_firm_id()), alongside `filings_assignment_scope` on "
        "can_access_client(client_id). No code reads filings.firm_id.",
    "automation_executions.firm_id":
        "Live policy `firm_isolation` is EXISTS(automation_rules ar WHERE "
        "ar.id = automation_executions.rule_id AND ar.firm_id = get_my_firm_id()), "
        "with a matching WITH CHECK. repositories/automation_repository.py agrees: "
        "it scopes reads through automation_rules by rule_id and its insert payload "
        "has no firm_id, so the column would be NULL on every row forever.",
    "permission_grants.firm_id":
        "Isolated per USER, which is narrower than per firm: live policy "
        "`user_isolation` is (user_id = auth.uid() OR granted_by = auth.uid()), "
        "with WITH CHECK (granted_by = auth.uid()). A firm_id here would widen "
        "nothing and is read by no code.",
}


def _superseded(table: str, column: str) -> bool:
    return table in SUPERSEDED_TABLES or f"{table}.{column}" in SUPERSEDED_COLUMNS


def expected_columns_from_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> dict[str, set[str]]:
    """Parse every `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...;` statement
    across all migration files into {table_name: {column_name, ...}}.

    Deliberately covers only this one statement shape -- it's the dominant
    pattern this codebase's migrations use for additive schema changes (see
    migrations 233-241, all nine of which used it). A false negative here (a
    column added some other way, e.g. inside a CREATE TABLE) only means this
    guard doesn't check that column -- it can never cause a false "missing"
    report, since the check only ever looks for columns this parser found.
    """
    expected: dict[str, set[str]] = {}
    if not migrations_dir.exists():
        return expected
    for path in sorted(migrations_dir.glob("*.sql")):
        if path.name.startswith("_"):
            continue
        text = path.read_text(errors="ignore")
        for table, body in _ALTER_TABLE_BLOCK.findall(text):
            cols = _ADD_COLUMN.findall(body)
            if cols:
                expected.setdefault(table.lower(), set()).update(c.lower() for c in cols)
    return expected


def check_schema_drift(db) -> dict:
    """Diffs expected_columns_from_migrations() against the live database's
    actual public-schema columns (via the get_public_columns() RPC, migration
    242).

    Returns {"checked": bool, "missing": ["table.column", ...]}. `checked` is
    False whenever the RPC itself couldn't be reached (network hiccup, or the
    RPC doesn't exist yet on a database older than migration 242) -- a
    connectivity failure must never be misreported as confirmed drift.
    """
    expected = expected_columns_from_migrations()
    if not expected:
        return {"checked": True, "missing": []}
    try:
        resp = db.rpc("get_public_columns", {}).execute()
        rows = resp.data or []
    except Exception as e:
        _logger.warning(
            "schema_guard: could not reach get_public_columns() RPC — skipping drift check (%s)", e
        )
        return {"checked": False, "missing": []}

    actual: dict[str, set[str]] = {}
    for row in rows:
        actual.setdefault(row["table_name"].lower(), set()).add(row["column_name"].lower())

    missing: list[str] = []
    skipped: list[str] = []
    for table, cols in expected.items():
        for col in sorted(cols):
            if col in actual.get(table, set()):
                continue
            (skipped if _superseded(table, col) else missing).append(f"{table}.{col}")

    if skipped:
        # INFO, not silence: an exclusion that nobody can see is indistinguishable
        # from a guard that does not check. One line at boot names every skipped
        # expectation, so the list is auditable from the log without reading code.
        _logger.info(
            "schema_guard: %d expectation(s) skipped as superseded (see "
            "SUPERSEDED_TABLES / SUPERSEDED_COLUMNS): %s",
            len(skipped), ", ".join(sorted(skipped)),
        )
    return {"checked": True, "missing": missing}


def run_startup_check() -> dict:
    """Called once at boot (main.py). Never raises -- a broken check must not
    crash the app (same non-fatal posture as core/config_validation.py). Logs
    CRITICAL with the exact missing list so it's impossible to miss in
    Render's log stream, in addition to driving /health.

    Skipped entirely when SUPABASE_URL isn't set (test/mock mode — there is no
    real database to check).
    """
    if not os.environ.get("SUPABASE_URL"):
        return {"checked": False, "missing": []}
    try:
        from core.supabase_client import get_supabase
        result = check_schema_drift(get_supabase())
    except Exception as e:
        _logger.warning("schema_guard: startup check failed to run (%s)", e)
        return {"checked": False, "missing": []}

    if result["missing"]:
        _logger.critical(
            "SCHEMA DRIFT: %d column(s) the deployed code depends on are missing from "
            "the live database — a migration was committed but never applied: %s",
            len(result["missing"]), ", ".join(result["missing"]),
        )
    return result
