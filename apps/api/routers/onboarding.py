"""
Firm onboarding endpoints.
POST /api/onboarding/firm       — create firm + first Partner user (JWT-authenticated)
POST /api/onboarding/invite     — invite user to firm (Partner/Manager only)
GET  /api/onboarding/status     — onboarding completeness check (Partner/Manager only)
"""
import re
import secrets
import logging
from domain.gst.gstin import problem_with as gstin_problem
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional
from models.common import api_response
from core.supabase_client import get_service_supabase
from core.auth import get_jwt_user
from core.permissions import rbac

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])
_logger = logging.getLogger("caflow.onboarding")

# PAN validation (AAAAA9999A) — IT Act format
_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
# GSTIN (CGST Act Section 25)
_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


class FirmCreate(BaseModel):
    firm_name: str
    firm_email: EmailStr          # maps to firms.email (NOT NULL)
    # PAN is optional at signup time (the signup form does not collect it). When
    # provided it is validated, de-duplicated, and used to provision the firm's
    # internal practice client. When absent the firm is created without a PAN and
    # the internal client is provisioned later (once PAN is set) via
    # POST /api/practice/provision.
    pan: Optional[str] = None
    gstin: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    partner_name: str
    entity_type: Optional[str] = None


class InviteUser(BaseModel):
    email: EmailStr
    role: str


@router.post("/firm")
def create_firm(
    body: FirmCreate,
    jwt_user: dict = Depends(get_jwt_user),
):
    """
    Create a new firm + first Partner user record.
    Requires a valid Supabase Auth JWT. The authenticated user becomes the Partner.
    Called immediately after Supabase Auth sign-up completes.
    """
    pan: Optional[str] = None
    if body.pan:
        pan = body.pan.upper()
        if not _PAN_RE.match(pan):
            raise HTTPException(status_code=400, detail="Invalid PAN format. Expected: AAAAA9999A")

    if body.gstin:
        gstin = body.gstin.upper()
        # Shape AND check digit. A firm's own GSTIN goes on every invoice it
        # raises, so a transposition here is not caught later by anything —
        # it is simply wrong on every document from day one.
        problem = gstin_problem(gstin)
        if problem:
            raise HTTPException(status_code=400, detail=problem)
    else:
        gstin = None

    auth_user_id = jwt_user["auth_user_id"]
    db = get_service_supabase()

    # Prevent duplicate firm creation for same auth user
    existing_user = db.table("users").select("id, firm_id").eq("auth_user_id", auth_user_id).execute()
    if existing_user.data:
        raise HTTPException(status_code=409, detail="This user already belongs to a firm")

    # Prevent duplicate PAN (only when a PAN was supplied)
    if pan:
        existing_pan = db.table("firms").select("id").eq("pan", pan).execute()
        if existing_pan.data:
            raise HTTPException(status_code=409, detail="A firm with this PAN already exists")

    # Insert firm — column names match live schema (name, email, pan, gstin, address, city, state)
    firm = db.table("firms").insert({
        "name": body.firm_name,          # firms.name (NOT NULL)
        "email": str(body.firm_email),   # firms.email (NOT NULL)
        "pan": pan,
        "gstin": gstin,
        "phone": body.phone,
        "address": body.address,         # firms.address (nullable)
        "city": body.city,
        "state": body.state,
    }).execute().data[0]

    firm_id = firm["id"]

    # Create Partner user record linking auth user to this firm
    db.table("users").insert({
        "firm_id": firm_id,
        "auth_user_id": auth_user_id,
        "full_name": body.partner_name,
        "email": str(body.firm_email),
        "role": "Partner",
    }).execute()

    # Batch 3.1: seed the firm-wide master Chart of Accounts (Migration-057
    # architecture; seeded with a NULL client column) so posting can always resolve its accounts.
    # Idempotent + non-fatal (re-runnable); firm creation must still succeed.
    try:
        from services.coa_seed_service import seed_firm_coa
        seed_firm_coa(firm_id)
    except Exception as e:  # pragma: no cover - defensive
        _logger.error("Firm CoA seeding failed for firm %s: %s", firm_id, e)

    # Amendment v1.1: provision the firm-as-internal-client (idempotent). Reuses
    # the firm's own PAN/GSTIN. Non-fatal — firm creation must still succeed even
    # if provisioning is skipped (it can be re-run later via POST /api/practice/provision).
    try:
        from services.internal_client_service import provision as _provision_internal
        _provision_internal(
            firm_id, body.firm_name, pan,
            entity_type=(body.entity_type or "Partnership"), gstin=gstin,
            state=body.state, actor_id=auth_user_id,
        )
    except Exception as e:  # pragma: no cover - defensive
        _logger.error("Internal-client provisioning failed for firm %s: %s", firm_id, e)

    return api_response(True, {"firm": firm, "message": "Firm created successfully"})


@router.post("/seed-coa")
def seed_coa(current_user: dict = Depends(rbac("accounting", "write"))):
    """Idempotently seed the firm-wide CANONICAL master CoA for the caller's firm
    (single source of truth: coa_seed_service.STANDARD_COA). Skips if the firm
    already has firm-wide accounts. This is the path the onboarding UI calls
    instead of inserting accounts directly from the browser (Phase 3.3A, Part E)."""
    firm_id = current_user.get("firm_id")
    if not firm_id:
        return api_response(False, None, "No firm found for the current user.")
    from services.coa_seed_service import seed_firm_coa
    return api_response(True, seed_firm_coa(firm_id))


@router.post("/invite")
def invite_user(
    body: InviteUser,
    current_user: dict = Depends(rbac("team", "write")),
):
    """
    Invite a user to the authenticated Partner's firm. Sends email if RESEND_API_KEY is set.
    Requires Partner role (team.write permission).
    """
    valid_roles = {"Partner", "Manager", "Executive", "Reviewer", "Client"}
    if body.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}")

    firm_id = current_user["firm_id"]
    db = get_service_supabase()

    # Look up firm name — column is "name" not "firm_name"
    firm = db.table("firms").select("name").eq("id", firm_id).maybe_single().execute().data
    firm_name = firm["name"] if firm else "Your firm"

    token = secrets.token_urlsafe(32)
    from core.urls import frontend_base
    invite_link = (f"{frontend_base()}/accept-invite"
                   f"?token={token}&firm_id={firm_id}&role={body.role}")

    db.table("pending_invites").insert({
        "firm_id": firm_id,
        "email": str(body.email),
        "role": body.role,
        "token": token,
        "invited_by": current_user.get("auth_user_id"),
    }).execute()

    from services.email_service import send_firm_invite
    send_firm_invite(
        to=str(body.email),
        firm_name=firm_name,
        inviter_name=current_user.get("full_name", ""),
        role=body.role,
        invite_link=invite_link,
    )

    return api_response(True, {"message": f"Invitation sent to {body.email}"})


@router.get("/status")
def onboarding_status(
    current_user: dict = Depends(rbac("firm", "read")),
):
    """Return onboarding completeness for the authenticated user's firm."""
    firm_id = current_user["firm_id"]
    db = get_service_supabase()

    firm = db.table("firms").select("*").eq("id", firm_id).maybe_single().execute().data
    if not firm:
        raise HTTPException(status_code=404, detail="Firm not found")

    users = db.table("users").select("id").eq("firm_id", firm_id).execute().data or []
    # Guardrail G2: the internal practice client does not count as an onboarded client.
    clients = db.table("clients").select("id").eq("firm_id", firm_id).eq("is_internal", False).execute().data or []

    checks = {
        "firm_created": True,
        "gstin_configured": bool(firm.get("gstin")),
        "team_members_added": len(users) > 1,
        "first_client_added": len(clients) > 0,
    }
    score = sum(checks.values())
    return api_response(True, {"checks": checks, "score": score, "total": len(checks)})
