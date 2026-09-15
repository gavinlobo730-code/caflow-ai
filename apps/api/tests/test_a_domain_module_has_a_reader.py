"""
A MODULE NOBODY IMPORTS IS A RULE NOBODY APPLIES.

THREE OF THESE WERE FOUND IN ONE AFTERNOON, and each had been written
carefully, tested, and never wired to anything:

    models/uqc.py                            CBIC's Unit Quantity Code list.
        Three validators cited `VALID_UQC_CODES` in their COMMENTS and none
        imported it, so GSTR-1 Table 12 filed 'PIECES' as a UQC.

    domain/currency/fx_revaluation_service.py    AS 11's year-end retranslation.
        The only writer of `fx_revaluations`, so the Unrealized FX report was a
        structural nil for every client.

    domain/income_tax/regime_election.py     §115BAC(6) with Rule 21AGA.
        A missed Form 10-IEA cannot be cured after the due date, and the
        return computes cleanly either way.

Each was found by hand, by asking "what under domain/ does nothing import?".
That question should not need asking twice, so it is a test.

WHAT THIS IS NOT
    It is not "delete unused code". Several modules below are imported only
    through a package `__init__` re-export, or are a deliberate re-export
    shim, or are a rule whose one caller is a sibling in the same package.
    Those are fine and are why the scan resolves re-exports rather than
    grepping for a name.

    Nor is it a claim that everything here is a defect. It is the LIST, with a
    reason each, and this test fails when the list GROWS — the same shape as
    test_every_dated_posting_path_asserts_the_client_lock.py's NOT_YET and
    test_no_posting_path_names_a_ledger_by_string.py's STILL_NAMING_IT. The
    entries are the work; a list that can only shrink turns "we will wire that
    up" into something a test can hold you to.

WHY `domain/` AND NOT `services/` OR `routers/`
    A router is reachable by being mounted, and `test_every_mounted_endpoint_
    has_a_way_in.py` already asks whether a screen reaches it. A service is
    called by a router. `domain/` is where the STATUTORY RULES live, and a
    statutory rule with no reader is the failure this codebase keeps finding:
    the software knows the law and never applies it.
"""
from __future__ import annotations

import ast
import pathlib

API = pathlib.Path(__file__).resolve().parent.parent
DOMAIN = API / "domain"

# module path (relative to apps/api) -> why nothing imports it.
# Entries may be REMOVED as each is wired up. Adding one needs a reason.
NO_READER_YET: dict[str, str] = {
    "domain/reporting/pdf_text.py":
        "NOT A DEFECT, and the reason is worth keeping so nobody 'fixes' it. "
        "Its docstring says the rupee-glyph substitution 'is one function "
        "now'; in fact the five PDF services never CONSTRUCT a ₹ string at "
        "all — they write 'Rs.' into their format strings directly — and "
        "test_no_pdf_renders_the_rupee_sign.py is what enforces that. The one "
        "place the text is NOT under a service's control is CA-authored HTML "
        "in an engagement letter, and engagement_pdf_service._pdf_safe "
        "handles that with 'Rs. ' (a space, for running prose) where this "
        "module uses 'Rs.' (no space, for a table cell). They are two "
        "answers to two questions; unifying them would change a document a "
        "client receives.",
    "domain/banking/exceptions.py":
        "A REAL GAP, named rather than silently fixed. 315 lines of rules for "
        "'what a partner should look at' on a bank transaction, and the only "
        "importer is its own test. Its docstring says the context is gathered "
        "by `services/bank_exception_service.py` — THAT FILE DOES NOT EXIST. "
        "So no flag is raised, no partner sees one, and `blocking` is "
        "computed by nobody. The module itself records that nothing here "
        "gating a posting is a PRODUCT DECISION and not an oversight, and "
        "surfacing it is a review queue somebody has to want: it is in "
        "docs/audits/questions-for-the-owner.md rather than built on a guess "
        "about how a firm reviews.",
    "domain/notification_service.py":
        "DEAD DUPLICATE, and the hazard is which one gets imported next. "
        "`services/notification_service.py` is the live one — routers/tasks.py "
        "calls it — and this is an older copy whose store is a module-level "
        "MOCK_NOTIFICATIONS list. Nothing in the production tree imports it; "
        "the one importer anywhere is tests/test_pilot_features.py, which "
        "reads MOCK_NOTIFICATIONS directly. The risk is the retired "
        "supplier table's shape (migration 378, not named here because a "
        "guard reserves that name and is right to — a real read of it could "
        "be a raw SQL string): a future reader reaches for the name, gets "
        "the mock, and writes notifications nobody receives. "
        "Deleting it is the right end state and is an owner decision, like "
        "the two DROPs in questions-for-the-owner.md §9.",
}


def _module_name(path: pathlib.Path) -> str:
    return str(path.relative_to(API).with_suffix("")).replace("/", ".")


def _imported_names(tree: ast.AST, own: str) -> set[str]:
    """Every module this file imports, as a dotted name.

    Resolves a RELATIVE import against the importing package, because that is
    how most of `domain/` refers to its siblings — a scan that only looked for
    absolute `domain.x.y` would report almost everything as unread.
    """
    own_pkg = own.rsplit(".", 1)[0]
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # `from . import x` / `from .y import z`
                base = own_pkg
                for _ in range(node.level - 1):
                    base = base.rsplit(".", 1)[0] if "." in base else ""
                mod = f"{base}.{node.module}" if node.module else base
            else:
                mod = node.module or ""
            if mod:
                out.add(mod)
                for alias in node.names:
                    # `from domain.gst import uqc` imports domain.gst.uqc
                    out.add(f"{mod}.{alias.name}")
    return out


def _modules_with_no_reader() -> dict[str, str]:
    modules = {}
    for path in sorted(DOMAIN.rglob("*.py")):
        if "__pycache__" in str(path) or path.name == "__init__.py":
            continue
        modules[_module_name(path)] = path

    # Everything the production tree imports. Tests are EXCLUDED on purpose:
    # a module imported only by its own tests is exactly the shape this test
    # exists to find — all three examples in the docstring were well tested.
    imported: set[str] = set()
    for root in ("domain", "services", "routers", "core", "models", "jobs", "seed"):
        base = API / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:                                  # pragma: no cover
                continue
            own = _module_name(path)
            for name in _imported_names(tree, own):
                if name != own:
                    imported.add(name)
    for extra in (API / "main.py",):
        if extra.exists():
            tree = ast.parse(extra.read_text())
            imported |= _imported_names(tree, "main")

    return {mod: str(p.relative_to(API).as_posix())
            for mod, p in modules.items() if mod not in imported}


def test_no_new_statutory_rule_is_left_without_a_reader():
    unread = _modules_with_no_reader()
    rels = {rel for rel in unread.values()}
    new = sorted(rels - set(NO_READER_YET))
    assert not new, (
        "these modules under domain/ are imported by nothing in the "
        "production tree, so whatever rule they hold is never applied:\n  "
        + "\n  ".join(new) +
        "\n\nWire one up, or add an entry to NO_READER_YET with the reason. "
        "A module imported only by its own tests is exactly this shape — all "
        "three found on 14-09-2026 were well tested.")


def test_the_acknowledged_list_does_not_name_a_module_that_is_now_read():
    """An entry left behind after something is wired up reads as debt and is
    not. Same reason the post-snapshot column list refuses a migration that
    does not exist."""
    unread = {rel for rel in _modules_with_no_reader().values()}
    stale = sorted(set(NO_READER_YET) - unread)
    assert not stale, (
        f"these are named as having no reader and now have one: {stale}. "
        f"Delete the entry.")


def test_the_scan_is_not_vacuous():
    """A resolver that quietly stopped resolving would report everything as
    read and this whole module would pass on nothing."""
    total = sum(1 for p in DOMAIN.rglob("*.py")
                if "__pycache__" not in str(p) and p.name != "__init__.py")
    assert total > 150, f"only {total} domain modules found — the walk is broken"
    unread = _modules_with_no_reader()
    assert len(unread) < total // 4, (
        f"{len(unread)} of {total} domain modules report as unread, which "
        f"means the import resolver has stopped resolving rather than that "
        f"the codebase has decayed")
