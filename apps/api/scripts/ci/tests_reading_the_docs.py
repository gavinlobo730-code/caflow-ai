"""Print the test modules that read `docs/` or `CLAUDE.md`, for CI to run on a docs-only pull request.

WHY THIS EXISTS. `.github/workflows/backend-ci.yml` runs the whole backend suite for every change that is not confined to the two
frontends, because the suite reads the whole repository: `CLAUDE.md` (its size limit and the design-record index), `docs/` (the open-items
ledger, the design records, the compliance notes). That rule was written after three merges each took CLAUDE.md over its limit before a
change that happened to touch the backend ran the test. It is right, and it costs a full run, about 45 minutes, for a change that
cannot break anything but the tests that read the documents it changed.

So a pull request whose every changed file is under `docs/` or is `CLAUDE.md` runs only the modules that can SEE those files (the "docs
lane"). This script names them, and it derives the list rather than holding one: a test added later that reads the documents is picked up
with no edit here, which is the property a hand-kept list loses the first time somebody forgets. It is the same shape as
`tests_reading_the_browser.py`, which does it for the frontends.

WHAT COUNTS AS A READ, written as the rule and not as one spelling of it:

  1. A string CONSTANT, outside a docstring, that names the documents: `"docs"`, `"docs/open-items/README.md"`, `"../docs/x.md"`,
     `"CLAUDE.md"`, or a piece of an f-string that does. A path in a docstring or a comment is prose, not a read.
  2. A path built one segment at a time (`ROOT / "docs" / "open-items"`): the constant on the right of the `/` is rule 1's.
  3. A walk of the tree from the repository root (`rglob`, `os.walk`, `glob`, `listdir`, `iterdir` in a module that builds its root with
     `parents[3]`, `parents[4]` or `REPO`): it reaches `docs/` and `CLAUDE.md` without naming either, so it counts.
  4. IMPORTING a module that does, transitively. A guard with no path of its own that imports a helper reading the documents reads them
     through it. The walk goes through the test modules and through the helpers in `tests/` that read the documents themselves; it does
     NOT go through every helper, because `e2e_harness` is imported by hundreds of modules and a closure through it selects the suite.

IT ERRS TOWARD RUNNING MORE. A constant that merely MENTIONS a path in an assertion message selects its module, which costs seconds. What
it cannot do is select a module that reads the documents by a spelling none of the four rules sees, so the docs lane is only the
fast path: a push to `main` always runs the whole suite (the `scope` job never marks a push as docs-only), so a read this script
missed is found within one run after the merge, which is the same lag the rule had before the lane existed, and not before it.

`--mock` prints the modules that are not real-Postgres ones, `--pg` the `*_pg.py` ones (they run in the migration job, where the
database is), and neither prints both. It never prints nothing for the mock or the whole set: an empty argument list makes pytest
collect the WHOLE suite, which is the opposite of this script's purpose and would look like a pass while costing the full budget. Only
`--pg` may print nothing (and then exits 0), because the migration step skips an empty list instead of handing it to pytest.
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import re
import sys

TESTS = pathlib.Path(__file__).resolve().parents[2] / "tests"

# `docs`, `docs/...`, `.../docs/...`, `CLAUDE.md`. Anchored on a path separator so `mydocs` and `docstring` are not documents.
_NAMES_THE_DOCUMENTS = re.compile(r"(^|/)docs(/|$)|CLAUDE\.md")

# A walk of a tree...
_WALKS = re.compile(r"rglob|os\.walk|\.glob\(|listdir|iterdir")
# ...rooted at the repository, not at some subdirectory: the repository root is `parents[3]` from apps/api/tests (or `parents[4]` from
# a nested helper), or a module-level name for it.
_FROM_THE_REPOSITORY_ROOT = re.compile(r"parents\[(3|4)\]|\bREPO(_ROOT)?\b")


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def reads_the_documents(path: pathlib.Path) -> bool:
    """Whether this one file opens `docs/` or `CLAUDE.md` itself (rules 1 to 3), without following an import."""
    try:
        text = path.read_text(errors="ignore")
        tree = ast.parse(text)
    except (SyntaxError, OSError):
        # A file that cannot be read is not known NOT to read them: run it.
        return True
    skip = _docstring_ids(tree)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip
                and _NAMES_THE_DOCUMENTS.search(node.value)):
            return True
    return bool(_WALKS.search(text) and _FROM_THE_REPOSITORY_ROOT.search(text))


def _imports(path: pathlib.Path, known: set[str]) -> set[str]:
    """Modules of `tests/` this file imports, by module name."""
    try:
        tree = ast.parse(path.read_text(errors="ignore"))
    except (SyntaxError, OSError):
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.rsplit(".", 1)[-1])
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            out.update(alias.name.rsplit(".", 1)[-1] for alias in node.names)
    return out & known


def modules_reading_the_docs(tests: pathlib.Path = TESTS) -> list[pathlib.Path]:
    """Every `test_*.py` under `tests` that reads the documents, itself or through a module it imports (rule 4)."""
    everything = sorted(tests.glob("*.py"))
    by_name = {p.stem: p for p in everything}
    reading: set[str] = {p.stem for p in everything if reads_the_documents(p)}
    edges = {p.stem: _imports(p, set(by_name)) for p in everything}
    changed = True
    while changed:
        changed = False
        for name, imported in edges.items():
            # Only a test module is selected through an import; a helper joins the set only by reading the documents itself.
            if name.startswith("test_") and name not in reading and imported & reading:
                reading.add(name)
                changed = True
    return [by_name[n] for n in sorted(reading) if n.startswith("test_")]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--mock", action="store_true", help="only the modules that are not real-Postgres ones")
    group.add_argument("--pg", action="store_true", help="only the real-Postgres (*_pg.py) modules")
    args = ap.parse_args(argv)
    found = modules_reading_the_docs()
    if args.mock:
        found = [p for p in found if not p.stem.endswith("_pg")]
    elif args.pg:
        found = [p for p in found if p.stem.endswith("_pg")]
    if not found:
        if args.pg:
            # No real-Postgres module reads the documents: the migration job has nothing to run in the docs lane. That is an answer, not
            # an error, and the workflow step says so; it is the only set allowed to be empty (see the module docstring).
            print("No real-Postgres test module reads docs/ or CLAUDE.md.", file=sys.stderr)
            return 0
        print("No test module reads docs/ or CLAUDE.md in the requested set — that cannot be right, so this is a bug in "
              "tests_reading_the_docs.py rather than a clean result.", file=sys.stderr)
        return 1
    for path in found:
        print(f"tests/{path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
