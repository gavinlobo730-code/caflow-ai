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

    missing = [
        f"{table}.{col}"
        for table, cols in expected.items()
        for col in sorted(cols)
        if col not in actual.get(table, set())
    ]
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
