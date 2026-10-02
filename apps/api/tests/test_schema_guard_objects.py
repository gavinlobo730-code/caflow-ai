"""The schema-drift check heals itself, and it covers the tables and functions the code calls (ops-19).

THE TWO GAPS
    1. It ran ONCE. A deploy that booted in the minutes before its migration landed answered 503 until the next
       restart, long after the migration arrived: a false alarm that outlived its cause.
    2. It knew only `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Code calling a table or a function that a
       migration creates, in a database without it, passed.

WHAT IS PINNED, AND WHAT IS DELIBERATELY NOT
    * /health goes from 503 back to 200 on its own, within the re-check interval, when the missing column
      appears (the headline); and "not yet checked" is still never a 503.
    * The watch only moves the verdict TOWARDS healthy: it ends at the first clean answer and is never started
      by a clean boot, so it cannot newly turn a healthy instance's /health into a 503 hours after it booted.
    * A table or function the code names and the database lacks is REPORTED (`schema_objects` on /health) and is
      NOT YET a 503 (OBJECT_DRIFT_FAILS_HEALTH is False), because the function half is unmeasured against
      production. The flip is tested in both positions so it is one line when somebody makes it.
    * Every table the code names exists in the last production snapshot or is created by a migration after it.
      That is the measurement the "not yet a 503" decision rests on, held as a test so it is re-measured every
      time a table is added.
"""
from __future__ import annotations

import ast
import json
import re
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main as main_module
from core import schema_guard
from core.schema_guard import (
    check_schema_objects,
    code_called_objects,
    live_functions,
    needs_watch,
    start_drift_watch,
    stop_drift_watch,
)

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
FIXTURES = API_ROOT / "tests" / "fixtures"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """The verdicts and the watcher are process-wide; leave them as found."""
    before = dict(main_module._SCHEMA_DRIFT)
    stop_drift_watch()
    _reset_objects()
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    yield
    stop_drift_watch()
    _reset_objects()
    main_module._SCHEMA_DRIFT = before


def _reset_objects():
    with schema_guard._OBJECTS_LOCK:
        schema_guard._OBJECTS.update({"tables_checked": False, "functions_checked": False,
                                      "missing_tables": [], "missing_functions": []})


# ── doubles ────────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, data):
        self.data = data


class _Rpc:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return _Resp(self._fn())


class FakeDb:
    """Speaks the two introspection RPCs. `tables` and `functions` can be changed after the fact, which is what
    'a migration applied' means to a check that asks again."""

    def __init__(self, tables: dict, functions=None, functions_rpc=True):
        self.tables = {t: list(c) for t, c in tables.items()}
        self.functions = list(functions or [])
        self.functions_rpc = functions_rpc
        self.calls: list[str] = []

    def rpc(self, name, params):
        self.calls.append(name)
        if name == "get_public_schema_columns":
            return _Rpc(lambda: {"total_columns": sum(len(c) for c in self.tables.values()),
                                 "tables": self.tables})
        if name == "get_public_schema_functions":
            if not self.functions_rpc:
                raise RuntimeError("function public.get_public_schema_functions() does not exist")
            return _Rpc(lambda: {"total_functions": len(set(self.functions)), "functions": self.functions})
        raise AssertionError(f"unexpected RPC {name}")


def _code(tmp_path: Path, **files: str) -> Path:
    (tmp_path / "services").mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (tmp_path / "services" / f"{name}.py").write_text(text)
    return tmp_path


# ── what the code calls ────────────────────────────────────────────────────────

def test_the_literal_table_and_function_names_in_calls_are_found(tmp_path):
    root = _code(
        tmp_path,
        a='db.table("widgets").select("*")\nsb.rpc("make_widget", {})\n',
        b='client.table(\n    "gadgets"\n).insert({})\nclient.rpc(\n  \'do_gadget\', {})\n',
    )
    tables, functions = code_called_objects(root, ("services",))
    assert tables == {"widgets", "gadgets"} and functions == {"make_widget", "do_gadget"}


def test_a_name_in_a_variable_or_a_storage_bucket_is_not_a_table(tmp_path):
    root = _code(tmp_path, a='db.table(name)\ndb.table(f"x_{n}")\nstorage.from_("Documents")\nx.table("")\n')
    assert code_called_objects(root, ("services",)) == (frozenset(), frozenset())


def test_the_real_tree_is_scanned_and_the_guard_does_not_read_itself():
    tables, functions = code_called_objects()
    assert len(tables) > 200 and len(functions) >= 30, "the scan found almost nothing"
    # core/schema_guard.py quotes `.table("…")` and `.rpc("…")` in its own text.
    assert "get_public_schema_functions" not in functions


def test_the_regular_expression_scan_and_the_syntax_tree_find_the_same_names():
    """The regex is used because parsing 700 files costs seconds on the boot thread. The cost of that choice is a
    docstring or a comment that quotes a call looking like one; this fails the day that happens."""
    tables: set[str] = set()
    functions: set[str] = set()
    this = Path(schema_guard.__file__).resolve()
    for d in schema_guard.CODE_DIRS:
        for path in (API_ROOT / d).rglob("*.py"):
            if path.resolve() == this:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in ("table", "rpc") and node.args
                        and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                        and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", node.args[0].value)):
                    (tables if node.func.attr == "table" else functions).add(node.args[0].value.lower())
    got_tables, got_functions = code_called_objects()
    assert got_tables == tables and got_functions == functions, (
        f"regex-only tables {sorted(got_tables - tables)[:5]}, ast-only {sorted(tables - got_tables)[:5]}; "
        f"regex-only functions {sorted(got_functions - functions)[:5]}, ast-only {sorted(functions - got_functions)[:5]}")


# ── the measurement the "reports, does not gate" decision rests on ─────────────

def _production_snapshot():
    path = sorted(p for p in FIXTURES.glob("production_schema_*.json") if not p.name.endswith(".meta.json"))[-1]
    meta = json.loads(path.with_name(path.stem + ".meta.json").read_text())
    return set(json.loads(path.read_text())), int(meta["applied_through_migration"])


def _created_by(migration_glob_names: list[Path]) -> dict[str, int]:
    create = re.compile(r"create\s+(?:or\s+replace\s+)?(?:unlogged\s+)?(?:table|view)\s+(?:if\s+not\s+exists\s+)?"
                        r"(?:public\.)?[\"']?([a-z0-9_]+)", re.I)
    out: dict[str, int] = {}
    for path in migration_glob_names:
        number = int(re.match(r"(\d+)_", path.name).group(1))
        text = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8", errors="ignore"))
        for name in create.findall(text):
            out[name.lower()] = max(out.get(name.lower(), 0), number)
    return out


def test_every_table_the_code_names_is_one_production_had_or_a_later_migration_creates():
    """The evidence behind OBJECT_DRIFT_FAILS_HEALTH = False being SAFE to flip for tables: against the last
    production snapshot there is no table the code calls that production lacks, apart from tables created by a
    migration newer than that snapshot (which production applies on merge). If a name appears here that is in
    neither set, the code calls something nothing ever created."""
    production, applied_through = _production_snapshot()
    forward = [p for p in MIGRATIONS.glob("*.sql") if "rollback" not in p.name and not p.name.startswith("_")]
    created = _created_by(forward)
    tables, _ = code_called_objects()
    unexplained = sorted(t for t in tables
                         if t not in production and created.get(t, 0) <= applied_through)
    assert not unexplained, (
        f"the code calls tables absent from production's snapshot (through migration {applied_through}) and not "
        f"created by any later migration: {unexplained}")


def test_every_function_the_code_calls_is_created_by_a_migration():
    forward = [p for p in MIGRATIONS.glob("*.sql") if "rollback" not in p.name and not p.name.startswith("_")]
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in forward)
    defined = {m.lower() for m in re.findall(
        r"create\s+(?:or\s+replace\s+)?function\s+(?:public\.)?[\"']?([a-zA-Z0-9_]+)", text, re.I)}
    _, functions = code_called_objects()
    assert sorted(f for f in functions if f not in defined) == []


# ── the object check ───────────────────────────────────────────────────────────

def test_a_table_the_code_names_and_the_database_lacks_is_reported(tmp_path):
    """A migration that only CREATES a table adds no column, so the column check could never see it."""
    root = _code(tmp_path, a='db.table("brand_new_table").select("*")\n')
    db = FakeDb({"clients": ["id"]}, functions=[])
    got = check_schema_objects(db, root=root, dirs=("services",))
    assert got["tables_checked"] and got["missing_tables"] == ["brand_new_table"]

    db.tables["brand_new_table"] = ["id"]                   # the migration applies
    again = check_schema_objects(db, root=root, dirs=("services",))
    assert again["missing_tables"] == []


def test_a_function_the_code_names_and_the_database_lacks_is_reported(tmp_path):
    root = _code(tmp_path, a='db.rpc("brand_new_fn", {})\ndb.rpc("old_fn", {})\n')
    db = FakeDb({"clients": ["id"]}, functions=["old_fn", "something_else"])
    got = check_schema_objects(db, root=root, dirs=("services",))
    assert got["functions_checked"] and got["missing_functions"] == ["brand_new_fn"]


def test_a_database_without_the_function_list_checks_the_tables_and_reports_no_function_missing(tmp_path):
    """Migration 475 may not have landed when the code boots. That is 'functions not checked', never 'every
    function is missing'."""
    root = _code(tmp_path, a='db.table("clients")\ndb.rpc("fn", {})\n')
    db = FakeDb({"clients": ["id"]}, functions_rpc=False)
    got = check_schema_objects(db, root=root, dirs=("services",))
    assert got == {"tables_checked": True, "functions_checked": False,
                   "missing_tables": [], "missing_functions": []}


def test_a_partial_function_list_is_not_trusted():
    class _Partial:
        def rpc(self, name, params):
            return _Rpc(lambda: {"total_functions": 10, "functions": ["a", "b"]})

    assert live_functions(_Partial()) is None


@pytest.mark.parametrize("payload", [None, [], "x", {"functions": ["a"]}, {"total_functions": 1},
                                     {"total_functions": 1, "functions": "a"}])
def test_a_malformed_function_list_is_not_trusted(payload):
    class _Odd:
        def rpc(self, name, params):
            return _Rpc(lambda: payload)

    assert live_functions(_Odd()) is None


def test_overloads_are_one_name_on_both_sides():
    db = FakeDb({"t": ["id"]}, functions=["f", "f", "g"])
    assert live_functions(db) == {"f", "g"}


# ── /health: reports, and does not yet gate ────────────────────────────────────

def _health():
    return TestClient(main_module.app).get("/health")


def test_object_drift_is_not_yet_a_reason_to_refuse_traffic():
    """Pinned, with the reason, so the flip is a decision and not a drift."""
    assert schema_guard.OBJECT_DRIFT_FAILS_HEALTH is False
    with schema_guard._OBJECTS_LOCK:
        schema_guard._OBJECTS.update({"tables_checked": True, "functions_checked": True,
                                      "missing_tables": ["a_table"], "missing_functions": ["a_fn"]})
    main_module._SCHEMA_DRIFT = {"checked": True, "missing": []}
    r = _health()
    assert r.status_code == 200
    objects = r.json()["data"]["schema_objects"]
    assert objects["missing_tables"] == ["a_table"] and objects["missing_functions"] == ["a_fn"]


def test_flipping_the_switch_makes_object_drift_a_503(monkeypatch):
    monkeypatch.setattr(schema_guard, "OBJECT_DRIFT_FAILS_HEALTH", True)
    with schema_guard._OBJECTS_LOCK:
        schema_guard._OBJECTS.update({"tables_checked": True, "functions_checked": True,
                                      "missing_tables": ["a_table"], "missing_functions": []})
    main_module._SCHEMA_DRIFT = {"checked": True, "missing": []}
    r = _health()
    assert r.status_code == 503
    body = r.json()
    assert body["data"]["schema_objects"]["missing_tables"] == ["a_table"] and body["data"]["missing_columns"] == []


def test_a_clean_database_says_so_on_health():
    with schema_guard._OBJECTS_LOCK:
        schema_guard._OBJECTS.update({"tables_checked": True, "functions_checked": True})
    main_module._SCHEMA_DRIFT = {"checked": True, "missing": []}
    data = _health().json()["data"]
    assert data["schema"] == "ok" and data["schema_objects"] == {
        "tables_checked": True, "functions_checked": True, "missing_tables": [], "missing_functions": []}


def test_not_yet_checked_is_still_never_a_503():
    main_module._SCHEMA_DRIFT = {"checked": False, "missing": []}
    r = _health()
    assert r.status_code == 200 and r.json()["data"]["schema"] == "checking"


# ── the watch ──────────────────────────────────────────────────────────────────

def _wait(predicate, seconds=3.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_a_clean_boot_starts_no_watch(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://fake")
    with schema_guard._OBJECTS_LOCK:
        schema_guard._OBJECTS.update({"tables_checked": True, "functions_checked": True})
    assert not needs_watch({"checked": True, "missing": []})
    assert start_drift_watch({"checked": True, "missing": []}, lambda r: None, check=lambda: {}) is None


def test_mock_mode_has_nothing_to_watch():
    assert not needs_watch({"checked": True, "missing": ["a.b"]}), "no SUPABASE_URL means no database to ask"
    assert start_drift_watch({"checked": False, "missing": []}, lambda r: None, check=lambda: {}) is None


def test_the_watch_hands_every_answer_on_and_ends_at_the_first_clean_one(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://fake")
    with schema_guard._OBJECTS_LOCK:
        schema_guard._OBJECTS.update({"tables_checked": True, "functions_checked": True})
    answers = iter([{"checked": True, "missing": ["t.c"]},
                    {"checked": False, "missing": []},
                    {"checked": True, "missing": []}])
    applied: list[dict] = []
    calls = []

    def check():
        calls.append(1)
        return next(answers)

    thread = start_drift_watch({"checked": True, "missing": ["t.c"]}, applied.append, check=check, interval=0.01)
    assert thread is not None
    thread.join(3)
    assert not thread.is_alive(), "the watch must end once the schema is clean"
    assert applied == [{"checked": True, "missing": ["t.c"]}, {"checked": False, "missing": []},
                       {"checked": True, "missing": []}]
    assert len(calls) == 3, "it must not ask again after a clean answer"


def test_one_bad_round_does_not_end_the_watch(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://fake")
    with schema_guard._OBJECTS_LOCK:
        schema_guard._OBJECTS.update({"tables_checked": True, "functions_checked": True})
    rounds = []

    def check():
        rounds.append(1)
        if len(rounds) == 1:
            raise ConnectionError("connection reset by peer")
        return {"checked": True, "missing": []}

    applied: list[dict] = []
    thread = start_drift_watch({"checked": False, "missing": []}, applied.append, check=check, interval=0.01)
    thread.join(3)
    assert applied == [{"checked": True, "missing": []}] and len(rounds) == 2


def test_there_is_one_watcher_per_process(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://fake")
    release = threading.Event()

    def check():
        release.wait(2)
        return {"checked": True, "missing": []}

    first = start_drift_watch({"checked": False, "missing": []}, lambda r: None, check=check, interval=0.01)
    second = start_drift_watch({"checked": False, "missing": []}, lambda r: None, check=check, interval=0.01)
    assert first is second
    release.set()
    stop_drift_watch()


def test_a_watch_that_is_stopped_stops(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://fake")
    calls = []
    thread = start_drift_watch({"checked": False, "missing": []}, lambda r: None,
                               check=lambda: calls.append(1) or {"checked": False, "missing": []}, interval=0.01)
    assert _wait(lambda: len(calls) >= 2)
    stop_drift_watch()
    assert not thread.is_alive()


# ── the headline: /health comes back by itself ─────────────────────────────────

@pytest.fixture()
def database(monkeypatch):
    """A fake Supabase behind the real run_startup_check, with a tiny interval."""
    monkeypatch.setenv("SUPABASE_URL", "http://fake")
    monkeypatch.setattr(schema_guard, "RECHECK_INTERVAL_SECONDS", 0.02)
    monkeypatch.setattr(schema_guard, "expected_columns_from_migrations",
                        lambda *a, **k: {"clients": {"id", "brand_new_column"}})
    monkeypatch.setattr(schema_guard, "code_called_objects",
                        lambda *a, **k: (frozenset({"clients"}), frozenset({"fn_a"})))
    db = FakeDb({"clients": ["id"]}, functions=["fn_a"])
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    return db


def test_health_returns_to_200_by_itself_after_the_migration_applies(database):
    """A boot in the window before the migration lands. Without the watch this stays 503 until a restart."""
    main_module._SCHEMA_DRIFT = schema_guard.run_startup_check()
    assert main_module._SCHEMA_DRIFT == {"checked": True, "missing": ["clients.brand_new_column"]}
    assert _health().status_code == 503

    main_module._watch_schema_drift(main_module._SCHEMA_DRIFT)
    time.sleep(0.1)
    assert _health().status_code == 503, "still drifted: the migration has not applied"

    database.tables["clients"].append("brand_new_column")           # the migration applies
    assert _wait(lambda: _health().status_code == 200), (
        "/health stayed 503 after the migration applied: the check does not ask again")
    assert _health().json()["data"]["schema"] == "ok"


def test_a_boot_that_could_not_read_the_schema_is_read_later(database):
    """`checked: False` was a verdict that never improved."""
    database.tables["clients"].append("brand_new_column")
    boot_database_up = {"up": False}
    real_rpc = database.rpc

    def flaky(name, params):
        if not boot_database_up["up"]:
            raise ConnectionError("database unreachable at boot")
        return real_rpc(name, params)

    database.rpc = flaky
    main_module._SCHEMA_DRIFT = schema_guard.run_startup_check()
    assert main_module._SCHEMA_DRIFT == {"checked": False, "missing": []}
    assert _health().status_code == 200 and _health().json()["data"]["schema"] == "checking"

    main_module._watch_schema_drift(main_module._SCHEMA_DRIFT)
    boot_database_up["up"] = True
    assert _wait(lambda: _health().json()["data"]["schema"] == "ok")


def test_the_watch_goes_on_while_the_function_list_is_unreadable_and_ends_when_it_is(database):
    """Migration 475 can land after the code boots. Columns are clean the whole time; the object half is not
    read yet, and the watch is what reads it when the function appears."""
    database.tables["clients"].append("brand_new_column")
    database.functions_rpc = False
    main_module._SCHEMA_DRIFT = schema_guard.run_startup_check()
    assert main_module._SCHEMA_DRIFT == {"checked": True, "missing": []}
    assert schema_guard.object_drift()["functions_checked"] is False

    thread = schema_guard.start_drift_watch(main_module._SCHEMA_DRIFT, main_module._apply_schema_drift)
    assert thread is not None, "a clean column verdict with an unread function list still has something to wait for"
    time.sleep(0.1)
    assert thread.is_alive()

    database.functions_rpc = True                                    # migration 475 applies
    thread.join(3)
    assert not thread.is_alive()
    assert schema_guard.object_drift()["functions_checked"] is True
    assert schema_guard.object_drift()["missing_functions"] == []


def test_a_clean_database_starts_no_thread(database):
    database.tables["clients"].append("brand_new_column")
    main_module._SCHEMA_DRIFT = schema_guard.run_startup_check()
    before = threading.active_count()
    main_module._watch_schema_drift(main_module._SCHEMA_DRIFT)
    assert threading.active_count() == before


def test_the_boot_thread_starts_the_watch_after_the_first_verdict(monkeypatch):
    """The wiring: without this every test above could pass against an app that never starts the watch."""
    started = []
    monkeypatch.setattr(main_module, "_watch_schema_drift", lambda initial: started.append(dict(initial)))
    monkeypatch.setattr(schema_guard, "run_startup_check", lambda: {"checked": True, "missing": ["x.y"]})
    monkeypatch.setattr(main_module, "start_scheduler", lambda: None)
    monkeypatch.setattr(main_module, "log_scheduler_startup_health", lambda: None)
    import jobs.scheduler as sched
    monkeypatch.setattr(sched, "run_catchup_if_stale", lambda: None)
    main_module._boot_background()
    assert started == [{"checked": True, "missing": ["x.y"]}]
