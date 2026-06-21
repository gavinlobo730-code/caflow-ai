"""
Recurring Invoices router (Phase 4.3).

Thin surface over services/recurring_invoice_service.py. Recurring templates
generate DRAFT sales invoices through the EXISTING invoice engine — never
auto-issue, auto-post, or auto-email (locked decisions 1 & 6). RBAC mirrors the
sales-invoice engine (accounting read/write); responses follow the standard
{success, data, error} envelope. Kept separate from /api/billing (practice fees).
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, field_validator

from models.common import api_response
from core.permissions import rbac
from services import recurring_invoice_service as recurring

router = APIRouter(prefix="/api/recurring-invoices", tags=["recurring_invoices"])

_FREQUENCIES = ("weekly", "monthly", "quarterly", "half_yearly", "yearly")


class RecurringLineIn(BaseModel):
    description: str
    hsn_sac: Optional[str] = None
    quantity: float = 1.0
    rate_paise: int
    gst_rate_percent: float = 18.0
    is_service: bool = False

    @field_validator("rate_paise")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("rate_paise must be non-negative.")
        return v


class RecurringTemplateIn(BaseModel):
    client_id: str
    customer_id: str
    title: str
    description: Optional[str] = None
    frequency: str
    start_date: str                       # YYYY-MM-DD
    end_date: Optional[str] = None
    notes: Optional[str] = None
    is_inter_state: bool = False
    lines: list[RecurringLineIn]

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


class RecurringTemplateUpdateIn(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    frequency: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    notes: Optional[str] = None
    is_inter_state: Optional[bool] = None
    lines: Optional[list[RecurringLineIn]] = None

    @field_validator("frequency")
    @classmethod
    def _freq(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _FREQUENCIES:
            raise ValueError(f"frequency must be one of {_FREQUENCIES}")
        return v


def _dump_lines(lines) -> list[dict]:
    return [ln.model_dump() for ln in lines] if lines is not None else None


@router.get("")
def list_recurring(client_id: Optional[str] = Query(None),
                   status: Optional[str] = Query(None),
                   current_user: dict = Depends(rbac("accounting", "read"))):
    """List recurring templates for the firm (optionally scoped to one client)."""
    return api_response(True, recurring.list_templates(
        current_user["firm_id"], client_id=client_id, status=status))


@router.post("")
def create_recurring(body: RecurringTemplateIn,
                     current_user: dict = Depends(rbac("accounting", "write"))):
    """Create a recurring invoice template (drafts only; never auto-sends)."""
    data = body.model_dump()
    data["lines"] = _dump_lines(body.lines)
    return api_response(True, recurring.create_template(
        current_user["firm_id"], data, current_user.get("auth_user_id")))


@router.get("/{template_id}")
def get_recurring(template_id: str = Path(...),
                  current_user: dict = Depends(rbac("accounting", "read"))):
    t = recurring.get_template(current_user["firm_id"], template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Recurring template not found.")
    return api_response(True, t)


@router.put("/{template_id}")
def update_recurring(template_id: str, body: RecurringTemplateUpdateIn,
                     current_user: dict = Depends(rbac("accounting", "write"))):
    data = body.model_dump(exclude_unset=True)
    if "lines" in data:
        data["lines"] = _dump_lines(body.lines)
    return api_response(True, recurring.update_template(current_user["firm_id"], template_id, data))


@router.post("/{template_id}/pause")
def pause_recurring(template_id: str,
                    current_user: dict = Depends(rbac("accounting", "write"))):
    return api_response(True, recurring.set_status(current_user["firm_id"], template_id, "paused"))


@router.post("/{template_id}/resume")
def resume_recurring(template_id: str,
                     current_user: dict = Depends(rbac("accounting", "write"))):
    return api_response(True, recurring.set_status(current_user["firm_id"], template_id, "active"))


@router.post("/{template_id}/archive")
def archive_recurring(template_id: str,
                      current_user: dict = Depends(rbac("accounting", "write"))):
    return api_response(True, recurring.set_status(current_user["firm_id"], template_id, "archived"))


@router.get("/{template_id}/history")
def history_recurring(template_id: str,
                      current_user: dict = Depends(rbac("accounting", "read"))):
    """Generation history (occurrence -> generated draft invoice + status)."""
    return api_response(True, recurring.template_history(current_user["firm_id"], template_id))


@router.get("/{template_id}/preview")
def preview_recurring(template_id: str, count: int = Query(5, ge=1, le=24),
                      current_user: dict = Depends(rbac("accounting", "read"))):
    """The next N occurrence dates for a template (read-only)."""
    t = recurring.get_template(current_user["firm_id"], template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Recurring template not found.")
    return api_response(True, {"occurrences": recurring.preview_occurrences(t, count=count)})


@router.post("/{template_id}/run")
def run_one_recurring(template_id: str, as_of: Optional[str] = Query(None),
                      current_user: dict = Depends(rbac("accounting", "write"))):
    """Generate due DRAFT invoices for a single template now (CA-initiated)."""
    return api_response(True, recurring.run_for_template(
        current_user["firm_id"], template_id, as_of=as_of, actor=current_user))


@router.post("/run")
def run_due_recurring(client_id: Optional[str] = Query(None), as_of: Optional[str] = Query(None),
                      current_user: dict = Depends(rbac("accounting", "write"))):
    """Manually run recurring generation for the firm (optionally one client).
    Same job the daily scheduler runs — works whether the scheduler is on or off."""
    return api_response(True, recurring.generate_due_recurring_invoices(
        current_user["firm_id"], client_id=client_id, as_of=as_of, actor=current_user))
