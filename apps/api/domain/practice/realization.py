"""
Realization: what the practice invoiced against what the billable time was worth at the rate it was recorded at (POST-A-426).

WHAT WAS WRONG. `/api/analytics/revenue-vs-effort` priced the hours from `time_entries.hourly_rate_paise`, the legacy column,
averaged the entries that carry one and multiplied that average by ALL the engagement's billable minutes. Since migration
451 an hour is priced when it is recorded and the answer is stored in `billable_rate_paise`; `hourly_rate_paise` is NULL on
every entry the timer started and on every entry priced from the engagement's or the person's rate. So:

  1. A FIRM THAT PRICES ITS TIME WITH THE NEW RATES SAW A DASH AGAINST EVERY ENGAGEMENT: the average was of nothing, the
     rate read 0.0 and the screen drew 0.0 as a dash, which a Partner reads as "nothing to report" and not as "the
     product could not read your rates".
  2. WHERE A FEW ENTRIES CARRIED A LEGACY RATE, THE REST WERE PRICED AT THEIRS: one entry at ₹2,000 among nine unpriced
     ones made all ten hours worth ₹2,000, and realization was computed on a worth that was mostly invented.
  3. AN ENGAGEMENT WITH TIME AND NO INVOICE WAS NOT A ROW, although the firm's total counted its hours.
  4. THE FIRM'S FIGURE HAD NO WAY TO REACH THE SCREEN: the server answered `realization_rate` and the browser read
     `overall_realization_rate`, so the tile was a dash whatever the books held.

THE RULE NOW.

  * AN ENTRY IS PRICED FROM ITS OWN RATE. `time_rate.entry_rate`: `billable_rate_paise` first, `hourly_rate_paise` second,
    the order the unbilled-work total reads, floored once per ENTRY by `time_rate.value_paise`, so every grouping of the same
    entries adds to the same total (a property test holds that). A stated rate of 0 is a rate.
  * AN ENTRY NOBODY PRICED IS UNKNOWN, NOT WORTH 0. Its minutes are counted as `unpriced_minutes` and left out of the worth.
  * A REALIZATION IS GIVEN ONLY WHERE EVERY BILLABLE MINUTE IS PRICED. One unpriced minute makes the worth short, so a ratio
    against it would be too high, and it is None for that row. A worth of 0 (every hour stated at 0) is None too: a ratio
    against nothing is undefined. A row with billable time, every minute priced and no invoice has a realization of 0.0,
    which is a figure: the practice billed none of it.
  * A CLIENT'S AND THE FIRM'S RATIO IS TAKEN ON THE WORK THAT HAS TIME. Fees on an engagement with no billable time recorded
    (a fixed-fee return nobody timed) have a fee and no worth, and putting them over the OTHER engagements' worth read
    10.00× for a firm whose timed engagement read 1.00×. They are `revenue_without_time_paise`: named, never added to the
    numerator. Fees on an invoice that names no engagement are in no row at all and are named the same way.
  * ONLY BILLABLE TIME IS COUNTED, and only time that has ended. Time and fees that name no engagement are in no
    engagement's row and in no total here; the payload says how much time that is.

NO DATABASE HANDLE, NO MONEY CONVERSION. `repositories/time_tracking_analytics_repository` fetches, `routers/analytics`
assembles, this module decides. All arithmetic is whole paise and whole minutes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from domain.billing import time_rate

#: What the figures are and are not. Rendered beside them.
NOT_MEASURED: tuple[str, ...] = (
    "Realization is the fee before GST invoiced on an engagement in the period, against what the billable time recorded "
    "on it in the period is worth at the rate each entry was recorded with. 1.00× recovers it exactly; below that the "
    "engagement is under-priced or over-served. Fees and time are each counted in their own period, so work done in one "
    "month and invoiced in the next shows low in the first and high in the second.",
    "Only billable time that has ended is counted. Time and invoices that name no engagement are in no engagement's row "
    "and in no total here, and are named beside the figure.",
    "A client's and the firm's realization is taken on the engagements that have billable time recorded. Fees on an "
    "engagement with none (a fixed-fee return nobody timed) are named and left out of it, because there is no worth to "
    "set them against.",
    "Billable time that nobody priced is named and is not counted as worth nothing. A row with such time shows no "
    "realization, because a ratio against part of the worth would be too high.",
)


def _whole(value: object) -> int:
    """Whole minutes out of what PostgREST sent. A NULL is 0 here because a sum needs a number; a rate never comes through
    this function."""
    if value is None or isinstance(value, bool):
        return 0
    return int(value)


@dataclass(frozen=True)
class Worth:
    """The billable time recorded against one engagement, client or the firm, and what it is worth."""
    billable_minutes: int = 0
    #: Minutes whose entry has no rate: counted, never priced at 0.
    unpriced_minutes: int = 0
    #: What the minutes that HAVE a rate are worth. Short of the real worth while `unpriced_minutes` is above 0.
    value_paise: int = 0

    @property
    def priced_minutes(self) -> int:
        return self.billable_minutes - self.unpriced_minutes

    @property
    def value_is_known(self) -> bool:
        """Some billable time was recorded and every minute of it has a rate. No time is not a worth of 0."""
        return self.billable_minutes > 0 and self.unpriced_minutes == 0

    @property
    def priced_value_paise(self) -> Optional[int]:
        """What the minutes that have a rate are worth, or None when none has one: a sum of nothing is not a worth of 0."""
        return self.value_paise if self.priced_minutes > 0 else None

    def __add__(self, other: "Worth") -> "Worth":
        return Worth(self.billable_minutes + other.billable_minutes,
                     self.unpriced_minutes + other.unpriced_minutes,
                     self.value_paise + other.value_paise)


def fold_worth(entries: Iterable[Mapping], key: str) -> dict[Optional[str], Worth]:
    """Group ended BILLABLE time entries by `key` (`engagement_id`, usually) and price each from its own rate. The group
    `None` holds entries with no value for the key, so a caller can say how much time was left out."""
    acc: dict[Optional[str], list[int]] = {}
    for entry in entries:
        if not entry.get("is_billable"):
            continue
        minutes = _whole(entry.get("duration_minutes"))
        if minutes <= 0:
            continue
        a = acc.setdefault(entry.get(key) or None, [0, 0, 0])
        a[0] += minutes
        value = time_rate.value_paise(minutes, time_rate.entry_rate(entry))
        if value is None:
            a[1] += minutes
        else:
            a[2] += value
    return {group: Worth(billable_minutes=v[0], unpriced_minutes=v[1], value_paise=v[2]) for group, v in acc.items()}


def realization_rate(revenue_paise: int, worth: Worth) -> Optional[float]:
    """Revenue over the worth of the billable time, to two places, or None where it cannot be said: no billable time, any
    minute of it unpriced, or a worth of 0. Never 0.0 for an unknown (0.0 is "next to nothing was billed against it", to two
    places, and is only given where the worth is known)."""
    if not worth.value_is_known or worth.value_paise <= 0:
        return None
    return round(revenue_paise / worth.value_paise, 2)


def revenue_per_hour_paise(revenue_paise: int, billable_minutes: int) -> Optional[int]:
    """What each billable hour brought in, in whole paise, or None with no billable time (no hours is not ₹0 an hour)."""
    if billable_minutes <= 0:
        return None
    return (revenue_paise * 60) // billable_minutes


@dataclass(frozen=True)
class Row:
    """One engagement, one client or the firm: what was invoiced on it, and what its billable time is worth.

    `revenue_paise` is every fee on the row. `compared_paise` is the part of it on work that has billable time recorded, and
    it alone is what the ratio is taken on: a fixed-fee engagement with no time recorded has fees and no worth, and putting
    its fees over the worth of the OTHER engagements is the "ratio against part of the worth" defect in the other direction
    (a firm with a timed audit at 1.00× and a fixed-fee return with no time read 10.00×). What is left out is named
    (`revenue_without_time_paise`), never dropped."""
    key: str
    revenue_paise: int
    compared_paise: int
    worth: Worth

    @property
    def revenue_without_time_paise(self) -> int:
        return self.revenue_paise - self.compared_paise

    @property
    def realization_rate(self) -> Optional[float]:
        return realization_rate(self.compared_paise, self.worth)

    @property
    def revenue_per_hour_paise(self) -> Optional[int]:
        return revenue_per_hour_paise(self.compared_paise, self.worth.billable_minutes)


def rows(revenue: Mapping[str, int], worth: Mapping[Optional[str], Worth]) -> list[Row]:
    """One row for every key that has revenue OR billable time, so the engagement the practice worked on and never invoiced
    is listed (its realization is 0.0 when its time is priced). The worth group `None` is not a key and is not here. The
    biggest fee first, then by key, so the order does not depend on which dictionary was filled first."""
    keys = {k for k, v in revenue.items() if v > 0} | {k for k, w in worth.items() if k is not None and w.billable_minutes > 0}
    empty = Worth()
    out = []
    for k in keys:
        w = worth.get(k, empty)
        fee = revenue.get(k, 0)
        out.append(Row(key=k, revenue_paise=fee, compared_paise=fee if w.billable_minutes > 0 else 0, worth=w))
    out.sort(key=lambda r: (-r.revenue_paise, r.key))
    return out


def combine(key: str, parts: Iterable[Row]) -> Row:
    """The rows added up (an engagement's rows into its client, every row into the firm). Each part keeps its own
    comparison, so the total's ratio is taken on the work that has time and nowhere else."""
    revenue = compared = 0
    worth = Worth()
    for r in parts:
        revenue += r.revenue_paise
        compared += r.compared_paise
        worth = worth + r.worth
    return Row(key=key, revenue_paise=revenue, compared_paise=compared, worth=worth)


def firm(revenue: Mapping[str, int], worth: Mapping[Optional[str], Worth]) -> Row:
    """The firm's figure over every engagement that has revenue or billable time. A total with unpriced time in it has no
    realization, for the reason a row does not, and fees on engagements with no time are named and left out of the ratio."""
    return combine("firm", rows(revenue, worth))


def revenue_outside_engagements(invoices: Iterable[Mapping]) -> dict[str, int]:
    """`{client_id: fees}` on issued invoices that name no engagement: they are in no engagement's row, so in no client's and
    not in the firm's, and the screen says how much that is. The same invoices count in `/profitability`'s revenue."""
    from domain.practice import profitability as profit

    out: dict[str, int] = {}
    for inv in invoices:
        client_id = inv.get("client_id")
        if not client_id or inv.get("engagement_id") or not profit.counts_as_revenue(inv):
            continue
        out[client_id] = out.get(client_id, 0) + profit.revenue_paise(inv)
    return out


def minutes_outside_engagements(entries: Iterable[Mapping]) -> dict[Optional[str], int]:
    """`{client_id: billable minutes}` on ended billable entries that name no engagement (the key `None` is time with no
    client either). In no row and no total, for the same reason as the fees above."""
    out: dict[Optional[str], int] = {}
    for entry in entries:
        if not entry.get("is_billable") or entry.get("engagement_id"):
            continue
        minutes = _whole(entry.get("duration_minutes"))
        if minutes <= 0:
            continue
        client_id = entry.get("client_id") or None
        out[client_id] = out.get(client_id, 0) + minutes
    return out
