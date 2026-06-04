"""
Compliance Records router.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from core.auth import get_current_user
from typing import Optional
from models.common import api_response
from domain.compliance_record_service import compliance_record_service
from core.exceptions import NotFoundError, ValidationError

router = APIRouter(prefix="/api/compliance-records", tags=["compliance-records"])


@router.get("")
def list_compliance_records(
    client_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    compliance_type: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    records = compliance_record_service.list_records(
        client_id=client_id,
        status=status,
        compliance_type=compliance_type,
    )
    return api_response(True, records)


@router.post("")
def create_compliance_record(data: dict, current_user: dict = Depends(get_current_user)):
    try:
        record = compliance_record_service.create_record(data)
        return api_response(True, record)
    except (ValidationError, KeyError) as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/firm/summary")
def get_firm_summary(current_user: dict = Depends(get_current_user)):
    summary = compliance_record_service.get_firm_summary()
    return api_response(True, summary)


@router.get("/client/{client_id}/health")
def get_client_health(client_id: str, current_user: dict = Depends(get_current_user)):
    try:
        health = compliance_record_service.get_client_health_score(client_id)
        return api_response(True, health)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{record_id}")
def get_compliance_record(record_id: str, current_user: dict = Depends(get_current_user)):
    try:
        record = compliance_record_service.get_record(record_id)
        return api_response(True, record)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{record_id}")
def update_compliance_record(record_id: str, data: dict, current_user: dict = Depends(get_current_user)):
    try:
        record = compliance_record_service.update_record(record_id, data)
        return api_response(True, record)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
