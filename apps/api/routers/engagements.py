from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from models.common import api_response
from core.permissions import rbac
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


class EngagementUpdate(BaseModel):
    client_id: Optional[str] = None
    service_type: Optional[str] = None
    fee_paise: Optional[int] = None
    billing_cycle: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


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
    client = client_repo.find_by_id(body.client_id)
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
