"""
Portal identity layer (Phase 4.5.1).

get_current_portal_client() — the client-facing auth dependency. It REUSES the
Supabase JWT validation (core.auth.get_jwt_user, which does NOT require a staff
`users` row) and resolves the authenticated identity to exactly one client via
portal_access_service. It returns a strict portal context with NO firm-staff
fields and NO RBAC role — a portal contact can never gain staff privilege.
"""
from fastapi import Depends, HTTPException, status

from core.auth import get_jwt_user
from services import portal_access_service


def get_current_portal_client(jwt_user: dict = Depends(get_jwt_user)) -> dict:
    """Resolve the Supabase-authenticated caller to their portal client context.
    401 if the JWT is missing/invalid (handled upstream); 403 if the caller is not
    an active portal contact for any client."""
    ctx = portal_access_service.resolve_portal_client(
        jwt_user.get("auth_user_id"), jwt_user.get("email"))
    if not ctx:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a portal user.")
    # Strict portal context only — deliberately no firm-staff role / RBAC fields.
    return {
        "portal": True,
        "client_id": ctx["client_id"],
        "firm_id": ctx.get("firm_id"),
        "portal_contact_id": ctx.get("contact_id"),
        "email": ctx.get("email"),
        "name": ctx.get("name"),
        "role": "PortalClient",
    }
