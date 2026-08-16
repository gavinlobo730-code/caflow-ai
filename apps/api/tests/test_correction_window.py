"""
The 30 November window — after which a period cannot be corrected at all.

CGST §37(3) (rectifying GSTR-1), §39(9) (rectifying GSTR-3B) and §16(4) (taking
input tax credit) all close on the same date, amended by the Finance Act 2022 to:

    30 November following the end of the financial year, OR the furnishing of
    the relevant annual return, WHICHEVER IS EARLIER.

Two things here decide whether a CA is told the truth:

  * the financial year. India's runs 1 April to 31 March, so a June 2025 invoice
    is in FY 2025-26 and its window runs to 30 November 2026. Reading the
    calendar year instead is the difference between "months left" and "closed
    last year".
  * the "whichever is earlier". Filing GSTR-9 early shuts the window early.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from domain.gst.correction_window import (
    CLOSED, CLOSING_SOON, CLOSING_SOON_DAYS, OPEN, financial_year_end, fy_label,
    is_actionable, window_for,
)
from services.compliance_engine import correction_window_closes, november_30_cutoff


# ── the financial year ───────────────────────────────────────────────────────

@pytest.mark.parametrize("period,fy_end,label", [
    ("042025", 2026, "2025-26"),   # April — first month of the FY
    ("062025", 2026, "2025-26"),
    ("032026", 2026, "2025-26"),   # March — last month of the SAME FY
    ("042026", 2027, "2026-27"),   # April — a new FY starts
    ("122025", 2026, "2025-26"),
    ("012026", 2026, "2025-26"),   # January is late in the FY, not early
])
def test_the_financial_year_runs_april_to_march(period, fy_end, label):
    assert financial_year_end(period) == fy_end
    assert fy_label(period) == label


def test_march_and_april_are_in_different_financial_years():
    """The boundary that a calendar-year reading gets wrong."""
    assert financial_year_end("032026") == 2026
    assert financial_year_end("042026") == 2027


@pytest.mark.parametrize("bad", ["", None, "nonsense", "132025", "002025", "62025"])
def test_a_malformed_period_has_no_window(bad):
    assert financial_year_end(bad) is None
    assert window_for(bad, as_of=date(2026, 1, 1)) is None
    assert fy_label(bad) == ""


# ── the statutory date ───────────────────────────────────────────────────────

def test_the_window_closes_on_30_november_after_the_financial_year_ends():
    """FY 2025-26 ends 31 Mar 2026, so its cutoff is 30 Nov 2026 — not 2025."""
    assert november_30_cutoff(2026) == date(2026, 11, 30)

    w = window_for("062025", as_of=date(2026, 1, 1))

    assert w["closes_on"] == "2026-11-30"
    assert w["financial_year"] == "2025-26"


def test_an_early_annual_return_shuts_the_window_early():
    """The "whichever is earlier" limb. A client who files GSTR-9 in August has
    lost the ability to amend that year from August — three months before the
    date everyone quotes."""
    assert correction_window_closes(2026, date(2026, 8, 15)) == date(2026, 8, 15)

    w = window_for("062025", as_of=date(2026, 1, 1),
                   annual_return_filed_on=date(2026, 8, 15))

    assert w["closes_on"] == "2026-08-15"
    assert w["statutory_cutoff"] == "2026-11-30"
    assert w["shortened_by_annual_return"] is True


def test_an_annual_return_filed_after_30_november_does_not_extend_anything():
    """Whichever is EARLIER — a late annual return cannot buy more time."""
    assert correction_window_closes(2026, date(2026, 12, 20)) == date(2026, 11, 30)

    w = window_for("062025", as_of=date(2026, 1, 1),
                   annual_return_filed_on=date(2026, 12, 20))

    assert w["closes_on"] == "2026-11-30"
    assert w["shortened_by_annual_return"] is False


def test_with_no_annual_return_the_statutory_date_stands():
    w = window_for("062025", as_of=date(2026, 1, 1))

    assert w["closes_on"] == w["statutory_cutoff"]
    assert w["shortened_by_annual_return"] is False


# ── where the window stands ──────────────────────────────────────────────────

def test_a_window_with_months_left_is_open():
    w = window_for("062025", as_of=date(2026, 1, 1))

    assert w["status"] == OPEN
    assert w["days_left"] == 333
    assert is_actionable(w) is True


def test_a_window_inside_the_warning_period_is_closing_soon():
    w = window_for("062025", as_of=date(2026, 11, 10))

    assert w["status"] == CLOSING_SOON
    assert w["days_left"] == 20
    assert is_actionable(w) is True, "closing is not closed — it can still be fixed"


def test_the_last_day_is_still_open():
    """30 November is the last day ON which it can be done, not the first day it
    cannot."""
    w = window_for("062025", as_of=date(2026, 11, 30))

    assert w["days_left"] == 0
    assert w["status"] == CLOSING_SOON
    assert is_actionable(w) is True


def test_the_day_after_is_closed():
    w = window_for("062025", as_of=date(2026, 12, 1))

    assert w["days_left"] == -1
    assert w["status"] == CLOSED
    assert is_actionable(w) is False


def test_the_warning_period_boundary():
    closes = date(2026, 11, 30)
    exactly = window_for("062025", as_of=closes - timedelta(days=CLOSING_SOON_DAYS))
    day_before = window_for("062025", as_of=closes - timedelta(days=CLOSING_SOON_DAYS + 1))

    assert exactly["status"] == CLOSING_SOON
    assert day_before["status"] == OPEN


def test_a_long_closed_window_is_reported_rather_than_hidden():
    """A CA needs to know what can no longer be fixed at least as much as what
    can — a closed window means the output tax stays understated or the input
    credit is simply lost."""
    w = window_for("062023", as_of=date(2026, 1, 1))

    assert w["status"] == CLOSED
    assert w["financial_year"] == "2023-24"
    assert w["closes_on"] == "2024-11-30"


# ── what it says ─────────────────────────────────────────────────────────────

def test_the_window_cites_all_three_provisions():
    """One date governs amendments and unclaimed credit alike; a CA reading
    only the GSTR-1 rule would miss the ITC consequence."""
    w = window_for("062025", as_of=date(2026, 1, 1))

    for section in ("§37(3)", "§39(9)", "§16(4)"):
        assert section in w["rule"]


def test_is_actionable_is_false_for_a_period_with_no_window():
    assert is_actionable(None) is False
