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
from services import portal_access_service, employee_portal_service

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


# THE SECTIONS THIS PORTAL HAS, AND WHAT EACH ONE CANNOT DO.
#
# ⚠️ ALL SEVEN WERE `available: True` AND THE DASHBOARD RENDERED FOUR. The
# browser kept its own `DATA_SECTIONS = new Set([...])` of the four it knew how
# to load and filtered the other three out of its own tab row, so the API told
# a client Documents, Document Requests and Messages existed and the screen
# silently disagreed — on the one surface the outside world sees, with the API
# making the claim. The three are served now (`portal_data`) and the browser
# keeps no list: it renders what this sends, which is the Schedule III caption
# rule applied to the portal.
#
# `note` is the THIRD STATE this list needed and did not have. A section can be
# present and complete, absent, or present with something a client has to be
# told — and the one that matters is Document Requests, where fulfilling means
# writing into the firm's own document store and migration 005's storage
# policies admit no portal principal. Saying so beats a button that 403s, and
# beats hiding the section, which is what the browser used to do.
_DASHBOARD_SECTIONS = [
    {"key": "documents",  "label": "Documents",          "available": True,
     "note": None},
    {"key": "requests",   "label": "Document Requests",  "available": True,
     "note": ("You can see what your accountant has asked for. Uploading here "
              "is not available yet — send the papers the way you usually do, "
              "or reply under Messages.")},
    {"key": "messages",   "label": "Messages",           "available": True,
     "note": None},
    {"key": "invoices",   "label": "Invoices",           "available": True,
     "note": None},
    {"key": "statements", "label": "Statements",         "available": True,
     "note": None},
    {"key": "reminders",  "label": "Payment Reminders",  "available": True,
     "note": None},
    {"key": "compliance", "label": "Compliance Status",  "available": True,
     "note": None},
]


@router.get("/dashboard")
def portal_dashboard(portal: dict = Depends(get_current_portal_client)):
    """Dashboard SHELL — section scaffold only, no business data (4.5.1 foundation)."""
    return api_response(True, {
        "client_id": portal["client_id"],
        "contact": {"email": portal["email"], "name": portal["name"]},
        "sections": _DASHBOARD_SECTIONS,
    })


# ─── Employee portal activation ──────────────────────────────────────────────

class AcceptEmployeeInviteBody(BaseModel):
    token: str


@router.post("/employee/accept-invite")
def accept_employee_invite(body: AcceptEmployeeInviteBody,
                           jwt_user: dict = Depends(get_jwt_user)):
    """Bind the caller's Supabase identity to the employee they were invited as.

    Deliberately guarded by get_jwt_user ONLY — not rbac, and not
    get_current_portal_client. An employee is neither firm staff nor a client
    portal contact: before this call succeeds they have no row in `users` and no
    client_portal_users membership, so every other dependency in this codebase
    would reject them. The invite token is what authorises the bind; the JWT
    only says which identity to bind it to.

    Runs through the backend's service-role client because RLS cannot help here:
    migration 262 scopes an employee's own row on auth_user_id AND
    portal_enabled, and at this moment neither is set yet.
    """
    result = employee_portal_service.accept_employee_invite(
        body.token, jwt_user.get("auth_user_id"), jwt_user.get("email"))
    return api_response(True, result)
