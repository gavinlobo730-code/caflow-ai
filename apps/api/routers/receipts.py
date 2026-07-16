"""Customer receipts — partial receipts, allocation against invoices, outstanding tracking.

The receipt-creation engine lives in services.receipt_service (create_receipt_core);
this router is a thin wrapper over it so that online payments (Phase 4.6) reuse the
identical engine — no duplicated receipt math, no parallel AR.
"""
import os
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from models.common import api_response
from models.invoices import ReceiptIn, ReceiptAllocationsUpdateIn
from core.permissions import rbac
from services.audit_service import log_event
from services import receipt_service
# Re-exported for backward compat — collections_service and tests import these here.
from services.receipt_service import MOCK_RECEIPTS, MOCK_RECEIPT_ALLOCATIONS

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.receipts")

router = APIRouter(prefix="/api/receipts", tags=["receipts"])


def _adjust_invoice_paid(db, firm_id: str, client_id: str, inv_id: str, delta_paise: int) -> None:
    """Apply a signed delta to an invoice's paid_paise and recompute status.
    Integer paise; paid clamped at >= 0. Used to REVERSE then RE-APPLY a receipt's
    allocations on re-allocation so paid_paise is recomputed from scratch and never
    inflated (H3). F1: the lookup AND update are scoped to (firm_id, client_id) so a
    receipt can never read or mutate another firm's/client's invoice."""
    if not inv_id or delta_paise == 0:
        return
    inv_resp = (db.table("client_sales_invoices")
                .select("total_paise,paid_paise,credited_paise,debit_note_paise")
                .eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute())
    if not inv_resp.data:
        return
    inv = inv_resp.data[0]
    # Debit notes (CGST Act §34(3)) raise the ceiling; credit notes settle part
    # of it. The settlement threshold is paid + credited >= (total + debit
    # notes), matching create_receipt_core and the settle_receipt_atomic RPC.
    total = int(inv.get("total_paise", 0) or 0) + int(inv.get("debit_note_paise", 0) or 0)
    credited = int(inv.get("credited_paise", 0) or 0)
    new_paid = int(inv.get("paid_paise", 0) or 0) + delta_paise
    if new_paid < 0:
        new_paid = 0
    status = ("paid" if (total > 0 and new_paid + credited >= total)
              else ("partially_paid" if new_paid > 0 else "issued"))
    db.table("client_sales_invoices").update({"paid_paise": new_paid, "status": status}) \
        .eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id).execute()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/")
def list_receipts(
    client_id: str = Query(..., description="CA client ID — required"),
    customer_id: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, description="Filter by receipt_date >= from_date (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="Filter by receipt_date <= to_date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """List receipts, optionally filtered by customer and date range."""
    try:
        if _USE_MOCK:
            result = [r for r in MOCK_RECEIPTS if r["client_id"] == client_id]
            if customer_id:
                result = [r for r in result if r.get("customer_id") == customer_id]
            if from_date:
                result = [r for r in result if r.get("receipt_date", "") >= from_date]
            if to_date:
                result = [r for r in result if r.get("receipt_date", "") <= to_date]
            result = result[offset:offset + limit]
            return api_response(True, result)

        from core.supabase_client import get_supabase
        db = get_supabase()
        q = db.table("receipts").select("*").eq("firm_id", current_user["firm_id"]).eq("client_id", client_id)
        if customer_id:
            q = q.eq("customer_id", customer_id)
        if from_date:
            q = q.gte("receipt_date", from_date)
        if to_date:
            q = q.lte("receipt_date", to_date)
        resp = q.order("receipt_date", desc=True).range(offset, offset + limit - 1).execute()
        return api_response(True, resp.data or [])
    except Exception as e:
        _logger.error("list_receipts: %s", e)
        return api_response(False, None, "Unable to complete receipt operation. Please try again.")


@router.post("/")
def create_receipt(
    data: ReceiptIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """
    Create a customer receipt with optional invoice allocations. Thin wrapper over
    services.receipt_service.create_receipt_core — the single receipt engine
    (validation → receipt no → AR update → allocations → journal → audit → timeline).
    All amounts in integer paise.
    """
    try:
        db = None
        if not _USE_MOCK:
            from core.supabase_client import get_supabase
            db = get_supabase()
        result = receipt_service.create_receipt_core(
            firm_id=current_user.get("firm_id"),
            data=data.model_dump(),
            actor=current_user,
            db=db,
        )
        return api_response(True, result)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("create_receipt: %s", e)
        return api_response(False, None, "Unable to complete receipt operation. Please try again.")


@router.get("/{receipt_id}")
def get_receipt(
    receipt_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Get a receipt with its allocations."""
    try:
        if _USE_MOCK:
            rcpt = next((r for r in MOCK_RECEIPTS if r["id"] == receipt_id), None)
            if not rcpt:
                raise HTTPException(status_code=404, detail=f"Receipt {receipt_id} not found")
            allocs = [a for a in MOCK_RECEIPT_ALLOCATIONS if a.get("receipt_id") == receipt_id]
            return api_response(True, {**rcpt, "allocations": allocs})

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("receipts").select("*").eq("id", receipt_id).eq("firm_id", current_user["firm_id"]).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Receipt {receipt_id} not found")
        receipt = resp.data[0]
        allocs_resp = db.table("receipt_allocations").select("*").eq("receipt_id", receipt_id).execute()
        receipt["allocations"] = allocs_resp.data or []
        return api_response(True, receipt)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_receipt: %s", e)
        return api_response(False, None, "Unable to complete receipt operation. Please try again.")


@router.patch("/{receipt_id}/allocate")
def update_allocations(
    receipt_id: str,
    data: ReceiptAllocationsUpdateIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """
    Add or update allocations for a receipt.
    Body: {allocations: [{sales_invoice_id, allocated_paise}]}
    Validates total allocated does not exceed receipt amount.
    """
    try:
        allocations = [a.model_dump() for a in data.allocations]

        if _USE_MOCK:
            rcpt = next((r for r in MOCK_RECEIPTS if r["id"] == receipt_id), None)
            if not rcpt:
                raise HTTPException(status_code=404, detail=f"Receipt {receipt_id} not found")
            total_allocated = sum(int(a.get("allocated_paise", 0)) for a in allocations)
            if total_allocated > rcpt["amount_paise"]:
                raise HTTPException(status_code=422, detail="Allocated amount exceeds receipt amount")
            # Update mock allocations
            MOCK_RECEIPT_ALLOCATIONS[:] = [
                a for a in MOCK_RECEIPT_ALLOCATIONS if a.get("receipt_id") != receipt_id
            ]
            for alloc in allocations:
                alloc["receipt_id"] = receipt_id
                MOCK_RECEIPT_ALLOCATIONS.append(alloc)
            return api_response(True, {"receipt_id": receipt_id, "allocations": allocations})

        from core.supabase_client import get_supabase
        db = get_supabase()

        firm_id = current_user.get("firm_id")
        # F1 fix: scope the receipt to the caller's firm — cannot touch another firm's receipt.
        resp = (db.table("receipts").select("amount_paise, tds_paise, client_id")
                .eq("id", receipt_id).eq("firm_id", firm_id).limit(1).execute())
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Receipt {receipt_id} not found")

        receipt_client_id = resp.data[0].get("client_id")
        amount_paise    = int(resp.data[0]["amount_paise"])
        tds_paise       = int(resp.data[0].get("tds_paise") or 0)
        total_allocated = sum(int(a.get("allocated_paise", 0)) for a in allocations)
        # Cap at the SETTLEMENT value (cash + customer-deducted TDS), matching
        # the creation path — a §194J receipt of ₹98,000 cash + ₹2,000 TDS
        # settles ₹1,00,000 of invoices; capping at cash alone silently
        # reopened invoices by the TDS on every re-allocation.
        if total_allocated > amount_paise + tds_paise:
            raise HTTPException(status_code=422, detail="Allocated amount exceeds receipt amount")

        # This receipt's PRIOR allocations (reversed below before re-applying)
        # — also needed per invoice so the over-application check measures the
        # invoice's outstanding as it will be AFTER that reversal.
        prior = (db.table("receipt_allocations").select("sales_invoice_id, allocated_paise")
                 .eq("receipt_id", receipt_id).execute().data) or []
        prior_by_invoice: dict = {}
        for old in prior:
            k = old.get("sales_invoice_id")
            prior_by_invoice[k] = prior_by_invoice.get(k, 0) + int(old.get("allocated_paise", 0) or 0)

        # Requested totals per invoice (duplicate rows summed, mirroring the
        # atomic creation RPC's pre-aggregation).
        requested_by_invoice: dict = {}
        for alloc in allocations:
            inv_id = alloc.get("sales_invoice_id")
            amt = int(alloc.get("allocated_paise", 0) or 0)
            if inv_id and amt > 0:
                requested_by_invoice[inv_id] = requested_by_invoice.get(inv_id, 0) + amt

        # F1: every allocation must target an invoice in THIS receipt's
        # firm+client books; and (H3 follow-up) no allocation may exceed the
        # invoice's live outstanding (total − paid − credited, plus whatever
        # THIS receipt already had on it, since that is reversed first) — the
        # old code had no per-invoice cap at all, so a ₹1,00,000 receipt
        # re-allocated onto a ₹50,000 invoice drove paid_paise to double the
        # invoice total.
        for inv_id, req_amt in requested_by_invoice.items():
            chk = (db.table("client_sales_invoices")
                   .select("id, total_paise, paid_paise, credited_paise, debit_note_paise")
                   .eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", receipt_client_id)
                   .limit(1).execute())
            if not chk.data:
                raise HTTPException(status_code=422, detail=f"Invoice {inv_id} is not part of this client's books.")
            inv = chk.data[0]
            # (total + debit notes) is the true ceiling (CGST Act §34(3)).
            outstanding = (int(inv.get("total_paise") or 0) + int(inv.get("debit_note_paise") or 0)
                           - int(inv.get("paid_paise") or 0)
                           - int(inv.get("credited_paise") or 0)
                           + prior_by_invoice.get(inv_id, 0))
            if req_amt > outstanding:
                raise HTTPException(
                    status_code=422,
                    detail=f"Allocation (₹{req_amt/100:,.2f}) exceeds the invoice's outstanding (₹{max(outstanding,0)/100:,.2f}).")

        # H3 fix: reverse this receipt's PRIOR allocations before re-applying, so
        # invoice.paid_paise is recomputed from scratch and never inflated by
        # repeated re-allocation. (Previously the old allocation rows were deleted
        # but their amounts were never subtracted from paid_paise.)
        for old in prior:
            _adjust_invoice_paid(db, firm_id, receipt_client_id, old.get("sales_invoice_id"), -int(old.get("allocated_paise", 0) or 0))
        db.table("receipt_allocations").delete().eq("receipt_id", receipt_id).execute()

        alloc_payloads = []
        for alloc in allocations:
            inv_id    = alloc.get("sales_invoice_id")
            alloc_amt = int(alloc.get("allocated_paise", 0))
            if not inv_id or alloc_amt <= 0:
                continue
            alloc_payloads.append({
                "receipt_id":       receipt_id,
                "sales_invoice_id": inv_id,
                "allocated_paise":  alloc_amt,
            })
            _adjust_invoice_paid(db, firm_id, receipt_client_id, inv_id, alloc_amt)

        if alloc_payloads:
            db.table("receipt_allocations").insert(alloc_payloads).execute()

        # Update unallocated balance — settlement basis (cash + TDS), matching
        # create_receipt_core's "unallocated_paise = settlement - allocated".
        unallocated = amount_paise + tds_paise - total_allocated
        db.table("receipts").update({"unallocated_paise": unallocated}).eq("id", receipt_id).execute()

        log_event(
            current_user.get("firm_id", ""), "receipt", receipt_id,
            "update", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            new_data={"allocations": alloc_payloads, "unallocated_paise": unallocated},
        )
        return api_response(True, {"receipt_id": receipt_id, "allocations": alloc_payloads, "unallocated_paise": unallocated})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("update_allocations: %s", e)
        return api_response(False, None, "Unable to complete receipt operation. Please try again.")
