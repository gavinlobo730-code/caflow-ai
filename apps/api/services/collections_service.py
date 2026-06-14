"""
Collections & AR (Amendment v1.1 §3.1, Batch 4) — a thin read/sweep layer over
the internal client's sales invoices + receipts. Partner-only (G1) at the router.

Approved model:
- Aging is DUE-DATE based: days_overdue = today - reference_date, where
  reference_date = invoice.due_date else invoice_date + credit_days.
- Overdue is DERIVED + denormalised (is_overdue / days_overdue / aging_bucket).
  Payment status is never mutated. paid invoices are never overdue.
- TDS deducted on firm fees is captured on the receipt (tds_paise); once an
  invoice is settled (cash + TDS), its outstanding is 0 and it leaves AR.

Owns no ledger/GST logic — reuses client_sales_invoices, the receipts engine,
internal_client_service, and timeline_service.
"""
import os
import logging
from datetime import date, datetime, timezone, timedelta
from typing import Optional

from services.internal_client_service import get_internal_client_id

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.collections")

DEFAULT_CREDIT_DAYS = 30          # fallback when invoice.due_date is absent
REMINDER_INTERVAL_DAYS = 7        # collections reminder cadence (anti-spam)
_OPEN_STATUSES = ("issued", "partially_paid")


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _today() -> date:
    return date.today()


def reference_due_date(inv: dict, credit_days: int = DEFAULT_CREDIT_DAYS) -> Optional[date]:
    """due_date when present, else invoice_date + credit_days."""
    if inv.get("due_date"):
        try:
            return date.fromisoformat(str(inv["due_date"])[:10])
        except ValueError:
            pass
    if inv.get("invoice_date"):
        try:
            return date.fromisoformat(str(inv["invoice_date"])[:10]) + timedelta(days=credit_days)
        except ValueError:
            return None
    return None


def aging_bucket(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "not_due"
    if days_overdue <= 30:
        return "0-30"
    if days_overdue <= 60:
        return "31-60"
    if days_overdue <= 90:
        return "61-90"
    return "90+"


def assess_invoice(inv: dict, today: Optional[date] = None,
                   credit_days: int = DEFAULT_CREDIT_DAYS) -> dict:
    """Return collections metadata for one invoice (pure; no I/O)."""
    today = today or _today()
    outstanding = int(inv.get("total_paise", 0)) - int(inv.get("paid_paise", 0))
    ref = reference_due_date(inv, credit_days)
    days_overdue = (today - ref).days if ref else 0
    is_open = inv.get("status") in _OPEN_STATUSES and outstanding > 0
    is_overdue = bool(is_open and days_overdue > 0)
    return {
        "outstanding_paise": max(outstanding, 0),
        "days_overdue": days_overdue if is_open else 0,
        "is_overdue": is_overdue,
        "aging_bucket": aging_bucket(days_overdue) if is_open else None,
    }


def _open_invoices(firm_id: str, internal_id: Optional[str]) -> list[dict]:
    if _USE_MOCK:
        from routers.sales_invoices import MOCK_SALES_INVOICES
        return [i for i in MOCK_SALES_INVOICES
                if i.get("firm_id") == firm_id
                and (internal_id is None or i.get("client_id") == internal_id)
                and i.get("status") in _OPEN_STATUSES
                and (int(i.get("total_paise", 0)) - int(i.get("paid_paise", 0))) > 0]
    q = (_db().table("client_sales_invoices").select("*")
         .eq("firm_id", firm_id).in_("status", list(_OPEN_STATUSES)))
    if internal_id:
        q = q.eq("client_id", internal_id)
    rows = q.execute().data or []
    return [r for r in rows if int(r.get("total_paise", 0)) - int(r.get("paid_paise", 0)) > 0]


def sweep_overdue(firm_id: str, today: Optional[date] = None) -> dict:
    """Recompute + persist is_overdue / days_overdue / aging_bucket for open
    internal-client invoices. Idempotent; safe to run daily."""
    today = today or _today()
    internal_id = get_internal_client_id(firm_id)
    updated = 0
    for inv in _open_invoices(firm_id, internal_id):
        m = assess_invoice(inv, today)
        if _USE_MOCK:
            inv.update({"is_overdue": m["is_overdue"], "days_overdue": m["days_overdue"],
                        "aging_bucket": m["aging_bucket"]})
        else:
            _db().table("client_sales_invoices").update({
                "is_overdue": m["is_overdue"], "days_overdue": m["days_overdue"],
                "aging_bucket": m["aging_bucket"],
            }).eq("id", inv["id"]).execute()
        updated += 1
    return {"swept": updated}


def ar_aging(firm_id: str, today: Optional[date] = None) -> dict:
    """AR aging across the internal client's open invoices (paise + counts per bucket)."""
    today = today or _today()
    internal_id = get_internal_client_id(firm_id)
    buckets = {b: {"paise": 0, "count": 0} for b in ("not_due", "0-30", "31-60", "61-90", "90+")}
    total_outstanding = 0
    overdue_paise = 0
    overdue_count = 0
    for inv in _open_invoices(firm_id, internal_id):
        m = assess_invoice(inv, today)
        b = m["aging_bucket"] or "not_due"
        buckets[b]["paise"] += m["outstanding_paise"]
        buckets[b]["count"] += 1
        total_outstanding += m["outstanding_paise"]
        if m["is_overdue"]:
            overdue_paise += m["outstanding_paise"]
            overdue_count += 1
    return {
        "buckets": buckets,
        "total_outstanding_paise": total_outstanding,
        "overdue_paise": overdue_paise,
        "overdue_count": overdue_count,
    }


def _collected_and_tds(firm_id: str, internal_id: Optional[str],
                       date_from: Optional[str], date_to: Optional[str]) -> tuple[int, int]:
    """(cash collected, TDS receivable captured) from receipts in the window."""
    if _USE_MOCK:
        from routers.receipts import MOCK_RECEIPTS
        rows = [r for r in MOCK_RECEIPTS if r.get("firm_id") == firm_id
                and (internal_id is None or r.get("client_id") == internal_id)]
    else:
        q = _db().table("receipts").select("amount_paise,tds_paise,receipt_date").eq("firm_id", firm_id)
        if internal_id:
            q = q.eq("client_id", internal_id)
        if date_from:
            q = q.gte("receipt_date", date_from)
        if date_to:
            q = q.lte("receipt_date", date_to)
        rows = q.execute().data or []
    if _USE_MOCK:
        if date_from:
            rows = [r for r in rows if str(r.get("receipt_date", "")) >= date_from]
        if date_to:
            rows = [r for r in rows if str(r.get("receipt_date", "")) <= date_to]
    cash = sum(int(r.get("amount_paise", 0)) for r in rows)
    tds = sum(int(r.get("tds_paise", 0)) for r in rows)
    return cash, tds


def dashboard(firm_id: str, date_from: Optional[str] = None, date_to: Optional[str] = None,
              today: Optional[date] = None) -> dict:
    """Firm Collections/AR dashboard KPIs (Partner-only). Operational metrics only;
    DSO/realization (Revenue Intelligence, FR-RI) are deferred to Phase 13+."""
    internal_id = get_internal_client_id(firm_id)
    aging = ar_aging(firm_id, today)
    cash, tds = _collected_and_tds(firm_id, internal_id, date_from, date_to)
    # top overdue clients (by outstanding) via billing_schedules.client_id mapping
    return {
        "total_receivable_paise": aging["total_outstanding_paise"],
        "aging": aging["buckets"],
        "overdue_paise": aging["overdue_paise"],
        "overdue_count": aging["overdue_count"],
        "tds_receivable_paise": tds,
        "collected_cash_paise": cash,
        "period": {"from": date_from, "to": date_to},
    }


def send_overdue_reminders(firm_id: str, today: Optional[date] = None) -> dict:
    """Send a collections reminder for overdue invoices not reminded within the
    cadence window. Idempotent (last_reminded_at gate). Reuses timeline_service;
    notification dispatch is best-effort. Portal/WhatsApp mirroring is Batch 7+."""
    from services.timeline_service import timeline_service
    today = today or _today()
    internal_id = get_internal_client_id(firm_id)
    cutoff = datetime.now(timezone.utc) - timedelta(days=REMINDER_INTERVAL_DAYS)
    sent = 0
    for inv in _open_invoices(firm_id, internal_id):
        m = assess_invoice(inv, today)
        if not m["is_overdue"]:
            continue
        last = inv.get("last_reminded_at")
        if last:
            try:
                if datetime.fromisoformat(str(last).replace("Z", "+00:00")) > cutoff:
                    continue  # reminded recently — skip (anti-spam)
            except ValueError:
                pass
        now_iso = datetime.now(timezone.utc).isoformat()
        count = int(inv.get("reminder_count", 0)) + 1
        if _USE_MOCK:
            inv.update({"last_reminded_at": now_iso, "reminder_count": count})
        else:
            _db().table("client_sales_invoices").update({
                "last_reminded_at": now_iso, "reminder_count": count,
            }).eq("id", inv["id"]).execute()
        try:
            timeline_service.log(
                inv.get("client_id", ""), "ai", "Payment Reminder Sent",
                f"Reminder #{count} for invoice {inv.get('invoice_no','')} "
                f"(₹{m['outstanding_paise'] // 100:,} overdue {m['days_overdue']}d)",
                "warning", firm_id=firm_id,
                entity_type="sales_invoice", entity_id=inv.get("id"),
                amount_paise=m["outstanding_paise"],
            )
        except Exception:  # pragma: no cover - timeline is best-effort
            pass
        sent += 1
    return {"reminders_sent": sent}
