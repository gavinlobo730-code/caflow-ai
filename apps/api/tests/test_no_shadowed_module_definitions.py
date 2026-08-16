"""
No module-level name is defined twice in the same file.

WHY THIS EXISTS
    Python binds a module-level name to whichever definition executes LAST.
    Two functions with the same name in one file is therefore not a warning,
    a lint error, or a crash — it is a silent rebinding, and every call site
    written against the earlier one now calls the later one.

    routers/accounting.py had exactly this. It guards journal entries against
    two different engines: the production Supabase ledger and a legacy
    in-memory service. Both guards were called _assert_journal_scope, and they
    take different arguments. GET and PATCH /journal/{entry_id} called the
    three-argument one; Python handed them the two-argument one; every request
    to either route raised TypeError.

    The suite stayed entirely green — 6982 passing — because the tests
    exercised the service those routes delegate to, and nothing walked the
    routes themselves. The failure was found by hand, wiring the editor UI.

    A test that only pinned that one file would not have helped, because the
    problem is not that name: it is that nothing in the build says anything at
    all when a definition is shadowed. This walks every module instead, so the
    next one fails here rather than in production.

SCOPE
    Module level only. A name rebound inside a function or an `if`/`try` branch
    is ordinary control flow (fallback imports, conditional stubs) and is left
    alone. Classes and functions both count — two `class Foo` in a file is the
    same silent rebinding.
"""
from __future__ import annotations

import ast
import collections
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"venv", ".venv", "node_modules", "__pycache__", ".git", "migrations"}


def _python_files() -> list[Path]:
    return [p for p in sorted(API_ROOT.rglob("*.py"))
            if not any(part in SKIP_DIRS for part in p.relative_to(API_ROOT).parts)]


def _shadowed(path: Path) -> list[tuple[str, list[int]]]:
    """Names defined more than once at module level, with their line numbers."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    seen: dict[str, list[int]] = collections.defaultdict(list)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            seen[node.name].append(node.lineno)
    return [(name, lines) for name, lines in seen.items() if len(lines) > 1]


def test_no_module_level_definition_is_shadowed_by_a_later_one():
    offenders = []
    for path in _python_files():
        for name, lines in _shadowed(path):
            offenders.append(f"{path.relative_to(API_ROOT)}: {name} defined at lines {lines}")

    assert not offenders, (
        "A module-level definition is shadowed by a later one with the same "
        "name. Python keeps only the last, so every call site written against "
        "the earlier definition now silently calls the later one:\n  "
        + "\n  ".join(sorted(offenders))
    )


def test_the_check_actually_detects_a_shadowed_definition(tmp_path):
    """Guards the guard. A walker that silently matched nothing — wrong parse,
    wrong node types, an over-broad skip list — would pass the test above
    forever and prove only that it ran."""
    sample = tmp_path / "shadowed_sample.py"
    sample.write_text(
        "def f(a):\n    return a\n\n\ndef f(a, b):\n    return a + b\n",
        encoding="utf-8",
    )

    assert _shadowed(sample) == [("f", [1, 5])]


def test_the_check_does_not_flag_rebinding_inside_a_function(tmp_path):
    """Nested and conditional definitions are ordinary control flow — fallback
    imports and conditional stubs legitimately define the same name twice."""
    sample = tmp_path / "nested_sample.py"
    sample.write_text(
        "def outer():\n"
        "    def inner():\n"
        "        return 1\n"
        "    def inner():\n"
        "        return 2\n"
        "    return inner\n",
        encoding="utf-8",
    )

    assert _shadowed(sample) == []
