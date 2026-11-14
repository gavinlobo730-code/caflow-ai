"""A member's own time over a range of Indian days: the window a period names, and the totals (POST-A-156).

WHY THIS MODULE
    `/time` used to total the entries it LISTED, a window of at most 500, so its "Total Hours" was the latest entries and not a
    period, and the server's `GET /api/time-entries/summary/me` summed every entry the member had ever made in Python, accepted a
    `period` it ignored and nothing called it. The figure is three numbers, so CLAUDE.md's reporting rule puts the sum in the
    database: `public.time_entry_summary` (migration 586). This module is its mock-mode twin, held identical to it by
    `tests/test_time_entry_summary_parity_pg.py`, and the one place that says which days a period is.

THE RULES, ONCE
    * A period is a range of INDIAN days. "This week" is Monday to Sunday of the week holding India's today, "this month" the
      calendar month holding it, and a chosen range is the two days given, both counted; a range whose first day is after its
      last is refused rather than read as empty.
    * An entry belongs to the day it STARTED on, in India (`ist_day_window` on the database side, `in_ist_window` here). An entry
      that runs past midnight is counted whole on the day it began, which is how the list on the same screen dates it.
    * Only a FINISHED entry is counted (`ended_at` and `duration_minutes` both recorded). A timer still running has no duration
      yet; it is counted apart (`running`), so a screen can say it is not in the total rather than leave it out silently.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Iterable, Optional

from core.ist_clock import in_ist_window

PERIODS = ("week", "month", "range")


class PeriodProblem(ValueError):
    """A period the rule cannot turn into a range of days, in a sentence for the person who asked."""


def window_for(period: str, today: date, date_from: Optional[date] = None, date_to: Optional[date] = None) -> tuple[date, date]:
    """(first day, last day), both counted, for a period on the given Indian day."""
    if period == "week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    if period == "month":
        last = calendar.monthrange(today.year, today.month)[1]
        return today.replace(day=1), today.replace(day=last)
    if period == "range":
        if date_from is None or date_to is None:
            raise PeriodProblem("A chosen range needs both its first day and its last day.")
        if date_from > date_to:
            raise PeriodProblem("The first day of the range is after its last day.")
        if date_to >= date.max:
            # The window is closed at the start of the day AFTER the last one (end exclusive), which the calendar cannot hold.
            raise PeriodProblem("The last day of the range is the last day the calendar holds; choose an earlier one.")
        return date_from, date_to
    raise PeriodProblem(f"period must be one of: {', '.join(PERIODS)}.")


def _finished(entry: dict) -> bool:
    return bool(entry.get("ended_at")) and entry.get("duration_minutes") is not None


def summarise(entries: Iterable[dict], date_from: date, date_to: date) -> dict:
    """The totals over the entries whose start's Indian day lies in the range: the shape `time_entry_summary` returns."""
    total = billable = count = running = 0
    by_client: dict[Optional[str], dict] = {}
    for e in entries:
        if not in_ist_window(e.get("started_at"), date_from, date_to):
            continue
        if not _finished(e):
            if not e.get("ended_at"):
                running += 1
            continue
        minutes = int(e["duration_minutes"])
        is_billable = bool(e.get("is_billable"))
        total += minutes
        count += 1
        if is_billable:
            billable += minutes
        row = by_client.setdefault(e.get("client_id"), {"client_id": e.get("client_id"), "minutes": 0, "billable_minutes": 0})
        row["minutes"] += minutes
        if is_billable:
            row["billable_minutes"] += minutes
    return {
        "total_minutes": total,
        "billable_minutes": billable,
        "entries_count": count,
        "running": running,
        # NULLS LAST, then by id, as the SQL orders them, so the two answers compare whole.
        "by_client": sorted(by_client.values(), key=lambda r: (r["client_id"] is None, r["client_id"] or "")),
    }
