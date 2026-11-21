"""POST-A-539: what the product says about professional tax is what the product does, and nothing it has not read.

WHAT WAS WRONG
    The owner was shown Settings, Tax and statutory values on the live Test Firm on 21-11-2026 and could not tell what the
    page was for. Two of its sentences also stated things nobody had confirmed. "Twenty-two states levy it": the list is this
    product's own (`professional_tax.LEVYING_STATES`), graded [S], and CLAUDE.md records that it is probably one or two too
    long. "Article 276 makes the employer liable either way": a legal reading that was never checked against the text, and
    the duty to deduct is each state's own Act in any case. The same sentence stood in the note a payroll run carries for an
    employee in a state whose slabs are not built in, so it reached every CA who released such a run. And the server's
    sentence about a state whose slabs are built in said they were "verified against the state Act", with no record of the
    reading to point to.

WHAT THESE TESTS HOLD
    The rule, in three places a person reads: the note a payroll run carries, the server's sentence on the settings page, and
    the page itself. Each says what the product did (nothing was deducted, the slabs are built in or are not, the gap is
    named) and none cites Article 276, says who is liable, counts the states that levy the tax, or calls a table verified.
    The questions those sentences were answering are on the owner's list (S9) for a practising CA.

    The last test is the sweep: no screen of the web app says "Article 276" at all. It is the rule and not a list of the
    places found, so a new screen that reaches for the same authority fails here.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from domain.payroll import firm_rates
from domain.payroll import professional_tax as pt

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
PAGE = WEB / "app" / "settings" / "statutory-values" / "page.tsx"

#: What a sentence about professional tax may not say until somebody has read the text it leans on.
UNREAD = re.compile(r"Article\s+276|\bliable\b|verified against", re.IGNORECASE)
#: A count of the states that levy the tax, however it is written. The count of states BUILT IN is the product's own and is allowed.
COUNT_OF_LEVYING_STATES = re.compile(r"\b(twenty[- ]two|22)\s+states\b|\bof\s+(twenty[- ]two|22)\b", re.IGNORECASE)


def _code(path: Path) -> str:
    """A TypeScript source with its comments removed: the rule is about what a person is shown, and these files explain
    their own history in comments (the page's header says what it used to claim)."""
    src = path.read_text(encoding="utf8")
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"(?m)^\s*//.*$", "", src)


UNBUILT = sorted(set(pt.LEVYING_STATES) - set(pt.MODELLED_STATES))


def test_the_sweep_has_something_to_look_at():
    assert len(UNBUILT) >= 10, "the list of states with no slabs built in has all but emptied: this test is about them"
    assert PAGE.exists(), "the statutory values page has moved"


@pytest.mark.parametrize("code", UNBUILT)
def test_the_note_on_a_run_says_what_was_done_and_claims_nothing_unread(code):
    note = pt.classify_state(code).note
    assert pt.classify_state(code).is_gap
    assert "NOTHING has been deducted" in note
    assert "not a finding that nothing is due" in note, "a zero with no explanation reads as 'nothing due'"
    assert "is listed here as levying professional tax" in note, "the note states the list as law and not as the product's own"
    assert "Settings" in note, "the note does not say where the slabs are recorded"
    assert not UNREAD.search(note), f"the note for {code} says something nobody has read: {note}"


def test_the_note_for_a_ticked_employee_with_no_state_cites_nothing():
    note = pt.classify_for_employee(True, "").note
    assert "no state is recorded" in note.replace("\n", " ")
    assert not UNREAD.search(note), note


def test_the_servers_sentence_about_a_built_in_state_does_not_call_it_verified():
    sentences = firm_rates.slabs_recorded_against_a_modelled_state([{"state": "MH"}], pt.MODELLED_STATES)
    assert len(sentences) == 1
    assert "built into the software" in sentences[0] and "NOT used" in sentences[0]
    assert not UNREAD.search(sentences[0]), sentences[0]


def test_the_page_says_what_it_is_for_and_states_nothing_unread():
    code = _code(PAGE)
    # What it is for, in its first sentence, and whose list the states are.
    assert "Professional tax is set by each state." in code
    assert re.search(r"payroll deducts no professional tax and names the gap on the run", code)
    assert re.search(r"has not been confirmed against each\s+state&apos;s current law", code), \
        "the page lists states as levying the tax without saying the list is the product's own"
    assert not UNREAD.search(code), "the page cites an authority, or calls something verified, that nobody has read"
    assert not COUNT_OF_LEVYING_STATES.search(code), "the page counts the states that levy the tax as a fact"
    # The one count it gives is of what the product holds, taken from the server's answer.
    assert "{modelled.length}" in code


def test_no_screen_cites_article_276():
    """The rule, over every screen and component. A comment may say what was wrong; a sentence a person reads may not lean
    on a provision nobody has read."""
    offenders = []
    for root in (WEB / "app", WEB / "components"):
        for path in sorted(root.rglob("*.tsx")):
            if re.search(r"Article\s+276", _code(path)):
                offenders.append(str(path.relative_to(WEB)))
    assert offenders == [], f"these screens cite Article 276: {offenders}"


def test_the_rule_reader_sees_what_it_is_for():
    """The control: each pattern fires on the sentence it replaced, and the comment stripper leaves code alone."""
    assert UNREAD.search("Article 276 makes the employer liable either way.")
    assert UNREAD.search("verified against the state Act")
    assert COUNT_OF_LEVYING_STATES.search("Twenty-two states levy it")
    assert COUNT_OF_LEVYING_STATES.search("this app models four of twenty-two")
    assert not COUNT_OF_LEVYING_STATES.search("PracticeSync has the slabs of 4 states built in")
    assert "kept" in re.sub(r"(?m)^\s*//.*$", "", re.sub(r"/\*[\s\S]*?\*/", "", "/* gone */ const a = 'kept'; // gone\n// gone"))
