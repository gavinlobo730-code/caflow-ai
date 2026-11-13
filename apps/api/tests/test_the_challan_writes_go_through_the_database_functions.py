"""A delivery challan's header and lines, a job-work lot and a draft's corrections are written by the three database functions of migration 585 and by nothing else (ledger POST-A-419).

THE RULE, NOT A SPELLING OF IT
    The three writes used to be several requests each, and the defects were the gaps between them. The fix is a function that writes the lot in one transaction, so the defect comes back the day
    a second place writes one of them in steps again. This reads the whole API tree through the AST (any quote style, not a pattern) and fails:

      * a write (insert, update, upsert, delete) of `delivery_challan_lines` or `delivery_challan_returns` made on the chain directly above a `.table("...")` call, and ANY other mention of either
        table's name that is not a read (a string constant that is not the argument of `.table(...).select(...)`), which catches a handle held in a variable (`q = db.table("..."); q.insert(...)`), a
        name held in a variable or passed to a helper, and `.from_`;
      * an insert, upsert or delete of `delivery_challans` from anywhere (its updates are the two statements `tests/test_a_challan_amendment_cannot_stop_the_clock_without_a_day_or_before_a_lot.py`
        pins by function);
      * a call of one of the three functions from any module but `services/delivery_challan_writes.py`, the one door, and any call in the door that is not made on `privileged_for(...)`.
    WHAT IT CANNOT SEE: a call of the functions whose name is held in a variable or built (`db.rpc(name, ...)`), which is how the door could not be told from the rest of the tree, and a table
    written by a statement written in SQL by hand. The first is why the door's own calls are held to a literal name, and why a new function that writes a challan would have to be named here.

    It also holds the door to the migration from both sides: the door passes exactly the parameters the migration declares (a misspelt one is a failed call at run time and a mock double that
    accepts anything cannot see it), every word the functions raise for a refusal a person can act on is worded by the door or is named here as a caller's bug, and the in-memory double
    mirrors exactly these three functions.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from tests import challan_functions_double as double

API = Path(__file__).resolve().parent.parent
_SKIP = {"tests", "scripts", "migrations", "__pycache__", ".venv", "venv", "node_modules"}
_WRITES = {"insert", "update", "upsert", "delete"}
_DOOR = "services/delivery_challan_writes.py"
_FUNCTIONS = {"create_delivery_challan_atomic", "record_challan_lot_atomic", "correct_draft_challan_lines_atomic"}
_MIGRATION = next(p for p in sorted((API / "migrations").glob("585_*.sql")) if not p.name.endswith("_rollback.sql"))

#: The two modules that list the child tables' names as data (the tables a delete counts), never as a client.
_CHILD_TABLE_LISTS = {"routers/service_catalogue.py", "routers/firm_hsn_library.py"}

#: Words the functions raise that the door does not word, and why. `challan_not_a_draft` is the create being asked for a status other than draft, which the door never does (it writes a draft) and
#: which the request model has no field for, so it is a caller's bug and is raised as it is.
_NOT_WORDED = {"challan_not_a_draft": "the create is only ever called with a draft header"}
#: The word the cancel trigger raises (a trigger is a part of the table, not of the three functions): the door's `amend` words it, and the in-memory tables have no triggers to raise it.
_TRIGGER_WORDS = {"challan_has_lots"}


def _python():
    for path in sorted(API.rglob("*.py")):
        rel = path.relative_to(API)
        if any(part in _SKIP for part in rel.parts):
            continue
        yield rel.as_posix(), ast.parse(path.read_text(encoding="utf-8"))


def _tables_written(tree):
    """(line, table, verb) for every `<x>.table("name")` whose chain goes on to a write, however the handle was held."""
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "table" and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            continue
        upward = parents.get(node)
        while isinstance(upward, (ast.Attribute, ast.Call)):
            if isinstance(upward, ast.Attribute) and upward.attr in _WRITES:
                yield node.lineno, node.args[0].value, upward.attr
                break
            upward = parents.get(upward)


def _mentions_of_the_child_tables_that_are_not_a_read(tree):
    """(line, name) for every string constant naming a lines or lots table that is not directly the argument of `<x>.table(...)` whose chain goes on to `.select`."""
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and node.value in ("delivery_challan_lines", "delivery_challan_returns")):
            continue
        call = parents.get(node)
        is_a_table_call = isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "table"
        chain = parents.get(call) if is_a_table_call else None
        if is_a_table_call and isinstance(chain, ast.Attribute) and chain.attr == "select":
            continue
        # a docstring or a comment is not an ast.Constant inside an expression; a bare string statement (a docstring) is
        if isinstance(call, ast.Expr):
            continue
        yield node.lineno, node.value


def test_no_module_writes_a_challans_lines_or_lots_itself_and_none_inserts_or_deletes_a_challan():
    problems = []
    seen_tables = set()
    for rel, tree in _python():
        for line, table, verb in _tables_written(tree):
            seen_tables.add(table)
            if table in ("delivery_challan_lines", "delivery_challan_returns"):
                problems.append(f"{rel}:{line} {verb}s {table}")
            if table == "delivery_challans" and verb != "update":
                problems.append(f"{rel}:{line} {verb}s delivery_challans")
        if rel in _CHILD_TABLE_LISTS:
            continue
        for line, name in _mentions_of_the_child_tables_that_are_not_a_read(tree):
            problems.append(f"{rel}:{line} names {name} other than as `.table(...).select(...)`")
    assert not problems, "a challan's lines, lots, insert or delete is written outside the database functions, or a table is held in a way this cannot read:\n  " + "\n  ".join(problems)
    # The rule is not vacuous: the tree does write `delivery_challans` (the two updates the amendment guard pins), and the walk found them.
    assert "delivery_challans" in seen_tables


def test_the_probe_shapes_the_guard_claims_to_catch_are_caught():
    """The guard states a rule, so the shapes it names are tried: a handle held in a variable, a name held in a variable, a helper taking the name, and the plain write."""
    probes = {
        "handle": 'q = db.table("delivery_challan_lines")\nq.insert({})\n',
        "name": 'name = "delivery_challan_returns"\ndb.table(name).insert({})\n',
        "helper": 'write_rows("delivery_challan_lines", rows)\n',
        "plain": 'db.table("delivery_challan_lines").insert({}).execute()\n',
    }
    for label, source in probes.items():
        tree = ast.parse(source)
        found = list(_mentions_of_the_child_tables_that_are_not_a_read(tree)) or [w for w in _tables_written(tree)]
        assert found, f"the guard does not see the {label} shape"
    assert not list(_mentions_of_the_child_tables_that_are_not_a_read(ast.parse('rows = db.table("delivery_challan_lines").select("id").eq("challan_id", c).execute()\n')))


def test_only_the_one_door_calls_the_three_functions():
    callers = {}
    for rel, tree in _python():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "rpc" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and first.value in _FUNCTIONS:
                    callers.setdefault(rel, set()).add(first.value)
    assert callers == {_DOOR: _FUNCTIONS}, f"the challan functions are called from {sorted(callers)}, not from the one door: {callers}"


def _declared() -> dict[str, list[str]]:
    sql = _MIGRATION.read_text(encoding="utf-8")
    out = {}
    for name in _FUNCTIONS:
        found = re.search(rf"CREATE OR REPLACE FUNCTION public\.{name}\(([^)]*)\)", sql)
        assert found, f"migration 585 no longer defines {name}"
        out[name] = [part.strip().split()[0] for part in found.group(1).split(",") if part.strip()]
    return out


def test_every_call_in_the_door_is_made_on_the_privileged_client_and_names_its_function_as_a_literal():
    tree = ast.parse((API / _DOOR).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "rpc"]
    assert {c.args[0].value for c in calls if c.args and isinstance(c.args[0], ast.Constant)} == _FUNCTIONS
    for call in calls:
        assert call.args and isinstance(call.args[0], ast.Constant), f"{_DOOR}:{call.lineno} names its function in a variable, which no rule can read"
        on = call.func.value
        assert isinstance(on, ast.Call) and isinstance(on.func, ast.Name) and on.func.id == "privileged_for", (
            f"{_DOOR}:{call.lineno} calls {call.args[0].value} on something other than privileged_for(...): migration 585 revokes EXECUTE from the signed-in roles")


def test_the_door_passes_exactly_the_parameters_the_migration_declares():
    declared = _declared()
    tree = ast.parse((API / _DOOR).read_text(encoding="utf-8"))
    passed = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "rpc" and len(node.args) == 2:
            name, params = node.args
            assert isinstance(name, ast.Constant) and isinstance(params, ast.Dict), "the door's calls are written as a name and a dict literal, so a misspelt parameter can be read"
            passed[name.value] = [k.value for k in params.keys if isinstance(k, ast.Constant)]
    assert set(passed) == _FUNCTIONS
    for name, keys in passed.items():
        assert sorted(keys) == sorted(declared[name]), f"{name}: the door passes {keys}, the migration declares {declared[name]}"


def test_every_word_the_functions_raise_for_a_refusal_is_worded_or_named_a_callers_bug():
    sql = _MIGRATION.read_text(encoding="utf-8")
    words = set(re.findall(r"RAISE EXCEPTION '([a-z_]+)' USING ERRCODE = 'P000[12]'", sql))
    assert words >= {"challan_not_found", "challan_not_issued", "challan_not_job_work", "line_not_found", "lot_exceeds_line", "challan_not_draft", "duplicate_fix", "challan_not_a_draft", "challan_has_lots"}, words
    door = (API / _DOOR).read_text(encoding="utf-8")
    unworded = {w for w in words if f'"{w}"' not in door}
    assert unworded == set(_NOT_WORDED), f"words raised and not worded by the door: {sorted(unworded - set(_NOT_WORDED))}; named a caller's bug but worded: {sorted(set(_NOT_WORDED) - unworded)}"


def test_the_in_memory_double_mirrors_these_three_functions_and_no_others():
    assert set(double.FUNCTIONS) == _FUNCTIONS
    harness = (API / "tests" / "e2e_harness.py").read_text(encoding="utf-8")
    for name in _FUNCTIONS:
        assert f"_fn_{name} = _challan_function" in harness, f"the shared harness does not answer {name}"
    # the double raises the words the functions raise (the parity test holds the rest)
    source = (API / "tests" / "challan_functions_double.py").read_text(encoding="utf-8")
    for word in set(re.findall(r"RAISE EXCEPTION '([a-z_]+)' USING ERRCODE = 'P000[12]'", _MIGRATION.read_text(encoding="utf-8"))) - _TRIGGER_WORDS:
        assert f'"{word}"' in source, f"the double never raises {word}"
