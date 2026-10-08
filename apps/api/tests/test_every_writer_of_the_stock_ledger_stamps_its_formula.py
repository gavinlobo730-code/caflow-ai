"""Every insert into `inventory_stock_ledger` says which cost formula was in force (POST-A-108, second half).

`inventory_stock_ledger.costing_method` is NOT NULL DEFAULT 'moving_average' (migration 394). A writer that omits
it is not refused: it is given the weighted average, whatever the client's policy is. The Significant Accounting
Policies note reads that column to say which formula priced the year, and the godown transfer omitted it, so a
FIFO client with one transfer was told in a signed note that it had changed its accounting policy (AS-5
paragraphs 29 and 32). Every fixture that stamped its rows by hand had agreed with the writers that did, which is
why nothing saw the one that did not.

THIS IS THE RULE AND NOT A LIST OF TODAY'S WRITERS. It reads every non-test module under apps/api, finds each
`.insert(...)` or `.upsert(...)` whose receiver names the table, resolves what is being written, and fails any
payload that cannot be shown to carry the column. A fifth writer added next year, in a module nobody thought of,
is covered on the day it is written.

WHAT COUNTS AS CARRYING IT, and why it is a visible literal:

  * a dict literal with a `"costing_method"` key, written inline, or built into a name in the same function and
    inserted by that name, or collected into a list by `.append(...)`, or given the key afterwards with
    `row["costing_method"] = ...`;
  * a `**spread` does NOT count. `services/inventory_location_service.transfer` says why its two payloads are
    spelled out in full: `tests/test_backend_inserts_supply_every_required_column_pg.py` resolves no names, and
    a payload nothing can read is a payload nothing can check, here as there;
  * a payload this reader cannot resolve (a call's return value, a parameter) FAILS, with the sentence saying to
    write it as a literal, rather than passing because nothing was seen.

WHAT IT CANNOT SEE, stated so a green run is not read as more than it is: a table reached through a variable
(`db.table(NAME)`), a payload assembled across functions, and any write that is not PostgREST's (a SQL function
inserting into the table; `grep -rn "INTO.*inventory_stock_ledger" migrations` finds none today). The stamp's
VALUE is not judged, only that one is written; `tests/test_which_cost_formula_prices_an_issue.py` and
`tests/test_accounting_policies_note.py` drive the real writers and read what they stored.
"""
from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass, field

import pytest

API = pathlib.Path(__file__).resolve().parent.parent

TABLE = "inventory_stock_ledger"
COLUMN = "costing_method"
WRITE_VERBS = ("insert", "upsert")
TABLE_METHODS = ("table", "from_")
_SKIPPED_TOP_LEVEL = {"tests", "migrations", ".venv", "venv", "node_modules", "__pycache__"}
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)

#: Said once, in the failure text, so the reason travels with the red line.
_WHY = ("migration 394 makes the column NOT NULL DEFAULT 'moving_average', so a writer that omits it stamps the "
        "weighted average on a FIFO client's row and the Significant Accounting Policies note reports a change "
        "of cost formula that never happened")


@dataclass
class Writer:
    where: str
    verb: str
    problems: list = field(default_factory=list)


# ── reading one module ──────────────────────────────────────────────────────

def _const_str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


class _Scope:
    """What one function (or the module's top level) does to the names it builds a payload in."""

    def __init__(self, root):
        self.assigned: dict = {}      # name -> [value nodes]
        self.appended: dict = {}      # name -> [argument nodes of .append(...)]
        self.keyed: dict = {}         # name -> {constant keys set by row["k"] = ... or row.update({...})}
        for node in self._own_nodes(root):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.assigned.setdefault(target.id, []).append(node.value)
                    elif (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
                          and _const_str(target.slice) is not None):
                        self.keyed.setdefault(target.value.id, set()).add(_const_str(target.slice))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                self.assigned.setdefault(node.target.id, []).append(node.value)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and isinstance(node.func.value, ast.Name)):
                name, verb = node.func.value.id, node.func.attr
                if verb == "append" and node.args:
                    self.appended.setdefault(name, []).append(node.args[0])
                elif verb == "update" and node.args and isinstance(node.args[0], ast.Dict):
                    keys = {_const_str(k) for k in node.args[0].keys if k is not None}
                    self.keyed.setdefault(name, set()).update(k for k in keys if k)

    @staticmethod
    def _own_nodes(root):
        """The scope's own statements: a nested function is another scope and is not read into this one."""
        stack = list(ast.iter_child_nodes(root))
        while stack:
            node = stack.pop()
            yield node
            if not isinstance(node, _FUNCTIONS + (ast.ClassDef,)):
                stack.extend(ast.iter_child_nodes(node))


def _names_the_table(node, scope: _Scope) -> bool:
    """`...table("inventory_stock_ledger")...` anywhere down the receiver chain, or one hop through a name."""
    seen: set = set()
    while True:
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Attribute) and func.attr in TABLE_METHODS and node.args
                    and _const_str(node.args[0]) == TABLE):
                return True
            node = func
        elif isinstance(node, ast.Attribute):
            node = node.value
        elif isinstance(node, ast.Name):
            if node.id in seen:
                return False
            seen.add(node.id)
            values = scope.assigned.get(node.id) or []
            if not values:
                return False
            node = values[-1]
        else:
            return False


def _payloads(node, scope: _Scope, via: frozenset = frozenset()):
    """Yield `(dict literal, extra keys given to it by name, None)` or `(None, set(), why unreadable)`."""
    if isinstance(node, ast.Dict):
        extra: set = set()
        for name in via:
            extra |= scope.keyed.get(name, set())
        yield node, extra, None
    elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for element in node.elts:
            yield from _payloads(element, scope, via)
    elif isinstance(node, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
        yield from _payloads(node.elt, scope, via)
    elif isinstance(node, ast.IfExp):
        yield from _payloads(node.body, scope, via)
        yield from _payloads(node.orelse, scope, via)
    elif isinstance(node, ast.Name):
        if node.id in via:
            return
        sources = list(scope.assigned.get(node.id, [])) + list(scope.appended.get(node.id, []))
        if not sources:
            yield None, set(), f"the name `{node.id}` is not built in this function"
            return
        for source in sources:
            yield from _payloads(source, scope, via | {node.id})
    else:
        yield None, set(), f"a {type(node).__name__} expression"


def _problems_with(call: ast.Call, scope: _Scope) -> list:
    if not call.args:
        return ["it is called with no positional payload"]
    problems, found = [], 0
    for literal, extra, unreadable in _payloads(call.args[0], scope):
        if unreadable:
            problems.append(f"the payload cannot be read ({unreadable}); write it as a dict literal here")
            continue
        found += 1
        keys = {_const_str(k) for k in literal.keys if k is not None}
        if COLUMN in keys or COLUMN in extra:
            continue
        spread = any(k is None for k in literal.keys)
        problems.append(
            f"a payload at line {literal.lineno} does not carry `{COLUMN}`"
            + (" (a `**spread` is not read: name the key in the literal)" if spread else ""))
    if not found and not problems:
        problems.append("no payload literal could be found for it")
    return problems


def writers_in(source: str, label: str) -> list:
    """Every insert/upsert into the stock ledger in one module's source, with what is wrong with each."""
    tree = ast.parse(source)
    scopes: dict = {}

    def scope_of(node, parents):
        while node is not None and not isinstance(node, _FUNCTIONS + (ast.Module,)):
            node = parents.get(node)
        return node

    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in WRITE_VERBS):
            continue
        root = scope_of(node, parents)
        scope = scopes.setdefault(id(root), _Scope(root))
        if not _names_the_table(node.func.value, scope):
            continue
        found.append(Writer(f"{label}:{node.lineno}", node.func.attr, _problems_with(node, scope)))
    return found


def _modules():
    for path in sorted(API.rglob("*.py")):
        relative = path.relative_to(API)
        if relative.parts[0] in _SKIPPED_TOP_LEVEL:
            continue
        yield path, relative.as_posix()


def _every_writer() -> list:
    out = []
    for path, label in _modules():
        text = path.read_text(encoding="utf-8")
        if TABLE not in text:
            continue
        out.extend(writers_in(text, label))
    return out


# ── the rule, over the tree ─────────────────────────────────────────────────

def test_every_writer_of_the_stock_ledger_stamps_the_formula_in_force():
    offenders = [f"{w.where} ({w.verb}): " + "; ".join(w.problems) for w in _every_writer() if w.problems]
    assert not offenders, (
        "a write to inventory_stock_ledger does not stamp its cost formula — " + _WHY + ":\n  "
        + "\n  ".join(offenders))


def test_the_scan_finds_the_writers_that_are_known_so_a_clean_run_is_not_an_empty_one():
    """A vacuity floor. The ledger has four writes today: the single-movement engine, the opening-balance batch
    and the transfer's two rows. A scan that finds fewer has stopped reading the shapes they are written in."""
    writers = _every_writer()
    assert len(writers) >= 4, [w.where for w in writers]
    files = {w.where.rsplit(":", 1)[0] for w in writers}
    assert {"domain/inventory_service.py", "services/inventory_location_service.py"} <= files


# ── the reader reads what it claims (each case is a way to fake a pass or hide a failure) ──────────────

def _problems(source: str) -> list:
    return [p for w in writers_in(source, "x.py") for p in w.problems]


def _count(source: str) -> int:
    return len(writers_in(source, "x.py"))


@pytest.mark.parametrize("name, source", [
    ("an inline literal", '''
def f(db):
    db.table("inventory_stock_ledger").insert({"firm_id": 1, "costing_method": m}).execute()
'''),
    ("a literal built into a name", '''
def f(db):
    row = {"firm_id": 1, "costing_method": m}
    db.table("inventory_stock_ledger").insert(row).execute()
'''),
    ("a list collected by append", '''
def f(db):
    rows = []
    for x in xs:
        rows.append({"firm_id": x, "costing_method": m})
    db.table("inventory_stock_ledger").insert(rows).execute()
'''),
    ("a key given afterwards", '''
def f(db):
    row = {"firm_id": 1}
    row["costing_method"] = m
    db.table("inventory_stock_ledger").insert(row).execute()
'''),
    ("a key given by update", '''
def f(db):
    row = {"firm_id": 1}
    row.update({"costing_method": m})
    db.table("inventory_stock_ledger").insert(row).execute()
'''),
    ("a spread beside the literal key", '''
def f(db):
    db.table("inventory_stock_ledger").insert({**base, "costing_method": m}).execute()
'''),
    ("an upsert", '''
def f(db):
    db.table("inventory_stock_ledger").upsert({"costing_method": m}, on_conflict="id").execute()
'''),
    ("a chain held in a name", '''
def f(db):
    ledger = db.table("inventory_stock_ledger")
    ledger.insert({"costing_method": m}).execute()
'''),
    ("a comprehension", '''
def f(db):
    db.table("inventory_stock_ledger").insert([{"costing_method": m, "q": q} for q in qs]).execute()
'''),
])
def test_a_payload_that_carries_the_column_passes(name, source):
    assert _count(source) == 1, f"the writer was not found: {name}"
    assert _problems(source) == [], name


@pytest.mark.parametrize("name, source", [
    ("an inline literal without it", '''
def f(db):
    db.table("inventory_stock_ledger").insert({"firm_id": 1}).execute()
'''),
    ("the transfer's shape: a literal without it, inserted twice", '''
def f(db):
    db.table("inventory_stock_ledger").insert({"movement_type": "transfer", "godown_id": a}).execute()
    db.table("inventory_stock_ledger").insert({"movement_type": "transfer", "godown_id": b}).execute()
'''),
    ("a literal in a name without it", '''
def f(db):
    row = {"firm_id": 1}
    db.table("inventory_stock_ledger").insert(row).execute()
'''),
    ("a list in which ONE appended literal lacks it", '''
def f(db):
    rows = []
    rows.append({"firm_id": 1, "costing_method": m})
    rows.append({"firm_id": 2})
    db.table("inventory_stock_ledger").insert(rows).execute()
'''),
    ("a spread alone", '''
def f(db):
    db.table("inventory_stock_ledger").insert({**stamp, "firm_id": 1}).execute()
'''),
    ("a payload from a call", '''
def f(db):
    db.table("inventory_stock_ledger").insert(build_row()).execute()
'''),
    ("a payload that is a parameter", '''
def f(db, row):
    db.table("inventory_stock_ledger").insert(row).execute()
'''),
    ("an upsert without it", '''
def f(db):
    db.table("inventory_stock_ledger").upsert({"firm_id": 1}, on_conflict="id").execute()
'''),
    ("a chain held in a name, without it", '''
def f(db):
    ledger = db.table("inventory_stock_ledger")
    ledger.insert({"firm_id": 1}).execute()
'''),
    ("a key set on a DIFFERENT name", '''
def f(db):
    row = {"firm_id": 1}
    other = {}
    other["costing_method"] = m
    db.table("inventory_stock_ledger").insert(row).execute()
'''),
    ("the key only in a nested function's payload", '''
def f(db):
    row = {"firm_id": 1}
    def g():
        row2 = {"costing_method": m}
    db.table("inventory_stock_ledger").insert(row).execute()
'''),
    ("the alias .from_", '''
def f(db):
    db.from_("inventory_stock_ledger").insert({"firm_id": 1}).execute()
'''),
])
def test_a_payload_that_does_not_carry_the_column_fails(name, source):
    assert _count(source) >= 1, f"the writer was not found: {name}"
    assert _problems(source), name


@pytest.mark.parametrize("name, source", [
    ("another table", '''
def f(db):
    db.table("journal_entries").insert({"firm_id": 1}).execute()
'''),
    ("a read of the ledger", '''
def f(db):
    db.table("inventory_stock_ledger").select("id").eq("firm_id", 1).execute()
'''),
    ("an update of the ledger (the stamp is written on insert)", '''
def f(db):
    db.table("inventory_stock_ledger").update({"journal_entry_id": j}).eq("id", i).execute()
'''),
    ("a dict method that is called insert", '''
def f(rows):
    rows.insert(0, {"firm_id": 1})
'''),
])
def test_what_is_not_a_write_to_the_ledger_is_not_judged(name, source):
    assert _count(source) == 0, name


def test_the_module_level_scope_is_read_too():
    source = '''
row = {"firm_id": 1}
db.table("inventory_stock_ledger").insert(row).execute()
'''
    assert _count(source) == 1 and _problems(source)
    stamped = 'db.table("inventory_stock_ledger").insert({"costing_method": m}).execute()'
    assert _count(stamped) == 1 and _problems(stamped) == []
