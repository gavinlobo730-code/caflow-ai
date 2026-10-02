"""
Boot-time schema-drift guard (task #244).

Root cause this closes: application code and its Postgres migrations deploy
on two INDEPENDENT tracks. Render redeploys the Docker image automatically on
every push to main; until task #244 nothing applied apps/api/migrations/*.sql
to the live Supabase project automatically -- that was a separate, manual
step, and it is now the `deploy-migrations` job in backend-ci.yml (see below).
Migrations 233-241 sat committed and CI-validated (against a throwaway
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

THE CHECK HEALS, AND IT LOOKS AT MORE THAN COLUMNS (ops-19)
    Two gaps were left in the guard above, and neither is about what it already
    does well.

    1. IT RAN ONCE. main.py computed the verdict at boot and never again, so a
       deploy that booted in the minutes before its migration landed answered 503
       until the NEXT restart, long after the migration had arrived: a false alarm
       that outlived its cause and could only be cleared by redeploying. Now,
       while the verdict is "drifted" or "not yet checked", `start_drift_watch`
       asks again on a timer (RECHECK_INTERVAL_SECONDS) and hands each answer to
       the same global /health reads, so the 503 clears by itself when the
       migration applies. It stops at the first clean answer and never starts
       again: a check that could newly turn a healthy instance's /health into a
       503 hours after it booted is a new way to take the API down, and this one
       only ever moves a verdict TOWARDS healthy. "Not yet checked" is still
       never a 503.
    2. IT KNEW ONLY `ADD COLUMN IF NOT EXISTS`. A migration that creates a table
       or a function and adds no column produced no expectation at all, so code
       calling it against a database that lacked it passed the guard and failed
       on first use. `check_schema_objects` takes the other side of that:
       the tables the code names in `.table("…")` and the functions it names in
       `.rpc("…")`, read from the source that is running, against the live
       catalogue (tables from the same single-row read as the columns, functions
       from get_public_schema_functions, migration 475).

    THE OBJECT CHECK REPORTS AND DOES NOT YET GATE, and the line between those is
    OBJECT_DRIFT_FAILS_HEALTH. Everything this module has learned about being
    permanently red applies to a new class of expectation: against the last
    production snapshot (tests/fixtures/production_schema_*.json) every table the
    code names exists or is created by a migration after the snapshot, which is
    measured. The function list is not: there is no snapshot of functions, so what
    production holds is unread, and a /health that answers 503 because of something
    nobody could measure pulls the service. So the verdict is on /health as
    `schema_objects` and is logged at CRITICAL (which Sentry receives), and the
    switch to refuse traffic on it is one constant, flipped by a person who has read
    that field on production and found it empty.
"""
from __future__ import annotations

import functools
import logging
import os
import re
import threading
from pathlib import Path
from typing import Callable, Optional

_logger = logging.getLogger("caflow.schema_guard")

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = API_ROOT / "migrations"

#: How often the verdict is asked again while it is "drifted" or "not checked".
#: Minutes, not seconds: one catalogue read each, and a migration lands in the
#: minutes after a merge, so two minutes is the longest a stale 503 can outlive it.
RECHECK_INTERVAL_SECONDS = 120.0

#: Whether a table or function the code calls and the database lacks makes /health
#: answer 503. OFF, for the reason in the module docstring; flip it after reading
#: `schema_objects` on production and finding nothing missing.
OBJECT_DRIFT_FAILS_HEALTH = False

#: Where the code that CALLS the database lives. The directories
#: tests/test_schema_contract.py reads, plus the two it leaves out.
CODE_DIRS = ("routers", "services", "repositories", "domain", "jobs", "core", "middleware", "models")

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


def live_columns(db) -> Optional[dict[str, set[str]]]:
    """The live public schema as {table: {column, ...}}, or None when it could
    not be read IN FULL.

    None is the important return value, and the reason this function exists.

    The previous read used get_public_columns() (migration 242), which returns
    one row per column. This schema has 3531 of them and PostgREST caps a
    response at 1000, so the guard received the first 1000 rows and treated them
    as the whole schema — reporting 401 existing columns as missing, including
    clients.firm_id, which every tenant-isolation policy is built on. The cut
    landed mid-table (form_26as_uploads.parse_errors "present" at row 922,
    parse_status "missing" at row 3073), which is what a row limit looks like and
    what real drift does not.

    So the failure was not the truncation itself — it was that a truncated read
    was indistinguishable from a complete one, and the code stated a confident
    conclusion from partial data. get_public_schema_columns() (migration 265)
    returns a SINGLE row, which a row limit cannot cut, and reports
    total_columns computed independently of the map so completeness can be
    PROVEN rather than assumed. Anything that fails that proof returns None, and
    the caller reports "not checked" instead of inventing drift.
    """
    try:
        resp = db.rpc("get_public_schema_columns", {}).execute()
    except Exception as e:  # noqa: BLE001 — unreachable RPC must never read as drift
        _logger.warning(
            "schema_guard: get_public_schema_columns() unavailable — skipping drift "
            "check. Apply migration 265 if this persists. (%s)", e,
        )
        return None

    # PostgREST hands back the scalar for a scalar-returning function; some
    # client versions wrap it in a single-element list. Accept both, refuse
    # anything else rather than guessing at a shape.
    payload = resp.data
    if isinstance(payload, list):
        payload = payload[0] if len(payload) == 1 else None
    if not isinstance(payload, dict):
        _logger.warning("schema_guard: unexpected introspection payload — skipping drift check")
        return None

    tables = payload.get("tables")
    declared_total = payload.get("total_columns")
    if not isinstance(tables, dict) or not isinstance(declared_total, int):
        _logger.warning("schema_guard: malformed introspection payload — skipping drift check")
        return None

    actual: dict[str, set[str]] = {}
    for table, cols in tables.items():
        if not isinstance(cols, list):
            _logger.warning("schema_guard: malformed column list for %s — skipping", table)
            return None
        actual[str(table).lower()] = {str(c).lower() for c in cols}

    # The completeness proof. Counted from the map we actually parsed, against a
    # total the database computed separately. A mismatch means we did not receive
    # what the database has, and the only honest answer then is "don't know".
    received = sum(len(cols) for cols in actual.values())
    if received != declared_total:
        _logger.error(
            "schema_guard: INCOMPLETE schema read — parsed %d column(s), database "
            "reports %d. Refusing to report drift from a partial read.",
            received, declared_total,
        )
        return None

    return actual


_UNREAD = object()


def check_schema_drift(db, actual=_UNREAD) -> dict:
    """Diffs expected_columns_from_migrations() against the live database's
    actual public-schema columns.

    Returns {"checked": bool, "missing": ["table.column", ...]}. `checked` is
    False whenever the schema could not be read IN FULL -- an unreachable RPC, a
    database older than migration 265, or a read that fails its own completeness
    check. None of those is evidence of drift, and reporting them as drift is
    exactly what made this guard useless for its first weeks of life.

    `actual` is the map live_columns() returned, for a caller that has already
    read it and wants the object check to use the SAME read; left out, it is read
    here as before. `None` is a real value (the read failed) and is not "left out".
    """
    expected = expected_columns_from_migrations()
    if not expected:
        return {"checked": True, "missing": []}

    if actual is _UNREAD:
        actual = live_columns(db)
    if actual is None:
        return {"checked": False, "missing": []}

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


# ── the tables and functions the code calls (ops-19) ───────────────────────────

_TABLE_CALL = re.compile(r"""\.table\(\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""")
_RPC_CALL = re.compile(r"""\.rpc\(\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""")


@functools.lru_cache(maxsize=8)
def _scan(root: str, dirs: tuple) -> tuple[frozenset, frozenset]:
    tables: set[str] = set()
    functions: set[str] = set()
    base = Path(root)
    this_file = Path(__file__).resolve()
    for d in dirs:
        for path in sorted((base / d).rglob("*.py")):
            # This file's own docstrings quote the call shapes it looks for.
            if path.resolve() == this_file:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            tables.update(m.lower() for m in _TABLE_CALL.findall(text))
            functions.update(m.lower() for m in _RPC_CALL.findall(text))
    return frozenset(tables), frozenset(functions)


def code_called_objects(root: Path = API_ROOT, dirs: tuple = CODE_DIRS) -> tuple[frozenset, frozenset]:
    """(tables, functions) the source under `root` names in `.table("…")` and
    `.rpc("…")` with a LITERAL name.

    Read from the running source, not from the migrations, and that is the
    point: a migration can create anything, and most of what 462 of them create
    nothing calls, or production replaced (SUPERSEDED_TABLES is what that cost
    for columns). What the code CALLS is what breaks when it is absent, and it
    needs no exclusion list, because code that names a table production lacks is
    the incident, not an approximation of it. A name passed in a variable is
    invisible here, which can only under-report.

    Regular expressions rather than the AST: parsing the 700 files takes about
    three seconds, the boot thread runs this before the scheduler starts, and
    tests/test_schema_guard_objects.py asserts the two methods find the same
    names on the real tree, so a docstring that quotes a call cannot slip in.
    """
    return _scan(str(root), tuple(dirs))


def live_functions(db) -> Optional[set[str]]:
    """The names of the functions in the live `public` schema, or None when they
    could not be read IN FULL.

    get_public_schema_functions() (migration 475) answers one jsonb row, so
    PostgREST's row cap cannot cut it, and `total_functions` is counted apart
    from the list so completeness is proven on every read, the lesson of
    live_columns(). None -- an unreachable RPC, a database older than 475, a
    malformed or incomplete answer -- is "not checked", never "missing".
    """
    try:
        resp = db.rpc("get_public_schema_functions", {}).execute()
    except Exception as e:  # noqa: BLE001 — an unreachable RPC must never read as drift
        _logger.warning(
            "schema_guard: get_public_schema_functions() unavailable — functions not checked. "
            "Apply migration 475 if this persists. (%s)", e,
        )
        return None
    payload = resp.data
    if isinstance(payload, list):
        payload = payload[0] if len(payload) == 1 else None
    if not isinstance(payload, dict):
        _logger.warning("schema_guard: unexpected function-list payload — functions not checked")
        return None
    names, declared = payload.get("functions"), payload.get("total_functions")
    if not isinstance(names, list) or not isinstance(declared, int):
        _logger.warning("schema_guard: malformed function-list payload — functions not checked")
        return None
    got = {str(n).lower() for n in names}
    if len(got) != declared:
        _logger.error(
            "schema_guard: INCOMPLETE function read — parsed %d name(s), database reports %d. "
            "Refusing to report drift from a partial read.", len(got), declared,
        )
        return None
    return got


def check_schema_objects(db, actual=_UNREAD, root: Path = API_ROOT, dirs: tuple = CODE_DIRS) -> dict:
    """The tables and functions the code names that the live database lacks.

    {"tables_checked": bool, "functions_checked": bool,
     "missing_tables": [...], "missing_functions": [...]}

    Each half is `checked` on its own: tables come from the same read the column
    check made (`actual`, passed in so the two cannot disagree), functions from
    their own RPC, and a database that answers one and not the other is half
    checked, not unchecked. A half that was not read reports nothing missing.
    """
    tables, functions = code_called_objects(root, dirs)
    if actual is _UNREAD:
        actual = live_columns(db)
    out = {"tables_checked": False, "functions_checked": False,
           "missing_tables": [], "missing_functions": []}
    if actual is not None:
        out["tables_checked"] = True
        out["missing_tables"] = sorted(t for t in tables if t not in actual)
    live = live_functions(db)
    if live is not None:
        out["functions_checked"] = True
        out["missing_functions"] = sorted(f for f in functions if f not in live)
    return out


_OBJECTS_LOCK = threading.Lock()
_OBJECTS: dict = {"tables_checked": False, "functions_checked": False,
                  "missing_tables": [], "missing_functions": []}


def object_drift() -> dict:
    """The latest object verdict, as a copy. Read by /health."""
    with _OBJECTS_LOCK:
        return {k: (list(v) if isinstance(v, list) else v) for k, v in _OBJECTS.items()}


def objects_pending(state: Optional[dict] = None) -> bool:
    """True while the object check has not been able to read everything, or has
    found something missing -- the states in which asking again can change the
    answer."""
    s = object_drift() if state is None else state
    return not (s["tables_checked"] and s["functions_checked"]) or bool(
        s["missing_tables"] or s["missing_functions"])


def _record_objects(db, actual) -> None:
    """Run the object check and keep the verdict. Never raises: a broken check
    must not take the column verdict, or the app, down with it."""
    try:
        state = check_schema_objects(db, actual=actual)
    except Exception as e:  # noqa: BLE001
        _logger.warning("schema_guard: object check failed to run (%s)", e)
        return
    with _OBJECTS_LOCK:
        previous = (list(_OBJECTS["missing_tables"]), list(_OBJECTS["missing_functions"]))
        _OBJECTS.update(state)
    if state["missing_tables"] or state["missing_functions"]:
        # Logged on the first sighting and whenever the list changes, not on every
        # re-check: a two-minute timer would otherwise write the same CRITICAL line
        # all day, and a log that repeats itself is a log nobody reads.
        if (state["missing_tables"], state["missing_functions"]) != previous:
            _logger.critical(
                "SCHEMA OBJECT DRIFT: the code calls %d table(s) and %d function(s) the live database "
                "lacks — a migration was committed but never applied. tables: %s; functions: %s",
                len(state["missing_tables"]), len(state["missing_functions"]),
                ", ".join(state["missing_tables"]) or "none",
                ", ".join(state["missing_functions"]) or "none",
            )


def run_startup_check() -> dict:
    """The column verdict, now and each time it is asked again. Never raises -- a
    broken check must not crash the app (same non-fatal posture as
    core/config_validation.py). Logs CRITICAL with the exact missing list so it's
    impossible to miss in Render's log stream, in addition to driving /health.

    It also refreshes the object verdict (object_drift()), from the same read of
    the schema. Its RETURN VALUE stays the two-key column verdict main.py and
    its tests have always compared against.

    Skipped entirely when SUPABASE_URL isn't set (test/mock mode — there is no
    real database to check).
    """
    if not os.environ.get("SUPABASE_URL"):
        return {"checked": False, "missing": []}
    try:
        from core.supabase_client import get_supabase
        db = get_supabase()
        actual = live_columns(db)
        result = check_schema_drift(db, actual=actual)
    except Exception as e:
        _logger.warning("schema_guard: startup check failed to run (%s)", e)
        return {"checked": False, "missing": []}

    _record_objects(db, actual)

    if result["missing"]:
        _logger.critical(
            "SCHEMA DRIFT: %d column(s) the deployed code depends on are missing from "
            "the live database — a migration was committed but never applied: %s",
            len(result["missing"]), ", ".join(result["missing"]),
        )
    return result


# ── asking again (ops-19) ──────────────────────────────────────────────────────

_WATCH_LOCK = threading.Lock()
_WATCH_THREAD: Optional[threading.Thread] = None
_WATCH_STOP = threading.Event()


def _healthy(result: dict) -> bool:
    return bool(result.get("checked")) and not result.get("missing")


def needs_watch(result: dict) -> bool:
    """Whether asking again can change anything: the column verdict is drifted or
    unread, or the object verdict has not read everything / found something.
    False in mock mode, where there is no database to ask."""
    if not os.environ.get("SUPABASE_URL"):
        return False
    return (not _healthy(result)) or objects_pending()


def start_drift_watch(
    initial: dict,
    apply: Callable[[dict], None],
    *,
    check: Optional[Callable[[], dict]] = None,
    interval: Optional[float] = None,
) -> Optional[threading.Thread]:
    """Re-run the check on a timer until it comes back clean, handing every answer
    to `apply` (main.py's setter for the global /health reads).

    WHAT IT WILL AND WILL NOT DO
      * It starts only when `needs_watch(initial)`; a boot that found everything
        in order starts nothing.
      * It ends at the first answer that is checked and clean (columns) and has
        nothing pending (objects), and nothing restarts it. So it can move a
        verdict from drifted or unread TO healthy and cannot move a healthy
        instance to a 503 hours later.
      * An exception in one round is logged and the next round tries again; the
        thread must not die of the thing it exists to wait out.
      * One watcher per process. A second call while one runs returns it.

    The thread is a daemon: it must never keep a worker alive past shutdown.
    """
    global _WATCH_THREAD
    if not needs_watch(initial):
        return None
    with _WATCH_LOCK:
        if _WATCH_THREAD is not None and _WATCH_THREAD.is_alive():
            return _WATCH_THREAD
        _WATCH_STOP.clear()
        thread = threading.Thread(
            target=_watch,
            args=(initial, apply, check or run_startup_check,
                  RECHECK_INTERVAL_SECONDS if interval is None else interval),
            name="schema-drift-watch", daemon=True)
        _WATCH_THREAD = thread
        thread.start()
        return thread


def stop_drift_watch(timeout: float = 5.0) -> None:
    """Stop the watcher and wait for it. For tests and for shutdown."""
    global _WATCH_THREAD
    _WATCH_STOP.set()
    with _WATCH_LOCK:
        thread, _WATCH_THREAD = _WATCH_THREAD, None
    if thread is not None and thread.is_alive():
        thread.join(timeout)


def _watch(initial: dict, apply, check, interval: float) -> None:
    last = initial
    rounds = 0
    while not _WATCH_STOP.wait(interval):
        rounds += 1
        try:
            result = check()
            apply(result)
        except Exception:  # noqa: BLE001 — one bad round must not end the watch
            _logger.exception("schema_guard: re-check round %d failed; will try again", rounds)
            continue
        if result != last:
            _logger.warning(
                "schema_guard: re-check %d — checked=%s, %d column(s) still missing",
                rounds, result.get("checked"), len(result.get("missing", [])))
            last = result
        if _healthy(result) and not objects_pending():
            _logger.info(
                "schema_guard: the database now matches the code (after %d re-check(s)); "
                "/health no longer reports drift and the watch has stopped.", rounds)
            return
