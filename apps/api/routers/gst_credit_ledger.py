"""The opening balance of the electronic credit ledger, as a CA keys it (gst-06).

THIN, BY DESIGN. The rule is `domain/gst/credit_ledger.py` (which source wins and
what is said when none exists) and the reads and the one write are
`services/gst_credit_ledger_service.py`; this module decides only who may ask
and what shape the request has. Read the domain header first.

WHAT A KEYED BALANCE IS. A statement about the PORTAL: what the Electronic Credit
Ledger showed for this GSTIN when this return's window opened. It is an INPUT to
the GSTR-3B set-off, never a ledger entry — nothing is posted, nothing is filed,
and the portal is not contacted. It serves the first period a client has here
and any later period where the portal differs from the chain of saved returns.

ONE REGISTRATION AT A TIME. The ledger is per GSTIN (CGST Act s.49(1)), and a
GSTIN the client does not hold is refused, never defaulted to the primary — the
same rule every GST compute path in this product keeps.

REFUSED ONCE THE WINDOW'S RETURN IS FILED. A filed return recorded the opening it
was computed with and cannot be revised (CGST s.39 with s.37); re-keying the
balance afterwards would leave this table disagreeing with it. A correction
belongs in the NEXT window's opening.

# CA REVIEW REQUIRED — a keyed balance changes the cash figure on a return. It
# files nothing and posts nothing.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.authz import assert_client_access
from core.permissions import rbac
from domain.gst import credit_ledger as ledger
from domain.gst import return_period
from models.common import api_response
from services import client_gst_registration_service as regs
from services import gst_credit_ledger_service as service
from services.audit_service import log_event
from core import db_provider

_logger = logging.getLogger("caflow.gst_credit_ledger")

router = APIRouter(prefix="/api/gst-workspace/credit-ledger", tags=["gst"])


def _db():
    """The privileged client, or a 503 with no database. Every route is rbac()-
gated and checks the client scope first; the service carries `firm_id` and
`client_id` on every read and write. The table's writes are service-role-only
by grant (migration 474), so this is the client they need."""
    return db_provider.service_db_or_503('The credit-ledger opening balance is kept in the database and is unavailable without it.')


def _window(db, firm_id: str, client_id: str, period: str,
            gstin: Optional[str]):
    """Resolve (registration, return window) or refuse in words.

    The registration decides the frequency, and the frequency decides which
    window a month belongs to — a quarterly registration's May is the quarter
    that opens in April, so the balance is keyed on that window's first day.
    """
    registration = regs.resolve(db, firm_id, client_id, gstin)
    try:
        window = return_period.resolve(period, registration.filing_frequency)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return registration, window


class OpeningIn(BaseModel):
    client_id: str
    #: Any month of the return window, MMYYYY. The window is resolved from the
    #: registration's own filing frequency.
    period: str
    gstin: Optional[str] = None
    # Strict ints: a balance that moves cash payable is not coerced from a string
    # or a float, and a negative one is refused here as well as by the table.
    igst_paise: int = Field(ge=0, strict=True)
    cgst_paise: int = Field(ge=0, strict=True)
    sgst_paise: int = Field(ge=0, strict=True)
    cess_paise: int = Field(ge=0, strict=True)
    #: Where it was read: "Electronic Credit Ledger, 1 May 2026". Optional.
    note: Optional[str] = Field(default=None, max_length=500)


@router.get("/opening")
def get_opening(
    client_id: str = Query(...),
    period: str = Query(..., description="MMYYYY — any month of the window"),
    gstin: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("gst", "read")),
):
    """What this window opens with, where that came from and whether it was
    KNOWN — plus whether the return is already filed, which closes the form."""
    assert_client_access(current_user, client_id)
    firm_id = current_user["firm_id"]
    db = _db()
    registration, window = _window(db, firm_id, client_id, period, gstin)
    opening = service.opening_for(db, firm_id, client_id, registration.gstin, window.start)
    return api_response(True, {
        "gstin": registration.gstin,
        "window": window.as_dict(),
        "opening": opening.as_dict(),
        "return_is_filed": service.window_is_filed(
            db, firm_id, client_id, registration.gstin, window.key),
    })


@router.put("/opening")
def put_opening(
    body: OpeningIn,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """Key the portal's opening balance for one window (replacing any earlier)."""
    assert_client_access(current_user, body.client_id)
    firm_id = current_user["firm_id"]
    db = _db()
    registration, window = _window(db, firm_id, body.client_id, body.period, body.gstin)
    if service.window_is_filed(db, firm_id, body.client_id, registration.gstin, window.key):
        raise HTTPException(
            status_code=409,
            detail=f"The GSTR-3B for {window.key} is already filed with the opening "
                   "balance it was computed with, and a filed return is not revised "
                   "(CGST Act s.39 with s.37). Record the correction as the opening of "
                   "the NEXT return's window instead.")
    try:
        balance = ledger.CreditBalance(body.igst_paise, body.cgst_paise,
                                       body.sgst_paise, body.cess_paise)
    except ledger.CreditLedgerError as e:
        raise HTTPException(status_code=422, detail=str(e))
    note = (body.note or "").strip() or None
    written = service.record_opening(
        db, firm_id=firm_id, client_id=body.client_id, gstin=registration.gstin,
        window_start=window.start, balance=balance, note=note,
        recorded_by=current_user.get("id"))
    log_event(firm_id, "gst_credit_ledger_opening", written.get("id") or "",
              "create" if written.get("created") else "update",
              actor_id=current_user.get("auth_user_id"),
              new_data={"client_id": body.client_id, "gstin": registration.gstin,
                        "window_start": window.start, "note": note,
                        **balance.as_dict()})
    opening = service.opening_for(db, firm_id, body.client_id, registration.gstin, window.start)
    return api_response(True, {"gstin": registration.gstin, "window": window.as_dict(),
                               "opening": opening.as_dict()})


@router.delete("/opening")
def delete_opening(
    client_id: str = Query(...),
    period: str = Query(...),
    gstin: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """Take a keyed balance back, handing the window to the chain (or to 'not
    recorded'). It does NOT mean 'the ledger was nil' — key a nil balance for that."""
    assert_client_access(current_user, client_id)
    firm_id = current_user["firm_id"]
    db = _db()
    registration, window = _window(db, firm_id, client_id, period, gstin)
    if service.window_is_filed(db, firm_id, client_id, registration.gstin, window.key):
        raise HTTPException(
            status_code=409,
            detail=f"The GSTR-3B for {window.key} is already filed with the opening "
                   "balance it was computed with; the figure recorded for it is kept.")
    removed = service.clear_opening(db, firm_id=firm_id, client_id=client_id,
                                    gstin=registration.gstin, window_start=window.start)
    if removed:
        log_event(firm_id, "gst_credit_ledger_opening", "", "delete",
                  actor_id=current_user.get("auth_user_id"),
                  old_data={"client_id": client_id, "gstin": registration.gstin,
                            "window_start": window.start})
    opening = service.opening_for(db, firm_id, client_id, registration.gstin, window.start)
    return api_response(True, {"gstin": registration.gstin, "window": window.as_dict(),
                               "opening": opening.as_dict(), "removed": removed})
