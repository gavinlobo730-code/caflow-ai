"""Monthly is not the only GST regime, and it was the only one the code knew.

WHAT WAS WRONG
    clients.gst_filing_frequency has existed since migration 001. It accepts
    'monthly' or 'quarterly', it is on the client form, and it is printed on the
    client Overview page. Nothing anywhere read it.

        def gstr1_due_date(y, m):  return nth_of_month(ny, nm, 11)
        def gstr3b_due_date(y, m): return nth_of_month(ny, nm, 20)

    So every client — including one explicitly marked quarterly — was quoted the
    monthly 11th and 20th, seeded twelve GSTR-1s and twelve GSTR-3Bs a year, and
    never told about PMT-06 at all.

WHY IT MATTERS RATHER THAN BEING A DISPLAY BUG
    QRMP (Rule 61A, Notifications 82/84/85-2020-Central Tax, live 01-01-2021) is
    open to anyone whose preceding-year aggregate turnover was up to Rs 5 crore,
    which is most small Indian business. It is NOT the same return three times
    less often:

        GSTR-1    13th of the month after the QUARTER
        GSTR-3B   22nd or 24th of that month, decided by the STATE
        PMT-06    25th monthly, for months 1 and 2 — tax is still paid monthly
        IFF       optional, months 1 and 2, B2B only, by the 13th

    Section 47 charges Rs 50 a day for filing late. A due date that is wrong in
    the generous direction is a penalty, which is why an unknown state resolves
    to the EARLIER of the two GSTR-3B dates rather than the later one.

WHAT IS ASSERTED
    The dates themselves; that the monthly path is untouched (every existing
    caller passes no frequency and must keep getting 11th/20th); the state split
    in both directions; and that a quarterly client is generated a DIFFERENT SET
    of obligations, not a thinner one.
"""
from __future__ import annotations

from datetime import date

import pytest

from services import compliance_engine as ce
from services.compliance_obligation_service import _gst_obligations, fy_quarters


# ── The monthly path must not move ──────────────────────────────────────────

def test_monthly_is_unchanged_and_is_still_the_default():
    """Every existing caller passes no frequency. If the default ever flips,
    every monthly client silently gets QRMP dates."""
    assert ce.gstr1_due_date(2026, 4) == date(2026, 5, 11)
    assert ce.gstr3b_due_date(2026, 4) == date(2026, 5, 20)
    assert ce.gstr1_due_date(2026, 12) == date(2027, 1, 11)
    assert ce.gstr3b_due_date(2026, 12) == date(2027, 1, 20)
    # Explicitly monthly gives the same answer as the default.
    assert ce.gstr1_due_date(2026, 4, ce.MONTHLY) == ce.gstr1_due_date(2026, 4)
    assert ce.gstr3b_due_date(2026, 4, ce.MONTHLY) == ce.gstr3b_due_date(2026, 4)
    # A monthly filer's GSTR-3B date does not depend on their state.
    assert ce.gstr3b_due_date(2026, 4, ce.MONTHLY, "27") == date(2026, 5, 20)
    assert ce.gstr3b_due_date(2026, 4, ce.MONTHLY, "07") == date(2026, 5, 20)


# ── Quarters ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("month,expected_end", [
    (4, 6), (5, 6), (6, 6),       # Q1 Apr-Jun
    (7, 9), (8, 9), (9, 9),       # Q2 Jul-Sep
    (10, 12), (11, 12), (12, 12), # Q3 Oct-Dec
    (1, 3), (2, 3), (3, 3),       # Q4 Jan-Mar
])
def test_every_month_maps_to_the_right_quarter_end(month, expected_end):
    assert ce.gst_quarter_end_month(month) == expected_end


@pytest.mark.parametrize("month,position", [
    (4, 1), (5, 2), (6, 3),
    (7, 1), (8, 2), (9, 3),
    (10, 1), (11, 2), (12, 3),
    (1, 1), (2, 2), (3, 3),
])
def test_every_month_knows_where_it_sits_in_its_quarter(month, position):
    """PMT-06 is owed in months 1 and 2 and not in month 3, so this is what
    decides whether a challan exists at all."""
    assert ce.gst_period_month_in_quarter(month) == position


# ── QRMP due dates ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("y,m,expected", [
    (2026, 4, date(2026, 7, 13)),   # any month of Q1 -> 13 Jul
    (2026, 5, date(2026, 7, 13)),
    (2026, 6, date(2026, 7, 13)),
    (2026, 9, date(2026, 10, 13)),  # Q2 -> 13 Oct
    (2026, 12, date(2027, 1, 13)),  # Q3 ends in December, so the year rolls
    (2027, 1, date(2027, 4, 13)),   # Q4 Jan-Mar -> 13 Apr
    (2027, 3, date(2027, 4, 13)),
])
def test_quarterly_gstr1_is_the_13th_after_the_quarter(y, m, expected):
    assert ce.gstr1_due_date(y, m, ce.QUARTERLY) == expected


def test_quarterly_gstr3b_is_the_22nd_in_category_x():
    """Maharashtra (27), Karnataka (29), Tamil Nadu (33), Gujarat (24)."""
    for code in ("27", "29", "33", "24", "22", "37"):
        assert ce.gstr3b_due_date(2026, 4, ce.QUARTERLY, code) == date(2026, 7, 22), code
        assert ce.gst_state_category(code) == "X"


def test_quarterly_gstr3b_is_the_24th_in_category_y():
    """Delhi (07), UP (09), West Bengal (19), J&K (01), Ladakh (38)."""
    for code in ("07", "09", "19", "01", "21", "38"):
        assert ce.gstr3b_due_date(2026, 4, ce.QUARTERLY, code) == date(2026, 7, 24), code
        assert ce.gst_state_category(code) == "Y"


def test_the_two_categories_partition_every_real_state_code():
    """A code in neither set, or in both, would silently take the fallback."""
    assert not (ce.GST_STATE_CATEGORY_X & ce.GST_STATE_CATEGORY_Y)
    covered = ce.GST_STATE_CATEGORY_X | ce.GST_STATE_CATEGORY_Y
    for n in range(1, 39):
        assert f"{n:02d}" in covered, f"state code {n:02d} belongs to neither group"


def test_an_unknown_state_gets_the_earlier_date_and_says_so():
    """Being early costs nothing. Being late is Rs 50 a day under §47, so the
    guess must never be the generous one — and gst_state_category returning
    None is how the screen knows to label the date as assumed."""
    for unknown in (None, "", "  ", "99", "97"):
        assert ce.gst_state_category(unknown) is None
        assert ce.gstr3b_due_date(2026, 4, ce.QUARTERLY, unknown) == date(2026, 7, 22)


# ── PMT-06 and IFF ──────────────────────────────────────────────────────────

def test_pmt06_is_due_in_the_first_two_months_of_a_quarter_and_not_the_third():
    assert ce.pmt06_due_date(2026, 4) == date(2026, 5, 25)   # Q1 month 1
    assert ce.pmt06_due_date(2026, 5) == date(2026, 6, 25)   # Q1 month 2
    assert ce.pmt06_due_date(2026, 6) is None                # paid with the return
    assert ce.pmt06_due_date(2027, 1) == date(2027, 2, 25)
    assert ce.pmt06_due_date(2027, 3) is None


def test_iff_is_offered_in_the_same_two_months():
    assert ce.iff_due_date(2026, 4) == date(2026, 5, 13)
    assert ce.iff_due_date(2026, 6) is None


# ── A quarterly client owes a different SET, not a thinner one ──────────────

def test_a_monthly_client_owes_twelve_of_each_and_no_challans():
    specs = _gst_obligations("2026-27", ce.MONTHLY)
    kinds = [s["obligation_type"] for s in specs]
    assert kinds.count("GSTR1") == 12
    assert kinds.count("GSTR3B") == 12
    assert kinds.count("PMT06") == 0
    assert kinds.count("GSTR9") == 1


def test_a_quarterly_client_owes_four_of_each_and_eight_challans():
    """Twelve monthly returns for a QRMP filer puts eight deadlines in their
    calendar that do not exist, and omits the eight that do."""
    specs = _gst_obligations("2026-27", ce.QUARTERLY, "27")
    kinds = [s["obligation_type"] for s in specs]
    assert kinds.count("GSTR1") == 4
    assert kinds.count("GSTR3B") == 4
    assert kinds.count("PMT06") == 8
    assert kinds.count("GSTR9") == 1


def test_the_quarterly_periods_are_the_quarters_not_the_months():
    specs = [s for s in _gst_obligations("2026-27", ce.QUARTERLY, "27")
             if s["obligation_type"] == "GSTR3B"]
    assert [(s["period_start"], s["period_end"]) for s in specs] == [
        ("2026-04-01", "2026-06-30"),
        ("2026-07-01", "2026-09-30"),
        ("2026-10-01", "2026-12-31"),
        ("2027-01-01", "2027-03-31"),
    ]
    assert [s["due_date"] for s in specs] == [
        "2026-07-22", "2026-10-22", "2027-01-22", "2027-04-22",
    ]


def test_the_state_reaches_the_generated_obligations():
    """The negative control for the fixture above: a Delhi client's quarterly
    3B is the 24th, so if state_code were dropped on the way through, every
    quarterly client would silently be given Maharashtra's date."""
    delhi = [s["due_date"] for s in _gst_obligations("2026-27", ce.QUARTERLY, "07")
             if s["obligation_type"] == "GSTR3B"]
    assert delhi == ["2026-07-24", "2026-10-24", "2027-01-24", "2027-04-24"]


def test_the_four_quarters_of_a_financial_year_are_april_to_march():
    assert fy_quarters("2026-27") == [
        (2026, 4, 2026, 6), (2026, 7, 2026, 9),
        (2026, 10, 2026, 12), (2027, 1, 2027, 3),
    ]


def test_no_obligation_falls_outside_the_financial_year_it_belongs_to():
    """A quarter's period must sit inside its FY even though its DUE date does
    not — Q4 Jan-Mar 2027 is due 13 Apr 2027, in the next FY, and that is
    correct."""
    for freq, state in ((ce.MONTHLY, None), (ce.QUARTERLY, "27")):
        for s in _gst_obligations("2026-27", freq, state):
            if s["obligation_type"] == "GSTR9":
                continue
            assert "2026-04-01" <= s["period_start"] <= "2027-03-31", s
            assert "2026-04-01" <= s["period_end"] <= "2027-03-31", s
            assert s["due_date"] > s["period_end"], "a return cannot be due before its period ends"
