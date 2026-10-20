"""Every reader of a client's bank lines is a known one, and each says whose access it reads with (POST-A-005, migration 524).

WHY A LIST
    Migration 524 makes the database ask `banking:read` of a signed-in person who reads the six tables below, and a
    read their tier hides comes back as ZERO ROWS. A reader that runs under the caller's own sign-in for someone who
    need not hold Banking therefore answers "none" for a client that has plenty, which is worse than a refusal. Two
    such readers existed when 524 was written (the health score and the GST return build) and both were found by
    reading, not by a test. This is the test: the files that read these tables are enumerated from the source, and a
    new one fails until somebody has decided which of the three kinds it is.

THE THREE KINDS
    banking module   Reached through `routers/banking.py`, whose routes all ask `banking:read` first (a router-level
                     dependency, `test_a_banking_route_also_asks_for_banking_read.py`) and then their own guard (one asks
                     `accounting:approve`, Partner only, see `test_the_banking_router_asks_the_banking_tier_on_every_route`).
                     A person without Banking is refused before any of these runs. Not ONLY through the router:
                     `bank_posting_service.settle_on_post` is also reached from `journal_posting_service._dispatch_deferred`
                     (the `accounting:approve` route, which runs on the SERVICE client, `routers/accounting._prod_db`, so the
                     policy never applies to it) and `bank_entry_service` from the trusted-rules job, which is listed
                     below as a service-client reader.
    service client   Reads with the server's own client and not the caller's, so row security does not apply and the
                     caller's tier cannot hide a row: the access to the client is checked, or the job is the firm's.
    chosen reader    Outside the banking module AND under a route anyone with another permission can reach, so it
                     CHOOSES the service client for the one fact it needs (`_bank_db` in the health router,
                     `_service_db() or db` in the return builder), after the route has checked the caller's access to
                     the client. Proved by `test_a_health_score_and_a_return_read_the_bank_lines_with_the_servers_access.py`.

RULE, NOT SPELLING
    The scan finds a table name used as the first argument of ANY call (`.table("x")`, `from_("x")`, a counting helper)
    or as the value of a `"table"` key, so a reader written through a helper is found as readily as a direct one. It
    does not see a name assembled at run time, which none of the files use.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

API = Path(__file__).resolve().parents[1]
MIGRATION = next((API / "migrations").glob("524_the_database_asks_the_banking_tier_*_read.sql"))

#: The six tables migration 524 puts a read tier on.
BANK_LINE_TABLES = {"bank_transactions", "bank_statements", "bank_transaction_splits",
                    "bank_reconciliations", "bank_reconciliation_matches", "bank_matching_rules"}

#: Two database functions that read these tables with the CALLER's rights (`LANGUAGE sql STABLE SECURITY INVOKER`, migrations
#: 353 and 356), so a call to one is a read under the caller's sign-in exactly as a table read is, and the policy hides rows from
#: it the same way. Watched by name for that reason; both are called only from the banking module today.
INVOKER_RIGHTS_FUNCTIONS = {"bank_register", "bank_reconciling_items"}
WATCHED_NAMES = BANK_LINE_TABLES | INVOKER_RIGHTS_FUNCTIONS

BANKING_MODULE = {
    "routers/banking.py",
    "services/bank_batch_service.py", "services/bank_candidate_search_service.py", "services/bank_entry_service.py",
    "services/bank_exception_service.py", "services/bank_matching_service.py", "services/bank_payee_service.py",
    "services/bank_posting_service.py", "services/bank_reconciliation_service.py", "services/bank_register_service.py",
    "services/bank_split_service.py", "services/bank_transfer_service.py", "services/banking_service.py",
}
SERVICE_CLIENT = {
    "jobs/bank_trusted_rules_job.py",        # the nightly sweep, a job of the firm and not of a person
    "services/first_run_service.py",         # the first-day checklist, `service_db` after the access check
    "services/hub_service.py",               # the hub's tile counts, `service_db`, narrowed to the caller's clients
    "services/hub_worklist_service.py",      # the hub's worklists, `service_db`
    "services/reconciliation_service.py",    # "Verify Books": the router hands it `get_service_supabase()`
}
CHOSEN_READER = {
    "routers/health.py",                     # `_bank_db`
    "services/gst_return_service.py",        # `_service_db() or db` in `_bank_lines_declaring_gst`
}


def _readers() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in API.rglob("*.py"):
        rel = path.relative_to(API).as_posix()
        if rel.startswith(("tests/", "scripts/", "venv/", ".venv/")) or "/site-packages/" in rel:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
                    and node.args[0].value in WATCHED_NAMES:
                found.setdefault(rel, set()).add(node.args[0].value)
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values, strict=True):
                    if isinstance(key, ast.Constant) and key.value == "table" and isinstance(value, ast.Constant) \
                            and value.value in BANK_LINE_TABLES:
                        found.setdefault(rel, set()).add(value.value)
    return found


def test_the_tables_are_the_ones_migration_524_puts_a_read_tier_on():
    named = set(re.findall(r"CREATE POLICY \"[a-z_]+\" ON public\.([a-z_]+)", MIGRATION.read_text()))
    assert named == BANK_LINE_TABLES, (
        f"migration 524 puts a read tier on {sorted(named)} and this guard watches {sorted(BANK_LINE_TABLES)}")


def test_the_invoker_rights_functions_exist_and_read_the_tables():
    """The two names watched above are real functions that read a watched table, so the list cannot rot into a comment.
    The LAST migration that defines each is the live definition (`CREATE OR REPLACE` replaces the whole body)."""
    files = [p for p in sorted((API / "migrations").glob("*.sql")) if not p.name.endswith("_rollback.sql")]
    for name in INVOKER_RIGHTS_FUNCTIONS:
        pattern = re.compile(rf"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+public\.{name}\s*\(", re.I)
        defining = [p for p in files if pattern.search(p.read_text())]
        assert defining, f"no migration defines public.{name}: remove it from INVOKER_RIGHTS_FUNCTIONS"
        text = defining[-1].read_text()
        start = [m.start() for m in pattern.finditer(text)][-1]
        body = text[start:start + 8000]
        assert any(t in body for t in BANK_LINE_TABLES), f"public.{name} no longer reads a watched table"
        assert "SECURITY DEFINER" not in body.split("$$")[0].upper(), (
            f"public.{name} now runs as its owner: it no longer reads with the caller's rights, so it can leave this list")


def test_the_scan_sees_a_call_to_an_invoker_rights_function_as_a_read():
    """A call to `bank_register` or `bank_reconciling_items` is a read under the caller's sign-in, so the scan above must report it
    (otherwise a new caller outside the banking module would pass without anybody deciding which kind it is). Both are called today
    from the register and reconciliation services, which must therefore show up as readers of those names."""
    readers = _readers()
    assert "bank_register" in readers.get("services/bank_register_service.py", set()), readers.get("services/bank_register_service.py")
    assert "bank_reconciling_items" in readers.get("services/bank_reconciliation_service.py", set()), (
        readers.get("services/bank_reconciliation_service.py"))


def test_every_reader_of_the_bank_line_tables_is_a_known_one():
    readers = _readers()
    known = BANKING_MODULE | SERVICE_CLIENT | CHOSEN_READER
    assert len(readers) >= 15, "the scan found almost no reader: it is reading nothing"
    assert set(readers) == known, (
        f"unknown readers of the bank line tables: {sorted(set(readers) - known)}; "
        f"entries that no longer read one: {sorted(known - set(readers))}. A reader the banking router does not "
        "guard runs under the caller's own sign-in, where migration 524 hides a blocked person's bank lines as ZERO "
        "ROWS. Decide whether the caller must hold banking:read (then it belongs in the banking module, behind "
        "rbac('banking', …)) or needs the fact whatever their tier (then it reads through the service client after "
        "assert_client_access, as the health score and the GST return do), and add it to the right set here.")


def test_the_three_kinds_are_disjoint():
    assert not (BANKING_MODULE & SERVICE_CLIENT or BANKING_MODULE & CHOSEN_READER or SERVICE_CLIENT & CHOSEN_READER)


def test_the_banking_router_asks_the_banking_tier_on_every_route():
    """A person without `banking:read` or `banking:write` is refused before a banking service runs. The one exception
    is the Partner-only reopen of a completed reconciliation, gated by `accounting:approve`; the router-level
    `banking:read` dependency still sits in front of it, so a Partner who has blocked THEIR OWN Banking read is refused
    at the door, a refusal and not a wrong figure."""
    tree = ast.parse((API / "routers" / "banking.py").read_text())
    ungated: list[str] = []
    routes = 0
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        is_route = any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                       and isinstance(d.func.value, ast.Name) and d.func.value.id == "router" for d in fn.decorator_list)
        if not is_route:
            continue
        routes += 1
        asks_banking = False
        for default in list(fn.args.defaults) + list(fn.args.kw_defaults):
            for call in ast.walk(default) if default is not None else []:
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "rbac" \
                        and call.args and isinstance(call.args[0], ast.Constant) and call.args[0].value == "banking":
                    asks_banking = True
        if not asks_banking:
            ungated.append(fn.name)
    assert routes >= 60, "the scan found almost no banking route: it is reading nothing"
    assert ungated == ["reopen_reconciliation"], (
        f"routes in routers/banking.py that do not ask rbac('banking', …): {ungated}")
