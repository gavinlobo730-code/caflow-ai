"""The analytics period label names the Indian FY quarter, not the calendar one.

`routers/analytics._period_range` buckets a quarter on
`((month - 1) // 3) * 3 + 1`, which gives January, April, July or October —
exactly the four quarters of an Indian financial year, so the WINDOW has always
been right. The LABEL was `f"Q{(q_start_month - 1) // 3 + 1} {today.year}"`,
the CALENDAR quarter number and the CALENDAR year, and it was wrong in all four
quarters rather than only across the year boundary:

    15-01-2026   "Q1 2026"   should be   Q4 2025-26
    02-05-2026   "Q2 2026"   should be   Q1 2026-27
    09-08-2026   "Q3 2026"   should be   Q2 2026-27
    30-11-2026   "Q4 2026"   should be   Q3 2026-27

A CA in this market reads Q1 as April-June. "Q1 2026" against a January window
names a quarter three months later than the figures it heads, and five
endpoints carry it — /team, /clients, /firm, /profitability and
/revenue-vs-effort — with Phase 3a putting it on a screen.

THE WINDOW IS PINNED TOO, and that is the point of the test rather than an
extra: the fix takes only the LABEL from `core.ist_clock.fy_quarters` and
leaves `start` exactly as it was, because this window is quarter-TO-DATE and
that module's own docstring refuses a to-date variant. A later change that
reached for `fy_quarters`' start as well would silently turn every quarter
figure into a whole-quarter one.
"""
from datetime import date

import pytest

from core.ist_clock import fy_quarters, ist_fy_label
from routers.analytics import _period_range


@pytest.mark.parametrize(
    "today,expected_label,expected_start",
    [
        (date(2026, 1, 15), "Q4 2025-26", "2026-01-01"),
        (date(2026, 5, 2),  "Q1 2026-27", "2026-04-01"),
        (date(2026, 8, 9),  "Q2 2026-27", "2026-07-01"),
        (date(2026, 11, 30), "Q3 2026-27", "2026-10-01"),
        # The two edges of the FY, where the calendar year and the FY label
        # disagree and a naive `today.year` is most obviously wrong.
        (date(2026, 3, 31), "Q4 2025-26", "2026-01-01"),
        (date(2026, 4, 1),  "Q1 2026-27", "2026-04-01"),
    ],
)
def test_the_quarter_label_is_the_financial_years(
    monkeypatch, today, expected_label, expected_start
):
    monkeypatch.setattr("routers.analytics.ist_today", lambda: today)
    start, end, label = _period_range("quarter")
    assert label == expected_label
    # Quarter-TO-DATE: the start is the quarter's, the end is today.
    assert start == expected_start
    assert end == today.isoformat()


def test_the_label_agrees_with_the_one_authority(monkeypatch):
    """Not a restatement of the table above — the table is a fixed set of
    dates, and this walks every month of two financial years against
    `fy_quarters` itself, so a month nobody thought to list cannot drift."""
    for y in (2025, 2026):
        for m in range(1, 13):
            d = date(y, m, 15)
            monkeypatch.setattr("routers.analytics.ist_today", lambda d=d: d)
            _, _, label = _period_range("quarter")
            fy = ist_fy_label(d)
            iso = d.isoformat()
            want = next(q for q, a, b in fy_quarters(fy) if a <= iso <= b)
            assert label == f"{want} {fy}", f"{iso} came back {label!r}"


def test_the_other_periods_are_untouched(monkeypatch):
    """Only the quarter branch moved. A sweep that 'tidied' the month label
    into an FY one would break the five endpoints' month view, which is a
    calendar month and correctly named as one."""
    d = date(2026, 1, 15)
    monkeypatch.setattr("routers.analytics.ist_today", lambda: d)
    assert _period_range("month")[2] == "January 2026"
    assert _period_range("week")[2].startswith("Week of ")
    # An unrecognised period still falls through to the month, as before.
    assert _period_range("decade")[2] == "January 2026"
