"""
Payment service (Phase 4.6) — orchestrates online payments WITHOUT ever doing
accounting itself.

Boundaries (hard rules):
  • A gateway/provider never creates accounting entries.
  • Accounting happens ONLY through services.receipt_service.create_receipt_core,
    and ONLY on a signature-VERIFIED `captured` event, AT MOST ONCE per payment
    (sealed by customer_payments.receipt_id).
  • AR stays invoices + receipts + allocations. No parallel receivable.
  • Webhooks are signature-verified, replay-protected (unique provider_event_id)
    and idempotent (unique provider_payment_id + receipt_id seal).

db-driven (tests pass a fake db; prod passes the Supabase client). Integer paise.
"""
import logging
from datetime import datetime, timezone, date, timedelta
from typing import Optional

from fastapi import HTTPException

from services.audit_service import log_event
from services.timeline_service import timeline_service
from services import email_service
from services.receipt_service import create_receipt_core, _current_fy_long
from services.payments import get_provider, PaymentLinkRequest, CAPTURED, FAILED, REFUNDED

_logger = logging.getLogger("caflow.payment_service")

# System actor for receipts/audit created by an automated payment capture.
def _system_actor(provider: str) -> dict:
    return {"auth_user_id": None, "email": f"online-payment:{provider}"}

_OPEN_LINK = ("created", "active")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_invoice(db, firm_id: str, invoice_id: str) -> Optional[dict]:
    rows = (db.table("client_sales_invoices")
            .select("id,firm_id,client_id,customer_id,invoice_no,total_paise,paid_paise,status")
            .eq("id", invoice_id).eq("firm_id", firm_id).is_("deleted_at", "null")
            .limit(1).execute().data or [])
    return rows[0] if rows else None


def _outstanding(inv: dict) -> int:
    return int(inv.get("total_paise", 0) or 0) - int(inv.get("paid_paise", 0) or 0)


def _customer(db, firm_id: str, customer_id: str) -> dict:
    rows = (db.table("customers").select("id,name,email,phone")
            .eq("id", customer_id).eq("firm_id", firm_id).limit(1).execute().data or [])
    return rows[0] if rows else {}


# ── Payment link generation (Deliverable D) ───────────────────────────────────

def create_link(db, firm_id: str, invoice_id: str, actor: dict,
                provider_name: Optional[str] = None, expires_in_days: int = 7) -> dict:
    """Create a hosted payment link for an invoice's EXACT outstanding balance.

    - amount = outstanding (cannot exceed it; rejected if <= 0)
    - idempotent: returns an existing OPEN link for the same invoice + amount
      instead of creating a duplicate (multiple links across different amounts
      are still allowed)
    - audit logged
    """
    inv = _get_invoice(db, firm_id, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    outstanding = _outstanding(inv)
    if outstanding <= 0:
        raise HTTPException(status_code=422, detail="Invoice has no outstanding balance to collect.")

    # Idempotency: reuse an existing open link of the same amount.
    existing = (db.table("customer_payment_links").select("*")
                .eq("firm_id", firm_id).eq("invoice_id", invoice_id)
                .eq("amount_paise", outstanding).in_("status", list(_OPEN_LINK))
                .limit(1).execute().data or [])
    if existing:
        return existing[0]

    provider = get_provider(provider_name)

    # Insert first so the provider reference_id == our link id (clean webhook correlation).
    link_row = (db.table("customer_payment_links").insert({
        "firm_id": firm_id, "client_id": inv["client_id"], "customer_id": inv["customer_id"],
        "invoice_id": invoice_id, "amount_paise": outstanding, "currency": "INR",
        "provider": provider.name, "status": "created", "created_by": actor.get("auth_user_id"),
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat(),
    }).execute().data or [{}])[0]
    link_id = link_row.get("id")

    cust = _customer(db, firm_id, inv["customer_id"])
    result = provider.create_payment_link(PaymentLinkRequest(
        amount_paise=outstanding,
        reference_id=str(link_id),
        description=f"Invoice {inv.get('invoice_no', '')}",
        customer_name=cust.get("name"), customer_email=cust.get("email"),
        customer_phone=cust.get("phone"),
        expires_at=int((datetime.now(timezone.utc) + timedelta(days=expires_in_days)).timestamp()),
        notes={"invoice_id": invoice_id, "link_id": str(link_id)},
    ))

    updated = (db.table("customer_payment_links").update({
        "provider_link_id": result.provider_link_id, "provider_order_id": result.provider_order_id,
        "short_url": result.short_url, "status": "active", "updated_at": _now(),
    }).eq("id", link_id).execute().data or [{}])[0]

    log_event(firm_id, "payment_link", str(link_id), "create",
              actor_id=actor.get("auth_user_id"), actor_email=actor.get("email"),
              new_data={"invoice_id": invoice_id, "amount_paise": outstanding, "provider": provider.name})
    return updated or {**link_row, "short_url": result.short_url, "status": "active"}


def list_links(db, firm_id: str, invoice_id: str) -> list[dict]:
    return (db.table("customer_payment_links").select("*")
            .eq("firm_id", firm_id).eq("invoice_id", invoice_id)
            .order("created_at", desc=True).execute().data or [])


def get_link(db, firm_id: str, link_id: str) -> Optional[dict]:
    rows = (db.table("customer_payment_links").select("*")
            .eq("firm_id", firm_id).eq("id", link_id).limit(1).execute().data or [])
    return rows[0] if rows else None


def list_payments(db, firm_id: str, invoice_id: str) -> list[dict]:
    return (db.table("customer_payments").select("*")
            .eq("firm_id", firm_id).eq("invoice_id", invoice_id)
            .order("created_at", desc=True).execute().data or [])


def history(db, firm_id: str, invoice_id: str) -> dict:
    """Outstanding + links + payments for the invoice UI (Deliverable G)."""
    inv = _get_invoice(db, firm_id, invoice_id)
    return {
        "invoice_id": invoice_id,
        "outstanding_paise": _outstanding(inv) if inv else 0,
        "links": list_links(db, firm_id, invoice_id),
        "payments": list_payments(db, firm_id, invoice_id),
    }


# ── Email a payment link (Deliverable H — reuse email + invoice_deliveries) ────

def send_link_email(db, firm_id: str, link_id: str, actor: dict) -> dict:
    link = get_link(db, firm_id, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Payment link not found.")
    inv = _get_invoice(db, firm_id, link["invoice_id"])
    cust = _customer(db, firm_id, link["customer_id"])
    to = cust.get("email")
    if not to:
        raise HTTPException(status_code=422, detail="Customer has no email on file.")

    # Firm display name (best-effort; non-fatal).
    firm_name = "Your accountant"
    try:
        frows = db.table("firms").select("name").eq("id", firm_id).limit(1).execute().data or []
        if frows:
            firm_name = frows[0].get("name") or firm_name
    except Exception:
        pass

    ok = email_service.send_payment_link_to_customer(
        to=to, customer_name=cust.get("name") or "", firm_name=firm_name,
        invoice_no=(inv or {}).get("invoice_no", ""), amount_paise=int(link["amount_paise"]),
        pay_url=link.get("short_url") or "")

    # Reuse invoice_deliveries (kind='payment_link') for delivery tracking.
    db.table("invoice_deliveries").insert({
        "firm_id": firm_id, "client_id": link["client_id"], "invoice_id": link["invoice_id"],
        "kind": "payment_link", "sent_to": to, "sent_by_id": actor.get("auth_user_id"),
        "sent_by_email": actor.get("email"), "status": "sent" if ok else "failed",
        "sent_at": _now() if ok else None,
    }).execute()

    log_event(firm_id, "payment_link", str(link_id), "send",
              actor_id=actor.get("auth_user_id"), actor_email=actor.get("email"),
              new_data={"sent_to": to, "ok": ok})
    return {"sent": ok, "to": to}


# ── Webhook processing (Deliverables E + I) ────────────────────────────────────

def _event_seen(db, provider: str, event_id: str) -> bool:
    if not event_id:
        return False
    rows = (db.table("customer_payment_events").select("id")
            .eq("provider", provider).eq("provider_event_id", event_id)
            .limit(1).execute().data or [])
    return bool(rows)


def _record_event(db, payment_id: Optional[str], event, firm_id: Optional[str]) -> None:
    try:
        db.table("customer_payment_events").insert({
            "firm_id": firm_id, "payment_id": payment_id, "provider": event.provider,
            "provider_event_id": event.event_id or None, "event_type": event.event_type,
            "status": event.status, "signature_verified": event.signature_verified,
            "raw_payload": event.raw,
        }).execute()
    except Exception as e:  # unique-violation on replay race → benign
        _logger.info("payment event not recorded (likely duplicate): %s", e)


def _find_link(db, event) -> Optional[dict]:
    if event.provider_link_id:
        rows = (db.table("customer_payment_links").select("*")
                .eq("provider", event.provider).eq("provider_link_id", event.provider_link_id)
                .limit(1).execute().data or [])
        if rows:
            return rows[0]
    if event.provider_order_id:
        rows = (db.table("customer_payment_links").select("*")
                .eq("provider", event.provider).eq("provider_order_id", event.provider_order_id)
                .limit(1).execute().data or [])
        if rows:
            return rows[0]
    return None


def _resolve_payment(db, event) -> Optional[dict]:
    """Find the customer_payments row for this event, creating it from the
    originating link on first sight. None when the event can't be correlated."""
    if event.provider_payment_id:
        rows = (db.table("customer_payments").select("*")
                .eq("provider", event.provider).eq("provider_payment_id", event.provider_payment_id)
                .limit(1).execute().data or [])
        if rows:
            return rows[0]
    link = _find_link(db, event)
    if not link:
        return None
    amount = int(event.amount_paise or link["amount_paise"])
    return (db.table("customer_payments").insert({
        "firm_id": link["firm_id"], "client_id": link["client_id"], "customer_id": link["customer_id"],
        "invoice_id": link["invoice_id"], "payment_link_id": link["id"], "amount_paise": amount,
        "currency": "INR", "status": event.status, "provider": event.provider,
        "provider_payment_id": event.provider_payment_id, "provider_order_id": event.provider_order_id,
    }).execute().data or [{}])[0]


def _settle(db, payment: dict, event) -> dict:
    """Create the receipt via the EXISTING engine. The only accounting in this file."""
    firm_id = payment["firm_id"]
    inv = _get_invoice(db, firm_id, payment["invoice_id"])
    outstanding = _outstanding(inv) if inv else 0
    amount = int(payment["amount_paise"])
    alloc = min(amount, outstanding) if outstanding > 0 else 0
    receipt = create_receipt_core(
        firm_id=firm_id,
        data={
            "client_id": payment["client_id"], "customer_id": payment["customer_id"],
            "receipt_date": date.today().isoformat(), "amount_paise": amount,
            "payment_mode": "online", "reference_no": payment.get("provider_payment_id") or str(payment["id"]),
            "notes": f"Online payment via {payment['provider']}",
            "allocations": ([{"sales_invoice_id": payment["invoice_id"], "allocated_paise": alloc}] if alloc > 0 else []),
        },
        actor=_system_actor(payment["provider"]),
        db=db,
    )
    return receipt


def _apply_event(db, payment: dict, event, firm_id: str) -> None:
    # Capture → settle EXACTLY ONCE. The settlement is guarded by an atomic claim:
    # a single conditional UPDATE flips the row to the 'capturing' sentinel only
    # while receipt_id IS NULL and it isn't already being claimed. Postgres
    # serializes concurrent UPDATEs on the row, so a simultaneous duplicate
    # delivery matches zero rows and bails — no second receipt. (Sequential
    # redelivery is also covered by event dedupe + the receipt_id seal.)
    if event.status == CAPTURED and not payment.get("receipt_id"):
        claimed = (db.table("customer_payments")
                   .update({"status": "capturing", "updated_at": _now()})
                   .eq("id", payment["id"]).is_("receipt_id", "null")
                   .neq("status", "capturing").execute().data or [])
        if not claimed:
            return  # another delivery is settling / already settled this payment
        receipt = _settle(db, payment, event)
        db.table("customer_payments").update({
            "status": CAPTURED, "receipt_id": receipt.get("id"), "updated_at": _now(),
        }).eq("id", payment["id"]).execute()
        if payment.get("payment_link_id"):
            db.table("customer_payment_links").update({"status": "paid", "updated_at": _now()}) \
              .eq("id", payment["payment_link_id"]).execute()
        log_event(firm_id, "customer_payment", str(payment["id"]), "captured",
                  new_data={"receipt_id": receipt.get("id"), "amount_paise": payment["amount_paise"]})
        timeline_service.log_timeline_event(
            client_id=payment["client_id"], firm_id=firm_id, financial_year=_current_fy_long(),
            category="accounting", event_type="online_payment_captured",
            title="Online payment received",
            description=f"Online payment of ₹{int(payment['amount_paise']) // 100:,} captured.",
            severity="success", entity_type="customer_payment", entity_id=str(payment["id"]),
            amount_paise=int(payment["amount_paise"]), actor_type="system")
        return
    # Non-capture transitions (created/authorized/failed/refunded) — no accounting.
    if event.status in (FAILED, REFUNDED):
        log_event(firm_id, "customer_payment", str(payment["id"]), event.status,
                  new_data={"event_type": event.event_type})
    db.table("customer_payments").update({"status": event.status, "updated_at": _now()}) \
      .eq("id", payment["id"]).execute()


def process_webhook(db, provider_name: str, headers: dict, raw_body: bytes) -> dict:
    """Verify → dedupe → correlate → transition → (on capture) settle via receipt engine.
    Returns a small status dict; never raises on a bad signature (records + rejects)."""
    try:
        provider = get_provider(provider_name)   # pinned to the configured provider
    except ValueError:
        return {"ok": False, "reason": "unknown_provider"}
    event = provider.process_webhook(headers, raw_body)

    # (I) Signature gate — refuse to act on unverified events.
    if not event.signature_verified:
        _record_event(db, None, event, firm_id=None)
        log_event("", "payment_webhook", event.event_id or "unknown", "signature_failed",
                  new_data={"provider": event.provider, "event_type": event.event_type})
        return {"ok": False, "reason": "invalid_signature"}

    # (I) Replay protection — an event id is ingested at most once.
    if _event_seen(db, event.provider, event.event_id):
        return {"ok": True, "duplicate": True}

    payment = _resolve_payment(db, event)
    if payment is None:
        _record_event(db, None, event, firm_id=None)
        return {"ok": True, "ignored": True}

    firm_id = payment["firm_id"]
    _record_event(db, payment["id"], event, firm_id=firm_id)
    _apply_event(db, payment, event, firm_id)
    return {"ok": True, "status": event.status, "payment_id": str(payment["id"])}
