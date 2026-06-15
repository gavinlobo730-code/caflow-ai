"""
M6 — Identity Administration backend (audited, server-side).

Replaces the client-side identity mutations in team/page.tsx with authorized,
audited backend APIs. Partner-only writes (rbac team:write); Manager+ reads.

Capabilities: create user, activate, suspend (kills sessions), reactivate, change
role, force-logout (single + firm-wide), login history. Every mutation is written
to audit_log; session-affecting actions also record a login_events row and bump
users.sessions_revoked_at so existing JWTs are rejected immediately.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from models.common import api_response
from core.permissions import rbac, Role
from repositories.user_repository import user_repo
from repositories.login_events_repository import login_events_repo
from services.audit_service import log_event

router = APIRouter(prefix="/api/identity", tags=["identity"])

_CANONICAL = {r.value for r in Role}


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
    created = user_repo.create({
        "firm_id": firm_id, "full_name": body.full_name, "email": body.email,
        "role": body.role, "is_active": True, "status": "invited",
    })
    log_event(firm_id, "user", str(created.get("id", "")), "create",
              actor_id=current_user.get("id"), actor_email=current_user.get("email"),
              new_data={"email": body.email, "role": body.role})
    return api_response(True, created)


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
def firm_login_history(current_user: dict = Depends(rbac("team", "read"))):
    return api_response(True, {"events": login_events_repo.list_for_firm(current_user["firm_id"])})


class LoginEventBody(BaseModel):
    event: str  # 'login' | 'logout'


@router.post("/login-event")
def record_login_event(body: LoginEventBody, current_user: dict = Depends(rbac("ai", "read"))):
    """Recorded by the frontend on sign-in / sign-out for the current user."""
    if body.event not in ("login", "logout"):
        raise HTTPException(400, "event must be 'login' or 'logout'")
    ev = login_events_repo.record(current_user.get("firm_id"), current_user.get("id"),
                                  current_user.get("email"), body.event)
    return api_response(True, ev)
