"""Which billing period a fee invoice belongs to, from the engagement's cycle.

WHY THIS EXISTS
    "Raise Invoice" minted a new fee invoice on every click. A Monthly engagement
    clicked twice in September was billed twice for September, and a Quarterly
    or Annual one was billed on every click all year (misc-tools-06). The guard
    needs one answer — the period THIS invoice date falls in — and the cycle
    vocabulary is migration 123's CHECK on fee_engagements.billing_cycle.

PERIODS FOLLOW THE INDIAN FINANCIAL YEAR, April to March, because that is the
    year a practice's engagements and fee letters run on: Quarterly is Apr–Jun,
    Jul–Sep, Oct–Dec, Jan–Mar; Half-Yearly is Apr–Sep and Oct–Mar. Monthly is the
    calendar month. A One-time engagement is billed once, ever, so its period is
    unbounded and is answered as (None, None).

AN UNKNOWN CYCLE IS REFUSED, never guessed: guessing Monthly would let a
    once-a-year fee be billed twelve times, and guessing One-time would refuse the
    second month of a monthly retainer.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

CYCLES = ("Monthly", "Quarterly", "Half-Yearly", "Annually", "One-time")


def _fy_start(d: date) -> date:
    return date(d.year if d.month >= 4 else d.year - 1, 4, 1)


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, 1)


def billing_period(cycle: str, on: date) -> tuple[Optional[date], Optional[date]]:
    """(first day, last day) of the period `on` falls in, both inclusive.

    (None, None) for One-time: the whole life of the engagement is one period.
    Raises ValueError for a cycle outside CYCLES.
    """
    if cycle == "One-time":
        return None, None
    if cycle == "Monthly":
        start = date(on.year, on.month, 1)
        return start, _add_months(start, 1) - timedelta(days=1)
    span = {"Quarterly": 3, "Half-Yearly": 6, "Annually": 12}.get(cycle)
    if span is None:
        raise ValueError(
            f"Unknown billing cycle {cycle!r} — expected one of {', '.join(CYCLES)}.")
    fy = _fy_start(on)
    index = ((on.year - fy.year) * 12 + on.month - fy.month) // span
    start = _add_months(fy, index * span)
    return start, _add_months(start, span) - timedelta(days=1)


def describe(cycle: str, start: Optional[date], end: Optional[date]) -> str:
    """A short phrase naming the period, for the refusal sentence."""
    if start is None:
        return "this one-time engagement"
    if cycle == "Monthly":
        return start.strftime("%B %Y")
    return f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"
