"""The post-dated cheque register (accounting-21).

THIN, BY DESIGN. The rule is `domain/banking/pdc.py` and the fetching, the
writing and the conversion are `services/post_dated_cheque_service.py`; this
module decides only who may ask and what shape the request has. Read the domain
header first: a post-dated cheque is a MEMORANDUM, the register posts NOTHING,
and conversion is an ordinary receipt or vendor payment through the one engine
for each — never a second posting path.

`client_id` IS REQUIRED on every route: a cheque belongs to one client's books,
and the register is that client's worklist.

NOTHING HERE SENDS ANYTHING, PRINTS A CHEQUE OR TALKS TO A BANK. Cheque printing
needs a per-bank layout nobody here holds and is a later add-on.
"""
from __future__ import annotations

import logging
import os
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from core.authz import assert_client_access
from core.permissions import rbac
from models.common import api_response
from services import post_dated_cheque_service as service

_logger = logging.getLogger("caflow.post_dated_cheques")

router = APIRouter(prefix="/api/post-dated-cheques", tags=["accounting"])


def _db():
    """The privileged client, or a 503 with no database. Every route is rbac()-
    gated and checks the client scope first; the service carries `firm_id` and
    `client_id` on every read and write. The register's writes are
    service-role-only by grant (migration 460), so this is the client they need."""
    if not os.environ.get("SUPABASE_URL"):
        raise HTTPException(
            status_code=503,
            detail="The cheque register is kept in the database and is unavailable without it.")
    from core.supabase_client import get_service_supabase
    return get_service_supabase()


def _a_date(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    try:
        date.fromisoformat(v)
    except ValueError:
        raise ValueError("Dates are written YYYY-MM-DD.")
    return v


class AllocationIn(BaseModel):
    """One document the cheque is meant for, in the engine's own shape: an
    invoice for a cheque received, a bill for one issued."""

    sales_invoice_id: Optional[str] = None
    purchase_bill_id: Optional[str] = None
    allocated_paise: int


def _allocations(items: Optional[list[AllocationIn]]) -> list[dict]:
    return [a.model_dump(exclude_none=True) for a in (items or [])]


class PostDatedChequeIn(BaseModel):
    client_id: str
    direction: Literal["received", "issued"]
    customer_id: Optional[str] = None
    vendor_id: Optional[str] = None
    cheque_no: str
    cheque_date: str
    amount_paise: int = Field(gt=0)
    drawee_bank: Optional[str] = None
    bank_account_id: Optional[str] = None
    allocations: list[AllocationIn] = []
    notes: Optional[str] = None

    @field_validator("cheque_date")
    @classmethod
    def _cheque_date_is_a_date(cls, v):
        return _a_date(v)


class PostDatedChequePatchIn(BaseModel):
    """Only what is sent changes. The direction and the party are NOT editable: a
    cheque recorded against the wrong party is cancelled and entered again."""

    client_id: str
    cheque_no: Optional[str] = None
    cheque_date: Optional[str] = None
    amount_paise: Optional[int] = Field(default=None, gt=0)
    drawee_bank: Optional[str] = None
    bank_account_id: Optional[str] = None
    allocations: Optional[list[AllocationIn]] = None
    notes: Optional[str] = None

    @field_validator("cheque_date")
    @classmethod
    def _cheque_date_is_a_date(cls, v):
        return _a_date(v)


class ConvertIn(BaseModel):
    client_id: str
    #: The day the cheque was presented. Defaults to today (IST) and may not be
    #: before the cheque's own date or in the future.
    presented_on: Optional[str] = None

    @field_validator("presented_on")
    @classmethod
    def _presented_on_is_a_date(cls, v):
        return _a_date(v)


class CancelIn(BaseModel):
    client_id: str
    reason: Optional[str] = None


@router.get("")
def list_register(
    client_id: str = Query(...),
    direction: Optional[Literal["received", "issued"]] = Query(None),
    include_finished: bool = Query(False),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """The register as a worklist: due cheques first, then what is still to come,
    with the party's name and the derived state. Held cheques only unless
    `include_finished` asks for converted and cancelled ones too."""
    assert_client_access(current_user, client_id)
    db = _db()
    return api_response(True, service.list_register(
        db, current_user["firm_id"], client_id, direction=direction,
        include_finished=include_finished))


@router.get("/options")
def form_options(
    client_id: str = Query(...),
    direction: Literal["received", "issued"] = Query(...),
    party_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """What the 'record a cheque' form picks from: the client's active parties, its
    bank accounts and, once a party is chosen, that party's open documents with
    what each still owes."""
    assert_client_access(current_user, client_id)
    db = _db()
    return api_response(True, service.options(
        db, current_user["firm_id"], client_id, direction, party_id))


@router.post("")
def record_cheque(
    body: PostDatedChequeIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Record a cheque. Posts nothing: the books are unchanged."""
    assert_client_access(current_user, body.client_id)
    db = _db()
    return api_response(True, service.create(
        db, current_user["firm_id"], body.client_id, direction=body.direction,
        customer_id=body.customer_id, vendor_id=body.vendor_id, cheque_no=body.cheque_no,
        cheque_date=body.cheque_date, amount_paise=body.amount_paise,
        drawee_bank=body.drawee_bank, bank_account_id=body.bank_account_id,
        allocations=_allocations(body.allocations), notes=body.notes, actor=current_user))


@router.patch("/{cheque_id}")
def edit_cheque(
    cheque_id: str,
    body: PostDatedChequePatchIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Correct a cheque that is still held."""
    assert_client_access(current_user, body.client_id)
    db = _db()
    changes = body.model_dump(exclude_unset=True)
    changes.pop("client_id", None)
    if "allocations" in changes:
        changes["allocations"] = _allocations(body.allocations)
    return api_response(True, service.update(
        db, current_user["firm_id"], body.client_id, cheque_id, changes, actor=current_user))


@router.post("/{cheque_id}/convert")
def convert_cheque(
    cheque_id: str,
    body: ConvertIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Turn a DUE cheque into an ordinary receipt (received) or vendor payment
    (issued). This is the one act on the register that reaches the books, and it
    does so through `create_receipt_core` / `create_payment_core` — the same two
    engines every other settlement goes through."""
    assert_client_access(current_user, body.client_id)
    db = _db()
    # The engines get the REQUEST-scoped client (the caller's own, under RLS when
    # per-user JWTs are on), as the Receipts screen and the bank match queue give
    # them; only the register's own table needs the privileged one.
    from core.supabase_client import get_supabase
    return api_response(True, service.convert(
        db, current_user["firm_id"], body.client_id, cheque_id,
        presented_on=body.presented_on, actor=current_user, engine_db=get_supabase()))


@router.post("/{cheque_id}/cancel")
def cancel_cheque(
    cheque_id: str,
    body: CancelIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Cancel a cheque that is still held. Posts nothing: nothing was posted."""
    assert_client_access(current_user, body.client_id)
    db = _db()
    return api_response(True, service.cancel(
        db, current_user["firm_id"], body.client_id, cheque_id, body.reason,
        actor=current_user))
