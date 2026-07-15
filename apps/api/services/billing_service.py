"""
Billing Orchestration (Amendment v1.1 §3.1) — a THIN service over the existing
accounting/Sales/GST engines. It owns NO ledger or GST logic: it materialises
billing_schedules into draft sales invoices in the internal client's books by
calling the existing Sales engine (routers.sales_invoices.create_invoice), and
tracks AR status from the existing receipts engine.

Design guarantees (Batch 3):
- REUSE, not reinvent: GST + invoice insert come from the Sales engine; the
  journal is posted by the existing issue path (phase2_journal_service). No
  second GST/accounting implementation is introduced.
- Idempotent / replay-safe / duplicate-safe: at most one invoice per
  (billing_schedule, period). Enforced by an existence check (fast path) AND the
  authoritative UNIQUE index uq_client_sales_invoices_billing_run (migration 075).
- Traceable: every generated invoice carries billing_schedule_id + billing_period;
  the originating practice client is billing_schedules.client_id; the linked
  customer is the invoice customer_id (client_firm_customer_links, G3).
- Partner-only (G1): billing endpoints require the Partner/Owner role.
- CA-confirm gate: generation produces a DRAFT; despatch/posting happens only on
  the existing draft->issue transition (reused), which is Partner-gated for the
  internal client.
"""
import os
import uuid
import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import HTTPException

from models.invoices import SalesInvoiceIn, InvoiceLineIn
from services.internal_client_service import get_internal_client_id
from services.numbering import draft_placeholder_invoice_no

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.billing")

# SAC for services rendered by Chartered Accountants (CGST — professional fees).
CA_SERVICE_SAC = "998211"

# In-memory stores (mock mode only) — mirrors the convention in sales_invoices.py.
MOCK_BILLING_SCHEDULES: list[dict] = []
MOCK_CLIENT_LINKS: list[dict] = []


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _today_iso() -> str:
    return date.today().isoformat()


# ── Period + cadence helpers ─────────────────────────────────────────────────

def period_for(cadence: str, run_date: Optional[str]) -> str:
    """Deterministic period label for idempotency (one invoice per schedule/period)."""
    d = date.fromisoformat(run_date) if run_date else date.today()
    if cadence == "monthly":
        return f"{d.year}-{d.month:02d}"
    if cadence == "quarterly":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    if cadence == "annual":
        start = d.year if d.month >= 4 else d.year - 1  # Indian FY
        return f"{start}-{str(start + 1)[2:]}"
    return "ONCE"  # one_time


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    return date(y, m % 12 + 1, min(d.day, 28))


def next_run_after(cadence: str, current: Optional[str]) -> Optional[str]:
    """Next run date after a generated period (None for one_time → schedule closes)."""
    base = date.fromisoformat(current) if current else date.today()
    if cadence == "monthly":
        return _add_months(base, 1).isoformat()
    if cadence == "quarterly":
        return _add_months(base, 3).isoformat()
    if cadence == "annual":
        return _add_months(base, 12).isoformat()
    return None


# ── Guardrail G3 — one customer per practice client (idempotent) ─────────────

def ensure_customer_link(firm_id: str, practice_client_id: str, internal_client_id: str) -> str:
    """Return the internal-client customer id linked to this practice client,
    creating the customer + link on first use. The UNIQUE(firm_id, client_id) on
    client_firm_customer_links is the authoritative single-link guarantee (G3)."""
    if _USE_MOCK:
        for lk in MOCK_CLIENT_LINKS:
            if lk["firm_id"] == firm_id and lk["client_id"] == practice_client_id:
                return lk["internal_customer_id"]
        cust_id = str(uuid.uuid4())
        MOCK_CLIENT_LINKS.append({
            "id": str(uuid.uuid4()), "firm_id": firm_id,
            "client_id": practice_client_id, "internal_customer_id": cust_id,
        })
        return cust_id

    db = _db()
    existing = (
        db.table("client_firm_customer_links")
        .select("internal_customer_id")
        .eq("firm_id", firm_id).eq("client_id", practice_client_id).limit(1).execute()
    )
    if existing.data:
        return existing.data[0]["internal_customer_id"]

    pc = (
        db.table("clients").select("client_name, gstin, pan, state_code")
        .eq("id", practice_client_id).limit(1).execute()
    )
    pcd = pc.data[0] if pc.data else {}
    cust = db.table("customers").insert({
        "firm_id": firm_id,
        "client_id": internal_client_id,           # customer lives in the internal client's books
        "name": pcd.get("client_name") or "Client",
        "gstin": pcd.get("gstin"),
        "pan": pcd.get("pan"),
        "state_code": pcd.get("state_code"),
    }).execute()
    cust_id = cust.data[0]["id"]
    try:
        db.table("client_firm_customer_links").insert({
            "firm_id": firm_id, "client_id": practice_client_id, "internal_customer_id": cust_id,
        }).execute()
        return cust_id
    except Exception as e:  # unique(firm_id, client_id) race — another link won
        _logger.warning("customer-link race for client %s: %s", practice_client_id, e)
        db.table("customers").update({"is_active": False}).eq("id", cust_id).execute()
        again = (
            db.table("client_firm_customer_links").select("internal_customer_id")
            .eq("firm_id", firm_id).eq("client_id", practice_client_id).limit(1).execute()
        )
        if again.data:
            return again.data[0]["internal_customer_id"]
        raise


# ── Idempotency lookup ───────────────────────────────────────────────────────

def _find_generated(firm_id: str, schedule_id: str, period: str) -> Optional[dict]:
    if _USE_MOCK:
        from routers.sales_invoices import MOCK_SALES_INVOICES
        for inv in MOCK_SALES_INVOICES:
            if inv.get("billing_schedule_id") == schedule_id and inv.get("billing_period") == period:
                return inv
        return None
    res = (
        _db().table("client_sales_invoices").select("*")
        .eq("firm_id", firm_id).eq("billing_schedule_id", schedule_id)
        .eq("billing_period", period).limit(1).execute()
    )
    return res.data[0] if res.data else None


def _stamp_billing_fields(firm_id: str, invoice: dict, schedule_id: str, period: str) -> dict:
    """Attach traceability to a freshly-created invoice. The UNIQUE index is the
    authoritative duplicate backstop; on conflict we drop the just-created draft
    and return the invoice that won."""
    fields = {"billing_schedule_id": schedule_id, "billing_period": period, "source": "billing"}
    if _USE_MOCK:
        invoice.update(fields)
        return invoice
    invoice_id = invoice["id"]
    try:
        upd = _db().table("client_sales_invoices").update(fields).eq("id", invoice_id).execute()
        return upd.data[0] if upd.data else {**invoice, **fields}
    except Exception as e:  # unique(billing_schedule_id, billing_period) race
        _logger.warning("duplicate billing run for schedule %s period %s: %s", schedule_id, period, e)
        # remove the orphan draft (no journal posted yet) and return the winner
        _db().table("client_sales_invoice_lines").delete().eq("invoice_id", invoice_id).execute()
        _db().table("client_sales_invoices").delete().eq("id", invoice_id).execute()
        winner = _find_generated(firm_id, schedule_id, period)
        if winner:
            return winner
        raise


# ── Generation ───────────────────────────────────────────────────────────────

def generate_for_schedule(firm_id: str, schedule: dict, current_user: dict,
                          period: Optional[str] = None) -> dict:
    """Idempotently generate a DRAFT sales invoice for one schedule/period.
    Returns {invoice, period, created, idempotent}."""
    internal_id = get_internal_client_id(firm_id)
    if not internal_id and not _USE_MOCK:
        raise HTTPException(status_code=409,
                            detail="Provision the firm's practice (internal client) before billing.")
    cadence = schedule.get("cadence", "monthly")
    period = period or period_for(cadence, schedule.get("next_run_date"))

    existing = _find_generated(firm_id, schedule["id"], period)
    if existing:
        return {"invoice": existing, "period": period, "created": False, "idempotent": True}

    internal_id = internal_id or "mock-internal"
    customer_id = ensure_customer_link(firm_id, schedule["client_id"], internal_id)

    line = InvoiceLineIn(
        service_catalogue_id=schedule["service_id"],
        description=schedule.get("description") or "Professional fees",
        hsn_sac=CA_SERVICE_SAC, quantity=1,
        rate_paise=int(schedule["amount_paise"]),
        gst_rate_percent=float(schedule.get("gst_rate", 18) or 0),
        is_service=True,
    )
    inv_in = SalesInvoiceIn(
        client_id=internal_id, customer_id=customer_id,
        # Sales invoice numbering is fully manual (no CA present in an
        # unattended billing run) — a placeholder the CA must replace with
        # the real invoice number before Issue. See draft_placeholder_invoice_no.
        invoice_no=draft_placeholder_invoice_no(),
        invoice_date=_today_iso(),
        due_date=schedule.get("due_date"), lines=[line],
        notes=f"Auto-generated from billing schedule {schedule['id']} for {period}",
    )

    # REUSE the Sales engine (GST + insert + timeline + mock/DB paths).
    from routers.sales_invoices import create_invoice
    resp = create_invoice(inv_in, current_user)
    if not resp.get("success"):
        raise HTTPException(status_code=500, detail=resp.get("error") or "Invoice generation failed")
    invoice = _stamp_billing_fields(firm_id, resp["data"], schedule["id"], period)

    _advance_schedule(firm_id, schedule, cadence)
    return {"invoice": invoice, "period": period, "created": True, "idempotent": False}


def _advance_schedule(firm_id: str, schedule: dict, cadence: str) -> None:
    nxt = next_run_after(cadence, schedule.get("next_run_date"))
    updates = {"next_run_date": nxt}
    if nxt is None:  # one_time schedule completes after a single run
        updates["is_active"] = False
    if _USE_MOCK:
        schedule.update(updates)
        return
    _db().table("billing_schedules").update(updates).eq("id", schedule["id"]).eq("firm_id", firm_id).execute()


# ── Schedules ────────────────────────────────────────────────────────────────

def list_schedules(firm_id: str, active_only: bool = False) -> list[dict]:
    if _USE_MOCK:
        out = [s for s in MOCK_BILLING_SCHEDULES if s["firm_id"] == firm_id]
        return [s for s in out if s.get("is_active", True)] if active_only else out
    q = _db().table("billing_schedules").select("*").eq("firm_id", firm_id)
    if active_only:
        q = q.eq("is_active", True)
    return q.order("next_run_date").execute().data or []


def get_schedule(firm_id: str, schedule_id: str) -> Optional[dict]:
    if _USE_MOCK:
        return next((s for s in MOCK_BILLING_SCHEDULES
                     if s["id"] == schedule_id and s["firm_id"] == firm_id), None)
    res = (_db().table("billing_schedules").select("*")
           .eq("id", schedule_id).eq("firm_id", firm_id).limit(1).execute())
    return res.data[0] if res.data else None


def create_schedule(firm_id: str, data: dict, created_by: Optional[str]) -> dict:
    payload = {
        "firm_id": firm_id,
        "client_id": data["client_id"],
        "arrangement": data["arrangement"],
        "service_id": data.get("service_id"),
        "amount_paise": int(data["amount_paise"]),
        "gst_rate": float(data.get("gst_rate", 18) or 0),
        "cadence": data["cadence"],
        "next_run_date": data.get("next_run_date") or _today_iso(),
        "is_active": data.get("is_active", True),
        "created_by": created_by,
    }
    if _USE_MOCK:
        payload["id"] = str(uuid.uuid4())
        payload["created_at"] = datetime.now(timezone.utc).isoformat()
        MOCK_BILLING_SCHEDULES.append(payload)
        return payload
    return _db().table("billing_schedules").insert(payload).execute().data[0]


def preview_due(firm_id: str, as_of: Optional[str] = None) -> list[dict]:
    """Active schedules whose next_run_date is due, with the period that would be
    generated and whether an invoice already exists (idempotent preview, no writes)."""
    as_of = as_of or _today_iso()
    due = []
    for s in list_schedules(firm_id, active_only=True):
        nrd = s.get("next_run_date")
        if nrd and nrd <= as_of:
            period = period_for(s.get("cadence", "monthly"), nrd)
            existing = _find_generated(firm_id, s["id"], period)
            due.append({
                "schedule_id": s["id"], "client_id": s["client_id"],
                "cadence": s.get("cadence"), "amount_paise": s.get("amount_paise"),
                "period": period, "already_generated": bool(existing),
            })
    return due


# ── Batch 5: billable / cost-rate capture + unbilled-work visibility ─────────
# Data-capture only. NO realization / margin / profitability / forecasting /
# utilization. cost_rate_paise is captured + partner-visible but is NEVER used in
# any computation here.

MOCK_COST_RATES: dict = {}   # mock-mode staff cost rates {user_id: paise}


def unbilled_value_paise(minutes: Optional[int], billable_rate_paise: Optional[int],
                         hourly_rate_paise: Optional[int]) -> int:
    """Billable value of a time entry in integer paise (minutes x rate / 60).
    Prefers billable_rate_paise; falls back to the legacy hourly_rate_paise."""
    rate = billable_rate_paise if billable_rate_paise else (hourly_rate_paise or 0)
    return (int(minutes or 0) * int(rate)) // 60


def group_unbilled(entries: list[dict]) -> dict:
    """Group billable, not-yet-billed time entries by client and by work item.
    Pure: filters is_billable AND billed_invoice_id IS NULL. No cost, no margin."""
    by_client: dict = {}
    by_work_item: dict = {}
    total_value = 0
    total_minutes = 0
    for e in entries:
        if not e.get("is_billable") or e.get("billed_invoice_id"):
            continue
        minutes = int(e.get("duration_minutes") or 0)
        if minutes <= 0:
            continue
        value = unbilled_value_paise(minutes, e.get("billable_rate_paise"), e.get("hourly_rate_paise"))
        cid = e.get("client_id") or "unassigned"
        wid = e.get("task_id") or "unassigned"
        for bucket, key in ((by_client, cid), (by_work_item, wid)):
            slot = bucket.setdefault(key, {"minutes": 0, "value_paise": 0, "count": 0})
            slot["minutes"] += minutes
            slot["value_paise"] += value
            slot["count"] += 1
        total_value += value
        total_minutes += minutes
    return {"by_client": by_client, "by_work_item": by_work_item,
            "total_value_paise": total_value, "total_minutes": total_minutes}


def unbilled_work(firm_id: str, client_id: Optional[str] = None) -> dict:
    """Unbilled-work view: billable, not-yet-billed time entries grouped by
    client/work item with their billable value (integer paise)."""
    if _USE_MOCK:
        entries: list[dict] = []   # time-entry repo is DB-only; mock returns empty
    else:
        q = (_db().table("time_entries").select("*")
             .eq("firm_id", firm_id).eq("is_billable", True).is_("billed_invoice_id", None))
        if client_id:
            q = q.eq("client_id", client_id)
        entries = q.execute().data or []
    return group_unbilled(entries)


def list_staff_cost_rates(firm_id: str) -> list[dict]:
    """Staff cost rates (partner-visible). Capture/display only."""
    if _USE_MOCK:
        return [{"user_id": uid, "cost_rate_paise": rate} for uid, rate in MOCK_COST_RATES.items()]
    rows = (_db().table("users").select("id, full_name, role, cost_rate_paise")
            .eq("firm_id", firm_id).execute().data or [])
    return rows


def set_staff_cost_rate(firm_id: str, user_id: str, cost_rate_paise: Optional[int]) -> dict:
    """Set a staff member's cost rate (integer paise, or None to clear)."""
    if cost_rate_paise is not None and int(cost_rate_paise) < 0:
        raise HTTPException(status_code=422, detail="cost_rate_paise must be non-negative")
    if _USE_MOCK:
        MOCK_COST_RATES[user_id] = cost_rate_paise
        return {"user_id": user_id, "cost_rate_paise": cost_rate_paise}
    row = (_db().table("users").update({"cost_rate_paise": cost_rate_paise})
           .eq("id", user_id).eq("firm_id", firm_id).execute())
    return row.data[0] if row.data else {"user_id": user_id, "cost_rate_paise": cost_rate_paise}


def mark_time_entries_billed(firm_id: str, entry_ids: list[str], invoice_id: str) -> dict:
    """System-controlled billed linkage for future time-based billing. Sets
    billed_invoice_id (authoritative); is_billed derives automatically (generated
    column). Not exposed for manual editing."""
    if _USE_MOCK or not entry_ids:
        return {"marked": 0}
    db = _db()
    count = 0
    for eid in entry_ids:
        db.table("time_entries").update({"billed_invoice_id": invoice_id}).eq("id", eid).eq("firm_id", firm_id).execute()
        count += 1
    return {"marked": count}


def run_due(firm_id: str, current_user: dict, as_of: Optional[str] = None) -> dict:
    """Generate drafts for all due schedules. Idempotent: already-generated
    schedules are skipped (counted separately)."""
    as_of = as_of or _today_iso()
    generated, skipped = [], []
    for s in list_schedules(firm_id, active_only=True):
        nrd = s.get("next_run_date")
        if not (nrd and nrd <= as_of):
            continue
        result = generate_for_schedule(firm_id, s, current_user)
        (generated if result["created"] else skipped).append({
            "schedule_id": s["id"], "period": result["period"],
            "invoice_id": result["invoice"].get("id"),
        })
    return {"generated": generated, "skipped": skipped,
            "generated_count": len(generated), "skipped_count": len(skipped)}
