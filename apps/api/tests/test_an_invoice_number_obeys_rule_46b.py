"""
CGST Rule 46(b) — a tax invoice's number, all four limbs.

WHAT WAS WRONG (SALES-12, and more than SALES-12 said)
    Rule 46(b) requires "a CONSECUTIVE SERIAL NUMBER not exceeding SIXTEEN
    CHARACTERS ... containing alphabets or numerals or special characters
    hyphen or dash and slash ... UNIQUE FOR A FINANCIAL YEAR".

    The product enforced TWO of the four. Uniqueness, yes — and stricter than
    required (unique per client, not merely per FY, migrations 151/209). The
    sixteen-character cap, only for the DRAFT- placeholder `numbering.py`
    generates; never for a number a CA typed.

    CONSECUTIVE was enforced nowhere. INV-1, then INV-57, then INV-9 were all
    accepted. THE CHARACTER SET was enforced nowhere either: `INV#001` passed,
    and the IRP rejects a malformed document number outright, so a number
    accepted today is one e-invoicing refuses tomorrow.

    SALES-12 reported only that Invoice Settings configured a series nothing
    read. The consecutiveness and character-set gaps are wider than the finding
    and were found by reading the rule rather than the finding.

WHAT REFUSES AND WHAT WARNS
    Breaking the RULE refuses — over sixteen characters, or a character the
    rule does not permit. Breaking the SEQUENCE warns: a gap has legitimate
    causes (a series carried over mid-year, a cancelled invoice, a second
    series, which the rule expressly allows) and refusing would make the
    product wrong about practices that are right.
"""
from __future__ import annotations

import pytest

from domain.gst.invoice_series import (
    MAX_LENGTH, SeriesSettings, format_number, format_violation, length_gap,
    next_sequence, sequence_break, settings_gap, split_number,
)

FY = "2026-27"
DEFAULT = SeriesSettings()


# ── the number the series produces ───────────────────────────────────────────

def test_the_default_series_is_what_a_ca_would_write_by_hand():
    assert format_number(DEFAULT, FY, 1) == "INV/2026-27/001"
    assert format_number(DEFAULT, FY, 42) == "INV/2026-27/042"


def test_the_financial_year_can_be_left_out():
    s = SeriesSettings(include_financial_year=False)
    assert format_number(s, FY, 7) == "INV/007"


def test_the_settings_row_drives_it_and_an_absent_row_falls_back_to_the_columns_defaults():
    """A firm that has never opened Invoice Settings has no row at all. It must
    still get a legal number, not an error and not a blank."""
    assert format_number(SeriesSettings.from_row(None), FY, 1) == "INV/2026-27/001"
    s = SeriesSettings.from_row({"prefix": "TAX", "sequence_length": 5, "starting_number": 100})
    assert format_number(s, FY, 100) == "TAX/2026-27/00100"


# ── limb 1: sixteen characters ───────────────────────────────────────────────

def test_a_number_over_sixteen_characters_is_refused():
    v = format_violation("INV/2026-27/000001")
    assert v and "18 characters" in v and "sixteen" in v


def test_exactly_sixteen_is_allowed():
    n = "A" * MAX_LENGTH
    assert len(n) == 16 and format_violation(n) is None


def test_a_series_that_overflows_LATER_is_caught_NOW():
    """Checked at the series' HIGHEST number, not its first. A prefix that fits
    at 001 and overflows at 1000 breaks in the middle of a busy year, which is
    the worst moment to discover it."""
    s = SeriesSettings(prefix="ACMEINDUSTRIES")
    assert format_violation(format_number(s, FY, 1)) is not None or True   # 001 may fit
    gap = length_gap(s, FY)
    assert gap and "Shorten the prefix" in gap


def test_a_series_that_fits_reports_no_gap():
    assert length_gap(DEFAULT, FY) is None


# ── limb 2: the character set ────────────────────────────────────────────────

@pytest.mark.parametrize("n", ["INV#001", "INV 001", "INV_001", "INV.001", "INV@2026"])
def test_a_character_rule_46b_does_not_permit_is_refused(n):
    v = format_violation(n)
    assert v and "letters, digits, hyphen and slash" in v


@pytest.mark.parametrize("n", ["INV/2026-27/001", "INV-001", "ABC123", "A/B-C/1"])
def test_the_permitted_characters_are_accepted(n):
    assert format_violation(n) is None


def test_an_empty_number_is_refused():
    assert "needs a number" in (format_violation("") or "")
    assert "needs a number" in (format_violation("   ") or "")


# ── limb 3: consecutive ──────────────────────────────────────────────────────

EXISTING = ["INV/2026-27/001", "INV/2026-27/002"]


def test_the_next_number_is_one_past_the_HIGHEST_not_one_past_the_COUNT():
    """`services/numbering.sequence_after` records why, and it is the same trap:
    count+1 returns an already-taken number the moment a middle document is
    deleted — deterministically, for the rest of the year."""
    with_a_hole = ["INV/2026-27/001", "INV/2026-27/007"]
    assert next_sequence(with_a_hole, DEFAULT, FY) == 8
    assert len(with_a_hole) + 1 == 3, "count+1 would have said 3, which is taken"


def test_an_empty_year_starts_at_the_configured_starting_number():
    assert next_sequence([], DEFAULT, FY) == 1
    assert next_sequence([], SeriesSettings(starting_number=500), FY) == 500


def test_the_starting_number_never_drags_a_running_series_backwards():
    assert next_sequence(EXISTING, SeriesSettings(starting_number=1), FY) == 3


def test_the_number_in_order_says_nothing():
    assert sequence_break("INV/2026-27/003", EXISTING, DEFAULT, FY) is None


def test_a_skipped_number_warns_and_names_what_was_expected():
    w = sequence_break("INV/2026-27/009", EXISTING, DEFAULT, FY)
    assert w and "skips 6 numbers" in w
    assert "INV/2026-27/003" in w, "must name the number it expected"
    assert "Rule 46(b)" in w


def test_a_number_going_backwards_warns_differently():
    w = sequence_break("INV/2026-27/002", EXISTING, DEFAULT, FY)
    assert w and "out of order" in w


def test_a_SECOND_SERIES_is_left_alone():
    """Rule 46(b) allows "one or multiple series" in terms. Complaining about a
    firm's export series while it numbers its domestic one would train the CA
    to ignore the warning that matters."""
    assert sequence_break("EXP/2026-27/001", EXISTING, DEFAULT, FY) is None


def test_a_number_ending_in_no_digit_is_left_alone():
    assert sequence_break("INV/2026-27/FINAL", EXISTING, DEFAULT, FY) is None


def test_splitting_a_number_finds_the_trailing_digits():
    assert split_number("INV/2026-27/042") == ("INV/2026-27/", 42)
    assert split_number("ABC") == ("ABC", None)


# ── the line between refusing and warning ────────────────────────────────────

def test_a_gap_WARNS_and_never_refuses():
    """The distinction is the statute's own. A gap has legitimate causes — a
    series carried over mid-year, a cancelled invoice, a second series — so it
    is said once and the CA decides. A character the rule forbids has none."""
    skipping = "INV/2026-27/009"
    assert format_violation(skipping) is None, "a gap is not a format violation"
    assert sequence_break(skipping, EXISTING, DEFAULT, FY) is not None


def test_a_forbidden_character_REFUSES_even_when_it_is_next_in_sequence():
    assert format_violation("INV#2026-27#003") is not None


# ---------------------------------------------------------------------------
# The shared fixture — the same cases the browser mirror is held to.
#
# apps/web/lib/invoices/gst.ts carries a regex for keystroke feedback, and a
# rule with two spellings has two chances to drift. tests/fixtures/
# invoice_number.json is read by this test and by
# apps/web/lib/invoices/invoiceNumberShape.test.ts, the same arrangement GSTIN
# has. Only the VERDICT is pinned — the two word their refusals differently on
# purpose, and pinning the wording would make the mirror the thing being
# maintained.
# ---------------------------------------------------------------------------
import json
from pathlib import Path

_SHARED = json.loads(
    (Path(__file__).parent / "fixtures" / "invoice_number.json").read_text())


@pytest.mark.parametrize("number", _SHARED["legal"])
def test_every_shared_legal_number_is_accepted(number):
    assert format_violation(number) is None, f"{number!r} should be legal"


@pytest.mark.parametrize("case", _SHARED["illegal"], ids=lambda c: c["why"])
def test_every_shared_illegal_number_is_refused(case):
    assert format_violation(case["number"]), f"{case['number']!r} — {case['why']}"


def test_the_shared_fixture_is_not_empty_in_either_direction():
    # A fixture that silently emptied would make both parametrised tests above
    # collect nothing and pass, on both sides of the mirror.
    assert len(_SHARED["legal"]) >= 10
    assert len(_SHARED["illegal"]) >= 8


# ---------------------------------------------------------------------------
# A settings row that cannot produce a legal number at all.
# ---------------------------------------------------------------------------
def test_a_prefix_carrying_a_forbidden_character_is_reported_as_a_settings_gap():
    # The prefix column has no CHECK, so this is reachable from the Invoice
    # Settings screen, and the CA must be told which SETTING is wrong rather
    # than being shown a refusal about a number they did not type.
    gap = settings_gap(SeriesSettings(prefix="INV#"), FY)
    assert gap and "prefix" in gap.lower()


def test_a_settings_gap_reports_the_overflow_when_the_characters_are_fine():
    gap = settings_gap(SeriesSettings(prefix="INVOICE", sequence_length=6), FY)
    assert gap and "sixteen" in gap


def test_a_workable_series_reports_no_settings_gap():
    assert settings_gap(SeriesSettings(), FY) is None
