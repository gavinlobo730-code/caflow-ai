"""The rule for a narration template's words (POST-A-093): what is stored, what is refused, and when two say the same thing.

The behaviour of the store and its routes is in `test_a_client_keeps_narration_templates_for_its_journals.py`; this file holds the pure
rule, which needs no database.
"""
from __future__ import annotations

import pytest

from domain.accounting import narration_templates as rule


@pytest.mark.parametrize("given,stored", [
    ("Being salary payable for the month", "Being salary payable for the month"),
    ("  Being  salary\tpayable \n for the month  ", "Being salary payable for the month"),
    ("Being\r\nrent", "Being rent"),
    (None, ""),
])
def test_the_words_are_stored_trimmed_with_one_space_between_them(given, stored):
    assert rule.normalise(given) == stored


@pytest.mark.parametrize("given,says", [
    ("", "needs some words"),
    ("   \n\t ", "needs some words"),
    (None, "needs some words"),
    ("x" * (rule.MAX_LENGTH + 1), f"at most {rule.MAX_LENGTH} characters; this one is {rule.MAX_LENGTH + 1}"),
    ("Being rent\x00", "control character"),
    ("\u200b\u200b", "needs some words"),                         # invisible characters only: a template that looks blank
    ("Being rent \u202epaid", "control character"),                # a direction control: text that reads otherwise than it stores
])
def test_words_that_cannot_be_a_template_are_refused_in_a_sentence(given, says):
    assert says in (rule.problem(given) or "")


def test_words_at_the_limit_and_ordinary_punctuation_are_accepted():
    assert rule.problem("x" * rule.MAX_LENGTH) is None
    assert rule.problem("Being depreciation @ 15% (WDV) on plant & machinery — Q1, FY 2026-27") is None
    assert rule.problem("  " + "x" * rule.MAX_LENGTH + "  ") is None        # the length is the stored words', not the typed ones'


def test_a_joiner_that_an_indian_script_needs_is_not_refused():
    assert rule.problem("\u0915\u094d\u200d\u0937 \u0915\u093e \u092d\u0941\u0917\u0924\u093e\u0928") is None   # a ZWJ inside Devanagari


def test_the_key_is_the_normalised_words_case_folded_and_is_what_same_words_compares():
    assert rule.key("  Being  SALARY payable ") == "being salary payable"
    assert rule.key("STRASSE") == rule.key("straße")              # casefold, which the stored key carries to the database's index
    assert rule.same_words("İx rent", "İx rent") and not rule.same_words("İx rent", "Ix rent")


def test_two_templates_are_the_same_when_their_words_match_ignoring_case_and_spacing():
    assert rule.same_words("Being salary payable", "  being SALARY   payable ")
    assert not rule.same_words("Being salary payable", "Being salary paid")
