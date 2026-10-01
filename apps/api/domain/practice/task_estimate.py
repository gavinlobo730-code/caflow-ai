"""How long a task is expected to take — the rule, and nothing else
(practice_management-24).

WHAT WAS WRONG

    The product had TWO answers to "how loaded is this person", and one of them
    was a guess by job title. `/team/workload` is a real model — a thirteen-week
    forecast off each person's configured `weekly_capacity_hours` and the time
    they have logged — while `/team/work-allocation` divided a count of open
    tasks by a constant held in the browser (Partner 20, Manager 30, Executive 40,
    Reviewer 20). And the real model could see effort for almost nothing: a task
    row carried no estimate, the task template's `estimated_hours` was never
    copied when a task was made from it, and the only effort the forecast could
    find was `workflow_steps.estimated_hours` reached through a `workflow_step_id`
    that nothing in the product writes. So the forecast said "no effort estimates
    recorded" for practically every firm.

THE ONE PLACE EFFORT LIVES IS THE TASK

    `tasks.estimated_minutes` (migration 452). Every door that makes a task from
    something that knows how long it takes COPIES it at creation — a task
    template (`estimated_hours`, whole hours), a recurring configuration that
    points at one, a workflow step (`estimated_hours`, tenths of an hour, or a
    `create_task` action's own `estimated_minutes`) — so the figure the forecast
    reads and the figure a person sees on the task are the same figure, and a
    later edit to the template does not silently re-estimate work already made.

    MINUTES, NOT HOURS: the template's whole hours cannot say ninety minutes and
    a quarter-hour workflow step cannot be held in an integer number of hours.
    Every conversion goes through `minutes_from_hours`, so there is one rounding.

NULL IS "NOBODY ESTIMATED THIS" AND IT IS NEVER ZERO

    `clean_minutes` returns a whole number of minutes MORE than zero, or `None`.
    There is no estimate of nothing: a task that takes no time is not a task, and
    reading an absent estimate as 0 would make a firm's work look free in exactly
    the forecast that exists to say it is not. The column CHECKs `> 0` for the
    same reason, which also stops a browser that writes `tasks` over PostgREST
    from storing a 0 this module would have refused.

    AND NOTHING IS AVERAGED. `summarise` totals what is recorded and COUNTS the
    tasks that carry none, side by side — an average over the second would make
    the first meaningless, which is the rule `domain/practice/capacity_risk`
    already holds for the forecast.

NO DATABASE HANDLE. The routers and services that make or read tasks fetch.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Iterable, Optional

#: The sentence a refused estimate is refused with — one wording at every door.
ESTIMATE_PROBLEM = (
    "An estimate is a whole number of minutes, more than zero. Three hours is 180; "
    "leave it out if nobody has estimated the task."
)


def clean_minutes(value: object) -> Optional[int]:
    """A task estimate as whole minutes (> 0), or None when absent or unusable.

    `bool` is refused although it is an `int` (True is not one minute), a float is
    accepted only where it is a whole number (`180.0` came from JSON), and text is
    accepted only as plain digits — PostgREST can return a number as text, and
    "1e3" or "12.5" are not estimates.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        value = int(text) if text.isascii() and text.isdigit() else None
        if value is None:
            return None
    try:
        whole = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError, OverflowError):
        return None
    return whole if whole > 0 and whole == value else None


def check_minutes(value: object) -> Optional[int]:
    """`clean_minutes` for a door that is SETTING one: None passes through as
    "not given"; anything else that is not an estimate is refused with the
    sentence rather than stored as something it is not."""
    if value is None:
        return None
    cleaned = clean_minutes(value)
    if cleaned is None:
        raise ValueError(ESTIMATE_PROBLEM)
    return cleaned


def minutes_from_hours(hours: object) -> Optional[int]:
    """Hours (a template's whole hours, a workflow step's tenths or quarters) as
    whole minutes, or None when there is no usable figure.

    Exact for every figure those sources can hold — 3 h is 180, 1.5 h is 90, 0.25 h
    is 15. Anything finer is rounded half up to the minute: this is an estimate of
    effort, not a statutory or money figure, and the minute is the unit it is kept
    in. Zero and negative hours are no estimate."""
    if hours is None or isinstance(hours, bool):
        return None
    try:
        h = Decimal(str(hours).strip())
    except (InvalidOperation, ValueError):
        return None
    if not h.is_finite() or h <= 0:
        return None
    minutes = int((h * 60).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return minutes if minutes > 0 else None


def hours_from_minutes(minutes: object) -> Optional[float]:
    """The forecast's unit. None stays None — an absent estimate is not 0.0."""
    cleaned = clean_minutes(minutes)
    return None if cleaned is None else cleaned / 60


@dataclass(frozen=True)
class Estimated:
    """What a pile of tasks is expected to take, and how many say nothing."""
    minutes: int
    with_estimate: int
    without_estimate: int


def summarise(estimates: Iterable[object]) -> Estimated:
    """Total the recorded estimates and COUNT the tasks that carry none."""
    minutes = have = lack = 0
    for raw in estimates:
        m = clean_minutes(raw)
        if m is None:
            lack += 1
        else:
            minutes += m
            have += 1
    return Estimated(minutes=minutes, with_estimate=have, without_estimate=lack)
