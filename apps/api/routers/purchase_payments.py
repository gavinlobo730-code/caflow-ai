"""Purchase payments — vendor payment recording with auto journal.
Outstanding tracking against purchase bills.
IT Act Section 194C/194I/194J/195: the charge falls at the time of CREDIT to the
payee's account or of PAYMENT, WHICHEVER IS EARLIER. A payment against a bill was
already charged when the bill was booked, so it is net. An ADVANCE — this table's
purchase_bill_id is nullable precisely to support one (migration 050) — is the
earlier event, and withholds here. services/vendor_tds.py decides how much.
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
from core.exceptions import document_failure_detail
from core.permissions import rbac
from core.authz import assert_client_access, can_access_client
from domain.accounting.payment_account import (
    stamp as _stamp_posting_account,
    stamp_all as _stamp_posting_accounts,
)
from services.audit_service import log_event
from services.period_validation_service import period_validation_service
from services.timeline_service import timeline_service
from services import tds_register_service
from services import reversal_service
from services import named_row_ownership
from services import purchase_payment_service
from services.numbering import sequence_after
from core.ist_clock import fy_code, ist_fy_label, ist_today
from domain.money_sentence import rupee_text, rupee_whole_text
from core import db_provider
from core.query_day import query_day

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.purchase_payments")



router = APIRouter(prefix="/api/purchase-payments", tags=["purchase_payments"])

MOCK_PURCHASE_PAYMENTS: list[dict] = []




def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_get_db = db_provider.request_db


def _assert_payment_scope(current_user: dict, payment_id: str) -> dict:
    """Resolve payment_id to its row and verify the caller's client-assignment
    scope. One fixed "Payment not found" message covers both a missing row
    and one outside the caller's assigned book (message-oracle), matching
    the pre-existing text every handler here already used."""
    if _USE_MOCK:
        payment = next(
            (p for p in MOCK_PURCHASE_PAYMENTS if p["id"] == payment_id and p.get("firm_id") == current_user.get("firm_id")),
            None,
        )
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
        # The mock branch checked the firm but NOT the assignment, diverging
        # from the real branch below — and _USE_MOCK is the mode the in-memory
        # test run uses, so no test could catch the divergence.
        if not can_access_client(current_user, payment.get("client_id")):
            raise HTTPException(status_code=404, detail="Payment not found")
        return payment

    db = _get_db()
    resp = (
        db.table("purchase_payments")
        .select("*, vendors(name)")
        .eq("id", payment_id)
        .eq("firm_id", current_user["firm_id"])
        .maybe_single()
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Payment not found")
    payment = resp.data
    if not can_access_client(current_user, payment.get("client_id")):
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


# ---------------------------------------------------------------------------
# Which payments settled ONE bill — and both shapes count (PUR-22)
# ---------------------------------------------------------------------------

def _allocations_for_bill(db, purchase_bill_id: str) -> dict:
    """{purchase_payment_id: allocated_paise} for one bill, voided rows out.

    A voided row is a reversed payment's allocation
    (`reversal_service.reverse_payment` sets `is_voided` rather than deleting),
    and the filter is applied in PYTHON rather than as `.eq("is_voided", False)`
    because a row that predates the column, or one whose value is NULL, must
    read as NOT voided — the same guard reverse_payment itself carries, and the
    lesson of tasks #145/#148.
    """
    rows = (db.table("purchase_payment_allocations")
            .select("purchase_payment_id, allocated_paise, is_voided")
            .eq("purchase_bill_id", purchase_bill_id)
            .execute().data) or []
    out: dict = {}
    for r in rows:
        if r.get("is_voided"):
            continue
        pid = r.get("purchase_payment_id")
        if pid:
            out[pid] = out.get(pid, 0) + int(r.get("allocated_paise") or 0)
    return out


def _settles_bill(payment: dict, purchase_bill_id: str) -> bool:
    """Mock-mode twin of the query above: the legacy FK, or an allocation."""
    if payment.get("purchase_bill_id") == purchase_bill_id:
        return True
    return any(a.get("purchase_bill_id") == purchase_bill_id
               and not a.get("is_voided")
               for a in (payment.get("allocations") or []))


def _with_allocated_to(payment: dict, purchase_bill_id: str,
                       allocated: Optional[dict] = None) -> dict:
    """Stamp what this payment put against THIS bill.

    `amount_paise` is the whole payment and stops being the bill's figure the
    moment one payment settles several. A legacy single-bill payment allocated
    all of itself (the payment function refuses one that settles less).
    """
    if payment.get("purchase_bill_id") == purchase_bill_id:
        amt = int(payment.get("amount_paise") or 0)
    elif allocated is not None:
        amt = int(allocated.get(payment.get("id"), 0))
    else:
        amt = sum(int(a.get("allocated_paise") or 0)
                  for a in (payment.get("allocations") or [])
                  if a.get("purchase_bill_id") == purchase_bill_id
                  and not a.get("is_voided"))
    return {**payment, "allocated_to_bill_paise": amt}


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
    assert_client_access(current_user, client_id)
    firm_id = current_user["firm_id"]

    from_date = query_day(from_date, "from_date")
    to_date = query_day(to_date, "to_date")
    if _USE_MOCK:
        results = [p for p in MOCK_PURCHASE_PAYMENTS if p.get("client_id") == client_id and p.get("firm_id") == firm_id]
        if vendor_id:
            results = [p for p in results if p.get("vendor_id") == vendor_id]
        if purchase_bill_id:
            results = [_with_allocated_to(p, purchase_bill_id) for p in results
                       if _settles_bill(p, purchase_bill_id)]
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
        allocated_to_bill: dict = {}
        if purchase_bill_id:
            # A BILL'S PAYMENTS ARE BOTH SHAPES (PUR-22). The legacy single-bill
            # payment carries `purchase_bill_id`; a payment that settled this
            # bill among several carries a `purchase_payment_allocations` row
            # instead and this column is NULL. Filtering on the column alone
            # showed the bill as unpaid-by-anything while its `paid_paise` said
            # otherwise — and "no payments" reads as a missing record, not as a
            # query that could not see one.
            allocated_to_bill = _allocations_for_bill(db, purchase_bill_id)
            ids = list(allocated_to_bill)
            if ids:
                # PostgREST `or` — quoting each id keeps a comma-free UUID safe
                # and is what the client builds for an in-list anyway.
                quoted = ",".join(f'"{i}"' for i in ids)
                query = query.or_(
                    f"purchase_bill_id.eq.{purchase_bill_id},id.in.({quoted})")
            else:
                query = query.eq("purchase_bill_id", purchase_bill_id)
        if from_date:
            query = query.gte("payment_date", from_date)
        if to_date:
            query = query.lte("payment_date", to_date)
        resp = query.range(offset, offset + limit - 1).execute()
        rows = resp.data or []
        if purchase_bill_id:
            # WHAT THIS PAYMENT PUT AGAINST THIS BILL, which is not
            # `amount_paise` once one payment settles several: a Rs 4,50,000
            # NEFT listed against a Rs 50,000 bill without this reads as a
            # gross overpayment.
            rows = [_with_allocated_to(r, purchase_bill_id, allocated_to_bill)
                    for r in rows]
        return api_response(True, _stamp_posting_accounts(rows))
    except Exception as e:
        _logger.error("list_purchase_payments error: %s", e)
        return api_response(False, None,
                            document_failure_detail(e, action="complete the payment"))


# ---------------------------------------------------------------------------
# Get single
# ---------------------------------------------------------------------------

@router.get("/{payment_id}")
def get_purchase_payment(
    payment_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    try:
        payment = _assert_payment_scope(current_user, payment_id)
        return api_response(True, _stamp_posting_account(payment))
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_purchase_payment error: %s", e)
        return api_response(False, None,
                            document_failure_detail(e, action="complete the payment"))


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def _vendor_and_account_of_the_client(db, firm_id: str, client_id: str, vendor_id: str, bank_account_id) -> dict:
    """The vendor row (active, and in THIS client's books) and the check that the account the money is paid from is this client's too.

    The vendor lookup is scoped by firm AND client and `select("*")`: an advance withholds, and the section, the PAN, the residency and
    the §195 paperwork all decide how much (services/vendor_tds.VENDOR_FIELDS_THAT_DECIDE_WITHHOLDING). The bank account is asked
    because the posting resolves it by firm alone (POST-A-350)."""
    _v = (db.table("vendors").select("*")
          .eq("id", vendor_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data)
    if not _v:
        raise HTTPException(status_code=422, detail="This vendor is not part of this client's books.")
    if _v[0].get("is_active") is False:
        raise HTTPException(status_code=422, detail="This vendor is inactive. Reactivate the vendor before recording a payment.")
    named_row_ownership.bank_account_is_the_clients(db, firm_id, client_id, bank_account_id)
    return _v[0]


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
    assert_client_access(current_user, client_id)
    vendor_id = data.get("vendor_id")
    if not vendor_id:
        raise HTTPException(status_code=422, detail="vendor_id is required")

    amount_paise = int(data.get("amount_paise", 0))
    if amount_paise <= 0:
        raise HTTPException(status_code=422, detail="amount_paise must be positive")

    payment_mode = data.get("payment_mode", "bank")
    payment_date = data.get("payment_date", str(ist_today()))
    purchase_bill_id = data.get("purchase_bill_id")
    allocations = data.get("allocations") or []

    # ── ONE PAYMENT, SEVERAL BILLS (PUR-22) ─────────────────────────────────
    # A practice settles a month's supplier bills with one NEFT.
    # `purchase_payment_service.create_payment_core` has done exactly that
    # since migration 226 (every allocation checked against what is left of
    # its bill before anything is written, and the entry, the payment, the
    # bills and the allocations written in one database transaction since
    # migration 784) — and until PUR-22 its only caller was the bank match
    # queue. From the Purchases screen the CA had to record six
    # payments against one bank line (six fabricated references, six journal
    # entries) or one unallocated payment that left all six bills showing as
    # outstanding in the AP ageing.
    #
    # The single-bill SHAPE below is kept and is still what a single-bill
    # request stores. That is deliberate, and the reason is
    # `reversal_service.reverse_payment`: it branches on
    # `purchase_payments.purchase_bill_id`, rolling the bill back by the
    # payment's whole AP relief where that column is set and by each
    # allocation's own amount where it is NULL. So the column says WHICH SHAPE
    # this payment is, not merely which bill it happened to pay — writing it
    # from the allocation path would send a PARTLY allocated payment down the
    # legacy branch and roll back more than the payment ever settled.
    if allocations and purchase_bill_id:
        raise HTTPException(
            status_code=422,
            detail="Send either purchase_bill_id or allocations, not both — "
                   "they are two shapes of the same fact.")

    # Validate posting date is not in a locked financial year (migration 020)
    period_validation_service.validate_posting_date(firm_id, payment_date)

    if _USE_MOCK:
        # The FY of the NUMBER comes from the DOCUMENT'S OWN DATE, not from
        # today (SALES-24) — see core.ist_clock.fy_code.
        fy = fy_code(payment_date)
        payment = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": client_id,
            "vendor_id": vendor_id,
            "purchase_bill_id": purchase_bill_id,
            "payment_no": "VPMT-{}-{:04d}".format(fy, sequence_after(
                (p.get("payment_no") for p in MOCK_PURCHASE_PAYMENTS), f"VPMT-{fy}-")),
            "payment_date": payment_date,
            "amount_paise": amount_paise,
            "payment_mode": payment_mode,
            "reference_no": data.get("reference_no"),
            "notes": data.get("notes"),
            "journal_entry_id": None,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        # `unallocated_paise` is what this payment has NOT discharged — the
        # figure the AP ageing's advances section and `update_allocations_core`
        # both read. Computed the same way create_payment_core computes it, so
        # mock mode and the real path agree about what an advance is.
        _allocated = sum(int(a.get("allocated_paise") or 0) for a in allocations)
        if _allocated > amount_paise:
            raise HTTPException(
                status_code=422,
                detail=f"Total allocated ({rupee_text(_allocated)}) exceeds payment "
                       f"amount ({rupee_text(amount_paise)}).")
        payment["unallocated_paise"] = (
            0 if purchase_bill_id else amount_paise - _allocated)
        if allocations:
            payment["allocations"] = [dict(a) for a in allocations]
        MOCK_PURCHASE_PAYMENTS.append(payment)
        return api_response(True, _stamp_posting_account(dict(payment)))

    try:
        db = _get_db()
        # Ownership + business guard (task #227 audit finding): scope by
        # firm+client (vendors.client_id is NOT NULL — every vendor belongs to
        # exactly one client) and reject when the vendor can't be found in
        # THIS client's books at all, instead of silently proceeding — the old
        # firm-only lookup let a vendor_id from a DIFFERENT client of the same
        # firm, or a nonexistent id, pass straight through to a real payment.
        # select("*") rather than is_active alone: an advance withholds, and the
        # section, the PAN, the residency and the §195 paperwork all decide how
        # much (services/vendor_tds.VENDOR_FIELDS_THAT_DECIDE_WITHHOLDING). The
        # bill path resolves its vendor the same way.
        vendor = _vendor_and_account_of_the_client(db, firm_id, client_id, vendor_id, data.get("bank_account_id"))
        # PUR-22: from here the multi-bill engine owns everything — its own
        # foreign-currency dispatch and the one database transaction that
        # settles every bill. It repeats the vendor lookup above and that is cheap;
        # doing it here first keeps "this vendor is not part of this client's
        # books" a single sentence whichever shape the request took.
        if allocations:
            _made = purchase_payment_service.create_payment_core(
                firm_id, data,
                {"id": current_user.get("id"),
                 "auth_user_id": current_user.get("auth_user_id"),
                 "email": current_user.get("email")},
                db,
            )
            # D14 — see the identical note in routers/receipts.create_receipt.
            return api_response(
                True,
                _stamp_posting_account(_made) if isinstance(_made, dict) else _made)
        # ── Multi-Currency (Phase 4): a foreign payment runs a dedicated realized-FX
        # path — the bill is relieved at ITS booked rate, cash at the payment's rate,
        # and the difference posts to Realized FX Gain/Loss. INR path below unchanged.
        if (data.get("currency") or "INR").strip().upper() != "INR":
            return api_response(True, _create_foreign_payment(db, firm_id, client_id, data, current_user))
        # ONE TRANSACTION (POST-A-575, migration 784). The bill's own checks, the tax withheld on an advance, and the entry, the
        # payment and the bill's paid amount written together or not at all, are `purchase_payment_service.create_single_bill_payment`.
        # This route used to reserve the bill's outstanding, post the entry, insert the payment, give the reservation back on a
        # failure and then recompute the bill from its payments, each a separate statement.
        payment, tds_cols = purchase_payment_service.create_single_bill_payment(
            firm_id, client_id,
            {**data, "vendor_id": vendor_id, "amount_paise": amount_paise, "payment_date": payment_date, "payment_mode": payment_mode},
            {"id": current_user.get("id"), "auth_user_id": current_user.get("auth_user_id"), "email": current_user.get("email")},
            db, vendor)
        payment_no = payment["payment_no"]

        # THE REGISTER, OR THE DEDUCTION IS INVISIBLE TO COMPLIANCE. A tds row
        # that exists only in the GL has no challan to pay by the 7th (Rule 30)
        # and no deductee line to assemble 26Q/27Q from (Rule 31A). Never raises
        # — a payment that posted correctly must not be rolled back because its
        # register row could not be written.
        register = tds_register_service.sync_for_payment(
            db, firm_id, client_id, {**payment, **tds_cols}, vendor)
        if register.get("statutory_gaps"):
            payment = {**payment, "statutory_gaps": register["statutory_gaps"],
                       "gap_details": register.get("gap_details")}
        if tds_cols.get("_tds_why"):
            payment = {**payment, "tds_why": tds_cols["_tds_why"]}

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
            financial_year=ist_fy_label(payment_date),
            category="accounting",
            event_type="payment_recorded",
            title=f"Vendor Payment {payment_no} recorded",
            description=f"Payment of {rupee_whole_text(amount_paise)} made to vendor.",
            severity="success",
            entity_type="purchase_payment",
            entity_id=payment["id"],
            amount_paise=amount_paise,
            actor_id=current_user.get("auth_user_id"),
            actor_name=current_user.get("email"),
        )

        # D14 — the single-bill INR path's own confirmation.
        return api_response(True, _stamp_posting_account(payment))

    except HTTPException:
        raise
    except Exception as e:
        _logger.error("create_purchase_payment error: %s", e)
        return api_response(False, None,
                            document_failure_detail(e, action="complete the payment"))


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
        return api_response(False, None,
                            document_failure_detail(e, action="complete the payment"))


def _create_foreign_payment(db, firm_id: str, client_id: str, data: dict, actor: dict) -> dict:
    """Foreign vendor payment with realized FX (Multi-Currency Phase 4), for the ONE bill it names. Relieves the bill at ITS frozen
    booking rate (R0); cash at the payment's rate (R1); the difference posts to Realized FX Gain/Loss in ONE balanced journal. Foreign
    settled is tracked on the bill (paid_txn) so partials never drift and the final settlement clears the base exactly. Bill/rate
    never changed. The entry, the payment, the bill's two paid amounts and the record of the realised difference are one database
    transaction since migration 784 (`purchase_payment_service.create_foreign_bill_payment`, POST-A-575)."""
    return purchase_payment_service.create_foreign_bill_payment(firm_id, client_id, data, actor, db)


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
        _assert_payment_scope(current_user, payment_id)
        db = _get_db()
        result = reversal_service.reverse_payment(
            db, current_user["firm_id"], payment_id, data.reversal_date, created_by=current_user.get("id"),
            actor=current_user,
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
        return api_response(False, None,
                            document_failure_detail(e, action="reverse the payment"))
