"""
Currency master + currency-policy resolution (Multi-Currency Phase 1 — read-only).

Additive and read-only: exposes the ISO 4217 currency master and the resolved
currency policy for a (firm, client). No accounting endpoint is touched, and
nothing here can change posting behaviour — with the feature off the policy is
always {active: false, functional_currency: "INR"}.
"""
import os
import logging

from fastapi import APIRouter, Depends, Query

from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access
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
        return api_response(True, {"active": pol.active, "functional_currency": pol.functional_currency})

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
    return api_response(True, {"active": pol.active, "functional_currency": pol.functional_currency})
