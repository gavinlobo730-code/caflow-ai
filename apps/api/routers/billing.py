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


class BillingScheduleUpdateIn(BaseModel):
    """A partial update to a schedule. Every field optional; omitted means
    unchanged.

    `client_id` is deliberately absent. Moving a schedule to another client
    would re-point every invoice already generated against it, and
    `_find_generated`'s idempotency key is (schedule, period), so the new
    client's first period would read as already billed. Raise a new schedule.
    """
    arrangement: Optional[str] = None
    cadence: Optional[str] = None
    amount_paise: Optional[int] = None
    gst_rate: Optional[float] = None
    service_id: Optional[str] = None
    next_run_date: Optional[str] = None
    is_active: Optional[bool] = None
    # No `description` / `due_date`. `billing_schedules` has neither column
    # (migration 073) — `BillingScheduleIn` accepts them and create_schedule
    # drops them, which is a gap of its own, but OFFERING them on a PATCH
    # would be worse: PostgREST rejects the whole row on an unknown key, so
    # sending one would silently fail the fee change beside it.

    @field_validator("arrangement")
    @classmethod
    def _arr(cls, v):
        if v is not None and v not in ("retainer", "one_time", "package"):
            raise ValueError("arrangement must be retainer | one_time | package")
        return v

    @field_validator("cadence")
    @classmethod
    def _cad(cls, v):
        if v is not None and v not in ("monthly", "quarterly", "annual", "one_time"):
            raise ValueError("cadence must be monthly | quarterly | annual | one_time")
        return v

    @field_validator("amount_paise")
    @classmethod
    def _amt(cls, v):
        if v is not None and v < 0:
            raise ValueError("amount_paise must be non-negative")
        return v

    @field_validator("service_id")
    @classmethod
    def _service(cls, v):
        # Not required on an update — omitting it leaves the stored one — but a
        # caller sending a blank string is clearing a field migration 206 made
        # mandatory, which is a different thing and is refused.
        if v is not None and not v.strip():
            raise ValueError("Product/Service is required.")
        return v


@router.patch("/schedules/{schedule_id}")
def update_schedule(schedule_id: str = Path(...),
                    body: BillingScheduleUpdateIn = ...,
                    current_user: dict = Depends(rbac("billing", "write"))):
    """Change a schedule's fee, cadence, service or active flag.

    There was no update path at all until now, and a retainer whose fee goes up
    is the ordinary case — without this the only way to record it was a second
    schedule, which then bills the client twice.
    """
    sched = billing_service.get_schedule(current_user["firm_id"], schedule_id)
    if not sched:
        raise HTTPException(status_code=404, detail="Billing schedule not found")
    # Same guard as create_schedule and generate: get_schedule firm-scopes its
    # query, and nothing asserted the CLIENT-scope invariant at the router.
    assert_client_access(current_user, sched.get("client_id"))
    out = billing_service.update_schedule(
        current_user["firm_id"], schedule_id,
        body.model_dump(exclude_unset=True), current_user.get("id"))
    if out is None:
        raise HTTPException(status_code=404, detail="Billing schedule not found")
    return api_response(True, out)


@router.get("/service-options")
def service_options(current_user: dict = Depends(rbac("billing", "read"))):
    """The practice's OWN service catalogue — what a retainer can bill for.

    `billing_schedules.service_id` has been mandatory since migration 206, and
    the catalogue is CLIENT-owned (migration 182: "Client B must never inherit
    Client A's products"). The practice bills out of its INTERNAL client's
    books — `generate_for_schedule` resolves that client itself — so the right
    catalogue is that one, and answering here keeps the internal-client concept
    out of the browser entirely.

    An empty list is a real answer: a firm that has recorded no services yet
    has none, and the screen says so rather than offering a blank dropdown.
    Not provisioned yet is the same shape — `get_internal_client_id` returns
    None and the caller gets `[]` with `internal_client_id: null`, which is
    what `generate` would 409 on.
    """
    from services.internal_client_service import get_internal_client_id
    firm_id = current_user["firm_id"]
    internal_id = get_internal_client_id(firm_id)
    if not internal_id:
        return api_response(True, {"internal_client_id": None, "services": []})
    # SCOPED, not exempted. The client is resolved server-side and cannot be
    # steered by the caller, but the handler still reads one client's rows, so
    # it goes through the same check every other billing endpoint does —
    # `create_schedule` and `generate` carry the identical guard with the
    # identical reasoning: a no-op while "billing" is Partner-only, and the
    # thing that keeps it right if it is ever opened to Manager or Executive.
    assert_client_access(current_user, internal_id)
    from core.supabase_client import get_supabase
    import os
    if not os.environ.get("SUPABASE_URL"):
        return api_response(True, {"internal_client_id": internal_id, "services": []})
    # Columns as migration 176 declares them: `gst_rate_bps` (basis points, a
    # hint only) and `is_active`, not the `gst_rate_percent` / `is_archived`
    # the models layer speaks in.
    rows = (get_supabase().table("service_catalogue")
            .select("id, name, hsn_sac, default_rate_paise, gst_rate_bps")
            .eq("firm_id", firm_id).eq("client_id", internal_id)
            .eq("is_active", True).order("name").execute().data or [])
    return api_response(True, {"internal_client_id": internal_id, "services": rows})


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
# NO journal, NO statement, NO GST/cash-flow impact. Manual and CA-initiated
# ONLY — see send_invoice_reminder below, per-invoice.
#
# There used to also be an automatic bulk version here (POST
# /collections/run-customer-reminders, plus a nightly scheduler job) that
# looped every open invoice for the firm with no bound and no way to resume.
# On a firm with a large overdue backlog it could never complete a single
# pass, and every job scheduled after it in the nightly sweep silently never
# ran for that firm, every day, indefinitely. Removed entirely rather than
# fixed in place — automatic emails to a client's own customers should not
# exist as a feature with no visible on/off switch anywhere in the product.

class ReminderSettingsIn(BaseModel):
    attach_pdf: Optional[bool] = None


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
    # M2 audit finding: client_id is caller-supplied and only ANDed into the
    # query — a foreign id would silently yield zero rows without this guard.
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
