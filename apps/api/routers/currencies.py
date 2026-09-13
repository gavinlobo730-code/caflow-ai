"""
Currency master + currency-policy resolution (Multi-Currency Phase 1 — read-only).

Additive and read-only: exposes the ISO 4217 currency master and the resolved
currency policy for a (firm, client). No accounting endpoint is touched, and
nothing here can change posting behaviour — with the feature off the policy is
always {active: false, functional_currency: "INR"}.
"""
import os
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access
from core.feature_flags import multi_currency_platform_enabled
from domain.currency import resolve_currency_policy
from domain.currency import currency_service

_logger = logging.getLogger("caflow.currencies")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

router = APIRouter(prefix="/api/currencies", tags=["currencies"])


@router.get("")
def get_currencies(
    active_only: bool = Query(True),
    current_user: dict = Depends(rbac("client", "read")),
):
    """List the ISO 4217 currency master (global reference data)."""
    if _USE_MOCK:
        return api_response(True, [])
    from core.supabase_client import get_supabase

    rows = currency_service.list_currencies(get_supabase(), active_only=active_only)
    return api_response(True, rows)


@router.get("/policy")
def get_currency_policy(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("client", "read")),
):
    """Resolve { active, functional_currency } for the caller's firm + this client.

    Phase 1: always {active: false, functional_currency: "INR"} unless all three
    gates (env, firm entitlement, client enablement) are on.
    """
    # Mount-guard-covered (required client_id query param); explicit so the
    # scope check is visible, and BEFORE the mock short-circuit below — which
    # otherwise returns a policy for any client_id without consulting scope.
    assert_client_access(current_user, client_id)
    firm_id = current_user.get("firm_id")
    if _USE_MOCK:
        pol = resolve_currency_policy(None, None)
        # Same SHAPE as the real branch. A mock reply missing `gates` would
        # make the screen render an undefined gate as "off" in dev and as
        # something else in production.
        return api_response(True, {
            "active": pol.active,
            "functional_currency": pol.functional_currency,
            "gates": _gates(None, None),
        })

    from core.supabase_client import get_supabase

    db = get_supabase()
    firm_res = (
        db.table("firms").select("id, multi_currency_entitled").eq("id", firm_id).limit(1).execute()
    )
    firm = (getattr(firm_res, "data", None) or [None])[0]
    # Tenant isolation: the client must belong to the caller's firm.
    client_res = (
        db.table("clients")
        .select("id, functional_currency, multi_currency_enabled")
        .eq("id", client_id)
        .eq("firm_id", firm_id)
        .limit(1)
        .execute()
    )
    client = (getattr(client_res, "data", None) or [None])[0]
    pol = resolve_currency_policy(firm, client)
    return api_response(True, {
        "active": pol.active,
        "functional_currency": pol.functional_currency,
        # WHICH GATE IS OFF (ACC-19). `active: false` alone is what made this
        # feature unusable: a Partner ticked a box, nothing happened, and the
        # screen could not say which of three switches was still down. Every
        # gate the caller can DO something about is reported separately, and
        # the one they cannot — the environment kill switch — says so.
        "gates": _gates(firm, client),
    })


def _gates(firm: dict | None, client: dict | None) -> dict:
    """The three gates `resolve_currency_policy` ANDs together, named.

    L1 is the environment kill switch and is deliberately not settable — see
    core/feature_flags, which says "No DB dependency". L2 and L3 are the two
    the endpoints below write.
    """
    functional = ((client or {}).get("functional_currency") or "INR").strip().upper()
    return {
        "platform": {
            "on": multi_currency_platform_enabled(),
            "settable": False,
            "why": ("MULTI_CURRENCY_ENABLED is an environment kill switch, not "
                    "a setting — it is read with no database dependency so it "
                    "can be turned off without one."),
        },
        "firm": {
            "on": bool((firm or {}).get("multi_currency_entitled")),
            "settable": True,
        },
        "client": {
            "on": bool((client or {}).get("multi_currency_enabled")),
            "settable": True,
        },
        # Capability B — a non-INR functional currency, meaning presentation
        # and translation — is not built, so the policy fails safe on one. A
        # client whose books are kept in USD therefore cannot be switched on,
        # and saying so is better than an inert checkbox.
        "functional_currency_supported": functional == "INR",
        "functional_currency": functional,
    }


@router.get("/entitlement")
def get_firm_entitlement(
    current_user: dict = Depends(rbac("settings", "read")),
):
    """The two FIRM-level gates, with no client in the request.

    WHY THIS EXISTS RATHER THAN READING THEM OFF A CLIENT'S POLICY. `GET
    /policy` carries the firm gate too, so the settings screen very nearly took
    it from the first client's answer — which is wrong for a firm that has no
    clients yet, exactly the firm a Partner is switching this on for. The
    checkbox would have snapped back to Off after every save, which is the
    inert control ACC-19 is about.

    One implementation either way: both answers come out of `_gates`.
    """
    firm_id = current_user.get("firm_id")
    if _USE_MOCK:
        g = _gates(None, None)
        return api_response(True, {"platform": g["platform"], "firm": g["firm"]})
    from core.supabase_client import get_supabase

    db = get_supabase()
    firm = (db.table("firms").select("id, multi_currency_entitled")
            .eq("id", firm_id).limit(1).execute().data or [None])[0]
    g = _gates(firm, None)
    return api_response(True, {"platform": g["platform"], "firm": g["firm"]})


@router.put("/entitlement")
def set_firm_entitlement(
    enabled: bool = Body(..., embed=True),
    current_user: dict = Depends(rbac("settings", "write")),
):
    """Turn multi-currency on or off for the caller's OWN firm (L2).

    WHAT WAS WRONG (ACC-19). All five multi-currency phases are built —
    foreign documents, realized and unrealized FX, five /api/fx-reports
    endpoints, foreign bank accounts — and `firms.multi_currency_entitled`
    (migration 146) was READ by policy.py and six routers and WRITTEN BY
    NOTHING. No endpoint, no Pydantic field, no screen, no seed. Only a manual
    UPDATE against the database could activate any of it.

    SELF-SERVE, and that is an owner decision of 13-09-2026. There is no
    billing, plan or entitlement machinery anywhere in this product, so a
    commercial gate has nothing to hang off and building one would be larger
    than the feature it gates. If it is ever sold the column does not move: a
    plan check goes in FRONT of this endpoint.

    Partner-only (`settings` write), because it changes what the posting kernel
    accepts for every client of the firm.
    """
    firm_id = current_user.get("firm_id")
    if _USE_MOCK:
        return api_response(True, {"firm_id": firm_id, "multi_currency_entitled": bool(enabled)})
    from core.supabase_client import get_supabase

    db = get_supabase()
    # Scoped to the caller's own firm and to nothing else: there is no firm_id
    # in the request, so a Partner can only ever change their own.
    res = (db.table("firms").update({"multi_currency_entitled": bool(enabled)})
           .eq("id", firm_id).execute())
    if not (getattr(res, "data", None) or []):
        raise HTTPException(status_code=404, detail="Firm not found.")
    _logger.info("caflow.currencies firm %s multi_currency_entitled=%s", firm_id, bool(enabled))
    return api_response(True, {"firm_id": firm_id, "multi_currency_entitled": bool(enabled)})


@router.put("/policy")
def set_client_currency_policy(
    client_id: str = Query(...),
    enabled: bool = Body(..., embed=True),
    current_user: dict = Depends(rbac("settings", "write")),
):
    """Turn multi-currency on or off for ONE client (L3).

    The other half of ACC-19: `clients.multi_currency_enabled` was read by the
    same six routers and written by nothing either.

    TURNING IT ON IS REFUSED WHERE IT WOULD BE INERT. Two ways that happens,
    and each is a sentence rather than a silent no-op — an inert checkbox is
    the defect this endpoint exists to end, and adding a second one would be
    the same mistake:

      * the FIRM is not entitled, so `active` would stay false however this is
        set. The order is firm first, then client;
      * the client's functional currency is not INR. Capability B
        (presentation and translation) is not built, so `resolve_currency_policy`
        fails safe on a non-INR functional currency by design.

    Turning it OFF is never refused. A client that should not be transacting in
    foreign currency has to be stoppable whatever the firm's state is.
    """
    assert_client_access(current_user, client_id)
    firm_id = current_user.get("firm_id")
    if _USE_MOCK:
        return api_response(True, {"client_id": client_id, "multi_currency_enabled": bool(enabled)})
    from core.supabase_client import get_supabase

    db = get_supabase()
    client = (db.table("clients")
              .select("id, functional_currency, multi_currency_enabled")
              .eq("id", client_id).eq("firm_id", firm_id).limit(1).execute().data or [None])[0]
    if not client:
        raise HTTPException(status_code=404, detail="Client not found.")

    if enabled:
        firm = (db.table("firms").select("id, multi_currency_entitled")
                .eq("id", firm_id).limit(1).execute().data or [None])[0]
        if not (firm or {}).get("multi_currency_entitled"):
            raise HTTPException(
                status_code=409,
                detail=("Multi-currency is off for the firm, so turning it on for "
                        "one client would change nothing. Turn it on for the firm "
                        "first (Settings → Multi-currency)."))
        functional = (client.get("functional_currency") or "INR").strip().upper()
        if functional != "INR":
            raise HTTPException(
                status_code=409,
                detail=(f"This client's functional currency is {functional}. The "
                        "product supports INR-functional books that transact in "
                        "foreign currency; keeping the books themselves in "
                        "another currency (presentation and translation) is not "
                        "built, so the policy would stay inactive."))

    res = (db.table("clients").update({"multi_currency_enabled": bool(enabled)})
           .eq("id", client_id).eq("firm_id", firm_id).execute())
    if not (getattr(res, "data", None) or []):
        raise HTTPException(status_code=404, detail="Client not found.")
    _logger.info("caflow.currencies client %s multi_currency_enabled=%s", client_id, bool(enabled))
    return api_response(True, {"client_id": client_id, "multi_currency_enabled": bool(enabled)})
