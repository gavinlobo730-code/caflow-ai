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
from models.invoices import PurchasePaymentIn, PurchasePaymentAllocationsUpdateIn
from models.accounting import JournalReversalIn
from core.permissions import rbac
from services.audit_service import log_event
from services.period_validation_service import period_validation_service
from services.timeline_service import timeline_service
from services import reversal_service
from services import purchase_payment_service

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


def _is_unique_violation(err: Exception) -> bool:
    """True when a Postgres/PostgREST error is a unique-constraint violation
    (23505) — used to recognise a payment_no collision against migration 159's
    UNIQUE (firm_id, payment_no) constraint."""
    s = str(err).lower()
    return "23505" in s or "duplicate key" in s or "already exists" in s


def _insert_payment_or_compensate(db, firm_id: str, payload: dict, journal_entry_id, created_by: Optional[str]) -> dict:
    """Insert the purchase_payments row; both call sites post the vendor-payment
    journal FIRST (Dr Trade Payables / Cr Bank), then insert this row. R2.9/
    migration 159 added a UNIQUE (firm_id, payment_no) constraint that previously
    didn't exist, so this insert can now fail on a genuine numbering collision —
    a failure here must reverse the already-committed journal rather than leave
    a phantom GL entry with no payment row (same class of gap F7/R1.6 fixed for
    receipts, mirrored here via services/receipt_service.py's compensation
    pattern).

    R2.9 adversarial review finding (CONFIRMED): phase2_journal_service._create_journal
    has an idempotency fast-path (_find_existing) keyed only on
    (firm_id, client_id, reference_no, entry_date) — no payment id involved. When two
    payments race to the same auto-generated payment_no (the exact scenario migration
    159's UNIQUE constraint now catches), the LOSING request's journal_for_purchase_payment
    call can match the WINNING request's already-committed journal via that fast-path and
    receive ITS journal_entry_id back. Blindly reversing that journal would corrupt the
    winning payment's already-successful books — so before reversing, confirm no OTHER
    purchase_payments row already claims this exact journal_entry_id.
    """
    try:
        resp = db.table("purchase_payments").insert(payload).execute()
        return (resp.data or [payload])[0]
    except Exception as e:
        if journal_entry_id:
            owned_by_another = (
                db.table("purchase_payments").select("id")
                .eq("journal_entry_id", journal_entry_id)
                .limit(1).execute().data
            )
            if owned_by_another:
                _logger.warning(
                    "R2.9: skipping journal reversal for journal=%s (firm=%s) — it belongs "
                    "to another already-committed payment (%s), not this failed insert; "
                    "reversing it would corrupt that other payment's books.",
                    journal_entry_id, firm_id, owned_by_another[0].get("id"),
                )
            else:
                from services.phase2_journal_service import phase2_journal_service
                try:
                    phase2_journal_service.reverse_entry(
                        db, firm_id, journal_entry_id, str(datetime.now(timezone.utc).date()),
                        narration=f"Compensating reversal — payment {payload.get('payment_no')} insert failed",
                        created_by=created_by,
                    )
                except Exception:
                    _logger.error(
                        "R2.9 compensation FAILED for journal=%s (firm=%s) after a purchase "
                        "payment insert failure — manual reconciliation required, a phantom "
                        "GL entry may remain.", journal_entry_id, firm_id, exc_info=True,
                    )
        if _is_unique_violation(e):
            raise HTTPException(
                status_code=409,
                detail="A payment numbering collision was detected; please retry.",
            ) from e
        raise


def _claim_bill_outstanding(
    db, firm_id: str, client_id: str, bill_id: str, amount_paise: int, net_payable_paise: int,
    max_retries: int = 5,
) -> None:
    """H4: atomically reserve amount_paise against a purchase bill's outstanding
    balance via compare-and-swap on paid_paise, BEFORE any journal/payment is
    created. A plain "read outstanding, then check, then insert" let two
    concurrent payments both read the same stale paid_paise, both pass the
    outstanding check, and both post — overpaying the vendor. The CAS's WHERE
    clause (eq paid_paise=<value just read>) makes the increment atomic: a
    concurrent winner's committed update makes our WHERE clause match zero
    rows, so we re-read the fresh state and re-check outstanding on retry.
    """
    for _ in range(max_retries):
        cur_paid = (
            db.table("purchase_bills").select("paid_paise, debited_paise, credit_note_paise")
            .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .limit(1).execute().data
        ) or []
        if not cur_paid:
            raise HTTPException(status_code=422, detail="Purchase bill is not part of this client's books.")
        raw_paid = cur_paid[0].get("paid_paise")  # CAS guard must match this exact stored value
        paid_paise = int(raw_paid or 0)
        # Debit notes reduce the payable (purchase_bills.debited_paise, set by
        # routers/debit_notes.py) — outstanding that ignored them let a
        # debit-noted bill be paid in full, overpaying the vendor by the
        # debit-note amount; and a bill fully settled by cash + debit note
        # never reached "paid" status. Purchase credit notes (§34(3), the
        # increase-side mirror) raise the ceiling the same way.
        debited_paise = int(cur_paid[0].get("debited_paise") or 0)
        credit_note_paise = int(cur_paid[0].get("credit_note_paise") or 0)
        effective_payable = net_payable_paise + credit_note_paise
        outstanding = effective_payable - paid_paise - debited_paise
        if amount_paise > outstanding:
            raise HTTPException(
                status_code=422,
                detail=f"Payment (₹{amount_paise/100:,.2f}) exceeds the bill's outstanding "
                       f"(₹{outstanding/100:,.2f}).")
        new_paid = paid_paise + amount_paise
        new_status = "paid" if new_paid + debited_paise >= effective_payable else "partially_paid"
        result = (
            db.table("purchase_bills").update({"paid_paise": new_paid, "status": new_status})
            .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("paid_paise", raw_paid)
            .execute()
        )
        if result.data:
            return
        # Lost the race to a concurrent payment on this same bill — retry against
        # the now-current paid_paise rather than accept or silently drop it.
    raise HTTPException(status_code=409, detail="This bill is being paid concurrently; please retry.")


def _rollback_bill_claim(
    db, firm_id: str, client_id: str, bill_id: str, amount_paise: int, net_payable_paise: int,
    max_retries: int = 5,
) -> None:
    """Undo a successful _claim_bill_outstanding reservation after a downstream
    failure (journal/payment insert). Decrements paid_paise by exactly our own
    amount_paise via the same CAS-retry technique — never resets to a captured
    snapshot, since another payment may have claimed on top of ours since."""
    for _ in range(max_retries):
        cur = (
            db.table("purchase_bills").select("paid_paise, debited_paise, credit_note_paise")
            .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .limit(1).execute().data
        ) or []
        if not cur:
            return
        raw_paid = cur[0].get("paid_paise")
        paid_paise = int(raw_paid or 0)
        debited_paise = int(cur[0].get("debited_paise") or 0)
        credit_note_paise = int(cur[0].get("credit_note_paise") or 0)
        effective_payable = net_payable_paise + credit_note_paise
        reverted = paid_paise - amount_paise
        reverted_status = (
            "paid" if reverted + debited_paise >= effective_payable
            else "partially_paid" if reverted > 0 else "received"
        )
        result = (
            db.table("purchase_bills").update({"paid_paise": reverted, "status": reverted_status})
            .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("paid_paise", raw_paid)
            .execute()
        )
        if result.data:
            return
    _logger.error(
        "H4 compensation FAILED for bill=%s (firm=%s) after a purchase payment failure — "
        "manual reconciliation required, paid_paise may be overstated by %d.",
        bill_id, firm_id, amount_paise,
    )


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
        # Ownership + business guard (task #227 audit finding): scope by
        # firm+client (vendors.client_id is NOT NULL — every vendor belongs to
        # exactly one client) and reject when the vendor can't be found in
        # THIS client's books at all, instead of silently proceeding — the old
        # firm-only lookup let a vendor_id from a DIFFERENT client of the same
        # firm, or a nonexistent id, pass straight through to a real payment.
        _v = (db.table("vendors").select("is_active")
              .eq("id", vendor_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data)
        if not _v:
            raise HTTPException(status_code=422, detail="This vendor is not part of this client's books.")
        if _v[0].get("is_active") is False:
            raise HTTPException(status_code=422, detail="This vendor is inactive. Reactivate the vendor before recording a payment.")
        # ── Multi-Currency (Phase 4): a foreign payment runs a dedicated realized-FX
        # path — the bill is relieved at ITS booked rate, cash at the payment's rate,
        # and the difference posts to Realized FX Gain/Loss. INR path below unchanged.
        if (data.get("currency") or "INR").strip().upper() != "INR":
            return api_response(True, _create_foreign_payment(db, firm_id, client_id, data, current_user))
        # OOS-1 fix: a linked bill must belong to THIS payment's firm+client, validated
        # before any payment/journal is created (mirrors the receipt-allocation guard).
        net_payable_paise = 0
        if purchase_bill_id:
            _bill = (db.table("purchase_bills")
                     .select("id, status, net_payable_paise, vendor_id")
                     .eq("id", purchase_bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
                     .limit(1).execute().data) or []
            if not _bill:
                raise HTTPException(status_code=422, detail="Purchase bill is not part of this client's books.")
            if _bill[0].get("vendor_id") != vendor_id:
                raise HTTPException(status_code=422, detail="This bill does not belong to the specified vendor.")
            # M6: never pay a cancelled bill, and never overpay one (payables can't go
            # negative). Outstanding = net_payable − already-paid.
            if (_bill[0].get("status") or "") == "cancelled":
                raise HTTPException(status_code=409, detail="This bill is cancelled and cannot be paid.")
            # task #227 audit finding: a draft bill was never received (no AP
            # journal exists yet) — same class of gap as a draft sales invoice.
            if (_bill[0].get("status") or "") == "draft":
                raise HTTPException(status_code=409, detail="This bill is still a draft and has not been received yet.")
            net_payable_paise = int(_bill[0].get("net_payable_paise") or 0)
            # H4: reserve amount_paise of outstanding atomically BEFORE any journal or
            # payment row is created — see _claim_bill_outstanding for why the previous
            # read-then-check-then-insert let concurrent payments overpay the same bill.
            _claim_bill_outstanding(db, firm_id, client_id, purchase_bill_id, amount_paise, net_payable_paise)

        fy = _current_fy()
        seq = _next_payment_seq(db, firm_id, fy)
        payment_no = f"VPMT-{fy}-{seq:04d}"

        try:
            # Auto-journal
            from services.phase2_journal_service import phase2_journal_service
            # task #102: pre-generated (matching create_receipt_core's convention)
            # so the journal can carry source_type/source_id back to this payment,
            # for reverse_payment / any future source_id-keyed lookup.
            payment_id = str(uuid.uuid4())
            payment_dict = {
                "id": payment_id,
                "payment_no": payment_no,
                "payment_date": payment_date,
                "amount_paise": amount_paise,
            }
            journal_entry_id = phase2_journal_service.journal_for_purchase_payment(
                payment_dict, firm_id, client_id
            )

            payload = {
                "id": payment_id,
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
            }
            payment = _insert_payment_or_compensate(
                db, firm_id, payload, journal_entry_id, current_user.get("id"),
            )
        except Exception:
            if purchase_bill_id:
                _rollback_bill_claim(db, firm_id, client_id, purchase_bill_id, amount_paise, net_payable_paise)
            raise

        # Reconcile paid_paise/status from the ledger of actual payment rows if linked
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


@router.patch("/{payment_id}/allocate")
def update_purchase_payment_allocations(
    payment_id: str,
    data: PurchasePaymentAllocationsUpdateIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """
    Re-allocate a vendor payment's cash across bills — resolves a stranded
    advance (purchase_payments.unallocated_paise, e.g. left over from a
    bank-match settlement or a payment recorded before its bill existed) once
    a bill is available to apply it against, without recording a new payment.
    Mirrors receipts.py's PATCH /{receipt_id}/allocate (the AR side of the
    same gap). Body: {allocations: [{purchase_bill_id, allocated_paise}]}.
    """
    if _USE_MOCK:
        return api_response(True, {
            "payment_id": payment_id,
            "allocations": [a.model_dump() for a in data.allocations],
        })
    try:
        db = _get_db()
        result = purchase_payment_service.update_allocations_core(
            current_user["firm_id"], payment_id,
            [a.model_dump() for a in data.allocations], current_user, db,
        )
        return api_response(True, result)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("update_purchase_payment_allocations: %s", e)
        return api_response(False, None, "Unable to complete payment operation. Please try again.")


def _create_foreign_payment(db, firm_id: str, client_id: str, data: dict, actor: dict) -> dict:
    """Foreign vendor payment with realized FX (Multi-Currency Phase 4). Relieves the
    bill at ITS frozen booking rate (R0); cash at the payment's rate (R1); the
    difference posts to Realized FX Gain/Loss in ONE balanced journal through the
    kernel. Foreign settled is tracked on the bill (paid_txn) so partials never
    drift and the final settlement clears the base exactly. Bill/rate never changed."""
    from decimal import Decimal, InvalidOperation
    from datetime import date as _date
    from domain.currency.policy import resolve_currency_policy, CurrencyPolicy
    from domain.currency.conversion import to_base_minor
    from domain.currency import currency_service, RateNotFound
    from services.phase2_journal_service import phase2_journal_service as K

    ccy = (data.get("currency") or "").strip().upper()
    bill_id = data.get("purchase_bill_id")
    vendor_id = data.get("vendor_id")
    if not bill_id:
        raise HTTPException(status_code=422, detail="A foreign payment must be linked to the purchase bill it settles.")
    payment_date = data.get("payment_date", str(datetime.now(timezone.utc).date()))
    period_validation_service.validate_posting_date(firm_id, payment_date)

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

    overridden = data.get("exchange_rate") is not None
    if overridden:
        try:
            R1 = Decimal(str(data["exchange_rate"]))
        except (InvalidOperation, ValueError, TypeError):
            raise HTTPException(status_code=422, detail="Invalid exchange rate.")
        r1_source = "manual-override"
    else:
        try:
            q = K.exchange_rate_service(db).get_quote(ccy, "INR", _date.fromisoformat(str(payment_date)[:10]), "booking")
        except RateNotFound:
            raise HTTPException(status_code=422, detail=f"No exchange rate available for {ccy}->INR on {payment_date}.")
        R1, r1_source = q.rate, q.source
    if R1 <= 0:
        raise HTTPException(status_code=422, detail="Exchange rate must be positive.")

    bill = (db.table("purchase_bills")
            .select("id, txn_currency, exchange_rate, net_payable_paise, paid_paise, paid_txn, debited_paise, txn_net_payable, status, vendor_id")
            .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data or [None])[0]
    if not bill:
        raise HTTPException(status_code=422, detail="Purchase bill is not part of this client's books.")
    if bill.get("vendor_id") != vendor_id:
        raise HTTPException(status_code=422, detail="This bill does not belong to the specified vendor.")
    if (bill.get("status") or "") == "cancelled":
        raise HTTPException(status_code=409, detail="This bill is cancelled and cannot be paid.")
    # task #227 audit finding: a draft bill was never received (no AP journal
    # exists yet) — same class of gap as a draft sales invoice (finding #1).
    if (bill.get("status") or "") == "draft":
        raise HTTPException(status_code=409, detail="This bill is still a draft and has not been received yet.")
    if (bill.get("txn_currency") or "INR").upper() != ccy:
        raise HTTPException(status_code=422, detail=(
            f"Currency mismatch: payment is {ccy} but bill is billed in {bill.get('txn_currency')}."))
    R0 = Decimal(str(bill.get("exchange_rate") or 1))
    base_out = int(bill.get("net_payable_paise") or 0) - int(bill.get("paid_paise") or 0) - int(bill.get("debited_paise") or 0)
    foreign_out = int(bill.get("txn_net_payable") or 0) - int(bill.get("paid_txn") or 0)
    f = int(data["amount_paise"])
    if f <= 0:
        raise HTTPException(status_code=422, detail="amount_paise must be positive")
    if f > foreign_out:
        raise HTTPException(status_code=422, detail=f"Payment {f} exceeds the bill's outstanding {foreign_out} {ccy}.")
    ap_relieved = base_out if f == foreign_out else to_base_minor(f, R0, minor)
    cash_base = to_base_minor(f, R1, minor)
    fx_diff = ap_relieved - cash_base   # + gain (paid less INR) / − loss (paid more)

    ap_id = K._find_account(db, firm_id, client_id, "%Trade Payable%", system_key="ap")
    bank_id = K._find_account(db, firm_id, client_id, "%Bank%", system_key="bank")
    lines = [
        {"account_id": ap_id, "debit_paise": ap_relieved, "credit_paise": 0,
         "narration": "Trade payable settled at booked rate", "txn_debit": f, "txn_credit": 0},
        {"account_id": bank_id, "debit_paise": 0, "credit_paise": cash_base,
         "narration": "Bank payment (foreign)", "txn_debit": 0, "txn_credit": f},
    ]
    if fx_diff != 0:
        fx_id = K._find_account(db, firm_id, client_id, "%Foreign Exchange%", system_key="fx_realized")
        if fx_diff > 0:
            lines.append({"account_id": fx_id, "debit_paise": 0, "credit_paise": fx_diff,
                          "narration": "Realized FX gain", "txn_debit": 0, "txn_credit": 0})
        else:
            lines.append({"account_id": fx_id, "debit_paise": -fx_diff, "credit_paise": 0,
                          "narration": "Realized FX loss", "txn_debit": 0, "txn_credit": 0})

    fy = _current_fy()
    seq = _next_payment_seq(db, firm_id, fy)
    payment_no = f"VPMT-{fy}-{seq:04d}"
    # task #102: pre-generated so the journal can carry source_type/source_id
    # back to this payment, for reverse_payment / any future source_id lookup.
    payment_id = str(uuid.uuid4())
    entry_id = K._create_journal(
        db=db, firm_id=firm_id, client_id=client_id, entry_date=payment_date,
        reference_no=payment_no, narration=f"Vendor payment {payment_no} (foreign)",
        entry_type="Payment", lines=lines, created_by=(actor or {}).get("id"),
        source_type="purchase_payment", source_id=payment_id,
        txn_currency=ccy, exchange_rate=R1, rate_source=r1_source, rate_type="booking",
        rate_date=str(payment_date)[:10], rate_selected_by=(actor or {}).get("id"),
        rate_overridden=overridden, currency_policy=CurrencyPolicy(active=True, functional_currency="INR"),
    )

    payload = {
        "id": payment_id,
        "firm_id": firm_id, "client_id": client_id, "vendor_id": vendor_id,
        "purchase_bill_id": bill_id, "payment_no": payment_no, "payment_date": payment_date,
        "amount_paise": cash_base, "payment_mode": data.get("payment_mode", "bank"),
        "reference_no": data.get("reference_no"), "notes": data.get("notes"),
        "journal_entry_id": entry_id, "created_at": _now_iso(), "updated_at": _now_iso(),
        "txn_currency": ccy, "exchange_rate": str(R1), "txn_amount": f,
        "rate_source": r1_source, "rate_type": "booking", "rate_date": str(payment_date)[:10],
        "rate_selected_by": (actor or {}).get("id"), "rate_overridden": overridden,
    }
    payment = _insert_payment_or_compensate(
        db, firm_id, payload, entry_id, (actor or {}).get("id"),
    )

    # task #102: this used to blindly overwrite paid_paise/paid_txn/status from
    # the bill read taken at the TOP of this function (before validation, the
    # rate lookup and journal posting all ran) — no CAS guard, no re-read. Two
    # concurrent foreign payments on the same bill both pass the earlier
    # `f > foreign_out` check against the same stale snapshot, both post their
    # journals, and whichever writes here LAST wins outright — the other
    # payment's paid_paise/paid_txn contribution is silently clobbered, not
    # merely overpaid. Mirrors create_foreign_receipt's already-reviewed CAS
    # retry (re-validate against FRESH state on every attempt; a genuine
    # concurrent race surfaces as 422/409, never a silent overwrite).
    for _attempt in range(6):
        cur = (db.table("purchase_bills").select("paid_paise, paid_txn, txn_net_payable")
               .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
               .limit(1).execute().data or [None])[0]
        if not cur:
            break
        raw_paid = cur.get("paid_paise")  # CAS guard must match this exact stored value (possibly NULL)
        old_paid = int(raw_paid or 0)
        old_paid_txn = int(cur.get("paid_txn") or 0)
        fresh_new_paid_txn = old_paid_txn + f
        txn_net_payable = int(cur.get("txn_net_payable") or 0)
        if fresh_new_paid_txn > txn_net_payable:
            raise HTTPException(status_code=422, detail=f"Bill {bill_id}: payment would exceed the bill's outstanding")
        fresh_new_paid = old_paid + ap_relieved
        fresh_status = "paid" if fresh_new_paid_txn >= txn_net_payable else "partially_paid"
        upd = (db.table("purchase_bills")
               .update({"paid_paise": fresh_new_paid, "paid_txn": fresh_new_paid_txn, "status": fresh_status})
               .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
               .eq("paid_paise", raw_paid).execute())
        if upd.data:
            break
    else:
        raise HTTPException(status_code=409, detail=f"Bill {bill_id} is being updated concurrently — please retry.")

    if fx_diff != 0:
        db.table("fx_adjustments").insert({
            "firm_id": firm_id, "client_id": client_id, "kind": "realized",
            "document_type": "purchase_payment", "document_id": payment.get("id"), "currency": ccy,
            "settlement_rate": str(R1), "base_delta_paise": fx_diff,
            "journal_entry_id": entry_id, "rate_source": r1_source, "created_by": (actor or {}).get("id"),
        }).execute()

    log_event(firm_id, "purchase_payment", payment.get("id"), "create",
              actor_id=(actor or {}).get("auth_user_id"), actor_email=(actor or {}).get("email"),
              new_data={"amount_paise": cash_base, "currency": ccy})
    return {**payment, "journal_entry_id": entry_id, "realized_fx_paise": fx_diff}


def _update_bill_payment_status(db, firm_id: str, client_id: str, bill_id: str, paid_paise: int = 0,
                                max_retries: int = 5) -> None:
    """Recompute a purchase bill's paid_paise + status from ALL recorded payments so
    the AP sub-ledger reconciles to the GL (H11). The current payment row is already
    inserted, so we sum from the DB (never add it again — the old code double-counted).
    Firm+client scoped so a vendor payment can never read/mutate another tenant's bill.

    task #102: this used to write the recomputed sum UNCONDITIONALLY, racing with a
    CONCURRENT payment's _claim_bill_outstanding CAS bump on this exact same bill.
    Sequence: P1 claims (bill.paid_paise = X+amt1) -> P2 claims, reading P1's fresh
    total (bill.paid_paise = X+amt1+amt2) -> P1 inserts its payment row -> P1 reaches
    HERE and sums purchase_payments (P2's row isn't inserted yet) = X+amt1, then
    blindly overwrites bill.paid_paise = X+amt1 — silently erasing P2's amt2 that was
    already correctly CAS-claimed. A plain "guard on the column we're about to
    overwrite" CAS doesn't fix this: the new value comes from a DIFFERENT source
    (summing purchase_payments) than the guarded column (purchase_bills.paid_paise),
    so a same-value CAS match doesn't imply the recomputed sum is current. Since
    paid_paise only legitimately increases today (no reversal path decrements it —
    task #151), never write a sum LOWER than what's already there; retry so a
    concurrent claim visible in the guard read but not yet reflected in the payments
    sum converges once that row lands.
    """
    try:
        for _attempt in range(max_retries):
            rows = (
                db.table("purchase_bills")
                .select("paid_paise, net_payable_paise, status, debited_paise, credit_note_paise")
                .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
                .limit(1)
                .execute()
            ).data or []
            bill = rows[0] if rows else None
            if not bill:
                return
            raw_paid = bill.get("paid_paise")  # CAS guard must match this exact stored value

            payments_resp = (
                db.table("purchase_payments")
                .select("amount_paise")
                .eq("purchase_bill_id", bill_id).eq("firm_id", firm_id)
                .execute()
            )
            summed_paid = sum(int(p["amount_paise"]) for p in (payments_resp.data or []))
            # Never regress a concurrently-claimed higher value (see docstring).
            total_paid = max(summed_paid, int(raw_paid or 0))
            # Purchase credit notes (§34(3)) raise what's payable before debit
            # notes/cash settle it.
            net_payable = int(bill["net_payable_paise"]) + int(bill.get("credit_note_paise") or 0)
            # Debit notes settle part of the payable — a bill fully covered by
            # cash + debit note must reach "paid", and the threshold must not
            # demand cash for the debit-noted portion.
            debited = int(bill.get("debited_paise") or 0)
            new_status = ("paid" if total_paid + debited >= net_payable
                          else "partially_paid" if total_paid > 0
                          else bill.get("status"))

            if total_paid == int(raw_paid or 0):
                return   # already reconciled — nothing to write
            result = (
                db.table("purchase_bills").update(
                    {"paid_paise": total_paid, "status": new_status, "updated_at": _now_iso()}
                ).eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("paid_paise", raw_paid).execute()
            )
            if result.data:
                return
            # Lost the race — another write touched paid_paise between our read
            # and write; retry against the now-current state.
        _logger.warning(
            "_update_bill_payment_status: CAS retries exhausted for bill=%s (firm=%s) — "
            "leaving paid_paise as last written by a concurrent claim.", bill_id, firm_id,
        )
    except Exception as e:
        _logger.warning("_update_bill_payment_status error: %s", e)


@router.post("/{payment_id}/reverse")
def reverse_purchase_payment(
    payment_id: str,
    data: JournalReversalIn,
    current_user: dict = Depends(rbac("accounting", "approve")),
):
    """Reverse a vendor payment — Partner only (task #102). Decrements the
    linked bill's paid_paise back down, reverses the posted GL journal
    (append-only), and marks the payment reversed. This is the missing step
    cancel_purchase_bill's "payments applied" guard has always pointed
    callers to."""
    if _USE_MOCK:
        return api_response(True, {"id": payment_id, "reversed": True, "mock": True})
    try:
        db = _get_db()
        result = reversal_service.reverse_payment(
            db, current_user["firm_id"], payment_id, data.reversal_date, created_by=current_user.get("id"),
        )
        log_event(
            current_user.get("firm_id", ""), "purchase_payment", payment_id,
            "reverse", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=result,
        )
        return api_response(True, result)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("reverse_purchase_payment: %s", e)
        return api_response(False, None, "Unable to reverse payment. Please try again.")
