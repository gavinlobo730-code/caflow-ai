"""
Firm-as-Internal-Client (Amendment v1.1) — provisioning + guardrail helpers.

The CA firm is modelled as a single `clients` row with `is_internal = true`,
referenced by `firms.internal_client_id`. It reuses the full client stack
(accounting, GST, TDS, documents, reports, billing) but is governed by four
mandatory guardrails:

  G1  Partner-only access to the internal client and its financial data.
  G2  Excluded from every client-population surface (counts, lists, Health,
      dashboards, reporting, search, lifecycle) — see clients_external + the
      repository default and the per-router patches.
  G3  Exactly one linked customer per practice client (wired in Batch 3).
  G4  Module cap: accounting + GST + TDS + documents + reports + billing only;
      payroll/HR provisioning is blocked for the internal client.

ENFORCEMENT NOTE. The backend connects with the Supabase SERVICE_ROLE key, which
BYPASSES RLS (see core/supabase_client.py + SECURITY.md). Therefore these
application-layer checks are the *effective* control. The RLS restrictive
policies in migration 074 are defence-in-depth for any direct (non-service-role)
database access. "Partner" is the Owner-equivalent role per the approved mapping.
"""
import os
import logging
from typing import Optional

from fastapi import HTTPException, Request, Depends
from core.auth import get_current_user

_logger = logging.getLogger("caflow.internal_client")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

# Owner-equivalent roles (approved mapping: Owner -> Partner). Accept either label.
_PARTNER_ROLES = {"partner", "owner"}


def _db():
    from core.supabase_client import get_service_supabase
    return get_service_supabase()


def is_partner(current_user: dict) -> bool:
    """True if the user holds the Owner-equivalent (Partner) role."""
    return str(current_user.get("role", "")).strip().lower() in _PARTNER_ROLES


def get_internal_client_id(firm_id: Optional[str]) -> Optional[str]:
    """Return firms.internal_client_id for the firm, or None (also None in mock)."""
    if not firm_id or _USE_MOCK:
        return None
    res = _db().table("firms").select("internal_client_id").eq("id", firm_id).limit(1).execute()
    if res.data:
        return res.data[0].get("internal_client_id")
    return None


def is_internal_client(client_id: Optional[str], firm_id: Optional[str]) -> bool:
    """True if client_id is this firm's internal practice client."""
    if not client_id:
        return False
    internal_id = get_internal_client_id(firm_id)
    return bool(internal_id) and str(client_id) == str(internal_id)


# ── Guardrail G1 — partner-only access to the internal client ────────────────

def assert_can_view_client(client: Optional[dict], current_user: dict) -> None:
    """G1 (row already loaded): hide the internal client from non-partners.

    Returns 404 (not 403) so the internal client's existence is not disclosed to
    staff/manager/viewer — consistent with cross-firm isolation behaviour.
    """
    if client and client.get("is_internal") and not is_partner(current_user):
        raise HTTPException(status_code=404, detail="Client not found")


def assert_partner_for_internal_id(client_id: Optional[str], current_user: dict) -> None:
    """G1 (id only): same as above when only the client_id is known."""
    if is_internal_client(client_id, current_user.get("firm_id")) and not is_partner(current_user):
        raise HTTPException(status_code=404, detail="Client not found")


# ── Guardrail G4 — module cap (no payroll/HR for the internal client) ────────

def assert_not_internal_for_payroll(client_id: Optional[str], firm_id: Optional[str]) -> None:
    """G4: the internal client gets accounting/GST/TDS/documents/reports/billing
    only — payroll/HR provisioning is blocked."""
    if is_internal_client(client_id, firm_id):
        raise HTTPException(
            status_code=403,
            detail="Payroll/HR is not available for the firm's internal practice client.",
        )


async def require_client_access(
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """G1 router-level guard (Batch 2.1). Applied via include_router(dependencies=[...])
    to every client-scoped router. Reads client_id from the path, query string, OR
    a JSON request body (writes); when it targets the firm's internal practice
    client and the caller is not a Partner, returns 404 (existence not disclosed),
    and enforces client-assignment scope (M2). No-op for requests without a
    client_id (firm-level endpoints). The portal router is intentionally NOT
    guarded here — it uses a separate auth audience.

    Module 9.0 hardening: the original guard only inspected path/query, so a write
    that carried client_id in its JSON body (e.g. creating an invoice/customer for
    an UNASSIGNED client) bypassed assignment enforcement. We now also scope the
    JSON body on POST/PUT/PATCH. Multipart/form writes (e.g. document upload) carry
    client_id outside JSON and are scoped explicitly in their handlers.
    """
    client_id = request.path_params.get("client_id") or request.query_params.get("client_id")
    if not client_id and request.method in ("POST", "PUT", "PATCH"):
        # Only JSON bodies are inspected here; reading the body caches it on the
        # Request, so the downstream handler still parses normally.
        if request.headers.get("content-type", "").startswith("application/json"):
            try:
                body = await request.json()
            except Exception:
                body = None
            if isinstance(body, dict):
                cid = body.get("client_id")
                if isinstance(cid, str) and cid.strip():
                    client_id = cid.strip()
    if client_id:
        assert_partner_for_internal_id(client_id, current_user)   # G1: internal-client
        # M2: central client-assignment enforcement (Partner/Manager firm-wide;
        # Executive/Reviewer restricted to assigned clients). 404 on unauthorized.
        from core.authz import assert_client_access
        assert_client_access(current_user, client_id)
    return current_user


# ── Provisioning (idempotent) ────────────────────────────────────────────────

# CA firms are most commonly partnerships/LLPs; used only when the caller does
# not specify an entity type. The value must be a valid clients.entity_type.
DEFAULT_INTERNAL_ENTITY_TYPE = "Partnership"
_PAN_RE = __import__("re").compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def provision(
    firm_id: str,
    legal_name: str,
    pan: Optional[str],
    entity_type: str = DEFAULT_INTERNAL_ENTITY_TYPE,
    gstin: Optional[str] = None,
    state: Optional[str] = None,
    state_code: Optional[str] = None,
    actor_id: Optional[str] = None,
) -> Optional[str]:
    """Idempotently create the firm's internal client and link
    firms.internal_client_id. Returns the internal client id, or None if it could
    not be provisioned (mock mode, or no valid PAN — clients.pan is NOT NULL +
    regex-validated). Safe to call repeatedly (e.g. on every firm creation).

    state_code is derived (Part C) from the explicit code, then the GSTIN prefix,
    then the state name — best-effort, never fatal."""
    if _USE_MOCK or not firm_id:
        return None

    existing = get_internal_client_id(firm_id)
    db = _db()
    if existing:
        chk = db.table("clients").select("id").eq("id", existing).eq("is_internal", True).limit(1).execute()
        if chk.data:
            return existing  # already provisioned

    pan_norm = (pan or "").upper().strip()
    if not _PAN_RE.match(pan_norm):
        # clients.pan is NOT NULL + regex-validated; cannot provision without it.
        _logger.warning("Skipping internal-client provisioning for firm %s: no valid PAN", firm_id)
        return None

    from core.validators import derive_state_code
    derived_state_code = derive_state_code(state_code, state, gstin)

    try:
        row = db.table("clients").insert({
            "firm_id": firm_id,
            "client_name": legal_name,
            "legal_name": legal_name,
            "entity_type": entity_type if entity_type else DEFAULT_INTERNAL_ENTITY_TYPE,
            "pan": pan_norm,
            "gstin": gstin,
            "state": state,
            "state_code": derived_state_code,
            "is_internal": True,
            "status": "active",
        }).execute()
    except Exception as e:
        # Concurrency: the partial unique index uq_clients_one_internal_per_firm
        # (migration 080) rejects a duplicate internal client — another call won
        # the race. Re-read and return the winner (idempotent, no duplicate).
        _logger.warning("Internal-client insert race for firm %s: %s", firm_id, e)
        existing = get_internal_client_id(firm_id)
        if existing:
            return existing
        chk = db.table("clients").select("id").eq("firm_id", firm_id).eq("is_internal", True).limit(1).execute()
        if chk.data:
            won = chk.data[0]["id"]
            db.table("firms").update({"internal_client_id": won}).eq("id", firm_id).execute()
            return won
        raise
    new_id = row.data[0]["id"]
    db.table("firms").update({"internal_client_id": new_id}).eq("id", firm_id).execute()
    _logger.info("Provisioned internal client %s for firm %s", new_id, firm_id)
    try:
        from services.audit_service import log_event
        log_event(
            firm_id, "client", new_id, "create", actor_id=actor_id,
            new_data={"is_internal": True, "client_name": legal_name},
            metadata={"source": "internal_client_provision", "state_code": derived_state_code},
        )
    except Exception:  # pragma: no cover - audit must never block provisioning
        pass
    return new_id
