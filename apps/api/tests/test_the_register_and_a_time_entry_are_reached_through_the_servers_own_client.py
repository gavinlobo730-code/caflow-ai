"""THE RELATED-PARTY REGISTER IS READ, AND A TIME ENTRY IS WRITTEN, THROUGH THE SERVER'S OWN CLIENT (POST-A-544, POST-A-546).

Both lines end in a migration that takes something away from the signed-in role: the READ of `entities`,
`entity_relationships` and `entity_to_entity_relationships` (the server narrows the register to a member's own clients and
the database's row rule does not), and the WRITE of `time_entries` (its rate columns price an hour and `billed_invoice_id`
says which invoice bills it, and a hand-made request can set either today). The API runs as the caller, so a statement of
its own that still used the caller's client would be refused the day that migration lands. The house order is therefore two
changes: the server's statements move first and ship, and the migration follows. This file holds the first.

The rule, over the whole server tree and not over the two files that were changed:

  1. every statement on one of the three register tables is made on the server's own client;
  2. every insert, update or delete of `time_entries` is made on the server's own client;
  3. the time repository's three writers refuse to run without a firm, because row security does not narrow that client;
  4. driven, not read: a create, an update and a delete land on the server's client and name the firm, and a read stays on
     the caller's.

The firm scope of each statement is held for every table by `test_every_query_on_a_firm_table_carries_its_firm_scope.py`.
"""
import ast
import pathlib

import pytest

API = pathlib.Path(__file__).resolve().parent.parent
REGISTER = {"entities", "entity_relationships", "entity_to_entity_relationships"}
WRITES = {"insert", "update", "delete", "upsert"}
SERVER_DIRS = ("routers", "services", "repositories", "domain", "jobs", "core")


def _sources():
    for d in SERVER_DIRS:
        for path in sorted((API / d).rglob("*.py")):
            yield path, ast.parse(path.read_text())


def _table_calls(tree):
    """Every `<receiver>.table("<literal>")` call: (table name, the receiver's source, the call node)."""
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "table"
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            yield node.args[0].value, ast.unparse(node.func.value), node


def _is_the_servers(receiver: str) -> bool:
    return receiver.startswith(("privileged_for(", "db_provider.privileged_for(", "_writer(")) or "service_db" in receiver


def _verbs_chained_on(tree, call):
    """The method names called on the result of `call`, following the chain outwards (`.table(x).update(..).eq(..)`)."""
    parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    verbs, node = [], call
    while True:
        attr = parents.get(id(node))
        if not isinstance(attr, ast.Attribute):
            return verbs
        outer = parents.get(id(attr))
        if not (isinstance(outer, ast.Call) and outer.func is attr):
            return verbs
        verbs.append(attr.attr)
        node = outer


def test_every_statement_on_the_register_is_made_on_the_servers_own_client():
    seen, on_the_callers = 0, []
    for path, tree in _sources():
        for table, receiver, call in _table_calls(tree):
            if table in REGISTER:
                seen += 1
                if not _is_the_servers(receiver):
                    on_the_callers.append(f"{path.relative_to(API)}:{call.lineno} {receiver}.table({table!r})")
    assert seen >= 20, f"only {seen} statements on the register were found: this scan has gone blind"
    assert not on_the_callers, (
        "a statement on the related-party register runs as the caller, and the migration that closes POST-A-544 takes the "
        "signed-in role's read away:\n  " + "\n  ".join(on_the_callers))


def test_every_write_of_a_time_entry_is_made_on_the_servers_own_client():
    seen, on_the_callers = 0, []
    for path, tree in _sources():
        for table, receiver, call in _table_calls(tree):
            if table != "time_entries":
                continue
            wrote = WRITES & set(_verbs_chained_on(tree, call))
            if wrote:
                seen += 1
                if not _is_the_servers(receiver):
                    on_the_callers.append(f"{path.relative_to(API)}:{call.lineno} {receiver}.table('time_entries').{sorted(wrote)[0]}")
    assert seen >= 5, f"only {seen} writes of a time entry were found: this scan has gone blind"
    assert not on_the_callers, (
        "a write of a time entry runs as the caller, and the migration that closes POST-A-546 takes the signed-in role's "
        "write away:\n  " + "\n  ".join(on_the_callers))


def test_the_scan_sees_a_write_made_on_the_callers_client():
    """The negative control: the same scan over a statement written the old way finds it."""
    tree = ast.parse('def f(db):\n    return db.table("time_entries").update({"a": 1}).eq("id", 1).execute()\n')
    [(table, receiver, call)] = list(_table_calls(tree))
    assert table == "time_entries" and not _is_the_servers(receiver)
    assert "update" in _verbs_chained_on(tree, call)


# ── driven ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

class _Recorder:
    """A stand-in database client that records each statement as (table, verb, filters) and answers one row."""

    def __init__(self, name, log):
        self.name, self.log = name, log

    def table(self, table):
        return _Statement(self, table)


class _Statement:
    def __init__(self, client, table):
        self.client, self.tbl, self.verb, self.filters = client, table, "select", {}

    def select(self, *_a, **_k): return self
    def insert(self, _row): self.verb = "insert"; self.filters["firm_id"] = _row.get("firm_id"); return self
    def update(self, _row): self.verb = "update"; return self
    def delete(self): self.verb = "delete"; return self
    def eq(self, col, val): self.filters[col] = val; return self
    def maybe_single(self): return self

    def execute(self):
        self.client.log.append((self.client.name, self.tbl, self.verb, dict(self.filters)))
        return type("R", (), {"data": [{"id": "e1"}]})()


@pytest.fixture
def repo(monkeypatch):
    from core import db_provider
    from repositories import time_tracking_repository as module
    log = []
    caller, server = _Recorder("caller", log), _Recorder("server", log)
    monkeypatch.setattr(module, "_get_db", lambda: caller)
    monkeypatch.setattr(db_provider, "privileged_for", lambda db: server if db is caller else db)
    return module.TimeTrackingRepository(), log


def test_a_create_an_update_and_a_delete_land_on_the_servers_client_naming_the_firm_and_a_read_stays_the_callers(repo):
    r, log = repo
    r.create({"firm_id": "f1", "user_id": "u1"})
    r.update("e1", {"description": "x"}, firm_id="f1")
    r.delete("e1", firm_id="f1")
    r.find_by_id("e1", firm_id="f1")
    assert [(who, verb) for who, _t, verb, _f in log] == [("server", "insert"), ("server", "update"), ("server", "delete"), ("caller", "select")]
    assert all(f.get("firm_id") == "f1" for _w, _t, _v, f in log), "a statement of the server's own client did not name the firm"
    assert log[1][3].get("id") == "e1" and log[2][3].get("id") == "e1"


@pytest.mark.parametrize("call", [
    lambda r: r.create({"user_id": "u1"}),
    lambda r: r.update("e1", {"description": "x"}, firm_id=""),
    lambda r: r.update("e1", {"description": "x"}, firm_id=None),
    lambda r: r.delete("e1", firm_id=""),
    lambda r: r.delete("e1", firm_id=None),
])
def test_a_writer_refuses_to_run_without_a_firm_and_writes_nothing(repo, call):
    r, log = repo
    with pytest.raises(ValueError):
        call(r)
    assert log == [], "a statement was sent before the firm was asked for"


def test_no_caller_of_the_three_writers_leaves_the_firm_out():
    """`update` and `delete` take the firm as a required argument; a caller that passed it positionally-missing would raise."""
    import inspect
    from repositories.time_tracking_repository import TimeTrackingRepository as T
    for name in ("update", "delete"):
        firm = inspect.signature(getattr(T, name)).parameters["firm_id"]
        assert firm.default is inspect.Parameter.empty, f"{name} gives the firm a default again"
