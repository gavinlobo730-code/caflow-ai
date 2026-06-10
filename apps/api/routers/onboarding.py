"""
Firm onboarding endpoints.
POST /api/onboarding/firm       — create firm + first Partner user
POST /api/onboarding/invite     — invite user to firm (sends email)
GET  /api/onboarding/status     — onboarding completeness check
"""
import os
import secrets
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional
from models.common import api_response
from core.supabase_client import get_supabase

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

# PAN validation (AAAAA9999A) — IT Act format
import re
_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
# GSTIN (CGST Act Section 25)
_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


class FirmCreate(BaseModel):
    firm_name: str
    pan: str
    gstin: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    partner_name: str
    partner_email: EmailStr
    partner_auth_user_id: str


class InviteUser(BaseModel):
    email: EmailStr
    role: str
    inviter_firm_id: str
    inviter_auth_user_id: str


@router.post("/firm")
def create_firm(body: FirmCreate):
    """
    Create a new firm + Partner user record.
    Called after Supabase Auth sign-up to complete firm setup.
    """
    pan = body.pan.upper()
    if not _PAN_RE.match(pan):
        raise HTTPException(status_code=400, detail="Invalid PAN format. Expected: AAAAA9999A")

    if body.gstin:
        gstin = body.gstin.upper()
        if not _GSTIN_RE.match(gstin):
            raise HTTPException(status_code=400, detail="Invalid GSTIN format")
    else:
        gstin = None

    db = get_supabase()

    # Check for duplicate PAN
    existing = db.table("firms").select("id").eq("pan", pan).execute()
    if existing.data:
        raise HTTPException(status_code=409, detail="A firm with this PAN already exists")

    firm = db.table("firms").insert({
        "firm_name": body.firm_name,
        "pan": pan,
        "gstin": gstin,
        "address": body.address,
        "city": body.city,
        "state": body.state,
    }).execute().data[0]

    firm_id = firm["id"]

    # Create Partner user record
    db.table("users").insert({
        "firm_id": firm_id,
        "auth_user_id": body.partner_auth_user_id,
        "full_name": body.partner_name,
        "email": body.partner_email,
        "role": "Partner",
    }).execute()

    return api_response(True, {"firm": firm, "message": "Firm created successfully"})


@router.post("/invite")
def invite_user(body: InviteUser):
    """Invite a user to join the firm. Sends email if RESEND_API_KEY is set."""
    valid_roles = {"Partner", "Manager", "Executive", "Reviewer", "Client"}
    if body.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}")

    db = get_supabase()

    # Look up inviter
    inviter = db.table("users")\
        .select("full_name, firm_id, role")\
        .eq("auth_user_id", body.inviter_auth_user_id)\
        .eq("firm_id", body.inviter_firm_id)\
        .maybe_single().execute().data

    if not inviter:
        raise HTTPException(status_code=403, detail="Inviter not found")
    if inviter["role"] not in ("Partner", "Manager"):
        raise HTTPException(status_code=403, detail="Only Partners and Managers can invite users")

    # Look up firm name
    firm = db.table("firms").select("firm_name").eq("id", body.inviter_firm_id).maybe_single().execute().data
    firm_name = firm["firm_name"] if firm else "Your firm"

    # Generate invite token stored in a hypothetical invites table or just send magic link
    token = secrets.token_urlsafe(32)
    frontend_url = os.environ.get("FRONTEND_URL", "https://caflow-ai.pages.dev")
    invite_link = f"{frontend_url}/accept-invite?token={token}&firm_id={body.inviter_firm_id}&role={body.role}"

    # Store pending invite
    db.table("pending_invites").insert({
        "firm_id": body.inviter_firm_id,
        "email": body.email,
        "role": body.role,
        "token": token,
        "invited_by": body.inviter_auth_user_id,
    }).execute()

    # Send invite email (non-fatal)
    from services.email_service import send_firm_invite
    send_firm_invite(
        to=body.email,
        firm_name=firm_name,
        inviter_name=inviter["full_name"],
        role=body.role,
        invite_link=invite_link,
    )

    return api_response(True, {"message": f"Invitation sent to {body.email}"})


@router.get("/status")
def onboarding_status(firm_id: str):
    """Return onboarding completeness for a firm."""
    db = get_supabase()

    firm = db.table("firms").select("*").eq("id", firm_id).maybe_single().execute().data
    if not firm:
        raise HTTPException(status_code=404, detail="Firm not found")

    users = db.table("users").select("id").eq("firm_id", firm_id).execute().data or []
    clients = db.table("clients").select("id").eq("firm_id", firm_id).execute().data or []

    checks = {
        "firm_created": True,
        "gstin_configured": bool(firm.get("gstin")),
        "team_members_added": len(users) > 1,
        "first_client_added": len(clients) > 0,
    }
    score = sum(checks.values())
    return api_response(True, {"checks": checks, "score": score, "total": len(checks)})
