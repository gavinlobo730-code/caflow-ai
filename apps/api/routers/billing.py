"""
Billing (Revenue Operations) router — Amendment v1.1, Batch 3.

Partner/Owner-only (the "billing" RBAC resource exposes fee economics, Guardrail
G1). Thin surface over services/billing_service.py: manage billing schedules,
preview due runs, and generate DRAFT sales invoices in the internal client's
books (reusing the Sales/GST engine). Generation is idempotent / duplicate-safe.

CA-confirm gate: generation produces drafts only. Confirm + post the journal via
the existing POST /api/sales-invoices/{id}/issue (Partner-gated for the internal
client). Collections: record receipts via the existing POST /api/receipts
(updates invoice status automatically). Credit notes: existing /api/credit-notes.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, field_validator

from models.common import api_response
from core.permissions import rbac
from services import billing_service
from services import collections_service

router = APIRouter(prefix="/api/billing", tags=["billing"])


class BillingScheduleIn(BaseModel):
    client_id: str                      # the practice (external) client being billed
    arrangement: str                    # retainer | one_time | package
    cadence: str                        # monthly | quarterly | annual | one_time
    amount_paise: int                   # integer paise
    gst_rate: float = 18.0              # percentage rate
    service_id: Optional[str] = None
    next_run_date: Optional[str] = None  # YYYY-MM-DD; defaults to today
    description: Optional[str] = None
    due_date: Optional[str] = None
    is_active: bool = True

    @field_validator("arrangement")
    @classmethod
    def _arr(cls, v: str) -> str:
        if v not in ("retainer", "one_time", "package"):
            raise ValueError("arrangement must be retainer | one_time | package")
        return v

    @field_validator("cadence")
    @classmethod
    def _cad(cls, v: str) -> str:
        if v not in ("monthly", "quarterly", "annual", "one_time"):
            raise ValueError("cadence must be monthly | quarterly | annual | one_time")
        return v

    @field_validator("amount_paise")
    @classmethod
    def _amt(cls, v: int) -> int:
        if v < 0:
            raise ValueError("amount_paise must be non-negative")
        return v


@router.get("/schedules")
def list_schedules(active_only: bool = Query(False),
                   current_user: dict = Depends(rbac("billing", "read"))):
    return api_response(True, billing_service.list_schedules(current_user["firm_id"], active_only))


@router.post("/schedules")
def create_schedule(body: BillingScheduleIn,
                    current_user: dict = Depends(rbac("billing", "write"))):
    sched = billing_service.create_schedule(
        current_user["firm_id"], body.model_dump(), current_user.get("auth_user_id"))
    return api_response(True, sched)


@router.post("/preview-run")
def preview_run(as_of: Optional[str] = Query(None, description="YYYY-MM-DD; defaults to today"),
                current_user: dict = Depends(rbac("billing", "read"))):
    """Dry run: which schedules are due and what would be generated. No writes."""
    return api_response(True, billing_service.preview_due(current_user["firm_id"], as_of))


@router.post("/schedules/{schedule_id}/generate")
def generate(schedule_id: str = Path(...),
             period: Optional[str] = Query(None),
             current_user: dict = Depends(rbac("billing", "write"))):
    """Idempotently generate a DRAFT invoice for one schedule (CA-confirm pending)."""
    sched = billing_service.get_schedule(current_user["firm_id"], schedule_id)
    if not sched:
        raise HTTPException(status_code=404, detail="Billing schedule not found")
    result = billing_service.generate_for_schedule(current_user["firm_id"], sched, current_user, period)
    return api_response(True, result)


@router.post("/run")
def run(as_of: Optional[str] = Query(None),
        current_user: dict = Depends(rbac("billing", "write"))):
    """Idempotently generate drafts for all due schedules."""
    return api_response(True, billing_service.run_due(current_user["firm_id"], current_user, as_of))


# ── Collections & AR (Batch 4) — Partner-only ───────────────────────────────

@router.get("/ar-aging")
def ar_aging(current_user: dict = Depends(rbac("billing", "read"))):
    """Due-date based AR aging across the firm's fee invoices (internal client)."""
    return api_response(True, collections_service.ar_aging(current_user["firm_id"]))


@router.get("/collections/dashboard")
def collections_dashboard(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("billing", "read")),
):
    """Firm Collections/AR KPIs: total receivable, aging, overdue, TDS receivable,
    collected cash. (DSO/realization are deferred Revenue Intelligence.)"""
    return api_response(True, collections_service.dashboard(current_user["firm_id"], date_from, date_to))


@router.post("/collections/sweep")
def run_overdue_sweep(current_user: dict = Depends(rbac("billing", "write"))):
    """Recompute is_overdue/days_overdue/aging_bucket for open invoices (idempotent)."""
    return api_response(True, collections_service.sweep_overdue(current_user["firm_id"]))


@router.post("/collections/send-reminders")
def send_reminders(current_user: dict = Depends(rbac("billing", "write"))):
    """Send collections reminders for overdue invoices (cadence-gated, idempotent)."""
    return api_response(True, collections_service.send_overdue_reminders(current_user["firm_id"]))
