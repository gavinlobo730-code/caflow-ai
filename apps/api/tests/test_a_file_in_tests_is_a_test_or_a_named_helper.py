"""
Nothing in `tests/` may terminate the interpreter when it is imported.

WHAT THIS REPLACES

    `tests/e2e_gst_verification.py` was a 42 KB procedural SCRIPT living in the
    test directory: twenty-four `check()` calls, a readiness scorecard and a
    `sys.exit(1)` at module level. Two things followed from that.

    It never ran. No `test_` prefix, so `pytest tests/` skipped it — and asking
    for it BY NAME did not run it either: the module-level `sys.exit` raised
    during collection and pytest answered `INTERNALERROR`, not a failure. A file
    that cannot be collected cannot be red, so nothing ever told anyone it had
    gone stale.

    And it had. Its last honest reading was months old: "Engine Readiness 93%",
    "UI Readiness 0% — no GSTR-1 review UI, no GSTR-3B review UI", "Commercial
    Readiness 5%", "56 tests passing", and seven "BLOCKERS BEFORE A CA CAN
    GENERATE RETURNS" of which every single one is built. Run today it failed
    six checks, and **all six were the script being wrong**:

      * it expected the B2CL threshold to be ₹2,50,000. Notification
        12/2024-Central Tax moved it to ₹1,00,000 from 01-08-2024, which is
        what `classifier.b2cl_threshold_paise` answers, by invoice date.
      * it expected reverse charge in Table 3.2. Table 3.2 is supplies to
        unregistered persons, composition dealers and UIN holders; inward
        reverse charge is 3.1(d).
      * it expected net IGST to be outward IGST less IGST credit. Since the
        four-step §49(5) set-off with Rule 88A, IGST credit also pays CGST and
        SGST, so the net legitimately differs.
      * its own fixture GSTIN carried a wrong check digit, which GST-29 now
        catches — the same correction the other 77 fixture files took.
      * and one check's expectation contradicted its own label.

    So a file whose entire purpose was to verify the engine end to end reported
    the engine at 93% and the product at 5%, and was wrong about all of it. That
    is worse than no file: somebody runs it and doubts a correct engine.

    Deleted rather than repaired. Its twenty-four assertions are covered by the
    suite that actually runs — `test_gstr3b_setoff_and_rcm.py` alone has
    twenty-four cases across cross-utilisation, the CGST/SGST bar, stranded
    IGST, reverse charge in cash and zero-rated supplies, and
    `test_the_return_declares_what_the_books_hold.py` covers the 3.1(e) line the
    script's own scorecard never mentioned. `docs/audits/` is where a
    point-in-time scorecard belongs, and CLAUDE.md already says those are
    historical records rather than current specs.

THE RULE

    Every file in `tests/` is importable. A file that is not a test is a named
    helper — a parser, the harness, a fixture set — and a helper does not exit
    the interpreter either.
"""
from __future__ import annotations

import ast
import pathlib

TESTS = pathlib.Path(__file__).resolve().parent

#: Files in tests/ that are deliberately not test modules. Each is imported BY
#: a test rather than collected as one. Listed rather than pattern-matched, so
#: adding a script to this directory is a decision somebody writes down.
HELPERS = {
    "__init__.py",
    "conftest.py",
    "_backend_query_parser.py",
    "_frontend_select_parser.py",
    "_schema_checked_db.py",
    "e2e_harness.py",
    "generate_gst_parity_vectors.py",
    "production_types.py",
    "uat_fixtures.py",
}

_EXITS = {"exit", "quit", "_exit"}


def _module_level_exit(tree: ast.Module) -> ast.AST | None:
    """A call that ends the process, reachable at import.

    Statements inside `if __name__ == "__main__":` are skipped — that is the
    one place a module may legitimately behave like a script, because pytest
    never takes that branch.
    """
    for node in tree.body:
        if isinstance(node, ast.If) and ast.dump(node.test).find("__main__") != -1:
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            fn = inner.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else fn.id if isinstance(fn, ast.Name) else "")
            if name in _EXITS and not isinstance(node, (ast.FunctionDef,
                                                        ast.AsyncFunctionDef,
                                                        ast.ClassDef)):
                return inner
    return None


def test_no_file_in_tests_exits_the_interpreter_at_import():
    offenders = []
    for path in sorted(TESTS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        hit = _module_level_exit(tree)
        if hit is not None:
            offenders.append(f"{path.name}:{hit.lineno}")
    assert offenders == [], (
        "a module-level exit makes the file uncollectable — pytest answers "
        "INTERNALERROR rather than a failure, so the file can never be red and "
        "nothing tells you it has gone stale: " + ", ".join(offenders))


def test_every_file_here_is_a_test_or_a_declared_helper():
    stray = sorted(p.name for p in TESTS.glob("*.py")
                   if not p.name.startswith("test_") and p.name not in HELPERS)
    assert stray == [], (
        "a script in tests/ reads as verification and runs in no CI. Give it a "
        "test_ prefix so it is collected, move it to scripts/, or add it to "
        "HELPERS above with a reason: " + ", ".join(stray))


def test_the_declared_helpers_all_exist():
    """So the list cannot quietly outlive what it exempts."""
    missing = sorted(h for h in HELPERS if not (TESTS / h).exists())
    assert missing == [], f"HELPERS names files that are gone: {missing}"
