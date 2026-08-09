"""
Portal Access (CA-side) router — Phase 4.5.1.

Lets firm staff enable a client's portal and manage its contacts (invite / resend /
deactivate) for the multi-contact model. CA-facing: rbac("portal", ...). The
client-facing surface is routers/portal_self.py. Reuses Supabase auth; creates no
parallel auth system.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access, can_access_client
from services import portal_access_service as portal

router = APIRouter(prefix="/api/portal", tags=["portal_access"])


class InviteContactBody(BaseModel):
    email: str
    name: Optional[str] = None


def _assert_contact_scope(current_user: dict, contact_id: str) -> dict:
    """Resolve a client_portal_users row and refuse (identical message for
    both "no such row" and "not your client") unless it belongs to the
    caller's firm and the caller may access its client.

    # M2 audit finding: resend/deactivate resolved the contact by firm_id
    # alone (via portal.get_contact) and never checked its client against
    # the caller's assignment.
    """
    contact = portal.get_contact(current_user["firm_id"], contact_id)
    if not contact or not can_access_client(current_user, contact.get("client_id")):
        raise HTTPException(status_code=404, detail="Portal contact not found.")
    return contact


@router.get("/clients/{client_id}/contacts")
def list_portal_contacts(client_id: str = Path(...),
                         current_user: dict = Depends(rbac("portal", "read"))):
    """List the portal contacts (and their lifecycle status) for a client."""
    # M2 audit finding: this previously only checked the client belonged to
    # the caller's firm, not that the caller was assigned to it.
    assert_client_access(current_user, client_id)
    return api_response(True, {"contacts": portal.list_contacts(current_user["firm_id"], client_id)})


@router.post("/clients/{client_id}/contacts")
def invite_portal_contact(client_id: str, body: InviteContactBody,
                          current_user: dict = Depends(rbac("portal", "write"))):
    """Enable the client's portal and invite a contact (idempotent per email)."""
    # M2 audit finding: this previously only checked the client belonged to
    # the caller's firm, not that the caller was assigned to it.
    assert_client_access(current_user, client_id)
    contact = portal.invite_contact(current_user["firm_id"], client_id,
                                    body.email, body.name, actor=current_user)
    return api_response(True, {"contact": contact})


@router.post("/contacts/{contact_id}/resend")
def resend_portal_invite(contact_id: str,
                         current_user: dict = Depends(rbac("portal", "write"))):
    """Re-send a pending invitation."""
    _assert_contact_scope(current_user, contact_id)
    return api_response(True, {"contact": portal.resend_invite(current_user["firm_id"], contact_id, actor=current_user)})


@router.post("/contacts/{contact_id}/deactivate")
def deactivate_portal_contact(contact_id: str,
                              current_user: dict = Depends(rbac("portal", "write"))):
    """Revoke a contact's portal access (no hard delete)."""
    _assert_contact_scope(current_user, contact_id)
    return api_response(True, {"contact": portal.deactivate_contact(current_user["firm_id"], contact_id, actor=current_user)})
