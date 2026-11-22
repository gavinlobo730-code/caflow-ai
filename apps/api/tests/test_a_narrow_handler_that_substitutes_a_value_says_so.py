"""POST-A-505: a handler that swaps a value in for a failed read says so, across the tree, with a baseline that only shrinks.

WHAT WAS WRONG
    The sweep that made a swallowed fallback say so (POST-A-021 and the slices after it) reached eleven named files, and its guard
    (`test_a_narrow_swallow_is_triaged.py`) reads `pass` and `continue` bodies in those files only; the tree-wide ratchet in
    `test_soft_failure_visibility.py` counts only a single-`pass` handler. A narrow handler whose whole body is a constant
    (`except ValueError: return None`, `except (TypeError, KeyError): x = 0`) sat outside both: when it guards a stored date or figure
    it moves the answer onto the fallback and nothing, not a log line and not Sentry, says that it did. A new one went unseen, and
    the sweep read as complete when it was one file list wide.

THE RULE (stated, not spelled)
    In `core`, `domain`, `jobs`, `repositories`, `routers` and `services`, a handler that names only built-in narrow errors
    (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError, ZeroDivisionError and the decimal ones) and whose
    WHOLE body is a constant substitution (`pass`, `continue`, `return <constant>`, `name = <constant>`) must carry a comment inside it
    of ten characters or more saying why that is right (a value that is optional by design, not read from a stored record), or
    report through `core.observability.capture_soft_failure`, which makes it no longer a constant substitution. One that does neither
    is a finding. On 20-11-2026 the tree held 146 of them, frozen BY FILE AND FUNCTION in a baseline that could only shrink. On
    22-11-2026 each was read: 142 carry their reason inside the handler, and four that guarded a stored record report now (an
    invoice's date in two places, a member of a recorded ECR, and the answer of the unrecorded-stock function). THE BASELINE IS
    EMPTY, so a new one is refused outright.

WHAT IT DOES NOT CLAIM
    A reason written inside a handler is a person's reading, and the scan checks that one is there (ten characters), not that it is
    true. One reading found a real defect that a comment could only name: a bank statement's amount cell that is not a number is
    read as nil and the row is not named (POST-A-551). A handler that returns a computed value, or calls anything, is not this shape
    and is not judged here.
"""
from __future__ import annotations

import ast
import collections
import json
import re
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
BASELINE_FILE = Path(__file__).resolve().parent / "fixtures" / "narrow_handler_baseline.json"
TREE = ("core", "domain", "jobs", "middleware", "models", "repositories", "routers", "services")

NARROW = {"ValueError", "TypeError", "KeyError", "IndexError", "AttributeError", "OverflowError", "ZeroDivisionError",
          "InvalidOperation", "DecimalException", "UnicodeDecodeError", "JSONDecodeError"}


def _names(t: ast.expr | None) -> set[str]:
    if t is None:
        return {"<bare>"}
    if isinstance(t, ast.Tuple):
        return {n for e in t.elts for n in _names(e)}
    if isinstance(t, ast.Name):
        return {t.id}
    if isinstance(t, ast.Attribute):
        return {t.attr}
    return {"?"}


def _constant_value(v: ast.expr | None) -> bool:
    """A value that is written out, not computed: a literal, a negative number, or an empty list, dict or tuple (or a tuple of such)."""
    if v is None or isinstance(v, ast.Constant):
        return True
    if isinstance(v, ast.UnaryOp) and isinstance(v.op, (ast.USub, ast.UAdd)):
        return isinstance(v.operand, ast.Constant)
    if isinstance(v, (ast.List, ast.Tuple, ast.Set)):
        return all(_constant_value(e) for e in v.elts)
    if isinstance(v, ast.Dict):
        return not v.keys
    return False


def _constant_statement(b: ast.stmt) -> bool:
    if isinstance(b, (ast.Pass, ast.Continue)):
        return True
    if isinstance(b, ast.Return):
        return _constant_value(b.value)
    if isinstance(b, ast.Assign):
        return _constant_value(b.value)
    return False


def _function_name(tree: ast.AST, target: ast.ExceptHandler) -> str:
    best = "<module>"
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.lineno <= target.lineno <= (fn.end_lineno or fn.lineno):
            best = fn.name
    return best


def silent_substitutions(relative: str, source: str, *, include_explained: bool = False) -> list[tuple[str, str, int]]:
    """(file, function, line) of each narrow handler that is only a constant substitution and says nothing why.

    With `include_explained`, the ones that DO carry their reason are returned too: the shape itself, which is what the check that
    the scan still sees the tree counts now that the unexplained ones are none."""
    tree = ast.parse(source)
    lines = source.splitlines()
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.ExceptHandler) or not n.body or not _names(n.type) <= NARROW:
            continue
        if not all(_constant_statement(b) for b in n.body):
            continue
        end = n.end_lineno or n.lineno
        inside = "\n".join(lines[n.lineno - 1:end])
        if re.search(r"#[^\n]{10,}", inside) and not include_explained:
            continue
        out.append((relative, _function_name(tree, n), n.lineno))
    return out


def _tree_findings(*, include_explained: bool = False) -> list[tuple[str, str, int]]:
    found: list[tuple[str, str, int]] = []
    for top in TREE:
        for path in sorted((API_ROOT / top).rglob("*.py")):
            relative = path.relative_to(API_ROOT).as_posix()
            found.extend(silent_substitutions(relative, path.read_text(encoding="utf-8"), include_explained=include_explained))
    return found


def _counts(found) -> dict[str, int]:
    c = collections.Counter(f"{f}::{fn}" for f, fn, _ in found)
    return dict(sorted(c.items()))


# ── the rule over the tree ────────────────────────────────────────────────────────────────────────────────────

def test_no_new_handler_substitutes_a_constant_without_saying_why():
    baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))["frozen"]
    now = _counts(_tree_findings())
    added = {k: n for k, n in now.items() if n > baseline.get(k, 0)}
    assert not added, (
        f"A narrow handler swaps a constant in for a failed read and says nothing: {added}. Report it with "
        "core.observability.capture_soft_failure, ask the question instead of catching it, or write in a comment inside it why "
        "that is right (ten characters or more).")


def test_the_baseline_only_shrinks():
    baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))["frozen"]
    now = _counts(_tree_findings())
    stale = {k: n for k, n in baseline.items() if now.get(k, 0) < n}
    assert not stale, (
        f"tests/fixtures/narrow_handler_baseline.json lists handlers that are fixed or commented now: {stale}. Lower or delete them.")


def test_the_tree_the_scan_reads_includes_the_middleware_and_the_models():
    # `middleware/body_limit.py` had the exact shape and was unscanned; an independent read found it, and the folders are named so a
    # handler there is judged like any other.
    assert {"middleware", "models"} <= set(TREE)
    assert all((API_ROOT / top).is_dir() for top in TREE)


def test_a_computed_return_is_still_not_this_shape():
    computed = "def f(x):\n    try:\n        return int(x)\n    except ValueError:\n        return [x]\n"
    assert silent_substitutions("x.py", computed) == []


def test_the_scan_sees_the_tree_it_claims_to():
    """The shape is still in the tree and still recognised: counted WITH the handlers that say why, because since 22-11-2026 the ones
    that do not are none, and a scan that found nothing because it had gone blind would look exactly like that."""
    shape = _tree_findings(include_explained=True)
    assert len(shape) >= 100, "the scan stopped recognising the shape: an empty list of findings would then mean nothing"


def test_every_handler_of_the_shape_was_read_and_none_is_frozen():
    """POST-A-505's reading is done: the baseline is empty, and nothing of the shape is left without its reason."""
    assert json.loads(BASELINE_FILE.read_text(encoding="utf-8"))["frozen"] == {}
    assert _tree_findings() == []


def test_a_handler_that_says_why_is_the_shape_and_is_not_a_finding():
    explained = ("def f(x):\n    try:\n        return int(x)\n    except ValueError:\n"
                 "        # not a number: there is no figure, which the caller says\n        return None\n")
    assert silent_substitutions("x.py", explained) == []
    assert silent_substitutions("x.py", explained, include_explained=True) == [("x.py", "f", 4)]


# ── negative controls: the rule finds the shape it was written for ─────────────────────────────────────────────────────────────

CASES = {
    "return None": "def f(x):\n    try:\n        return int(x)\n    except ValueError:\n        return None\n",
    "return 0": "def f(x):\n    try:\n        return int(x)\n    except (TypeError, ValueError):\n        return 0\n",
    "assign": "def f(x):\n    v = 1\n    try:\n        v = int(x)\n    except KeyError:\n        v = None\n    return v\n",
    "pass": "def f(x):\n    try:\n        int(x)\n    except ValueError:\n        pass\n",
    "return a negative number": "def f(x):\n    try:\n        return int(x)\n    except ValueError:\n        return -1\n",
    "return an empty list": "def f(x):\n    try:\n        return [int(x)]\n    except ValueError:\n        return []\n",
    "return an empty dict": "def f(x):\n    try:\n        return {int(x): 1}\n    except TypeError:\n        return {}\n",
    "return an empty tuple": "def f(x):\n    try:\n        return (int(x),)\n    except ValueError:\n        return ()\n",
    "assign a negative number": "def f(x):\n    v = 1\n    try:\n        v = int(x)\n    except KeyError:\n        v = -1\n    return v\n",
    "continue": "def f(xs):\n    for x in xs:\n        try:\n            int(x)\n        except ValueError:\n            continue\n",
}


@pytest.mark.parametrize("name", list(CASES))
def test_the_rule_finds_each_spelling_of_a_constant_substitution(name):
    assert len(silent_substitutions("x.py", CASES[name])) == 1


def test_a_comment_inside_the_handler_that_says_why_clears_it():
    src = "def f(x):\n    try:\n        return int(x)\n    except ValueError:\n        return None  # optional by design, nothing stored\n"
    assert silent_substitutions("x.py", src) == []


def test_a_comment_too_short_to_be_a_reason_does_not():
    src = "def f(x):\n    try:\n        return int(x)\n    except ValueError:\n        return None  # skip\n"
    assert len(silent_substitutions("x.py", src)) == 1


def test_a_handler_that_reports_or_computes_is_not_this_shape():
    reports = ("def f(x):\n    try:\n        return int(x)\n    except ValueError as exc:\n"
               "        capture_soft_failure(exc, operation='x.f')\n        return None\n")
    computes = "def f(x):\n    try:\n        return int(x)\n    except ValueError:\n        return len(str(x))\n"
    broad = "def f(x):\n    try:\n        return int(x)\n    except Exception:\n        return None\n"
    assert silent_substitutions("x.py", reports) == []
    assert silent_substitutions("x.py", computes) == []
    assert silent_substitutions("x.py", broad) == []   # a broad handler is the other rules' (test_soft_failure_visibility)
