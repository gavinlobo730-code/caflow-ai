"""
Platform Admin authorization — COMPLETELY separate from the firm RBAC model.

A platform admin is identified ONLY by membership in the platform_admins
allowlist (an auth_user_id), never by a firm role (Partner/Manager/...). These
dependencies do not touch core.permissions / core.authz at all, so a firm user
can never reach platform powers through any role or assignment change.

Platform endpoints are cross-tenant BY DESIGN and use the service-role client;
access is gated to the vetted allowlist and every mutating action is audited.
"""
import logging
from fastapi import Depends, HTTPException, status
from core.auth import get_jwt_user

_logger = logging.getLogger("caflow.platform")


def _is_platform_admin(auth_user_id: str) -> bool:
    if not auth_user_id:
        return False
    try:
        from core.supabase_client import get_service_supabase
        res = (
            get_service_supabase()
            .table("platform_admins")
            .select("auth_user_id")
            .eq("auth_user_id", auth_user_id)
            .limit(1)
            .execute()
        )
        return bool(res.data)
    except Exception as e:  # pragma: no cover - defensive
        _logger.error("platform_admin lookup failed: %s", e)
        return False


def is_platform_admin(jwt_user: dict = Depends(get_jwt_user)) -> dict:
    """Non-failing — returns the caller plus an is_platform_admin flag. Used by
    GET /api/platform/me for UI gating (does NOT deny non-admins)."""
    return {**jwt_user, "is_platform_admin": _is_platform_admin(jwt_user.get("auth_user_id", ""))}


def require_platform_admin(jwt_user: dict = Depends(get_jwt_user)) -> dict:
    """Deny-by-default gate for platform endpoints. Returns 404 (not 403) so a
    firm user cannot even confirm the platform surface exists."""
    if not _is_platform_admin(jwt_user.get("auth_user_id", "")):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return jwt_user


def require_platform_admin_mfa(admin: dict = Depends(require_platform_admin)) -> dict:
    """Destructive actions (suspend / delete) require a fresh MFA (aal2) token."""
    if admin.get("aal") != "aal2":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Multi-factor authentication is required for this action. Enrol at Settings → Security.",
        )
    return admin
