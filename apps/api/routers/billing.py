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
from core.authz import assert_client_access, can_access_client, filter_by_client
from core.permissions import rbac
from services import billing_service
from services import collections_service
from services import fee_billing_service
from repositories.invoice_repository import invoice_repo

router = APIRouter(prefix="/api/billing", tags=["billing"])


def _assert_invoice_scope(current_user: dict, invoice_id: str) -> dict:
    """Resolve a fee_invoices row and 404 unless the caller may access its
    client. fee_invoices.client_id is NOT NULL (migration 014) — every
    invoice belongs to exactly one client. invoice_repo.find_by_id() does not
    itself filter by firm, so the firm check below is load-bearing, not
    redundant with it.

    Uses can_access_client (boolean) rather than assert_client_access so a
    hidden invoice and a missing one raise the IDENTICAL detail text — the
    generic "Not found" assert_client_access raises would otherwise let the
    message itself distinguish "wrong client" from "no such invoice"."""
    invoice = invoice_repo.find_by_id(invoice_id)
    if (not invoice or invoice.get("firm_id") != current_user.get("firm_id")
            or not can_access_client(current_user, invoice.get("client_id"))):
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found.")
    return invoice


class BillingScheduleIn(BaseModel):
    client_id: str                      # the practice (external) client being billed
    arrangement: str                    # retainer | one_time | package
    cadence: str                        # monthly | quarterly | annual | one_time
    amount_paise: int                   # integer paise
    gst_rate: float = 18.0              # percentage rate
    service_id: str                     # -> service_catalogue; mandatory (migration 206)
    next_run_date: Optional[str] = None  # YYYY-MM-DD; defaults to today
    description: Optional[str] = None
    due_date: Optional[str] = None
    is_active: bool = True

    @field_validator("service_id")
    @classmethod
    def _service(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Product/Service is required.")
        return v

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
    schedules = billing_service.list_schedules(current_user["firm_id"], active_only)
    # M2 audit finding: firm-scoped only. A no-op today — every endpoint on
    # this router requires Partner (PERMISSIONS["billing"] in
    # core/permissions.py), the sole firm-wide role (core/authz.py
    # _FIRMWIDE_ROLES) — but kept explicit so this still holds if "billing"
    # is ever opened to Manager/Executive.
    return api_response(True, filter_by_client(current_user, schedules))


@router.post("/schedules")
def create_schedule(body: BillingScheduleIn,
                    current_user: dict = Depends(rbac("billing", "write"))):
    # task #230 audit finding: client_id is caller-supplied and was never
    # checked against the caller's firm — a schedule created against another
    # firm's client_id would later (on /generate or /run) read that OTHER
    # firm's real client PAN/GSTIN unscoped (services/billing_service.py's
    # ensure_customer_link) and persist it into a customer row in THIS firm's
    # own books. Mirrors routers/engagements.py's identical body.client_id guard.
    assert_client_access(current_user, body.client_id)
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
    # M2 audit finding: get_schedule() already firm-scopes its query, but
    # nothing asserted the client-scope invariant explicitly at the router —
    # the same "guards the body, not the record" gap this sweep has found in
    # every prior router. Same reasoning as create_schedule's guard above.
    assert_client_access(current_user, sched.get("client_id"))
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


# ── Phase 4.2 — Customer payment reminders (collections only) ────────────────
# Emails the CUSTOMER an overdue-payment reminder (with the invoice PDF) and
# records it in invoice_deliveries (kind='reminder'). Purely informational:
# NO journal, NO statement, NO GST/cash-flow impact. Works whether the
# scheduler is enabled or disabled (this manual run is always available).

class ReminderSettingsIn(BaseModel):
    enabled: Optional[bool] = None
    interval_days: Optional[int] = None
    max_reminders: Optional[int] = None
    attach_pdf: Optional[bool] = None

    @field_validator("interval_days")
    @classmethod
    def _interval(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError("interval_days must be at least 1")
        return v

    @field_validator("max_reminders")
    @classmethod
    def _maxr(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("max_reminders must be non-negative")
        return v


@router.post("/collections/run-customer-reminders")
def run_customer_reminders(client_id: Optional[str] = Query(None),
                           current_user: dict = Depends(rbac("billing", "write"))):
    """Run the automatic reminder cadence (7/14/21 days, capped) for the firm's
    customers. client_id optional → restrict to one client. Manual trigger of the
    same job the scheduler runs daily; idempotent via the anti-spam window."""
    # M2 audit finding: client_id is caller-supplied. services/
    # collections_service.py's _open_invoices() already ANDs it with firm_id
    # (a foreign id just yields zero rows — no leak), but a silent empty
    # result is not the same as an explicit refusal. Mirrors create_schedule's
    # guard; a no-op when client_id is None.
    assert_client_access(current_user, client_id)
    return api_response(True, collections_service.run_due_reminders(current_user["firm_id"], client_id))


@router.get("/collections/reminder-settings")
def get_reminder_settings(current_user: dict = Depends(rbac("billing", "read"))):
    """Per-firm reminder policy (cadence / cap / attach-PDF). Returns defaults if unset."""
    return api_response(True, collections_service.reminder_settings(current_user["firm_id"]))


@router.put("/collections/reminder-settings")
def put_reminder_settings(body: ReminderSettingsIn,
                          current_user: dict = Depends(rbac("billing", "write"))):
    """Update the per-firm reminder policy."""
    return api_response(True, collections_service.update_reminder_settings(
        current_user["firm_id"], body.model_dump(exclude_none=True)))


# ── Batch 5: billable / cost-rate capture + unbilled-work visibility (Partner-only) ─

class StaffCostRateIn(BaseModel):
    cost_rate_paise: Optional[int] = None   # integer paise; None clears


@router.get("/unbilled-work")
def unbilled_work(client_id: Optional[str] = Query(None),
                  current_user: dict = Depends(rbac("billing", "read"))):
    """Unbilled (billable, not-yet-billed) work grouped by client/work item with
    billable value. Capture/visibility only — no realization/margin/profitability."""
    # M2 audit finding: same shape as run_customer_reminders above —
    # client_id is caller-supplied and only ANDed into the query.
    assert_client_access(current_user, client_id)
    return api_response(True, billing_service.unbilled_work(current_user["firm_id"], client_id))


@router.get("/staff-cost-rates")
def list_staff_cost_rates(current_user: dict = Depends(rbac("billing", "read"))):
    """Staff cost rates (Partner-only, capture/display only)."""
    return api_response(True, billing_service.list_staff_cost_rates(current_user["firm_id"]))


@router.put("/staff-cost-rates/{user_id}")
def set_staff_cost_rate(user_id: str, body: StaffCostRateIn,
                        current_user: dict = Depends(rbac("billing", "write"))):
    """Capture a staff member's cost rate (integer paise)."""
    return api_response(True, billing_service.set_staff_cost_rate(
        current_user["firm_id"], user_id, body.cost_rate_paise))


# ── Fee Billing receipts (R3.9b) ─────────────────────────────────────────────
# fee_invoices/fee_receipts are a separate "Fee Billing" system (apps/web/app/
# billing/page.tsx) from the internal-customer billing_schedules/
# client_sales_invoices system above — see migration 172's header comment.
# This endpoint fixes that system's partial-payment bug in place rather than
# migrating it onto the other engine (a bigger, separate product decision).

class FeeReceiptIn(BaseModel):
    receipt_date: Optional[str] = None  # YYYY-MM-DD; defaults to today
    amount_paise: int
    payment_mode: str = "NEFT"
    reference_no: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("amount_paise")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("amount_paise must be positive")
        return v

    @field_validator("payment_mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        allowed = {"NEFT", "RTGS", "IMPS", "UPI", "Cheque", "Cash"}
        if v not in allowed:
            raise ValueError(f"payment_mode must be one of {sorted(allowed)}")
        return v


@router.post("/fee-invoices/{invoice_id}/receipts")
def record_fee_receipt(invoice_id: str, body: FeeReceiptIn,
                       current_user: dict = Depends(rbac("billing", "write"))):
    """Record a receipt against a fee_invoices row. Only marks the invoice Paid
    once cumulative receipts (paid_paise) cover its total — a partial receipt
    no longer force-marks the whole invoice as paid."""
    # M2 audit finding: this only reached fee_billing_service.record_receipt,
    # whose own check is firm_id-only (see _assert_invoice_scope's docstring —
    # invoice_repo.find_by_id() doesn't filter by firm at all). fee_invoices.client_id
    # is NOT NULL, so the row is always traceable to a client — nothing checked it.
    _assert_invoice_scope(current_user, invoice_id)
    try:
        result = fee_billing_service.record_receipt(
            current_user["firm_id"], invoice_id, body.model_dump()
        )
        return api_response(True, result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
