"""The census and the rules every "these tables are written with the privileged client" guard asks (POST-A-008's tranches).

`test_the_tds_register_..._privileged_client.py` (POST-A-443) wrote these for its four tables; a tranche of the tables a signed-in session
can write that the access matrix does not observe asks the same three questions of its own group, so they live here with the group as an
argument: every write to one of the tables starts from a privileged expression (the payroll guard's judgement, imported, not copied);
every update and delete names the firm and the client; and the count of write sites is today's, so the rule cannot go vacuous.
"""
from __future__ import annotations

import ast
import re

from tests import _table_uses as tu
from tests.test_a_payroll_bank_or_document_table_is_queried_with_the_privileged_client import (
    _Scope, _chain_receiver, _enclosing_function, is_privileged, privileged_names)

WRITE_VERBS = frozenset({"insert", "update", "upsert", "delete"})


def module_constants(tree: ast.Module) -> dict[str, str]:
    """`NAME = "text"` at a module's top level: a table named through one (`db.table(LOANS_TABLE)`) is the same write as one named
    in place, and a census reading only literals would not see it (the related-party loan was written that way)."""
    out = {}
    for stmt in tree.body:
        target, value = None, None
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = stmt.targets[0], stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            target, value = stmt.target, stmt.value
        if isinstance(target, ast.Name) and isinstance(value, ast.Constant) and isinstance(value.value, str):
            out[target.id] = value.value
    return out


def _table_name(arg: ast.AST, consts: dict[str, str]) -> str | None:
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.Name):
        return consts.get(arg.id)
    return None


def _table_call_of(verb_call: ast.Call, tables: frozenset, consts: dict[str, str] | None = None) -> tuple[ast.Call, str] | None:
    if not (isinstance(verb_call.func, ast.Attribute) and verb_call.func.attr in WRITE_VERBS):
        return None
    recv = verb_call.func.value
    if isinstance(recv, ast.Call) and isinstance(recv.func, ast.Attribute) and recv.func.attr == "table" and recv.args:
        name = _table_name(recv.args[0], consts or {})
        if name in tables:
            return recv, name
    return None


def write_sites(source: str, tables: frozenset) -> list[tuple[str, str, int, bool, str]]:
    """(table, enclosing function, line, privileged?, receiver) for every write to one of `tables` in `source`."""
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    names = privileged_names(tree)
    scope = _Scope(tree, parents)
    consts = module_constants(tree)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        found = _table_call_of(node, tables, consts)
        if found is None:
            continue
        table_call, table = found
        fn = _enclosing_function(node, parents)
        recv = _chain_receiver(table_call)
        out.append((table, fn.name if fn else "<module>", node.lineno, is_privileged(recv, names, scope, node),
                    ast.unparse(recv)[:60]))
    return out


def _outer_chain(node: ast.AST, parents: dict) -> ast.AST:
    while True:
        parent = parents.get(node)
        if isinstance(parent, ast.Attribute) and isinstance(parents.get(parent), ast.Call) and parents[parent].func is parent:
            node = parents[parent]
            continue
        return node


#: The columns an update or a delete must filter on, unless a group names others for a table that has no `client_id` of its own (a row
#: keyed on its parent, whose client the route asserts through the parent: `year_end_checklist_items` hangs from its engagement).
SCOPE_KEYS = ("firm_id", "client_id")


def unscoped_updates_and_deletes(source: str, tables: frozenset, keys: dict | None = None) -> list[str]:
    """Every `.update(` or `.delete(` on one of `tables` whose chain does not filter each of its scope keys (`firm_id` and `client_id`,
    or the ones `keys` names for that table)."""
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    consts = module_constants(tree)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        found = _table_call_of(node, tables, consts)
        if found is None or node.func.attr not in {"update", "delete"}:
            continue
        chain = ast.unparse(_outer_chain(node, parents))
        table = found[1]
        need = (keys or {}).get(table, SCOPE_KEYS)
        if not all(re.search(r"\.eq\(\s*['\"]" + re.escape(k) + r"['\"]", chain) for k in need):
            out.append(f"{table} at line {node.lineno}")
    return out


def runtime_sources():
    for rel, text in tu.sources():
        if not rel.startswith(("scripts/", "tests/")):
            yield rel, text


def unprivileged_writes(tables: frozenset) -> list[str]:
    bad = []
    for rel, text in runtime_sources():
        if not any(t in text for t in tables):
            continue
        bad += [f"{rel}:{line} {fn}(): a write to {table} on {recv}" for table, fn, line, ok, recv in write_sites(text, tables) if not ok]
    return bad


def unscoped(tables: frozenset, keys: dict | None = None) -> list[str]:
    bad = []
    for rel, text in runtime_sources():
        if any(t in text for t in tables):
            bad += [f"{rel}: {hit}" for hit in unscoped_updates_and_deletes(text, tables, keys)]
    return bad


def census(tables: frozenset) -> dict[str, int]:
    found = {t: 0 for t in tables}
    for _rel, text in runtime_sources():
        if any(t in text for t in tables):
            for table, *_rest in write_sites(text, tables):
                found[table] += 1
    return found
