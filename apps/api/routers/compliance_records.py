"""
Compliance Records router.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from core.permissions import rbac
from core.authz import filter_by_client, assert_client_access  # H2: assignment-scope (same engine as compliance_ops)
from typing import Optional, Any
from models.common import api_response
from domain.compliance_record_service import compliance_record_service
from core.exceptions import NotFoundError, ValidationError


class ComplianceRecordIn(BaseModel):
    """Typed wrapper — fields delegated to domain service for validation."""
    client_id: str
    compliance_type: str
    financial_year: Optional[str] = None
    due_date: Optional[str] = None
    status: str = "pending"
    notes: Optional[str] = None


class ComplianceRecordUpdateIn(BaseModel):
    status: Optional[str] = None
    due_date: Optional[str] = None
    notes: Optional[str] = None
    filing_date: Optional[str] = None
    acknowledgement_no: Optional[str] = None

router = APIRouter(prefix="/api/compliance-records", tags=["compliance-records"])


@router.get("")
def list_compliance_records(
    client_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    compliance_type: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("compliance_record", "read")),
):
    firm_id = current_user.get("firm_id")
    records = compliance_record_service.list_records(
        firm_id=firm_id,
        client_id=client_id,
        status=status,
        compliance_type=compliance_type,
    )
    # H2 fix: drop records for clients this caller is not assigned to (firm-wide
    # roles are unaffected; mock/dev is permissive). Mirrors compliance_ops.py.
    records = filter_by_client(current_user, records)
    return api_response(True, records)


@router.post("")
def create_compliance_record(data: ComplianceRecordIn, current_user: dict = Depends(rbac("compliance_record", "write"))):
    try:
        # firm_id always comes from the authenticated user — never from the request body
        record = compliance_record_service.create_record(data.model_dump(), firm_id=current_user["firm_id"])
        return api_response(True, record)
    except (ValidationError, KeyError) as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/firm/summary")
def get_firm_summary(current_user: dict = Depends(rbac("compliance_record", "read"))):
    summary = compliance_record_service.get_firm_summary(firm_id=current_user.get("firm_id"))
    return api_response(True, summary)


@router.get("/client/{client_id}/health")
def get_client_health(client_id: str, current_user: dict = Depends(rbac("compliance_record", "read"))):
    try:
        health = compliance_record_service.get_client_health_score(
            client_id, firm_id=current_user.get("firm_id")
        )
        return api_response(True, health)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{record_id}")
def get_compliance_record(record_id: str, current_user: dict = Depends(rbac("compliance_record", "read"))):
    try:
        record = compliance_record_service.get_record(record_id, firm_id=current_user.get("firm_id"))
        # H2 fix: 404 (existence hidden) if the caller is not assigned to this record's client.
        assert_client_access(current_user, record.get("client_id"))
        return api_response(True, record)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{record_id}")
def update_compliance_record(record_id: str, data: ComplianceRecordUpdateIn, current_user: dict = Depends(rbac("compliance_record", "write"))):
    try:
        record = compliance_record_service.update_record(
            record_id, data.model_dump(exclude_none=True), firm_id=current_user.get("firm_id")
        )
        return api_response(True, record)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
