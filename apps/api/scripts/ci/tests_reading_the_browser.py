"""Print the test modules that read a frontend, for CI to run on a frontend PR.

WHY THIS EXISTS. `.github/workflows/backend-ci.yml` skips the whole backend
suite when a diff touches no `apps/api/` file, and says so in its own output:
"the required jobs will report green without running". A redesign PR is exactly
that diff shape — `apps/web` only — so the guards written to protect the
redesign never ran on the PRs they protect. `test_the_redesign_cannot_orphan_
an_endpoint.py` is the sharpest example: it exists to catch a screen that
quietly stops calling its engine, and it was switched off by the very PR that
would do it.

Widening that scope to `apps/web/` is the obvious fix and the wrong one. The
full suite is ~7 minutes plus a ~6 minute real-Postgres job, and the account
hit 100% of its 2,000 included Actions minutes on 16 Aug 2026 — the workflow's
own concurrency comment records it. A module-by-module redesign is dozens of
PRs with several pushes each; paying full price on every one spends the budget
on tests that cannot fail, because nothing under `apps/api` changed.

So CI runs only the modules that can actually SEE the change. This script names
them, and it derives the list rather than holding one: a guard added later is
picked up with no edit here, which is the property a hardcoded list loses the
first time somebody forgets.

TWO WAYS A MODULE QUALIFIES, and the second is not optional:

  1. It builds the path itself — `parents[3] / "apps" / "web"`.
  2. It IMPORTS a module that does. `test_the_redesign_cannot_orphan_an_
     endpoint.py` has no `WEB` constant of its own; it imports `_sources`,
     `_routes` and `_pattern` from `test_every_mounted_endpoint_has_a_way_in`.
     A grep for the path construction misses it — and it is the single most
     important guard in the set.

The import walk is transitive and confined to `tests/`, so a helper chain of
any depth resolves.

A STRING IN A COMMENT IS NOT A READ. Matching the bare text `apps/web` finds 89
modules, most of which only mention it in prose. Requiring the path-building
expression finds the ones that open the tree.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

TESTS = pathlib.Path(__file__).resolve().parents[2] / "tests"

# `<something> / "apps" / "web"` (or "marketing") — the expression that opens a
# frontend tree. Deliberately not the bare string: see the docstring.
#
# BOTH FRONTENDS, because the hole is the same one directory over. apps/
# marketing is a second Next.js app on its own Cloudflare project, and on
# 16-09-2026 test_every_mounted_endpoint_has_a_way_in.py was taught to scan it
# — the demo form is the most-used public endpoint on the site and the scanner
# had been calling it unreachable. A marketing-only PR touches no apps/api
# file, so without this it would skip the whole suite exactly as an apps/web
# PR did, and test_the_marketing_site_says_what_the_product_does.py would
# never run on the diff it exists to check.
_BUILDS_WEB_PATH = re.compile(r'/\s*"apps"\s*/\s*"(web|marketing)"')

# THERE ARE TWO SPELLINGS OF THAT PATH AND THIS SCRIPT KNEW ONE (18-09-2026).
# `parents[3] / "apps" / "web" / …` is the common one. The other puts the whole
# tail in a single literal and lets `parents[2]` supply `apps/`:
#
#     _SCREEN = "web/app/income-tax/advance-tax/page.tsx"
#     pathlib.Path(__file__).resolve().parents[2] / _SCREEN
#
# Two modules are written that way — the §140A challan guard and the ITR
# keying-sheet one — and NEITHER was in this list, so a frontend-only PR
# skipped both. That is precisely the defect this script's docstring says it
# exists to prevent, and it is how a gap-callout adoption on 18 September broke
# `test_the_panel_tells_a_gap_from_a_caveat` with the browser-contract job
# reporting green.
#
# Matched on a STRING CONSTANT via the AST rather than on the raw text, because
# the docstring's own rule holds: a path in a comment is not a read.
_WEB_TAIL = re.compile(r'^(web|marketing)/')


def _has_web_literal(path: pathlib.Path) -> bool:
    try:
        tree = ast.parse(path.read_text(errors="ignore"))
    except SyntaxError:
        return False
    return any(
        isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and _WEB_TAIL.match(n.value)
        for n in ast.walk(tree)
    )


def _module_name(path: pathlib.Path) -> str:
    return path.stem


def _imports_within_tests(path: pathlib.Path, known: set[str]) -> set[str]:
    """Test modules this file imports, by module name."""
    try:
        tree = ast.parse(path.read_text(errors="ignore"))
    except SyntaxError:
        return set()

    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            # `from tests.test_x import y` or `from test_x import y`
            tail = node.module.rsplit(".", 1)[-1]
            if tail in known:
                out.add(tail)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                tail = alias.name.rsplit(".", 1)[-1]
                if tail in known:
                    out.add(tail)
    return out


def modules_reading_the_browser() -> list[pathlib.Path]:
    files = sorted(TESTS.glob("test_*.py"))
    by_name = {_module_name(p): p for p in files}

    # Seed: the modules that build the path themselves.
    reading: set[str] = {
        _module_name(p)
        for p in files
        if _BUILDS_WEB_PATH.search(p.read_text(errors="ignore"))
        or _has_web_literal(p)
    }

    # Close over imports until nothing new is added — a module that imports a
    # reader is itself a reader, however long the chain.
    edges = {_module_name(p): _imports_within_tests(p, set(by_name)) for p in files}
    changed = True
    while changed:
        changed = False
        for name, imported in edges.items():
            if name not in reading and (imported & reading):
                reading.add(name)
                changed = True

    return [by_name[n] for n in sorted(reading)]


def main() -> int:
    found = modules_reading_the_browser()
    if not found:
        # Never print nothing: an empty argument list makes pytest collect the
        # WHOLE suite, which is the opposite of this script's purpose and would
        # look like a pass while costing the full budget.
        print(
            "No test module reads apps/web — that cannot be right, so this is a "
            "bug in tests_reading_the_browser.py rather than a clean result.",
            file=sys.stderr,
        )
        return 1
    for path in found:
        print(f"tests/{path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
