"""Read every PostgREST chain in apps/api and say whether it carries its firm scope.

WHY THIS IS A SEPARATE MODULE
    The guard (test_every_query_on_a_firm_table_carries_its_firm_scope.py) states
    the RULE and holds a frozen list. This file is the READER, kept apart so the
    guard's own negative controls can run it over a synthetic source string and
    over a real file with one line removed, and so the rule is not hidden inside
    a 1,000-line test.

    It reuses nothing from _backend_query_parser.py on purpose. That reader
    answers "which COLUMNS does a chain name" and flattens a chain to its parts;
    this one needs the chain as a unit (its table, its operation, every filter
    on it, and the statements around it), so it walks the tree its own way.

WHAT IS A CHAIN
    db.table("customers").select("*").eq("firm_id", f).eq("id", cid).execute()
    ^^^^^^^^^^^^^^^^^^^^^ root          ^^^^^^^^^^^^^^^^ filters
    One chain per root `.table("literal")`. A chain built across statements
    (`q = db.table("x").select("*")` ... `q = q.eq("firm_id", f)`) is read as ONE
    chain: the calls made on the name `q` after the assignment are folded in, and
    so are the calls made on a name built from it. A chain whose name is handed to
    another function, or returned, or that is never terminated in the expression,
    is `built elsewhere`: its filters are not all here to read, and it is COUNTED
    rather than guessed at.

    A CALL TO A REPOSITORY METHOD IS A CHAIN TOO. `client_repo.update(id, data)`
    runs `.table("clients").update(...).eq("id", id)` with no firm filter, and the
    firm check is its CALLER'S, so the repository's own chain can only say "bare".
    The call site is read as the query it stands for (table `repo:client_repo.update`),
    keyed on the id it passes and scoped when it passes the firm. The same is done
    for a function whose firm filter is CONDITIONAL on an optional `firm_id`
    argument (table `call:get_risk`): the filter is there when the caller asks for
    it, so the caller is what is judged.

WHEN A CHAIN IS SCOPED  (`scoped_by`, in the order tried)
    filter      .eq / .in_ / .filter("firm_id", ...), .match({"firm_id": ...}) or an
                .or_("...firm_id...") string, on the chain or on a call made later on
                the name it was assigned to; or an `.eq("parent.firm_id", ...)` on an
                embedded `parent!inner(...)`.
    payload     an INSERT or UPSERT whose payload carries a `firm_id` key: an inline
                dict (spreads followed), a list or comprehension of dicts, a name
                assigned one (with `name["firm_id"] = ...`, `.update`, `.append` and
                loops followed), a `dict(x, firm_id=...)`, or a call to a function in
                the same module whose returned dict carries one.
    gate        the chain is keyed on an id (`id` or a `*_id` column) whose value was
                handed, earlier in the same function, to a GATE (`assert_client_access`,
                any `_assert_*`, `_load_*_or_404`), or the chain is itself an argument
                of a gate. `verified_gates()` asks what each gate's DEFINITIONS do: a
                name counts only when every definition carrying it names the firm.
    parent-read the same value was already used, earlier in the function, as the PRIMARY
                KEY of a chain that is itself scoped: the parent was looked up under the
                firm and the child is keyed on it.
    flow        the id came OUT of a scoped chain in this function (a name assigned from
                one, a loop or comprehension variable over one), or out of a call that
                was handed the firm.
    post-fetch  the function reads `firm_id` off the row the chain returned, or hands that
                row to a gate: the check is made after the read, and the gates themselves
                are held to it.
    principal   the key is the caller's OWN identity (`current_user["id"]`).

    None of the last five is proof; each is the evidence an AST can read that someone
    looked. They are what the allowlist's `child-by-parent` category would otherwise
    restate by hand a hundred times, and the guard's frozen list holds only what they
    cannot clear.

WHAT IT DOES NOT SEE
    * `.rpc()` calls (a function takes the firm as an argument; there is no filter
      to read).
    * Whether the VALUE of `.eq("firm_id", x)` is the caller's firm and not a
      request field. The reader asks whether the filter is there.
    * Reads of `firms` (its tenant column is `id`, not `firm_id`).
    * A repository reached through a name it cannot resolve to a singleton.
"""
from __future__ import annotations

import ast
import functools
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

FN = (ast.FunctionDef, ast.AsyncFunctionDef)

OP_OF = {"select": "read", "insert": "insert", "update": "update",
         "delete": "delete", "upsert": "upsert"}
FILTER_METHODS = frozenset({
    "eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "is_", "in_",
    "contains", "contained_by", "filter", "not_", "match", "or_", "order",
    "range_gt", "range_gte", "range_lt", "range_lte", "overlaps", "text_search",
})
_QUERY_METHODS = FILTER_METHODS | frozenset(OP_OF)
# Methods that narrow by a column value and whose first argument is that column.
KEYING_METHODS = frozenset({"eq", "in_", "filter"})

# `_assert_invoice_scope`, `assert_client_access`, `_assert_via_parent`,
# `_load_article_or_404`, `_get_owned_or_404`, `can_access_client`: the names this
# codebase gives a function whose job is to refuse a row that is not the caller's.
# A NAME only nominates a function; whether it counts is decided by
# `verified_gates()`, which asks what its definitions actually do.
GATE_RE = re.compile(
    r"^(_?assert_[a-z_0-9]+|[a-z_0-9]*_or_404|_?load_[a-z_0-9]*_or_none|can_access_client)$")
_GATE_DEF_TEXT = re.compile(
    r"def\s+(_?assert_\w+|\w*_or_404|_?load_\w*_or_none|can_access_client)\s*\(")

PRINCIPAL_NAMES = frozenset({"current_user", "user", "principal"})

SKIP_DIRS = {"tests", "__pycache__", "venv", ".venv", "migrations"}


# ── Which tables carry a firm ────────────────────────────────────────────────

_CREATE_TABLE = re.compile(
    r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?"?([a-z_0-9]+)"?\s*\(', re.I)
_ADD_FIRM_COLUMN = re.compile(
    r'ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:public\.)?"?([a-z_0-9]+)"?\s+'
    r'ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?"?firm_id"?\b', re.I)


def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*[\s\S]*?\*/", " ", sql)
    return "\n".join(re.sub(r"--.*$", "", ln) for ln in sql.splitlines())


def _table_body(sql: str, open_paren: int) -> str:
    depth = 0
    for i in range(open_paren, len(sql)):
        if sql[i] == "(":
            depth += 1
        elif sql[i] == ")":
            depth -= 1
            if depth == 0:
                return sql[open_paren + 1:i]
    return ""


def firm_tables_from_snapshot(schema: dict) -> set[str]:
    """Every relation in the production snapshot that has a `firm_id` column."""
    return {t for t, cols in schema.items() if "firm_id" in cols}


def firm_tables_from_newer_migrations(migrations_dir: Path, applied_through: int) -> set[str]:
    """Tables a migration NEWER than the snapshot gives a `firm_id` column.

    The snapshot is a point in time (its meta file says which migration it was
    taken after), and a table created by migration 476 is invisible to it. A rule
    that derived its table set from the snapshot alone would let every newest
    table through unscoped until the next refresh.
    """
    found: set[str] = set()
    for path in sorted(migrations_dir.glob("[0-9][0-9][0-9]_*.sql")):
        if path.name.endswith("_rollback.sql"):
            continue
        if int(path.name[:3]) <= applied_through:
            continue
        sql = _strip_sql_comments(path.read_text(encoding="utf-8"))
        for m in _ADD_FIRM_COLUMN.finditer(sql):
            found.add(m.group(1).lower())
        for m in _CREATE_TABLE.finditer(sql):
            body = _table_body(sql, m.end() - 1)
            if re.search(r'(^|[,\s(])"?firm_id"?\s+[a-z]', body, re.I):
                found.add(m.group(1).lower())
    return found


# ── The chain ────────────────────────────────────────────────────────────────

@dataclass
class Chain:
    file: str
    function: str          # dotted: Class.method.inner, or <module>
    table: str             # the literal table, "<dynamic>", "repo:x.m" or "call:f"
    op: str                # read | insert | update | delete | upsert | none
    line: int
    scoped_by: str | None = None     # None means NOT scoped
    conditional: bool = False        # the firm filter sits under an `if`
    built_elsewhere: bool = False    # filters are not all readable here
    detail: str = ""                 # unparsed chain, for a failure message
    fn_params: tuple = ()            # enclosing function's parameters (for `conditional`)
    # The parameters of the enclosing function that decide which row this chain
    # reads or writes. Set only while the chain is unscoped: they are what the
    # function's CALLERS are asked to have checked.
    key_params: tuple = ()
    is_route: bool = False           # the enclosing function is an HTTP handler
    # For a call to a helper (`call:name` in "keys" mode) that is itself reached
    # with one of ITS caller's parameters: which, and whose.
    flow_params: tuple = ()
    caller_params: tuple = ()
    caller_name: str = ""
    helper: str = ""                 # "module::name" of the helper a `call:` chain stands for
    why: str = ""                    # what the evidence was (for a human reading a verdict)
    # An INSERT whose payload is one of the enclosing function's own parameters:
    # which. The firm key is then the CALLER's to supply, and is judged there.
    payload_param: str = ""

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.file, self.function, self.table, self.op)


@dataclass
class _Filter:
    method: str
    col: str
    value: ast.AST | None
    call: ast.Call | None = None
    embedded: bool = False         # the firm filter is on an embedded parent (`t.firm_id`)
    pk: bool = False               # a call's first id: it looks one row up by key
    forced: bool = False           # a call's key argument: judged whatever it is named


@dataclass
class _Raw:
    top: ast.Call
    table_call: ast.Call
    ops: list                       # [(method, Call)], in source order, root outward
    function: str
    outer: ast.AST                  # outermost enclosing function (or the module)
    assigned_to: str | None = None
    followers: list = field(default_factory=list)   # [(method, Call)] made on the name
    cond_calls: set = field(default_factory=set)    # id() of follower calls under an `if`
    escapes: bool = False
    # A call standing in for the query it makes:
    # {"table": "repo:client_repo.update", "op": "update", "params": [...]}.
    synthetic: dict | None = None


@dataclass
class FuncTarget:
    """A function whose CALLERS carry the firm scope its own chain lacks.

    mode "firm": its firm filter is conditional on a `firm_id` argument, so the
                 caller must pass one.
    mode "keys": its query is keyed on some of its parameters (`keys`) and says
                 nothing about the firm, so the caller must have checked what it
                 passes for them.
    mode "payload": it inserts one of its parameters as it is received, so the
                 caller must hand it a payload that carries `firm_id`.
    """
    op: str
    params: list
    mode: str = "firm"
    keys: list = field(default_factory=list)
    module: str = ""        # dotted module the function is defined in
    name: str = ""          # its simple name (two modules may each define one)
    payload: str = ""       # mode "payload": the parameter the INSERT writes verbatim

    @property
    def key(self) -> str:
        return f"{self.module}::{self.name}"


@dataclass
class CallTargets:
    """Calls to judge as the queries they stand for."""
    repos: dict = field(default_factory=dict)       # singleton -> {method: (op, params)}
    functions: dict = field(default_factory=dict)   # "module::name" -> FuncTarget

    def names(self) -> set[str]:
        return set(self.repos) | {t.name for t in self.functions.values()}

    def by_name(self, name: str) -> list["FuncTarget"]:
        return [t for t in self.functions.values() if t.name == name]

    def helper_keys(self) -> set[str]:
        return {k for k, t in self.functions.items() if t.mode == "keys"}


_AST = ast.AST
#: Leaves that carry no information the reader asks about (`Load`, `Add`, `And`, ...).
_LEAF = (ast.expr_context, ast.operator, ast.boolop, ast.unaryop, ast.cmpop)


def _children(node: ast.AST):
    """`ast.iter_child_nodes`, without the two generator layers and without the
    operator and context leaves: the walk below is the hot loop of the whole guard
    (about 750 files) and this is its inner step."""
    for name in node._fields:
        v = getattr(node, name, None)
        if v is None:
            continue
        if v.__class__ is list:
            for x in v:
                if isinstance(x, _AST) and not isinstance(x, _LEAF):
                    yield x
        elif isinstance(v, _AST) and not isinstance(v, _LEAF):
            yield v


class _Index:
    """One source file, walked ONCE: the parent map and every call in it."""

    def __init__(self, source: str):
        self.tree = ast.parse(source)
        self.parent: dict = {}
        self.attr_calls: list[ast.Call] = []     # calls whose func is an Attribute
        self.name_calls: list[ast.Call] = []     # calls whose func is a bare Name
        self.functions: dict[str, ast.AST] = {}
        # `from repositories.workflow_repository import workflow_repo as repo`
        self.repo_aliases: dict[str, str] = {}
        # local name -> the dotted modules it may be bound from
        self.imports: dict[str, set[str]] = {}
        self._scope: dict[int, list] = {}
        self.origin_cache: dict[int, dict] = {}
        # `self._repo = workflow_repo` in a constructor: attribute -> assigned value
        self.self_attrs: dict[str, ast.AST] = {}
        stack = [self.tree]
        parent = self.parent
        while stack:
            n = stack.pop()
            for c in _children(n):
                parent[c] = n
                stack.append(c)
                if isinstance(c, ast.Call):
                    if isinstance(c.func, ast.Attribute):
                        self.attr_calls.append(c)
                    elif isinstance(c.func, ast.Name):
                        self.name_calls.append(c)
                elif isinstance(c, ast.Assign) and len(c.targets) == 1 \
                        and isinstance(c.targets[0], ast.Attribute) \
                        and isinstance(c.targets[0].value, ast.Name) \
                        and c.targets[0].value.id == "self":
                    self.self_attrs.setdefault(c.targets[0].attr, c.value)
                elif isinstance(c, FN):
                    self.functions.setdefault(c.name, c)
                elif isinstance(c, ast.ImportFrom):
                    base = c.module or ""
                    for a in c.names:
                        local = a.asname or a.name
                        # `from services import x` binds a MODULE, `from services.x
                        # import f` an OBJECT in services.x: either is "from x".
                        self.imports.setdefault(local, set()).update({base, f"{base}.{a.name}"})
                        if base.startswith("repositories"):
                            self.repo_aliases[local] = a.name
                elif isinstance(c, ast.Import):
                    for a in c.names:
                        self.imports.setdefault(a.asname or a.name.split(".")[0], set()).add(
                            a.name if a.asname else a.name.split(".")[0])
        self.attr_calls.sort(key=lambda c: (c.lineno, c.col_offset))

    def scope_nodes(self, node: ast.AST) -> list:
        """Descendants of `node` in source order, stopping at nested classes only.

        Nested FUNCTIONS are included on purpose: a helper defined inside a handler
        closes over the handler's gate and its verified names, and judging it alone
        would call every closure unscoped.
        """
        got = self._scope.get(id(node))
        if got is None:
            out: list = []
            stack = [node]
            while stack:
                n = stack.pop()
                for c in _children(n):
                    if isinstance(c, ast.ClassDef):
                        continue
                    stack.append(c)
                    out.append(c)
            out.sort(key=lambda x: (getattr(x, "lineno", 0), getattr(x, "col_offset", 0)))
            self._scope[id(node)] = got = out
        return got


_INDEX_CACHE: dict[tuple[str, str], _Index] = {}


def _index(source: str, relpath: str) -> _Index:
    key = (relpath, hashlib.sha1(source.encode("utf-8")).hexdigest())
    got = _INDEX_CACHE.get(key)
    if got is None:
        if len(_INDEX_CACHE) > 2000:
            _INDEX_CACHE.clear()
        got = _INDEX_CACHE[key] = _Index(source)
    return got


def clear_cache() -> None:
    _INDEX_CACHE.clear()


def _chain_ops(top: ast.Call):
    ops = []
    cur: ast.AST = top
    while isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute):
        if cur.func.attr == "table" and cur.args:
            ops.reverse()
            return cur, ops
        ops.append((cur.func.attr, cur))
        cur = cur.func.value
    return None


def _root_name(expr: ast.AST) -> str | None:
    cur = expr
    while True:
        if isinstance(cur, ast.Name):
            return cur.id
        if isinstance(cur, ast.Attribute):
            cur = cur.value
        elif isinstance(cur, ast.Subscript):
            cur = cur.value
        elif isinstance(cur, ast.Call):
            if isinstance(cur.func, ast.Name) and cur.func.id in ("str", "int", "UUID") and cur.args:
                cur = cur.args[0]
            else:
                cur = cur.func
        elif isinstance(cur, ast.BoolOp) and cur.values:
            cur = cur.values[0]
        else:
            return None


def _hard(ch: "Chain") -> bool:
    """Scoped by something that was read (a filter, a payload, a gate, a flow...), as
    against the two provisional verdicts: a call in the mock branch, and a pass-through."""
    return bool(ch.scoped_by) and ch.scoped_by not in ("mock-branch", "pass-through")


def _field_ref(expr: ast.AST):
    """(root, field) for `data.client_id`, `data["client_id"]` or `data.get("client_id")`,
    seen through `str(...)` and `a or b`: the same value however it is spelled."""
    cur = expr
    for _ in range(4):
        if isinstance(cur, ast.Call) and isinstance(cur.func, ast.Name) \
                and cur.func.id in ("str", "int", "UUID") and cur.args:
            cur = cur.args[0]
        elif isinstance(cur, ast.BoolOp) and cur.values:
            cur = cur.values[0]
        else:
            break
    if isinstance(cur, ast.Attribute) and isinstance(cur.value, ast.Name):
        return (cur.value.id, cur.attr)
    if isinstance(cur, ast.Subscript) and isinstance(cur.value, ast.Name) \
            and isinstance(cur.slice, ast.Constant) and isinstance(cur.slice.value, str):
        return (cur.value.id, cur.slice.value)
    if isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute) \
            and cur.func.attr == "get" and cur.args \
            and isinstance(cur.args[0], ast.Constant) and isinstance(cur.args[0].value, str) \
            and isinstance(cur.func.value, ast.Name):
        return (cur.func.value.id, cur.args[0].value)
    return None


def _alias_ref(nodes: list, expr: ast.AST, before: int):
    """`client_id` assigned from `data.get("client_id")`: the field it stands for."""
    if not isinstance(expr, ast.Name):
        return None
    for n in nodes:
        if getattr(n, "lineno", 0) >= before:
            break
        if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                and isinstance(n.targets[0], ast.Name) and n.targets[0].id == expr.id:
            ref = _field_ref(n.value)
            if ref is not None:
                return ref
    return None


def _derives_from(nodes: list, name: str) -> set[str]:
    """Names `name` was built from, through assignments in this scope."""
    out: set[str] = set()
    todo = [name]
    while todo:
        cur = todo.pop()
        for n in nodes:
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == cur
                                                 for t in n.targets):
                for m in ast.walk(n.value):
                    if isinstance(m, ast.Name) and m.id not in out and m.id != name:
                        out.add(m.id)
                        todo.append(m.id)
    return out


def _block_key(stmt: ast.AST, parent: dict):
    """(owner, field) of the statement list `stmt` sits in: an If's body and its
    orelse are different blocks even though they share a parent node."""
    owner = parent.get(stmt)
    if owner is None:
        return (None, "")
    for fld in ("body", "orelse", "finalbody", "handlers"):
        lst = getattr(owner, fld, None)
        if isinstance(lst, list) and any(x is stmt for x in lst):
            return (id(owner), fld)
    return (id(owner), "")


def _root_of_chain(expr: ast.AST) -> str | None:
    """The Name a method chain starts from: `q` in `q.eq("a", 1).limit(2)`."""
    cur = expr
    while isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute):
        cur = cur.func.value
    return cur.id if isinstance(cur, ast.Name) else None


def _filters_of(ops) -> list[_Filter]:
    out: list[_Filter] = []
    for method, call in ops:
        if method in KEYING_METHODS and call.args:
            a = call.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                col = a.value
                value = call.args[1] if len(call.args) > 1 else None
                if col.endswith(".firm_id"):
                    out.append(_Filter(method, "firm_id", value, call, embedded=True))
                else:
                    out.append(_Filter(method, col, value, call))
            elif isinstance(a, ast.JoinedStr) and a.values \
                    and isinstance(a.values[-1], ast.Constant) \
                    and str(a.values[-1].value).endswith(".firm_id"):
                # .eq(f"{parent_table}.firm_id", firm_id)
                out.append(_Filter(method, "firm_id", call.args[1] if len(call.args) > 1 else None,
                                   call, embedded=True))
            elif not isinstance(a, ast.Constant) and len(call.args) > 1:
                out.append(_Filter(method, "*", call.args[1], call))   # `.eq(col, value)`
        elif method == "match" and call.args and isinstance(call.args[0], ast.Dict):
            for k, v in zip(call.args[0].keys, call.args[0].values, strict=True):
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    out.append(_Filter("eq", k.value, v, call))
        elif method == "or_" and call.args:
            try:
                text = ast.unparse(call.args[0])
            except Exception:
                text = ""
            if "firm_id" in text:
                out.append(_Filter("or_", "firm_id", None, call))
    return out


def _is_idish(col: str) -> bool:
    # "*" is a filter whose column is a variable (`.eq(col, value)`): it may be
    # anything, so it is judged like an id rather than ignored.
    return col in ("id", "*") or (col.endswith("_id") and col != "firm_id")


def _fn_params(fn: ast.AST) -> list[str]:
    a = fn.args
    return [x.arg for x in (a.posonlyargs + a.args + a.kwonlyargs) if x.arg not in ("self", "cls")]


def _is_route(fn: ast.AST) -> bool:
    """An HTTP handler: nothing calls it, the request does."""
    for d in getattr(fn, "decorator_list", []):
        try:
            text = ast.unparse(d)
        except Exception:
            continue
        if re.match(r"(router|app|api_router|[a-z_]*router)\.(get|post|put|patch|delete)\b", text):
            return True
    return False


def _origins(idx: "_Index", fn: ast.AST) -> dict[str, set[str]]:
    """name -> the parameters of `fn` it is built from (a parameter is its own)."""
    got = idx.origin_cache.get(id(fn))
    if got is None:
        got = idx.origin_cache[id(fn)] = _origins_uncached(idx, fn)
    return got


def _origins_uncached(idx: "_Index", fn: ast.AST) -> dict[str, set[str]]:
    origin: dict[str, set[str]] = {p: {p} for p in _fn_params(fn)}
    nodes = idx.scope_nodes(fn)
    for _ in range(3):
        grew = False
        for n in nodes:
            if isinstance(n, ast.Assign):
                value, tgts = n.value, n.targets
            elif isinstance(n, ast.AnnAssign) and n.value is not None:
                value, tgts = n.value, [n.target]
            elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
                value, tgts = n.iter, [n.target]
            else:
                continue
            # A row a READ brought back by a parameter's key carries that parameter's
            # origin (the rows of invoice `invoice_id` are as checked as it is). A
            # row an INSERT brought back is fresh, and its id is nobody's argument.
            if any(isinstance(m, ast.Call) and isinstance(m.func, ast.Attribute)
                   and m.func.attr in ("insert", "upsert") for m in ast.walk(value)):
                continue
            src: set[str] = set()
            for m in ast.walk(value):
                if isinstance(m, ast.Name) and m.id in origin:
                    src |= origin[m.id]
            if not src:
                continue
            for t in tgts:
                for m in ast.walk(t):
                    if isinstance(m, ast.Name):
                        cur = origin.setdefault(m.id, set())
                        if not src <= cur:
                            cur |= src
                            grew = True
        if not grew:
            break
    return origin


# ── Insert payloads ──────────────────────────────────────────────────────────

def _dict_has_firm(d: ast.Dict) -> bool:
    return any(isinstance(k, ast.Constant) and k.value == "firm_id" for k in d.keys)


def _returned_values(idx: _Index, fn: ast.AST):
    return [n.value for n in idx.scope_nodes(fn) if isinstance(n, ast.Return) and n.value is not None]


def _returns_firm_dict(idx: _Index, fn: ast.AST, depth: int, index: int | None = None) -> bool:
    rets = _returned_values(idx, fn)
    if not rets:
        return False
    out = []
    for r in rets:
        if index is not None:
            if not isinstance(r, ast.Tuple) or index >= len(r.elts):
                return False
            r = r.elts[index]
        out.append(_payload_has_firm(idx, r, fn, depth + 1))
    return all(out)


def _payload_has_firm(idx: _Index, expr: ast.AST, scope: ast.AST, depth: int = 0) -> bool:
    """Does the payload this expression names carry a `firm_id` key?

    Lenient about what it cannot resolve (an assignment from a store lookup in a
    mock branch is ignored) and strict about what it can: a dict literal with no
    `firm_id` key is not scoped, whatever is said about it elsewhere.
    """
    if depth > 4:
        return False
    if isinstance(expr, ast.Dict):
        if _dict_has_firm(expr):
            return True
        # {"id": x, **record}: the spread carries whatever `record` carries.
        return any(k is None and _payload_has_firm(idx, v, scope, depth + 1)
                   for k, v in zip(expr.keys, expr.values, strict=True))
    if isinstance(expr, ast.Subscript):
        # rows[i:i + 500]: a slice of a list whose rows were built here.
        return _payload_has_firm(idx, expr.value, scope, depth + 1)
    if isinstance(expr, (ast.List, ast.Tuple)):
        return bool(expr.elts) and all(_payload_has_firm(idx, e, scope, depth + 1) for e in expr.elts)
    if isinstance(expr, ast.DictComp):
        # {k: v for k, v in row.items() if k != "id"} keeps row's keys.
        gen = expr.generators[0] if expr.generators else None
        if gen is not None and isinstance(gen.iter, ast.Call) \
                and isinstance(gen.iter.func, ast.Attribute) and gen.iter.func.attr == "items":
            return _payload_has_firm(idx, gen.iter.func.value, scope, depth + 1)
        return False
    if isinstance(expr, (ast.ListComp, ast.GeneratorExp)):
        elt = expr.elt
        gen = expr.generators[0] if expr.generators else None
        if isinstance(elt, ast.Name) and gen is not None and isinstance(gen.target, ast.Tuple) \
                and isinstance(gen.iter, ast.Name):
            # [p for _, p in to_insert] where to_insert.append((idx, payload))
            pos = next((i for i, t in enumerate(gen.target.elts)
                        if isinstance(t, ast.Name) and t.id == elt.id), None)
            if pos is None:
                return False
            appended = []
            for n in idx.scope_nodes(scope):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                        and n.func.attr == "append" and isinstance(n.func.value, ast.Name) \
                        and n.func.value.id == gen.iter.id and n.args \
                        and isinstance(n.args[0], ast.Tuple) and pos < len(n.args[0].elts):
                    appended.append(n.args[0].elts[pos])
            return bool(appended) and all(
                _payload_has_firm(idx, a, scope, depth + 1) for a in appended)
        if isinstance(elt, ast.Name) and gen is not None and isinstance(gen.iter, ast.Name) \
                and isinstance(gen.target, ast.Name) and gen.target.id == elt.id:
            return _payload_has_firm(idx, gen.iter, scope, depth + 1)
        return _payload_has_firm(idx, elt, scope, depth + 1)
    if isinstance(expr, ast.IfExp):
        return (_payload_has_firm(idx, expr.body, scope, depth + 1)
                and _payload_has_firm(idx, expr.orelse, scope, depth + 1))
    if isinstance(expr, ast.Call):
        for kw in expr.keywords:
            if kw.arg == "firm_id":
                return True
        if isinstance(expr.func, ast.Name) and expr.func.id in idx.functions:
            return _returns_firm_dict(idx, idx.functions[expr.func.id], depth)
        return False
    if isinstance(expr, ast.Name):
        assigned: list[ast.AST] = []
        for n in idx.scope_nodes(scope):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name) and t.id == expr.id:
                        assigned.append(n.value)
                    elif isinstance(t, ast.Tuple):
                        # workflow, steps = _build(...) — the helper returns a tuple.
                        for i, e in enumerate(t.elts):
                            if isinstance(e, ast.Name) and e.id == expr.id \
                                    and isinstance(n.value, ast.Call) \
                                    and isinstance(n.value.func, ast.Name) \
                                    and n.value.func.id in idx.functions:
                                if _returns_firm_dict(idx, idx.functions[n.value.func.id], depth, i):
                                    return True
                    if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                            and t.value.id == expr.id and isinstance(t.slice, ast.Constant)
                            and t.slice.value == "firm_id"):
                        return True
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) \
                    and n.target.id == expr.id and n.value is not None:
                assigned.append(n.value)
            elif isinstance(n, ast.For) and isinstance(n.target, ast.Name) \
                    and n.target.id == expr.id:
                # for record in records: insert(record)
                assigned.append(n.iter)
            elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == expr.id:
                if n.func.attr == "update" and n.args and isinstance(n.args[0], ast.Dict) \
                        and _dict_has_firm(n.args[0]):
                    return True
                if n.func.attr == "setdefault" and n.args and isinstance(n.args[0], ast.Constant) \
                        and n.args[0].value == "firm_id":
                    return True
                if n.func.attr in ("append", "extend", "insert") and n.args:
                    assigned.append(n.args[-1])
        literal = [a for a in assigned if isinstance(a, (ast.Dict, ast.DictComp, ast.List,
                                                          ast.ListComp, ast.Call, ast.Tuple,
                                                          ast.Name))
                   and not (isinstance(a, ast.Name) and a.id == expr.id)]
        # A literal WITHOUT the key is not rescued by another assignment, but
        # an assignment this reader cannot resolve is not held against it.
        return bool(literal) and any(
            _payload_has_firm(idx, v, scope, depth + 1) for v in literal)
    return False


# ── Calls judged as the queries they stand for ───────────────────────────────

def _resolve_repo(recv: ast.AST, idx: _Index, repos: dict, depth: int = 0) -> str | None:
    if depth > 2:
        return None
    if isinstance(recv, ast.Attribute) and isinstance(recv.value, ast.Name) \
            and recv.value.id == "self" and recv.attr in idx.self_attrs:
        return _resolve_repo(idx.self_attrs[recv.attr], idx, repos, depth + 1)
    if isinstance(recv, ast.Name):
        if recv.id in repos:
            return recv.id
        real = idx.repo_aliases.get(recv.id)
        if real in repos:
            return real
        if recv.id.startswith("_") and recv.id.lstrip("_") in repos:
            return recv.id.lstrip("_")
        return None
    if isinstance(recv, ast.Call) and isinstance(recv.func, ast.Name) and not recv.args:
        nm = recv.func.id
        fn = idx.functions.get(nm)
        if fn is not None:
            for r in _returned_values(idx, fn):
                if isinstance(r, ast.Name):
                    real = idx.repo_aliases.get(r.id, r.id)
                    if real in repos:
                        return real
        if nm.startswith("_get_") and nm[5:] in repos:
            return nm[5:]
    return None


def _call_arg(call: ast.Call, params: list[str], name: str):
    if name in params:
        i = params.index(name)
        if i < len(call.args):
            return call.args[i]
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def _synthetic_chain(raw: _Raw, relpath: str, idx: _Index):
    call: ast.Call = raw.top
    spec = raw.synthetic
    params: list[str] = spec["params"]
    filters: list[_Filter] = []
    scoped_by = None
    payload_param = ""
    outer = raw.outer if isinstance(raw.outer, FN) else None

    def own_param(expr) -> str:
        """The enclosing function's parameter this payload IS, if any: the firm key
        is then its caller's to supply."""
        if expr is None or outer is None:
            return ""
        root = _root_name(expr)
        return root if root in _fn_params(outer) and root not in ("db", "firm_id") else ""

    if spec.get("mode") == "payload":
        arg = _call_arg(call, params, spec["payload"])
        if arg is not None and _payload_has_firm(idx, arg, raw.outer):
            scoped_by = "payload"
        elif arg is not None:
            payload_param = own_param(arg)
    elif spec.get("mode") == "keys":
        # The helper's query is keyed on these parameters; the caller must have
        # checked what it passes for them.
        for i, name in enumerate(spec["keys"]):
            a = _call_arg(call, params, name)
            if a is not None and not (isinstance(a, ast.Constant) and a.value is None):
                filters.append(_Filter("eq", name, a, call, pk=(i == 0), forced=True))
    else:
        firm_arg = _call_arg(call, params, "firm_id")
        if firm_arg is not None and not (isinstance(firm_arg, ast.Constant) and firm_arg.value is None):
            scoped_by = "filter"
        for i, name in enumerate(params):
            if name != "firm_id" and _is_idish(name):
                a = _call_arg(call, params, name)
                if a is not None and not (isinstance(a, ast.Constant) and a.value is None):
                    filters.append(_Filter("eq", name, a, call,
                                           pk=(i == 0 and name != "client_id")))
        if scoped_by is None and spec["op"] in ("insert", "upsert"):
            data = call.args[0] if call.args else _call_arg(call, params, "data")
            if data is not None and _payload_has_firm(idx, data, raw.outer):
                scoped_by = "payload"
            elif data is not None:
                payload_param = own_param(data)
    try:
        detail = ast.unparse(call)[:200]
    except Exception:
        detail = ""
    ch = Chain(file=relpath, function=raw.function, table=spec["table"], op=spec["op"],
               line=call.lineno, scoped_by=scoped_by, detail=detail,
               helper=spec.get("helper", ""), payload_param=payload_param)
    if outer is not None:
        ch.caller_name = outer.name
        ch.caller_params = tuple(_fn_params(outer))
        ch.is_route = _is_route(outer)
    return ch, filters


def _module_of(relpath: str) -> str:
    """`services/foo.py` -> `services.foo`; `pkg/__init__.py` -> `pkg`."""
    mod = relpath[:-3] if relpath.endswith(".py") else relpath
    mod = mod.replace("/", ".")
    return mod[:-len(".__init__")] if mod.endswith(".__init__") else mod


def _call_resolves(call: ast.Call, target: "FuncTarget", idx: _Index, relpath: str) -> str:
    """Is this call to the function `target` describes? "yes", "no" or "unknown".

    A helper is found by its simple name, and a simple name is shared: the tree has
    a dozen `create`, `record` and `process`. A call is to the helper only when it
    names the helper's own module (imported by that name) or is made inside that
    module; it is PROVABLY to something else when what it names is imported from, or
    defined in, a different module. Anything else (a parameter, an attribute of
    something, the result of a call) shares the name and nothing more: it is
    "unknown", it is not guessed at in either direction, and while one exists the
    helper's own chain is not cleared by its callers.
    """
    if not target.module:
        return "yes"
    here = _module_of(relpath)
    f = call.func
    if isinstance(f, ast.Name):
        if f.id in idx.functions and f.id not in idx.imports:
            return "yes" if here == target.module else "no"
        mods = idx.imports.get(f.id)
        if mods:
            return "yes" if target.module in mods else "no"
        return "unknown"
    recv = f.value
    if isinstance(recv, ast.Name):
        if recv.id in ("self", "cls"):
            return "yes" if here == target.module else "no"
        mods = idx.imports.get(recv.id)
        if mods:
            return "yes" if target.module in mods else "no"
    return "unknown"


def derive_call_targets(per_file: dict[str, tuple[list[Chain], "_Index | None"]],
                        firm_tables: set[str]) -> CallTargets:
    """What the callers must carry, read off a first scan of the tree.

    * every repository method that, judged alone, is not firm-scoped (bare, or
      scoped only when the caller supplies `firm_id`);
    * every other function whose firm filter is conditional on a `firm_id`
      parameter.
    """
    targets = CallTargets()
    for rel, (chains, idx) in per_file.items():
        in_repo = rel.startswith("repositories/")
        tree = idx.tree if idx is not None else None
        flagged: dict[str, dict[str, str]] = {}
        for ch in chains:
            if (ch.table not in firm_tables and ch.table != "<dynamic>") or ch.op == "none":
                continue
            if in_repo:
                if ch.scoped_by == "filter" and not ch.conditional:
                    continue
                if ch.scoped_by and ch.scoped_by != "filter":
                    continue    # cleared by evidence inside the method
                parts = ch.function.split(".")
                if len(parts) >= 2:
                    flagged.setdefault(parts[0], {})[parts[1]] = ch.op
            elif ch.conditional and ch.scoped_by == "filter" and "firm_id" in ch.fn_params:
                parts = ch.function.split(".")
                name = parts[0] if not parts[0][:1].isupper() else (parts[1] if len(parts) > 1 else parts[0])
                tgt = FuncTarget(ch.op, [p for p in ch.fn_params if p != "self"], "firm",
                                 module=_module_of(rel), name=name)
                targets.functions.setdefault(tgt.key, tgt)
            elif not ch.scoped_by and ch.key_params and not ch.is_route:
                # An unscoped query keyed on parameters: its callers carry the scope.
                parts = ch.function.split(".")
                name = parts[0] if not parts[0][:1].isupper() else (parts[1] if len(parts) > 1 else parts[0])
                tkey = f"{_module_of(rel)}::{name}"
                if tkey not in targets.functions:
                    targets.functions[tkey] = FuncTarget(
                        ch.op, list(ch.fn_params), "keys", list(ch.key_params),
                        module=_module_of(rel), name=name)
                else:
                    t = targets.functions[tkey]
                    if t.mode == "keys":
                        t.keys = sorted(set(t.keys) | set(ch.key_params))
        if not in_repo:
            for ch in chains:
                if ch.scoped_by or not ch.payload_param or ch.is_route or ch.op not in ("insert", "upsert"):
                    continue
                if ch.table not in firm_tables and ch.table != "<dynamic>":
                    continue
                name = _simple_name(ch.function)
                tkey = f"{_module_of(rel)}::{name}"
                targets.functions.setdefault(tkey, FuncTarget(
                    ch.op, list(ch.fn_params), "payload", [], module=_module_of(rel), name=name,
                    payload=ch.payload_param))
        if not in_repo or tree is None:
            continue
        singletons: dict[str, str] = {}
        for n in tree.body:
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) \
                    and isinstance(n.value.func, ast.Name) and len(n.targets) == 1 \
                    and isinstance(n.targets[0], ast.Name):
                singletons[n.value.func.id] = n.targets[0].id
        for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
            if cls.name not in singletons:
                continue
            methods = {m.name: m for m in cls.body if isinstance(m, FN)}
            mm = dict(flagged.get(cls.name, {}))
            for _ in range(3):
                for name, fn in methods.items():
                    if name in mm:
                        continue
                    for c in ast.walk(fn):
                        if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) \
                                and isinstance(c.func.value, ast.Name) and c.func.value.id == "self" \
                                and c.func.attr in mm:
                            mm[name] = mm[c.func.attr]
                            break
            table: dict[str, tuple[str, list[str]]] = {}
            for name, op in mm.items():
                fn = methods.get(name)
                if fn is None or name.startswith("__"):
                    continue
                table[name] = (op, [a.arg for a in fn.args.args if a.arg != "self"])
            if table:
                targets.repos[singletons[cls.name]] = table
    return targets


# ── One file ─────────────────────────────────────────────────────────────────

def _qualname(node: ast.AST, parent: dict) -> str:
    names = []
    cur = node
    while cur in parent:
        cur = parent[cur]
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(cur.name)
    return ".".join(reversed(names)) or "<module>"


def _outer_function(node: ast.AST, parent: dict, tree: ast.AST) -> ast.AST:
    outer: ast.AST = tree
    cur = node
    while cur in parent:
        cur = parent[cur]
        if isinstance(cur, FN):
            outer = cur
        if isinstance(cur, ast.ClassDef):
            break
    return outer


_MOCK_FLAG = re.compile(r"^_?(USE_)?MOCK\w*$|^_USE_MOCK$")


def _in_mock_branch(node: ast.AST, parent: dict) -> bool:
    """Is this node inside `if _USE_MOCK:` (or the else of `if not _USE_MOCK:`)?

    That branch reads and writes an in-memory list, never the database, so a CALL
    made there is not a query. A `.table(...)` chain in it would be a defect of its
    own, and is not excused: only calls standing in for queries are.
    """
    cur = node
    while cur in parent:
        p = parent[cur]
        if isinstance(p, ast.If):
            test = p.test
            negated = isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
            if negated:
                test = test.operand
            nm = test.id if isinstance(test, ast.Name) else None
            if nm and _MOCK_FLAG.match(nm):
                in_body = any(cur is s for s in p.body)
                if in_body != negated:
                    return True
        cur = p
    return False


def _under_condition(node: ast.AST, parent: dict, stop: ast.AST) -> bool:
    cur = node
    while cur in parent and cur is not stop:
        cur = parent[cur]
        if isinstance(cur, (ast.If, ast.IfExp)) and cur is not stop:
            return True
    return False


def scan_source(source: str, relpath: str, firm_tables: set[str],
                allowed_gates: set[str] | None = None,
                targets: CallTargets | None = None,
                _idx: "_Index | None" = None) -> tuple[list[Chain], list[str]]:
    """(chains, gate-call names seen). Every chain, scoped or not, firm table or not.

    `allowed_gates` is the set of gate NAMES allowed to count as evidence (see
    `verified_gates`). Left out, every name GATE_RE nominates counts, which is what
    a synthetic source in a test wants. `targets` adds the calls that stand for
    queries (see `derive_call_targets`).
    """
    idx = _idx if _idx is not None else _index(source, relpath)
    tree, parent = idx.tree, idx.parent
    calls = idx.attr_calls
    inner = {id(n.func.value) for n in calls if isinstance(n.func.value, ast.Call)}

    raws: list[_Raw] = []
    for n in calls:
        if id(n) in inner:
            continue
        r = _chain_ops(n)
        if r is None:
            continue
        table_call, ops = r
        raws.append(_Raw(top=n, table_call=table_call, ops=ops,
                         function=_qualname(n, parent),
                         outer=_outer_function(n, parent, tree)))

    unresolved: list[Chain] = []
    if targets is not None and (targets.repos or targets.functions):
        fn_names = {t.name for t in targets.functions.values()}
        for n in idx.attr_calls + idx.name_calls:
            spec = None
            fname = None
            if isinstance(n.func, ast.Attribute):
                single = _resolve_repo(n.func.value, idx, targets.repos) if targets.repos else None
                if single is not None and n.func.attr in targets.repos[single]:
                    op, params = targets.repos[single][n.func.attr]
                    spec = {"table": f"repo:{single}.{n.func.attr}", "op": op, "params": params}
                elif n.func.attr in fn_names:
                    fname = n.func.attr
            elif isinstance(n.func, ast.Name) and n.func.id in fn_names:
                fname = n.func.id
            if fname is not None:
                fq0 = _qualname(n, parent)
                if fq0.split(".")[-1] == fname:
                    continue        # a function's own recursion is not a caller
                chosen = None
                for t in targets.by_name(fname):
                    verdict = _call_resolves(n, t, idx, relpath)
                    if verdict == "yes":
                        chosen = t
                        break
                    if t.mode in ("keys", "payload") and verdict == "unknown":
                        # Same name, but not provably the function: it cannot be
                        # judged, and while one exists the helper's own chain is not
                        # cleared by its callers.
                        unresolved.append(Chain(
                            file=relpath, function=fq0, table=f"unresolved:{fname}", op=t.op,
                            line=n.lineno, scoped_by="unresolved", helper=t.key))
                    elif t.mode == "firm" and verdict != "no" and chosen is None:
                        # A conditional-firm function is judged by name alone unless
                        # the call is provably to something else: that errs towards
                        # asking for the firm, which is the safe direction.
                        chosen = t
                if chosen is None:
                    continue
                spec = {"table": f"call:{fname}", "op": chosen.op, "params": chosen.params,
                        "mode": chosen.mode, "keys": chosen.keys, "helper": chosen.key,
                        "payload": chosen.payload}
            if spec is None:
                continue
            raws.append(_Raw(top=n, table_call=n, ops=[], function=_qualname(n, parent),
                             outer=_outer_function(n, parent, tree), synthetic=spec))

    # Per outer scope: the nodes in source order and the gate calls.
    scope_cache: dict[int, dict] = {}

    def info(outer: ast.AST) -> dict:
        got = scope_cache.get(id(outer))
        if got is not None:
            return got
        nodes = idx.scope_nodes(outer)
        gate_calls = []
        for c in nodes:
            if isinstance(c, ast.Call):
                f = c.func
                nm = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                if nm and GATE_RE.match(nm) and (allowed_gates is None or nm in allowed_gates):
                    args = [ast.unparse(a) for a in c.args] + [ast.unparse(k.value) for k in c.keywords]
                    gate_calls.append((c.lineno, nm, set(args),
                                       list(c.args) + [k.value for k in c.keywords]))
        got = {"nodes": nodes, "gates": gate_calls}
        scope_cache[id(outer)] = got
        return got

    # Fold calls made later on the name a chain was assigned to, and on any name
    # that is itself built from it (`q = (base.select(a) if c else base.select(b))`).
    def assigned_name(top: ast.AST) -> str | None:
        cur = top
        p = parent.get(cur)
        while isinstance(p, (ast.IfExp, ast.BoolOp)):
            cur = p
            p = parent.get(cur)
        if isinstance(p, ast.Assign) and p.value is cur and len(p.targets) == 1 \
                and isinstance(p.targets[0], ast.Name):
            return p.targets[0].id
        if isinstance(p, ast.AnnAssign) and p.value is cur and isinstance(p.target, ast.Name):
            return p.target.id
        return None

    def assign_stmt(top: ast.AST) -> ast.AST:
        cur = top
        while not isinstance(cur, (ast.Assign, ast.AnnAssign)) and cur in parent:
            cur = parent[cur]
        return cur

    def chain_root(c: ast.AST) -> str | None:
        cur: ast.AST = c
        while isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute):
            cur = cur.func.value
        return cur.id if isinstance(cur, ast.Name) else None

    for raw in raws:
        nm = assigned_name(raw.top)
        if nm is None:
            continue
        raw.assigned_to = nm
        if raw.synthetic is not None:
            continue
        nodes = info(raw.outer)["nodes"]
        start = raw.top.lineno
        # `q = q.eq(...)` continues the chain; `q = <something else>` ends it, but
        # only in the SAME block: the arms of an if/elif ladder each bind `q` to a
        # different table and share what is done to `q` after the ladder.
        my_block = _block_key(assign_stmt(raw.top), parent)
        rebinds = sorted(
            a.lineno for a in nodes
            if isinstance(a, ast.Assign) and a.lineno > start
            and any(isinstance(t, ast.Name) and t.id == nm for t in a.targets)
            and _root_of_chain(a.value) != nm
            and _block_key(a, parent) == my_block)
        end = rebinds[0] if rebinds else 10 ** 9
        names = {nm}
        for _ in range(3):
            grew = False
            for a in nodes:
                if isinstance(a, ast.Assign) and start <= a.lineno < end and len(a.targets) == 1 \
                        and isinstance(a.targets[0], ast.Name) and a.targets[0].id not in names:
                    if any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                           and chain_root(c) in names for c in ast.walk(a.value)):
                        names.add(a.targets[0].id)
                        grew = True
            if not grew:
                break
        top_subtree = {id(n) for n in ast.walk(raw.top)}
        seen_calls: set[int] = set()
        for c in nodes:
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) \
                    and start <= c.lineno < end and id(c) not in top_subtree \
                    and chain_root(c) in names:
                sub = []
                cur: ast.AST = c
                while isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute):
                    if id(cur) not in seen_calls:
                        sub.append((cur.func.attr, cur))
                        seen_calls.add(id(cur))
                    cur = cur.func.value
                sub.reverse()
                raw.followers.extend(sub)
                if _under_condition(c, parent, raw.outer):
                    raw.cond_calls.update(id(call) for _m, call in sub)
        # A name handed on (argument, return, attribute) means more filters may be
        # added where this file cannot see them.
        for c in nodes:
            if isinstance(c, ast.Name) and c.id in names and isinstance(c.ctx, ast.Load) \
                    and start <= c.lineno < end:
                par = parent.get(c)
                if isinstance(par, ast.Attribute) and par.value is c:
                    continue
                if isinstance(par, ast.Call) and c in par.args or isinstance(par, ast.keyword) \
                        or isinstance(par, (ast.Return, ast.Yield)):
                    raw.escapes = True

    chains: list[Chain] = []
    prelim: list[tuple[Chain, _Raw, list[_Filter], bool]] = []
    for raw in raws:
        if raw.synthetic is not None:
            ch, filters = _synthetic_chain(raw, relpath, idx)
            prelim.append((ch, raw, filters, True))
            chains.append(ch)
            continue
        arg = raw.table_call.args[0]
        table = arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else "<dynamic>"
        all_ops = list(raw.ops) + list(raw.followers)
        op = next((OP_OF[m] for m, _ in all_ops if m in OP_OF), "none")
        filters = _filters_of(all_ops)
        scoped_by = None
        conditional = False
        inner_join = any(m == "select" and c.args and "!inner" in ast.unparse(c.args[0])
                         for m, c in all_ops)
        for f in filters:
            if f.col == "firm_id" and (not f.embedded or inner_join):
                if scoped_by is None or id(f.call) not in raw.cond_calls:
                    conditional = id(f.call) in raw.cond_calls
                scoped_by = "filter"
        if scoped_by is None:
            for m, c in all_ops:
                if m in ("insert", "upsert") and c.args:
                    if _payload_has_firm(idx, c.args[0], raw.outer):
                        scoped_by = "payload"
        terminated = any(m == "execute" for m, _ in all_ops)
        built_elsewhere = raw.escapes or (raw.assigned_to is None and not terminated)
        try:
            detail = ast.unparse(raw.top)[:200]
        except Exception:
            detail = ""
        in_fn = isinstance(raw.outer, FN)
        ch = Chain(file=relpath, function=raw.function, table=table, op=op,
                   line=raw.table_call.lineno, scoped_by=scoped_by,
                   conditional=conditional, built_elsewhere=built_elsewhere, detail=detail,
                   fn_params=tuple(_fn_params(raw.outer)) if in_fn else (),
                   is_route=in_fn and _is_route(raw.outer))
        chains.append(ch)
        prelim.append((ch, raw, filters, terminated))

    # Evidence from the surroundings, to a fixpoint (it only ever adds).
    vcache: dict = {}
    pfcache: dict = {}
    for _ in range(4):
        changed = False
        by_outer: dict[int, list] = {}
        for item in prelim:
            by_outer.setdefault(id(item[1].outer), []).append(item)
        for items in by_outer.values():
            if all(ch.scoped_by for ch, _r, _f, _t in items):
                continue
            outer = items[0][1].outer
            inf = info(outer)
            # Only a chain that was actually scoped vouches for what came out of it or
            # for the value it was keyed on: a call in the mock branch queried nothing,
            # and a pass-through is a promise somebody else keeps (and may not).
            scoped_tops = {id(raw.top) for ch, raw, _f, _t in items if _hard(ch)}
            scoped_vars = {raw.assigned_to for ch, raw, _f, _t in items
                           if _hard(ch) and raw.assigned_to}
            vkey = (id(outer), frozenset(scoped_tops), frozenset(scoped_vars))
            verified = vcache.get(vkey)
            if verified is None:
                verified = vcache[vkey] = _verified_names(inf["nodes"], scoped_tops, scoped_vars)
            for ch, raw, filters, _term in items:
                if ch.scoped_by:
                    continue
                if raw.synthetic is not None and _in_mock_branch(raw.top, parent):
                    ch.scoped_by = "mock-branch"
                    changed = True
                    continue
                keys = [f for f in filters
                        if (_is_idish(f.col) or f.forced) and f.value is not None]
                for f in keys:
                    vtext = ast.unparse(f.value)
                    root = _root_name(f.value)
                    how = None
                    for ln, gname, args, _argnodes in inf["gates"]:
                        if ln < ch.line and vtext in args:
                            how = f"gate:{gname}"
                            break
                    if how is None:
                        vref = _field_ref(f.value) or _alias_ref(inf["nodes"], f.value, ch.line)
                        if vref is not None:
                            derived = _derives_from(inf["nodes"], vref[0])
                            for ln, gname, _args, argnodes in inf["gates"]:
                                if ln >= ch.line:
                                    continue
                                if any((ar := _field_ref(an)) is not None and ar[1] == vref[1]
                                       and (ar[0] == vref[0] or ar[0] in derived)
                                       for an in argnodes):
                                    how = f"gate:{gname}"
                                    break
                    if how is None:
                        for och, _oraw, ofilters, _ot in items:
                            if och is ch or not _hard(och) or och.line >= ch.line:
                                continue
                            # The parent is looked up by its PRIMARY KEY: a scoped chain
                            # that merely filtered on `client_id` returned nothing for
                            # a foreign client, but nothing was REFUSED, so the same
                            # value on another table would not be a checked one.
                            if any((of.col == "id" or of.pk) and of.value is not None
                                   and ast.unparse(of.value) == vtext for of in ofilters):
                                how = "parent-read"
                                break
                    if how is None and any(
                            isinstance(n, ast.Name) and n.id in verified
                            for n in ast.walk(f.value)):
                        how = "flow"
                    if how is None and root in PRINCIPAL_NAMES:
                        how = "principal"
                    if how:
                        ch.scoped_by = how
                        ch.why = f"{how.split(':')[0]} for {vtext}"
                        changed = True
                        break
                if not ch.scoped_by:
                    wrap = _wrapping_gate(raw.top, parent, allowed_gates)
                    if wrap:
                        ch.scoped_by = f"gate:{wrap}"
                        changed = True
                if not ch.scoped_by:
                    # Static for a chain (its scope, its gates and its line do not
                    # change between passes), so it is read once.
                    pf = pfcache.get(id(raw.top))
                    if pf is None:
                        pf = pfcache[id(raw.top)] = _reads_firm_of_result(
                            inf["nodes"], raw, inf["gates"], ch.line, parent)
                    if pf:
                        ch.scoped_by = "post-fetch"
                        ch.why = pf
                        changed = True
                if not ch.scoped_by and raw.synthetic is not None \
                        and raw.synthetic.get("mode") == "keys":
                    _pass_through(idx, raw, ch, filters, targets, relpath)
                    if ch.scoped_by:
                        changed = True
        if not changed:
            break

    # What a chain that is still unscoped is keyed on, among its function's parameters:
    # the thing its callers are asked to have checked.
    for ch, raw, filters, _term in prelim:
        if ch.scoped_by or raw.synthetic is not None or not isinstance(raw.outer, FN):
            continue
        origin = _origins(idx, raw.outer)
        names = {n.id for f in filters if _is_idish(f.col) and f.value is not None
                 for n in ast.walk(f.value) if isinstance(n, ast.Name)}
        flow: set[str] = set()
        for nm in names:
            flow |= origin.get(nm, set())
        ch.key_params = tuple(p for p in _fn_params(raw.outer)
                              if p in flow and p not in ("db", "firm_id"))
        if ch.op in ("insert", "upsert"):
            for m, c in list(raw.ops) + list(raw.followers):
                if m in ("insert", "upsert") and c.args:
                    root = _root_name(c.args[0])
                    if root in _fn_params(raw.outer) and root not in ("db", "firm_id", "self", "cls"):
                        ch.payload_param = root

    gate_names = sorted({gname for inf in scope_cache.values() for _l, gname, _a, _n in inf["gates"]})
    return chains + unresolved, gate_names


def _pass_through(idx: _Index, raw: _Raw, ch: Chain, filters: list, targets: "CallTargets | None",
                  relpath: str) -> None:
    """A helper reached with the CALLER'S OWN parameter: the check is owed by the
    caller's callers, which are judged in their turn, so this call site passes only
    when the caller is itself a helper (and not an HTTP handler, which nothing
    calls: the request does, and a request is where an unchecked id comes from)."""
    caller = raw.outer
    if not isinstance(caller, FN):
        return
    ch.caller_name = caller.name
    ch.caller_params = tuple(_fn_params(caller))
    if _is_route(caller):
        ch.is_route = True
        return
    origin = _origins(idx, caller)
    flow: set[str] = set()
    for f in filters:
        if f.value is None:
            continue
        for n in ast.walk(f.value):
            if isinstance(n, ast.Name) and n.id in origin:
                flow |= origin[n.id]
    ch.flow_params = tuple(p for p in ch.caller_params if p in flow and p not in ("db", "firm_id"))
    if ch.flow_params and targets is not None \
            and f"{_module_of(relpath)}::{caller.name}" in targets.helper_keys():
        ch.scoped_by = "pass-through"


def _wrapping_gate(top: ast.AST, parent: dict, allowed: set[str] | None) -> str | None:
    """`_assert_engagement_scope(user, repo.find_by_id(id))`: the read is an
    argument of the gate, which sees what it returned and refuses it."""
    p = parent.get(top)
    if isinstance(p, ast.keyword):
        p = parent.get(p)
    if isinstance(p, ast.Call):
        f = p.func
        nm = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
        if nm and GATE_RE.match(nm) and (allowed is None or nm in allowed):
            return nm
    return None


def _reads_firm_of_result(nodes: list, raw: "_Raw", gates: list, line: int, parent: dict) -> str:
    """Does the function COMPARE the `firm_id` of a row this chain returned?

    `row = db.table("t").select("*").eq("id", i).execute().data[0]` followed by
    `if row.get("firm_id") != firm_id: raise ...` (or by a verified gate that is
    handed `row`) is a check made AFTER the read: nothing was filtered, and nothing
    was returned to the caller either. It is the shape a gate has when it must tell
    "no such row" from "someone else's".

    Only a COMPARISON counts. Reading `row["firm_id"]` to stamp it onto what is
    built next (`{"firm_id": engagement["firm_id"], ...}`) is the opposite of a
    check: it carries the foreign row's firm into the new row.
    """
    seeds = {raw.assigned_to} if raw.assigned_to else set()
    names = _verified_names(nodes, {id(raw.top)}, seeds)
    for ln, _nm, args, _argnodes in gates:
        # A CLIENT gate is not a check of the row it is handed the client of:
        # `can_access_client(user, None)` is True (a firm-level row has no client
        # scope), so a row with no client_id passes it whoever's it is. It vouches
        # for a client id BEFORE a read; after one it vouches for nothing.
        if _nm in ("can_access_client", "assert_client_access"):
            continue
        if ln > line and any(a in names for a in args):
            return f"handed to {_nm} at line {ln}"

    def compared(expr: ast.AST) -> bool:
        cur = expr
        while True:
            p = parent.get(cur)
            if isinstance(p, ast.Call) and isinstance(p.func, ast.Name) and p.func.id in ("str", "int") \
                    and cur in p.args:
                cur = p
                continue
            return isinstance(p, ast.Compare)

    for n in nodes:
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) \
                and n.slice.value == "firm_id" and _root_name(n.value) in names \
                and n.lineno > line and compared(n):
            return f"compares ...['firm_id'] at line {n.lineno}"
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" \
                and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "firm_id" \
                and _root_name(n.func.value) in names and n.lineno > line and compared(n):
            return f"compares .get('firm_id') at line {n.lineno}"
    return ""


def _handed_the_firm(call: ast.Call) -> bool:
    """A call given the firm (`find_mapping(db, firm_id, ...)`,
    `svc.get(current_user, ...)`) is trusted to answer for it: if the callee did
    not filter on it, ITS chain would be an unscoped one and the guard would be
    holding it. The trust is not extended to a call that was not handed the firm."""
    for a in list(call.args) + [k.value for k in call.keywords]:
        if isinstance(a, ast.Name) and a.id in ("firm_id", "current_user", "user"):
            return True
        if isinstance(a, ast.Subscript) and isinstance(a.slice, ast.Constant) \
                and a.slice.value == "firm_id":
            return True
        if isinstance(a, ast.Call) and isinstance(a.func, ast.Attribute) and a.func.attr == "get" \
                and a.args and isinstance(a.args[0], ast.Constant) and a.args[0].value == "firm_id":
            return True
    return False


_FACTS: dict[int, tuple] = {}


def _binding_facts(nodes: list) -> list:
    """For every statement in `nodes` that binds a name from an expression: the names
    it binds, the names and the call nodes the expression contains, and whether it
    contains a call that was handed the firm. Read once per scope; what is verified
    is then a set computation over these (the expressions are walked ONCE, not once
    per pass per chain)."""
    got = _FACTS.get(id(nodes))
    if got is not None and got[0] is nodes:
        return got[1]
    facts: list = []

    def bound(target: ast.AST, out: list) -> None:
        # Names being ASSIGNED, never the ones merely used to address the slot:
        # `cache[auth_user_id] = row` verifies `cache`'s contents, not the key.
        if isinstance(target, ast.Name):
            out.append(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for e in target.elts:
                bound(e, out)
        elif isinstance(target, ast.Starred):
            bound(target.value, out)

    def of(expr: ast.AST, targets: list) -> None:
        names: set[str] = set()
        call_ids: set[int] = set()
        handed = False
        for n in ast.walk(expr):
            if isinstance(n, ast.Name):
                names.add(n.id)
            elif isinstance(n, ast.Call):
                call_ids.add(id(n))
                if not (isinstance(n.func, ast.Attribute) and n.func.attr in _QUERY_METHODS) \
                        and _handed_the_firm(n):
                    handed = True
        if targets:
            facts.append((targets, names, call_ids, handed))

    for n in nodes:
        out: list = []
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) \
                and isinstance(n.value.func, ast.Attribute) \
                and n.value.func.attr in ("append", "add", "extend") \
                and isinstance(n.value.func.value, ast.Name) and n.value.args:
            # `movement_ids.append(movement["id"])`: the list holds what came out
            # of a call that was handed the firm.
            of(n.value.args[0], [n.value.func.value.id])
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                bound(t, out)
            of(n.value, out)
        elif isinstance(n, ast.AnnAssign) and n.value is not None:
            bound(n.target, out)
            of(n.value, out)
        elif isinstance(n, ast.NamedExpr):
            bound(n.target, out)
            of(n.value, out)
        elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
            bound(n.target, out)
            of(n.iter, out)
        elif isinstance(n, ast.withitem) and n.optional_vars is not None:
            bound(n.optional_vars, out)
            of(n.context_expr, out)
    if len(_FACTS) > 4000:
        _FACTS.clear()
    _FACTS[id(nodes)] = (nodes, facts)
    return facts


def _verified_names(nodes: list, scoped_tops: set[int], scoped_vars: set[str]) -> set[str]:
    """Names holding something that came out of a scoped chain in this scope."""
    verified = set(scoped_vars)
    facts = _binding_facts(nodes)
    for _ in range(3):
        before = len(verified)
        for targets, names, call_ids, handed in facts:
            if handed or (scoped_tops and not call_ids.isdisjoint(scoped_tops)) \
                    or not names.isdisjoint(verified):
                verified.update(targets)
        if len(verified) == before:
            break
    return verified


# ── The tree ─────────────────────────────────────────────────────────────────

def source_files(api_root: Path):
    for path in sorted(api_root.rglob("*.py")):
        if SKIP_DIRS & set(path.relative_to(api_root).parts):
            continue
        yield path


def _simple_name(function: str) -> str:
    """`Class.method` -> method, `outer.inner` -> outer, `fn` -> fn."""
    parts = function.split(".")
    return parts[0] if not parts[0][:1].isupper() else (parts[1] if len(parts) > 1 else parts[0])


def scan_tree(api_root: Path, firm_tables: set[str], *, return_targets: bool = False):
    """(every chain, every gate name called, files that would not parse)
    and, asked for, the call targets the callers were judged against.

    The first pass reads every file that makes a `.table(...)` query. That is enough
    to know which repository methods, which conditional functions and which keyed
    helpers their CALLERS must carry the scope to. The following passes read again
    only the files that mention one of those (so a tree of 780 files is parsed once
    and scanned about twice over its small query-bearing part), and repeat while a
    caller that merely passes ITS OWN parameter on turns out to be a helper in its
    turn: the check is owed further up, and is judged there.
    """
    gates: set[str] = set()
    unparsed = 0
    verified = verified_gates(api_root)
    texts: dict[str, str] = {}
    for path in source_files(api_root):
        texts[str(path.relative_to(api_root))] = path.read_text(encoding="utf-8")

    first: dict[str, tuple[list[Chain], "_Index | None"]] = {}
    for rel, src in texts.items():
        if ".table(" not in src:
            continue
        try:
            idx = _index(src, rel)
        except SyntaxError:
            unparsed += 1
            continue
        got, g = scan_source(src, rel, firm_tables, verified, None, idx)
        first[rel] = (got, idx)
        gates.update(g)

    targets = derive_call_targets(first, firm_tables)
    chains: list[Chain] = []
    # What a file's chains depend on, besides its own source, is the targets it
    # CALLS (a repository singleton by name, a function as `name(`): a file whose
    # relevant targets are unchanged since it was last read keeps its chains.
    seen: dict[str, tuple] = {}
    words: dict[str, set[str]] = {rel: set(re.findall(r"[A-Za-z_]\w*", src))
                                  for rel, src in texts.items()}
    for _round in range(6):
        repo_names = set(targets.repos)
        fn_names = {t.name for t in targets.functions.values()}
        chains = []
        for rel, src in texts.items():
            w = words[rel]
            cand_fns = fn_names & w
            called = set(repo_names & w)
            if cand_fns:
                call_re = re.compile(r"\b(" + "|".join(sorted(map(re.escape, cand_fns))) + r")\s*\(")
                called |= set(call_re.findall(src))
            if not called:
                if rel in first:
                    chains.extend(first[rel][0])
                continue
            sig = tuple(sorted(
                (t.key, t.mode, t.op, tuple(t.keys), tuple(t.params), t.payload)
                for t in targets.functions.values() if t.name in called)) \
                + tuple(sorted(r for r in targets.repos if r in called))
            prev = seen.get(rel)
            if prev is not None and prev[0] == sig:
                chains.extend(prev[1])
                gates.update(prev[2])
                continue
            try:
                idx = _index(src, rel)
            except SyntaxError:
                unparsed += 1
                continue
            got, g = scan_source(src, rel, firm_tables, verified, targets, idx)
            seen[rel] = (sig, got, g)
            chains.extend(got)
            gates.update(g)
        grew = False
        for c in chains:
            if c.table.startswith(("call:", "repo:")) and not c.scoped_by and c.payload_param \
                    and not c.is_route and c.op in ("insert", "upsert"):
                ckey = f"{_module_of(c.file)}::{c.caller_name}"
                if ckey not in targets.functions:
                    targets.functions[ckey] = FuncTarget(
                        c.op, list(c.caller_params), "payload", [],
                        module=_module_of(c.file), name=c.caller_name, payload=c.payload_param)
                    grew = True
        for c in chains:
            if c.table.startswith("call:") and not c.scoped_by and c.flow_params and not c.is_route:
                ckey = f"{_module_of(c.file)}::{c.caller_name}"
                t = targets.functions.get(ckey)
                if t is None:
                    targets.functions[ckey] = FuncTarget(
                        c.op, list(c.caller_params), "keys", list(c.flow_params),
                        module=_module_of(c.file), name=c.caller_name)
                    grew = True
                elif t.mode == "keys" and not set(c.flow_params) <= set(t.keys):
                    t.keys = sorted(set(t.keys) | set(c.flow_params))
                    grew = True
        if not grew:
            break

    # A keyed helper's own chain is scoped by its callers when every one of them
    # (and there must be one: a helper nothing calls is not judged by anybody) has
    # something to show for the keys it passes.
    #
    # That is a LEAST fixpoint, deliberately: a call that only hands on its own
    # caller's parameter ("pass-through") stands only when the function it sits in
    # is itself a helper that STANDS, and a function stands when it has at least one
    # call and every call of it does. Starting from "everything stands" would accept
    # two helpers that call each other and nothing else, and would accept a
    # dependency the framework calls (`get_current_user`), which has no call site at
    # all: the chain of evidence has to END somewhere that looked, not run off the
    # end of the program.
    by_call: dict[str, list[Chain]] = {}
    blocked: set[str] = set()
    for c in chains:
        if c.table.startswith("call:"):
            by_call.setdefault(c.helper, []).append(c)
        elif c.table.startswith("unresolved:"):
            blocked.add(c.helper)
    standing: set[str] = set()

    def stands(call: Chain) -> bool:
        caller = f"{_module_of(call.file)}::{call.caller_name}"
        if call.scoped_by:
            return call.scoped_by != "pass-through" or caller in standing
        if call.payload_param and not call.is_route and call.op in ("insert", "upsert"):
            return caller in standing       # it relays a payload it was itself handed
        return False

    grew = True
    while grew:
        grew = False
        for key, calls in by_call.items():
            if key in standing or key in blocked:
                continue
            t = targets.functions.get(key)
            if t is None or t.mode not in ("keys", "payload"):
                continue
            if calls and all(stands(x) for x in calls):
                standing.add(key)
                grew = True
    for c in chains:
        if c.scoped_by == "pass-through" \
                and f"{_module_of(c.file)}::{c.caller_name}" not in standing:
            c.scoped_by = None          # nothing above it looked: it is where the trail ends
        elif not c.scoped_by and c.payload_param and not c.is_route \
                and c.table.startswith(("repo:", "call:")) \
                and f"{_module_of(c.file)}::{c.caller_name}" in standing:
            c.scoped_by = "pass-through"    # its caller's payloads all carry the firm
    for c in chains:
        if c.scoped_by or not (c.key_params or c.payload_param) \
                or c.table.startswith(("repo:", "call:", "unresolved:")):
            continue
        if f"{_module_of(c.file)}::{_simple_name(c.function)}" in standing:
            c.scoped_by = "callers"
    if return_targets:
        return chains, gates, unparsed, targets
    return chains, gates, unparsed


def gate_definitions(api_root: Path) -> dict[str, list[tuple[str, ast.AST, str]]]:
    """gate name -> [(file, node, source)] for every definition in the tree."""
    out: dict[str, list] = {}
    for path in source_files(api_root):
        src = path.read_text(encoding="utf-8")
        if not _GATE_DEF_TEXT.search(src):
            continue
        rel = str(path.relative_to(api_root))
        try:
            idx = _index(src, rel)
        except SyntaxError:
            continue
        lines = src.splitlines()
        for n in idx.parent:
            if isinstance(n, FN) and GATE_RE.match(n.name):
                body = "\n".join(lines[n.lineno - 1:n.end_lineno])
                out.setdefault(n.name, []).append((rel, n, body))
    return out


def _called_names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def _code_mentions_firm(node: ast.AST) -> bool:
    """Does the definition NAME the firm in its CODE (a variable, an attribute, a
    string key, a keyword argument), docstring and comments aside?

    The first version asked whether the text `firm_id` appeared in the source, and
    two gates passed on a sentence in their docstrings. A gate that only talks about
    the firm is not one that asks.
    """
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    for stmt in body:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Name) and n.id == "firm_id":
                return True
            if isinstance(n, ast.Attribute) and n.attr == "firm_id":
                return True
            if isinstance(n, ast.Constant) and n.value == "firm_id":
                return True
            if isinstance(n, ast.keyword) and n.arg == "firm_id":
                return True
    return False


@functools.lru_cache(maxsize=8)
def gate_verdicts(api_root: Path) -> dict[str, tuple[bool, list[str]]]:
    """gate name -> (verified, [files of the definitions that are not]).

    A definition is firm-aware when its own source names `firm_id`, or it calls a
    gate that is. A NAME is verified only when EVERY definition carrying it is: two
    routers each define `_assert_engagement_scope`, and the one that checks
    nothing must not be vouched for by the one that does.
    """
    defs = gate_definitions(api_root)
    roots: dict[tuple[str, int], bool] = {}
    called: dict[tuple[str, int], set[str]] = {}
    for items in defs.values():
        for f, node, _src in items:
            roots[(f, node.lineno)] = _code_mentions_firm(node)
            called[(f, node.lineno)] = _called_names(node)
    verified_names: set[str] = set()
    for _ in range(8):
        grew = False
        for name, items in defs.items():
            if name in verified_names:
                continue
            ok = True
            for f, node, _src in items:
                key = (f, node.lineno)
                if roots[key]:
                    continue
                if any(c in verified_names and c != name for c in called[key]):
                    continue
                ok = False
            if ok:
                verified_names.add(name)
                grew = True
        if not grew:
            break
    out: dict[str, tuple[bool, list[str]]] = {}
    for name, items in defs.items():
        bad = [f for f, node, _s in items
               if not roots[(f, node.lineno)]
               and not any(c in verified_names and c != name for c in called[(f, node.lineno)])]
        out[name] = (name in verified_names, bad)
    return out


def verified_gates(api_root: Path) -> set[str]:
    return {n for n, (ok, _bad) in gate_verdicts(api_root).items() if ok}


def census(chains: list[Chain], firm_tables: set[str]) -> dict:
    """What the scan covered, in numbers the guard pins exactly.

    `judged` is every query chain on a table that carries a `firm_id`, plus a
    table named by a variable (it may be one); `unjudged_no_firm_column` is every
    chain on a table that has no such column, which this rule does not reach (its
    tenant is its parent's, and that is the assignment-scope rule's business).
    """
    real = [c for c in chains if not c.table.startswith(("call:", "repo:", "unresolved:"))]
    synthetic = [c for c in chains if c.table.startswith(("call:", "repo:"))]
    firm = [c for c in real if c.table in firm_tables or c.table == "<dynamic>"]
    out = {
        "chains": len(real),
        "judged": len(firm),
        "calls_judged_as_queries": len(synthetic),
        "unjudged_no_firm_column": len(real) - len(firm),
        "table_named_by_a_variable": sum(1 for c in real if c.table == "<dynamic>"),
        # A chain whose filters are not all in the statement the reader is looking at
        # AND whose firm scope is not visible on it either: scoped by what its
        # callers do, or by flow, or not at all. (A chain built inside a lambda, or
        # across statements, whose firm filter IS visible is simply scoped.)
        "handed_on_without_a_visible_firm_filter": sum(
            1 for c in firm if c.built_elsewhere and c.scoped_by != "filter"),
        "same_name_calls_not_provably_the_helper": sum(
            1 for c in chains if c.table.startswith("unresolved:")),
    }
    by: dict[str, int] = {}
    for c in firm + synthetic:
        if c.op == "none":
            continue
        k = c.scoped_by.split(":")[0] if c.scoped_by else "unscoped"
        by[k] = by.get(k, 0) + 1
    out["by_evidence"] = dict(sorted(by.items()))
    return out


def unscoped(chains: list[Chain], firm_tables: set[str]) -> dict[tuple, int]:
    """key -> how many chains with that key carry no firm scope the reader can see.

    A chain on a table with no `firm_id` column is not this rule's; a table named by
    a variable is judged as though it had one (it may); a call standing for a query
    is judged as that query. A same-name call the reader could not tie to its helper
    is not a chain at all (`census` counts it) and never an entry.
    """
    out: dict[tuple, int] = {}
    for ch in chains:
        if ch.scoped_by or ch.op == "none":
            continue
        if ch.table in firm_tables or ch.table == "<dynamic>" \
                or ch.table.startswith(("repo:", "call:")):
            out[ch.key] = out.get(ch.key, 0) + 1
    return out
