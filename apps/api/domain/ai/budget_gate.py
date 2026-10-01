"""
The gate in front of every model call: has this firm spent its month? (ai-17)

`domain/ai/budget` is the rule and has no memory. This is the memory it needs to be asked
on the hot path of every model call without a database round trip each time:

  * per firm, the allowance and the month-to-date total are read ONCE a minute (the
    table and one aggregate function, `ai_usage_totals`), and a firm with NO allowance
    set costs one tiny read a minute and nothing else;
  * every attempt the gateway records is ADDED to the cached total at once (`note`), so a
    burst inside one process is counted immediately and not a minute late — the cached
    figure is then replaced by the database's at the next refresh;
  * a Partner changing the allowance drops that firm's entry (`invalidate`), so it takes
    effect on this process at the next call.

IT FAILS OPEN, AND SAYS SO. The AI is an optional helper and the allowance is a cost
guard, not a security control. If the allowance or the total cannot be read — the table
is missing, the database is down, a function is not there — the call goes ahead, a warning
is logged, and the failure is remembered for thirty seconds so a database that is down is
not asked again on every call. The opposite choice would turn an outage of the usage
database into an outage of the assistant for every firm, which is the larger harm.

IT IS PER PROCESS. With one worker (what Render runs today) the count is exact up to the
refresh interval. With several, each counts what it saw until its next refresh, so the
overshoot is bounded by the interval and the number of workers; the database total is
always the authority. `middleware/rate_limit` has the same stated limit.

NOTHING HERE IS A DEFAULT. A firm with no row has no limit; this module never supplies one.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from core.ist_clock import ist_today
from domain.ai import budget, gateway

_logger = logging.getLogger("caflow.ai.budget")

#: How long a firm's allowance and running total are trusted before they are read again.
TTL_S = 60.0
#: How long a FAILED read is remembered, so a database that is down is not asked again on
#: every call.
UNREADABLE_TTL_S = 30.0

Fetcher = Callable[[str, "budget.Month"], "tuple[budget.Limits, budget.Used]"]


@dataclass
class _Entry:
    month_key: str
    limits: budget.Limits
    used: budget.Used
    at: float
    readable: bool = True


_lock = threading.Lock()
_cache: dict[str, _Entry] = {}
_fetcher: Optional[Fetcher] = None


def _clock() -> float:
    return time.monotonic()


def set_fetcher(fn: Optional[Fetcher]) -> None:
    """Replace how the allowance and total are read (tests); None restores the default."""
    global _fetcher
    _fetcher = fn


def reset() -> None:
    """Forget every firm. For tests: the cache is process-wide."""
    with _lock:
        _cache.clear()


def invalidate(firm_id: str) -> None:
    """Drop one firm's entry, so the next call reads its allowance afresh."""
    with _lock:
        _cache.pop(firm_id, None)


def default_fetch(firm_id: str, month: "budget.Month") -> "tuple[budget.Limits, budget.Used]":
    """The allowance row, and — only when there is an allowance to measure against — the
    month-to-date totals. Both reads carry the firm; the second is an aggregate, so what
    crosses the wire is two numbers however many calls the month holds."""
    from core.supabase_client import get_service_supabase
    db = get_service_supabase()
    rows = (db.table("ai_firm_budgets")
            .select("monthly_token_limit, monthly_page_limit")
            .eq("firm_id", firm_id).limit(1).execute().data or [])
    limits = (budget.Limits(rows[0].get("monthly_token_limit"), rows[0].get("monthly_page_limit"))
              if rows else budget.Limits())
    if not limits.any_set:
        return limits, budget.Used()
    totals = (db.rpc("ai_usage_totals", {"p_firm": firm_id, "p_from": month.start_utc,
                                         "p_to": month.end_utc}).execute().data or [])
    row = totals[0] if totals else {}
    return limits, budget.Used(int(row.get("tokens") or 0), int(row.get("pages") or 0))


def _fetch_function() -> Optional[Fetcher]:
    if _fetcher is not None:
        return _fetcher
    # No database on this deployment (mock or local development): no allowance can exist.
    return default_fetch if os.environ.get("SUPABASE_URL") else None


def _entry(firm_id: str, month: "budget.Month", fetch: Fetcher) -> _Entry:
    now = _clock()
    with _lock:
        entry = _cache.get(firm_id)
    if entry is not None and entry.month_key == month.key:
        ttl = TTL_S if entry.readable else UNREADABLE_TTL_S
        if now - entry.at < ttl:
            return entry
    try:
        limits, used = fetch(firm_id, month)
        entry = _Entry(month.key, limits, used, now)
    except Exception:                                            # noqa: BLE001
        _logger.warning("ai budget: could not read the allowance for a firm; calls go ahead "
                        "until it can be read", exc_info=True)
        entry = _Entry(month.key, budget.Limits(), budget.Used(), now, readable=False)
    with _lock:
        _cache[firm_id] = entry
    return entry


def enforce(firm_id: Optional[str], feature: str, pages_wanted: int = 0) -> None:
    """Raise `ProviderFailed(kind=budget_exhausted, 429)` when this firm has spent its
    month; return otherwise. No firm, an exempt feature, no database and an unreadable
    allowance all return."""
    if not firm_id or feature in budget.EXEMPT_FEATURES:
        return
    fetch = _fetch_function()
    if fetch is None:
        return
    month = budget.month_of(ist_today())
    entry = _entry(firm_id, month, fetch)
    if not entry.readable:
        return
    verdict = budget.check(entry.limits, entry.used, month=month, feature=feature,
                           pages_wanted=pages_wanted)
    if not verdict.allowed:
        raise gateway.ProviderFailed(verdict.sentence or "The AI allowance is used up.",
                                     http_status=429, kind=gateway.BUDGET)


def note(ev: "gateway.UsageEvent") -> None:
    """Add one recorded attempt to the cached running total, if this firm is cached and
    the attempt falls in the cached month. Never reads the database."""
    if not ev.firm_id or ev.outcome == gateway.BUDGET:
        return
    key = budget.month_of(ist_today()).key
    with _lock:
        entry = _cache.get(ev.firm_id)
        if entry is None or not entry.readable or entry.month_key != key:
            return
        entry.used = budget.Used(entry.used.tokens + int(ev.total_tokens or 0),
                                 entry.used.pages + int(ev.input_units or 0))
