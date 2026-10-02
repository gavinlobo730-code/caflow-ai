"""Fetches what `domain/billing/time_rate` needs, and writes the two rates
(practice_management-11). It decides nothing about a rate.

SERVICE ROLE, WITH THE FIRM FILTER ON EVERY QUERY. `users` shows a caller only
their own row under their own JWT (migration 153's grants and `users_own_row_
select`), and `authenticated` may update only `full_name` on it — so a staff
member's default rate cannot be read for a colleague, or written at all, as the
caller. The rate is resolved for the person whose time it is, which is often not
the person asking.

NOTHING HERE READS `cost_rate_paise`. What an hour costs the firm is not what it
bills, and the column's own comment says it is "NEVER used in any computation".
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import HTTPException

from domain.billing import time_rate as rule
from core import db_provider

_USE_MOCK = not os.environ.get("SUPABASE_URL")

# Mock stores (mock/dev mode only).
MOCK_USER_RATES: dict[str, Optional[int]] = {}
MOCK_ENGAGEMENTS: list[dict] = []


def reset_mock_stores() -> None:  # test helper
    MOCK_USER_RATES.clear()
    MOCK_ENGAGEMENTS.clear()


_db = db_provider.service_db


def check_rate(rate: object) -> Optional[int]:
    """A rate somebody is SETTING: whole non-negative paise, or None to clear.
    Anything else is refused with a sentence rather than stored as something
    else."""
    if rate is None:
        return None
    cleaned = rule.clean_rate(rate)
    if cleaned is None:
        raise HTTPException(
            status_code=422,
            detail="A billing rate is a whole number of paise, zero or more — "
                   "or empty to clear it. ₹2,500 an hour is 250000.")
    return cleaned


# ── engagements ──────────────────────────────────────────────────────────────

def engagements_for_client(firm_id: str, client_id: str) -> list[dict]:
    if _USE_MOCK:
        return [e for e in MOCK_ENGAGEMENTS
                if e.get("firm_id") == firm_id and e.get("client_id") == client_id]
    return ((_db().table("fee_engagements")
             .select("id, client_id, service_type, status, billable_rate_paise")
             .eq("firm_id", firm_id).eq("client_id", client_id)
             .order("created_at", desc=True).execute().data) or [])


def engagement_choices(firm_id: str, client_id: str) -> dict:
    """The engagements a time entry for this client may be recorded against, and
    the one it defaults to. The OVERRIDE rate is not served: it is fee economics
    (`billing:write`), and a person choosing an engagement does not need it."""
    rows = engagements_for_client(firm_id, client_id)
    choice = rule.default_engagement(rows)
    live = [{"id": str(e["id"]), "service_type": e.get("service_type"), "status": e.get("status")}
            for e in rows if e.get("status") in rule.ACTIVE_ENGAGEMENT_STATUSES]
    return {"engagements": live, "default_engagement_id": choice.engagement_id,
            "reason": choice.reason}


def _engagement(firm_id: str, engagement_id: str) -> Optional[dict]:
    if _USE_MOCK:
        return next((e for e in MOCK_ENGAGEMENTS
                     if str(e.get("id")) == str(engagement_id) and e.get("firm_id") == firm_id), None)
    rows = (_db().table("fee_engagements")
            .select("id, client_id, service_type, status, billable_rate_paise")
            .eq("firm_id", firm_id).eq("id", engagement_id).limit(1).execute().data) or []
    return rows[0] if rows else None


def user_rate(firm_id: str, user_id: str) -> Optional[int]:
    if not user_id:
        return None
    if _USE_MOCK:
        return MOCK_USER_RATES.get(str(user_id))
    rows = (_db().table("users").select("default_billable_rate_paise")
            .eq("firm_id", firm_id).eq("id", user_id).limit(1).execute().data) or []
    return rule.clean_rate(rows[0].get("default_billable_rate_paise")) if rows else None


# ── resolution ───────────────────────────────────────────────────────────────

def resolve_for_entry(firm_id: str, user_id: str, client_id: Optional[str],
                      engagement_id: Optional[str], *, entry_rate: object = None,
                      is_billable: bool = True) -> dict:
    """The engagement an entry belongs to and the rate it bills at.

    * a named engagement must exist in this firm AND belong to the entry's
      client — refused (422), because pricing an hour under another client's
      override is a wrong invoice with no error;
    * none named: the client's single ACTIVE engagement, or none and a reason —
      never the first of several;
    * a non-billable entry carries NO rate: a rate on work that is not billed is
      a figure that reads as money owed.

    Returns `{engagement_id, billable_rate_paise, rate_source, notes}`.
    """
    notes: list[str] = []
    engagement: Optional[dict] = None
    if engagement_id:
        if not client_id:
            raise HTTPException(status_code=422,
                                detail="An engagement belongs to a client — choose the client first.")
        engagement = _engagement(firm_id, engagement_id)
        if not engagement or str(engagement.get("client_id")) != str(client_id):
            raise HTTPException(status_code=422,
                                detail="That engagement is not one of this client's.")
    elif client_id:
        choice = rule.default_engagement(engagements_for_client(firm_id, client_id))
        engagement_id = choice.engagement_id
        if choice.engagement_id:
            engagement = next((e for e in choice.active if str(e["id"]) == choice.engagement_id), None)
        elif choice.reason:
            notes.append(choice.reason)

    if not is_billable:
        return {"engagement_id": engagement_id, "billable_rate_paise": None,
                "rate_source": None, "notes": notes}

    res = rule.resolve_rate(
        entry_rate_paise=entry_rate,
        engagement_rate_paise=(engagement or {}).get("billable_rate_paise"),
        user_rate_paise=user_rate(firm_id, user_id))
    if not res.has_rate:
        notes.append("No billing rate is recorded for you or for this engagement, so this time "
                     "will be listed as 'no rate' until one is.")
    return {"engagement_id": engagement_id, "billable_rate_paise": res.rate_paise,
            "rate_source": res.source, "notes": notes}


# ── setting the two rates ────────────────────────────────────────────────────

def list_staff_rates(firm_id: str) -> list[dict]:
    if _USE_MOCK:
        return [{"user_id": u, "default_billable_rate_paise": r}
                for u, r in MOCK_USER_RATES.items()]
    rows = (_db().table("users")
            .select("id, full_name, email, role, is_active, default_billable_rate_paise")
            .eq("firm_id", firm_id).is_("deleted_at", None).order("full_name").execute().data) or []
    return [{"user_id": r["id"], "full_name": r.get("full_name") or r.get("email"),
             "role": r.get("role"), "is_active": r.get("is_active") is not False,
             "default_billable_rate_paise": rule.clean_rate(r.get("default_billable_rate_paise"))}
            for r in rows]


def set_staff_rate(firm_id: str, user_id: str, rate: object) -> dict:
    """Set (or, with None, clear) a person's default billing rate."""
    cleaned = check_rate(rate)
    if _USE_MOCK:
        MOCK_USER_RATES[str(user_id)] = cleaned
        return {"user_id": user_id, "default_billable_rate_paise": cleaned}
    res = (_db().table("users").update({"default_billable_rate_paise": cleaned})
           .eq("firm_id", firm_id).eq("id", user_id).execute())
    if not res.data:
        # The firm filter is the scope: another firm's person matches no row.
        raise HTTPException(status_code=404, detail="Team member not found")
    return {"user_id": user_id, "default_billable_rate_paise": cleaned}


def set_engagement_rate(firm_id: str, engagement_id: str, rate: object) -> dict:
    """Set (or clear) the billing-rate OVERRIDE of one fee engagement."""
    cleaned = check_rate(rate)
    if _USE_MOCK:
        e = _engagement(firm_id, engagement_id)
        if not e:
            raise HTTPException(status_code=404, detail="Engagement not found")
        e["billable_rate_paise"] = cleaned
        return {"engagement_id": engagement_id, "billable_rate_paise": cleaned}
    res = (_db().table("fee_engagements").update({"billable_rate_paise": cleaned})
           .eq("firm_id", firm_id).eq("id", engagement_id).execute())
    if not res.data:
        raise HTTPException(status_code=404, detail="Engagement not found")
    return {"engagement_id": engagement_id, "billable_rate_paise": cleaned}
