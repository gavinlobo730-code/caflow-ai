"""A Bill of Entry — the customs assessment on an import of goods (PUR-18).

Thin surface over `services/bill_of_entry_service.py`, which is in turn a fetch
and posting layer over `domain/gst/bill_of_entry.py`. Nothing here decides which
figure is credit and which is cost.

# CA REVIEW REQUIRED — the assessment is confirmed before it is posted.
# Nothing here transmits anything to any portal.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from core.authz import assert_client_access
from core.permissions import rbac
from models.common import api_response
from domain.gst import bill_of_entry as boe
from services import bill_of_entry_service as svc

router = APIRouter(prefix="/api/bills-of-entry", tags=["bills_of_entry"])


class BillOfEntryIn(BaseModel):
    """What customs assessed.

    Every amount is integer paise. The four duty fields and the two tax fields
    are kept apart rather than summed by the caller, because which of them is
    input tax and which is cost is exactly the question this feature exists to
    answer — CGST Act s.2(62)(a) against AS-2 paragraph 6.
    """
    client_id: str
    be_number: str
    be_date: str
    port_code: Optional[str] = None
    vendor_id: Optional[str] = None
    purchase_bill_id: Optional[str] = None
    assessable_value_paise: int = Field(0, ge=0)
    basic_customs_duty_paise: int = Field(0, ge=0)
    social_welfare_surcharge_paise: int = Field(0, ge=0)
    other_duty_paise: int = Field(0, ge=0)
    igst_paise: int = Field(0, ge=0)
    cess_paise: int = Field(0, ge=0)
    ineligible_igst_paise: int = Field(0, ge=0)
    ineligible_cess_paise: int = Field(0, ge=0)
    is_sez: bool = False
    payment_account_id: Optional[str] = None
    duty_expense_account_id: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("be_number")
    @classmethod
    def number_is_a_number(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            raise ValueError("The Bill of Entry number is the customs house's "
                             "own reference and is required.")
        return value

    @field_validator("port_code")
    @classmethod
    def tidy_port(cls, v: Optional[str]) -> Optional[str]:
        value = (v or "").strip().upper()
        return value or None


class BillOfEntryUpdateIn(BaseModel):
    """Every field optional — a PATCH leaves what it omits alone."""
    be_number: Optional[str] = None
    be_date: Optional[str] = None
    port_code: Optional[str] = None
    vendor_id: Optional[str] = None
    purchase_bill_id: Optional[str] = None
    assessable_value_paise: Optional[int] = Field(None, ge=0)
    basic_customs_duty_paise: Optional[int] = Field(None, ge=0)
    social_welfare_surcharge_paise: Optional[int] = Field(None, ge=0)
    other_duty_paise: Optional[int] = Field(None, ge=0)
    igst_paise: Optional[int] = Field(None, ge=0)
    cess_paise: Optional[int] = Field(None, ge=0)
    ineligible_igst_paise: Optional[int] = Field(None, ge=0)
    ineligible_cess_paise: Optional[int] = Field(None, ge=0)
    is_sez: Optional[bool] = None
    payment_account_id: Optional[str] = None
    duty_expense_account_id: Optional[str] = None
    notes: Optional[str] = None


def _mock_enabled() -> bool:
    from core.config import settings as _s
    return bool(getattr(_s, "USE_MOCK_DATA", False))


@router.get("/authorities")
def authorities(current_user: dict = Depends(rbac("accounting", "read"))):
    """What makes the split, and what this document deliberately cannot say.

    Served rather than written on the screen: the two citations are the whole
    of the rule, and a copy in the browser is a second place for them to drift.
    """
    return api_response(True, {
        "credit_authority": boe.CREDIT_AUTHORITY,
        "cost_authority": boe.COST_AUTHORITY,
        "table_4a_row": boe.TABLE_4A_ROW,
        "gstr2b_sections": [boe.SECTION_IMPG, boe.SECTION_IMPGSEZ],
        "not_modelled": list(boe.NOT_MODELLED),
    })


@router.get("")
def list_bills_of_entry(
    client_id: str = Query(...),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, [])
    from core.supabase_client import get_supabase
    return api_response(True, svc.listing(
        get_supabase(), firm_id=current_user.get("firm_id"),
        client_id=client_id, start=date_from, end=date_to))


@router.post("")
def create_bill_of_entry(
    data: BillOfEntryIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    assert_client_access(current_user, data.client_id)
    if data.ineligible_igst_paise > data.igst_paise:
        raise HTTPException(
            status_code=422,
            detail="Blocked credit cannot exceed the integrated tax paid — "
                   "CGST Act s.17(5) bars part of a credit, never more than it.")
    if data.ineligible_cess_paise > data.cess_paise:
        raise HTTPException(
            status_code=422,
            detail="Blocked cess credit cannot exceed the cess paid.")
    if _mock_enabled():
        return api_response(True, {"id": "mock-bill-of-entry", **data.model_dump()})

    from core.supabase_client import get_supabase
    from services.audit_service import log_event
    db = get_supabase()
    # EVERY COLUMN NAMED, rather than `**data.model_dump()`. The spread reads
    # better and is invisible to
    # `tests/test_backend_inserts_supply_every_required_column_pg.py` and to the
    # column scan beside it — and PostgREST rejects the WHOLE write on one
    # column that does not exist, so a name nobody can check is a write nobody
    # notices failing. The same reason the reads in
    # `services/rcm_document_service.py` are spelled out.
    # INLINE rather than through a `payload` variable: `scan` in
    # tests/_backend_query_parser resolves no names, so a write whose argument
    # is a variable is a blind spot to the column check even when the
    # insert-payload scanner beside it can follow it.
    rows = db.table("bills_of_entry").insert({
        "firm_id": current_user.get("firm_id"),
        "client_id": data.client_id,
        "be_number": data.be_number,
        "be_date": data.be_date,
        "port_code": data.port_code,
        "vendor_id": data.vendor_id,
        "purchase_bill_id": data.purchase_bill_id,
        "assessable_value_paise": data.assessable_value_paise,
        "basic_customs_duty_paise": data.basic_customs_duty_paise,
        "social_welfare_surcharge_paise": data.social_welfare_surcharge_paise,
        "other_duty_paise": data.other_duty_paise,
        "igst_paise": data.igst_paise,
        "cess_paise": data.cess_paise,
        "ineligible_igst_paise": data.ineligible_igst_paise,
        "ineligible_cess_paise": data.ineligible_cess_paise,
        "is_sez": data.is_sez,
        "payment_account_id": data.payment_account_id,
        "duty_expense_account_id": data.duty_expense_account_id,
        "notes": data.notes,
        "created_by": current_user.get("id"),
    }).execute().data or []
    row = rows[0] if rows else {}
    # The ROW as written, not the payload as sent — the two differ by every
    # defaulted column, and the audit log wants what is on the record.
    log_event(current_user.get("firm_id") or "", "bill_of_entry",
              row.get("id") or "", "create",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=row)
    return api_response(True, row)


@router.patch("/{be_id}")
def update_bill_of_entry(
    be_id: str,
    data: BillOfEntryUpdateIn,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Correct a Bill of Entry that has not been posted.

    A POSTED one is refused: its journal is on the ledger and a posted entry
    cannot be rewritten in place (migration 251). The correction is a reversal.
    """
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, {"id": be_id, **data.model_dump(exclude_none=True)})
    from core.supabase_client import get_supabase
    db = get_supabase()
    row = svc.get(db, current_user.get("firm_id"), be_id)
    if row.get("status") == "posted":
        raise HTTPException(
            status_code=409,
            detail="This Bill of Entry is posted. Its journal is on the ledger "
                   "and a posted entry cannot be rewritten — reverse it instead.")
    # Named, for the same reason the insert above is. A None means "leave it
    # alone", which is what every field on the update model means.
    patch = {k: v for k, v in {
        "be_number": data.be_number,
        "be_date": data.be_date,
        "port_code": data.port_code,
        "vendor_id": data.vendor_id,
        "purchase_bill_id": data.purchase_bill_id,
        "assessable_value_paise": data.assessable_value_paise,
        "basic_customs_duty_paise": data.basic_customs_duty_paise,
        "social_welfare_surcharge_paise": data.social_welfare_surcharge_paise,
        "other_duty_paise": data.other_duty_paise,
        "igst_paise": data.igst_paise,
        "cess_paise": data.cess_paise,
        "ineligible_igst_paise": data.ineligible_igst_paise,
        "ineligible_cess_paise": data.ineligible_cess_paise,
        "is_sez": data.is_sez,
        "payment_account_id": data.payment_account_id,
        "duty_expense_account_id": data.duty_expense_account_id,
        "notes": data.notes,
    }.items() if v is not None}
    if not patch:
        return api_response(True, row)

    # WRITTEN AS A MERGE, not as the patch alone. A `.update(patch)` hides the
    # column names from the scan above; a literal dict of `patch.get(k)` would
    # send NULL for every field the CA did not touch and wipe them. `_merged`
    # falls back to what the row already holds, so every column is named AND
    # nothing is cleared by omission.
    def _merged(key: str):
        return patch[key] if key in patch else row.get(key)

    updated = (db.table("bills_of_entry")
               .update({
                   "be_number": _merged("be_number"),
                   "be_date": _merged("be_date"),
                   "port_code": _merged("port_code"),
                   "vendor_id": _merged("vendor_id"),
                   "purchase_bill_id": _merged("purchase_bill_id"),
                   "assessable_value_paise": _merged("assessable_value_paise"),
                   "basic_customs_duty_paise": _merged("basic_customs_duty_paise"),
                   "social_welfare_surcharge_paise": _merged("social_welfare_surcharge_paise"),
                   "other_duty_paise": _merged("other_duty_paise"),
                   "igst_paise": _merged("igst_paise"),
                   "cess_paise": _merged("cess_paise"),
                   "ineligible_igst_paise": _merged("ineligible_igst_paise"),
                   "ineligible_cess_paise": _merged("ineligible_cess_paise"),
                   "is_sez": _merged("is_sez"),
                   "payment_account_id": _merged("payment_account_id"),
                   "duty_expense_account_id": _merged("duty_expense_account_id"),
                   "notes": _merged("notes"),
               })
               .eq("id", be_id).eq("firm_id", current_user.get("firm_id"))
               .execute().data) or []
    return api_response(True, updated[0] if updated else row)


@router.post("/{be_id}/post")
def post_bill_of_entry(
    be_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Post the assessment to the ledger.

    # CA REVIEW REQUIRED — the CA confirms the figures first.
    """
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, {"id": be_id, "status": "posted"})
    from core.supabase_client import get_supabase
    from services.audit_service import log_event
    row = svc.post(get_supabase(), current_user.get("firm_id"), be_id,
                   actor_id=current_user.get("id"))
    log_event(current_user.get("firm_id") or "", "bill_of_entry", be_id, "post",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"),
              new_data={"journal_entry_id": row.get("journal_entry_id")})
    return api_response(True, row)


@router.delete("/{be_id}")
def delete_bill_of_entry(
    be_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Withdraw a Bill of Entry entered in error. Soft delete, and refused once
    posted — the ledger entry behind it is immutable."""
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, {"id": be_id, "deleted": True})
    from core.supabase_client import get_supabase
    from services.audit_service import log_event
    db = get_supabase()
    row = svc.get(db, current_user.get("firm_id"), be_id)
    if row.get("status") == "posted":
        raise HTTPException(
            status_code=409,
            detail="This Bill of Entry is posted. Reverse its journal first — "
                   "deleting it would leave a credit on the return with nothing "
                   "in the ledger behind it.")
    from datetime import datetime, timezone
    db.table("bills_of_entry").update(
        {"deleted_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", be_id).eq("firm_id", current_user.get("firm_id")).execute()
    log_event(current_user.get("firm_id") or "", "bill_of_entry", be_id, "delete",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), old_data=row)
    return api_response(True, {"id": be_id, "deleted": True})
