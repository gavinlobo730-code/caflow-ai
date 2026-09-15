"""The GST registrations a client holds (GST-20).

CGST Act s.25(1) requires registration in every State or Union territory from
which a taxable supply is made, and s.25(2)'s proviso allows a separate
registration per place of business inside one state — so one legal person may
hold several GSTINs. `clients.gstin` holds the PRIMARY and this manages the
rest; `domain/gst/registrations.py` presents the union and decides everything.

WRITES ARE `client.write`, NOT a GST action, and the reason is where the
PRIMARY lives: `clients.gstin` is written under `client.write` by onboarding and
the client edit screen, and an additional registration is the same kind of fact
about the same entity. Giving it a GST action would mean an Executive who may
COMPUTE a return could also add the registration it is filed under, while being
unable to correct the primary sitting beside it. READS stay `gst.read`, because
every GST screen needs the list to render its selector and `_ALL_STAFF` already
reach those screens.

Nothing here transmits anything to any portal.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core.authz import assert_client_access
from core.permissions import rbac
from models.common import api_response
from domain.gst import registrations as reg
from services import client_gst_registration_service as svc

router = APIRouter(prefix="/api/client-gst-registrations",
                   tags=["client_gst_registrations"])


class RegistrationIn(BaseModel):
    """An additional registration.

    `state_code` is OPTIONAL and is derived from the GSTIN when omitted — a
    registration is state-wise, so the number already says which state. Sending
    one that disagrees is refused rather than silently overridden, because one
    of the two is then wrong and guessing which puts every supply under this
    registration in the wrong state.
    """
    client_id: str
    gstin: str
    state_code: Optional[str] = None
    registration_type: str = reg.REGULAR
    filing_frequency: str = reg.MONTHLY
    trade_name: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    notes: Optional[str] = None


class CloseRegistrationIn(BaseModel):
    client_id: str
    effective_to: str


def _mock_enabled() -> bool:
    from core.config import settings as _s
    return bool(getattr(_s, "USE_MOCK_DATA", False))


@router.get("/kinds")
def list_kinds(current_user: dict = Depends(rbac("gst", "read"))):
    """The registration types and filing frequencies, with which of them file
    GSTR-1 and GSTR-3B at all — so a screen holds labels and no statute.

    A composition dealer, an ISD, a s.51 deductor and a s.52 collector each owe
    a DIFFERENT form, and `other_return_form` names it. Offering them a GSTR-3B
    screen offers a return they must not file.
    """
    return api_response(True, {
        "registration_types": [
            {
                "value": t,
                "files_gstr1_and_3b": t in reg.FILES_GSTR1_AND_3B,
                "other_return_form": reg.OTHER_RETURN_FORMS.get(t),
            }
            for t in reg.REGISTRATION_TYPES
        ],
        "filing_frequencies": list(reg.FILING_FREQUENCIES),
    })


@router.get("")
def list_registrations(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("gst", "read")),
):
    """Every GSTIN this client holds, primary first."""
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, [])
    from core.supabase_client import get_supabase
    return api_response(True, svc.listing(
        get_supabase(), current_user.get("firm_id"), client_id))


@router.post("")
def add_registration(
    data: RegistrationIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    assert_client_access(current_user, data.client_id)
    if _mock_enabled():
        return api_response(True, {"id": "mock-registration", **data.model_dump()})
    from core.supabase_client import get_supabase
    from services.audit_service import log_event
    row = svc.create(
        get_supabase(), current_user.get("firm_id"), data.client_id,
        gstin=data.gstin, state_code=data.state_code,
        registration_type=data.registration_type,
        filing_frequency=data.filing_frequency, trade_name=data.trade_name,
        address_line1=data.address_line1, address_line2=data.address_line2,
        city=data.city, pincode=data.pincode,
        effective_from=data.effective_from, effective_to=data.effective_to,
        notes=data.notes, actor_id=current_user.get("id"))
    log_event(current_user.get("firm_id") or "", "client_gst_registration",
              row.get("id") or "", "create",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=row)
    return api_response(True, row)


@router.post("/{registration_id}/close")
def close_registration(
    registration_id: str,
    data: CloseRegistrationIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    """Record a CGST Act s.29 cancellation or surrender.

    Not a delete: the returns for every period the registration was live are
    still owed, and the rows already prepared are keyed on its GSTIN.
    """
    assert_client_access(current_user, data.client_id)
    if _mock_enabled():
        return api_response(True, {"id": registration_id,
                                   "effective_to": data.effective_to})
    from core.supabase_client import get_supabase
    from services.audit_service import log_event
    row = svc.close(get_supabase(), current_user.get("firm_id"),
                    registration_id, effective_to=data.effective_to)
    log_event(current_user.get("firm_id") or "", "client_gst_registration",
              registration_id, "close",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"),
              new_data={"effective_to": data.effective_to})
    return api_response(True, row)


@router.delete("/{registration_id}")
def withdraw_registration(
    registration_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("client", "write")),
):
    """Remove a registration recorded in error. Refused once a return has been
    prepared under it — a registration that ENDED is closed, not withdrawn."""
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, {"id": registration_id, "deleted": True})
    from core.supabase_client import get_supabase
    from services.audit_service import log_event
    row = svc.withdraw(get_supabase(), current_user.get("firm_id"), registration_id)
    log_event(current_user.get("firm_id") or "", "client_gst_registration",
              registration_id, "delete",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), old_data=row)
    return api_response(True, {"id": registration_id, "deleted": True})
