from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from models.common import api_response
from core.permissions import rbac
from core.authz import filter_by_client
from repositories.engagement_repository import engagement_repo
from repositories.client_repository import client_repo
from datetime import datetime, timezone

router = APIRouter(prefix="/api/engagements", tags=["engagements"])


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
    current_user: dict = Depends(rbac("engagement", "read")),
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
    current_user: dict = Depends(rbac("engagement", "read")),
):
    firm_id = current_user.get("firm_id")
    engagement = engagement_repo.find_by_id(engagement_id)
    if not engagement or engagement.get("firm_id") != firm_id:
        raise HTTPException(status_code=404, detail="Engagement not found")
    return api_response(True, {"engagement": engagement})


@router.post("")
def create_engagement(
    body: EngagementCreate,
    current_user: dict = Depends(rbac("engagement", "write")),
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
    current_user: dict = Depends(rbac("engagement", "write")),
):
    firm_id = current_user.get("firm_id")
    engagement = engagement_repo.find_by_id(engagement_id)
    if not engagement or engagement.get("firm_id") != firm_id:
        raise HTTPException(status_code=404, detail="Engagement not found")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}

    if "fee_paise" in updates and updates["fee_paise"] <= 0:
        raise HTTPException(status_code=400, detail="fee_paise must be greater than 0")

    if "client_id" in updates:
        client = client_repo.find_by_id(updates["client_id"])
        if not client or client.get("firm_id") != firm_id:
            raise HTTPException(status_code=404, detail="Client not found")

    updated = engagement_repo.update(engagement_id, updates)
    return api_response(True, {"engagement": updated})


@router.delete("/{engagement_id}")
def delete_engagement(
    engagement_id: str,
    current_user: dict = Depends(rbac("engagement", "write")),
):
    firm_id = current_user.get("firm_id")
    engagement = engagement_repo.find_by_id(engagement_id)
    if not engagement or engagement.get("firm_id") != firm_id:
        raise HTTPException(status_code=404, detail="Engagement not found")

    updated = engagement_repo.update(engagement_id, {"status": "Inactive"})
    return api_response(True, {"engagement": updated})


@router.post("/{engagement_id}/transition")
def transition_engagement(
    engagement_id: str,
    body: EngagementTransition,
    current_user: dict = Depends(rbac("engagement", "write")),
):
    """Advance an engagement through its lifecycle (validated). Audited + timelined; no hard delete."""
    firm_id = current_user.get("firm_id")
    engagement = engagement_repo.find_by_id(engagement_id)
    if not engagement or engagement.get("firm_id") != firm_id:
        raise HTTPException(status_code=404, detail="Engagement not found")

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
    financial_year: Optional[str] = None,
    current_user: dict = Depends(rbac("compliance", "write")),
):
    """Generate the statutory compliance obligations this engagement implies for the
    given FY (idempotent; draft obligations only — no filing)."""
    firm_id = current_user.get("firm_id")
    engagement = engagement_repo.find_by_id(engagement_id)
    if not engagement or engagement.get("firm_id") != firm_id:
        raise HTTPException(status_code=404, detail="Engagement not found")
    from services import compliance_obligation_service as obligations
    fy = financial_year or obligations._current_fy()
    result = obligations.generate_for_engagement(firm_id, engagement, fy, actor=current_user)
    return api_response(True, {"financial_year": fy, **result})
