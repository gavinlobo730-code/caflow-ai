"""Customer receipts — partial receipts, allocation against invoices, outstanding tracking."""
import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from models.common import api_response
from models.invoices import ReceiptIn, ReceiptAllocationsUpdateIn
from core.permissions import rbac
from services.audit_service import log_event
from services.period_validation_service import period_validation_service
from services.timeline_service import timeline_service

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.receipts")


def _current_fy_long() -> str:
    """Return full financial year string like '2025-26' for display/timeline use.
    Indian FY runs April 1 – March 31.
    """
    now = datetime.now(timezone.utc)
    start = now.year if now.month >= 4 else now.year - 1
    return f"{start}-{str(start + 1)[2:]}"

router = APIRouter(prefix="/api/receipts", tags=["receipts"])

# ---------------------------------------------------------------------------
# Mock stores
# ---------------------------------------------------------------------------
MOCK_RECEIPTS: list[dict] = []
MOCK_RECEIPT_ALLOCATIONS: list[dict] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _current_fy() -> str:
    now = datetime.now(timezone.utc)
    if now.month >= 4:
        return f"{str(now.year)[2:]}{str(now.year + 1)[2:]}"
    return f"{str(now.year - 1)[2:]}{str(now.year)[2:]}"


def _next_receipt_seq(db, firm_id: str, client_id: str, fy: str) -> int:
    try:
        resp = (
            db.table("receipts")
            .select("id", count="exact")
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .like("receipt_no", f"RCPT-{fy}-%")
            .execute()
        )
        return (resp.count or 0) + 1
    except Exception:
        return 1


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
    Create a customer receipt with optional invoice allocations.
    - sum(allocations.allocated_paise) must be <= amount_paise (enforced by ReceiptIn)
    - unallocated_paise = amount_paise - sum(allocated)
    - Auto-creates journal entry (Dr Bank / Cr Trade Receivables)
    - Updates invoice status if fully paid
    All amounts in integer paise.
    """
    try:
        data = data.model_dump()
        firm_id      = current_user.get("firm_id")
        client_id    = data["client_id"]
        amount_paise = data["amount_paise"]
        allocations  = data.get("allocations", [])

        # Validate allocation totals — integer arithmetic (also enforced by ReceiptIn)
        total_allocated = sum(int(a.get("allocated_paise", 0)) for a in allocations)
        if total_allocated > amount_paise:
            raise HTTPException(
                status_code=422,
                detail=f"Total allocated ({total_allocated} paise) exceeds receipt amount ({amount_paise} paise)",
            )
        unallocated_paise = amount_paise - total_allocated

        # Validate posting date is not in a locked financial year (migration 020)
        period_validation_service.validate_posting_date(firm_id or "", data["receipt_date"])

        fy = _current_fy()

        if _USE_MOCK:
            seq = len([r for r in MOCK_RECEIPTS if r["client_id"] == client_id]) + 1
            receipt_no = f"RCPT-{fy}-{seq:04d}"
            receipt_id = str(uuid.uuid4())
            receipt = {
                "id":                receipt_id,
                "firm_id":           firm_id,
                "client_id":         client_id,
                "customer_id":       data["customer_id"],
                "receipt_no":        receipt_no,
                "receipt_date":      data["receipt_date"],
                "amount_paise":      amount_paise,
                "unallocated_paise": unallocated_paise,
                "payment_mode":      data.get("payment_mode", ""),
                "reference_no":      data.get("reference_no", ""),
                "notes":             data.get("notes", ""),
                "created_at":        datetime.now(timezone.utc).isoformat(),
            }
            MOCK_RECEIPTS.append(receipt)
            from services.phase2_journal_service import phase2_journal_service
            phase2_journal_service.journal_for_receipt(receipt, firm_id or "", client_id)
            return api_response(True, {**receipt, "allocations": allocations})

        from core.supabase_client import get_supabase
        db = get_supabase()
        seq = _next_receipt_seq(db, firm_id, client_id, fy)
        receipt_no = f"RCPT-{fy}-{seq:04d}"

        receipt_payload = {
            "firm_id":           firm_id,
            "client_id":         client_id,
            "customer_id":       data["customer_id"],
            "receipt_no":        receipt_no,
            "receipt_date":      data["receipt_date"],
            "amount_paise":      amount_paise,
            "unallocated_paise": unallocated_paise,
            "payment_mode":      data.get("payment_mode", ""),
            "reference_no":      data.get("reference_no", ""),
            "notes":             data.get("notes", ""),
            "created_at":        datetime.now(timezone.utc).isoformat(),
        }

        rcpt_resp = db.table("receipts").insert(receipt_payload).execute()
        receipt   = rcpt_resp.data[0] if rcpt_resp.data else receipt_payload
        receipt_id = receipt.get("id", str(uuid.uuid4()))

        # Insert allocations and update invoice statuses
        alloc_payloads = []
        for alloc in allocations:
            inv_id     = alloc.get("sales_invoice_id")
            alloc_amt  = int(alloc.get("allocated_paise", 0))
            if not inv_id or alloc_amt <= 0:
                continue
            alloc_payloads.append({
                "receipt_id":       receipt_id,
                "sales_invoice_id": inv_id,
                "allocated_paise":  alloc_amt,
            })

            # Update invoice paid_paise and status
            inv_resp = (
                db.table("client_sales_invoices")
                .select("total_paise,paid_paise")
                .eq("id", inv_id)
                .limit(1)
                .execute()
            )
            if inv_resp.data:
                inv = inv_resp.data[0]
                new_paid = int(inv.get("paid_paise", 0)) + alloc_amt
                if new_paid > int(inv.get("total_paise", 0)):
                    raise HTTPException(status_code=422, detail=f"Invoice {inv_id}: allocation would exceed invoice total")
                new_status = "paid" if new_paid >= int(inv.get("total_paise", 0)) else "partially_paid"
                db.table("client_sales_invoices").update({
                    "paid_paise": new_paid,
                    "status":     new_status,
                }).eq("id", inv_id).execute()

        if alloc_payloads:
            db.table("receipt_allocations").insert(alloc_payloads).execute()

        # Auto-create journal entry
        from services.phase2_journal_service import phase2_journal_service
        journal_id = phase2_journal_service.journal_for_receipt(
            receipt=receipt,
            firm_id=firm_id or "",
            client_id=client_id,
        )

        log_event(
            firm_id or "", "receipt", receipt_id,
            "create", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=receipt,
        )

        # Record timeline event for received payment
        timeline_service.log_timeline_event(
            client_id=client_id,
            firm_id=firm_id or "",
            financial_year=_current_fy_long(),
            category="accounting",
            event_type="receipt_recorded",
            title=f"Receipt {receipt.get('receipt_no', '')} recorded",
            description=f"Payment of ₹{amount_paise // 100:,} received from customer.",
            severity="success",
            entity_type="receipt",
            entity_id=receipt_id,
            amount_paise=amount_paise,
            actor_id=current_user.get("auth_user_id"),
            actor_name=current_user.get("email"),
        )

        receipt["journal_entry_id"] = journal_id
        receipt["allocations"]      = alloc_payloads
        return api_response(True, receipt)
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

        resp = db.table("receipts").select("amount_paise").eq("id", receipt_id).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Receipt {receipt_id} not found")

        amount_paise    = int(resp.data[0]["amount_paise"])
        total_allocated = sum(int(a.get("allocated_paise", 0)) for a in allocations)
        if total_allocated > amount_paise:
            raise HTTPException(status_code=422, detail="Allocated amount exceeds receipt amount")

        # Delete existing allocations and reinsert
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
            # Update invoice paid_paise
            inv_resp = (
                db.table("client_sales_invoices")
                .select("total_paise,paid_paise")
                .eq("id", inv_id)
                .limit(1)
                .execute()
            )
            if inv_resp.data:
                inv      = inv_resp.data[0]
                new_paid = int(inv.get("paid_paise", 0)) + alloc_amt
                new_status = "paid" if new_paid >= int(inv.get("total_paise", 0)) else "partially_paid"
                db.table("client_sales_invoices").update({
                    "paid_paise": new_paid,
                    "status":     new_status,
                }).eq("id", inv_id).execute()

        if alloc_payloads:
            db.table("receipt_allocations").insert(alloc_payloads).execute()

        # Update unallocated balance
        unallocated = amount_paise - total_allocated
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
