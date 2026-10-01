"""
A firm's monthly AI allowance, and what the month's usage rows add up to. (ai-17)

THE RULE, WITH NO DATABASE. Which month a call belongs to, whether a call may go
ahead, what is said when it may not, and how a month's grouped usage rows fold into
the figures a Partner reads. `domain/ai/budget_gate` is the stateful half that reads
the allowance and the running total and asks this module; `services/ai_usage_service`
is the half that reads the table for the screen.

THE MONTH IS THE INDIAN ONE. A firm's day, and so its month, is IST (CLAUDE.md,
"Reporting times"): a call at 23:30 UTC on 30 September is 05:00 on 1 October for the
people who made it, and counting it against September would let October start already
spent. `ist_month_bounds` returns the half-open window as UTC instants for the query.

NO LIMIT IS NOT ZERO. A limit that is `None` is not set, which is every firm's position
until a Partner sets one. Zero is refused where a limit is written, and `check` treats
a non-positive limit as not set rather than as "refuse everything", so a bad row can
never switch the AI off for a firm by accident.

TOKENS CAN ONLY BE COUNTED AFTER THE CALL, so the call that CROSSES a token limit is
allowed to finish and the next one is refused: the overshoot is at most one call. PAGES
ARE KNOWN BEFORE THE CALL, so a document that would take the firm past its page limit is
refused before anything is sent, never read in part (a reading that stops partway drops
the line items after it and says nothing).

THE OUTCOME VOCABULARY IS NOT HERE. Which outcomes are answers and which are failures is
`domain/ai/gateway`'s; `fold` asks it, so a word added there is classified in one place.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from core.ist_clock import IST
from domain.ai import gateway
from domain.money_text import group_indian

#: How far back the screen will read. A usage row is small, but the answer is a month
#: and a Partner asking about 2019 is asking about something nobody recorded.
MONTHS_BACK = 12

#: A Partner may not set a limit above these: they are not a policy, they stop a typo
#: from reading as "unlimited" the other way round and overflowing the column.
MAX_TOKEN_LIMIT = 10**12
MAX_PAGE_LIMIT = 10**7

#: Features that are never refused for want of an allowance. The probe is how a Partner
#: finds out WHY the AI is not answering, and it costs a few tokens.
EXEMPT_FEATURES = frozenset({"probe"})

_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December")


class BudgetError(ValueError):
    """A limit or a month that cannot be accepted. The message is for the person."""


# ── the month ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Month:
    key: str                 # "2026-10"
    label: str               # "October 2026"
    start: _dt.datetime      # IST midnight on day 1, aware
    end: _dt.datetime        # IST midnight on day 1 of the next month, aware

    @property
    def start_utc(self) -> str:
        return self.start.astimezone(_dt.timezone.utc).isoformat()

    @property
    def end_utc(self) -> str:
        return self.end.astimezone(_dt.timezone.utc).isoformat()

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label,
                "starts_on": self.start.date().isoformat(),
                "ends_before": self.end.date().isoformat()}


def month_of(today: _dt.date) -> Month:
    first = _dt.datetime(today.year, today.month, 1, tzinfo=IST)
    nxt_year, nxt_month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return Month(key=f"{today.year:04d}-{today.month:02d}",
                 label=f"{_MONTH_NAMES[today.month - 1]} {today.year}",
                 start=first, end=_dt.datetime(nxt_year, nxt_month, 1, tzinfo=IST))


def month_for(instant: _dt.datetime) -> Month:
    """The IST month an instant falls in. A naive instant is read as UTC."""
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=_dt.timezone.utc)
    return month_of(instant.astimezone(IST).date())


def parse_month(raw: Optional[str], today: _dt.date) -> Month:
    """`YYYY-MM`, or the current IST month when absent. Refuses a month in the future
    or further back than `MONTHS_BACK`, in words."""
    current = month_of(today)
    if raw is None or raw == "":
        return current
    m = _MONTH_RE.match(raw.strip())
    if not m:
        raise BudgetError("A month is written year-month, like 2026-10.")
    asked = month_of(_dt.date(int(m.group(1)), int(m.group(2)), 1))
    if asked.start > current.start:
        raise BudgetError("That month has not started yet.")
    earliest = current.start.year * 12 + current.start.month - 1 - MONTHS_BACK
    if asked.start.year * 12 + asked.start.month - 1 < earliest:
        raise BudgetError(f"Usage is kept for the last {MONTHS_BACK} months.")
    return asked


# ── the limits ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Limits:
    monthly_tokens: Optional[int] = None
    monthly_pages: Optional[int] = None

    @property
    def any_set(self) -> bool:
        return _is_set(self.monthly_tokens) or _is_set(self.monthly_pages)

    def as_dict(self) -> dict:
        return {"monthly_tokens": self.monthly_tokens, "monthly_pages": self.monthly_pages}


@dataclass(frozen=True)
class Used:
    tokens: int = 0
    pages: int = 0


def _is_set(limit: Any) -> bool:
    return isinstance(limit, int) and not isinstance(limit, bool) and limit > 0


def validate_limit(value: Any, *, name: str, maximum: int) -> Optional[int]:
    """A limit as a Partner sends it: a whole number from 1, or `None` for none.
    Zero, a negative, a fraction, a bool and a string are all refused."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise BudgetError(f"{name} must be a whole number, or left empty for no limit.")
    if value < 1:
        raise BudgetError(f"{name} must be at least 1, or left empty for no limit "
                          "(zero is not accepted: it would read as both).")
    if value > maximum:
        raise BudgetError(f"{name} cannot be more than {group_indian(str(maximum))}.")
    return value


# ── the decision ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Verdict:
    allowed: bool
    #: "tokens" or "pages" when refused.
    reason: Optional[str] = None
    sentence: Optional[str] = None


ALLOWED = Verdict(True)

_WHERE = "A Partner can raise or remove the limit under Settings, AI status."
_NOTHING_SENT = "Nothing was sent to the AI provider."


def check(limits: Limits, used: Used, *, month: Month, feature: str,
          pages_wanted: int = 0) -> Verdict:
    """May this call go ahead? The caller has already skipped a call with no firm."""
    if feature in EXEMPT_FEATURES or not limits.any_set:
        return ALLOWED
    if _is_set(limits.monthly_pages) and pages_wanted > 0 \
            and used.pages + pages_wanted > limits.monthly_pages:
        return Verdict(False, "pages", (
            f"This {pages_wanted}-page document would take your firm past its AI page "
            f"allowance for {month.label} ({group_indian(str(used.pages))} of "
            f"{group_indian(str(limits.monthly_pages))} pages used). {_WHERE} {_NOTHING_SENT}"))
    if _is_set(limits.monthly_tokens) and used.tokens >= limits.monthly_tokens:
        return Verdict(False, "tokens", (
            f"Your firm has used its AI allowance for {month.label} "
            f"({group_indian(str(used.tokens))} of {group_indian(str(limits.monthly_tokens))} "
            f"tokens, counted from 1 {_MONTH_NAMES[month.start.month - 1]} IST). "
            f"{_WHERE} {_NOTHING_SENT}"))
    return ALLOWED


def standing(limits: Limits, used: Used, *, month: Month) -> dict:
    """What the Partner's screen says about the allowance, whatever any call is doing.
    `sentence` is only ever set when an allowance has been reached."""
    def part(limit: Optional[int], spent: int) -> dict:
        if not _is_set(limit):
            return {"limit": None, "used": spent, "remaining": None, "reached": False}
        return {"limit": limit, "used": spent, "remaining": max(0, limit - spent),
                "reached": spent >= limit}

    tokens, pages = part(limits.monthly_tokens, used.tokens), part(limits.monthly_pages, used.pages)
    sentence: Optional[str] = None
    if tokens["reached"]:
        # The refusal a call would get, word for word: one sentence for one fact.
        sentence = check(limits, used, month=month, feature="usage").sentence
    elif pages["reached"]:
        sentence = (f"Your firm has used its AI page allowance for {month.label} "
                    f"({group_indian(str(used.pages))} of {group_indian(str(limits.monthly_pages))} "
                    f"pages). {_WHERE}")
    return {"tokens": tokens, "pages": pages,
            "reached": bool(tokens["reached"] or pages["reached"]), "sentence": sentence}


# ── what the month's rows add up to ──────────────────────────────────────────

def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


#: PostgREST caps a response at about a thousand rows and says nothing when it does
#: (`db-max-rows`). A grouped answer that REACHES it may have been cut, and is reported
#: as such rather than presented as complete.
ROW_CAP = 1000

_ZERO = {"calls": 0, "attempts": 0, "answered": 0, "failed": 0, "refused": 0,
         "tokens": 0, "reasoning_tokens": 0, "pages": 0}


def _delta(r: dict) -> dict:
    """One grouped row as the figures it adds. A CALL is a first attempt
    (`first_attempts`): a retry or a fallback is a further attempt of the same call, not a
    second call. An ANSWER is an outcome the gateway names as one; a REFUSAL is a call
    turned away for want of the allowance; everything else is a FAILED attempt, except the
    gateway's own retry-without-the-hint, which is housekeeping and counts nowhere as a
    failure. The vocabulary is the gateway's, asked here, never restated."""
    outcome = str(r.get("outcome") or "")
    attempts = _int(r.get("attempts"))
    d = {"calls": _int(r.get("first_attempts")), "attempts": attempts,
         "tokens": _int(r.get("tokens")), "reasoning_tokens": _int(r.get("reasoning_tokens")),
         "pages": _int(r.get("pages")), "answered": 0, "failed": 0, "refused": 0}
    if outcome in gateway.ANSWERED:
        d["answered"] = attempts
    elif outcome == gateway.BUDGET:
        d["refused"] = attempts
    elif outcome != gateway.PARAM_REJECTED:
        d["failed"] = attempts
    return d


def _add(into: dict, d: dict) -> None:
    for k, v in d.items():
        into[k] += v


def fold(by_day: Iterable[dict], by_feature: Iterable[dict]) -> dict:
    """The two grouped answers (`ai_usage_by_day`, `ai_usage_by_feature`) as the three views
    a Partner reads: month totals, by feature, by day. The totals are summed from the DAY
    rows; the by-feature rows are summed on their own, so the two agree whenever neither
    answer was cut (`truncated` says when one may have been)."""
    day_rows, feature_rows = list(by_day), list(by_feature)
    totals = dict(_ZERO)
    days: dict[str, dict] = {}
    for r in day_rows:
        d = _delta(r)
        _add(totals, d)
        key = str(r.get("day") or "")[:10]
        _add(days.setdefault(key, {"day": key, **_ZERO}), d)

    features: dict[tuple, dict] = {}
    models: dict[tuple, set] = {}
    for r in feature_rows:
        key = (r.get("feature"), r.get("provider"))
        _add(features.setdefault(key, {"feature": r.get("feature"), "provider": r.get("provider"),
                                       **_ZERO}), _delta(r))
        models.setdefault(key, set()).add(r.get("model"))
    by_feature_list = [{**e, "models": sorted(m for m in models[k] if m)} for k, e in features.items()]
    by_feature_list.sort(key=lambda e: (-e["tokens"], -e["pages"], str(e["feature"])))

    return {"totals": totals, "by_feature": by_feature_list,
            "by_day": sorted(days.values(), key=lambda e: e["day"]),
            "truncated": len(day_rows) >= ROW_CAP or len(feature_rows) >= ROW_CAP}
