"""
Portal Self (client-facing) router — Phase 4.5.1.

Client-authenticated via get_current_portal_client (Supabase JWT → portal contact).
Foundation only: identity (/me) and the dashboard SHELL (/dashboard) that declares
which sections exist. It exposes NO invoice / statement / compliance / reminder data
yet — those land in Phase 4.5.2+. Strict client isolation; no staff privilege.
"""
from fastapi import APIRouter, Depends, HTTPException

from models.common import api_response
from core.auth import get_jwt_user
from core.portal_auth import get_current_portal_client
from services import portal_access_service

router = APIRouter(prefix="/api/portal", tags=["portal_self"])


@router.get("/memberships")
def portal_memberships(jwt_user: dict = Depends(get_jwt_user)):
    """All client memberships for the authenticated identity (the client switcher
    source). Unlike /me and /dashboard, this never forces a selection."""
    ms = portal_access_service.list_portal_memberships(
        jwt_user.get("auth_user_id"), jwt_user.get("email"))
    if not ms:
        raise HTTPException(status_code=403, detail="Not a portal user.")
    return api_response(True, {"memberships": [{"client_id": m["client_id"], "name": m.get("name")} for m in ms]})


@router.get("/me")
def portal_me(portal: dict = Depends(get_current_portal_client)):
    """The authenticated portal contact's own identity (their single client)."""
    return api_response(True, {
        "client_id": portal["client_id"],
        "firm_id": portal["firm_id"],
        "contact_id": portal["portal_contact_id"],
        "email": portal["email"],
        "name": portal["name"],
    })


# Dashboard SHELL (foundation). `available=False` sections are scaffolding for
# Phase 4.5.2+ and intentionally carry NO data yet. The already-live RLS-direct
# surfaces (documents/messages/requests) are marked available.
_DASHBOARD_SECTIONS = [
    {"key": "documents",  "label": "Documents",          "available": True},
    {"key": "requests",   "label": "Document Requests",  "available": True},
    {"key": "messages",   "label": "Messages",           "available": True},
    {"key": "invoices",   "label": "Invoices",           "available": False},
    {"key": "statements", "label": "Statements",         "available": False},
    {"key": "reminders",  "label": "Payment Reminders",  "available": False},
    {"key": "compliance", "label": "Compliance Status",  "available": False},
]


@router.get("/dashboard")
def portal_dashboard(portal: dict = Depends(get_current_portal_client)):
    """Dashboard SHELL — section scaffold only, no business data (4.5.1 foundation)."""
    return api_response(True, {
        "client_id": portal["client_id"],
        "contact": {"email": portal["email"], "name": portal["name"]},
        "sections": _DASHBOARD_SECTIONS,
    })
