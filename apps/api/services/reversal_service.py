"""Reverse-receipt / reverse-payment cascades (task #102).

cancel_invoice / cancel_purchase_bill refuse to cancel a document once a
receipt/payment has been applied to it ("Reverse the receipt(s)/payment(s)
first") — this module is that missing reversal path. Each function:
  1. undoes the sub-ledger effect on every invoice/bill the receipt/payment
     touched (CAS-guarded, mirrors purchase_payments._claim_bill_outstanding),
  2. reverses the posted GL journal through the kernel (append-only —
     phase2_journal_service.reverse_entry), and
  3. marks the receipt/payment row is_reversed (append-only — the row itself
     is never deleted, preserving audit history; migration 215).

A reversed receipt's receipt_allocations rows are marked is_voided rather
than deleted, for the same audit-history reason — and so
customer_statement_service's AR-relief calculation (task #102) stops
counting them.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from services.period_validation_service import period_validation_service

_logger = logging.getLogger("caflow.reversal")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rollback_invoice_paid(db, firm_id: str, client_id: str, invoice_id: str, amount_paise: int,
                           max_retries: int = 5) -> None:
    """CAS-decrement a sales invoice's paid_paise by exactly amount_paise (an
    allocation being undone) and recompute status. Mirrors
    purchase_payments._rollback_bill_claim, but raises on CAS exhaustion
    (unlike that compensation-only helper) — a user-initiated reversal must
    not silently no-op the sub-ledger side."""
    for _attempt in range(max_retries):
        rows = (db.table("client_sales_invoices")
                .select("total_paise, paid_paise, credited_paise, debit_note_paise")
                .eq("id", invoice_id).eq("firm_id", firm_id).eq("client_id", client_id)
                .limit(1).execute().data or [])
        if not rows:
            return
        inv = rows[0]
        raw_paid = inv.get("paid_paise")
        total = int(inv.get("total_paise") or 0) + int(inv.get("debit_note_paise") or 0)
        credited = int(inv.get("credited_paise") or 0)
        reverted = max(int(raw_paid or 0) - amount_paise, 0)
        status = ("paid" if (total > 0 and reverted + credited >= total)
                  else "partially_paid" if reverted > 0 else "issued")
        result = (db.table("client_sales_invoices").update({"paid_paise": reverted, "status": status})
                  .eq("id", invoice_id).eq("firm_id", firm_id).eq("client_id", client_id)
                  .eq("paid_paise", raw_paid).execute())
        if result.data:
            return
    raise HTTPException(status_code=409, detail=f"Invoice {invoice_id} is being updated concurrently — please retry.")


def _rollback_bill_paid(db, firm_id: str, client_id: str, bill_id: str, amount_paise: int,
                        max_retries: int = 5) -> None:
    """CAS-decrement a purchase bill's paid_paise by exactly amount_paise (the
    payment's true AP relief being undone) and recompute status. Same shape as
    _rollback_invoice_paid / purchase_payments._rollback_bill_claim."""
    for _attempt in range(max_retries):
        rows = (db.table("purchase_bills")
                .select("net_payable_paise, paid_paise, credit_note_paise, debited_paise")
                .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
                .limit(1).execute().data or [])
        if not rows:
            return
        bill = rows[0]
        raw_paid = bill.get("paid_paise")
        effective_payable = int(bill.get("net_payable_paise") or 0) + int(bill.get("credit_note_paise") or 0)
        debited = int(bill.get("debited_paise") or 0)
        reverted = max(int(raw_paid or 0) - amount_paise, 0)
        status = ("paid" if reverted + debited >= effective_payable
                  else "partially_paid" if reverted > 0 else "received")
        result = (db.table("purchase_bills").update({"paid_paise": reverted, "status": status})
                  .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
                  .eq("paid_paise", raw_paid).execute())
        if result.data:
            return
    raise HTTPException(status_code=409, detail=f"Bill {bill_id} is being updated concurrently — please retry.")


def _payment_ap_relief(db, firm_id: str, client_id: str, payment: dict) -> int:
    """A payment's TRUE AP relief — amount_paise for a domestic payment; for a
    foreign payment, amount_paise (the CASH-rate total) is NOT what was debited
    from AP (the journal debits AP at the bill's frozen BOOKED rate) — the
    correction is fx_adjustments.base_delta_paise, exactly as
    vendor_statement_service derives it (task #102)."""
    amount = int(payment.get("amount_paise") or 0)
    fx_rows = (db.table("fx_adjustments").select("base_delta_paise")
               .eq("firm_id", firm_id).eq("client_id", client_id)
               .eq("document_type", "purchase_payment").eq("document_id", payment["id"])
               .execute().data or [])
    fx_delta = sum(int(r.get("base_delta_paise") or 0) for r in fx_rows)
    return amount + fx_delta


def reverse_receipt(db, firm_id: str, receipt_id: str, reversal_date: str,
                    created_by: Optional[str] = None) -> dict:
    """Undo a customer receipt: decrement every allocated invoice's paid_paise
    back down (CAS), void the receipt_allocations rows, reverse the posted
    journal (append-only, through the kernel), and mark the receipt reversed.
    Firm-scoped lookup (mirrors phase2_journal_service.reverse_entry) —
    client_id is read from the receipt row itself, not supplied by the caller.
    Raises HTTPException: 404 (not found in firm), 422 (already reversed / no
    journal to reverse), 409 (concurrent update / journal already reversed
    elsewhere)."""
    from services.phase2_journal_service import phase2_journal_service

    rows = (db.table("receipts").select("*")
            .eq("id", receipt_id).eq("firm_id", firm_id)
            .limit(1).execute().data or [])
    receipt = rows[0] if rows else None
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    if receipt.get("is_reversed"):
        raise HTTPException(status_code=422, detail="This receipt has already been reversed")
    client_id = receipt["client_id"]

    period_validation_service.validate_posting_date(firm_id or "", reversal_date)

    # Python-side is_voided filter (not .eq()) — a row lacking the key
    # (impossible on the real NOT NULL DEFAULT false column, but common in
    # test doubles / any allocation inserted before migration 215) must be
    # treated as not-voided, not silently excluded (task #145/#148's lesson).
    _allocs = (db.table("receipt_allocations").select("*")
               .eq("receipt_id", receipt_id).execute().data or [])
    allocations = [a for a in _allocs if not a.get("is_voided")]
    for alloc in allocations:
        inv_id = alloc.get("sales_invoice_id")
        amt = int(alloc.get("allocated_paise") or 0)
        if inv_id and amt > 0:
            _rollback_invoice_paid(db, firm_id, client_id, inv_id, amt)
    if allocations:
        db.table("receipt_allocations").update({"is_voided": True}).eq("receipt_id", receipt_id).execute()

    journal_id = receipt.get("journal_entry_id")
    if not journal_id:
        raise HTTPException(status_code=422, detail="No posted journal found for this receipt to reverse.")
    phase2_journal_service.reverse_entry(
        db, firm_id, journal_id, reversal_date,
        narration=f"Reversal of receipt {receipt.get('receipt_no') or receipt_id}",
        created_by=created_by,
    )

    db.table("receipts").update({"is_reversed": True, "updated_at": _now()}).eq("id", receipt_id).execute()

    _logger.info("Reversed receipt %s (firm=%s client=%s), %d allocation(s) undone",
                receipt_id, firm_id, client_id, len(allocations))
    return {"id": receipt_id, "reversed": True, "invoices_adjusted": len(allocations), "journal_reversed": journal_id}


def reverse_payment(db, firm_id: str, payment_id: str, reversal_date: str,
                    created_by: Optional[str] = None) -> dict:
    """Undo a vendor payment: decrement the linked bill's paid_paise back down
    (CAS, using the payment's TRUE AP relief — booked-rate for a foreign
    payment, not its cash-rate amount_paise), reverse the posted journal, and
    mark the payment reversed. Firm-scoped lookup, client_id read from the
    payment row itself. Raises HTTPException: 404, 422, 409 — same shape as
    reverse_receipt."""
    from services.phase2_journal_service import phase2_journal_service

    rows = (db.table("purchase_payments").select("*")
            .eq("id", payment_id).eq("firm_id", firm_id)
            .limit(1).execute().data or [])
    payment = rows[0] if rows else None
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.get("is_reversed"):
        raise HTTPException(status_code=422, detail="This payment has already been reversed")
    client_id = payment["client_id"]

    period_validation_service.validate_posting_date(firm_id or "", reversal_date)

    bill_id = payment.get("purchase_bill_id")
    if bill_id:
        ap_relief = _payment_ap_relief(db, firm_id, client_id, payment)
        if ap_relief > 0:
            _rollback_bill_paid(db, firm_id, client_id, bill_id, ap_relief)

    journal_id = payment.get("journal_entry_id")
    if not journal_id:
        raise HTTPException(status_code=422, detail="No posted journal found for this payment to reverse.")
    phase2_journal_service.reverse_entry(
        db, firm_id, journal_id, reversal_date,
        narration=f"Reversal of payment {payment.get('payment_no') or payment_id}",
        created_by=created_by,
    )

    db.table("purchase_payments").update({"is_reversed": True, "updated_at": _now()}).eq("id", payment_id).execute()

    _logger.info("Reversed payment %s (firm=%s client=%s), bill=%s adjusted",
                payment_id, firm_id, client_id, bill_id)
    return {"id": payment_id, "reversed": True, "bill_adjusted": bill_id, "journal_reversed": journal_id}
