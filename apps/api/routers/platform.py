"""
Platform Admin API — /api/platform.

Cross-tenant visibility + control for the PracticeSync owner. Every endpoint is
gated by the platform_admins allowlist (require_platform_admin), uses the
service-role DB client (intentionally bypassing firm RLS), and audits every
mutation. This router is intentionally NOT part of firm RBAC.

Scope (v1, deliberately minimal): list firms + stats, view a firm + its users,
suspend / unsuspend, and SOFT delete. No billing, impersonation, hard delete,
or cross-firm data editing.
"""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from models.common import api_response
from core.platform_auth import require_platform_admin, require_platform_admin_mfa, is_platform_admin
from core.supabase_client import get_service_supabase
from services.audit_service import log_event

router = APIRouter(prefix="/api/platform", tags=["platform"])
_logger = logging.getLogger("caflow.platform")


class SuspendBody(BaseModel):
    reason: str


def _count(db, table: str, **eq) -> int:
    q = db.table(table).select("id", count="exact").limit(1)
    for k, v in eq.items():
        q = q.eq(k, v)
    return q.execute().count or 0


def _firm_status(firm: dict) -> str:
    if firm.get("deleted_at"):
        return "deleted"
    return "active" if firm.get("is_active", True) else "suspended"


# ─── Identity / gating ───────────────────────────────────────────────────────
@router.get("/me")
def me(ctx: dict = Depends(is_platform_admin)):
    """UI gating — non-failing; returns whether the caller is a platform admin."""
    return api_response(True, {"is_platform_admin": ctx.get("is_platform_admin", False)})


# ─── Stats ───────────────────────────────────────────────────────────────────
@router.get("/stats")
def stats(_admin: dict = Depends(require_platform_admin)):
    db = get_service_supabase()
    firms = db.table("firms").select("id, is_active, deleted_at").execute().data or []
    active = sum(1 for f in firms if not f.get("deleted_at") and f.get("is_active", True))
    suspended = sum(1 for f in firms if not f.get("deleted_at") and not f.get("is_active", True))
    return api_response(True, {
        "total_firms": len(firms),
        "active_firms": active,
        "suspended_firms": suspended,
        "total_users": _count(db, "users"),
        "total_clients": _count(db, "clients", is_internal=False),
    })


# ─── Firms ───────────────────────────────────────────────────────────────────
@router.get("/firms")
def list_firms(_admin: dict = Depends(require_platform_admin)):
    db = get_service_supabase()
    firms = (db.table("firms").select("id, name, created_at, is_active, deleted_at")
             .order("created_at", desc=True).execute().data or [])
    out = []
    for f in firms:
        out.append({
            "id": f["id"],
            "name": f.get("name"),
            "created_at": f.get("created_at"),
            "users": _count(db, "users", firm_id=f["id"]),
            "clients": _count(db, "clients", firm_id=f["id"], is_internal=False),
            "status": _firm_status(f),
        })
    return api_response(True, out)


@router.get("/firms/{firm_id}")
def firm_detail(firm_id: str, _admin: dict = Depends(require_platform_admin)):
    db = get_service_supabase()
    firm = db.table("firms").select("*").eq("id", firm_id).maybe_single().execute().data
    if not firm:
        raise HTTPException(status_code=404, detail="Firm not found")
    return api_response(True, {
        "id": firm["id"],
        "name": firm.get("name"),
        "email": firm.get("email"),
        "created_at": firm.get("created_at"),
        "status": _firm_status(firm),
        "users": _count(db, "users", firm_id=firm_id),
        "clients": _count(db, "clients", firm_id=firm_id, is_internal=False),
    })


@router.get("/firms/{firm_id}/users")
def firm_users(firm_id: str, _admin: dict = Depends(require_platform_admin)):
    db = get_service_supabase()
    rows = (db.table("users").select("full_name, email, role, is_active")
            .eq("firm_id", firm_id).order("role").execute().data or [])
    return api_response(True, [{
        "name": r.get("full_name"),
        "email": r.get("email"),
        "role": r.get("role"),
        "status": "active" if r.get("is_active", True) else "inactive",
    } for r in rows])


# ─── Suspend / unsuspend / soft-delete ──────────────────────────────────────
@router.post("/firms/{firm_id}/suspend")
def suspend_firm(firm_id: str, body: SuspendBody, admin: dict = Depends(require_platform_admin_mfa)):
    if not body.reason or not body.reason.strip():
        raise HTTPException(status_code=400, detail="A reason is required to suspend a firm.")
    db = get_service_supabase()
    firm = db.table("firms").select("id, is_active").eq("id", firm_id).maybe_single().execute().data
    if not firm:
        raise HTTPException(status_code=404, detail="Firm not found")
    db.table("firms").update({"is_active": False}).eq("id", firm_id).execute()
    log_event(firm_id, "firm", firm_id, "platform_suspend",
              actor_id=admin.get("auth_user_id"), actor_email=admin.get("email"),
              metadata={"reason": body.reason.strip()})
    return api_response(True, {"firm_id": firm_id, "status": "suspended"})


@router.post("/firms/{firm_id}/unsuspend")
def unsuspend_firm(firm_id: str, admin: dict = Depends(require_platform_admin)):
    db = get_service_supabase()
    firm = db.table("firms").select("id, deleted_at").eq("id", firm_id).maybe_single().execute().data
    if not firm:
        raise HTTPException(status_code=404, detail="Firm not found")
    if firm.get("deleted_at"):
        raise HTTPException(status_code=409, detail="Cannot unsuspend a deleted firm.")
    db.table("firms").update({"is_active": True}).eq("id", firm_id).execute()
    log_event(firm_id, "firm", firm_id, "platform_unsuspend",
              actor_id=admin.get("auth_user_id"), actor_email=admin.get("email"))
    return api_response(True, {"firm_id": firm_id, "status": "active"})


@router.delete("/firms/{firm_id}")
def soft_delete_firm(firm_id: str, admin: dict = Depends(require_platform_admin_mfa)):
    db = get_service_supabase()
    firm = db.table("firms").select("id").eq("id", firm_id).maybe_single().execute().data
    if not firm:
        raise HTTPException(status_code=404, detail="Firm not found")
    # SOFT delete only — records are preserved.
    db.table("firms").update({
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "is_active": False,
    }).eq("id", firm_id).execute()
    log_event(firm_id, "firm", firm_id, "platform_delete",
              actor_id=admin.get("auth_user_id"), actor_email=admin.get("email"))
    return api_response(True, {"firm_id": firm_id, "status": "deleted"})


@router.delete("/firms/{firm_id}/permanent")
def purge_firm(firm_id: str, admin: dict = Depends(require_platform_admin_mfa)):
    """PERMANENT (hard) delete — irreversible. Removes the firm and ALL of its
    data (users rows, clients, every firm-scoped table) via platform_purge_firm,
    which disables FK enforcement for its own transaction to handle the mixed
    CASCADE / NO ACTION constraints. Auth login accounts are intentionally left
    intact (so the platform admin's own access survives purging their firm).
    Gated by aal2 (require_platform_admin_mfa)."""
    db = get_service_supabase()
    firm = db.table("firms").select("id, name").eq("id", firm_id).maybe_single().execute().data
    if not firm:
        raise HTTPException(status_code=404, detail="Firm not found")
    removed = db.rpc("platform_purge_firm", {"p_firm_id": firm_id}).execute().data
    # Durable platform-level audit — written AFTER the purge so it is not swept
    # away with the firm's own (firm-scoped) audit_logs.
    db.table("platform_audit").insert({
        "action": "platform_purge",
        "target_firm_id": firm_id,
        "firm_name": firm.get("name"),
        "actor_auth_user_id": admin.get("auth_user_id"),
        "actor_email": admin.get("email"),
        "metadata": removed or {},
    }).execute()
    return api_response(True, {"firm_id": firm_id, "status": "purged", "removed": removed})
