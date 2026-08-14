"""
Every AI system prompt must agree with the code that computes the real answer.

THE MISTAKE THIS EXISTS TO CATCH
    A prompt is prose, so nothing checks it. Two ways that bit:

    1. WRONG DEADLINE. Both CLAUDE.md and the copilot prompt stated the TDS
       return rule as "31st of month following quarter end". That holds for
       Q1-Q3 and is WRONG for Q4: the quarter ends 31 March, the rule implies
       30 April, and the statutory date is 31 May.
       services/compliance_engine.py::tds_return_due_date had it right all
       along — so the app's own compliance calendar generated correct due
       dates while the AI, asked the same question, would have answered a month
       early. Nothing reconciled the two.

    2. A HARDCODED YEAR. The copilot prompt said "Current financial year:
       2026-27" as a literal. Correct for twelve months, then silently wrong —
       on 1 April 2027 the copilot would still introduce itself as working in
       FY 2026-27 and every "this year" answer would be off by one, with no
       failure anywhere until a human noticed.

    Both are the same shape: a fact duplicated into prose, drifting from the
    code that owns it. This file re-derives the facts and asserts the prose.

SCOPE
    Only claims that CAN be checked against code. Nothing here can tell you a
    rate is right — that needs a CA and the current Finance Act, which is why
    the prompts are written to attribute rates to their Act rather than assert
    them for an unverified year. That property is asserted too, since deleting
    it is the easy edit that makes a prompt confidently wrong.
"""
import re
from datetime import date

import pytest

from core.ist_clock import ist_fy_label
from services.compliance_engine import tds_return_due_date


def _prompts() -> dict[str, str]:
    """name -> rendered prompt text, for every system prompt in the backend."""
    from domain.ai_copilot_service import _system_prompt
    from domain.financial_analysis_service import _SYSTEM_PROMPT as analysis
    from routers.ai_copilot import COPILOT_SYSTEM_PROMPT
    from routers.assistant import SYSTEM_PROMPT as assistant

    return {
        "routers/assistant.py": assistant,
        "routers/ai_copilot.py": COPILOT_SYSTEM_PROMPT,
        "domain/ai_copilot_service.py": _system_prompt(),
        "domain/financial_analysis_service.py": analysis,
    }


def test_the_scan_finds_every_prompt():
    """Vacuity guard. A renamed constant would otherwise silently drop a prompt
    out of every check below."""
    prompts = _prompts()

    assert len(prompts) == 4
    for name, text in prompts.items():
        assert len(text) > 200, f"{name} looks empty — did the constant move?"


# ── TDS Q4: the deadline the prose kept getting wrong ────────────────────────

def test_the_engine_really_does_say_31_may_for_q4():
    """Anchors the source of truth before asserting anything against it. If
    this changes, the prompts are not the thing that broke."""
    assert tds_return_due_date("Q4", 2027) == date(2027, 5, 31)
    assert tds_return_due_date("Q1", 2027) == date(2026, 7, 31)
    assert tds_return_due_date("Q2", 2027) == date(2026, 10, 31)
    assert tds_return_due_date("Q3", 2027) == date(2027, 1, 31)


@pytest.mark.parametrize("name", ["routers/assistant.py", "domain/ai_copilot_service.py"])
def test_prompts_that_state_tds_deadlines_get_q4_right(name):
    text = _prompts()[name]

    assert re.search(r"31 MAY|31 May", text), \
        f"{name} lists TDS return deadlines without the correct Q4 date (31 May)"
    assert "30 April" not in text or "NOT" in text, \
        f"{name} mentions 30 April for TDS without marking it as the wrong answer"


@pytest.mark.parametrize("name", ["routers/assistant.py", "domain/ai_copilot_service.py"])
def test_the_q4_exception_is_flagged_not_merely_listed(name):
    """Listing four dates invites the model to "correct" the odd one by analogy
    to the other three. The exception has to be named as an exception."""
    text = _prompts()[name]

    assert "NOT" in text and "30 April" in text, \
        f"{name} does not warn that 30 April is the wrong Q4 answer"


# ── The financial year must be computed, never written down ──────────────────

def test_the_copilot_states_the_financial_year_the_clock_says():
    text = _prompts()["domain/ai_copilot_service.py"]

    assert f"Current financial year: {ist_fy_label()}" in text


def test_the_copilot_year_tracks_the_clock_rather_than_a_literal(monkeypatch):
    """The regression that matters: a hardcoded year passes on the day it is
    written and fails silently every day after 31 March. Move the clock and the
    prompt must follow."""
    import core.ist_clock as clock
    from domain import ai_copilot_service

    monkeypatch.setattr(clock, "ist_today", lambda: date(2031, 6, 1))
    text = ai_copilot_service._system_prompt()

    assert "Current financial year: 2031-32" in text
    assert "1 April 2031 to 31 March 2032" in text


@pytest.mark.parametrize("name", sorted(_prompts()))
def test_no_prompt_hardcodes_a_financial_year_as_current(name):
    """Any literal FY next to the word "current" is a claim with an expiry date
    on it. Compute it instead."""
    text = _prompts()[name]
    for m in re.finditer(r"(?i)current financial year[:\s]+(\d{4}-\d{2})", text):
        assert m.group(1) == ist_fy_label(), (
            f"{name} states FY {m.group(1)} as current; the clock says "
            f"{ist_fy_label()}. Render it from core.ist_clock.ist_fy_label()."
        )


# ── Rates must be attributed, not asserted for an unverified year ────────────

@pytest.mark.parametrize("name", ["routers/assistant.py", "domain/ai_copilot_service.py"])
def test_prompts_carrying_tax_content_say_rates_are_year_bound(name):
    """The failure this prevents is the worst one available to these endpoints:
    a CA asks for a rate and gets a confident, stale number."""
    text = _prompts()[name].lower()

    assert "finance act" in text
    assert "cannot confirm" in text or "cannot verify" in text


# ── Guard rails that must survive any future prompt edit ─────────────────────

@pytest.mark.parametrize("name", sorted(_prompts()))
def test_no_prompt_invites_auto_submission(name):
    """CLAUDE.md: never auto-submit to any government portal. A prompt that
    offers to file is the one place that rule could be undone by prose."""
    lowered = _prompts()[name].lower()

    for phrase in ("submit the return", "file it for you", "auto-submit to"):
        assert phrase not in lowered, f"{name} suggests submitting on the user's behalf"


def test_the_copilot_prompt_still_forbids_naming_clients():
    """The copilot's firm context deliberately carries counts, not identities.
    That constraint lives only in the prompt, so it is worth pinning."""
    text = _prompts()["routers/ai_copilot.py"]

    assert "NO" in text and "client names" in text
    assert "do not ask for them, invent them" in text


def test_the_financial_analysis_prompt_stays_out_of_tax():
    """It reads a P&L and Balance Sheet only. Letting it opine on GST or TDS
    would put tax advice behind a prompt with no citation discipline at all."""
    text = _prompts()["domain/financial_analysis_service.py"]

    assert "Do not mention GST, TDS, or any tax filing" in text


@pytest.mark.parametrize("name", sorted(_prompts()))
def test_every_prompt_tells_the_model_to_admit_uncertainty(name):
    lowered = _prompts()[name].lower()

    assert "uncertain" in lowered or "unsure" in lowered or "never invent" in lowered, \
        f"{name} has no instruction to admit what it does not know"
