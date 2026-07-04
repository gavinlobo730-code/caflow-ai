"""
Fee receipt recording — R3.9b fix.

apps/web/app/billing/page.tsx ("Fee Billing," linked from AccountingPanel)
previously wrote directly to fee_receipts and force-set the paired
fee_invoices.status to "Paid" regardless of the amount entered — a partial
receipt marked the whole invoice fully paid, and the receipt itself landed
in a table nothing backend-side ever read.

This service records a receipt against a fee_invoices row and only marks it
Paid once cumulative payments (paid_paise) cover the total — via one atomic
Postgres transaction in production (record_fee_receipt_atomic, migration
172), the same post_journal_atomic/settle_receipt_atomic pattern used for
every other ledger-facing write in this app (R1.6/R2.12).
"""
import os
import uuid
import logging
from typing import Optional

from fastapi import HTTPException

from repositories.invoice_repository import invoice_repo

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.fee_billing")

# In-memory store (mock mode only) — mirrors the MOCK_* convention used
# throughout services/billing_service.py and services/receipt_service.py.
MOCK_FEE_RECEIPTS: list[dict] = []


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


def record_receipt(firm_id: str, invoice_id: str, data: dict) -> dict:
    """Record a fee receipt against invoice_id and update its paid_paise/status.

    data: {receipt_date?, amount_paise, payment_mode?, reference_no?, notes?}
    Raises HTTPException(422) for a non-positive amount, HTTPException(404)
    if the invoice doesn't belong to this firm.
    """
    amount_paise = int(data.get("amount_paise") or 0)
    if amount_paise <= 0:
        raise HTTPException(status_code=422, detail="Receipt amount must be positive.")

    invoice = invoice_repo.find_by_id(invoice_id)
    if not invoice or invoice.get("firm_id") != firm_id:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found.")

    receipt_date = data.get("receipt_date") or invoice_repo.now_iso()[:10]
    payment_mode = data.get("payment_mode") or "NEFT"
    reference_no = data.get("reference_no")
    notes = data.get("notes")

    if _USE_MOCK:
        receipt = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "invoice_id": invoice_id,
            "receipt_date": receipt_date,
            "amount_paise": amount_paise,
            "payment_mode": payment_mode,
            "reference_no": reference_no,
            "notes": notes,
        }
        MOCK_FEE_RECEIPTS.append(receipt)
        total = int(invoice.get("total_paise", 0) or 0)
        new_paid = int(invoice.get("paid_paise", 0) or 0) + amount_paise
        updates: dict = {"paid_paise": new_paid}
        if total > 0 and new_paid >= total:
            updates["status"] = "Paid"
        invoice_repo.update(invoice_id, updates)
        return receipt

    db = _db()
    try:
        result = db.rpc("record_fee_receipt_atomic", {
            "p_firm_id": firm_id,
            "p_invoice_id": invoice_id,
            "p_receipt_date": receipt_date,
            "p_amount_paise": amount_paise,
            "p_payment_mode": payment_mode,
            "p_reference_no": reference_no,
            "p_notes": notes,
        }).execute()
    except Exception as rpc_err:
        # Same PGRST202 / "function ... does not exist" classifier used by
        # phase2_journal_service.py for post_journal_atomic (R2.12 adversarial
        # review) — a bare substring check on the function's own name would
        # misclassify its own RAISE EXCEPTION messages as "RPC not found."
        msg = str(rpc_err).lower()
        if "pgrst202" in msg or ("function" in msg and ("does not exist" in msg or "could not find the function" in msg)):
            raise RuntimeError(
                "record_fee_receipt_atomic RPC not found — migration 172 "
                "(apps/api/migrations/172_fee_receipt_atomic_and_rls.sql) must be "
                "applied to this database before the API is deployed."
            ) from rpc_err
        raise
    receipt_id = result.data
    if not receipt_id:
        raise RuntimeError(f"Failed to record receipt for invoice={invoice_id}")

    return {
        "id": receipt_id,
        "firm_id": firm_id,
        "invoice_id": invoice_id,
        "receipt_date": receipt_date,
        "amount_paise": amount_paise,
        "payment_mode": payment_mode,
        "reference_no": reference_no,
        "notes": notes,
    }
