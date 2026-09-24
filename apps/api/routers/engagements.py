from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from models.common import api_response
from core.permissions import rbac
from core.authz import filter_by_client, assert_client_access, can_access_client
from repositories.engagement_repository import engagement_repo
from repositories.client_repository import client_repo
from datetime import datetime, timezone
from models.fy import OptionalFYLabel

router = APIRouter(prefix="/api/engagements", tags=["engagements"])


# ── WHICH PERMISSION GOVERNS A FEE ENGAGEMENT (G2) ────────────────────────────
#
# This router writes `fee_engagements`, whose rows carry `fee_paise` — what the
# practice charges that client. Two authorities answered differently and a whole
# tier apart:
#
#   core/permissions.py   billing:write     Partner only  ("exposes fee economics")
#   core/permissions.py   engagement:write  Manager+
#   migration 260         RLS on the table  Partner, and its comment cites billing
#   this router (before)  rbac("engagement", …)           Manager+
#
# It is `billing`. The row carries the fee and the matrix is Partner *because
# of* that; migration 260 read it the same way. The other reading would have
# meant loosening the database so a Manager may set fee economics, which is a
# widening nobody asked for.
#
# THIS REMOVES NOTHING ANYBODY CAN DO TODAY, which is what made it decidable
# rather than an owner question. Measured 24-09-2026: `apps/web` mentions
# `/api/engagements` NOWHERE — `lib/api/index.ts` had no `engagements`
# namespace, so all seven endpoints were unreachable from the browser — and the
# billing screen's own PostgREST insert was already refused for a Manager by
# migration 260's RESTRICTIVE policy (`USE_USER_JWT` is true in production, so
# RLS applies on both paths). No journey existed in which a Manager created a
# fee engagement.
#
# AND THE PER-PERSON GRID IS WHY THE TIER IS NOT THE LAST WORD. `rbac()`
# resolves migration 403's overrides, so a Partner who wants one Manager on
# billing grants that person `billing:write` on the Team screen. That is the
# control, and pointing this router at `engagement` was pointing the grid at
# the wrong checkbox for this row.
#
# `generate-obligations` keeps `compliance:write`: it writes compliance
# records, not fee economics.


# ── Client-assignment scope (M2) ──────────────────────────────────────────────
# The "guards the body, not the record" shape again: the list was narrowed and
# create checked its body, but every ROW-addressed endpoint checked only the
# firm — so any member could read, edit, soft-delete or transition any client's
# fee engagement, and generate statutory obligations into their compliance
# records. fee_engagements.client_id is NOT NULL (migration 014), and every
# handler already loads the row, so the guard reads what is in hand.

def _assert_engagement_scope(current_user: dict, engagement) -> dict:
    """Firm check + client check, one 404. Takes whatever find_by_id returned."""
    if not engagement or engagement.get("firm_id") != current_user.get("firm_id"):
        raise HTTPException(status_code=404, detail="Engagement not found")
    # Same detail as the branch above, not assert_client_access's generic
    # "Not found" — a distinct message would be an oracle for which ids exist.
    if not can_access_client(current_user, engagement.get("client_id")):
        raise HTTPException(status_code=404, detail="Engagement not found")
    return engagement


class EngagementCreate(BaseModel):
    client_id: str
    service_type: str
    fee_paise: int = Field(gt=0)
    billing_cycle: str
    start_date: str
    status: str = "Active"
    notes: Optional[str] = None
    # Phase 4.4 (Module A) — assignment chain + deadline (all optional, additive)
    assigned_to: Optional[str] = None
    reviewer_id: Optional[str] = None
    partner_id: Optional[str] = None
    due_date: Optional[str] = None


class EngagementUpdate(BaseModel):
    client_id: Optional[str] = None
    service_type: Optional[str] = None
    fee_paise: Optional[int] = None
    billing_cycle: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    assigned_to: Optional[str] = None
    reviewer_id: Optional[str] = None
    partner_id: Optional[str] = None
    due_date: Optional[str] = None


class EngagementTransition(BaseModel):
    status: str
    notes: Optional[str] = None


# Phase 4.4 Module A — engagement lifecycle (Draft → Active → In Progress →
# Review → Completed → Closed). 'Inactive' retained for backward-compatibility
# (the legacy soft-delete). No hard deletes; audited + timelined.
ENGAGEMENT_TRANSITIONS: dict[str, list[str]] = {
    "Draft": ["Active", "Closed"],
    "Active": ["In Progress", "Closed", "Inactive"],
    "In Progress": ["Review", "Active", "Closed"],
    "Review": ["Completed", "In Progress"],
    "Completed": ["Closed"],
    "Closed": [],
    "Inactive": ["Active"],
}


@router.get("")
def list_engagements(
    client_id: Optional[str] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(rbac("billing", "read")),
):
    firm_id = current_user.get("firm_id")
    engagements = engagement_repo.find_all(
        firm_id=firm_id,
        client_id=client_id,
        status=status,
    )
    engagements = filter_by_client(current_user, engagements)  # M2/M5: assignment scope
    return api_response(True, {"engagements": engagements, "total": len(engagements)})


@router.get("/{engagement_id}")
def get_engagement(
    engagement_id: str,
    current_user: dict = Depends(rbac("billing", "read")),
):
    firm_id = current_user.get("firm_id")
    engagement = _assert_engagement_scope(
        current_user, engagement_repo.find_by_id(engagement_id))
    return api_response(True, {"engagement": engagement})


@router.post("")
def create_engagement(
    body: EngagementCreate,
    current_user: dict = Depends(rbac("billing", "write")),
):
    from core.authz import assert_client_access
    assert_client_access(current_user, body.client_id)  # M6 #7: body client_id guard
    client = client_repo.find_by_id(body.client_id, current_user.get("firm_id"))
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    firm_id = current_user.get("firm_id")
    if client.get("firm_id") != firm_id:
        raise HTTPException(status_code=404, detail="Client not found")

    engagement = engagement_repo.create({
        **body.model_dump(),
        "firm_id": firm_id,
    })
    return api_response(True, {"engagement": engagement})


@router.patch("/{engagement_id}")
def update_engagement(
    engagement_id: str,
    body: EngagementUpdate,
    current_user: dict = Depends(rbac("billing", "write")),
):
    firm_id = current_user.get("firm_id")
    engagement = _assert_engagement_scope(
        current_user, engagement_repo.find_by_id(engagement_id))

    updates = {k: v for k, v in body.model_dump().items() if v is not None}

    if "fee_paise" in updates and updates["fee_paise"] <= 0:
        raise HTTPException(status_code=400, detail="fee_paise must be greater than 0")

    if "client_id" in updates:
        # Both ends: _assert_engagement_scope above checked the engagement
        # being edited; this checks the client it is being MOVED to. The old
        # firm-membership test let an assigned-scope caller push an engagement
        # into any client's book in the firm.
        assert_client_access(current_user, updates["client_id"])
        client = client_repo.find_by_id(updates["client_id"])
        if not client or client.get("firm_id") != firm_id:
            raise HTTPException(status_code=404, detail="Client not found")

    updated = engagement_repo.update(engagement_id, updates)
    return api_response(True, {"engagement": updated})


@router.delete("/{engagement_id}")
def delete_engagement(
    engagement_id: str,
    current_user: dict = Depends(rbac("billing", "write")),
):
    firm_id = current_user.get("firm_id")
    engagement = _assert_engagement_scope(
        current_user, engagement_repo.find_by_id(engagement_id))

    updated = engagement_repo.update(engagement_id, {"status": "Inactive"})
    return api_response(True, {"engagement": updated})


@router.post("/{engagement_id}/transition")
def transition_engagement(
    engagement_id: str,
    body: EngagementTransition,
    current_user: dict = Depends(rbac("billing", "write")),
):
    """Advance an engagement through its lifecycle (validated). Audited + timelined; no hard delete."""
    firm_id = current_user.get("firm_id")
    engagement = _assert_engagement_scope(
        current_user, engagement_repo.find_by_id(engagement_id))

    old_status = engagement.get("status", "Draft")
    allowed = ENGAGEMENT_TRANSITIONS.get(old_status, [])
    if body.status not in allowed:
        raise HTTPException(status_code=422,
                            detail=f"Cannot transition engagement from '{old_status}' to '{body.status}'. Allowed: {allowed}")
    updates = {"status": body.status}
    if body.notes is not None:
        updates["notes"] = body.notes
    updated = engagement_repo.update(engagement_id, updates)

    # Module H — audit + timeline (best-effort; never blocks the transition).
    try:
        from services.audit_service import log_event
        log_event(firm_id, "engagement", engagement_id, "status_change",
                  actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
                  old_data={"status": old_status}, new_data={"status": body.status})
    except Exception:
        pass
    try:
        from services.timeline_service import timeline_service
        timeline_service.log(engagement.get("client_id", ""), "compliance", "Engagement Updated",
                             f"{engagement.get('service_type', 'Engagement')}: {old_status} → {body.status}",
                             "info", firm_id=firm_id, entity_type="engagement", entity_id=engagement_id)
    except Exception:
        pass
    return api_response(True, {"engagement": updated})


@router.post("/{engagement_id}/generate-obligations")
def generate_engagement_obligations(
    engagement_id: str,
    financial_year: OptionalFYLabel = None,
    current_user: dict = Depends(rbac("compliance", "write")),
):
    """Generate the statutory compliance obligations this engagement implies for the
    given FY (idempotent; draft obligations only — no filing)."""
    firm_id = current_user.get("firm_id")
    engagement = _assert_engagement_scope(
        current_user, engagement_repo.find_by_id(engagement_id))
    from services import compliance_obligation_service as obligations
    fy = financial_year or obligations._current_fy()
    result = obligations.generate_for_engagement(firm_id, engagement, fy, actor=current_user)
    return api_response(True, {"financial_year": fy, **result})
