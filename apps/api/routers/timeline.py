"""
Timeline REST endpoint — exposes client_timeline_events for the UI audit trail.
"""
import logging
import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Annotated, Literal, Optional

from core.list_window import MAX_LIST_LIMIT, probe, split
from models.common import api_response
from core.permissions import rbac
from models.fy import FYLabel, OptionalFYLabel

_logger = logging.getLogger("caflow.timeline")

router = APIRouter(prefix="/api/timeline", tags=["timeline"])

_USE_MOCK = not os.environ.get("SUPABASE_URL")


def _window(rows: list[dict], limit: int):
    """The answer: the window, and whether the read found a row beyond it (the probe row is dropped by `split`)."""
    events, has_more = split(rows, limit)
    return api_response(True, {
        "events": events,
        "returned": len(events),
        "has_more": has_more,
        "limit": limit,
        "max_limit": MAX_LIST_LIMIT,
    })


@router.get("")
def list_timeline_events(
    client_id: str = Query(...),
    category: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    financial_year: Annotated[OptionalFYLabel, Query()] = None,
    entity_type: Optional[str] = Query(None, max_length=64),
    entity_id: Optional[UUID] = Query(None),
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = 50,
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """
    A window of a client's timeline events, newest first, and whether older ones exist.

    `entity_type` and `entity_id` narrow the read to the events of ONE record (a sales invoice, a purchase bill), which is
    what a document's own activity panel needs. Before they existed the panels read the client's latest hundred events of
    every kind and kept the ones that named their document in the browser, so a document older than the client's hundredth
    event read "No activity recorded yet" - an empty state that was only an artefact of where the window stopped
    (POST-A-259). `has_more` comes from the read (core/list_window): one row more than the window is asked for, and it is
    never returned.
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
        if entity_type:
            events = [e for e in events if e.get("entity_type") == entity_type]
        if entity_id:
            events = [e for e in events if str(e.get("entity_id")) == str(entity_id)]
        events = sorted(events, key=lambda e: e["created_at"], reverse=True)
        return _window(events[offset: offset + probe(limit)], limit)

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
    if entity_type:
        q = q.eq("entity_type", entity_type)
    if entity_id:
        q = q.eq("entity_id", str(entity_id))
    # `id` breaks a tie between two events stamped the same instant, so the same row is never on two pages.
    res = q.order("created_at", desc=True).order("id", desc=True).range(offset, offset + probe(limit) - 1).execute()
    return _window(res.data or [], limit)


class TimelineEventIn(BaseModel):
    """What a browser may say about an event it wants recorded, and nothing it may say about WHO recorded it.

    There is no firm, no actor and no pin here, on purpose (POST-A-228): the firm is the caller's, the actor is the signed-in
    person, and an event is born unpinned. A field a caller adds anyway is ignored rather than refused, so a browser tab left
    open across the deploy that still sends them is not broken by it.
    """
    client_id: str
    financial_year: FYLabel
    category: Literal["accounting", "compliance", "payroll", "tax", "document", "work", "ai", "portal", "team"]
    event_type: str = Field(..., min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$")
    severity: Literal["info", "success", "warning", "critical"] = "info"
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    action_label: Optional[str] = Field(None, max_length=80)
    # A path inside the product. A link to somewhere else on a client's activity feed is a phishing link with the firm's name
    # on it, so only a path that starts with a single "/" is accepted.
    action_url: Optional[str] = Field(None, max_length=300, pattern=r"^/([^/\s][^\s]*)?$")
    entity_type: Optional[str] = Field(None, max_length=60)
    entity_id: Optional[str] = Field(None, max_length=80)
    amount_paise: Optional[int] = Field(None, ge=0)
    visibility: Literal["all", "internal", "partner_only"] = "all"


@router.post("/events")
def write_timeline_event(
    body: TimelineEventIn,
    current_user: dict = Depends(rbac("timeline", "write")),
):
    """Record an event on a client's activity feed, as the signed-in person.

    The browser used to INSERT these over PostgREST with the actor type, id and name it chose, so a staff member could write an
    entry naming someone else (the audit log is a separate append-only table and was never affected). The server door sets the
    firm from the caller, the actor type to "user", the actor id to the signed-in person's sign-in id (the convention
    `audit_log` already uses) and the name to their full name or email, and migration 515 takes the signed-in INSERT away.
    The client must be one the caller may act on: 404 for a client in another firm or outside their assignment, the same
    answer as a client that does not exist.
    """
    from core.authz import assert_client_access
    from repositories.client_repository import client_repo
    from services.timeline_service import timeline_service

    assert_client_access(current_user, body.client_id, detail="Client not found")
    firm_id = current_user.get("firm_id")
    if not client_repo.find_by_id(body.client_id, firm_id):
        raise HTTPException(status_code=404, detail="Client not found")

    try:
        event = timeline_service.record_event(
            client_id=body.client_id, firm_id=firm_id, financial_year=body.financial_year,
            category=body.category, event_type=body.event_type, title=body.title,
            description=body.description, severity=body.severity, entity_type=body.entity_type,
            entity_id=body.entity_id, amount_paise=body.amount_paise,
            actor_id=current_user.get("auth_user_id"),
            actor_name=current_user.get("full_name") or current_user.get("email"),
            actor_type="user", action_label=body.action_label, action_url=body.action_url,
            visibility=body.visibility,
        )
    except Exception as exc:
        _logger.exception("timeline event not written for client=%s", body.client_id)
        raise HTTPException(
            status_code=503,
            detail="The event could not be recorded on the client's activity feed. Nothing else was changed; try again.",
        ) from exc
    return api_response(True, event)
