"""Every kind of register-integrity finding is rendered by a screen (FA-02, FA-07).

WHY THIS GUARD IS ON THE PYTHON SIDE

`routers/fixed_assets.py` OWNS the vocabulary. It decides what kinds of finding
exist and composes the sentence for each. A guard written in `apps/web` would
assert the screen against a copy of the vocabulary held in `apps/web`, and would
pass whenever both drifted together — which is exactly what the Schedule III
mapping screen's hardcoded caption list did for months (CLAUDE.md records the
nine mapped accounts it silently discarded).

So the assertion runs from the side that owns the words, reading the TypeScript,
the same shape as test_the_browser_fallback_speaks_the_engines_vocabulary.py.

WHAT WAS WRONG

GET /api/fixed-assets/register-integrity existed and NO SCREEN CALLED IT. It is
the whole of FA-02's remedy — a depreciation basis off Schedule II Part C is
REPORTED rather than migrated away, because Part A permits a different useful
life or residual value provided it is disclosed, so only the CA can say whether
a departure is an error or a judgement. Reporting it to nobody is not reporting
it. CLAUDE.md states the rule this breaks: a figure the computer gets right and
no screen shows is not a fixed bug.

WHAT THIS DOES NOT CLAIM

That the rendering is GOOD — only that every kind the router can emit has a
title on the screen, and that the screen renders the server's own sentence
rather than rebuilding it. A finding whose `what_it_means` were composed in the
browser would be a second implementation of the rule, and the two would drift.
"""
from __future__ import annotations

import pathlib
import re

WEB = pathlib.Path(__file__).resolve().parents[2] / "web"
SCREEN = WEB / "app" / "clients" / "[id]" / "fixed-assets" / "page.tsx"
ROUTER = pathlib.Path(__file__).resolve().parents[1] / "routers" / "fixed_assets.py"


def _strip_line_comments(ts: str) -> str:
    """Comments quote the very strings they explain — this file's own panel
    header names `register-integrity` in prose. Assertions are about CODE."""
    ts = re.sub(r"/\*[\s\S]*?\*/", "", ts)
    return re.sub(r"^\s*//.*$", "", ts, flags=re.M)


def _router_kinds() -> set[str]:
    """Every `"kind": "..."` literal the register-integrity answer can carry.

    Read from the ROUTER and from `domain/fixed_assets/integrity.py`, because
    FA-20 moved the rule into the domain so the nightly reconciliation sweep
    could run the same checks — and a scanner left pointing at the router alone
    would have found nothing and passed every assertion in this file
    vacuously, which is the state the guard below exists to refuse.
    """
    src = ROUTER.read_text() + (
        ROUTER.resolve().parents[1] / "domain" / "fixed_assets" / "integrity.py"
    ).read_text()
    return set(re.findall(r'"kind":\s*"([a-z0-9_]+)"', src))


def test_the_router_still_emits_the_kinds_this_guard_checks():
    """A scan that silently matched nothing would pass every other test here."""
    kinds = _router_kinds()
    assert len(kinds) >= 4, f"expected the four register-integrity kinds, found {kinds}"
    assert "depreciation_basis_departs_from_schedule_ii" in kinds, (
        "FA-02's finding is the reason this file exists; if it has been renamed, "
        "rename it here too rather than deleting the assertion")


def test_a_screen_calls_the_endpoint():
    code = _strip_line_comments(SCREEN.read_text())
    assert "register-integrity" in code, (
        "GET /api/fixed-assets/register-integrity is the whole of FA-02's remedy "
        "and three-quarters of FA-07's. It went un-called by any screen from the "
        "day it was written; a finding nothing displays is not a finding.")


def test_every_finding_kind_has_a_title_on_the_screen():
    """Matched on the IDENTIFIER, not on a quoting style.

    The first version of this assertion looked for `"kind"` with quotes and
    failed on all four, because the screen's lookup table uses bare object keys
    — `no_acquisition_journal: "..."`. That is the money-parser mistake in
    miniature and inside a guard written to prevent it: the rule is "the screen
    names this kind", and `"..."` was one spelling of it.
    """
    code = _strip_line_comments(SCREEN.read_text())
    missing = sorted(k for k in _router_kinds()
                     if not re.search(rf"\b{re.escape(k)}\b", code))
    assert not missing, (
        "the router can emit these and the screen has no title for them, so they "
        f"render as a raw snake_case key: {missing}")


def test_the_screen_renders_the_servers_sentence_rather_than_rebuilding_it():
    """The INTERPOLATION, not the mere presence of the name.

    The first version asserted `"what_it_means" in code` and PASSED when the
    rendered sentence was replaced with a hardcoded "Check this asset." — because
    the name still appeared in the TypeScript type declaring the field. Matching
    a type is not matching a behaviour, and it is the same error as matching a
    quoting style one test up.
    """
    code = _strip_line_comments(SCREEN.read_text())
    assert re.search(r"\{\s*[A-Za-z_$][\w$]*\.what_it_means\s*\}", code), (
        "each finding's sentence is composed in routers/fixed_assets.py, beside "
        "the rule it states, and must be RENDERED — not merely typed. Rebuilding "
        "it in the browser is a second implementation of a statutory explanation, "
        "and the two drift.")


def _catch_bodies(code: str) -> list[str]:
    """The text following each `catch`, to the end of its block or 800 chars.

    Crude on purpose: the assertion below is about what the failure path DOES,
    and a brace-matching parser here would be a second TypeScript parser to
    maintain. 800 characters comfortably covers a setState call.
    """
    return [code[m.end():m.end() + 800] for m in re.finditer(r"\bcatch\s*\(", code)]


def test_an_all_clear_is_distinguishable_from_a_failed_check():
    """The endpoint returns `checked` precisely so that "no findings" over
    nothing checked is not the same statement as a clean register. A screen that
    swallowed the error would undo that.

    Asserted over the FAILURE PATH, not over the presence of the word. The first
    version searched the whole file for `status: "error"` and passed when the
    catch was changed to report a clean, zero-asset result — the string was
    still there, in the state union TYPE.
    """
    code = _strip_line_comments(SCREEN.read_text())
    assert "checked" in code, "the screen must show how many assets were checked"

    integrity = code[code.index("register-integrity"):] if "register-integrity" in code else ""
    # The discriminant's NAME is the screen's own choice — this panel calls it
    # `phase`, because "loading | error | ok" is where the fetch has got to and
    # not the state of any record, and spelling it `status` made
    # test_frontend_status_values_match_the_check_pg read those three as
    # database status values. What this guard is about is the VALUE: the catch
    # has to set an error state rather than an empty one.
    assert any(re.search(r'\b(?:phase|status):\s*"error"', body)
               for body in _catch_bodies(integrity)), (
        "a failed load must render as a failure, not as an empty — and therefore "
        "clean-looking — result. No catch on this panel sets an error state.")
