"""A payroll, bank or document table is queried with the privileged client, and the source says so at the query (POST-A-339).

THE PREMISE
    The API runs under the caller's own sign-in (`USE_USER_JWT`, the production default), so a service that takes a `db` parameter
    from a route reads and writes with `authenticated`, and `authenticated` still holds privileges on these tables: the only reason
    a person with their own token cannot call PostgREST by hand and read a colleague's payslips is a row policy. POST-A-010 took the
    BROWSER off them. This is the half that lets the grant be taken away: nothing in the API may need it. A query that does would
    start to fail the day the grant goes (and fail SOFT, the way the stock callers did when 535 and 536 were reviewed: the lookup
    answers "not found", the list is empty, the posting is skipped), so every such query is made with the privileged client now, in a
    change that ships BEFORE the migration that revokes.

    The privileged client carries no row security. What the signed-in role's policies did (the firm, the client assignment, the
    role tier) is now the caller's to assert, and the routes that reach these tables did already: `rbac()`, `assert_client_access`,
    `filter_by_client`, and a `firm_id` on every query (`test_every_query_on_a_firm_table_carries_its_firm_scope.py`). This test is
    the half that cannot be seen from one handler: WHICH client a query is made with.

THE RULE, NOT A SPELLING OF IT
    Every `.table("<sensitive table>")` (and every `.table(<not a literal>)` that a sensitive table can reach: the function spells one
    in its body, or a call in the same module hands it one as that very argument, because a table chosen at run time is where the
    next one hides) and every `.rpc("<function that reads a bank table as its caller>")` starts from
    a privileged expression: a call of `privileged_for(db)` / `service_db()` / `service_db_or_none()` / `service_db_or_503()` /
    `get_service_supabase()`, a module-level name bound to one of them (`_db = db_provider.service_db_or_none`), a no-argument
    function that returns one, `<privileged> or db`, or a local bound only to such an expression. A PARAMETER is never privileged,
    whatever its caller passes, because the next caller is the one that passes the wrong one. What the rule decides is the
    expression at the query, which is the one place it can be read.

ONE MODULE IS EXEMPT BY ITS SHAPE, AND THE SHAPE IS TESTED
    `routers/payroll.py` binds `_db` to the privileged provider (its own comment says why: a request-scoped client is silently
    downgraded to `authenticated`, which lacks the write grant its writers need), has no other source of a client, and every
    `db` in it is assigned from `_db()`. 190 queries pass `db` into its helpers; wrapping each would add nothing the three checks
    below do not already prove.

WHAT IT DOES NOT SEE
    Supabase Storage (a separate change takes the bucket's policies off a signed-in session), a sensitive table handed to a
    run-time-table function from ANOTHER module, an embedded select (`select("*, payroll_employees(name)")` reads the embedded table as
    the same client as the outer one, so the outer query's client is the one that matters and is checked), and a client held in
    an attribute (`self._db`), which no module that touches these tables uses.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests import _table_uses as tu
from tests._sensitive_tables import SENSITIVE_RPCS, is_sensitive

API = Path(__file__).resolve().parents[1]

#: The functions that return the privileged client (or, for `privileged_for`, the privileged client where a database exists).
PRIVILEGED_CALLS = {"privileged_for", "service_db", "service_db_or_none", "service_db_or_503", "get_service_supabase"}

#: Every way a module obtains the caller's OWN client.
REQUEST_GETTERS = {"get_supabase", "request_db", "request_db_or_none", "get_user_client", "get_request_supabase",
                   "get_user_supabase", "get_anon_supabase"}

#: module -> why the shape check replaces the per-query check.
WHOLLY_PRIVILEGED = {
    "routers/payroll.py": "`_db = db_provider.service_db_or_none`, no request-scoped getter anywhere, every `db` assigned from `_db()`",
}


# ── the analyser ─────────────────────────────────────────────────────────────

def _callee(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def privileged_names(tree: ast.Module) -> set[str]:
    """The privileged provider functions, plus every module-level name bound to one, and every function of the module whose every
    `return` is the privileged client (`_db = db_provider.service_db_or_none`, `def _svc(): return get_service_supabase()`, and a
    helper that takes a client and answers `_service_db() or db`)."""
    names = set(PRIVILEGED_CALLS)
    changed = True
    while changed:
        changed = False
        for node in tree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id not in names and _callee(node.value) in names
                    and not isinstance(node.value, ast.Call)):
                names.add(node.targets[0].id)
                changed = True
            elif isinstance(node, ast.FunctionDef) and node.name not in names:
                returns = [r.value for r in ast.walk(node) if isinstance(r, ast.Return) and r.value is not None]
                if returns and all(_returns_privileged(v, names) for v in returns) and any(
                        _is_privileged_call(c, names) for v in returns for c in ast.walk(v)):
                    names.add(node.name)
                    changed = True
    return names


def _is_privileged_call(node: ast.AST, names: set[str]) -> bool:
    return isinstance(node, ast.Call) and _callee(node.func) in names


def _returns_privileged(node: ast.AST, names: set[str]) -> bool:
    """A return value that is the privileged client, `None` (mock mode: no database, so no client at all), or `<privileged> or x`."""
    if isinstance(node, ast.Constant) and node.value is None:
        return True
    if isinstance(node, ast.IfExp):
        return _returns_privileged(node.body, names) and _returns_privileged(node.orelse, names)
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return _returns_privileged(node.values[0], names)
    return _is_privileged_call(node, names)


def _walk_scope(scope: ast.AST):
    """The nodes of one scope, not descending into the bodies of functions, lambdas or classes nested in it."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        n = stack.pop()
        yield n
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(n))


class _Scope:
    """The assignments visible from one query: its function's, the enclosing functions' and the module's."""

    def __init__(self, tree: ast.Module, parents: dict):
        self.tree, self.parents = tree, parents

    def chain(self, node: ast.AST) -> list[ast.AST]:
        out = []
        while node in self.parents:
            node = self.parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                out.append(node)
        out.append(self.tree)
        return out

    def bindings(self, name: str, node: ast.AST) -> list[ast.AST] | None:
        """Every value assigned to `name` in the nearest scope that binds it, or None when that scope binds it as a parameter
        or in a way that has no single value (a `for` target, a `with ... as`, a tuple unpack). [] when nothing binds it."""
        for scope in self.chain(node):
            if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                args = scope.args
                params = {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}
                params |= {a.arg for a in (args.vararg, args.kwarg) if a}
                if name in params:
                    return None
            values, opaque = [], False
            for n in _walk_scope(scope):
                if isinstance(n, ast.Assign):
                    for t in n.targets:
                        if isinstance(t, ast.Name) and t.id == name:
                            values.append(n.value)
                        elif isinstance(t, (ast.Tuple, ast.List)) and any(isinstance(e, ast.Name) and e.id == name for e in ast.walk(t)):
                            opaque = True
                elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == name and n.value is not None:
                    values.append(n.value)
                elif isinstance(n, (ast.For, ast.AsyncFor)) and any(isinstance(e, ast.Name) and e.id == name for e in ast.walk(n.target)):
                    opaque = True
                elif isinstance(n, ast.withitem) and n.optional_vars is not None and any(
                        isinstance(e, ast.Name) and e.id == name for e in ast.walk(n.optional_vars)):
                    opaque = True
            if values or opaque:
                return None if opaque else values
        return []


def is_privileged(node: ast.AST, names: set[str], scope: _Scope, at: ast.AST, depth: int = 0) -> bool:
    if depth > 4:
        return False
    if isinstance(node, ast.Call):
        return _callee(node.func) in names
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return is_privileged(node.values[0], names, scope, at, depth + 1)
    if isinstance(node, ast.IfExp):
        branches = (node.body, node.orelse)
        return (all((isinstance(b, ast.Constant) and b.value is None) or is_privileged(b, names, scope, at, depth + 1)
                    for b in branches)
                and any(is_privileged(b, names, scope, at, depth + 1) for b in branches))
    if isinstance(node, ast.Name):
        values = scope.bindings(node.id, at)
        return bool(values) and all(is_privileged(v, names, scope, at, depth + 1) for v in values)
    return False


def _chain_receiver(call: ast.Call) -> ast.AST:
    """For `X.table(...)` the expression `X`."""
    assert isinstance(call.func, ast.Attribute)
    return call.func.value


def _enclosing_function(node: ast.AST, parents: dict):
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    return None


def _a_sensitive_name_can_reach(first: ast.AST, call: ast.Call, tree: ast.Module, parents: dict) -> bool:
    """Could the table a `.table(<not a literal>)` is given be a sensitive one? Yes when the function that makes the call spells
    a sensitive table anywhere in its body (a tuple of tables it loops over), or when the table is one of its parameters and any
    call in the same module hands that function a sensitive literal. A table named in another module is not seen: the module
    that names it is the one that is read."""
    fn = _enclosing_function(call, parents)
    if fn is None:
        return False
    if any(isinstance(n, ast.Constant) and isinstance(n.value, str) and is_sensitive(n.value) for n in ast.walk(fn)):
        return True
    if not isinstance(first, ast.Name):
        return False
    params = [a.arg for a in fn.args.posonlyargs + fn.args.args]
    if first.id not in params and first.id not in [a.arg for a in fn.args.kwonlyargs]:
        return False
    index = params.index(first.id) - (1 if params and params[0] in {"self", "cls"} else 0) if first.id in params else None
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and _callee(n.func) == fn.name:
            passed = [n.args[index]] if index is not None and 0 <= index < len(n.args) else []
            passed += [k.value for k in n.keywords if k.arg == first.id]
            if any(isinstance(a, ast.Constant) and isinstance(a.value, str) and is_sensitive(a.value) for a in passed):
                return True
    return False


def violations(rel: str, source: str) -> list[tuple[str, int, str]]:
    """(function, line, what) for every query on a sensitive table, or call of a sensitive function, whose client is not
    privileged. A module in WHOLLY_PRIVILEGED is judged on its shape instead (`shape_problems`)."""
    return [(fn, line, what) for fn, line, what, _recv in violating_receivers(rel, source)]


def violating_receivers(rel: str, source: str) -> list[tuple[str, int, str, ast.AST]]:
    """`violations`, with the receiver expression itself (its position is what a rewrite needs)."""
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    names = privileged_names(tree)
    scope = _Scope(tree, parents)

    def fn_of(node):
        fn = _enclosing_function(node, parents)
        return fn.name if fn else "<module>"

    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args):
            continue
        attr, first = node.func.attr, node.args[0]
        literal = first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None
        if attr == "from_" and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "storage":
            continue        # `client.storage.from_(BUCKET)` names a bucket, not a table
        if attr in {"table", "from_"}:
            sensitive = is_sensitive(literal) if literal is not None else _a_sensitive_name_can_reach(first, node, tree, parents)
        elif attr == "rpc":
            sensitive = literal in SENSITIVE_RPCS
        else:
            continue
        if not sensitive:
            continue
        if rel in WHOLLY_PRIVILEGED:
            continue
        recv = _chain_receiver(node)
        if not is_privileged(recv, names, scope, node):
            out.append((fn_of(node), node.lineno, f"{attr}({literal or ast.unparse(first)}) on {ast.unparse(recv)[:50]}", recv))
    return out


def shape_problems(rel: str, source: str) -> list[str]:
    """The three facts that stand in for a per-query check in a wholly privileged module."""
    tree = ast.parse(source)
    names = privileged_names(tree)
    problems = []
    if "_db" not in names:
        problems.append("`_db` is not bound to a privileged provider function")
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id in REQUEST_GETTERS and isinstance(n.ctx, ast.Load):
            problems.append(f"line {n.lineno}: names the request-scoped getter {n.id}")
        elif isinstance(n, ast.Attribute) and n.attr in REQUEST_GETTERS:
            problems.append(f"line {n.lineno}: names the request-scoped getter {n.attr}")
        elif isinstance(n, ast.ImportFrom) and any(a.name in REQUEST_GETTERS for a in n.names):
            problems.append(f"line {n.lineno}: imports a request-scoped getter")
        elif isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "db" for t in n.targets):
            if not (isinstance(n.value, ast.Call) and _callee(n.value.func) == "_db"):
                problems.append(f"line {n.lineno}: `db` is assigned from {ast.unparse(n.value)[:60]}, not `_db()`")
    return problems


# ── the rule over the source ─────────────────────────────────────────────────

def _runtime_sources():
    for rel, text in tu.sources():
        if not rel.startswith("scripts/"):
            yield rel, text


def test_every_query_on_a_payroll_bank_or_document_table_starts_at_the_privileged_client():
    bad, seen = {}, 0
    for rel, text in _runtime_sources():
        if "bank_" not in text and "payroll_" not in text and "document" not in text and "attendance" not in text \
                and "leave_balances" not in text and "salary_" not in text and "entity_documents" not in text:
            continue
        found = violations(rel, text)
        seen += 1
        if found:
            bad[rel] = found
    assert seen > 40, "the scan looked at almost nothing: the collector is broken"
    assert not bad, (
        "A query on a payroll, bank or document table, or a call of a function that reads one as its caller, is made with a client "
        "that is not visibly the privileged one (POST-A-339). Write `privileged_for(db).table(...)` at the query (and assert the "
        "caller's firm and client before it: the privileged client carries no row security). module: (function, line, what):\n  "
        + "\n  ".join(f"{rel}: {v}" for rel, v in sorted(bad.items())))


def test_the_wholly_privileged_modules_keep_their_shape():
    for rel, why in WHOLLY_PRIVILEGED.items():
        problems = shape_problems(rel, (API / rel).read_text(encoding="utf-8"))
        assert not problems, f"{rel} is exempt because of {why}, and: {problems}"


def test_the_exemption_list_names_a_module_that_still_queries_a_sensitive_table():
    """An exemption nothing needs is a hole nobody is looking at."""
    for rel in WHOLLY_PRIVILEGED:
        text = (API / rel).read_text(encoding="utf-8")
        assert any(f'"{t}"' in text for t in ("payroll_runs", "payroll_slips", "payroll_employees")), rel


# ── the analyser itself, on synthetic sources (the negative controls) ────────

def _flagged(src: str, rel: str = "services/x.py") -> list[str]:
    return [w for _fn, _ln, w in violations(rel, src)]


_HEAD = "from core import db_provider\nfrom core.db_provider import privileged_for\n"


def test_a_parameter_is_not_privileged_whatever_the_name():
    assert _flagged('def f(db):\n    return db.table("bank_accounts").select("*")\n')
    assert _flagged('def f(service_db):\n    return service_db.table("payroll_runs").select("*")\n')


def test_the_door_the_alias_and_the_local_bound_to_one_are_privileged():
    assert not _flagged(_HEAD + 'def f(db):\n    return privileged_for(db).table("bank_accounts").select("*")\n')
    assert not _flagged(_HEAD + '_db = db_provider.service_db_or_none\ndef f():\n    return _db().table("documents").select("*")\n')
    assert not _flagged(_HEAD + 'def f(db):\n    reader = db_provider.service_db_or_none() or db\n    return reader.table("bank_transactions").select("*")\n')
    assert not _flagged(_HEAD + 'def _svc():\n    return db_provider.service_db()\ndef f():\n    return _svc().table("client_documents").select("*")\n')
    assert not _flagged(_HEAD + 'def _db():\n    return None if MOCK else db_provider.service_db()\ndef f():\n    return _db().table("document_requests").select("*")\n')


def test_a_helper_that_answers_the_privileged_client_or_the_callers_is_privileged_and_one_that_answers_the_callers_alone_is_not():
    assert not _flagged(_HEAD + '_service_db = db_provider.service_db_or_none\ndef _bank_db(db):\n    return _service_db() or db\n'
                        'def f(db):\n    return _bank_db(db).table("bank_transactions").select("*")\n')
    assert _flagged(_HEAD + 'def _bank_db(db):\n    return db\ndef f(db):\n    return _bank_db(db).table("bank_transactions").select("*")\n')
    assert _flagged(_HEAD + 'def _bank_db(db):\n    return db or db_provider.service_db()\n'
                    'def f(db):\n    return _bank_db(db).table("bank_transactions").select("*")\n')


def test_a_local_bound_to_the_request_client_or_to_two_things_is_not_privileged():
    assert _flagged(_HEAD + 'def f():\n    db = db_provider.request_db()\n    return db.table("payroll_slips").select("*")\n')
    assert _flagged(_HEAD + 'def f(db, wide):\n    c = privileged_for(db)\n    c = db\n    return c.table("bank_statements").select("*")\n')
    assert _flagged(_HEAD + 'def f(db):\n    return (db or privileged_for(db)).table("documents").select("*")\n')


def test_a_table_chosen_at_run_time_is_judged_when_a_sensitive_one_can_reach_it():
    # the function spells one
    assert _flagged('def f(db):\n    for t in ("journal_lines", "bank_transactions"):\n        db.table(t).select("id")\n')
    # a caller in the same module hands it one, by position, by keyword and through a method
    assert _flagged('def f(db, table):\n    return db.table(table).select("id")\ndef g(db):\n    return f(db, "bank_transactions")\n')
    assert _flagged('def f(db, table):\n    return db.table(table).select("id")\ndef g(db):\n    return f(db, table="payroll_runs")\n')
    assert _flagged('class C:\n    def f(self, db, table):\n        return db.table(table).select("id")\n    def g(self, db):\n        return self.f(db, "documents")\n')
    # nothing sensitive can reach it: a party lookup, a module that merely names a sensitive table elsewhere
    assert not _flagged('def f(db, table):\n    return db.table(table).select("id")\ndef g(db):\n    return f(db, "customers")\n')
    assert not _flagged('X = "bank_transactions"\ndef f(db, table):\n    return db.table(table).select("id")\n')
    assert not _flagged(_HEAD + 'def f(db, table):\n    return privileged_for(db).table(table).select("id")\ndef g(db):\n    return f(db, "bank_accounts")\n')


def test_a_storage_bucket_is_not_a_table():
    assert not _flagged('def f(client):\n    x = "documents"\n    return client.storage.from_(BUCKET)\n')


def test_the_two_bank_report_functions_are_called_with_the_privileged_client():
    assert _flagged('def f(db):\n    return db.rpc("bank_register", {}).execute()\n')
    assert _flagged('def f(db):\n    return db.rpc("bank_reconciling_items", {}).execute()\n')
    assert not _flagged(_HEAD + 'def f(db):\n    return privileged_for(db).rpc("bank_register", {}).execute()\n')
    assert not _flagged('def f(db):\n    return db.rpc("some_definer_function", {}).execute()\n')


def test_a_table_that_is_not_sensitive_is_left_alone():
    assert not _flagged('def f(db):\n    return db.table("journal_entries").select("*")\n')
    assert not _flagged('def f(db):\n    return db.table("bonus_disqualifications").select("*")\n')


def test_the_shape_check_names_each_way_a_wholly_privileged_module_could_stop_being_one():
    ok = _HEAD + '_db = db_provider.service_db_or_none\ndef h():\n    db = _db()\n    return db.table("payroll_runs")\n'
    assert shape_problems("routers/payroll.py", ok) == []
    assert shape_problems("routers/payroll.py", ok.replace("service_db_or_none", "request_db_or_none"))
    assert shape_problems("routers/payroll.py", ok + 'def k():\n    from core.supabase_client import get_supabase\n    return get_supabase()\n')
    assert shape_problems("routers/payroll.py", ok + 'def k(x):\n    db = x\n    return db\n')


@pytest.mark.parametrize("rel", sorted(WHOLLY_PRIVILEGED))
def test_the_exempt_module_is_read_by_the_shape_check_and_not_by_the_per_query_one(rel):
    text = (API / rel).read_text(encoding="utf-8")
    assert violations(rel, text) == []
    assert violations("services/not_exempt.py", text), "the same source in a module that is not exempt must be flagged"
