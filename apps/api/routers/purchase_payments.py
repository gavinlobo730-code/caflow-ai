"""Purchase payments — vendor payment recording with auto journal.
Outstanding tracking against purchase bills.
IT Act Section 194C/194I/194J: TDS already deducted at bill stage; payment is net amount.
"""
import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from models.common import api_response
from models.invoices import PurchasePaymentIn
from core.permissions import rbac
from services.audit_service import log_event
from services.period_validation_service import period_validation_service
from services.timeline_service import timeline_service

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.purchase_payments")


def _current_fy_long() -> str:
    """Return full financial year string like '2025-26' for display/timeline use.
    Indian FY runs April 1 – March 31.
    """
    now = datetime.now(timezone.utc)
    start = now.year if now.month >= 4 else now.year - 1
    return f"{start}-{str(start + 1)[2:]}"

router = APIRouter(prefix="/api/purchase-payments", tags=["purchase_payments"])

MOCK_PURCHASE_PAYMENTS: list[dict] = []


def _current_fy() -> str:
    now = datetime.now(timezone.utc)
    if now.month >= 4:
        return f"{str(now.year)[2:]}{str(now.year + 1)[2:]}"
    return f"{str(now.year - 1)[2:]}{str(now.year)[2:]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _next_payment_seq(db, firm_id: str, fy: str) -> int:
    try:
        resp = (
            db.table("purchase_payments")
            .select("id", count="exact")
            .eq("firm_id", firm_id)
            .like("payment_no", f"VPMT-{fy}-%")
            .execute()
        )
        return (resp.count or 0) + 1
    except Exception:
        return 1


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@router.get("")
def list_purchase_payments(
    client_id: str = Query(...),
    vendor_id: Optional[str] = Query(None),
    purchase_bill_id: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, description="Filter by payment_date >= from_date (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="Filter by payment_date <= to_date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    firm_id = current_user["firm_id"]

    if _USE_MOCK:
        results = [p for p in MOCK_PURCHASE_PAYMENTS if p.get("client_id") == client_id and p.get("firm_id") == firm_id]
        if vendor_id:
            results = [p for p in results if p.get("vendor_id") == vendor_id]
        if purchase_bill_id:
            results = [p for p in results if p.get("purchase_bill_id") == purchase_bill_id]
        if from_date:
            results = [p for p in results if p.get("payment_date", "") >= from_date]
        if to_date:
            results = [p for p in results if p.get("payment_date", "") <= to_date]
        results = results[offset:offset + limit]
        return api_response(True, results)

    try:
        db = _get_db()
        query = (
            db.table("purchase_payments")
            .select("*, vendors(name)")
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .order("payment_date", desc=True)
        )
        if vendor_id:
            query = query.eq("vendor_id", vendor_id)
        if purchase_bill_id:
            query = query.eq("purchase_bill_id", purchase_bill_id)
        if from_date:
            query = query.gte("payment_date", from_date)
        if to_date:
            query = query.lte("payment_date", to_date)
        resp = query.range(offset, offset + limit - 1).execute()
        return api_response(True, resp.data or [])
    except Exception as e:
        _logger.error("list_purchase_payments error: %s", e)
        return api_response(False, None, "Unable to complete payment operation. Please try again.")


# ---------------------------------------------------------------------------
# Get single
# ---------------------------------------------------------------------------

@router.get("/{payment_id}")
def get_purchase_payment(
    payment_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    firm_id = current_user["firm_id"]

    if _USE_MOCK:
        payment = next((p for p in MOCK_PURCHASE_PAYMENTS if p["id"] == payment_id and p.get("firm_id") == firm_id), None)
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
        return api_response(True, payment)

    try:
        db = _get_db()
        resp = (
            db.table("purchase_payments")
            .select("*, vendors(name)")
            .eq("id", payment_id)
            .eq("firm_id", firm_id)
            .maybe_single()
            .execute()
        )
        if not resp.data:
            raise HTTPException(status_code=404, detail="Payment not found")
        return api_response(True, resp.data)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_purchase_payment error: %s", e)
        return api_response(False, None, "Unable to complete payment operation. Please try again.")


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@router.post("")
def create_purchase_payment(
    data: PurchasePaymentIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """
    Record a vendor payment. Auto-creates journal entry:
      Dr Trade Payables = amount_paise
      Cr Bank Account   = amount_paise

    TDS was already deducted at the purchase bill stage, so payment is net.
    """
    firm_id = current_user["firm_id"]
    data = data.model_dump()
    client_id = data.get("client_id")
    vendor_id = data.get("vendor_id")
    if not vendor_id:
        raise HTTPException(status_code=422, detail="vendor_id is required")

    amount_paise = int(data.get("amount_paise", 0))
    if amount_paise <= 0:
        raise HTTPException(status_code=422, detail="amount_paise must be positive")

    payment_mode = data.get("payment_mode", "bank")
    payment_date = data.get("payment_date", str(datetime.now(timezone.utc).date()))
    purchase_bill_id = data.get("purchase_bill_id")

    # Validate posting date is not in a locked financial year (migration 020)
    period_validation_service.validate_posting_date(firm_id, payment_date)

    if _USE_MOCK:
        fy = _current_fy()
        payment = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": client_id,
            "vendor_id": vendor_id,
            "purchase_bill_id": purchase_bill_id,
            "payment_no": f"VPMT-{fy}-{len(MOCK_PURCHASE_PAYMENTS) + 1:04d}",
            "payment_date": payment_date,
            "amount_paise": amount_paise,
            "payment_mode": payment_mode,
            "reference_no": data.get("reference_no"),
            "notes": data.get("notes"),
            "journal_entry_id": None,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        MOCK_PURCHASE_PAYMENTS.append(payment)
        return api_response(True, payment)

    try:
        db = _get_db()
        # Business guard: never pay a deactivated vendor.
        _v = (db.table("vendors").select("is_active")
              .eq("id", vendor_id).eq("firm_id", firm_id).limit(1).execute().data)
        if _v and _v[0].get("is_active") is False:
            raise HTTPException(status_code=422, detail="This vendor is inactive. Reactivate the vendor before recording a payment.")
        # ── Multi-Currency (Phase 3): a foreign payment settles a same-currency bill
        # at the bill's FROZEN rate (no realized FX yet). Convert to base up front so
        # the outstanding check, journal and status update all run in base. INR ⇒ no-op.
        _ccy_cols: dict = {}
        if (data.get("currency") or "INR").strip().upper() != "INR":
            _ccy_cols = _resolve_foreign_payment(db, firm_id, client_id, data, current_user)
            amount_paise = int(data["amount_paise"])   # rewritten to base by the resolver
        # OOS-1 fix: a linked bill must belong to THIS payment's firm+client, validated
        # before any payment/journal is created (mirrors the receipt-allocation guard).
        if purchase_bill_id:
            _bill = (db.table("purchase_bills")
                     .select("id, status, net_payable_paise, paid_paise")
                     .eq("id", purchase_bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
                     .limit(1).execute().data) or []
            if not _bill:
                raise HTTPException(status_code=422, detail="Purchase bill is not part of this client's books.")
            # M6: never pay a cancelled bill, and never overpay one (payables can't go
            # negative). Outstanding = net_payable − already-paid.
            _b = _bill[0]
            if (_b.get("status") or "") == "cancelled":
                raise HTTPException(status_code=409, detail="This bill is cancelled and cannot be paid.")
            _outstanding = int(_b.get("net_payable_paise") or 0) - int(_b.get("paid_paise") or 0)
            if amount_paise > _outstanding:
                raise HTTPException(
                    status_code=422,
                    detail=f"Payment (₹{amount_paise/100:,.2f}) exceeds the bill's outstanding "
                           f"(₹{_outstanding/100:,.2f}).")
        fy = _current_fy()
        seq = _next_payment_seq(db, firm_id, fy)
        payment_no = f"VPMT-{fy}-{seq:04d}"

        # Auto-journal
        from services.phase2_journal_service import phase2_journal_service
        payment_dict = {
            "payment_no": payment_no,
            "payment_date": payment_date,
            "amount_paise": amount_paise,
            **_ccy_cols,
        }
        journal_entry_id = phase2_journal_service.journal_for_purchase_payment(
            payment_dict, firm_id, client_id
        )

        payload = {
            "firm_id": firm_id,
            "client_id": client_id,
            "vendor_id": vendor_id,
            "purchase_bill_id": purchase_bill_id,
            "payment_no": payment_no,
            "payment_date": payment_date,
            "amount_paise": amount_paise,
            "payment_mode": payment_mode,
            "reference_no": data.get("reference_no"),
            "notes": data.get("notes"),
            "journal_entry_id": journal_entry_id,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            **_ccy_cols,
        }
        resp = db.table("purchase_payments").insert(payload).execute()
        if not resp.data:
            raise RuntimeError("Insert returned no data")
        payment = resp.data[0]

        # Update purchase bill status if linked
        if purchase_bill_id:
            _update_bill_payment_status(db, firm_id, client_id, purchase_bill_id, amount_paise)

        log_event(
            firm_id, "purchase_payment", payment["id"], "create",
            actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            new_data={"amount_paise": amount_paise, "vendor_id": vendor_id},
        )

        # Record timeline event for vendor payment
        timeline_service.log_timeline_event(
            client_id=client_id,
            firm_id=firm_id,
            financial_year=_current_fy_long(),
            category="accounting",
            event_type="payment_recorded",
            title=f"Vendor Payment {payment_no} recorded",
            description=f"Payment of ₹{amount_paise // 100:,} made to vendor.",
            severity="success",
            entity_type="purchase_payment",
            entity_id=payment["id"],
            amount_paise=amount_paise,
            actor_id=current_user.get("auth_user_id"),
            actor_name=current_user.get("email"),
        )

        return api_response(True, payment)

    except HTTPException:
        raise
    except Exception as e:
        _logger.error("create_purchase_payment error: %s", e)
        return api_response(False, None, "Unable to complete payment operation. Please try again.")


def _resolve_foreign_payment(db, firm_id: str, client_id: str, data: dict, actor: dict) -> dict:
    """Validate + convert a FOREIGN vendor payment to base (INR) at the bill's frozen
    rate (Multi-Currency Phase 3). Mutates data['amount_paise'] to base paise and
    returns the payment's currency columns. Enforces the Phase-3 limits (Task 3/6):
    active policy, supported+active currency, a linked same-currency bill, the bill's
    frozen rate (no cross-rate), and FULL settlement (partial arrives with realized FX)."""
    from decimal import Decimal, InvalidOperation
    from domain.currency.policy import resolve_currency_policy
    from domain.currency.conversion import to_txn_minor
    from domain.currency import currency_service

    ccy = (data.get("currency") or "").strip().upper()
    bill_id = data.get("purchase_bill_id")
    if not bill_id:
        raise HTTPException(status_code=422, detail="A foreign payment must be linked to the purchase bill it settles.")

    firm = (db.table("firms").select("multi_currency_entitled").eq("id", firm_id).limit(1).execute().data or [None])[0]
    client = (db.table("clients").select("functional_currency, multi_currency_enabled").eq("id", client_id).eq("firm_id", firm_id).limit(1).execute().data or [None])[0]
    if not resolve_currency_policy(firm, client).active:
        raise HTTPException(status_code=422, detail="Multi-currency is not enabled for this client.")
    cur = currency_service.get_currency(db, ccy)
    if not cur:
        raise HTTPException(status_code=422, detail=f"Unsupported currency: {ccy}.")
    if not cur.get("is_active", True):
        raise HTTPException(status_code=422, detail=f"Currency {ccy} is inactive.")
    minor = int(cur.get("minor_unit", 2))

    override = None
    if data.get("exchange_rate") is not None:
        try:
            override = Decimal(str(data["exchange_rate"]))
        except (InvalidOperation, ValueError, TypeError):
            raise HTTPException(status_code=422, detail="Invalid exchange rate.")
        if override <= 0:
            raise HTTPException(status_code=422, detail="Exchange rate must be positive.")

    bill = (db.table("purchase_bills")
            .select("txn_currency, exchange_rate, net_payable_paise, paid_paise, debited_paise")
            .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data or [None])[0]
    if not bill:
        raise HTTPException(status_code=422, detail="Purchase bill is not part of this client's books.")
    bill_ccy = (bill.get("txn_currency") or "INR").upper()
    if bill_ccy != ccy:
        raise HTTPException(status_code=422, detail=(
            f"Currency mismatch: payment is {ccy} but bill is billed in {bill_ccy}."))
    bill_rate = Decimal(str(bill.get("exchange_rate") or 1))
    if override is not None and override != bill_rate:
        raise HTTPException(status_code=422, detail=(
            "Settling at a rate different from the bill's booked rate would realise an FX "
            "gain/loss — that arrives in the next phase. Settle at the bill's rate."))
    base_out = int(bill.get("net_payable_paise") or 0) - int(bill.get("paid_paise") or 0) - int(bill.get("debited_paise") or 0)
    foreign_out = to_txn_minor(base_out, bill_rate, minor)
    if int(data.get("amount_paise") or 0) != foreign_out:
        raise HTTPException(status_code=422, detail=(
            "Phase 3 settles a foreign bill in full at its booked rate; partial foreign "
            "settlement arrives with realized FX in the next phase."))
    data["amount_paise"] = base_out
    return {
        "txn_currency": ccy, "exchange_rate": str(bill_rate), "txn_amount": foreign_out,
        "rate_source": "settlement", "rate_type": "booking", "rate_date": data.get("payment_date"),
        "rate_selected_by": (actor or {}).get("id"), "rate_overridden": override is not None,
    }


def _update_bill_payment_status(db, firm_id: str, client_id: str, bill_id: str, paid_paise: int = 0) -> None:
    """Recompute a purchase bill's paid_paise + status from ALL recorded payments so
    the AP sub-ledger reconciles to the GL (H11). The current payment row is already
    inserted, so we sum from the DB (never add it again — the old code double-counted).
    Firm+client scoped so a vendor payment can never read/mutate another tenant's bill."""
    try:
        rows = (
            db.table("purchase_bills")
            .select("net_payable_paise, status")
            .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .limit(1)
            .execute()
        ).data or []
        bill = rows[0] if rows else None
        if not bill:
            return

        payments_resp = (
            db.table("purchase_payments")
            .select("amount_paise")
            .eq("purchase_bill_id", bill_id).eq("firm_id", firm_id)
            .execute()
        )
        total_paid = sum(int(p["amount_paise"]) for p in (payments_resp.data or []))
        net_payable = int(bill["net_payable_paise"])
        new_status = ("paid" if total_paid >= net_payable
                      else "partially_paid" if total_paid > 0
                      else bill.get("status"))

        db.table("purchase_bills").update(
            {"paid_paise": total_paid, "status": new_status, "updated_at": _now_iso()}
        ).eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id).execute()
    except Exception as e:
        _logger.warning("_update_bill_payment_status error: %s", e)
