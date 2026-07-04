"""
Portal identity layer (Phase 4.5.1 + multi-client fix).

get_current_portal_client() — the client-facing auth dependency. It REUSES the
Supabase JWT validation (core.auth.get_jwt_user, which does NOT require a staff
`users` row), lists ALL of the identity's client memberships, and selects ONE
active client EXPLICITLY (deterministic; never implicit first-match):

  • exactly one membership          → that client (single-client portals unchanged)
  • header X-Portal-Client-Id given → that client IF it is one of the memberships,
                                       else 403 (cannot select a non-member client)
  • multiple memberships, no header → 409 (must choose; available clients returned)

Returns a strict portal context: NO firm-staff fields, NO RBAC role.
"""
import logging
import time
from typing import Optional
from fastapi import Depends, Header, HTTPException, status

from core.auth import get_jwt_user
from services import portal_access_service

_logger = logging.getLogger("caflow.portal_auth")

# ── Portal activity tracking ──────────────────────────────────────────────────
# The client-health engine's "responsiveness" signal reads
# client_portal_sessions (routers/health.py) — one row per activity window.
# This dependency is the single choke point every portal API request passes
# through, so it writes the touch. In-process debounce (one write per
# client+contact per window) keeps it from becoming a per-request insert;
# health only needs day-level granularity. Best-effort: a failed write must
# never fail the portal request itself.
_TOUCH_WINDOW_SECONDS = 6 * 60 * 60  # 6h — several rows/day max per contact
_last_touch: dict[tuple, float] = {}


def _touch_portal_session(ctx: dict) -> None:
    key = (ctx.get("client_id"), ctx.get("portal_contact_id") or ctx.get("email"))
    now = time.monotonic()
    last = _last_touch.get(key)
    if last is not None and (now - last) < _TOUCH_WINDOW_SECONDS:
        return
    _last_touch[key] = now
    try:
        import os
        if not os.environ.get("SUPABASE_URL"):
            return  # dev/test without a database
        from core.supabase_client import get_service_supabase
        get_service_supabase().table("client_portal_sessions").insert({
            "firm_id": ctx.get("firm_id"),
            "client_id": ctx.get("client_id"),
            "portal_contact_id": ctx.get("portal_contact_id"),
            "email": ctx.get("email"),
        }).execute()
    except Exception:  # noqa: BLE001 — tracking must never break portal access
        _logger.debug("portal session touch failed", exc_info=True)


def get_current_portal_client(
    jwt_user: dict = Depends(get_jwt_user),
    x_portal_client_id: Optional[str] = Header(default=None),
) -> dict:
    """Resolve the caller to a single ACTIVE portal-client context.
    401 (upstream) if the JWT is invalid; 403 if not a portal user or the requested
    client is not one of their memberships; 409 if they must pick a client."""
    memberships = portal_access_service.list_portal_memberships(
        jwt_user.get("auth_user_id"), jwt_user.get("email"))
    if not memberships:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a portal user.")

    active, needs_selection = portal_access_service.select_active_membership(
        memberships, x_portal_client_id)

    if needs_selection:
        # Multiple memberships and no explicit choice — never switch implicitly.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Multiple client memberships — choose one via the X-Portal-Client-Id header.",
                    "memberships": [{"client_id": m["client_id"], "name": m.get("name")} for m in memberships]},
        )
    if active is None:
        # A client_id was requested that the caller is not a member of (isolation).
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You do not have access to this client.")

    ctx = {
        "portal": True,
        "client_id": active["client_id"],
        "firm_id": active.get("firm_id"),
        "portal_contact_id": active.get("contact_id"),
        "email": active.get("email"),
        "name": active.get("name"),
        "role": "PortalClient",
        # The full membership list lets the client UI render a client switcher.
        "memberships": [{"client_id": m["client_id"], "name": m.get("name")} for m in memberships],
    }
    _touch_portal_session(ctx)  # health engine's engagement signal; best-effort
    return ctx
