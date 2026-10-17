"""`.single()` is allowed only where its failure is caught; a lookup that may find nothing is `.maybe_single()` (POST-A-198).

THE RULE, NOT A LIST OF FILES
    PostgREST's `.single()` raises (406, PGRST116) when no row matches, and the call sites were written as
    `... .single().execute().data` followed by `if not row: raise 404`: a line that can never run. A wrong or foreign id
    was a 500. `.maybe_single()` answers an absent row with `data=None` (core/supabase_client.py restores that contract).
    So a `.single()` call anywhere in the backend must sit inside a `try` that has an `except` clause, where the raise
    is the thing being handled; anywhere else it is a defect.

    This reads the AST, so a `.single()` named in a comment or a docstring (several explain this very bug) is not a
    call, and it follows the call rather than a spelling: a chain split over lines, a `.single()` on a variable.

    The tests in `tests/` are not scanned (a double that defines `single` is not a lookup). `scripts/` is not scanned
    either: they are one-off tools, not the request path.
"""
from __future__ import annotations

import ast
from pathlib import Path

API = Path(__file__).resolve().parents[1]
SKIP_TOP = {"tests", "scripts", "venv", ".venv", "node_modules", "migrations"}


def _single_calls(tree: ast.AST):
    """Every `<x>.single()` call (no arguments) with whether a `try` that has an except clause encloses it."""
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "single"
                and not node.args and not node.keywords):
            cur, caught = node, False
            while cur in parents:
                parent = parents[cur]
                if isinstance(parent, ast.Try) and parent.handlers and cur in parent.body:
                    caught = True
                    break
                cur = parent
            yield node, caught


def _scan() -> tuple[list[str], int]:
    loose: list[str] = []
    total = 0
    for path in sorted(API.rglob("*.py")):
        rel = path.relative_to(API)
        if rel.parts[0] in SKIP_TOP:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node, caught in _single_calls(tree):
            total += 1
            if not caught:
                loose.append(f"{rel}:{node.lineno}")
    return loose, total


def test_no_single_lookup_is_left_where_a_missing_row_would_be_a_server_error():
    loose, _ = _scan()
    assert not loose, (
        "`.single()` raises when no row matches, so a wrong id becomes a 500. Use `.maybe_single()` (it answers an "
        "absent row with data=None) and check the result, or wrap the call in a try that handles the failure:\n  "
        + "\n  ".join(loose))


def test_the_scan_sees_the_calls_it_is_meant_to_police():
    # A scan that finds nothing passes on any tree. The remaining calls are the ones inside a try (engagement letters,
    # the year-end screens, the posting account lookups); fewer than this means the walk stopped seeing them.
    _, total = _scan()
    assert total >= 20, total


def test_negative_control_the_scan_flags_a_bare_single_and_not_a_guarded_one():
    bare = ast.parse("def f(db):\n    return db.table('t').select('*').eq('id', 1).single().execute().data\n")
    guarded = ast.parse(
        "def f(db):\n    try:\n        return db.table('t').select('*').single().execute().data\n"
        "    except Exception:\n        return None\n")
    in_handler = ast.parse(
        "def f(db):\n    try:\n        pass\n    except Exception:\n        return db.table('t').single().execute()\n")
    spoken = ast.parse('def f():\n    """uses .single() in prose"""\n    # and .single() here\n')
    assert [caught for _, caught in _single_calls(bare)] == [False]
    assert [caught for _, caught in _single_calls(guarded)] == [True]
    assert [caught for _, caught in _single_calls(in_handler)] == [False]    # a call in the handler is not protected
    assert list(_single_calls(spoken)) == []
