"""What a firm's AI use came to, and the allowance it is held to. (ai-17)

THE RULES ARE `domain/ai/budget` AND THE MEMORY IS `domain/ai/budget_gate`; this is the
half that reads the table for the Partner's screen and the one write.

NOTHING IS COMPUTED HERE THAT A SQL AGGREGATE CAN ANSWER. The month's attempts are
grouped by `ai_usage_by_day` and `ai_usage_by_feature` (migration 476), so what crosses
the wire is two small answers however many calls the month held; the figures are then
folded by `budget.fold`, which asks the gateway which outcomes are answers and which are
failures. A grouped answer that reached PostgREST's row cap is reported as possibly cut
(`truncated`), never presented as complete.

TOKENS AND PAGES, NOT RUPEES. The providers' prices are not held here and they move, so
no cost figure is shown and none is implied; the answer says so.

THE ALLOWANCE APPLIES TO THE CURRENT MONTH, whichever month is being read: a Partner
looking at September still wants to know where October stands against the limit.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any, Optional

from core.ist_clock import ist_today
from domain.ai import budget, budget_gate

_logger = logging.getLogger("caflow.ai.usage")

NOT_COVERED = (
    "Tokens and pages only. No rupee figure is shown: the providers' prices are not held "
    "here and they change.",
    "Only calls made since the usage record began are counted; the first one for this firm "
    "is shown above.",
    "A limit is checked about once a minute on each server, so a burst can overshoot it by "
    "a few calls, and the call that crosses a token limit is allowed to finish. A page "
    "limit is checked before a document is sent and refuses it whole.",
    "The \"Check now\" buttons on this screen are never refused for want of an allowance: "
    "they are how you find out why the AI is not answering.",
)

NO_DATABASE = "This server has no database, so no AI usage is recorded and no allowance can be set."


def _window(month: "budget.Month", firm_id: str) -> dict:
    """The arguments all three aggregates take. The function NAMES are written out at each
    `.rpc()` call so the schema checks can read them."""
    return {"p_firm": firm_id, "p_from": month.start_utc, "p_to": month.end_utc}


def read_limits(db: Any, firm_id: str) -> tuple["budget.Limits", Optional[str]]:
    """The allowance row, or no limits and no timestamp. The projection is a literal
    because the column checker reads it."""
    rows = (db.table("ai_firm_budgets")
            .select("monthly_token_limit, monthly_page_limit, updated_at")
            .eq("firm_id", firm_id).limit(1).execute().data or [])
    if not rows:
        return budget.Limits(), None
    r = rows[0]
    return (budget.Limits(r.get("monthly_token_limit"), r.get("monthly_page_limit")),
            r.get("updated_at"))


def _first_recorded(db: Any, firm_id: str) -> Optional[str]:
    rows = (db.table("ai_usage_events").select("created_at").eq("firm_id", firm_id)
            .order("created_at").limit(1).execute().data or [])
    return rows[0].get("created_at") if rows else None


def month_choices(today: _dt.date) -> list[dict]:
    """The months a Partner may read, newest first, as the server will accept them."""
    out = []
    y, m = today.year, today.month
    for _ in range(budget.MONTHS_BACK + 1):
        mo = budget.month_of(_dt.date(y, m, 1))
        out.append({"key": mo.key, "label": mo.label})
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out


def usage(db: Optional[Any], firm_id: str, month: "budget.Month") -> dict:
    """Everything the usage section shows. With no database the usage and allowance are
    `None` and a sentence says why — not an empty month, which would read as "none used"."""
    today = ist_today()
    current = budget.month_of(today)
    base = {"month": month.as_dict(), "current_month": current.as_dict(),
            "choices": month_choices(today), "not_covered": list(NOT_COVERED)}
    if db is None:
        return {**base, "usage": None, "allowance": None, "first_recorded_at": None,
                "unread": NO_DATABASE}
    try:
        folded = budget.fold(
            db.rpc("ai_usage_by_day", _window(month, firm_id)).execute().data or [],
            db.rpc("ai_usage_by_feature", _window(month, firm_id)).execute().data or [])
        limits, updated_at = read_limits(db, firm_id)
        if month.key == current.key:
            used = budget.Used(folded["totals"]["tokens"], folded["totals"]["pages"])
        else:
            row = (db.rpc("ai_usage_totals", _window(current, firm_id)).execute().data or [{}])[0]
            used = budget.Used(int(row.get("tokens") or 0), int(row.get("pages") or 0))
        first = _first_recorded(db, firm_id)
    except Exception:                                            # noqa: BLE001
        _logger.warning("ai usage: could not read the usage for a firm", exc_info=True)
        return {**base, "usage": None, "allowance": None, "first_recorded_at": None,
                "unread": "The usage could not be read just now."}
    return {**base, "usage": folded, "first_recorded_at": first, "unread": None,
            "allowance": {"limits": limits.as_dict(), "updated_at": updated_at,
                          "standing": budget.standing(limits, used, month=current)}}


def set_limits(db: Any, firm_id: str, user_id: Optional[str],
               limits: "budget.Limits") -> "budget.Limits":
    """Replace the allowance. Both limits travel together: `None` is "no limit", so a
    Partner clearing one keeps the other by sending it back, and clearing both is the
    same write. The privileged client writes it (the table's writes are service-role-only)
    after the route's rbac(); this firm's cached entry is dropped so the change is felt at
    the next call on this server."""
    previous, _ = read_limits(db, firm_id)
    db.table("ai_firm_budgets").upsert({
        "firm_id": firm_id,
        "monthly_token_limit": limits.monthly_tokens,
        "monthly_page_limit": limits.monthly_pages,
        "set_by": user_id,
        "updated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }, on_conflict="firm_id").execute()
    budget_gate.invalidate(firm_id)
    return previous
