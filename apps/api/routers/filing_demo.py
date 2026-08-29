"""Filing-demo endpoints — one preview per statutory flow, all read-only.

WHAT THIS ROUTER IS AND IS NOT
    It serves the portal-faithful walk-throughs (services/filing_demo/) that
    show what each filing WILL look like once real transmission exists. It
    performs no write of any kind: no status moves, no filings row, no audit
    entry claiming a filing, no contact with any government system. The real
    "this was filed on the portal" paths live in each module's own router and
    are untouched by anything here.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    Nothing here can submit. When real filing is built it is a new endpoint
    behind explicit CA confirmation, and these demos are deleted rather than
    repointed — everything that makes them safe is that they cannot file.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core.authz import assert_client_access
from core.permissions import can, rbac
from models.common import api_response
from services import filing_demo
from services.filing_demo.common import filing_simulation_enabled

router = APIRouter(prefix="/api/filing-demo", tags=["filing_demo"])
_logger = logging.getLogger("caflow.filing_demo")


class PreviewRequest(BaseModel):
    client_id: str
    # Flow-specific addressing — e.g. {"return_id": ...} for GST returns,
    # {"quarter": ..., "fy": ...} for TDS, {"month": ...} for PF/ESI. Each
    # flow module documents and validates what it needs.
    ref: dict = Field(default_factory=dict)


@router.get("/capabilities")
def capabilities(current_user: dict = Depends(rbac("compliance_record", "read"))):
    """What this build can demo, so screens never offer a button that errors.

    The dead-control rule, learned twice on this feature already: a capability
    the server does not have must not be offered by the screen, and only the
    server knows. Flows are filtered to the caller's role so a button never
    appears that the preview endpoint would then refuse.
    """
    enabled = filing_simulation_enabled()
    role = current_user.get("role", "")
    return api_response(True, {
        "enabled": enabled,
        "flows": ([k for k, (_b, resource) in filing_demo.FLOWS.items()
                   if can(role, resource, "read")] if enabled else []),
        # Stated so no screen ever has to infer it: real transmission does not
        # exist in this build, for any filing.
        "real_filing": False,
    })


@router.post("/{flow}/preview")
def preview(flow: str, body: PreviewRequest,
            current_user: dict = Depends(rbac("compliance_record", "read"))):
    """Build one flow's walk-through script. Read-only — see the module header.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    # Before the database is touched at all, let alone the client's figures.
    assert_client_access(current_user, body.client_id)

    if not filing_simulation_enabled():
        return api_response(False, None,
            "Filing demos are switched off on this deployment "
            "(ENABLE_FILING_SIMULATION=false).")

    entry = filing_demo.FLOWS.get(flow)
    if entry is None:
        return api_response(False, None,
            f"Unknown filing demo '{flow}'. Available: "
            f"{', '.join(sorted(filing_demo.FLOWS))}.")
    builder, resource = entry

    # The demo shows the module's real figures, so it is gated like the
    # module: a role without payroll read does not get the PF walk-through.
    if not can(current_user.get("role", ""), resource, "read"):
        return api_response(False, None,
            "Your role does not have access to this module's figures.")

    from core.supabase_client import get_supabase
    try:
        script = builder(get_supabase(), current_user["firm_id"],
                         body.client_id, body.ref or {})
    except ValueError as ve:
        # A flow's own refusal (bad ref, record not found, not built yet) is
        # an answer, not an incident.
        return api_response(False, None, str(ve))
    except Exception:
        _logger.exception("filing demo %s failed", flow)
        return api_response(False, None,
            "Couldn't build this walk-through. Please try again.")
    return api_response(True, script)
