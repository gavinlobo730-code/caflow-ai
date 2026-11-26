"""How long one filing of an obligation type takes in this practice (POST-A-212, migration 671): the rule for what a firm may record.

A task carries its own whole-minute estimate (`task_estimate`, migration 452). A compliance obligation that is not worked as a task has
none, so Team Workload's one capacity model saw it as dated and weightless. The firm states, per obligation type, how many whole
minutes ONE filing of that kind takes. The figure is the firm's statement and never the product's: nothing is defaulted, seeded or
averaged, and a type with no figure stays an item without an estimate. Minutes are whole and more than zero (`task_estimate`'s rule,
reused so the two cannot disagree), and no statutory figure is held here: effort is not a date, a rate or a threshold.
"""
from __future__ import annotations

from typing import Optional

from domain.practice import task_estimate

#: A sanity bound, not a rule of practice: a year of minutes. It stops a mistyped figure reading as a real one in a forecast; it says
#: nothing about how long any filing should take.
MAX_MINUTES = 525_600
MAX_TYPE_CHARS = 60

TYPE_PROBLEM = f"Name the kind of filing (for example GSTR-3B), up to {MAX_TYPE_CHARS} characters, with no control characters."
MINUTES_PROBLEM = (f"{task_estimate.ESTIMATE_PROBLEM} It cannot be more than {MAX_MINUTES:,} minutes (a year).")


def clean_type(value: object) -> Optional[str]:
    """The obligation type as stored, or None when it is not a usable one. Whitespace is trimmed; case is kept (the calendar's word)."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > MAX_TYPE_CHARS or any(ord(c) < 32 or ord(c) == 127 for c in text):
        return None
    return text


def check_minutes(value: object) -> int:
    """The whole minutes to store, or a ValueError carrying the sentence."""
    cleaned = task_estimate.clean_minutes(value)
    if cleaned is None or cleaned > MAX_MINUTES:
        raise ValueError(MINUTES_PROBLEM)
    return cleaned


def hours_by_type(rows: list[dict]) -> dict[str, float]:
    """`{compliance_type: hours}` from stored rows; a row whose minutes are unusable is left out (an unknown, never a zero)."""
    out: dict[str, float] = {}
    for r in rows:
        key = clean_type(r.get("compliance_type"))
        hours = task_estimate.hours_from_minutes(r.get("estimated_minutes"))
        if key is not None and hours is not None:
            out[key] = hours
    return out
