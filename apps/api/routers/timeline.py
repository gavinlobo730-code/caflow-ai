"""
Timeline REST endpoint — exposes client_timeline_events for the UI audit trail.
"""
import os
from fastapi import APIRouter, Depends, Query
from typing import Optional

from models.common import api_response
from core.permissions import rbac

router = APIRouter(prefix="/api/timeline", tags=["timeline"])

_USE_MOCK = not os.environ.get("SUPABASE_URL")


@router.get("")
def list_timeline_events(
    client_id: str = Query(...),
    category: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    financial_year: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """
    Return paginated timeline events for a client.
    Events are ordered newest-first.
    """
    # Hoisted ABOVE the mock branch: it returns real (mock) events and used to
    # sit before this check, so the whole in-memory test run — which is where
    # _USE_MOCK is true — exercised the unguarded path. Same placement bug as
    # currencies.get_currency_policy.
    from core.authz import assert_client_access
    assert_client_access(current_user, client_id)

    if _USE_MOCK:
        from services.timeline_service import MOCK_TIMELINE_EVENTS
        firm_id = current_user.get("firm_id")
        events = [e for e in MOCK_TIMELINE_EVENTS if e["client_id"] == client_id and e.get("firm_id") == firm_id]
        if category:
            events = [e for e in events if e.get("category") == category]
        if severity:
            events = [e for e in events if e.get("severity") == severity]
        if financial_year:
            events = [e for e in events if e.get("financial_year") == financial_year]
        events = sorted(events, key=lambda e: e["created_at"], reverse=True)
        return api_response(True, events[offset: offset + limit])

    from core.supabase_client import get_supabase
    db = get_supabase()
    q = (
        db.table("client_timeline_events")
        .select("*")
        .eq("client_id", client_id)
        .eq("firm_id", current_user.get("firm_id"))
        .is_("deleted_at", "null")
    )
    if category:
        q = q.eq("category", category)
    if severity:
        q = q.eq("severity", severity)
    if financial_year:
        q = q.eq("financial_year", financial_year)
    res = q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return api_response(True, res.data or [])
