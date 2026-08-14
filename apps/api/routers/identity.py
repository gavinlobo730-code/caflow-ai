"""
M6 — Identity Administration backend (audited, server-side).

Replaces the client-side identity mutations in team/page.tsx with authorized,
audited backend APIs. Partner-only writes (rbac team:write); Manager+ reads.

Capabilities: create user, activate, suspend (kills sessions), reactivate, change
role, force-logout (single + firm-wide), login history. Every mutation is written
to audit_log; session-affecting actions also record a login_events row and bump
users.sessions_revoked_at so existing JWTs are rejected immediately.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from models.common import api_response
from core.auth import get_current_user, get_jwt_user
from core.permissions import rbac, Role, canonical_role, get_accessible_resources
from repositories.user_repository import user_repo
from repositories.login_events_repository import login_events_repo
from services.audit_service import log_event

router = APIRouter(prefix="/api/identity", tags=["identity"])

_CANONICAL = {r.value for r in Role}

# F21 fix: an invite must be accepted within this window. Chosen to match the
# window already advertised in the (previously non-functional) invite email
# copy — "This link expires in 7 days" (services/email_service.send_firm_invite).
_INVITE_TTL = timedelta(days=7)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CreateUserBody(BaseModel):
    full_name: str
    email: str
    role: str


class RoleBody(BaseModel):
    role: str


def _get_member(user_id: str, firm_id: str) -> dict:
    member = user_repo.find_by_id(user_id)
    if not member or member.get("firm_id") != firm_id:
        raise HTTPException(404, "User not found in firm")
    return member


@router.get("/users")
def list_users(current_user: dict = Depends(rbac("team", "read"))):
    return api_response(True, {"users": user_repo.find_all(firm_id=current_user["firm_id"])})


@router.post("/users")
def create_user(body: CreateUserBody, current_user: dict = Depends(rbac("team", "write"))):
    if body.role not in _CANONICAL:
        raise HTTPException(400, f"Invalid role. Must be one of: {', '.join(sorted(_CANONICAL))}")
    firm_id = current_user["firm_id"]
    # F21 fix: the invite link now carries a single-use, expiring, server-issued
    # token (not the firm_id/role themselves) — /join exchanges the token for a
    # link via POST /api/identity/accept-invite; it can no longer insert a users
    # row with client-supplied firm_id/role.
    invite_token = secrets.token_urlsafe(32)
    created = user_repo.create({
        "firm_id": firm_id, "full_name": body.full_name, "email": body.email,
        "role": body.role, "is_active": True, "status": "invited",
        "invite_token": invite_token,
        "invite_expires_at": (datetime.now(timezone.utc) + _INVITE_TTL).isoformat(),
    })
    log_event(firm_id, "user", str(created.get("id", "")), "create",
              actor_id=current_user.get("id"), actor_email=current_user.get("email"),
              new_data={"email": body.email, "role": body.role})
    return api_response(True, {**created, "invite_token": invite_token})


class AcceptInviteBody(BaseModel):
    token: str


@router.post("/accept-invite")
def accept_invite(body: AcceptInviteBody, jwt_user: dict = Depends(get_jwt_user)):
    """Complete a staff invite (F21 fix). JWT-only auth — the caller has no
    `users` row yet (that is exactly what this endpoint creates by linking).

    Identity is established ENTIRELY from the verified Supabase JWT (auth_user_id
    + email) and the pre-created invite row (firm_id + role) — never from a
    client-supplied field. This is the only way a `users` row's auth_user_id can
    ever be set; there is no client-side insert/update path left (see migration
    153, which also removed the RLS/grant paths that made the old raw insert
    possible)."""
    invite = user_repo.find_by_invite_token(body.token)
    if not invite:
        raise HTTPException(status_code=404, detail="Invalid or expired invite.")
    expires_at = invite.get("invite_expires_at")
    if not expires_at or datetime.fromisoformat(expires_at.replace("Z", "+00:00")) < datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="Invalid or expired invite.")
    if (invite.get("email") or "").strip().lower() != (jwt_user.get("email") or "").strip().lower():
        # Defense in depth: the token alone (a 256-bit random secret only ever
        # transmitted to the invited email) is already unforgeable, but a mismatch
        # here means the wrong mailbox somehow held the link — refuse rather than
        # silently link the wrong identity.
        raise HTTPException(status_code=404, detail="Invalid or expired invite.")

    updated = user_repo.update(invite["id"], {
        "auth_user_id": jwt_user["auth_user_id"],
        "status": "active",
        "is_active": True,
        "invite_token": None,
        "invite_expires_at": None,
    })
    log_event(invite["firm_id"], "user", str(invite["id"]), "invite_accepted",
              actor_id=jwt_user.get("auth_user_id"), actor_email=jwt_user.get("email"))
    return api_response(True, {
        "firm_id": invite["firm_id"], "role": invite["role"], "full_name": invite.get("full_name"),
    } if updated else None)


@router.patch("/users/{user_id}/role")
def change_role(user_id: str, body: RoleBody, current_user: dict = Depends(rbac("team", "write"))):
    if body.role not in _CANONICAL:
        raise HTTPException(400, f"Invalid role. Must be one of: {', '.join(sorted(_CANONICAL))}")
    member = _get_member(user_id, current_user["firm_id"])
    old = member.get("role")
    updated = user_repo.update(user_id, {"role": body.role})
    log_event(current_user["firm_id"], "user_role", user_id, "update",
              actor_id=current_user.get("id"), actor_email=current_user.get("email"),
              old_data={"role": old}, new_data={"role": body.role})
    return api_response(True, updated)


@router.post("/users/{user_id}/suspend")
def suspend_user(user_id: str, current_user: dict = Depends(rbac("team", "write"))):
    member = _get_member(user_id, current_user["firm_id"])
    # Disable AND revoke sessions so any existing JWT is rejected immediately.
    updated = user_repo.update(user_id, {"is_active": False, "sessions_revoked_at": _now()})
    log_event(current_user["firm_id"], "user", user_id, "suspend",
              actor_id=current_user.get("id"), actor_email=current_user.get("email"))
    login_events_repo.record(current_user["firm_id"], user_id, member.get("email"), "suspended")
    return api_response(True, updated)


@router.post("/users/{user_id}/reactivate")
def reactivate_user(user_id: str, current_user: dict = Depends(rbac("team", "write"))):
    _get_member(user_id, current_user["firm_id"])
    updated = user_repo.update(user_id, {"is_active": True})
    log_event(current_user["firm_id"], "user", user_id, "reactivate",
              actor_id=current_user.get("id"), actor_email=current_user.get("email"))
    return api_response(True, updated)


@router.post("/users/{user_id}/force-logout")
def force_logout(user_id: str, current_user: dict = Depends(rbac("team", "write"))):
    member = _get_member(user_id, current_user["firm_id"])
    updated = user_repo.update(user_id, {"sessions_revoked_at": _now()})
    log_event(current_user["firm_id"], "user", user_id, "force_logout",
              actor_id=current_user.get("id"), actor_email=current_user.get("email"))
    login_events_repo.record(current_user["firm_id"], user_id, member.get("email"), "forced_logout")
    return api_response(True, updated)


@router.post("/force-logout-all")
def force_logout_all(current_user: dict = Depends(rbac("team", "write"))):
    """Global logout — revoke every user's sessions in the firm."""
    firm_id = current_user["firm_id"]
    now = _now()
    count = 0
    for m in user_repo.find_all(firm_id=firm_id):
        user_repo.update(m["id"], {"sessions_revoked_at": now})
        count += 1
    log_event(firm_id, "firm", firm_id, "force_logout_all",
              actor_id=current_user.get("id"), actor_email=current_user.get("email"),
              metadata={"users_affected": count})
    return api_response(True, {"users_affected": count})


@router.get("/users/{user_id}/login-history")
def user_login_history(user_id: str, current_user: dict = Depends(rbac("team", "read"))):
    _get_member(user_id, current_user["firm_id"])
    return api_response(True, {"events": login_events_repo.list_for_user(current_user["firm_id"], user_id)})


@router.get("/login-history")
def firm_login_history(
    limit: int = Query(200, ge=1, le=1000),
    current_user: dict = Depends(rbac("team", "read")),
):
    return api_response(True, {"events": login_events_repo.list_for_firm(current_user["firm_id"], limit=limit)})


# ─── Self-service: what may the caller do? ───────────────────────────────────
# Deliberately guarded by get_current_user, NOT by rbac(). Gating "which actions
# am I allowed?" behind a permission is circular — every role would need it, so
# the guard would assert nothing while implying it asserts something.
#
# This exists so the FRONTEND stops re-deriving the matrix. Before this, the UI
# hardcoded role lists (hasRole(role, ["Partner","Manager"])) beside each button,
# which drifts the moment core/permissions.py changes: an Executive was still
# shown accounting write actions the backend answers with 403. Serving the
# matrix means there is exactly one copy of it, here.
#
# Not a security boundary. rbac() on each endpoint is still the only thing that
# decides anything; this only decides what is worth rendering.
@router.get("/permissions")
def my_permissions(current_user: dict = Depends(get_current_user)):
    """The caller's own resource→actions map, plus their canonical role."""
    role = canonical_role(current_user.get("role"))
    if role is None:
        # Unknown role string: an empty map rather than a 500. The frontend
        # helpers fail closed on an empty map, which is the right outcome for a
        # row carrying a role nobody recognises.
        return api_response(True, {"role": None, "permissions": {}})
    return api_response(True, {"role": role, "permissions": get_accessible_resources(role)})


class LoginEventBody(BaseModel):
    event: str  # 'login' | 'logout'


# NOTE: was rbac("ai", "read") — wrong resource entirely (this records who
# signed in, not anything AI), and a read-level action guarding a WRITE:
# it persists a row via login_events_repo.record below.
@router.post("/login-event")
def record_login_event(body: LoginEventBody,
                       current_user: dict = Depends(rbac("identity", "write"))):
    """Recorded by the frontend on sign-in / sign-out for the current user."""
    if body.event not in ("login", "logout"):
        raise HTTPException(400, "event must be 'login' or 'logout'")
    ev = login_events_repo.record(current_user.get("firm_id"), current_user.get("id"),
                                  current_user.get("email"), body.event)
    return api_response(True, ev)
