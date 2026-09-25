"""
Which weeks the practice is about to be short-staffed — the rule, and nothing else.

WHAT THIS ANSWERS THAT NOTHING ELSE DOES. `/api/workload` and
`intelligence_service.compute_workload_insights` both describe TODAY: who has
too many tasks open right now. An Indian practice's problem is not today, it is
that the work arrives in spikes nobody staffed for — the 11th and the 20th of
every month for GST, 31 July and 31 October for returns, the quarterly TDS
statements, and a March that is three ordinary months in one. A partner knows
March is bad; what they cannot see is that the week of 8 December is four times
an ordinary week because sixty clients' GSTR-3B and a quarterly TDS statement
land in it together, and that it is four weeks away rather than four months.

THE HARD PART IS WHAT NOT TO INVENT, and there are two of them.

  * **HOURS.** `tasks` carries NO effort estimate — only `workflow_steps` and
    `task_templates` do (migrations 002 and 063), so a task generated from a
    workflow step has one and a hand-created or recurring one does not. The
    obvious move is to impute an average and total it; that produces a
    confident hours figure whose accuracy is a property of how many tasks
    happen to come from workflows, which the CA cannot see. So hours are
    reported ONLY where they are recorded, the tasks with none are COUNTED
    beside them, and nothing is averaged.
  * **CAPACITY.** `user_capacity.max_concurrent_tasks` is a limit on how many
    things somebody may have OPEN, not on how many they can finish in a week,
    and treating it as a weekly throughput is a category error that would give
    every week a confident percentage. So the load is measured against the
    practice's OWN median week in the window — the same shape
    `domain/accounting/ledger_anomalies` uses, and for the same reason: a
    number derived from the client's own history needs no model. The team's
    size and configured hours are reported BESIDE it, never multiplied into it.

A COMPLIANCE OBLIGATION AND ITS TASK ARE ONE PIECE OF WORK.
`compliance_calendar.task_id` (migration 006) exists precisely because a filing
obligation is often worked as a task, so counting both would double every
GSTR-1 in the forecast — the biggest single population in the table. Deduped on
that column, and the answer says how many were folded.

NO DATABASE HANDLE. `services/capacity_risk_service.py` fetches.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable, Optional


#: How far ahead to look, in weeks. Thirteen — a quarter — because that is the
#: horizon a practice can still act on: hire a contractor, move a client's
#: fieldwork, warn the client that their books have to be in earlier. A year
#: would be honest and useless, since the tasks for it do not exist yet; a
#: month is too late to do anything but work the weekend.
DEFAULT_WEEKS_AHEAD = 13

#: A week carrying this many times the median week in the window is called out.
#: Three, and it is deliberately LOWER than the ledger check's six, because the
#: cost of the two errors is not symmetric: a week wrongly flagged costs a
#: partner a glance at a calendar, and a week missed costs a filing deadline
#: with a s. 47 late fee per client per day behind it.
PEAK_MULTIPLE = 3

#: Below this many weeks with work in them, a median says nothing and no week
#: is called a peak. Four, so a practice whose calendar is barely populated is
#: told that rather than shown three arbitrary peaks.
MIN_WEEKS_FOR_A_MEDIAN = 4

#: What the forecast cannot see, named so a flat profile is not read as a quiet
#: quarter. Rendered beside the answer — the `table_4a_gaps` discipline.
NOT_FORECAST: tuple[str, ...] = (
    "Work that has not been created yet. A GSTR-3B obligation exists in the "
    "calendar only once something generates it, so a quarter that looks empty "
    "at the far end is usually a calendar that has not been rolled forward.",
    "How long anything takes, except where a workflow step recorded an "
    "estimate. Nothing is averaged across the tasks that carry none.",
    "Who is available. Leave, notice periods and a new joiner's ramp-up are "
    "facts no table here holds, so the team figures are a headcount and a "
    "configured week, not an availability forecast.",
    "Anything about a task with no due date. It is counted in the backlog "
    "figure and falls in no week, because putting it in this week would make "
    "the first bar wrong every time somebody forgets a date.",
)


@dataclass(frozen=True)
class DueItem:
    """One piece of work with a date. `source` is "task" or "compliance", and
    `effort_hours` is set ONLY where something recorded it."""
    due_date: str                       # ISO YYYY-MM-DD
    source: str
    effort_hours: Optional[float] = None
    label: Optional[str] = None


@dataclass(frozen=True)
class Week:
    #: Monday of the week, ISO. Monday because an Indian practice's own week
    #: runs Monday to Saturday, and because every statutory due date (the 7th,
    #: 11th, 20th) falls on a calendar day rather than a weekday — so the week
    #: boundary has to come from somewhere, and the working week is the one a
    #: partner staffs against.
    week_start: str
    items_due: int
    tasks_due: int
    compliance_due: int
    #: Recorded effort only. `items_without_an_estimate` is the rest of
    #: `items_due`, and the two are never combined.
    estimated_hours: float
    items_without_an_estimate: int
    #: This week's load as a percentage of the window's median week. 100 means
    #: an ordinary week. None where there were too few weeks for a median.
    vs_median_pct: Optional[int]
    is_peak: bool


@dataclass(frozen=True)
class CapacityRisk:
    weeks: tuple[Week, ...]
    #: Work already past its due date. It is not in any week — it is in ALL of
    #: them, since it still has to be done on top of whatever arrives — so it
    #: is stated once, apart, rather than piled onto the first bar.
    overdue_items: int
    #: With no due date at all. Counted, never placed.
    undated_items: int
    #: Folded because a compliance obligation named a task: one piece of work,
    #: not two. Reported because a partner comparing this with the deadline
    #: list will otherwise think the forecast is short.
    obligations_folded_into_tasks: int
    median_week_items: Optional[int]
    peak_weeks: tuple[str, ...]
    #: Headcount and the sum of their configured weeks. BESIDE the load, never
    #: multiplied into it — see the module header.
    people: int
    configured_weekly_hours: int
    not_forecast: tuple[str, ...] = field(default=NOT_FORECAST)


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _median(values: list[int]) -> int:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def forecast(items: Iterable[DueItem],
             *,
             today: date,
             people: int,
             configured_weekly_hours: int,
             obligations_folded_into_tasks: int = 0,
             weeks_ahead: int = DEFAULT_WEEKS_AHEAD) -> CapacityRisk:
    """The next `weeks_ahead` weeks, the overdue and undated work apart.

    EVERY WEEK IN THE WINDOW APPEARS, including the empty ones. A forecast that
    only lists the busy weeks cannot show a partner the quiet one they could
    move work into, and it also hides the far end of the window going empty —
    which is the calendar not being rolled forward rather than a free quarter,
    and is named in `NOT_FORECAST`.
    """
    first = monday_of(today)
    starts = [(first + timedelta(weeks=i)).isoformat() for i in range(weeks_ahead)]
    window_end = (first + timedelta(weeks=weeks_ahead)).isoformat()
    today_iso = today.isoformat()

    buckets: dict[str, list[DueItem]] = {s: [] for s in starts}
    overdue = 0
    undated = 0
    for item in items:
        if not item.due_date:
            undated += 1
            continue
        if item.due_date < today_iso:
            overdue += 1
            continue
        if item.due_date >= window_end:
            continue
        buckets[monday_of(date.fromisoformat(item.due_date)).isoformat()].append(item)

    counts = [len(buckets[s]) for s in starts]
    # The median is taken over the weeks that have work in them. Including the
    # empty ones would drag it toward zero and make every ordinary week look
    # like a peak — the far end of the window is usually empty simply because
    # the calendar has not been rolled that far.
    with_work = [c for c in counts if c > 0]
    median = _median(with_work) if len(with_work) >= MIN_WEEKS_FOR_A_MEDIAN else None

    weeks: list[Week] = []
    peaks: list[str] = []
    for start in starts:
        rows = buckets[start]
        known = [r for r in rows if r.effort_hours is not None]
        peak = bool(median and median > 0 and len(rows) >= median * PEAK_MULTIPLE)
        if peak:
            peaks.append(start)
        weeks.append(Week(
            week_start=start,
            items_due=len(rows),
            tasks_due=sum(1 for r in rows if r.source == "task"),
            compliance_due=sum(1 for r in rows if r.source == "compliance"),
            estimated_hours=round(sum(r.effort_hours or 0.0 for r in known), 1),
            items_without_an_estimate=len(rows) - len(known),
            vs_median_pct=(round(len(rows) * 100 / median)
                           if median and median > 0 else None),
            is_peak=peak,
        ))

    return CapacityRisk(
        weeks=tuple(weeks),
        overdue_items=overdue,
        undated_items=undated,
        obligations_folded_into_tasks=obligations_folded_into_tasks,
        median_week_items=median,
        peak_weeks=tuple(peaks),
        people=people,
        configured_weekly_hours=configured_weekly_hours,
    )
