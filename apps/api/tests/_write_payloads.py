"""What every write in the API puts in each column, read once for the rules over keyed columns and status vocabularies (POST-A-166).

WHY THIS EXISTS
    The rule that a column keyed to `users` takes the internal id, and the rule that a status written is one its CHECK admits, each read
    the writes their own way: a window of text around `.table("x")`, or the braces of a payload that follows the table call. Both were
    blind to two shapes, and the first is how `documents.uploaded_by` was written with an id its key could never hold:
      * a payload built in one function and written by another (`document_repo.create(data)` in a router, and
        `.table("documents").insert({**data, ...})` in the repository), and
      * a value held in a name (`status = "failed"` ... `{"status": status}`).
    This reader sees both, so the two rules (and the one over the retired `team_members` keys) ask the same question of the same writes.

WHAT IT READS
    A WRITE is `.table("T").insert(X)`, `.upsert(X)` or `.update(X)` with a literal table name, anywhere in a function or method of the
    source tree `_call_graph.CallGraph` reads. X is read as rows: a dict literal (a `**name` spread followed), a list, tuple or
    comprehension of them, `dict(...)`, or a name bound to one of those in the same function, with `name["col"] = v`,
    `name.update({...})`, `name.update(col=v)`, `name.setdefault("col", v)` and `name.append({...})` folded in.
    A PAYLOAD PARAMETER is a parameter that reaches X whole: `.insert(data)`, `.insert({**data, ...})`, or a name bound to
    `{**data, ...}` or `dict(data, ...)`. Every resolved caller of its function is read: what the caller hands over is read as rows in
    the CALLER's function, and a caller that hands over its own parameter (whole or spread) makes that parameter a payload parameter too,
    so router -> service -> repository is followed to wherever the dict is actually built.

WHAT IT DOES NOT SEE
    A payload returned by a call (`od.row_for(...)`), a caller `CallGraph` cannot resolve (it says which it can), a column whose name is
    a variable, a value assembled in a loop over another name, and `.rpc()`. The rules built on it are a floor, as before, with the floor
    raised by the two shapes above.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from tests._call_graph import CallGraph, chain_of

_WRITE_OPS = ("insert", "update", "upsert")
_MAX_DEPTH = 4


@dataclass(frozen=True)
class Write:
    """One (table, column) a write sets, the expression it sets it to, and where that expression sits."""
    module: str                   # the dotted module the VALUE sits in (the caller's, for a followed write)
    line: int
    table: str
    column: str
    value: ast.AST = field(compare=False, hash=False)
    scope: ast.AST = field(compare=False, hash=False, repr=False)   # the function the value is read in
    via: str = ""                 # "" for a write made where the dict is built; else "module:function" of the function that writes it
    function: tuple[str, str] = ("", "")   # the CallGraph key of the function the value is read in


def tables_of(call: ast.Call) -> set[str]:
    """The literal `.table("T")` names on the chain a write call is made on."""
    return {c.args[0].value for name, c in chain_of(call)[1:]
            if name == "table" and len(c.args) == 1 and isinstance(c.args[0], ast.Constant)
            and isinstance(c.args[0].value, str)}


def _write_calls(fn: ast.AST):
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _WRITE_OPS
                and node.args):
            tables = tables_of(node)
            if tables:
                yield node, tables


def _bindings(fn: ast.AST, name: str):
    """What the function puts into `name`: whole values (('=', expr)) and single keys (('key', col, expr)); spreads and rows alike."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    yield ("=", node.value)
                elif (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == name
                      and isinstance(t.slice, ast.Constant) and isinstance(t.slice.value, str)):
                    yield ("key", t.slice.value, node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name and node.value:
            yield ("=", node.value)
        elif (isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == name
              and isinstance(node.op, ast.BitOr)):
            yield ("=", node.value)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and isinstance(node.func.value, ast.Name) and node.func.value.id == name):
            if node.func.attr in ("update", "append", "extend"):
                for a in node.args:
                    yield ("=", a)
                for kw in node.keywords:
                    if kw.arg:
                        yield ("key", kw.arg, kw.value)
            elif (node.func.attr == "setdefault" and len(node.args) == 2 and isinstance(node.args[0], ast.Constant)
                  and isinstance(node.args[0].value, str)):
                yield ("key", node.args[0].value, node.args[1])


def pairs(expr: ast.AST, fn: ast.AST | None, depth: int = 0):
    """(column, value) for every key the payload expression is known to carry, read in the function `fn`."""
    if depth > _MAX_DEPTH or expr is None:
        return
    if isinstance(expr, ast.Dict):
        for k, v in zip(expr.keys, expr.values, strict=True):
            if k is None:
                yield from pairs(v, fn, depth + 1)
            elif isinstance(k, ast.Constant) and isinstance(k.value, str):
                yield k.value, v
    elif isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
        for e in expr.elts:
            yield from pairs(e.value if isinstance(e, ast.Starred) else e, fn, depth + 1)
    elif isinstance(expr, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
        yield from pairs(expr.elt, fn, depth + 1)
    elif isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
        yield from pairs(expr.left, fn, depth + 1)
        yield from pairs(expr.right, fn, depth + 1)
    elif isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "dict":
        for a in expr.args:
            yield from pairs(a, fn, depth + 1)
        for kw in expr.keywords:
            if kw.arg:
                yield kw.arg, kw.value
            else:
                yield from pairs(kw.value, fn, depth + 1)
    elif isinstance(expr, ast.Name) and fn is not None:
        for b in _bindings(fn, expr.id):
            if b[0] == "=":
                yield from pairs(b[1], fn, depth + 1)
            else:
                yield b[1], b[2]


def spread_params(expr: ast.AST, fn: ast.AST, params: set[str], depth: int = 0) -> set[str]:
    """The parameters of `fn` that reach this payload whole: handed over as it, or spread into it."""
    if depth > _MAX_DEPTH or expr is None:
        return set()
    if isinstance(expr, ast.Name):
        out = {expr.id} & params
        for b in _bindings(fn, expr.id):
            if b[0] == "=" and b[1] is not expr:
                out |= spread_params(b[1], fn, params, depth + 1)
        return out
    if isinstance(expr, ast.Dict):
        return set().union(*(spread_params(v, fn, params, depth + 1) for k, v in zip(expr.keys, expr.values, strict=True)
                             if k is None)) if None in expr.keys else set()
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
        return spread_params(expr.left, fn, params, depth + 1) | spread_params(expr.right, fn, params, depth + 1)
    if isinstance(expr, ast.Call):
        f = expr.func
        if isinstance(f, ast.Name) and f.id == "dict" and expr.args:
            return spread_params(expr.args[0], fn, params, depth + 1)
        if isinstance(f, ast.Attribute) and f.attr == "copy" and not expr.args:
            return spread_params(f.value, fn, params, depth + 1)
    return set()


def literal_strings(expr: ast.AST, fn: ast.AST | None, depth: int = 0) -> set[str]:
    """Every string literal the expression can be: itself, either arm of a conditional, or what a name is bound to in the function."""
    if depth > _MAX_DEPTH or expr is None:
        return set()
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return {expr.value}
    if isinstance(expr, ast.IfExp):
        return literal_strings(expr.body, fn, depth + 1) | literal_strings(expr.orelse, fn, depth + 1)
    if isinstance(expr, ast.BoolOp):
        return set().union(*(literal_strings(v, fn, depth + 1) for v in expr.values))
    if isinstance(expr, ast.Name) and fn is not None:
        out: set[str] = set()
        for b in _bindings(fn, expr.id):
            if b[0] == "=":
                out |= literal_strings(b[1], fn, depth + 1)
        return out
    return set()


class Reader:
    """Every write of the tree, direct and followed. Build once per test module: it parses the whole API."""

    def __init__(self, root: Path, graph: CallGraph | None = None):
        self.graph = graph or CallGraph(root)
        self.carriers: dict[tuple[str, str], dict[str, set[str]]] = {}     # function -> payload parameter -> tables
        self.writes: list[Write] = []
        self._read()

    def _read(self) -> None:
        g = self.graph
        for key, fn in g.funcs.items():
            params = set(g.parameters(fn))
            for call, tables in _write_calls(fn):
                payload = call.args[0]
                for col, value in pairs(payload, fn):
                    for t in sorted(tables):
                        self.writes.append(Write(key[0], getattr(value, "lineno", call.lineno), t, col, value, fn, "", key))
                for p in spread_params(payload, fn, params):
                    self.carriers.setdefault(key, {}).setdefault(p, set()).update(tables)

        # Follow each payload parameter to its callers, and theirs, until nothing new is found.
        done: set[tuple[tuple[str, str], str, tuple[str, str], int]] = set()
        frontier = [(k, p) for k, ps in self.carriers.items() for p in ps]
        for _ in range(8):
            nxt = []
            for key, p in frontier:
                tables = self.carriers[key][p]
                for caller, call in g.callers(key):
                    if (key, p, caller, id(call)) in done:
                        continue
                    done.add((key, p, caller, id(call)))
                    arg = g.argument_for(call, key, p)
                    if arg is None:
                        continue
                    cfn = g.funcs[caller]
                    via = f"{key[0]}:{key[1]}"
                    for col, value in pairs(arg, cfn):
                        for t in sorted(tables):
                            self.writes.append(Write(caller[0], getattr(value, "lineno", call.lineno), t, col, value, cfn, via,
                                                     caller))
                    for q in spread_params(arg, cfn, set(g.parameters(cfn))):
                        have = self.carriers.setdefault(caller, {}).setdefault(q, set())
                        if not tables <= have:
                            have.update(tables)
                            nxt.append((caller, q))
            if not nxt:
                break
            frontier = nxt

    def followed(self) -> list[Write]:
        return [w for w in self.writes if w.via]
