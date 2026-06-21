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
from services import portal_access_service as portal

router = APIRouter(prefix="/api/portal", tags=["portal_access"])


class InviteContactBody(BaseModel):
    email: str
    name: Optional[str] = None


def _assert_client_in_firm(firm_id: str, client_id: str) -> None:
    try:
        from repositories.client_repository import client_repo
        client = client_repo.find_by_id(client_id)
    except Exception:
        client = None
    if client is not None and client.get("firm_id") and client.get("firm_id") != firm_id:
        raise HTTPException(status_code=404, detail="Client not found")


@router.get("/clients/{client_id}/contacts")
def list_portal_contacts(client_id: str = Path(...),
                         current_user: dict = Depends(rbac("portal", "read"))):
    """List the portal contacts (and their lifecycle status) for a client."""
    _assert_client_in_firm(current_user["firm_id"], client_id)
    return api_response(True, {"contacts": portal.list_contacts(current_user["firm_id"], client_id)})


@router.post("/clients/{client_id}/contacts")
def invite_portal_contact(client_id: str, body: InviteContactBody,
                          current_user: dict = Depends(rbac("portal", "write"))):
    """Enable the client's portal and invite a contact (idempotent per email)."""
    _assert_client_in_firm(current_user["firm_id"], client_id)
    contact = portal.invite_contact(current_user["firm_id"], client_id,
                                    body.email, body.name, actor=current_user)
    return api_response(True, {"contact": contact})


@router.post("/contacts/{contact_id}/resend")
def resend_portal_invite(contact_id: str,
                         current_user: dict = Depends(rbac("portal", "write"))):
    """Re-send a pending invitation."""
    return api_response(True, {"contact": portal.resend_invite(current_user["firm_id"], contact_id, actor=current_user)})


@router.post("/contacts/{contact_id}/deactivate")
def deactivate_portal_contact(contact_id: str,
                              current_user: dict = Depends(rbac("portal", "write"))):
    """Revoke a contact's portal access (no hard delete)."""
    return api_response(True, {"contact": portal.deactivate_contact(current_user["firm_id"], contact_id, actor=current_user)})
