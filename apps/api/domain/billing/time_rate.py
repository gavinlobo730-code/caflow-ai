"""What an hour of recorded time bills at, and what a pile of unbilled hours is
worth — the rule, and nothing else (practice_management-11).

WHAT WAS WRONG

    Hours were logged and could never become a bill. The timer carried no
    engagement and no rate; nothing gave a staff member a billing rate at all
    (`users.cost_rate_paise` is capture-only and "NEVER used in any
    computation"); and the one place that totalled unbilled work read a missing
    rate as ZERO — which prints "this work is worth ₹0" for what is really
    "nobody has said what it is worth". Those are different statements and a CA
    acts differently on each: the first is a write-off, the second is a task.

THE ORDER A RATE IS READ IN

    1. the entry's OWN rate, where somebody typed one for this entry;
    2. the ENGAGEMENT's override, where the work was recorded against one;
    3. the PERSON's default;
    4. NOTHING — `None`, which is not 0.

    The answer is stored on the entry (`time_entries.billable_rate_paise`), so a
    later change to a rate does not silently re-price work already logged. The
    cost rate is never an input: what an hour costs the firm is not what it bills.

    NULL AND 0 ARE DIFFERENT AND BOTH ARE KEPT. A stated 0 — a retainer's hours,
    a favour — is a decision and is honoured (it values the hour at nothing and
    does NOT put the entry on the "no rate" list). Only an absent rate is
    unknown. `if rate:` is how the code this replaces confused them.

WHICH ENGAGEMENT, WHEN NOBODY CHOSE ONE

    The client's single ACTIVE engagement. Two or more is NOT resolved by taking
    the first or the newest: which one the hour belongs to is a fact about the
    work, and a wrong guess would price it under the wrong override. So the
    answer is `None` with a reason the screen can show, and the picker asks.
    "Active" is the same set `compliance_obligation_service` already generates
    obligations for — one definition, imported there.

THE UNBILLED TOTAL

    `fold_unbilled` takes GROUPED rows — `(client_id, task_id, priced, minutes,
    value_paise, entries)` — which is what the SQL function
    `public.unbilled_time_summary` (migration 451) returns, and
    `group_unbilled_entries` turns raw entries into the same grouped rows so the
    in-memory path and the database path share ONE assembler. A group that is
    not priced adds minutes and a count to the "no rate" section and NOTHING to
    value. Value is floored per entry (minutes x paise // 60), so every grouping
    of the same entries sums to the same total.

NO DATABASE HANDLE, NO MONEY CONVERSION. `services/time_rates_service` fetches.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

#: The fee-engagement statuses whose work is live. The SAME set the obligation
#: generator treats as active (`compliance_obligation_service` imports this), so
#: "the client's active engagement" cannot mean two things in one product.
ACTIVE_ENGAGEMENT_STATUSES: tuple[str, ...] = ("Active", "In Progress", "Review")

#: Where a resolved rate came from, for the screen to say.
SOURCE_ENTRY = "entry"
SOURCE_ENGAGEMENT = "engagement"
SOURCE_USER = "user"


@dataclass(frozen=True)
class RateResolution:
    rate_paise: Optional[int]
    source: Optional[str]

    @property
    def has_rate(self) -> bool:
        return self.rate_paise is not None


def clean_rate(rate: object) -> Optional[int]:
    """A rate as whole non-negative paise, or None when it is absent or unusable.

    `bool` is refused although it is an `int` (True is not ₹0.01 an hour) and a
    negative is refused rather than clamped: neither is a rate anybody stated.
    """
    if rate is None or isinstance(rate, bool):
        return None
    if isinstance(rate, str):
        # PostgREST can hand a bigint back as text; digits only, so "1e3" and
        # "12.5" are not read as amounts.
        text = rate.strip()
        return int(text) if text.isascii() and text.isdigit() else None
    try:
        value = int(rate)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 and value == rate else None


def resolve_rate(*, entry_rate_paise: object = None,
                 engagement_rate_paise: object = None,
                 user_rate_paise: object = None) -> RateResolution:
    """The billing rate for one entry, and where it came from. `None` is
    returned as itself — never as 0."""
    for source, raw in ((SOURCE_ENTRY, entry_rate_paise),
                        (SOURCE_ENGAGEMENT, engagement_rate_paise),
                        (SOURCE_USER, user_rate_paise)):
        rate = clean_rate(raw)
        if rate is not None:
            return RateResolution(rate, source)
    return RateResolution(None, None)


def value_paise(minutes: object, rate_paise: object) -> Optional[int]:
    """minutes x rate / 60, floored, in whole paise — or None when there is no
    rate, because a figure computed from nothing is not 0."""
    rate = clean_rate(rate_paise)
    if rate is None:
        return None
    try:
        mins = int(minutes or 0)
    except (TypeError, ValueError):
        return None
    return (max(mins, 0) * rate) // 60


@dataclass(frozen=True)
class EngagementChoice:
    """Which engagement an entry defaults to, and why not where it does not."""
    engagement_id: Optional[str]
    reason: Optional[str]
    active: tuple[dict, ...]


def default_engagement(engagements: Iterable[Mapping]) -> EngagementChoice:
    """The client's single active engagement, or nothing and a reason."""
    active = tuple(dict(e) for e in engagements
                   if e.get("status") in ACTIVE_ENGAGEMENT_STATUSES)
    if len(active) == 1:
        return EngagementChoice(str(active[0]["id"]), None, active)
    if not active:
        return EngagementChoice(None, "The client has no active engagement, so no engagement "
                                      "override applies.", active)
    return EngagementChoice(
        None,
        f"The client has {len(active)} active engagements and none was chosen, so no "
        f"engagement override applies. Which one this time belongs to is a fact about "
        f"the work.", active)


# ── the unbilled total ───────────────────────────────────────────────────────

#: How many un-rated entries a screen is shown. The COUNT is always the whole
#: truth; the list is what a person can act on in one sitting.
NO_RATE_LIST_LIMIT = 200


def entry_group(entry: Mapping) -> Optional[dict]:
    """One raw time entry as a single-entry GROUPED row, or None when it is not
    unbilled billable time at all (the rule `unbilled_time_summary` applies in
    its WHERE clause)."""
    if not entry.get("is_billable") or entry.get("billed_invoice_id"):
        return None
    minutes = int(entry.get("duration_minutes") or 0)
    if minutes <= 0:
        return None
    billable, hourly = entry.get("billable_rate_paise"), entry.get("hourly_rate_paise")
    rate = billable if billable is not None else hourly
    value = value_paise(minutes, rate)
    return {
        "client_id": entry.get("client_id"),
        "task_id": entry.get("task_id"),
        "priced": value is not None,
        "minutes": minutes,
        "value_paise": value or 0,
        "entries": 1,
    }


def group_unbilled_entries(entries: Iterable[Mapping]) -> list[dict]:
    """Raw entries -> the grouped rows the SQL function returns."""
    merged: dict[tuple, dict] = {}
    for entry in entries:
        g = entry_group(entry)
        if g is None:
            continue
        key = (g["client_id"], g["task_id"], g["priced"])
        slot = merged.setdefault(key, {**g, "minutes": 0, "value_paise": 0, "entries": 0})
        slot["minutes"] += g["minutes"]
        slot["value_paise"] += g["value_paise"]
        slot["entries"] += 1
    return list(merged.values())


def fold_unbilled(groups: Iterable[Mapping]) -> dict:
    """Grouped rows -> the answer the unbilled-work screen renders.

    `by_client` / `by_work_item` carry PRICED work only, in the shape
    `{minutes, value_paise, count}` they always had. Work with no rate is the
    `no_rate` section — minutes and a count, never a value — and
    `total_minutes` is everything unbilled so the two can be told apart from a
    total that quietly leaves them out.
    """
    by_client: dict = {}
    by_work_item: dict = {}
    nr_by_client: dict = {}
    total_value = priced_minutes = no_rate_minutes = no_rate_count = 0
    for g in groups:
        minutes = int(g.get("minutes") or 0)
        count = int(g.get("entries") or 0)
        client = g.get("client_id") or "unassigned"
        work = g.get("task_id") or "unassigned"
        if g.get("priced"):
            value = int(g.get("value_paise") or 0)
            for bucket, key in ((by_client, client), (by_work_item, work)):
                slot = bucket.setdefault(str(key), {"minutes": 0, "value_paise": 0, "count": 0})
                slot["minutes"] += minutes
                slot["value_paise"] += value
                slot["count"] += count
            total_value += value
            priced_minutes += minutes
        else:
            slot = nr_by_client.setdefault(str(client), {"minutes": 0, "count": 0})
            slot["minutes"] += minutes
            slot["count"] += count
            no_rate_minutes += minutes
            no_rate_count += count
    return {
        "by_client": by_client,
        "by_work_item": by_work_item,
        "total_value_paise": total_value,
        "priced_minutes": priced_minutes,
        "total_minutes": priced_minutes + no_rate_minutes,
        "no_rate": {
            "count": no_rate_count,
            "minutes": no_rate_minutes,
            "by_client": nr_by_client,
            "entries": [],
        },
    }
