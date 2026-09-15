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


# ─────────────────────────────────────────────────────────────────────────────
# THE EMPLOYEE PRINCIPAL (PAY-26)
#
# An employee already holds a real Supabase identity — `accept_employee_invite`
# writes `payroll_employees.auth_user_id` and flips `portal_enabled`, and
# migration 262's RLS policies read exactly that pair. What did NOT exist was
# any way for the API to resolve one, so every employee-facing figure had to be
# computed in the browser over PostgREST or not shown at all. The §192
# projection is the case that forced this: `_compute_slip` is the run's own
# engine and there is no second one, so the working an employee most wants to
# see was unreachable to them.
#
# THREE PROPERTIES, EACH A DELIBERATE NARROWING OF `get_current_portal_client`
# (owner decision of 14-09-2026):
#
#   SELF-SCOPED. The context carries the employee's OWN ids and an endpoint
#   using it must take none from the request. That is what makes it safe: there
#   is no employee_id parameter to tamper with, so no endpoint built on this
#   can be asked for somebody else's salary by changing a query string.
#
#   READ-ONLY. Nothing here is a write principal. An employee submitting a
#   declaration or a reimbursement claim is a separate decision with its own
#   consequences, and adding the surface now would invite it by accident.
#
#   NO CLIENT SWITCHER. A portal client may hold several memberships and must
#   choose; migration 262's unique index makes one auth identity at most ONE
#   employee, so there is nothing to choose and a 409 branch would be dead code
#   that later reads as a supported feature.
#
# `portal_enabled` IS ASKED SEPARATELY FROM `auth_user_id`, because they are two
# different facts: the binding happened, and the CA still permits it.
# `revoke_employee_portal` clears the second and may leave the first, so a check
# on the binding alone would keep a revoked employee signed in.
# ─────────────────────────────────────────────────────────────────────────────

def get_current_portal_employee(jwt_user: dict = Depends(get_jwt_user)) -> dict:
    """Resolve the caller to the ONE payroll employee they are, or refuse.

    401 (upstream) if the JWT is invalid; 403 if this identity is not a portal
    employee, or the CA has withdrawn access.

    THE SAME 403 FOR BOTH, and the same as "no such employee": a distinct
    message would tell an outsider whether an identity is an employee of this
    firm at all, which is the oracle `employee_portal_service` raises one
    generic 404 everywhere to avoid.
    """
    denied = HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                           detail="Not an employee portal user.")
    auth_user_id = jwt_user.get("auth_user_id")
    if not auth_user_id:
        raise denied

    import os
    if not os.environ.get("SUPABASE_URL"):
        # Dev and mock mode: there is no database to resolve against, and
        # inventing an employee here would make every guard below vacuous.
        raise denied

    from core.supabase_client import get_service_supabase
    rows = (get_service_supabase().table("payroll_employees")
            # EVERY COLUMN SPELLED INLINE, not `*` and not through a
            # constant. Named rather than `*` so a column dropped or renamed
            # fails here, at the one place that resolves an employee, rather
            # than producing a context with a missing id; inline rather than
            # via a variable because `tests/_backend_query_parser` resolves no
            # names, so a select whose argument is a variable is a blind spot
            # to the column check — the same reason
            # `routers/bills_of_entry.py` spells its insert out.
            .select("id, firm_id, client_id, name, employee_code, "
                    "portal_enabled, auth_user_id")
            .eq("auth_user_id", auth_user_id).limit(1).execute().data) or []
    if not rows:
        raise denied
    emp = rows[0]
    if not emp.get("portal_enabled"):
        raise denied

    return {
        "portal": True,
        "employee": True,
        "employee_id": emp["id"],
        "client_id": emp.get("client_id"),
        "firm_id": emp.get("firm_id"),
        "name": emp.get("name"),
        "employee_code": emp.get("employee_code"),
        "email": jwt_user.get("email"),
        # NOT an RBAC role. `core/permissions.PERMISSIONS` has no entry for it,
        # so `rbac()` would deny this principal everywhere — which is correct
        # and is why no endpoint on this dependency may also carry rbac().
        "role": "PortalEmployee",
    }
