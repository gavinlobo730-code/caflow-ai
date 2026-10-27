"""A test that replaces a journal method does it through `monkeypatch`, so the real method is back when the test ends.

WHAT WAS WRONG (found while building POST-A-345, 27-10-2026)
    Sixteen tests in three files wrote `fa_router._journal_svc.journal_for_depreciation = lambda ...` (or the disposal or receipt
    twin) straight onto the module-level service the routers share. Nothing put the real method back, so every later test in the
    same process that reached the real journal through that instance got the stub instead. CI runs `pytest -n auto --dist loadfile`: each
    file stays on one worker but a worker runs many files, in an order nobody chose, so a fixed-asset test that posts real depreciation
    passed or failed according to which file the worker had run before it. Run in the order (r232, then `test_an_asset_can_be_corrected`) it
    failed three tests with "No live depreciation journal found" - the stub had returned "je-1" and written nothing.

THE RULE, not a spelling of it: no test assigns to an attribute that is a method of `Phase2JournalService`. The method names are read off
the class, so a journal method added later is covered without anybody editing a list. A stub on a fresh instance the test built itself is
not shared and is also written with `monkeypatch`, which costs nothing. An assignment that the same function puts back in a `finally:` is
not a leak and is not flagged (two tests save the original and restore it). The allowlist is empty.
"""
from __future__ import annotations

import ast
import functools
import pathlib

from services.phase2_journal_service import Phase2JournalService

TESTS = pathlib.Path(__file__).resolve().parent
METHODS = {n for n, v in vars(Phase2JournalService).items() if callable(v) and not n.startswith("__")}
ALLOWED: set[str] = set()


def _method_assignments(node: ast.AST) -> list[ast.Assign]:
    return [n for n in ast.walk(node)
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr in METHODS for t in n.targets)]


def _leaves(target: ast.AST) -> list[ast.AST]:
    """`a.x, a.y = ...` assigns two attributes through one Tuple target."""
    return [leaf for t in ast.walk(target) if isinstance(t, (ast.Tuple, ast.List)) for leaf in t.elts] or [target]


def _restored_in_a_finally(function: ast.AST) -> set[str]:
    """The targets a `finally:` of this function assigns again: a stub that is put back there does not outlive the test."""
    back: set[str] = set()
    for n in ast.walk(function):
        if isinstance(n, ast.Try):
            for stmt in n.finalbody:
                for a in ast.walk(stmt):
                    if isinstance(a, ast.Assign):
                        back |= {ast.unparse(leaf) for t in a.targets for leaf in _leaves(t)}
    return back


def _unrestored(tree: ast.AST) -> list[ast.Assign]:
    """Method assignments that nothing puts back: every assignment in the module, less those whose function restores the same target."""
    bad: dict[int, ast.Assign] = {a.lineno: a for a in _method_assignments(tree)}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            back = _restored_in_a_finally(fn)
            for a in _method_assignments(fn):
                if all(ast.unparse(t) in back for t in a.targets if isinstance(t, ast.Attribute) and t.attr in METHODS):
                    bad.pop(a.lineno, None)
    return list(bad.values())


@functools.lru_cache(maxsize=1)
def _offenders() -> tuple[int, list[str]]:
    seen, found = 0, []
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name == pathlib.Path(__file__).name:
            continue
        seen += 1
        for node in _unrestored(ast.parse(path.read_text(encoding="utf-8"))):
            if f"{path.name}:{node.lineno}" not in ALLOWED:
                found.append(f"{path.name}:{node.lineno} assigns {ast.unparse(node.targets[0])}")
    return seen, found


def test_the_rule_reads_the_methods_off_the_class_and_the_tests_off_the_directory():
    seen, _ = _offenders()
    assert {"journal_for_depreciation", "journal_for_asset_disposal", "journal_for_receipt", "_create_journal"} <= METHODS
    assert seen > 500, "the scan is not reading the tests"


def test_no_test_leaves_a_stub_on_a_journal_method():
    _, found = _offenders()
    assert not found, ("a test writes a journal method straight onto an object, so the stub outlives the test and reaches whatever runs "
                       "after it on the same worker. Use monkeypatch.setattr(obj, 'name', stub): " + "; ".join(found))


def test_the_detector_sees_the_spelling_that_was_there():
    bad = ast.parse("def t(monkeypatch):\n    fa_router._journal_svc.journal_for_depreciation = lambda *a, **k: 'je-1'\n")
    good = ast.parse("def t(monkeypatch):\n    monkeypatch.setattr(fa_router._journal_svc, 'journal_for_depreciation', lambda *a, **k: 'je-1')\n")

    restored = ast.parse(
        "def t():\n    orig = svc._create_journal\n    svc._create_journal = lambda **k: 1\n    try:\n        pass\n"
        "    finally:\n        svc._create_journal = orig\n")
    assert _unrestored(bad) and not _unrestored(good) and not _unrestored(restored)
