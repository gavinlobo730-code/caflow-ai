"""GSTR-9C — the audited-books reconciliation statement (GST-25, part 4).

Same tier split as `routers/ecommerce_operator.py` and `routers/gstr4_annual.py`:
WRITES are `gst.compute` (there is no `gst.write` action), READS are
`gst.read`. Nothing here transmits anything to any portal;
`services.gstr9c_service.gstr9c_statement` is the only reader that turns
these rows into a statement.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.authz import assert_client_access
from core.permissions import rbac
from models.common import api_response
from models.fy import FYLabel

router = APIRouter(prefix="/api/gstr9c", tags=["gstr9c"])


def _mock_enabled() -> bool:
    from core.config import settings as _s
    return bool(getattr(_s, "USE_MOCK_DATA", False))


def _resolve(db, firm_id, client_id, gstin):
    from services import client_gst_registration_service as regs
    return regs.resolve(db, firm_id, client_id, gstin)


class ReconciliationIn(BaseModel):
    """Table 5/7/12/16's CA-recorded figures for one financial year."""
    client_id: str
    gstin: Optional[str] = None
    financial_year: FYLabel
    act_name: Optional[str] = None
    # Table 5
    turnover_per_audited_fs_paise: Optional[int] = None
    unbilled_revenue_begin_paise: Optional[int] = None
    unadjusted_advances_end_paise: Optional[int] = None
    deemed_supply_paise: Optional[int] = None
    credit_notes_issued_post_fy_paise: Optional[int] = None
    trade_discount_not_permissible_paise: Optional[int] = None
    unbilled_revenue_end_paise: Optional[int] = None
    unadjusted_advances_begin_paise: Optional[int] = None
    credit_notes_in_fs_not_permissible_paise: Optional[int] = None
    sez_dta_adjustment_paise: Optional[int] = None
    composition_period_turnover_paise: Optional[int] = None
    section_15_adjustment_paise: Optional[int] = None
    forex_adjustment_paise: Optional[int] = None
    other_turnover_adjustment_paise: Optional[int] = None
    turnover_after_adjustments_paise: Optional[int] = None
    turnover_reasons: list[str] = []
    # Table 7
    exempt_nil_nongst_turnover_paise: Optional[int] = None
    zero_rated_no_tax_turnover_paise: Optional[int] = None
    reverse_charge_turnover_paise: Optional[int] = None
    ecommerce_9_5_turnover_paise: Optional[int] = None
    taxable_turnover_after_adjustments_paise: Optional[int] = None
    taxable_turnover_reasons: list[str] = []
    # Table 12
    itc_per_audited_fs_paise: Optional[int] = None
    itc_booked_earlier_fy_claimed_this_fy_paise: Optional[int] = None
    itc_booked_this_fy_claimed_later_fy_paise: Optional[int] = None
    itc_reasons: list[str] = []
    # Table 16
    unreconciled_itc_tax_igst_paise: Optional[int] = None
    unreconciled_itc_tax_cgst_paise: Optional[int] = None
    unreconciled_itc_tax_sgst_paise: Optional[int] = None
    unreconciled_itc_tax_cess_paise: Optional[int] = None
    unreconciled_itc_interest_paise: Optional[int] = None
    unreconciled_itc_penalty_paise: Optional[int] = None
    itc_reasons_16: list[str] = []
    notes: Optional[str] = None


class RateWiseLineIn(BaseModel):
    """One row of Table 9, Table 11 or Part V's rate-wise array."""
    client_id: str
    reconciliation_id: str
    table_ref: str   # "9" | "11" | "partv"
    rate_description: str
    taxable_value_paise: int = 0
    igst_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    cess_paise: int = 0
    line_order: int = 0


class ExpenseLineIn(BaseModel):
    """One row of Table 14's expense-head array."""
    client_id: str
    reconciliation_id: str
    expense_head: str
    value_paise: int = 0
    total_itc_paise: int = 0
    eligible_itc_availed_paise: int = 0
    line_order: int = 0


@router.get("/reconciliation")
def get_reconciliation(
    client_id: str = Query(...),
    financial_year: Annotated[FYLabel, Query(...)] = ...,
    gstin: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("gst", "read")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, None)
    from core.supabase_client import get_supabase
    from services import gstr9c_service as svc
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    registration = _resolve(db, firm_id, client_id, gstin)
    return api_response(True, svc.get_reconciliation(
        db, firm_id, client_id, registration.gstin, financial_year))


@router.post("/reconciliation")
def save_reconciliation(
    data: ReconciliationIn,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, data.client_id)
    if _mock_enabled():
        return api_response(True, {"id": "mock-gstr9c-reconciliation", **data.model_dump()})
    from core.supabase_client import get_supabase
    from services import gstr9c_service as svc
    from services.audit_service import log_event
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    registration = _resolve(db, firm_id, data.client_id, data.gstin)
    row = svc.save_reconciliation(
        db, firm_id, data.client_id, gstin=registration.gstin,
        financial_year=data.financial_year, actor_id=current_user.get("id"),
        **data.model_dump(exclude={"client_id", "gstin", "financial_year"}))
    log_event(firm_id or "", "gstr9c_reconciliation", row.get("id") or "",
              "record", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=row)
    return api_response(True, row)


@router.get("/rate-wise-lines")
def list_rate_wise_lines(
    client_id: str = Query(...),
    reconciliation_id: str = Query(...),
    table_ref: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("gst", "read")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, [])
    from core.supabase_client import get_supabase
    from services import gstr9c_service as svc
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    return api_response(True, svc.list_rate_wise_lines(
        db, firm_id, reconciliation_id, table_ref))


@router.post("/rate-wise-lines")
def add_rate_wise_line(
    data: RateWiseLineIn,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, data.client_id)
    if data.table_ref not in ("9", "11", "partv"):
        raise HTTPException(status_code=422, detail=(
            "table_ref must be one of '9', '11' or 'partv'."))
    if _mock_enabled():
        return api_response(True, {"id": "mock-rate-wise-line", **data.model_dump()})
    from core.supabase_client import get_supabase
    from services import gstr9c_service as svc
    from services.audit_service import log_event
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    row = svc.add_rate_wise_line(
        db, firm_id, data.client_id, data.reconciliation_id,
        table_ref=data.table_ref, rate_description=data.rate_description,
        taxable_value_paise=data.taxable_value_paise, igst_paise=data.igst_paise,
        cgst_paise=data.cgst_paise, sgst_paise=data.sgst_paise,
        cess_paise=data.cess_paise, line_order=data.line_order,
        actor_id=current_user.get("id"))
    log_event(firm_id or "", "gstr9c_rate_wise_line", row.get("id") or "",
              "record", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=row)
    return api_response(True, row)


@router.delete("/rate-wise-lines/{line_id}")
def delete_rate_wise_line(
    line_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, {"id": line_id, "deleted": True})
    from core.supabase_client import get_supabase
    from services import gstr9c_service as svc
    from services.audit_service import log_event
    row = svc.delete_rate_wise_line(get_supabase(), current_user.get("firm_id"), line_id)
    log_event(current_user.get("firm_id") or "", "gstr9c_rate_wise_line",
              line_id, "delete", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), old_data=row)
    return api_response(True, {"id": line_id, "deleted": True})


@router.get("/expense-lines")
def list_expense_lines(
    client_id: str = Query(...),
    reconciliation_id: str = Query(...),
    current_user: dict = Depends(rbac("gst", "read")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, [])
    from core.supabase_client import get_supabase
    from services import gstr9c_service as svc
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    return api_response(True, svc.list_expense_lines(db, firm_id, reconciliation_id))


@router.post("/expense-lines")
def add_expense_line(
    data: ExpenseLineIn,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, data.client_id)
    if _mock_enabled():
        return api_response(True, {"id": "mock-expense-line", **data.model_dump()})
    from core.supabase_client import get_supabase
    from services import gstr9c_service as svc
    from services.audit_service import log_event
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    row = svc.add_expense_line(
        db, firm_id, data.client_id, data.reconciliation_id,
        expense_head=data.expense_head, value_paise=data.value_paise,
        total_itc_paise=data.total_itc_paise,
        eligible_itc_availed_paise=data.eligible_itc_availed_paise,
        line_order=data.line_order, actor_id=current_user.get("id"))
    log_event(firm_id or "", "gstr9c_expense_line", row.get("id") or "",
              "record", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=row)
    return api_response(True, row)


@router.delete("/expense-lines/{line_id}")
def delete_expense_line(
    line_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, {"id": line_id, "deleted": True})
    from core.supabase_client import get_supabase
    from services import gstr9c_service as svc
    from services.audit_service import log_event
    row = svc.delete_expense_line(get_supabase(), current_user.get("firm_id"), line_id)
    log_event(current_user.get("firm_id") or "", "gstr9c_expense_line",
              line_id, "delete", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), old_data=row)
    return api_response(True, {"id": line_id, "deleted": True})
