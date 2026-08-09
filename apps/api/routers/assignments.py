"""
Module 9.0 / M3 — client-assignment administration API.

Partner-administered (rbac assignment:write = Partner-only); Manager+ may read.
Creating/removing an assignment changes what the assigned user can discover,
view, search, be notified about, and provide as AI context (enforced by
core.authz). Every mutation is written to the audit_log.
"""
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access, effective_client_ids
from repositories.assignment_repository import assignment_repo
from repositories.client_repository import client_repo
from services.audit_service import log_event

router = APIRouter(prefix="/api/assignments", tags=["assignments"])

_USE_MOCK = not os.environ.get("SUPABASE_URL")


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


class AssignmentBody(BaseModel):
    user_id: str
    client_id: str


class BulkAssignmentBody(BaseModel):
    user_id: str
    client_ids: list[str]


def _validate_user_in_firm(user_id: str, firm_id: str) -> None:
    """User must exist in the caller's firm (real DB only)."""
    if _USE_MOCK:
        return
    res = (_db().table("users").select("id, firm_id, role")
           .eq("id", user_id).eq("firm_id", firm_id).limit(1).execute())
    if not res.data:
        raise HTTPException(status_code=404, detail="User not found in firm")


def _validate_client_in_firm(client_id: str, firm_id: str) -> None:
    """Client must exist in the caller's firm and must not be the internal client.

    Deliberately does NOT carry the client-assignment check: it is a validator
    that would still exist with the check stripped out, so putting the guard
    here would let the scope sweep pass on its name alone. The callers below
    assert_client_access themselves."""
    client = client_repo.find_by_id(client_id, firm_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if client.get("is_internal"):
        raise HTTPException(status_code=400,
                            detail="The firm's internal practice client cannot be assigned to staff.")


@router.post("")
def create_assignment(body: AssignmentBody, current_user: dict = Depends(rbac("assignment", "write"))):
    firm_id = current_user.get("firm_id")
    _validate_user_in_firm(body.user_id, firm_id)
    _validate_client_in_firm(body.client_id, firm_id)
    # assignment:write is Partner-only (core/permissions.py) and the Partner is
    # the sole firm-wide role, so this can never deny a real caller today. It is
    # the fail-closed default for if assignment administration is ever opened to
    # Manager, where granting access to a client outside your own book is the
    # escalation Module 9 exists to prevent. Same convention as billing.py's
    # Partner-only routes and clients.py's delete_client.
    assert_client_access(current_user, body.client_id)
    row = assignment_repo.create(firm_id, body.user_id, body.client_id)
    log_event(firm_id, "user_client_assignment", body.client_id, "create",
              actor_id=current_user.get("id"), actor_email=current_user.get("email"),
              new_data={"user_id": body.user_id, "client_id": body.client_id})
    return api_response(True, row)


@router.post("/bulk")
def create_bulk(body: BulkAssignmentBody, current_user: dict = Depends(rbac("assignment", "write"))):
    firm_id = current_user.get("firm_id")
    _validate_user_in_firm(body.user_id, firm_id)
    created = []
    for cid in body.client_ids:
        _validate_client_in_firm(cid, firm_id)
        assert_client_access(current_user, cid)
        created.append(assignment_repo.create(firm_id, body.user_id, cid))
    log_event(firm_id, "user_client_assignment", body.user_id, "create",
              actor_id=current_user.get("id"), actor_email=current_user.get("email"),
              new_data={"user_id": body.user_id, "client_ids": body.client_ids})
    return api_response(True, {"created": created, "count": len(created)})


@router.delete("")
def remove_assignment(
    user_id: str = Query(...),
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("assignment", "write")),
):
    firm_id = current_user.get("firm_id")
    assert_client_access(current_user, client_id)
    removed = assignment_repo.remove(firm_id, user_id, client_id)
    if not removed:
        return api_response(False, None, "Assignment not found")
    log_event(firm_id, "user_client_assignment", client_id, "delete",
              actor_id=current_user.get("id"), actor_email=current_user.get("email"),
              old_data={"user_id": user_id, "client_id": client_id})
    return api_response(True, {"user_id": user_id, "client_id": client_id, "removed": True})


@router.get("/clients/{client_id}")
def list_client_assignments(client_id: str, current_user: dict = Depends(rbac("assignment", "read"))):
    """User ids assigned to a client.

    M2: assignment:read is Manager+, and this router mounts the MFA guard
    rather than the client guard, so nothing checked client_id before —
    a Manager could enumerate the staff roster of any client in the firm."""
    firm_id = current_user.get("firm_id")
    assert_client_access(current_user, client_id)
    return api_response(True, {"client_id": client_id, "user_ids": assignment_repo.list_for_client(firm_id, client_id)})


@router.get("/users/{user_id}")
def list_user_assignments(user_id: str, current_user: dict = Depends(rbac("assignment", "read"))):
    """Client ids assigned to a user, narrowed to the caller's own book.

    M2: this endpoint is addressed by a STAFF user_id, so there is no
    client_id for assert_client_access to gate — and assignment:read is
    Manager+ while only the Partner is firm-wide (core.authz's M3 decision).
    Unnarrowed, a Manager could pass any colleague's user_id and read back
    that person's entire client book, which is precisely the "one manager
    cannot see another manager's book" goal Module 9 is built around.
    effective_client_ids returns None for the Partner, who still sees the
    full list."""
    firm_id = current_user.get("firm_id")
    client_ids = assignment_repo.list_for_user(firm_id, user_id)
    eff = effective_client_ids(current_user)
    if eff is not None:
        client_ids = [cid for cid in client_ids if str(cid) in eff]
    return api_response(True, {"user_id": user_id, "client_ids": client_ids})
