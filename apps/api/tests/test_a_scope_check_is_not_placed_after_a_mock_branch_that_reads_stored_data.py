"""A scope check is not placed after a mock-mode early return that reads stored data, and a narrowing is used (POST-A-011).

THE CLASS
    `tests/test_guard_placement_client_scope.py` names two placements that turn a correct client-scope check into no check:
    (A) the check sits AFTER an early `return` on a mock / no-database branch, so the branch that returns data never runs it, and
    (B) the check sits inside a `try` whose handler swallows `Exception`. B has been a tree-wide scan since it was found. A was
    tested only for the timeline, receipts and purchase-payments routers, which were the three places it was found by hand. The harm
    of A is specific: `_USE_MOCK` is exactly the mode the in-memory CI job runs in, so a guard below a mock branch is precisely the
    guard no test can exercise, and a mock branch that returns STORED rows then shows another client's data to the very run that is
    supposed to prove the guard.

WHAT IS HELD (routers only)
    * Every `if` at the top level of a function whose condition names mock mode or "no database" (`_USE_MOCK`, `MOCK`, `db is None`,
      `not db`, ...) and whose body returns, and which is followed in the same function by a scope check with NO scope check before it
      or inside it, is either INERT (it calls nothing but the response wrapper and the request's own `model_dump`, and names no
      `MOCK_*` store: it echoes the request or a constant, so it exposes nothing) or it is a failure. Measured on 18-10-2026: 474 such
      branches, 80 followed by a check, none reading stored data.
    * What counts as a scope check is `assert_client_access`, `can_access_client` and `assert_partner_for_internal_id`, plus any
      function of the SAME MODULE that reaches one of them (the router's own `_assert_run_scope`, `_assert_engagement_client_mock`):
      a closure over the module's own calls, deliberately not over names across the tree, where a common name like `get` would make
      nearly every call a "check" and the rule could never fail. The cost is that a guard imported from another module under its
      own name is not seen as a check: an imported guard is called at the router by a name in the seed set, or it is not recognised
      and the branch has to be inert.
    * THE NARROWING IS USED. A name bound from `effective_client_ids(...)`, `filter_by_client(...)` or `_scoped_client_ids(...)` must be
      READ later in the function, in the routers and the services: a variable that is assigned the caller's clients and never read
      is the narrowing "stripped but still present by name", which is what a name-based scan like `test_router_client_scope.py` cannot
      see. Measured on 18-10-2026: 68 such assignments, all read.

WHAT IS NOT HELD
    That a name which is READ is read into the right place (a value passed to a call that ignores it satisfies the rule). That would
    need data flow into the callee; the runtime scope tests per router (`test_*_client_scope.py`) hold the behaviour, this holds the
    placement. `payment_service.history()`'s redundant check, named in the ledger line, is left as it is: a check twice is not a gap.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
ROUTERS = API_ROOT / "routers"
SERVICES = API_ROOT / "services"

SEED_CHECKS = frozenset({"assert_client_access", "can_access_client", "assert_partner_for_internal_id"})
NARROWERS = frozenset({"effective_client_ids", "filter_by_client", "_scoped_client_ids"})
_MOCK_WORDS = ("MOCK", "mock", "db is None", "not db", "sb is None", "client is None", "_USE_MOCK")
_INERT_CALLS = frozenset({"api_response", "model_dump", "dict", "list", "str", "int", "len"})


def _call_name(node: ast.Call):
    return getattr(node.func, "id", None) or getattr(node.func, "attr", None)


def _functions(tree: ast.AST):
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _checks_of_this_module(tree: ast.AST) -> set:
    """The seed checks plus every function of this module that, through the module's own calls, reaches one."""
    calls = {}
    for fn in _functions(tree):
        calls.setdefault(fn.name, []).append({_call_name(n) for n in ast.walk(fn) if isinstance(n, ast.Call)})
    checks = set(SEED_CHECKS)
    grew = True
    while grew:
        grew = False
        for name, bodies in calls.items():
            if name not in checks and any(b & checks for b in bodies):
                checks.add(name)
                grew = True
    return checks


def _has_check(node: ast.AST, checks: set) -> bool:
    return any(isinstance(n, ast.Call) and _call_name(n) in checks for n in ast.walk(node))


def _names_mock_mode(test: ast.AST) -> bool:
    text = ast.unparse(test)
    return any(word in text for word in _MOCK_WORDS)


def _returns(statements) -> bool:
    return any(isinstance(n, ast.Return) for s in statements for n in ast.walk(s))


def _is_inert(statements, checks: set) -> bool:
    """A branch that reads no stored data: no `MOCK_*` store and no call except the response wrapper, the request's own dump and
    a scope check."""
    for s in statements:
        for n in ast.walk(s):
            if isinstance(n, ast.Name) and re.match(r"^_?MOCK", n.id):
                return False
            if isinstance(n, ast.Call) and _call_name(n) not in _INERT_CALLS and _call_name(n) not in checks:
                return False
    return True


def mock_branches(source: str):
    """`(function, line, followed_by_a_check_with_none_before_or_inside, inert)` for every top-level early-return mock branch."""
    tree = ast.parse(source)
    checks = _checks_of_this_module(tree)
    found = []
    for fn in _functions(tree):
        for i, st in enumerate(fn.body):
            if isinstance(st, ast.If) and _names_mock_mode(st.test) and _returns(st.body):
                before = any(_has_check(s, checks) for s in fn.body[:i])
                inside = any(_has_check(s, checks) for s in st.body)
                after = any(_has_check(s, checks) for s in fn.body[i + 1:])
                found.append((fn.name, st.lineno, after and not before and not inside, _is_inert(st.body, checks)))
    return found


def unused_narrowings(source: str):
    """`(function, line, name)` for every name bound from a narrowing call that the function never reads."""
    tree = ast.parse(source)
    out = []
    for fn in _functions(tree):
        for st in ast.walk(fn):
            if isinstance(st, ast.Assign) and isinstance(st.value, ast.Call) and _call_name(st.value) in NARROWERS:
                for target in st.targets:
                    if not isinstance(target, ast.Name):
                        continue
                    read = any(isinstance(n, ast.Name) and n.id == target.id and isinstance(n.ctx, ast.Load)
                               for n in ast.walk(fn))
                    if not read:
                        out.append((fn.name, st.lineno, target.id))
    return out


def _sources(directory: Path):
    for path in sorted(directory.glob("*.py")):
        yield path.name, path.read_text(encoding="utf-8")


# ── the rule over the tree ──────────────────────────────────────────────────────────────────────────

def test_no_router_returns_stored_data_from_a_mock_branch_before_it_asks_the_scope():
    offenders, branches, followed = [], 0, 0
    for name, source in _sources(ROUTERS):
        for function, line, unguarded, inert in mock_branches(source):
            branches += 1
            if unguarded:
                followed += 1
                if not inert:
                    offenders.append(f"routers/{name}:{line} {function}")
    # The floors prove the scan is looking at something: a rule that matches nothing passes on every tree.
    assert branches >= 400, f"only {branches} mock-mode early returns found: the scan has stopped seeing them"
    assert followed >= 60, f"only {followed} of them are followed by a scope check: the scan has stopped seeing checks"
    assert not offenders, (
        "a mock / no-database branch returns before the scope check and reads stored data, so the run that exercises it "
        f"(the in-memory CI job) sees data the check would have refused: {offenders}")


def test_a_narrowing_of_the_callers_clients_is_read_after_it_is_bound():
    unused, assignments = [], 0
    for directory, label in ((ROUTERS, "routers"), (SERVICES, "services")):
        for name, source in _sources(directory):
            tree = ast.parse(source)
            for fn in _functions(tree):
                for st in ast.walk(fn):
                    if isinstance(st, ast.Assign) and isinstance(st.value, ast.Call) and _call_name(st.value) in NARROWERS:
                        assignments += sum(isinstance(t, ast.Name) for t in st.targets)
            unused += [f"{label}/{name}:{line} {function} binds {var} and never reads it"
                       for function, line, var in unused_narrowings(source)]
    assert assignments >= 50, f"only {assignments} narrowing assignments found: the scan has stopped seeing them"
    assert not unused, f"a narrowing of the caller's clients is computed and then dropped: {unused}"


# ── negative controls: the rule is shown to fail on the shape it exists for ─────────────────────────

_TIMELINE_SHAPE = '''
def list_events(client_id, current_user):
    if _USE_MOCK:
        return api_response(True, [e for e in MOCK_EVENTS if e["client_id"] == client_id])
    assert_client_access(current_user, client_id)
    return api_response(True, read(client_id))
'''


def test_the_timeline_shape_is_flagged():
    (branch,) = mock_branches(_TIMELINE_SHAPE)
    assert branch[2] and not branch[3], branch


def test_a_check_inside_the_branch_is_fine():
    source = _TIMELINE_SHAPE.replace("    if _USE_MOCK:\n", "    if _USE_MOCK:\n        assert_client_access(current_user, client_id)\n")
    (branch,) = mock_branches(source)
    assert not branch[2], branch


def test_a_check_before_the_branch_is_fine():
    source = _TIMELINE_SHAPE.replace("    if _USE_MOCK:\n", "    assert_client_access(current_user, client_id)\n    if _USE_MOCK:\n")
    (branch,) = mock_branches(source)
    assert not branch[2], branch


def test_a_branch_that_only_echoes_the_request_is_inert():
    source = '''
def update(account_id, data, current_user):
    if not db:
        return api_response(True, data.model_dump(exclude_none=True))
    assert_client_access(current_user, read(account_id).get("client_id"))
'''
    (branch,) = mock_branches(source)
    assert branch[2] and branch[3], branch


def test_the_modules_own_guard_counts_as_a_check_through_its_calls():
    source = '''
def _assert_scope(user, cid):
    can_access_client(user, cid)

def _guard(user, cid):
    _assert_scope(user, cid)

def read_all(cid, current_user):
    if _USE_MOCK:
        _guard(current_user, cid)
        return api_response(True, MOCK_ROWS)
    assert_client_access(current_user, cid)
'''
    branches = {name: rest for name, *rest in mock_branches(source)}
    assert branches["read_all"][1] is False, branches            # a check inside the branch, through two hops


def test_a_narrowing_that_is_dropped_is_flagged_and_one_that_is_read_is_not():
    dropped = "def f(u):\n    allowed = effective_client_ids(u)\n    return read()\n"
    used = "def f(u):\n    allowed = effective_client_ids(u)\n    return read(allowed)\n"
    assert unused_narrowings(dropped) == [("f", 2, "allowed")]
    assert unused_narrowings(used) == []
