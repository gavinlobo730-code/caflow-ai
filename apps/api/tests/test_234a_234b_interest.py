"""
Interest under §234A and §234B — the two the engine was missing.

§234C was already implemented, and carefully: the 12/36/75/100 trigger
tolerances, the fixed 3/3/3/1-month periods, integer paise. Its module header
records that it exists because the frontend had computed §234C using an
actual-delay formula, which is §234B's shape, not §234C's. §234A and §234B
themselves were absent.

The three sections share one rate and one rounding convention — 1% per month or
part, integer paise — which is why they now live together. What they do NOT
share is the shape:

  §234A  from the day AFTER the §139(1) due date to the date the return is
         furnished, on tax net of TDS, advance tax and relief.
  §234B  from 1 APRIL OF THE ASSESSMENT YEAR to the date of assessment, on the
         shortfall, and only where advance tax plus TDS is BELOW 90% of
         assessed tax.
  §234C  fixed notional periods per instalment, regardless of actual delay.
"""
from datetime import date

import pytest

from domain.income_tax.advance_tax_interest_engine import (
    _months_or_part, compute_234a_interest, compute_234b_interest,
)

L = 1_00_000_00        # one lakh, in paise


# ── The shared month convention ──────────────────────────────────────────────

def test_a_part_month_counts_as_a_whole_month():
    """"Every month or part of a month" — one day past a month boundary is a
    second month, not a thirtieth of one."""
    assert _months_or_part(date(2026, 4, 1), date(2026, 5, 1)) == 1
    assert _months_or_part(date(2026, 4, 1), date(2026, 5, 2)) == 2


def test_a_period_of_days_is_one_month_not_nil():
    assert _months_or_part(date(2026, 4, 1), date(2026, 4, 2)) == 1


def test_no_months_accrue_before_the_period_starts():
    """A return filed early must not earn negative interest."""
    assert _months_or_part(date(2026, 7, 31), date(2026, 7, 1)) == 0
    assert _months_or_part(date(2026, 7, 31), date(2026, 7, 31)) == 0


# ── §234A ────────────────────────────────────────────────────────────────────

def test_234a_charges_one_percent_a_month_on_tax_net_of_credits():
    """31 July to 15 November is four months or parts. 4% of 4,00,000."""
    r = compute_234a_interest(
        tax_on_total_income_paise=5 * L, tds_tcs_paise=1 * L,
        due_date=date(2026, 7, 31), return_furnished_on=date(2026, 11, 15))
    assert r.applies is True
    assert r.months == 4
    assert r.base_paise == 4 * L
    assert r.interest_paise == 4 * L * 4 // 100


def test_234a_nets_off_advance_tax_and_relief_too():
    r = compute_234a_interest(
        tax_on_total_income_paise=10 * L, tds_tcs_paise=2 * L,
        advance_tax_paid_paise=3 * L, relief_paise=1 * L,
        due_date=date(2026, 7, 31), return_furnished_on=date(2026, 8, 31))
    assert r.base_paise == 4 * L


def test_234a_does_not_arise_on_a_return_filed_by_the_due_date():
    r = compute_234a_interest(
        tax_on_total_income_paise=5 * L, due_date=date(2026, 7, 31),
        return_furnished_on=date(2026, 7, 31))
    assert r.applies is False
    assert r.interest_paise == 0


def test_234a_charges_nothing_where_credits_cover_the_tax():
    """The delay itself is not what is taxed — §234A charges interest on an
    unpaid AMOUNT, and a taxpayer whose TDS covers their liability owes none
    however late they file."""
    r = compute_234a_interest(
        tax_on_total_income_paise=5 * L, tds_tcs_paise=6 * L,
        due_date=date(2026, 7, 31), return_furnished_on=date(2027, 3, 31))
    assert r.applies is False
    assert r.base_paise == 0
    assert any("not what is taxed" in x for x in r.reasons)


def test_an_unfiled_return_still_accrues_to_the_assessment_date():
    """Reporting nil for a return not yet furnished would tell a CA the
    cheapest moment to file is never."""
    r = compute_234a_interest(
        tax_on_total_income_paise=5 * L, due_date=date(2026, 7, 31),
        return_furnished_on=None, assessment_date=date(2027, 1, 31))
    assert r.applies is True
    assert r.months == 6


def test_an_unfiled_return_with_no_assessment_date_says_interest_is_running():
    r = compute_234a_interest(
        tax_on_total_income_paise=5 * L, due_date=date(2026, 7, 31),
        return_furnished_on=None)
    assert r.applies is False
    assert any("still running" in x for x in r.reasons)


# ── §234B ────────────────────────────────────────────────────────────────────

def test_234b_charges_the_shortfall_from_the_first_of_april():
    """1 April 2026 to 15 November 2026 is eight months or parts. The period
    starts at the ASSESSMENT year, not at the financial year end."""
    r = compute_234b_interest(
        assessed_tax_paise=10 * L, advance_tax_paid_paise=5 * L,
        assessment_year_start=date(2026, 4, 1), assessment_date=date(2026, 11, 15))
    assert r.applies is True
    assert r.months == 8
    assert r.base_paise == 5 * L
    assert r.interest_paise == 5 * L * 8 // 100


def test_exactly_ninety_percent_is_compliant_not_marginally_in_default():
    """The gate most easily missed. A taxpayer who has paid 90.0% owes no
    §234B at all — treating the threshold as a floor to clear rather than a
    line not to fall below charges interest to people who owe none."""
    r = compute_234b_interest(
        assessed_tax_paise=10 * L, advance_tax_paid_paise=9 * L,
        assessment_year_start=date(2026, 4, 1), assessment_date=date(2026, 11, 15))
    assert r.applies is False
    assert r.interest_paise == 0


def test_a_paise_below_ninety_percent_triggers_the_charge():
    r = compute_234b_interest(
        assessed_tax_paise=10 * L, advance_tax_paid_paise=9 * L - 1,
        assessment_year_start=date(2026, 4, 1), assessment_date=date(2026, 11, 15))
    assert r.applies is True
    # And once triggered it is charged on the WHOLE shortfall, not on the
    # amount by which the 90% line was missed.
    assert r.base_paise == 10 * L - (9 * L - 1)


def test_tds_counts_towards_the_ninety_percent():
    """Advance tax and TDS are added before the test. Ignoring TDS would put
    every salaried taxpayer with a small other-income liability into default."""
    r = compute_234b_interest(
        assessed_tax_paise=10 * L, advance_tax_paid_paise=1 * L,
        tds_tcs_paise=8 * L,
        assessment_year_start=date(2026, 4, 1), assessment_date=date(2026, 11, 15))
    assert r.applies is False


def test_no_assessed_tax_means_no_interest():
    r = compute_234b_interest(
        assessed_tax_paise=0, assessment_year_start=date(2026, 4, 1),
        assessment_date=date(2026, 11, 15))
    assert r.applies is False


# ── The three sections stay distinct ─────────────────────────────────────────

def test_234a_and_234b_run_over_different_periods_on_the_same_facts():
    """Same year, same taxpayer: §234A runs from the July due date, §234B from
    1 April. Conflating them — which is the mistake this module's header
    records the frontend having made for §234C — changes the interest by
    months."""
    a = compute_234a_interest(
        tax_on_total_income_paise=10 * L, advance_tax_paid_paise=5 * L,
        due_date=date(2026, 7, 31), return_furnished_on=date(2026, 11, 15))
    b = compute_234b_interest(
        assessed_tax_paise=10 * L, advance_tax_paid_paise=5 * L,
        assessment_year_start=date(2026, 4, 1), assessment_date=date(2026, 11, 15))
    assert a.months == 4
    assert b.months == 8
    assert a.from_date == date(2026, 7, 31)
    assert b.from_date == date(2026, 4, 1)


def test_every_amount_is_integer_paise():
    r = compute_234b_interest(
        assessed_tax_paise=1_23_45_678, advance_tax_paid_paise=12_345,
        assessment_year_start=date(2026, 4, 1), assessment_date=date(2026, 9, 7))
    for v in (r.base_paise, r.interest_paise, r.months):
        assert isinstance(v, int)


def test_234b_starts_on_the_first_of_april_not_the_last_of_march():
    """The start date is 1 APRIL of the assessment year. Starting a day earlier
    — at the financial year end — is the natural-looking slip, and for most end
    dates it gives the SAME month count, which is why it survives casual
    testing: from 1 April, any end day past the 1st adds a part-month; from 31
    March it does not, and the two cancel.

    They diverge only when the period ends on the 1st of a month. Then 31 March
    counts an extra whole month the section does not charge."""
    end = date(2026, 11, 1)
    correct = compute_234b_interest(
        assessed_tax_paise=10 * L, advance_tax_paid_paise=5 * L,
        assessment_year_start=date(2026, 4, 1), assessment_date=end)
    assert correct.months == 7, (
        "1 April to 1 November is seven months or parts"
    )
    # What starting at the FY end would have produced, computed directly.
    assert _months_or_part(date(2026, 3, 31), end) == 8
    assert correct.interest_paise == 5 * L * 7 // 100
