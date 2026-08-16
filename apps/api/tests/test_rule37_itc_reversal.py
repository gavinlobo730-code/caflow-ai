"""
Rule 37 — the arithmetic, and the parts of it that are judgement calls.

CGST Act §16(2) second proviso and Rule 37: input tax credit taken on an inward
supply is reversed, proportionate to the amount not paid, when the supplier goes
unpaid for 180 days from the invoice date. Reversal goes in the return for the
tax period immediately FOLLOWING the one the 180 days expire in, with interest
under §50. Rule 37(4) allows re-availment when payment is eventually made.

Two things in this module are interpretations rather than arithmetic, and both
are pinned here so a change to either is deliberate and visible:

  * TDS deducted at source counts as paid to the supplier
  * the proportionate figure rounds UP
"""
from __future__ import annotations

from datetime import date

import pytest

from domain.gst.itc_reversal import (
    RULE37_DAYS, days_outstanding, discharged_paise, is_overdue, parse_iso,
    payment_due_by, reversal_for_bill, reversal_period, unpaid_paise,
)

JAN1 = date(2026, 1, 1)


# ── the 180-day clock ────────────────────────────────────────────────────────

def test_the_window_is_180_days_from_the_invoice_date():
    assert RULE37_DAYS == 180
    assert payment_due_by(JAN1) == date(2026, 6, 30)


def test_the_bill_is_not_overdue_on_the_last_day_of_the_window():
    """Day 180 is still in time — the reversal is for a failure to pay WITHIN
    180 days, so the deadline day itself is not a breach."""
    assert is_overdue(JAN1, date(2026, 6, 30)) is False
    assert is_overdue(JAN1, date(2026, 7, 1)) is True


def test_the_clock_runs_from_the_invoice_date_not_the_due_date():
    assert days_outstanding(JAN1, date(2026, 7, 1)) == 181
    assert days_outstanding(JAN1, JAN1) == 0


def test_a_future_dated_bill_is_not_overdue():
    assert is_overdue(date(2026, 12, 1), JAN1) is False


def test_the_window_spans_a_leap_day_correctly():
    """180 calendar days, not six months. 2028 is a leap year, so a bill dated
    1 January 2028 falls due a day earlier in the month than a common year."""
    assert payment_due_by(date(2028, 1, 1)) == date(2028, 6, 29)
    assert payment_due_by(date(2027, 1, 1)) == date(2027, 6, 30)


# ── which return the reversal belongs in ─────────────────────────────────────

def test_the_reversal_goes_in_the_month_after_the_window_expires():
    """Rule 37(1): the period IMMEDIATELY FOLLOWING the one the 180 days expire
    in. Filing it against the bill's own month, or against the expiry month, is
    the usual way this goes wrong."""
    assert payment_due_by(JAN1) == date(2026, 6, 30)   # expires in June
    assert reversal_period(JAN1) == "072026"           # reported in July


def test_the_reversal_period_rolls_into_the_next_calendar_year():
    assert payment_due_by(date(2026, 6, 20)) == date(2026, 12, 17)
    assert reversal_period(date(2026, 6, 20)) == "012027"


# ── what counts as paid ──────────────────────────────────────────────────────

def test_tds_deducted_at_source_counts_as_paid_to_the_supplier():
    """An interpretation, and the one most likely to change a filed number. TDS
    is remitted to the government on the supplier's behalf and credited to them,
    so the supply is settled even though less cash moved. Treating it as unpaid
    would reverse credit on a bill that is in substance paid."""
    # 1,00,000 bill, 10,000 TDS, 90,000 cash paid — nothing is outstanding.
    assert unpaid_paise(100_000_00, paid_paise=90_000_00, tds_paise=10_000_00) == 0


def test_without_the_tds_allowance_the_same_bill_would_look_unpaid():
    """Pins the size of the interpretation: ignore TDS and this bill reverses
    credit it should not."""
    assert unpaid_paise(100_000_00, paid_paise=90_000_00, tds_paise=0) == 10_000_00


def test_an_overpayment_is_not_a_negative_liability():
    assert unpaid_paise(100_000_00, paid_paise=120_000_00) == 0
    assert discharged_paise(paid_paise=-5, tds_paise=0) == 0


# ── the proportionate reversal ───────────────────────────────────────────────

def test_a_wholly_unpaid_bill_reverses_all_of_its_credit():
    r = reversal_for_bill(total_paise=118_000_00, paid_paise=0,
                          cgst_paise=9_000_00, sgst_paise=9_000_00)

    assert r["unpaid_paise"] == 118_000_00
    assert r["cgst_paise"] == 9_000_00
    assert r["sgst_paise"] == 9_000_00
    assert r["total_paise"] == 18_000_00


def test_a_fully_paid_bill_reverses_nothing():
    r = reversal_for_bill(total_paise=118_000_00, paid_paise=118_000_00,
                          cgst_paise=9_000_00, sgst_paise=9_000_00)

    assert r == {"unpaid_paise": 0, "cgst_paise": 0, "sgst_paise": 0,
                 "igst_paise": 0, "total_paise": 0}


def test_a_half_paid_bill_reverses_half_the_credit():
    """Rule 37(1) is proportionate, not all-or-nothing."""
    r = reversal_for_bill(total_paise=118_000_00, paid_paise=59_000_00,
                          cgst_paise=9_000_00, sgst_paise=9_000_00)

    assert r["unpaid_paise"] == 59_000_00
    assert r["cgst_paise"] == 4_500_00
    assert r["sgst_paise"] == 4_500_00


def test_each_tax_head_is_reversed_in_its_own_right():
    """GSTR-3B table 4(B) reports IGST, CGST and SGST separately, so they have
    to add up per head rather than being carved out of one combined figure."""
    r = reversal_for_bill(total_paise=118_000_00, paid_paise=0, igst_paise=18_000_00)

    assert r["igst_paise"] == 18_000_00
    assert r["cgst_paise"] == 0 and r["sgst_paise"] == 0
    assert r["total_paise"] == 18_000_00


def test_the_proportionate_figure_rounds_up():
    """The other interpretation. Under-reversing leaves a shortfall carrying
    interest under §50; over-reversing is re-availed under Rule 37(4) as soon as
    the supplier is paid. So a fraction of a paisa rounds up.

    1/3 of 100 paise is 33.33; this reverses 34.
    """
    r = reversal_for_bill(total_paise=300, paid_paise=200, cgst_paise=100)

    assert r["unpaid_paise"] == 100
    assert r["cgst_paise"] == 34


def test_rounding_never_reverses_more_credit_than_was_taken():
    """The ceiling must not overshoot the credit itself — reversing 101 paise of
    a 100 paise credit would be arithmetic nobody could reconcile."""
    r = reversal_for_bill(total_paise=100, paid_paise=0, cgst_paise=100)

    assert r["cgst_paise"] == 100


def test_no_credit_means_nothing_to_reverse():
    """An exempt or non-GST purchase carries no ITC, so 180 days of non-payment
    changes nothing about the return."""
    r = reversal_for_bill(total_paise=100_000_00, paid_paise=0)

    assert r["total_paise"] == 0


def test_a_zero_value_bill_does_not_divide_by_zero():
    r = reversal_for_bill(total_paise=0, paid_paise=0, cgst_paise=500)

    assert r["total_paise"] == 0


def test_every_amount_stays_an_integer_number_of_paise():
    """CLAUDE.md: integer paise throughout, never floating point. A float would
    survive most of these assertions and fail on a bill nobody tested."""
    r = reversal_for_bill(total_paise=118_000_01, paid_paise=37_000_07,
                          cgst_paise=9_000_03, sgst_paise=9_000_03,
                          igst_paise=11, tds_paise=13)

    for key, value in r.items():
        assert isinstance(value, int), f"{key} is {type(value).__name__}, not int"


# ── parsing what the database returns ────────────────────────────────────────

def test_dates_arrive_as_strings_and_parse():
    assert parse_iso("2026-01-01") == JAN1
    assert parse_iso("2026-01-01T00:00:00Z") == JAN1


def test_a_missing_or_unusable_date_is_none_rather_than_a_crash():
    for bad in [None, "", "not-a-date", "2026-13-01"]:
        assert parse_iso(bad) is None
