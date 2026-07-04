"""
Portal Self (client-facing) router — Phase 4.5.1.

Client-authenticated via get_current_portal_client (Supabase JWT → portal contact).
Foundation only: identity (/me) and the dashboard SHELL (/dashboard) that declares
which sections exist. It exposes NO invoice / statement / compliance / reminder data
yet — those land in Phase 4.5.2+. Strict client isolation; no staff privilege.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from models.common import api_response
from core.auth import get_jwt_user
from core.portal_auth import get_current_portal_client
from services import portal_access_service

router = APIRouter(prefix="/api/portal", tags=["portal_self"])


@router.get("/memberships")
def portal_memberships(jwt_user: dict = Depends(get_jwt_user)):
    """All ALREADY-ACTIVE client memberships for the authenticated identity (the
    client switcher source). Unlike /me and /dashboard, this never forces a
    selection. Read-only — accepting a new invite is a separate, explicit,
    token-gated action (see POST /accept-invite, F22 fix)."""
    ms = portal_access_service.list_portal_memberships(
        jwt_user.get("auth_user_id"), jwt_user.get("email"))
    if not ms:
        raise HTTPException(status_code=403, detail="Not a portal user.")
    return api_response(True, {"memberships": [{"client_id": m["client_id"], "name": m.get("name")} for m in ms]})


class AcceptPortalInviteBody(BaseModel):
    token: str


@router.post("/accept-invite")
def accept_portal_invite(body: AcceptPortalInviteBody, jwt_user: dict = Depends(get_jwt_user)):
    """Accept ONE portal invite by its single-use token (F22 fix). Must be called
    once per client relationship before that client appears in /memberships."""
    membership = portal_access_service.accept_portal_invite(
        body.token, jwt_user.get("auth_user_id"), jwt_user.get("email"))
    return api_response(True, {"client_id": membership["client_id"], "name": membership.get("name")})


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


# Dashboard sections. documents/messages/requests are RLS-direct surfaces; the
# fee-relationship + compliance surfaces (Phase 4.5.2) are served by the
# client-facing /api/portal/self/* endpoints (portal_data router).
_DASHBOARD_SECTIONS = [
    {"key": "documents",  "label": "Documents",          "available": True},
    {"key": "requests",   "label": "Document Requests",  "available": True},
    {"key": "messages",   "label": "Messages",           "available": True},
    {"key": "invoices",   "label": "Invoices",           "available": True},
    {"key": "statements", "label": "Statements",         "available": True},
    {"key": "reminders",  "label": "Payment Reminders",  "available": True},
    {"key": "compliance", "label": "Compliance Status",  "available": True},
]


@router.get("/dashboard")
def portal_dashboard(portal: dict = Depends(get_current_portal_client)):
    """Dashboard SHELL — section scaffold only, no business data (4.5.1 foundation)."""
    return api_response(True, {
        "client_id": portal["client_id"],
        "contact": {"email": portal["email"], "name": portal["name"]},
        "sections": _DASHBOARD_SECTIONS,
    })
