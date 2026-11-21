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
from core.auth import mfa_guard
import services.approval_service as approvals
import services.access_request_service as access_requests

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class RequestBody(BaseModel):
    request_type: str
    payload: dict


class RejectBody(BaseModel):
    reason: Optional[str] = None


class AccessRequestBody(BaseModel):
    resource: str
    action: str
    #: The asker's own words, shown to the Partner as such: the screen they were on, and why they are asking.
    asked_from: Optional[str] = None
    note: Optional[str] = None


# A REQUEST FOR ACCESS HAS ITS OWN DOOR (POST-A-543), declared before the `/{request_id}` routes. The general door below
# asks `approval` `request`, which a Reviewer does not hold, and the person who presses "Request access" is by definition
# somebody who holds less than they need. `identity` `write` is every member of staff's (their own profile); what may be
# asked for, by whom, and that nobody decides their own, is `services/access_request_service`. Not behind the second
# factor, like the general door: asking changes nothing, and deciding is.
@router.post("/access-requests")
def request_access(body: AccessRequestBody, current_user: dict = Depends(rbac("identity", "write"))):
    row = approvals.create_request(current_user["firm_id"], access_requests.REQUEST_TYPE, body.model_dump(), current_user)
    return api_response(True, {"id": row.get("id"), "status": row.get("status"), "asked_at": row.get("created_at")})


@router.get("/access-requests/mine")
def my_access_requests(current_user: dict = Depends(rbac("identity", "read"))):
    """The caller's OWN requests for access and what became of each. The inbox itself is `approval` `read`."""
    return api_response(True, {"requests": access_requests.mine(current_user["firm_id"], current_user)})


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


# NOT behind mfa_guard, on purpose (POST-A-006): a person whose authenticator is lost is at the password level, and asking
# for it to be reset (request_type "mfa_reset", services/mfa_reset_service) is the only thing they can do. Approving and
# rejecting ARE behind it, so a password alone never removes anybody's authenticator. A test holds both halves.
@router.post("")
def create_approval(body: RequestBody, current_user: dict = Depends(rbac("approval", "request"))):
    row = approvals.create_request(current_user["firm_id"], body.request_type, body.payload, current_user)
    return api_response(True, row)


@router.post("/{request_id}/approve")
def approve_request(
    request_id: str,
    current_user: dict = Depends(rbac("approval", "approve")),
    _mfa: dict = Depends(mfa_guard),  # Approve executes the real privileged action — MFA required
):
    return api_response(True, approvals.approve(current_user["firm_id"], request_id, current_user))


@router.post("/{request_id}/reject")
def reject_request(
    request_id: str,
    body: RejectBody,
    current_user: dict = Depends(rbac("approval", "approve")),
    _mfa: dict = Depends(mfa_guard),  # Reject is a governance action — MFA required
):
    return api_response(True, approvals.reject(current_user["firm_id"], request_id, current_user, body.reason))


@router.post("/{request_id}/cancel")
def cancel_request(request_id: str, current_user: dict = Depends(rbac("approval", "request"))):
    # The service enforces that only the requester or a Partner may cancel.
    return api_response(True, approvals.cancel(current_user["firm_id"], request_id, current_user))
