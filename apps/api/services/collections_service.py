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
from services.email_service import GENERIC_SEND_FAILURE_MESSAGE

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.collections")

DEFAULT_CREDIT_DAYS = 30          # fallback when invoice.due_date is absent
REMINDER_INTERVAL_DAYS = 7        # collections reminder cadence (anti-spam)
_OPEN_STATUSES = ("issued", "partially_paid")


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _paginate_all(make_query, key: str = "id", page: int = 1000) -> list:
    """Fetch EVERY row of a Supabase query via keyset paging on `key` (task
    #221, same audit-C6 class as domain/reporting/sources.py's _fetch_all).
    An un-paged .execute() is silently capped at PostgREST's ~1000-row limit —
    an established firm invoicing many clients over several years can plausibly
    cross it on its own fee-invoice/receipt history, understating the
    Collections dashboard's cash-collected/AR totals with no error.
    `make_query` returns a fresh query builder each call. Test doubles that
    don't implement order/limit/gt just return their whole (small) fixture
    from a single execute(), which is already correct."""
    first = make_query()
    if not (hasattr(first, "gt") and hasattr(first, "order") and hasattr(first, "limit")):
        return first.execute().data or []
    out: list = []
    cursor = None
    while True:
        q = make_query()
        if cursor is not None:
            q = q.gt(key, cursor)
        rows = q.order(key).limit(page).execute().data or []
        out.extend(rows)
        if len(rows) < page:
            break
        cursor = rows[-1][key]
    return out


def _today() -> date:
    return date.today()


def reference_due_date(inv: dict, credit_days: int = DEFAULT_CREDIT_DAYS) -> Optional[date]:
    """due_date when present, else invoice_date + the invoice's OWN snapshotted
    credit_days (preferred) or the supplied fallback. Invoices created after the
    credit-terms snapshot always carry due_date, so this fallback only applies to
    older rows."""
    if inv.get("due_date"):
        try:
            return date.fromisoformat(str(inv["due_date"])[:10])
        except ValueError:
            pass
    cd = inv.get("credit_days")
    eff_credit_days = int(cd) if cd is not None else credit_days
    if inv.get("invoice_date"):
        try:
            return date.fromisoformat(str(inv["invoice_date"])[:10]) + timedelta(days=eff_credit_days)
        except (ValueError, TypeError):
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
    # Net outstanding = (total + debit notes) − cash/TDS settled (paid_paise) −
    # credit notes applied (credited_paise). TDS is correctly part of paid_paise
    # (settlement incl. §194 TDS); credit/debit notes must also move AR so aging
    # ties to the invoice sub-ledger (M13, CGST Act §34).
    outstanding = (int(inv.get("total_paise", 0))
                   + int(inv.get("debit_note_paise", 0) or 0)
                   - int(inv.get("paid_paise", 0))
                   - int(inv.get("credited_paise", 0) or 0))
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
                and (int(i.get("total_paise", 0)) + int(i.get("debit_note_paise", 0) or 0)
                     - int(i.get("paid_paise", 0)) - int(i.get("credited_paise", 0) or 0)) > 0]
    def make_q():
        # outstanding_paise is a generated column (migration 278) carrying exactly
        # the formula below — total + debit notes − paid − credited. Filtering on it
        # here keeps the fetch proportional to the number of invoices still owing
        # rather than to every issued/partially_paid invoice in the fee ledger
        # (CLAUDE.md, "Reporting performance"). The Python filter after the fetch is
        # retained: it is what mock mode and older test doubles run on.
        q = (_db().table("client_sales_invoices").select("*")
             .eq("firm_id", firm_id).in_("status", list(_OPEN_STATUSES))
             .gt("outstanding_paise", 0))
        if internal_id:
            q = q.eq("client_id", internal_id)
        return q
    rows = _paginate_all(make_q)
    # Same outstanding formula as assess_invoice — a "partially_paid" invoice
    # whose debit note is the only thing still owed (paid_paise == total_paise)
    # must not be silently dropped from the sweep/aging/reminder pipeline.
    return [r for r in rows
            if int(r.get("total_paise", 0)) + int(r.get("debit_note_paise", 0) or 0)
               - int(r.get("paid_paise", 0)) - int(r.get("credited_paise", 0) or 0) > 0]


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
        def make_q():
            q = _db().table("receipts").select("id,amount_paise,tds_paise,receipt_date").eq("firm_id", firm_id)
            if internal_id:
                q = q.eq("client_id", internal_id)
            if date_from:
                q = q.gte("receipt_date", date_from)
            if date_to:
                q = q.lte("receipt_date", date_to)
            return q
        rows = _paginate_all(make_q)
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


# ── Phase 4.2 — Customer-facing payment reminders (collections only) ──────────
# These send the CUSTOMER an overdue-payment reminder email (with the invoice PDF)
# and record the send in invoice_deliveries (kind='reminder'). They are purely
# informational: NO journal, NO statement, NO GST/cash-flow impact. Distinct from
# send_overdue_reminders() above, which is the practice's internal fee-collections
# sweep (timeline-only, Partner dashboard).

# Only attach_pdf remains. enabled/interval_days/max_reminders governed the
# automatic bulk cadence run (run_due_reminders), removed entirely: it looped
# every open invoice unbounded and, on any firm with a large enough overdue
# backlog, could never finish in one pass — starving every job scheduled after
# it in the nightly sweep, for that firm, every single day. The manual,
# CA-initiated single-invoice send (send_invoice_reminder, below) is the only
# way a reminder goes out now; attach_pdf is the one setting it still reads.
REMINDER_DEFAULTS = {"attach_pdf": True}


def reminder_settings(firm_id: str, db=None) -> dict:
    """Per-firm reminder policy (currently just attach_pdf). Falls back to defaults."""
    if _USE_MOCK:
        return dict(REMINDER_DEFAULTS)
    db = db or _db()
    try:
        rows = db.table("reminder_settings").select("*").eq("firm_id", firm_id).limit(1).execute().data or []
        if rows:
            return {"attach_pdf": bool(rows[0].get("attach_pdf", True))}
    except Exception:  # pragma: no cover - settings are best-effort
        pass
    return dict(REMINDER_DEFAULTS)


def update_reminder_settings(firm_id: str, fields: dict, db=None) -> dict:
    db = db or _db()
    payload = {k: v for k, v in fields.items() if k == "attach_pdf" and v is not None}
    payload["firm_id"] = firm_id
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.table("reminder_settings").upsert(payload, on_conflict="firm_id").execute()
    return reminder_settings(firm_id, db=db)


def _customer_for(db, firm_id: str, customer_id: Optional[str]) -> dict:
    if not customer_id:
        return {}
    try:
        rows = (db.table("customers").select("id,name,email")
                .eq("id", customer_id).eq("firm_id", firm_id).limit(1).execute().data or [])
        return rows[0] if rows else {}
    except Exception:  # pragma: no cover
        return {}


def _dispatch_invoice_reminder(db, firm_id: str, inv: dict, customer: dict,
                               reminder_number: int, actor_id: Optional[str] = None,
                               attach_pdf: bool = True, manual: bool = False) -> bool:
    """Send ONE customer reminder, record the delivery, and on success advance
    last_reminded_at / reminder_count. Returns True on send success."""
    from services.email_service import send_payment_reminder_to_customer
    from services.invoice_pdf_service import _load_firm, get_sales_invoice_pdf
    from services.timeline_service import timeline_service

    to_email = (customer or {}).get("email")
    if not to_email:
        return False
    m = assess_invoice(inv)
    invoice_id = inv["id"]

    pdf_bytes = pdf_name = None
    if attach_pdf:
        try:
            pdf_bytes, pdf_name = get_sales_invoice_pdf(invoice_id, firm_id)
        except Exception as e:  # best-effort — still send the reminder text
            _logger.warning("Reminder PDF generation failed for %s: %s", invoice_id, e)

    delivery_id = None
    try:
        d = (db.table("invoice_deliveries").insert({
            "firm_id": firm_id, "client_id": inv.get("client_id"), "invoice_id": invoice_id,
            "kind": "reminder", "sent_to": to_email, "sent_by_id": actor_id, "status": "sending",
        }).execute().data or [{}])[0]
        delivery_id = d.get("id")
    except Exception:  # pragma: no cover
        pass

    firm_name = (_load_firm(firm_id) or {}).get("name") or "Your Chartered Accountant"
    success, provider = send_payment_reminder_to_customer(
        to=to_email, customer_name=(customer or {}).get("name") or "Customer",
        firm_name=firm_name, invoice_no=inv.get("invoice_no", ""),
        invoice_date=str(inv.get("invoice_date", ""))[:10],
        due_date=str(inv["due_date"])[:10] if inv.get("due_date") else None,
        outstanding_paise=m["outstanding_paise"], reminder_number=reminder_number,
        pdf_bytes=pdf_bytes, pdf_filename=pdf_name)

    now_iso = datetime.now(timezone.utc).isoformat()
    if delivery_id:
        upd = {"status": "sent" if success else "failed"}
        if provider:
            upd["provider_message_id"] = provider
        if success:
            upd["sent_at"] = now_iso
        else:
            upd["error_message"] = GENERIC_SEND_FAILURE_MESSAGE
        try:
            db.table("invoice_deliveries").update(upd).eq("id", delivery_id).execute()
        except Exception:  # pragma: no cover
            pass

    if success:
        try:
            db.table("client_sales_invoices").update({
                "last_reminded_at": now_iso, "reminder_count": reminder_number,
            }).eq("id", invoice_id).eq("firm_id", firm_id).execute()
        except Exception:  # pragma: no cover
            pass
        try:
            timeline_service.log(inv.get("client_id", ""), "ai", "Payment Reminder Emailed",
                                 f"Reminder #{reminder_number}{' (manual)' if manual else ''} for "
                                 f"invoice {inv.get('invoice_no', '')} emailed to {to_email}", "warning",
                                 firm_id=firm_id, entity_type="sales_invoice", entity_id=invoice_id,
                                 amount_paise=m["outstanding_paise"])
        except Exception:  # pragma: no cover
            pass
        try:
            from services.audit_service import log_event
            log_event(firm_id, "sales_invoice", invoice_id, "reminder_sent", actor_id=actor_id,
                      new_data={"reminder_number": reminder_number, "sent_to": to_email, "manual": manual},
                      metadata={"source": "payment_reminder"})
        except Exception:  # pragma: no cover
            pass
    return success


def send_invoice_reminder(firm_id: str, invoice_id: str, actor_id: Optional[str] = None,
                          db=None) -> dict:
    """Manual single-invoice reminder (CA-initiated). Allowed for any OVERDUE
    invoice; bypasses the automatic cadence/cap but never sends before due."""
    from fastapi import HTTPException
    db = db or _db()
    rows = (db.table("client_sales_invoices").select("*")
            .eq("id", invoice_id).eq("firm_id", firm_id).limit(1).execute().data or [])
    inv = rows[0] if rows else None
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if not assess_invoice(inv)["is_overdue"]:
        raise HTTPException(status_code=422,
                            detail="Invoice is not overdue — reminders are for overdue invoices only.")
    customer = _customer_for(db, firm_id, inv.get("customer_id"))
    if not customer.get("email"):
        raise HTTPException(status_code=422, detail="Customer has no email address on file.")
    s = reminder_settings(firm_id, db=db)
    number = int(inv.get("reminder_count", 0)) + 1
    if not _dispatch_invoice_reminder(db, firm_id, inv, customer, number, actor_id=actor_id,
                                      attach_pdf=s["attach_pdf"], manual=True):
        raise HTTPException(status_code=502, detail="Reminder email could not be sent.")
    return {"sent": True, "to": customer["email"], "reminder_number": number}


def invoice_reminder_history(firm_id: str, invoice_id: str, db=None) -> list[dict]:
    db = db or _db()
    return (db.table("invoice_deliveries").select("*")
            .eq("firm_id", firm_id).eq("invoice_id", invoice_id).eq("kind", "reminder")
            .order("created_at", desc=True).execute().data or [])
