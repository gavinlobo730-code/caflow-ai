"""The user a model call is attributed to is the INTERNAL id, never the sign-in id (POST-A-361).

WHAT WAS WRONG
    `ai_usage_events.user_id` is a key to `users(id)` (migration 465). The copilot chat (`POST /api/copilot/chat` and
    `POST /api/copilot/conversations/{id}/messages`) passed the caller's SIGN-IN id (`current_user["auth_user_id"]`, the id its
    conversation is stored under) as the `user_id` of `chat()`, whose only use is to attribute the model call. Every other model caller
    passes `current_user["id"]`. In production no user's two ids are equal (2 of 2 differ), so the key refuses the row, and the gateway's
    writer swallows a failed usage insert by design (a usage row must never cost anybody an answer). The result is a copilot answer
    that is paid for and never counted: a firm's monthly AI cap, which counts the rows of this table, would not see the chat. The table
    is empty in production today only because the chat has not been used since it was created (the last message is from 27-09-2026).

    The keyed-column rule (`test_users_fk_columns_take_the_internal_id.py`) did not see it, because the id reaches the insert through a
    context variable (`gateway.attributed` reads the `user_id` argument) and not through a dict literal at the insert.

WHAT THIS HOLDS
    Every call that attributes a model call to a user is read for the id it passes, and a value that is, or is a name assigned from, the
    sign-in id FAILS. The calls are: a method decorated `@gateway.attributed(...)` that takes `user_id` (so a future one is found from its
    decorator), a `usage_scope(user_id=...)`, and a gateway door call that names both `feature=` and `user_id=`. A name is followed
    through its assignments in the same function (the chat routes held the sign-in id in a local name). The scan is not blind: a
    synthetic wrong call of each shape is flagged, the right one is passed, and the scan finds the call sites it was written for.
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests.test_a_bare_person_column_takes_the_id_it_holds import kind_of

API = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("routers", "services", "domain", "jobs", "repositories")


def _attributed_methods_with_user_id(trees: dict[str, ast.Module]) -> set[str]:
    out = set()
    for tree in trees.values():
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            decorated = any(isinstance(d, ast.Call) and getattr(d.func, "attr", getattr(d.func, "id", None)) == "attributed" for d in fn.decorator_list)
            takes_user = "user_id" in [a.arg for a in (*fn.args.args, *fn.args.kwonlyargs)]
            if decorated and takes_user:
                out.add(fn.name)
    return out


def _enclosing_function(node, parents):
    while node is not None and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        node = parents.get(node)
    return node


def _kinds_of(value: ast.expr, fn: ast.AST | None) -> set[str]:
    """The kinds a value can be: its own, and for a bare name every kind it is assigned in the same function."""
    kinds = {kind_of(value)}
    if isinstance(value, ast.Name) and fn is not None:
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == value.id for t in n.targets):
                kinds.add(kind_of(n.value))
    return kinds


def attributions_in(source: str, relpath: str, attributed: set[str]) -> list[tuple[str, int, str, set[str]]]:
    """(file, line, what it is, kinds the user id can be) for every call that attributes a model call to a user."""
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    out = []
    for call in [n for n in ast.walk(tree) if isinstance(n, ast.Call)]:
        name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", None)
        keywords = {k.arg: k.value for k in call.keywords if k.arg}
        if "user_id" not in keywords:
            continue
        if name in attributed:
            what = f"{name}() (attributed)"
        elif name == "usage_scope":
            what = "usage_scope()"
        elif "feature" in keywords:
            what = f"{name}(feature=..., user_id=...) (a gateway door)"
        else:
            continue
        out.append((relpath, call.lineno, what, _kinds_of(keywords["user_id"], _enclosing_function(call, parents))))
    return out


def _all_trees() -> dict[str, ast.Module]:
    trees = {}
    for d in SCAN_DIRS:
        for path in sorted((API / d).rglob("*.py")):
            try:
                trees[path.relative_to(API).as_posix()] = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
    return trees


TREES = _all_trees()
ATTRIBUTED = _attributed_methods_with_user_id(TREES)
FOUND = [a for rel, tree in TREES.items() for a in attributions_in(ast.unparse(tree), rel, ATTRIBUTED)]


def test_the_scan_finds_the_attributions_it_was_written_for():
    assert "chat" in ATTRIBUTED, ATTRIBUTED
    assert len(FOUND) >= 5, FOUND
    assert any("usage_scope" in what for _f, _l, what, _k in FOUND)
    assert any("(attributed)" in what for _f, _l, what, _k in FOUND)
    assert any("gateway door" in what for _f, _l, what, _k in FOUND)


def test_no_model_call_is_attributed_to_the_sign_in_id():
    wrong = [(f, line, what) for f, line, what, kinds in FOUND if "auth" in kinds]
    assert not wrong, ("a model call is attributed to the sign-in id; ai_usage_events.user_id keys users.id, so the row is refused and lost "
                       f"(file, line, call): {wrong}")


# ── the scan is not blind ─────────────────────────────────────────────────────────────────────────

def _scan(body: str, attributed=frozenset({"chat"})):
    return attributions_in(body, "synthetic.py", set(attributed))


def test_a_wrong_id_is_flagged_in_each_shape_and_the_right_one_passed():
    bad = {
        "an attributed method, direct": "async def r(current_user):\n    await svc.chat(firm_id='f', user_id=current_user.get('auth_user_id'))\n",
        "an attributed method, through a name": "async def r(current_user):\n    user_id = current_user.get('auth_user_id', 'dev')\n    await svc.chat(firm_id='f', user_id=user_id)\n",
        "a usage scope": "def r(current_user):\n    with gateway.usage_scope(firm_id='f', user_id=current_user['auth_user_id'], feature='x'):\n        pass\n",
        "a gateway door": "def r(current_user):\n    groq_text.chat(messages=[], feature='x', firm_id='f', user_id=current_user.get('auth_user_id'))\n",
    }
    for why, src in bad.items():
        found = _scan(src)
        assert found and any("auth" in k for *_x, k in found), why
    good = {
        "internal id direct": "async def r(current_user):\n    await svc.chat(firm_id='f', user_id=current_user.get('id'))\n",
        "internal id through a name": "async def r(current_user):\n    uid = current_user.get('id')\n    await svc.chat(firm_id='f', user_id=uid)\n",
        "a parameter passed on": "def r(user_id):\n    with gateway.usage_scope(firm_id='f', user_id=user_id, feature='x'):\n        pass\n",
        "a call that is not a model call": "def r(current_user):\n    repo.create_conversation(firm_id='f', user_id=current_user.get('auth_user_id'))\n",
    }
    for why, src in good.items():
        found = _scan(src)
        assert not any("auth" in k for *_x, k in found), why


def test_a_new_attributed_method_that_takes_a_user_is_found_from_its_decorator():
    src = "class S:\n    @gateway.attributed('f')\n    async def brand_new(self, firm_id, user_id):\n        pass\n"
    assert _attributed_methods_with_user_id({"s.py": ast.parse(src)}) == {"brand_new"}
