"""
Every RELATION and every RPC FUNCTION the backend names must actually exist.

WHY THIS FILE HAD TO BE WRITTEN, WHICH IS THE WHOLE POINT
    It was already CITED. Two modules skip the missing-relation case rather
    than report it, each naming this test as the one that covers it:

        test_backend_columns_exist_pg.py:38   (docstring)
            "a relation absent from the template is skipped — that is
             test_backend_tables_exist's job, and reporting it here would call
             one bug two."
        test_backend_inserts_supply_every_required_column_pg.py:46 (docstring)
        test_backend_inserts_supply_every_required_column_pg.py:151 (in code)
            `continue   # test_backend_tables_exist's job`

    test_backend_tables_exist did not exist. So the case both modules hand off
    was caught by nobody, and the hand-off is what made it invisible: each
    module reads as covered, and the reader who checks is reading a comment
    rather than a directory listing.

    That matters most under a RENAME. Rename a table in a migration and every
    stale reference to the old name stops being checked for its COLUMNS too —
    both guards skip a relation they cannot find — so the one change most
    likely to strand a query is the one that switches both checks off.

WHAT A MISSING NAME COSTS AT RUNTIME
    PostgREST rejects the statement at parse time — 42P01 for a relation,
    42883 for a function — before a row is considered. Most call sites in this
    codebase sit inside a broad `except Exception`, so the failure is total AND
    invisible: the endpoint answers HTTP 200 with success: false, or an empty
    list that reads as "no rows".

    apps/web has had this guard since /risks queried `dsc_tracker`, a relation
    that never existed. apps/api never did.

WHY IT READS THE REAL SCHEMA AND NOT THE MIGRATIONS
    Because replaying the migrations to decide what exists is a trap this
    repository has now fallen into twice, with the same victim both times:

      * test_frontend_tables_exist.py once claimed public.accounts was a
        missing relation. Its docstring carries the correction — accounts is a
        compatibility VIEW from migration 016, and the replay's CREATE pattern
        did not match views.
      * the sweep that led to this file said the same thing, for a different
        reason: migration 016 DROPs the view and recreates it a few lines
        later, and a scan that collects every CREATE and then every DROP loses
        the order and reads the pair as a deletion.

    A view, a materialized view, a rename and a drop-then-recreate are each
    enough to make a replay lie. information_schema is not a model of the
    schema; it is the schema.

WAS THE HAND-OFF BROKEN ANYWHERE ELSE?
    Checked, and no. Every `test_*` name any test module names in prose
    resolves to a file or to a function that exists, once elisions and
    line-wraps are discounted; the remainder are local variables and correct
    prose about a test since renamed. So this was the one orphaned hand-off,
    and it is deliberately NOT turned into a ratchet — a check on that would
    need a fourteen-entry exemption list on its first run, which is how a
    ratchet gets deleted rather than maintained.

WHAT IT STILL DOES NOT CHECK
    A name arriving as a variable. Those are counted and budgeted below rather
    than ignored, so the blind spot has a number on it — the discipline
    test_backend_columns_exist_pg.py's MAX_UNREADABLE established.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _backend_query_parser import (  # noqa: E402
    relation_refs,
    rpc_calls,
    unverifiable_functions,
    unverifiable_relations,
)
from test_migrations_apply import EXPECTED_MIGRATION_FAILURES  # noqa: E402

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="backend relation check requires HARNESS_PG + psql",
)

# Relations the backend may name that the schema does not have. Each needs a
# reason. EMPTY, and that is the state to defend: every one of the 249
# relations and 27 functions apps/api names resolves today, so this guard
# starts from zero with nothing to grandfather.
EXEMPT_RELATIONS: dict[str, str] = {}
EXEMPT_FUNCTIONS: dict[str, str] = {}

# Names that arrive as a variable and cannot be read from source.
#
# ONE, and it is unreadable by construction rather than by neglect:
# services/period_lock_service.py builds `fn_name` at runtime because it asks
# the database for one of TWO period predicates — period_closure_reason or
# period_lock_reason — and which one is the caller's question. Writing it as a
# literal would mean two near-identical call sites, which is how the two
# definitions drift apart.
MAX_UNREADABLE_RPC = 1


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-c", sql],
        capture_output=True, text=True)


@pytest.fixture(scope="module")
def catalog(pg_template):
    """(relations, functions) in schema public, from a real migrated database.

    relkind is deliberately NOT restricted to 'r'. PostgREST serves a table, a
    view, a materialized view, a partitioned table and a foreign table through
    the same `.table("x")` call, and public.accounts is a view — the exact name
    a tables-only reading has twice reported as a phantom.
    """
    admin = _ADMIN.strip()
    dbname = f"brels_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        r = _psql(dsn, "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
                       "ON n.oid = c.relnamespace WHERE n.nspname = 'public' "
                       "AND c.relkind IN ('r','v','m','p','f');")
        assert r.returncode == 0, r.stderr
        relations = {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}

        f = _psql(dsn, "SELECT p.proname FROM pg_proc p JOIN pg_namespace n "
                       "ON n.oid = p.pronamespace WHERE n.nspname = 'public';")
        assert f.returncode == 0, f.stderr
        functions = {ln.strip() for ln in f.stdout.splitlines() if ln.strip()}
        yield relations, functions
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _rel_offenders(relations: set[str]) -> dict[str, set[str]]:
    skip = unverifiable_relations(MIGRATIONS, EXPECTED_MIGRATION_FAILURES)
    bad: dict[str, set[str]] = {}
    for path, rel in relation_refs(API_ROOT):
        if rel in relations or rel in skip or rel in EXEMPT_RELATIONS:
            continue
        bad.setdefault(rel, set()).add(str(Path(path).relative_to(API_ROOT)))
    return bad


def _fn_offenders(functions: set[str]) -> dict[str, set[str]]:
    skip = unverifiable_functions(MIGRATIONS, EXPECTED_MIGRATION_FAILURES)
    found, _ = rpc_calls(API_ROOT)
    bad: dict[str, set[str]] = {}
    for path, lineno, fn in found:
        if fn in functions or fn in skip or fn in EXEMPT_FUNCTIONS:
            continue
        bad.setdefault(fn, set()).add(f"{Path(path).relative_to(API_ROOT)}:{lineno}")
    return bad


# ── Vacuity guards ───────────────────────────────────────────────────────────
#
# A parser that stopped matching would make every assertion below pass while
# checking nothing, and would look exactly like a clean bill of health — which
# is the shape this whole file exists to argue against.

@_NEEDS_PG
def test_the_scan_finds_enough_to_be_meaningful(catalog):
    relations, functions = catalog
    refs = relation_refs(API_ROOT)
    rpcs, _ = rpc_calls(API_ROOT)
    assert len({r for _, r in refs}) >= 200, (
        f"only {len({r for _, r in refs})} distinct relations named — parser likely broke")
    assert len({f for _, _, f in rpcs}) >= 20, (
        f"only {len({f for _, _, f in rpcs})} distinct rpc functions named — parser likely broke")
    assert len(relations) >= 250, f"only {len(relations)} relations in schema — migrations likely failed"
    assert len(functions) >= 50, f"only {len(functions)} functions in schema — migrations likely failed"


@_NEEDS_PG
def test_the_baseline_exclusion_is_derived_and_small(catalog):
    """The one place this check gives ground. It must actually derive something
    — an empty set means the migration reader broke and the first CI run would
    cry wolf — and it must stay far smaller than the schema it excludes from."""
    relations, _functions = catalog
    skip = unverifiable_relations(MIGRATIONS, EXPECTED_MIGRATION_FAILURES)
    assert skip, "derived no relations — the migration reader likely broke"
    assert len(skip) < len(relations) * 0.15, (
        f"{len(skip)} relations excluded against {len(relations)} known — "
        "the exclusion has grown into a blind spot")
    # 068_workflow_engine.sql is on the baseline and creates these.
    for rel in ("workflow_triggers", "workflow_conditions"):
        assert rel in skip, f"{rel} should be excluded but is not"


def test_a_view_is_a_relation():
    """public.accounts is a VIEW, and reading it as a phantom is the specific
    mistake this file is built around — made twice in this repository, once by
    the frontend guard and once by the sweep that led here. Pinned so a later
    'tidy-up' to relkind='r' fails rather than reintroduces it."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _backend_query_parser import relations_declared_in
    sql = (MIGRATIONS / "016_security_fixes.sql").read_text()
    assert "accounts" in relations_declared_in(sql), (
        "a CREATE VIEW is not being read as declaring a relation")
    assert any(rel == "accounts" for _p, rel in relation_refs(API_ROOT)), (
        "nothing names public.accounts any more — this pin no longer pins "
        "anything and should be re-pointed at another view rather than deleted")


def test_a_drop_then_recreate_in_one_migration_is_not_a_drop():
    """016 drops public.accounts and recreates it eleven lines later. A reader
    that collects every CREATE and then every DROP loses the order and reports
    the relation as deleted — which is how the sweep that led to this file
    got its one false positive."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _backend_query_parser import relations_declared_in
    sql = (MIGRATIONS / "016_security_fixes.sql").read_text()
    assert "DROP VIEW IF EXISTS public.accounts" in sql, (
        "016 no longer drops the view — re-point this test at whichever "
        "migration now does a drop-then-recreate")
    assert "accounts" in relations_declared_in(sql)


def test_a_commented_out_create_declares_nothing():
    """Migration 089 carries its rollback as a comment. A reader that does not
    strip SQL comments widens the exclusion list with relations no migration
    actually creates — which weakens this guard silently rather than loudly."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _backend_query_parser import functions_declared_in, relations_declared_in
    assert relations_declared_in("-- CREATE TABLE ghost (id uuid);") == set()
    assert relations_declared_in("/* CREATE VIEW ghost AS SELECT 1; */") == set()
    assert functions_declared_in("-- CREATE FUNCTION ghost() RETURNS void") == set()
    assert relations_declared_in("CREATE TABLE real_one (id uuid);") == {"real_one"}


# ── The checks themselves ────────────────────────────────────────────────────

@_NEEDS_PG
def test_no_backend_query_names_a_relation_that_does_not_exist(catalog):
    relations, _functions = catalog
    bad = _rel_offenders(relations)
    assert not bad, (
        "backend queries name relations that do not exist — PostgREST answers "
        "42P01 and the statement never runs:\n  "
        + "\n  ".join(f"{rel}  ← {', '.join(sorted(files))}"
                      for rel, files in sorted(bad.items())))


@_NEEDS_PG
def test_no_rpc_call_names_a_function_that_does_not_exist(catalog):
    _relations, functions = catalog
    bad = _fn_offenders(functions)
    assert not bad, (
        "backend .rpc() calls name functions that do not exist — PostgREST "
        "answers 42883 and the statement never runs:\n  "
        + "\n  ".join(f"{fn}  ← {', '.join(sorted(sites))}"
                      for fn, sites in sorted(bad.items())))


def test_the_dynamic_rpc_blind_spot_has_a_number_on_it():
    """Budgeted rather than ignored. It may shrink freely; growing it is a
    deliberate act that shows up in a diff."""
    _found, unreadable = rpc_calls(API_ROOT)
    assert unreadable <= MAX_UNREADABLE_RPC, (
        f"{unreadable} .rpc() calls take a name this scanner cannot read, "
        f"budget {MAX_UNREADABLE_RPC}. Each one is a function name nothing "
        "checks — prefer a literal unless the call genuinely picks between "
        "functions at runtime, and raise the budget with a reason if it does.")


def test_no_exemption_has_been_added_without_being_noticed():
    """Both lists are empty today. They are the place this guard would be
    weakened, so the emptiness is asserted rather than assumed."""
    assert EXEMPT_RELATIONS == {}, (
        "a relation exemption was added — it needs a reason in the dict and a "
        "line here saying why it is not a defect")
    assert EXEMPT_FUNCTIONS == {}
