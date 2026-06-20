"""
Practice (firm-as-internal-client) router — Amendment v1.1 + Phase 3.3A.

Partner/Owner-only entry point for the firm's own internal client:
  • GET  /api/practice          — provisioning status (+ whether the firm has a PAN)
  • POST /api/practice/provision — idempotent activation (legacy firms included)
  • PATCH /api/practice/identity — Partner-only maintenance of PAN/GSTIN/state

Guardrail G1: every endpoint here is Partner-only (see the "practice" RBAC
resource). The internal client is excluded from all client-population surfaces
by Guardrail G2 (clients_external + repository/router exclusions).
"""
import os
import logging
from fastapi import APIRouter, Depends
from models.common import api_response
from models.client import PracticeIdentityUpdate
from core.permissions import rbac
from core.validators import derive_state_code, validate_state_code
from services.internal_client_service import provision, get_internal_client_id

router = APIRouter(prefix="/api/practice", tags=["practice"])
_logger = logging.getLogger("caflow.practice")
_USE_MOCK = not os.environ.get("SUPABASE_URL")


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


@router.get("")
def get_practice(current_user: dict = Depends(rbac("practice", "read"))):
    """Provisioning status for the firm's internal practice client. Surfaces
    whether the firm has a PAN so the UI can show an actionable message when
    provisioning is not yet possible (Part A2)."""
    firm_id = current_user.get("firm_id")
    internal_client_id = get_internal_client_id(firm_id)
    firm_has_pan = False
    if not _USE_MOCK and firm_id:
        firm = _db().table("firms").select("pan").eq("id", firm_id).maybe_single().execute().data
        firm_has_pan = bool(firm and firm.get("pan"))
    return api_response(True, {
        "internal_client_id": internal_client_id,
        "provisioned": bool(internal_client_id),
        "firm_has_pan": firm_has_pan,
        "can_provision": firm_has_pan and not internal_client_id,
    })


@router.post("/provision")
def provision_practice(current_user: dict = Depends(rbac("practice", "write"))):
    """Idempotently provision the firm-as-internal-client using the firm's own
    PAN/GSTIN/state. The safe activation path for legacy firms created before
    provisioning existed (Part A1). Returns the internal client id and an
    actionable message when it could not be provisioned."""
    firm_id = current_user.get("firm_id")
    if _USE_MOCK:
        return api_response(True, {"internal_client_id": None, "provisioned": False,
                                   "message": "Provisioning is a no-op in mock mode."})
    firm = _db().table("firms").select("name, pan, gstin, state").eq("id", firm_id).maybe_single().execute().data
    if not firm:
        return api_response(False, None, "Firm not found")
    internal_client_id = provision(
        firm_id, firm.get("name") or "Practice", firm.get("pan"),
        gstin=firm.get("gstin"), state=firm.get("state"),
        actor_id=current_user.get("auth_user_id"),
    )
    return api_response(True, {
        "internal_client_id": internal_client_id,
        "provisioned": bool(internal_client_id),
        "message": None if internal_client_id else
        "Could not provision — the firm has no valid PAN. Set the firm PAN (Settings) and retry.",
    })


@router.patch("/identity")
def update_practice_identity(
    body: PracticeIdentityUpdate,
    current_user: dict = Depends(rbac("practice", "write")),
):
    """Partner-only maintenance of the internal practice client's tax identity
    (PAN / GSTIN / state / state_code) — the controlled path missing from the
    generic client update (Part B). Validation is enforced by the model; state_code
    is derived when omitted; the change is audit-logged."""
    firm_id = current_user.get("firm_id")
    internal_client_id = get_internal_client_id(firm_id)
    if not internal_client_id:
        return api_response(False, None,
                            "No practice client provisioned yet. Provision it first.")
    if _USE_MOCK:
        return api_response(True, {"internal_client_id": internal_client_id, "updated": False,
                                   "message": "Identity update is a no-op in mock mode."})

    update: dict = {}
    if body.pan is not None:
        update["pan"] = body.pan
    if body.gstin is not None:
        update["gstin"] = body.gstin
    if body.state is not None:
        update["state"] = body.state
    # state_code: explicit (validated) → else derive from explicit/state/gstin.
    if body.state_code is not None:
        err = validate_state_code(body.state_code)
        if err:
            return api_response(False, None, err)
        update["state_code"] = body.state_code
    elif body.state is not None or body.gstin is not None:
        derived = derive_state_code(None, body.state, body.gstin)
        if derived:
            update["state_code"] = derived
    if not update:
        return api_response(False, None, "No identity fields supplied.")

    db = _db()
    before = (db.table("clients").select("pan, gstin, state, state_code")
              .eq("id", internal_client_id).eq("firm_id", firm_id)
              .eq("is_internal", True).maybe_single().execute().data)
    if not before:
        return api_response(False, None, "Practice client not found.")

    db.table("clients").update(update).eq("id", internal_client_id).eq("firm_id", firm_id).eq("is_internal", True).execute()

    try:
        from services.audit_service import log_event
        log_event(
            firm_id, "client", internal_client_id, "update",
            actor_id=current_user.get("auth_user_id"),
            old_data=before, new_data=update,
            metadata={"source": "practice_identity_update"},
        )
    except Exception:  # pragma: no cover - audit must never block the update
        pass

    return api_response(True, {"internal_client_id": internal_client_id, "updated": True,
                               "fields": list(update.keys())})
