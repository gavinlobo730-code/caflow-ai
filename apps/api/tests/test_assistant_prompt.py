"""
/api/assistant — the system prompt's contract with the code that parses its output.

WHY THIS EXISTS
    The prompt was ported from a dead frontend route (removed in #220) that had
    a much richer domain brief. The two artefacts had DIFFERENT output contracts:
    this endpoint splits the model's reply on a trailing "Source:" marker to
    populate the `source` field, and the frontend prompt never asked for one.

    Porting it verbatim would have blanked `source` on every answer — with no
    error anywhere, because an answer without the marker is handled by the
    `else` branch as "the whole reply is the answer". A prompt and a parser that
    disagree is exactly the kind of break that ships.

WHAT THIS DOES NOT DO
    It cannot check that the tax figures are RIGHT — that needs a CA and the
    current Finance Act, and is why the prompt attributes rates to their source
    Act rather than asserting them for an unverified year. What it does check is
    that the caveat survives, since deleting it is the easy edit that makes the
    endpoint confidently wrong.
"""
import re

import pytest

from routers import assistant


# ── The parser contract ──────────────────────────────────────────────────────

def test_the_prompt_demands_the_source_line_the_parser_looks_for():
    """`source` is populated by rsplit on this exact marker. If the prompt stops
    asking for it, every answer silently loses its citation field."""
    assert "Source: [Act name], Section [number]" in assistant.SYSTEM_PROMPT


def test_the_prompt_says_the_marker_must_be_last_and_appear_once():
    """The parser uses rsplit, so a stray earlier "Source:" would put half the
    answer into the source field. Both constraints have to be stated."""
    prompt = assistant.SYSTEM_PROMPT.lower()

    assert "never omit it" in prompt
    assert "never place anything after it" in prompt
    assert "never use the word" in prompt and "anywhere earlier" in prompt


def test_a_well_formed_reply_round_trips_through_the_parser():
    answer, source = assistant.split_source(
        "GSTR-1 is due on the 11th of the following month.\n"
        "Source: CGST Act, Section 37")

    assert answer == "GSTR-1 is due on the 11th of the following month."
    assert source == "Source: CGST Act, Section 37"


def test_the_citation_keeps_its_space_after_the_colon():
    """Regression: the split strips the model's space and the rebuild used to
    omit it, so every citation rendered as "Source:CGST Act, Section 37"."""
    _, source = assistant.split_source("Answer.\nSource:   IT Act, Section 139")

    assert source == "Source: IT Act, Section 139"


def test_a_reply_without_the_marker_degrades_to_an_empty_source():
    """Documents the cost of the prompt drifting: no crash, no error, just a
    quietly missing citation. This is why the contract is asserted above."""
    answer, source = assistant.split_source("GSTR-1 is due on the 11th.")

    assert answer == "GSTR-1 is due on the 11th."
    assert source == ""


def test_only_the_last_marker_splits_the_reply():
    """rsplit, not split. A reply that discusses the word earlier must not have
    its answer carved in half — the prompt forbids that, but the parser should
    not depend on the model obeying."""
    answer, source = assistant.split_source(
        "Source: fields are cited below.\nMore text.\nSource: CGST Act, Section 37")

    assert answer == "Source: fields are cited below.\nMore text."
    assert source == "Source: CGST Act, Section 37"


# ── Domain content that was the point of the port ────────────────────────────

@pytest.mark.parametrize("fact", [
    "GSTR-1", "GSTR-3B", "GSTR-9", "GSTR-2B", "E-invoicing",
    "194C", "194J", "194A", "194I", "194Q", "24Q/26Q",
    "ADVANCE TAX", "AOC-4", "MGT-7", "DIR-3 KYC", "ADT-1",
])
def test_the_ported_domain_brief_survived(fact):
    """The port existed to move this content. If a later edit trims the prompt
    back to a few lines, that is a silent regression in answer quality."""
    assert fact in assistant.SYSTEM_PROMPT


@pytest.mark.parametrize("due", [
    ("GSTR-1", "11th"),
    ("GSTR-3B", "20th"),
    ("GSTR-9", "31st December"),
])
def test_the_gst_due_dates_match_the_project_rules(due):
    """CLAUDE.md fixes these. A prompt that contradicts the rules the rest of the
    codebase enforces would have the AI disagree with the app's own compliance
    calendar."""
    form, date = due
    line = next(ln for ln in assistant.SYSTEM_PROMPT.splitlines() if ln.startswith(f"- {form}"))

    assert date in line


def test_advance_tax_instalments_are_the_statutory_ones():
    for when, pct in (("15 June", "15%"), ("15 September", "45%"),
                      ("15 December", "75%"), ("15 March", "100%")):
        assert f"{when} {pct}" in assistant.SYSTEM_PROMPT


def test_the_q4_tds_exception_is_called_out_not_just_listed():
    """31 May is the one quarter that breaks the "month after quarter end"
    pattern — Q4 ends 31 March, so the pattern would suggest 30 April. Listing
    it without flagging it invites the model to "correct" it by analogy."""
    assert "31 May (Q4)" in assistant.SYSTEM_PROMPT
    assert "NOT 30 April" in assistant.SYSTEM_PROMPT


# ── The caveat that keeps a stale rate from being stated as current ──────────

def test_rates_are_attributed_to_the_act_that_set_them():
    """Not to a financial year they were assumed to carry into. The original
    frontend prompt was headed "KEY FACTS FOR FY 2026-27" over Finance Act 2025
    figures, which is an assumption dressed as a fact."""
    assert "Finance Act 2025" in assistant.SYSTEM_PROMPT
    assert "FY 2025-26 / AY 2026-27" in assistant.SYSTEM_PROMPT


def test_the_model_is_told_to_flag_a_later_year_rather_than_answer_for_it():
    prompt = assistant.SYSTEM_PROMPT

    assert "LATER" in prompt
    assert "subsequent Finance Act may have amended them" in prompt
    assert "Do not restate them as current for a year you cannot verify" in prompt


def test_no_slab_table_is_labelled_with_an_unverified_forward_year():
    """The specific regression to prevent: re-heading the rate block with a
    financial year later than the Act it came from."""
    for bad in ("FY 2026-27", "AY 2027-28", "FY 2027-28"):
        assert bad not in assistant.SYSTEM_PROMPT, \
            f"prompt asserts rates for {bad}, which no cited Act here establishes"


# ── Guard rails that predate the port and must not be lost in it ─────────────

def test_the_do_not_guess_instruction_survived():
    prompt = assistant.SYSTEM_PROMPT.lower()

    assert "never guess" in prompt
    assert "unsure" in prompt


def test_filing_answers_still_carry_the_ca_review_instruction():
    assert "Please have your CA review before filing." in assistant.SYSTEM_PROMPT


def test_the_endpoint_still_sends_no_client_data():
    """This router has no mount-level client guard, so the prompt must stay a
    STATIC brief. If it ever gains a format placeholder, someone is about to
    interpolate client context into a prompt nothing scopes."""
    assert not re.search(r"\{[a-z_]+\}", assistant.SYSTEM_PROMPT), \
        "prompt has a format placeholder — see the client_id note in this router"
