"""One scanner for "who writes this table", shared by the guards that hold a table to its one writer.

It reads the AST of every module the API runs or ships (`scripts/` included: a one-off script run with a service key is still a
writer) and reports each place a table's name is used as a value or written in SQL text. Two guards used to carry their own
copies and the copies drifted (one saw a constant table name, the other did not), so the rule lives here once.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
WRITE_VERBS = {"insert", "update", "delete", "upsert"}


def sources():
    """(relative path, text) of every module the API runs or ships, tests and migrations excluded."""
    for path in sorted(API_ROOT.rglob("*.py")):
        rel = path.relative_to(API_ROOT).as_posix()
        if rel.startswith(("tests/", "migrations/", ".venv", "venv/")) or "/.venv/" in rel or "/venv/" in rel:
            continue
        yield rel, path.read_text(encoding="utf-8")


def raw_write(table: str) -> "re.Pattern":
    return re.compile(r"\b(insert\s+into|update|delete\s+from|truncate(\s+table)?)\s+(only\s+)?(public\.)?%s\b" % table, re.I)


def _is_a_value_use(node, parents) -> bool:
    """Is a bare string naming the table something that could be handed on to a `.table(...)` call later: an argument or a
    keyword value, the right-hand side of an assignment, a return value, a tuple, list or set element, or a dict VALUE. A dict
    KEY, a subscript and a comparison are labels, not table handles."""
    parent = parents.get(node)
    if isinstance(parent, (ast.Call, ast.keyword, ast.Assign, ast.AnnAssign, ast.Return, ast.Tuple, ast.List, ast.Set)):
        return True
    if isinstance(parent, ast.Dict):
        return node in parent.values
    return False


def uses(source: str, table: str):
    """(kind, function, line, receiver, verbs) for every place `table` is named as a value or written in SQL text.

    kind is `write` (a write verb chained off `.table(...)` / `.from_(...)`), `read` (a chain with no write verb), `unchained`
    (the query is kept in a variable, so what is done to it is not visible), `named` (the name as a bare string used as a value
    any other way: a constant, an argument, a keyword value, a tuple of tables) and `raw_write` (INSERT INTO / UPDATE / DELETE
    FROM / TRUNCATE in a string). A docstring is not a use, and neither is the string as a dict key. A statement at module level
    counts as the function `<module>`.
    """
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                docstrings.add(body[0].value)

    def enclosing(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
        return "<module>"

    raw = raw_write(table)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)) or node in docstrings:
            continue
        if raw.search(node.value):
            yield "raw_write", enclosing(node), node.lineno, None, []
            continue
        if node.value != table:
            continue
        call = parents.get(node)
        # `.table(name="x")` carries the name in a keyword, one level further up
        if isinstance(call, ast.keyword):
            call = parents.get(call)
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in {"table", "from_"}
                and (node in call.args or any(k.value is node for k in call.keywords))):
            verbs, up = [], call
            while True:
                parent = parents.get(up)
                if isinstance(parent, ast.Attribute) and isinstance(parents.get(parent), ast.Call):
                    verbs.append(parent.attr)
                    up = parents[parent]
                else:
                    break
            written = [v for v in verbs if v in WRITE_VERBS]
            if written:
                yield "write", enclosing(node), node.lineno, call.func.value, written
            elif not verbs:
                yield "unchained", enclosing(node), node.lineno, call.func.value, []
            else:
                yield "read", enclosing(node), node.lineno, call.func.value, verbs
        elif _is_a_value_use(node, parents):
            yield "named", enclosing(node), node.lineno, None, []
