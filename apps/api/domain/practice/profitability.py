"""
What the practice billed a client and what the time spent on that client cost: the rule, and nothing else (POST-B-321).

WHAT WAS WRONG. Each of these put a figure on `/practice/profitability` that a Partner would have acted on.

  1. REVENUE COUNTED EVERY INVOICE. `invoice_repo.get_revenue_by_client` summed every non-deleted `fee_invoices` row in
     the window with no look at its status, so a Draft nobody had issued and a Cancelled invoice were both "revenue".
  2. THE TWO ENDPOINTS DISAGREED ABOUT WHAT REVENUE IS. `/profitability` summed `amount_paise` (the fee, before GST);
     `/revenue-vs-effort` summed `total_paise`, which is the fee PLUS the 18% GST the practice collects for the
     government (`invoice_generation_service`: `total = amount + gst`), and only the statuses 'Issued' and 'Paid', so
     an invoice that was issued and then fell overdue dropped out of it. Realization and revenue per hour were
     overstated by the GST. There is one definition now and both endpoints use it.
  3. A CLIENT WITH EFFORT AND NO INVOICE NEVER APPEARED. The list was built from the clients that had revenue, so the
     client the practice spent ten hours on and never billed, which is the one a Partner most needs to see, was not
     on it, and the firm's cost left out its time.
  4. COST WAS THE RATE THE HOUR BILLS AT, AND ZERO WHEN THERE WAS NONE. `cost = minutes x time_entries.hourly_rate_paise`
     is what the hour is WORTH to the client (it is the denominator of realization), not what it costs the practice;
     and the column is NULL on every entry started by the timer, so those hours cost nothing and profit equalled
     revenue, printed as a margin. `users.cost_rate_paise` was captured and read by nothing.

WHAT THE FIGURE IS NOW.

  * REVENUE is the fee, before GST, on invoices that are issued: Issued, Sent, Paid and Overdue. Drafts and Cancelled
    invoices count for nothing. (`Sent` is the database's original word for what the application calls `Issued`,
    migration 123.) An invoice counts in the period of its OWN DATE (`invoice_date`, which is the day it was made),
    not of the day it was issued: nothing records that day, so a draft dated in October and issued in November is
    October's revenue from the day it is issued. The payload says so.
  * COST is, for each ended time entry, the member's cost rate times the minutes, floored once per entry the way
    `domain/billing/time_rate` values an hour, so every grouping of the same entries adds to the same total.
  * A MEMBER WITH NO COST RATE IS UNKNOWN, NOT ZERO. The hours are counted and named (`unrated_minutes`); the cost of
    the hours that do have a rate is still shown; the client's profit and margin are None, never revenue less nothing.
    A rate of 0 is a rate somebody stated and is honoured.
  * A MARGIN ON NO REVENUE IS UNDEFINED. A client with time and no issued invoice has revenue 0, its cost, and no
    margin: 0% would rank it above a client billed at a loss.
  * A CLIENT BILLED WITH NO TIME RECORDED HAS NO KNOWN COST. The work happened and was not recorded, so revenue less 0
    is not a profit; the old footnote said "that is an absence of data, not a margin" under a margin column that drew
    it as 100%. Its profit is None and its status says why.

WHAT IT IS NOT. A cost rate is one number per member as it stands today: a rate changed in June changes the cost of
April's hours too. The payload says so (`NOT_MEASURED`) rather than keeping a history nobody asked for.
`HEALTHY_MARGIN_PCT` and `FAIR_MARGIN_PCT` are the product's own bands for a screen's colour, not a statutory or ICAI
figure.

NO DATABASE HANDLE, NO MONEY CONVERSION. `repositories/invoice_repository` and `repositories/time_tracking_analytics_repository`
fetch, `routers/analytics` assembles, this module decides. All arithmetic is whole paise.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from domain.billing import time_rate

#: The `fee_invoices.status` values that are an invoice somebody was sent. `Sent` is the original database word for what
#: the application calls `Issued` (migration 123); `Overdue` is an issued invoice past its due date, still revenue.
COUNTED_STATUSES: tuple[str, ...] = ("Issued", "Sent", "Paid", "Overdue")

#: The values that are not revenue. Together with COUNTED_STATUSES they are every value the table's CHECK allows, and a
#: test holds that, so a status added to the table is a decision here and not a silent omission.
NOT_COUNTED_STATUSES: tuple[str, ...] = ("Draft", "Cancelled")

HEALTHY_MARGIN_PCT = 25
FAIR_MARGIN_PCT = 15

STATUS_HEALTHY = "healthy"
STATUS_FAIR = "fair"
STATUS_AT_RISK = "at_risk"
#: Time was recorded and nothing was invoiced in the window.
STATUS_NOT_BILLED = "not_billed"
#: Invoiced, and no time recorded against the client at all, so its cost is not known.
STATUS_NO_TIME = "no_time"
#: Invoiced, but some of the time has no cost rate, so there is no margin to judge.
STATUS_UNPRICED = "unpriced"

#: What the figures are and are not. Rendered beside them.
NOT_MEASURED: tuple[str, ...] = (
    "Revenue is the fee before GST on invoices that are issued, counted in the period of the invoice's own date and "
    "not of the day it was issued, and not fees collected. A draft or a cancelled invoice counts for nothing, so a "
    "draft dated in one month and issued in the next is the earlier month's revenue from the day it is issued.",
    "Cost is each member's cost rate as it stands today, times the hours they recorded in the period. Changing a "
    "rate changes the cost of earlier months too.",
    "Only time that has ended is counted, so a running timer is not. Time recorded against no client is in no "
    "client's cost.",
)


def _whole(value: object) -> int:
    """Whole paise or minutes out of what PostgREST sent. A NULL is 0 here only because a sum needs a number: the
    callers that must not read an absence as 0 (a rate) do not come through this function."""
    if value is None or isinstance(value, bool):
        return 0
    return int(value)


# ── revenue ──────────────────────────────────────────────────────────────────

def counts_as_revenue(invoice: Mapping) -> bool:
    return invoice.get("status") in COUNTED_STATUSES


def revenue_paise(invoice: Mapping) -> int:
    """The fee on one invoice BEFORE GST. `fee_invoices.amount_paise` is the fee; `gst_paise` is added to it to make
    `total_paise` (migration 014; `invoice_generation_service`), and the GST is the government's, not the practice's."""
    return _whole(invoice.get("amount_paise"))


def revenue_by_client(invoices: Iterable[Mapping]) -> dict[str, int]:
    out: dict[str, int] = {}
    for inv in invoices:
        client_id = inv.get("client_id")
        if not client_id or not counts_as_revenue(inv):
            continue
        out[client_id] = out.get(client_id, 0) + revenue_paise(inv)
    return out


def revenue_by_engagement(invoices: Iterable[Mapping]) -> dict[str, dict]:
    """`{engagement_id: {engagement_id, client_id, revenue_paise, invoice_count}}`. An invoice that names no
    engagement is in no engagement's revenue (it is in its client's)."""
    out: dict[str, dict] = {}
    for inv in invoices:
        engagement_id = inv.get("engagement_id")
        if not engagement_id or not counts_as_revenue(inv):
            continue
        row = out.setdefault(engagement_id, {
            "engagement_id": engagement_id,
            "client_id": inv.get("client_id"),
            "revenue_paise": 0,
            "invoice_count": 0,
        })
        row["revenue_paise"] += revenue_paise(inv)
        row["invoice_count"] += 1
    return out


# ── effort and cost ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Effort:
    """The time recorded against one client, engagement or member, and what it cost."""
    minutes: int = 0
    billable_minutes: int = 0
    #: What the hours that HAVE a cost rate cost. Not the whole cost when `unrated_minutes` is above 0.
    cost_paise: int = 0
    #: Hours whose member has no cost rate: counted, and never priced at 0.
    unrated_minutes: int = 0

    @property
    def rated_minutes(self) -> int:
        return self.minutes - self.unrated_minutes

    @property
    def cost_is_known(self) -> bool:
        """Some time was recorded and every minute of it has a cost rate. No time is not a cost of 0."""
        return self.minutes > 0 and self.unrated_minutes == 0

    @property
    def priced_cost_paise(self) -> Optional[int]:
        """What the hours that have a cost rate cost, or None when none of them has one: a sum of nothing is not a cost
        of 0. A stated rate of 0 is a rate, so those hours do count as priced and cost 0."""
        return self.cost_paise if self.rated_minutes > 0 else None


def clean_cost_rates(raw: Mapping[object, object]) -> dict[str, Optional[int]]:
    """`{user_id: whole non-negative paise or None}`. A rate that is absent, negative or not a whole number is None,
    the unknown, through the same reader the billing rate uses."""
    return {str(user_id): time_rate.clean_rate(rate) for user_id, rate in raw.items()}


def fold_effort(entries: Iterable[Mapping], cost_rates: Mapping[str, Optional[int]], key: str) -> dict[Optional[str], Effort]:
    """Group ended time entries by `key` (`client_id`, `engagement_id` or `user_id`) and price each at its member's cost
    rate. The group `None` holds entries with no value for the key, so a caller can say it was left out."""
    acc: dict[Optional[str], list[int]] = {}
    for entry in entries:
        minutes = _whole(entry.get("duration_minutes"))
        if minutes <= 0:
            continue
        group = entry.get(key) or None
        a = acc.setdefault(group, [0, 0, 0, 0])
        a[0] += minutes
        if entry.get("is_billable"):
            a[1] += minutes
        user_id = entry.get("user_id")
        cost = time_rate.value_paise(minutes, cost_rates.get(str(user_id)) if user_id else None)
        if cost is None:
            a[3] += minutes
        else:
            a[2] += cost
    return {group: Effort(minutes=v[0], billable_minutes=v[1], cost_paise=v[2], unrated_minutes=v[3])
            for group, v in acc.items()}


def unrated_people(entries: Iterable[Mapping], cost_rates: Mapping[str, Optional[int]],
                   key: str = "client_id") -> list[tuple[Optional[str], int]]:
    """Who has hours with no cost rate and how many, the most first. A member the entry no longer names is `None`.

    ONLY TIME THAT HAS A `key` (a client, by default) IS COUNTED: the people this names are the ones whose missing rate
    leaves a client's cost short, so it must be the same population as `Effort.unrated_minutes` summed over the clients.
    Time with no client is in no client's cost whatever the member's rate, and naming it here made the headline hours and
    the names beside them disagree."""
    minutes_by_user: dict[Optional[str], int] = {}
    for entry in entries:
        minutes = _whole(entry.get("duration_minutes"))
        if minutes <= 0 or not entry.get(key):
            continue
        user_id = entry.get("user_id") or None
        if user_id is not None and cost_rates.get(str(user_id)) is not None:
            continue
        minutes_by_user[user_id] = minutes_by_user.get(user_id, 0) + minutes
    return sorted(minutes_by_user.items(), key=lambda kv: (-kv[1], str(kv[0])))


# ── a client's position ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class Position:
    key: str
    revenue_paise: int
    effort: Effort

    @property
    def cost_paise(self) -> int:
        return self.effort.cost_paise

    @property
    def unrated_minutes(self) -> int:
        return self.effort.unrated_minutes

    @property
    def priced_cost_paise(self) -> Optional[int]:
        """The cost of the hours that have a cost rate, or None when none has one (see `Effort.priced_cost_paise`)."""
        return self.effort.priced_cost_paise

    @property
    def cost_is_known(self) -> bool:
        return self.effort.cost_is_known

    @property
    def profit_paise(self) -> Optional[int]:
        """None unless the cost is known: revenue less part of the cost, or less the cost of time nobody recorded, is
        not a profit."""
        return self.revenue_paise - self.effort.cost_paise if self.cost_is_known else None

    @property
    def margin_pct(self) -> Optional[float]:
        """None where there is no profit to divide or no revenue to divide it by. Never 0.0 for either."""
        profit = self.profit_paise
        if profit is None or self.revenue_paise <= 0:
            return None
        return round(profit / self.revenue_paise * 100, 2)

    @property
    def status(self) -> str:
        if self.revenue_paise <= 0:
            return STATUS_NOT_BILLED
        if self.effort.minutes <= 0:
            return STATUS_NO_TIME
        pct = self.margin_pct
        if pct is None:
            return STATUS_UNPRICED
        if pct >= HEALTHY_MARGIN_PCT:
            return STATUS_HEALTHY
        if pct >= FAIR_MARGIN_PCT:
            return STATUS_FAIR
        return STATUS_AT_RISK


def positions(revenue: Mapping[str, int], effort: Mapping[Optional[str], Effort]) -> list[Position]:
    """One position for every key that has revenue OR effort, so the client the practice worked on and never billed is
    on the list. The effort group `None` (time with no client) is not a client and is not here."""
    keys = {k for k in revenue} | {k for k in effort if k is not None}
    empty = Effort()
    out = [Position(key=k, revenue_paise=revenue.get(k, 0), effort=effort.get(k, empty)) for k in keys]
    # A key with nothing billed and no time is not a row: a ₹0 invoice would otherwise be "time recorded, nothing billed"
    # for a client nobody spent a minute on, and would take the firm's profit away.
    out = [p for p in out if p.revenue_paise > 0 or p.effort.minutes > 0]
    # Known profits first, the most profitable at the top; then the rows whose profit cannot be known yet, by what they
    # billed. Mixing the two scales in one order would put a client with unpriced hours between two with real margins.
    out.sort(key=lambda p: ((0, -p.profit_paise) if p.profit_paise is not None else (1, -p.revenue_paise), p.key))
    return out


@dataclass(frozen=True)
class Totals:
    revenue_paise: int
    #: What the hours that have a cost rate cost. Short of the real cost while `clients_without_cost` or
    #: `unrated_minutes` is above 0.
    cost_paise: int
    unrated_minutes: int
    clients_billed: int
    clients_not_billed: int
    #: Minutes behind `cost_paise` that have a cost rate. Nothing priced is not a cost of 0.
    rated_minutes: int
    #: Rows whose cost is known (time recorded, every minute priced) and rows whose cost is not.
    clients_with_cost: int
    clients_without_cost: int
    #: The profit of the rows whose cost is known, by themselves: a figure with its scope named, for the day the firm
    #: total cannot be given.
    profit_on_known_paise: int

    @property
    def cost_is_complete(self) -> bool:
        return self.clients_without_cost == 0

    @property
    def priced_cost_paise(self) -> Optional[int]:
        """`cost_paise`, or None when no hour behind it has a cost rate."""
        return self.cost_paise if self.rated_minutes > 0 else None

    @property
    def profit_paise(self) -> Optional[int]:
        """The firm's profit, or None while any client's cost is unknown: a total with a hole in it is not a total."""
        return self.revenue_paise - self.cost_paise if self.cost_is_complete else None

    @property
    def margin_pct(self) -> Optional[float]:
        profit = self.profit_paise
        if profit is None or self.revenue_paise <= 0:
            return None
        return round(profit / self.revenue_paise * 100, 2)

    @property
    def avg_profit_per_billed_client_paise(self) -> Optional[int]:
        profit = self.profit_paise
        if profit is None or self.clients_billed <= 0:
            return None
        return profit // self.clients_billed


def totals(rows: Iterable[Position]) -> Totals:
    rows = list(rows)
    known = [r for r in rows if r.cost_is_known]
    return Totals(
        revenue_paise=sum(r.revenue_paise for r in rows),
        cost_paise=sum(r.cost_paise for r in rows),
        unrated_minutes=sum(r.unrated_minutes for r in rows),
        clients_billed=sum(1 for r in rows if r.revenue_paise > 0),
        clients_not_billed=sum(1 for r in rows if r.revenue_paise <= 0 and r.effort.minutes > 0),
        rated_minutes=sum(r.effort.rated_minutes for r in rows),
        clients_with_cost=len(known),
        clients_without_cost=len(rows) - len(known),
        profit_on_known_paise=sum(r.revenue_paise - r.cost_paise for r in known),
    )
