"""
Recurring purchase bills router (PUR-26).

Thin surface over services/recurring_purchase_bill_service.py — the AP twin of
routers/recurring_invoices.py, and deliberately the same shape: the same verbs
(list / create / get / update / pause / resume / archive / history / preview /
run / run-due), the same RBAC (accounting read/write), the same assignment
guard, and the same `{success, data, error}` envelope.

A template generates DRAFT bills through the EXISTING bill engine. Nothing here
RECEIVES one — receiving is what posts Dr Expense / Dr GST Input / Cr Trade
Payables, withholds the TDS and claims the credit, and that stays a CA's act.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, field_validator

from models.common import api_response
from core.authz import assert_client_access, effective_client_ids, filter_by_client
from core.permissions import rbac
from services import recurring_purchase_bill_service as recurring
from domain.recurrence import preview_occurrences

router = APIRouter(prefix="/api/recurring-purchase-bills", tags=["recurring_purchase_bills"])

_FREQUENCIES = ("weekly", "monthly", "quarterly", "half_yearly", "yearly")


class RecurringBillLineIn(BaseModel):
    # MANDATORY, exactly as PurchaseBillLineIn makes it (migration 206) and for
    # a second reason on top: a template holding a line the bill engine would
    # refuse fails inside an UNATTENDED 06:00 IST job, which is the worst place
    # to discover it. Validated at save time so the CA sees the refusal while
    # they are looking at the form. Same argument recurring_invoice_service
    # makes for its GSTR-1 classification.
    service_catalogue_id: str
    description: str
    hsn_sac: Optional[str] = None
    unit: Optional[str] = None
    quantity: float = 1.0
    rate_paise: int
    gst_rate_percent: float = 18.0
    is_service: bool = False
    # CGST §17(5) — CA-set only, never inferred from the HSN or the expense
    # account (migration 240). Blocked tax is a COST of the supply (PUR-04),
    # and on a goods line it is capitalised into stock (INV-05a), so getting
    # this wrong every month moves both the P&L and the balance sheet.
    itc_eligible: bool = True
    blocked_credit_reason: Optional[str] = None
    tds_applicable: bool = False
    expense_account_id: Optional[str] = None
    # Which stock item this line restocks, if any — the inventory engine reads
    # it at RECEIVE time (domain/inventory_service.apply_purchase_to_inventory).
    service_catalogue_id: Optional[str] = None

    @field_validator("service_catalogue_id")
    @classmethod
    def _service(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Product/Service is required on every line item.")
        return v

    @field_validator("rate_paise")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("rate_paise must be non-negative.")
        return v


class RecurringBillTemplateIn(BaseModel):
    client_id: str
    vendor_id: str
    title: str
    description: Optional[str] = None
    frequency: str
    start_date: str                       # YYYY-MM-DD
    end_date: Optional[str] = None
    notes: Optional[str] = None
    is_inter_state: bool = False
    is_reverse_charge: bool = False
    lines: list[RecurringBillLineIn]

    @field_validator("frequency")
    @classmethod
    def _freq(cls, v: str) -> str:
        if v not in _FREQUENCIES:
            raise ValueError(f"frequency must be one of {_FREQUENCIES}")
        return v

    @field_validator("lines")
    @classmethod
    def _lines(cls, v: list) -> list:
        if not v:
            raise ValueError("A template needs at least one line item.")
        return v


class RecurringBillTemplateUpdateIn(BaseModel):
    vendor_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    frequency: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    notes: Optional[str] = None
    is_inter_state: Optional[bool] = None
    is_reverse_charge: Optional[bool] = None
    lines: Optional[list[RecurringBillLineIn]] = None

    @field_validator("frequency")
    @classmethod
    def _freq(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _FREQUENCIES:
            raise ValueError(f"frequency must be one of {_FREQUENCIES}")
        return v


def _assert_template_scope(current_user: dict, template_id: str) -> Optional[str]:
    """404 unless the caller may act on this template's client.

    404 rather than 403, and the same 404 as "no such template" — otherwise the
    status code becomes an oracle for which template ids are real. Same guard,
    same reasoning, as routers/recurring_invoices._assert_template_scope.
    """
    t = recurring.get_template(current_user["firm_id"], template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Recurring bill template not found.")
    assert_client_access(current_user, t.get("client_id"))
    return t.get("client_id")


def _dump_lines(lines) -> Optional[list[dict]]:
    return [ln.model_dump() for ln in lines] if lines is not None else None


@router.get("")
def list_recurring_bills(client_id: Optional[str] = Query(None),
                         status: Optional[str] = Query(None),
                         current_user: dict = Depends(rbac("accounting", "read"))):
    """List recurring bill templates for the firm (optionally one client)."""
    if client_id:
        assert_client_access(current_user, client_id)
    rows = recurring.list_templates(
        current_user["firm_id"], client_id=client_id, status=status)
    if not client_id:
        rows = filter_by_client(current_user, rows)
    return api_response(True, rows)


@router.post("")
def create_recurring_bill(body: RecurringBillTemplateIn,
                          current_user: dict = Depends(rbac("accounting", "write"))):
    """Create a recurring bill template (drafts only; never auto-receives)."""
    assert_client_access(current_user, body.client_id)
    data = body.model_dump()
    data["lines"] = _dump_lines(body.lines)
    return api_response(True, recurring.create_template(
        current_user["firm_id"], data, current_user.get("id")))


@router.get("/{template_id}")
def get_recurring_bill(template_id: str = Path(...),
                       current_user: dict = Depends(rbac("accounting", "read"))):
    _assert_template_scope(current_user, template_id)
    t = recurring.get_template(current_user["firm_id"], template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Recurring bill template not found.")
    return api_response(True, t)


@router.put("/{template_id}")
def update_recurring_bill(template_id: str, body: RecurringBillTemplateUpdateIn,
                          current_user: dict = Depends(rbac("accounting", "write"))):
    _assert_template_scope(current_user, template_id)
    data = body.model_dump(exclude_unset=True)
    if "lines" in data:
        data["lines"] = _dump_lines(body.lines)
    return api_response(True, recurring.update_template(
        current_user["firm_id"], template_id, data))


@router.post("/{template_id}/pause")
def pause_recurring_bill(template_id: str,
                         current_user: dict = Depends(rbac("accounting", "write"))):
    _assert_template_scope(current_user, template_id)
    return api_response(True, recurring.set_status(
        current_user["firm_id"], template_id, "paused"))


@router.post("/{template_id}/resume")
def resume_recurring_bill(template_id: str,
                          current_user: dict = Depends(rbac("accounting", "write"))):
    _assert_template_scope(current_user, template_id)
    return api_response(True, recurring.set_status(
        current_user["firm_id"], template_id, "active"))


@router.post("/{template_id}/archive")
def archive_recurring_bill(template_id: str,
                           current_user: dict = Depends(rbac("accounting", "write"))):
    _assert_template_scope(current_user, template_id)
    return api_response(True, recurring.set_status(
        current_user["firm_id"], template_id, "archived"))


@router.get("/{template_id}/history")
def history_recurring_bill(template_id: str,
                           current_user: dict = Depends(rbac("accounting", "read"))):
    """Generation history (occurrence -> generated draft bill + status)."""
    _assert_template_scope(current_user, template_id)
    return api_response(True, recurring.template_history(
        current_user["firm_id"], template_id))


@router.get("/{template_id}/preview")
def preview_recurring_bill(template_id: str, count: int = Query(5, ge=1, le=24),
                           current_user: dict = Depends(rbac("accounting", "read"))):
    """The next N occurrence dates for a template (read-only)."""
    _assert_template_scope(current_user, template_id)
    t = recurring.get_template(current_user["firm_id"], template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Recurring bill template not found.")
    return api_response(True, {"occurrences": preview_occurrences(t, count=count)})


@router.post("/{template_id}/run")
def run_one_recurring_bill(template_id: str, as_of: Optional[str] = Query(None),
                           current_user: dict = Depends(rbac("accounting", "write"))):
    """Generate due DRAFT bills for a single template now (CA-initiated)."""
    _assert_template_scope(current_user, template_id)
    return api_response(True, recurring.run_for_template(
        current_user["firm_id"], template_id, as_of=as_of, actor=current_user))


@router.post("/run")
def run_due_recurring_bills(client_id: Optional[str] = Query(None),
                            as_of: Optional[str] = Query(None),
                            current_user: dict = Depends(rbac("accounting", "write"))):
    """Manually run recurring bill generation for the firm (optionally one
    client). The same job the daily scheduler runs — works whether the
    scheduler is on or off.

    A WRITE across every client, so the run is confined to the caller's own
    book rather than the output being filtered afterwards: the drafts would
    already exist. A Partner or Manager is firm-wide (one call, as before); an
    Executive generates only for the clients they are assigned to. Identical to
    routers/recurring_invoices.run_due_recurring and for the same reason.
    """
    if client_id:
        assert_client_access(current_user, client_id)
        targets = [client_id]
    else:
        eff = effective_client_ids(current_user)
        targets = [None] if eff is None else sorted(eff)

    merged: dict = {"generated": [], "skipped": [], "failed": []}
    for target in targets:
        res = recurring.generate_due_recurring_bills(
            current_user["firm_id"], client_id=target, as_of=as_of, actor=current_user)
        for key in merged:
            merged[key].extend(res.get(key) or [])
    merged.update({f"{k}_count": len(v) for k, v in list(merged.items())})
    return api_response(True, merged)
