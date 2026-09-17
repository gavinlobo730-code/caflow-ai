"""
The day book prints a journal's SOURCE, and derives the label from the value.

WHY THE GUARD IS HERE AND NOT IN apps/web
    `apps/web/app/clients/[id]/accounting/page.tsx::sourceLabel` turns a
    `journal_entries.source_type` into a reader's phrase by replacing
    underscores, splitting camelCase and title-casing the result. It does that
    rather than carrying a twenty-entry label map, because a map is a second
    copy of ALL_SOURCES and would be out of step the first time a source is
    added.

    Deriving only works while the vocabulary keeps a shape the derivation can
    read. A twenty-first source spelled `GSTR3B_ADJUSTMENT` would render as
    "Gstr3b adjustment"; one spelled `x` would render as "X". Neither is caught
    by anything in apps/web — a test written there would assert the prettifier
    against a copy of its own assumptions and pass whenever both drifted
    together, which is exactly what the Schedule III mapping screen's hardcoded
    caption list did for months (CLAUDE.md).

    So the constraint is held from the side that owns the vocabulary: adding a
    source is what should fail, not rendering one.

WHAT IS NOT ASSERTED
    That any particular value produces any particular English phrase. That
    would pin prose to a test. What is asserted is that the SHAPE stays
    derivable.
"""
from __future__ import annotations

import re

import pytest

from domain.accounting import journal_source as JS


def _prettify(value: str) -> str:
    """The TypeScript prettifier, transcribed. Kept short deliberately — if it
    grows past this, it has become a rule and belongs in one place with a
    parity test, not in two."""
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", value).replace("_", " ").strip()
    return (spaced[:1].upper() + spaced[1:].lower()) if spaced else "—"


def test_every_source_is_a_word_a_reader_can_read():
    for src in sorted(JS.ALL_SOURCES):
        label = _prettify(src)
        assert label and label != "—", f"{src!r} prettifies to nothing"
        assert len(label) >= 4, (
            f"{src!r} prettifies to {label!r}, which is too short to mean "
            "anything on a report. Give the source a spelled-out name.")
        assert re.fullmatch(r"[A-Z][a-z]+( [a-z]+)*", label), (
            f"{src!r} prettifies to {label!r}, which the day book's derivation "
            "cannot make readable. A source_type must be snake_case ASCII "
            "words, or camelCase — no digits, no acronyms, no punctuation. "
            "Adding one that is not means teaching sourceLabel about it, in "
            "apps/web/app/clients/[id]/accounting/page.tsx.")


def test_the_two_camelcase_spellings_are_still_the_only_two():
    """`Opening` and `TrialBalance` keep their original spelling on purpose —
    journal_source.py records why. The derivation handles camelCase for exactly
    those two; this fails if a third appears, so the decision is re-taken rather
    than inherited."""
    camel = {s for s in JS.ALL_SOURCES if re.search(r"[a-z][A-Z]", s) or s[:1].isupper()}
    assert camel == {JS.OPENING, JS.TRIAL_BALANCE_IMPORT}, (
        f"camelCase sources are now {sorted(camel)}. Two were a deliberate "
        "exception; a third is a vocabulary drifting.")


@pytest.mark.parametrize("src,expected", [
    ("sales_invoice", "Sales invoice"),
    ("payroll_disbursement", "Payroll disbursement"),
    ("TrialBalance", "Trial balance"),
    ("Opening", "Opening"),
    ("year_end_adjustment", "Year end adjustment"),
])
def test_the_worked_examples(src, expected):
    """A handful pinned by hand, so the transcription above is checked against
    real values rather than only against itself."""
    assert src in JS.ALL_SOURCES
    assert _prettify(src) == expected


def test_the_screen_derives_rather_than_listing():
    """The whole point. A label map in the browser is the failure this avoids,
    so its absence is what the test holds.

    RESOLVED, NOT NAMED. This used to assert `function sourceLabel` in
    `app/clients/[id]/accounting/page.tsx`, and broke when ACC-22 moved the
    function into `lib/accounting/sourceDocument.ts` so the ledger's
    drill-through could share it — a move that did not break the rule. The
    definition is found by searching `apps/web` for it, and the rule (derive,
    never list) is asserted against wherever it lives.
    """
    from pathlib import Path
    web = Path(__file__).resolve().parents[3] / "apps" / "web"
    if not web.exists():                        # backend-only checkout
        pytest.skip("apps/web not present")
    homes = [p for p in web.rglob("*.ts*")
             if "node_modules" not in p.parts and ".next" not in p.parts
             and "function sourceLabel" in p.read_text(encoding="utf-8", errors="replace")]
    assert len(homes) == 1, (
        "the browser must derive its source label in exactly one place — "
        f"found {len(homes)}: {[str(h.relative_to(web)) for h in homes]}")
    code = homes[0].read_text(encoding="utf-8")
    assert "SOURCE_LABELS" not in code, (
        "a hardcoded source-label map is back. It is a second copy of "
        "ALL_SOURCES and will be out of step the first time a source is added.")
    # The derivation itself, rather than only the absence of a map: a body that
    # stopped transforming the value would pass both checks above.
    assert "replace(/_/g" in code and "toUpperCase()" in code, (
        "sourceLabel no longer derives the label from the value")
