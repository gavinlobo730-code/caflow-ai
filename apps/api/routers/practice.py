"""
Practice (firm-as-internal-client) router — Amendment v1.1.

Partner/Owner-only entry point for the firm's own internal client. Batch 2
provides provisioning + identity; the full Practice workspace UI and the
Revenue Operations surfaces are layered in later batches.

Guardrail G1: every endpoint here is Partner-only (see the "practice" RBAC
resource). The internal client is excluded from all client-population surfaces
by Guardrail G2 (clients_external + repository/router exclusions).
"""
import os
from fastapi import APIRouter, Depends
from models.common import api_response
from core.permissions import rbac
from services.internal_client_service import provision, get_internal_client_id
from services.coa_seed_service import seed_firm_coa

router = APIRouter(prefix="/api/practice", tags=["practice"])

_USE_MOCK = not os.environ.get("SUPABASE_URL")


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


@router.get("")
def get_practice(current_user: dict = Depends(rbac("practice", "read"))):
    """Return the firm's internal practice client id (or None if not provisioned)."""
    firm_id = current_user.get("firm_id")
    internal_client_id = get_internal_client_id(firm_id)
    return api_response(True, {
        "internal_client_id": internal_client_id,
        "provisioned": bool(internal_client_id),
    })


@router.post("/provision")
def provision_practice(current_user: dict = Depends(rbac("practice", "write"))):
    """Idempotently provision the firm-as-internal-client using the firm's own
    PAN/GSTIN. Useful for firms created before provisioning existed, and as the
    hook the Practice UI calls. Returns the internal client id."""
    firm_id = current_user.get("firm_id")
    if _USE_MOCK:
        return api_response(True, {"internal_client_id": None, "provisioned": False,
                                   "message": "Provisioning is a no-op in mock mode."})
    firm = _db().table("firms").select("name, pan, gstin").eq("id", firm_id).maybe_single().execute().data
    if not firm:
        return api_response(False, None, "Firm not found")

    # Seed the firm-wide master Chart of Accounts first (idempotent — skips if the
    # firm already has firm-wide accounts). Required so the internal client can post
    # journals on invoice issue. This backfills CoA for firms onboarded before
    # seeding existed; non-fatal so provisioning still proceeds.
    coa = {"seeded": 0, "skipped": True}
    try:
        coa = seed_firm_coa(firm_id)
    except Exception:  # pragma: no cover - defensive
        pass

    internal_client_id = provision(
        firm_id, firm.get("name") or "Practice", firm.get("pan"), gstin=firm.get("gstin"),
    )
    return api_response(True, {
        "internal_client_id": internal_client_id,
        "provisioned": bool(internal_client_id),
        "coa_seeded": coa.get("seeded", 0),
        "message": None if internal_client_id else
        "Could not provision — firm has no valid PAN. Set the firm PAN and retry.",
    })
