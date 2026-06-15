"""
Module 9.0 / M4 — Governance approval inbox API (maker-checker).

Makers (Executive+) submit requests; Partners (checker) approve/reject; Manager+
read the inbox. Approving executes the real action via services.approval_service
handlers; every transition is audited.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from models.common import api_response
from core.permissions import rbac
import services.approval_service as approvals

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class RequestBody(BaseModel):
    request_type: str
    payload: dict


class RejectBody(BaseModel):
    reason: Optional[str] = None


@router.get("")
def list_approvals(status: Optional[str] = Query(None), current_user: dict = Depends(rbac("approval", "read"))):
    return api_response(True, {"requests": approvals.list_requests(current_user["firm_id"], status=status)})


@router.get("/types")
def list_request_types(current_user: dict = Depends(rbac("approval", "read"))):
    return api_response(True, {"request_types": list(approvals.REQUEST_TYPES)})


@router.get("/{request_id}")
def get_approval(request_id: str, current_user: dict = Depends(rbac("approval", "read"))):
    req = approvals.get_request(current_user["firm_id"], request_id)
    if not req:
        raise HTTPException(404, "Approval request not found")
    return api_response(True, req)


@router.post("")
def create_approval(body: RequestBody, current_user: dict = Depends(rbac("approval", "request"))):
    row = approvals.create_request(current_user["firm_id"], body.request_type, body.payload, current_user)
    return api_response(True, row)


@router.post("/{request_id}/approve")
def approve_request(request_id: str, current_user: dict = Depends(rbac("approval", "approve"))):
    return api_response(True, approvals.approve(current_user["firm_id"], request_id, current_user))


@router.post("/{request_id}/reject")
def reject_request(request_id: str, body: RejectBody, current_user: dict = Depends(rbac("approval", "approve"))):
    return api_response(True, approvals.reject(current_user["firm_id"], request_id, current_user, body.reason))


@router.post("/{request_id}/cancel")
def cancel_request(request_id: str, current_user: dict = Depends(rbac("approval", "request"))):
    # The service enforces that only the requester or a Partner may cancel.
    return api_response(True, approvals.cancel(current_user["firm_id"], request_id, current_user))
