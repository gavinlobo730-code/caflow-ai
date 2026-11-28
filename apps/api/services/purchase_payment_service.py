"""
Purchase payment service — the AP mirror of receipt_service.py.

A payment to a supplier has four shapes (one bill or several, rupees or a
foreign currency) and all four are recorded here, by ONE database transaction
each: `settle_payment_atomic` (migration 784, POST-A-575), reached from one
call site, `_record_payment`. The two shapes of the stored fact are kept: a
payment for ONE bill names it on its own row (`purchase_payments.purchase_bill_id`,
which `reversal_service.reverse_payment` reads to know how to roll the bill
back) and writes no allocation row; a payment across SEVERAL bills writes one
`purchase_payment_allocations` row per bill (migration 226) and carries what is
left of it as `unallocated_paise`. Callers: routers/purchase_payments.py, the
Bank Match Queue's multi-document allocation and the post-dated cheque register.

Re-allocating a payment (`update_allocations_core`) is still its own statements.

All monetary values are integer paise.
"""
import os
import uuid
import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from core.authz import can_access_client
from core.db_provider import privileged_for
from domain.accounting.payment_account import resolve_payment_account
from services.audit_service import log_event
from services.document_header_writer import update_header
from services.ledger_door import ledger_rpc, stored_answer
from services import period_lock_service
from services.period_validation_service import period_validation_service
from services.timeline_service import timeline_service
from services import tds_register_service
from services import vendor_tds
from domain.tds.residency import (
    GAP_FOREIGN_ADVANCE_NOT_WITHHELD, describe_gaps,
)
from core.ist_clock import fy_code, ist_fy_label, ist_today
from domain.money_text import minor_units_text
from domain.money_sentence import rupee_text, rupee_whole_text

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.purchase_payment_service")






def _next_payment_seq(db, firm_id: str, fy: str) -> int:
    from services.numbering import next_sequence
    return next_sequence(db, "purchase_payments", f"VPMT-{fy}-", firm_id=firm_id)


def _is_unique_violation(err: Exception) -> bool:
    """True when a Postgres/PostgREST error is a unique-constraint violation
    (23505) — recognises a payment_no collision against migration 159's
    UNIQUE (firm_id, payment_no) constraint.

    The STATE is read first, and where the driver kept one it decides. The words are asked only when there is none, and never the
    bare digits: every refusal of `settle_payment_atomic` names a bill by its id, and an id that happened to hold "23505" used to
    turn an ordinary refusal into a number collision (and a pointless second attempt)."""
    from core.exceptions import _sqlstate
    state = _sqlstate(err)
    if state:
        return state == "23505"
    s = str(err).lower()
    return "duplicate key value" in s or "already exists" in s


def _same_id(a, b) -> bool:
    """Two ids name one row. A uuid typed in capitals is the same supplier as the row's own spelling of it."""
    return str(a or "").strip().lower() == str(b or "").strip().lower() and bool(str(a or "").strip())


#: How many times a payment is prepared before it is refused: a fresh number each time and, for a foreign payment, a fresh read of its
#: bills. Each attempt is one whole transaction that writes everything or nothing, so a later attempt never builds on part of an earlier one.
PAYMENT_ATTEMPTS = 3

#: The state migration 784's function raises when a bill no longer reads as the plan read it.
BILL_MOVED_STATE = "VP001"

#: What a person reads when two payments (or a payment and a debit note) reached the same bill at the same moment.
PAYMENT_RACE_SENTENCE = (
    "One of these bills was paid or adjusted by somebody else while this payment was being recorded. "
    "Nothing was recorded. Open the payment again, so it shows what is still owed, and record it again.")

#: What a person reads when the bill had enough left when the payment was checked and not when it was written.
PAYMENT_OVERTAKEN_SENTENCE = (
    "One of these bills has less left to pay than this payment gives it: another payment or a debit note reached it while this "
    "one was being recorded. Nothing was recorded. Open the payment again, so it shows what is still owed, and record it again.")

#: What a person reads when a bill stopped being payable between the check and the write.
BILL_NO_LONGER_PAYABLE_SENTENCE = (
    "One of these bills was cancelled, or is no longer a received bill, while this payment was being recorded. "
    "Nothing was recorded. Open the payment again and record it against the bills that are still owed.")


def payment_number_carried_elsewhere(payment_no: str) -> str:
    """What a person reads when the number a payment would take is refused as a duplicate and no payment carries it."""
    return (f"The number this payment would take, {payment_no}, is already carried by another entry in this client's books "
            "(a journal typed with that reference on the same date, for example), so the payment cannot be recorded under it. "
            "Nothing was recorded. Change that entry's reference, or record the payment under another date.")


def rupee_payment_against_a_foreign_bill(bill: str, currency: str) -> str:
    """What a person reads when a payment in rupees names a bill billed in another currency."""
    return (f"Bill {bill} is billed in {currency}, and this payment is in rupees. Record the payment in {currency}, with the "
            "rate the money was paid at, so the bill's own amount is settled and the exchange difference is recorded. "
            "Nothing was recorded.")


def bill_of_another_supplier(bill: str) -> str:
    """What a person reads when a payment to one supplier names a bill raised by another (POST-A-580)."""
    return (f"Bill {bill} was raised by another supplier. A payment settles bills of the supplier it is paid to. "
            "Nothing was recorded.")


def _bill_changed_under_the_payment(err: Exception) -> bool:
    """The payment function's refusal of a foreign payment whose bill moved after it was read (migration 784): its own state VP001,
    or its own words where the client lost the code. Deliberately not serialization_failure (40001), which the gateway re-runs by
    itself; the migration says why."""
    from core.exceptions import _sqlstate
    return _sqlstate(err) == BILL_MOVED_STATE or "changed while this payment was being prepared" in str(err)


def _payment_refusal(e: Exception) -> Exception:
    """What to raise for a failure of the function that records a payment: the error in a person's words where it is a known refusal,
    and the error itself (so the caller re-raises it untouched) where it is not. Every one of these means NOTHING was written: the
    function is one transaction."""
    from services.receipt_service import _is_missing_rpc_function
    text = str(e)
    if _is_missing_rpc_function(e):
        return RuntimeError(
            "settle_payment_atomic RPC not found — migration 784 "
            "(apps/api/migrations/784_a_supplier_payment_is_recorded_in_one_transaction.sql) "
            "must be applied to this database before the API is deployed."
        )
    if _is_unique_violation(e):
        return HTTPException(status_code=409, detail="A payment numbering collision was detected; please retry.")
    if _bill_changed_under_the_payment(e):
        return HTTPException(status_code=409, detail=PAYMENT_RACE_SENTENCE)
    # The route asked each of these of a read before the call and answered in a person's words; when the FUNCTION is the one that
    # speaks, the bill changed between that read and its lock, and its own sentence is written for a log.
    if "exceeds its outstanding" in text:
        return HTTPException(status_code=409, detail=PAYMENT_OVERTAKEN_SENTENCE)
    if "and cannot be paid" in text:
        return HTTPException(status_code=409, detail=BILL_NO_LONGER_PAYABLE_SENTENCE)
    refusal = period_lock_service.closure_sentence_in(e)
    if refusal:
        return HTTPException(status_code=422, detail=refusal)
    return e


def _assert_the_clients_year_is_open(db, firm_id: str, client_id: str, payment_date: str) -> None:
    """The CLOSURES (the firm's locked year, this client's finalised year-end), asked before a payment number is taken or a row is
    written, as the receipt service asks them. The posting kernel asked this for a payment until it stopped being the one that
    posts it; `settle_payment_atomic`'s own door asks it again as the second lock, and this is the one a person reads."""
    period_lock_service.assert_not_closed(db, firm_id or "", client_id, payment_date)


def _record_payment(db, firm_id: str, client_id: str, *, fy: str, prepare) -> tuple:
    """Record ONE supplier payment through `settle_payment_atomic` (migration 784, POST-A-575): the entry, the payment row, each bill
    it settles, the allocation rows and a foreign payment's realised exchange difference are written together or not at all. There is
    nothing to compensate afterwards, which is what the four creation paths used to do in four different ways.

    `prepare(payment_no)` builds one attempt: {"payment", "entry", "lines", "allocations"}, with whatever of it depends on a read
    (a foreign payment's plan) worked out afresh. WHAT IS RETRIED: a number another payment took at the same moment (the next one is
    taken), and a foreign payment whose bill moved between the read and the function's lock (it is planned again). A number refused
    twice running is carried by something that is not a payment, and is said so. Returns (the function's answer, the attempt that
    was stored)."""
    attempt = 0
    refused_number = None
    while True:
        attempt += 1
        seq = _next_payment_seq(db, firm_id, fy)
        payment_no = f"VPMT-{fy}-{seq:04d}"
        prepared = prepare(payment_no)
        try:
            # POST-A-317: the privileged client, after the route's own checks (services/ledger_door.py says why and what stays asked).
            result = ledger_rpc(db, "settle_payment_atomic", {
                "p_payment": prepared["payment"],
                "p_journal_entry": prepared["entry"],
                "p_journal_lines": prepared["lines"],
                "p_allocations": prepared["allocations"],
            }, firm_id=firm_id, client_id=client_id).execute()
            return (result.data or {}), prepared
        except Exception as e:
            if _is_unique_violation(e):
                if payment_no == refused_number:
                    # The series still offers the number that was just refused, so no PAYMENT took it: something else in this
                    # client's books carries it. Taking it again cannot work, and "please retry" would be untrue.
                    raise HTTPException(status_code=409, detail=payment_number_carried_elsewhere(payment_no)) from e
                refused_number = payment_no
            if (_bill_changed_under_the_payment(e) or _is_unique_violation(e)) and attempt < PAYMENT_ATTEMPTS:
                continue
            refusal = _payment_refusal(e)
            if refusal is e:
                # None of the function's own refusals, which leave nothing behind. If the payment IS stored, the answer was lost on
                # the way back (POST-A-582): answer with what is there, and not with a failure the person would record again.
                stored = stored_answer(db, kind="payment", row_id=prepared["payment"]["id"], firm_id=firm_id, client_id=client_id)
                if stored is None:
                    raise
                return stored, prepared
            raise refusal from e


def _stored_payment(payment_payload: dict, out: dict) -> dict:
    """The payment as the function stored it: the database's own row over the payload that asked for it."""
    row = out.get("payment") or {}
    return {**payment_payload, **row, "id": out.get("payment_id") or payment_payload["id"],
            "journal_entry_id": out.get("journal_entry_id")}


def _rupee_entry_and_lines(db, firm_id: str, client_id: str, payment: dict, actor_id, now_iso: str) -> tuple[dict, list]:
    """The entry and the lines of a rupee payment, as the posting kernel would have written them: Dr Trade Payables, Cr the account
    the money left, Cr TDS Payable where tax was withheld on an advance. The number and the narration are added per attempt."""
    from services.phase2_journal_service import phase2_journal_service
    lines = phase2_journal_service.purchase_payment_journal_lines(db, payment, firm_id, client_id)
    day = payment["payment_date"]
    entry = {
        "firm_id": firm_id, "client_id": client_id, "entry_date": day,
        "entry_type": "Payment", "is_posted": True, "status": "posted",
        "posted_at": now_iso, "posted_by": actor_id, "created_by": actor_id,
        "source_type": "purchase_payment", "source_id": payment["id"],
    }
    line_payloads = [
        {
            "account_id": l["account_id"], "debit_paise": l["debit_paise"],
            "credit_paise": l["credit_paise"], "narration": l.get("narration", ""),
            "txn_currency": "INR", "base_currency": "INR", "exchange_rate": "1",
            "txn_debit": l["debit_paise"], "txn_credit": l["credit_paise"],
            "rate_source": "identity", "rate_type": "booking", "rate_date": day,
        }
        for l in lines
    ]
    return entry, line_payloads


def _record_rupee_payment(db, firm_id: str, client_id: str, payment_payload: dict, allocations: list, actor: dict) -> tuple[dict, list]:
    """A rupee payment, whole: `payment_payload` is the row without its number, `allocations` one row per bill. Returns the stored
    payment and what the function says it settled of each bill."""
    _assert_the_clients_year_is_open(db, firm_id, client_id, payment_payload["payment_date"])
    actor_id = (actor or {}).get("id")
    entry, lines = _rupee_entry_and_lines(db, firm_id, client_id, payment_payload, actor_id, payment_payload["created_at"])

    def prepare(payment_no: str) -> dict:
        return {
            "payment": {**payment_payload, "payment_no": payment_no},
            "entry": {**entry, "reference_no": payment_no, "narration": f"Vendor payment {payment_no}"},
            "lines": lines,
            "allocations": allocations,
        }

    out, prepared = _record_payment(db, firm_id, client_id, fy=fy_code(payment_payload["payment_date"]), prepare=prepare)
    return _stored_payment(prepared["payment"], out), (out.get("allocations") or [])


def _bills_a_rupee_payment_may_settle(db, firm_id: str, client_id: str, vendor_id: str, amount_by_bill: dict) -> None:
    """Every bill a rupee payment names is this client's, was raised by the supplier being paid, has been received and not cancelled,
    is billed in rupees, and has that much left. Asked of a read before anything is written, so the person is answered in words; the
    function asks each again of the locked row."""
    for bill_id, amount in amount_by_bill.items():
        row = (db.table("purchase_bills")
               .select("id, bill_no, status, vendor_id, txn_currency, net_payable_paise, paid_paise, debited_paise, credit_note_paise")
               .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data)
        if not row:
            raise HTTPException(status_code=422, detail=f"Bill {bill_id} is not part of this client's books.")
        bill = row[0]
        if not _same_id(bill.get("vendor_id"), vendor_id):
            raise HTTPException(status_code=422, detail=bill_of_another_supplier(bill.get("bill_no") or bill_id))
        status = bill.get("status") or ""
        if status == "cancelled":
            raise HTTPException(status_code=409, detail=f"Bill {bill_id} is cancelled and cannot be paid.")
        # task #227 audit finding: a draft bill was never received (no AP
        # journal exists — see receive_purchase_bill) so there is nothing
        # to pay yet, same class of gap as a draft sales invoice (finding #1).
        if status == "draft":
            raise HTTPException(status_code=409, detail=f"Bill {bill_id} is still a draft and has not been received yet.")
        billed_in = (str(bill.get("txn_currency") or "").strip() or "INR").upper()
        if billed_in != "INR":
            raise HTTPException(status_code=422, detail=rupee_payment_against_a_foreign_bill(bill.get("bill_no") or bill_id, billed_in))
        # Purchase credit notes (§34(3)) raise what's payable; debit notes lower
        # what still needs cash.
        effective_payable = int(bill.get("net_payable_paise") or 0) + int(bill.get("credit_note_paise") or 0)
        if int(bill.get("paid_paise") or 0) + int(bill.get("debited_paise") or 0) + amount > effective_payable:
            raise HTTPException(status_code=422, detail=f"Bill {bill_id}: allocation would exceed bill outstanding")


def create_payment_core(firm_id: str, data: dict, actor: dict, db) -> dict:
    """Create a vendor payment with MULTI-bill allocations — the AP mirror of
    receipt_service.create_receipt_core.

    - sum(allocations.allocated_paise) must be <= amount_paise
    - unallocated_paise = amount_paise - sum(allocated)  (a vendor advance,
      allocatable later — mirrors receipts.unallocated_paise)
    - the entry (Dr Trade Payables / Cr Bank), the payment, each bill's
      paid_paise + status and the allocation rows are written by ONE database
      transaction (`settle_payment_atomic`, migration 784, POST-A-575)
    - audit + timeline logged

    `data['currency']` != INR dispatches to create_foreign_payment_core (a
    per-bill realized-FX path mirroring receipt_service.create_foreign_receipt).
    `actor` supplies audit/timeline attribution: {id, auth_user_id, email}.
    Integer paise throughout.
    """
    client_id = data["client_id"]

    # Ownership + business guard (task #227 audit finding): checked here,
    # BEFORE the foreign-payment dispatch below, so a non-INR payment can no
    # longer bypass it entirely — the old placement (after the dispatch) meant
    # this check never ran for any foreign-currency payment at all. Scoped by
    # firm+client (vendors.client_id is NOT NULL — every vendor belongs to
    # exactly one client) and rejects when the vendor can't be found in THIS
    # client's books at all, not just when found-but-inactive.
    vendor: dict = {}
    if db is not None:
        # select("*") rather than is_active alone: the unallocated remainder of
        # a payment is an ADVANCE, and §194/§195 charge at credit or payment
        # whichever is earlier — so the section, the PAN, the residency and the
        # §195 paperwork all decide what this payment withholds. The bill path
        # resolves its vendor the same way.
        _v = (db.table("vendors").select("*")
              .eq("id", data["vendor_id"]).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data)
        if not _v:
            raise HTTPException(status_code=422, detail="This vendor is not part of this client's books.")
        if _v[0].get("is_active") is False:
            raise HTTPException(status_code=422, detail="This vendor is inactive. Reactivate the vendor before recording a payment.")
        vendor = _v[0]

    if db is not None and (data.get("currency") or "INR").strip().upper() != "INR":
        return create_foreign_payment_core(firm_id, data, actor, db)

    amount_paise = int(data["amount_paise"])
    if amount_paise <= 0:
        raise HTTPException(status_code=422, detail="Payment amount must be positive.")
    allocations = data.get("allocations", [])
    total_allocated = sum(int(a.get("allocated_paise", 0)) for a in allocations)
    if total_allocated > amount_paise:
        raise HTTPException(
            status_code=422,
            detail=f"Total allocated ({rupee_text(total_allocated)}) exceeds payment amount ({rupee_text(amount_paise)}).",
        )
    unallocated_paise = amount_paise - total_allocated

    period_validation_service.validate_posting_date(firm_id or "", data["payment_date"])

    # The FY of the NUMBER comes from the DOCUMENT'S OWN DATE, not from today
    # (SALES-24) — see core.ist_clock.fy_code.
    fy = fy_code(data["payment_date"])

    if db is None:
        payment_id = str(uuid.uuid4())
        payment = {
            "id": payment_id, "firm_id": firm_id, "client_id": client_id,
            "vendor_id": data["vendor_id"], "purchase_bill_id": None,
            "payment_no": f"VPMT-{fy}-0001", "payment_date": data["payment_date"],
            "amount_paise": amount_paise, "unallocated_paise": unallocated_paise,
            "payment_mode": data.get("payment_mode", "bank"),
            "bank_account_id": data.get("bank_account_id"),
            "reference_no": data.get("reference_no"), "notes": data.get("notes"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        from services.phase2_journal_service import phase2_journal_service
        phase2_journal_service.journal_for_purchase_payment(payment, firm_id or "", client_id, created_by=(actor or {}).get("id"))
        return {**payment, "allocations": allocations}

    # One row per BILL (rows for one bill are one settlement, and the allocations table holds one row per payment and bill), then
    # every bill asked, of a read, what the function will ask of the locked row: whose it is, that it can be paid, and that it has
    # this much left. Nothing has been written when any of these refuses.
    amount_by_bill: dict = {}
    for _a in allocations:
        _bill_id = _a.get("purchase_bill_id")
        _amt = int(_a.get("allocated_paise", 0) or 0)
        if _bill_id and _amt > 0:
            amount_by_bill[_bill_id] = amount_by_bill.get(_bill_id, 0) + _amt
    _bills_a_rupee_payment_may_settle(db, firm_id, client_id, data["vendor_id"], amount_by_bill)

    # ── §194 / §195: the unallocated remainder is an advance, and an advance
    # is the EARLIER of "credit or payment", so it withholds here. The
    # allocated part does not: it settles bills that were charged when they
    # were booked, and charging it again would deduct the same sum twice.
    # The allocations have not been applied to the bills yet, so the open
    # payable still includes what this payment is about to settle — subtract it,
    # or the payment appears to discharge nothing and the whole remainder reads
    # as a fresh advance.
    tds_cols = vendor_tds.columns_for_advance(
        vendor, unallocated_paise, data["payment_date"], firm_id, db,
        payment_total_paise=amount_paise,
        open_payable_paise=max(0, vendor_tds.open_payable_paise(
            db, firm_id=firm_id, client_id=client_id,
            vendor_id=data["vendor_id"]) - total_allocated))

    now_iso = datetime.now(timezone.utc).isoformat()
    payment_payload = {
        "id":                str(uuid.uuid4()),   # chosen here so the entry can name the payment it belongs to
        "firm_id":           firm_id,
        "client_id":         client_id,
        "vendor_id":         data["vendor_id"],
        "purchase_bill_id":  None,   # multi-bill => allocations table, not this legacy single-bill FK
        "payment_date":      data["payment_date"],
        "amount_paise":      amount_paise,
        "unallocated_paise": unallocated_paise,
        "payment_mode":      data.get("payment_mode", "bank"),
        "bank_account_id":   data.get("bank_account_id"),
        "reference_no":      data.get("reference_no"),
        "notes":             data.get("notes"),
        "created_at":        now_iso,
        "updated_at":        now_iso,
        # The bank leg is amount_paise − tds_paise; the difference credits TDS
        # Payable. amount_paise keeps its meaning — the sum credited or paid.
        **vendor_tds.strip_non_columns(tds_cols),
    }
    # ONE TRANSACTION (POST-A-575, migration 784). This path used to post the entry through the kernel, insert the payment, move each
    # bill with a compare-and-set it retried, insert the allocations, and on a failure compensate (reverse the entry, delete the
    # payment) without rolling back a bill an earlier step had already moved.
    payment, settled = _record_rupee_payment(
        db, firm_id, client_id, payment_payload,
        [{"purchase_bill_id": b, "allocated_paise": amt} for b, amt in amount_by_bill.items()], actor)
    payment_id = payment["id"]
    payment_no = payment["payment_no"]
    alloc_payloads = [
        {"purchase_payment_id": payment_id, "purchase_bill_id": r.get("purchase_bill_id"), "allocated_paise": r.get("allocated_paise")}
        for r in settled
    ]

    log_event(
        firm_id or "", "purchase_payment", payment_id, "create",
        actor_id=(actor or {}).get("auth_user_id"), actor_email=(actor or {}).get("email"),
        new_data={"amount_paise": amount_paise, "vendor_id": data["vendor_id"]},
    )
    timeline_service.log_timeline_event(
        client_id=client_id, firm_id=firm_id or "", financial_year=ist_fy_label(data["payment_date"]),
        category="accounting", event_type="payment_recorded",
        title=f"Vendor Payment {payment_no} recorded",
        description=f"Payment of {rupee_whole_text(amount_paise)} made to vendor across {len(alloc_payloads)} bill(s).",
        severity="success", entity_type="purchase_payment", entity_id=payment_id,
        amount_paise=amount_paise, actor_id=(actor or {}).get("auth_user_id"), actor_name=(actor or {}).get("email"),
    )

    # THE REGISTER, OR THE DEDUCTION IS INVISIBLE TO COMPLIANCE — no challan by
    # the 7th (Rule 30), no deductee line for 26Q/27Q (Rule 31A). Never raises.
    register = tds_register_service.sync_for_payment(
        db, firm_id or "", client_id, {**payment, **tds_cols}, vendor)
    if register.get("statutory_gaps"):
        payment["statutory_gaps"] = register["statutory_gaps"]
        payment["gap_details"] = register.get("gap_details")
    if tds_cols.get("_tds_why"):
        payment["tds_why"] = tds_cols["_tds_why"]

    payment["allocations"]      = alloc_payloads
    return payment


def create_single_bill_payment(firm_id: str, client_id: str, data: dict, actor: dict, db, vendor: dict) -> tuple[dict, dict]:
    """A rupee payment that names its bill on its own row, or names no bill at all (an advance): the shape
    `routers/purchase_payments.create_purchase_payment` has always written, which `reversal_service.reverse_payment` reads to know
    how to roll the bill back. Returns (the stored payment, the columns of the tax withheld on an advance).

    The entry, the payment and the bill's paid amount and status are ONE database transaction (`settle_payment_atomic`, migration
    784, POST-A-575). It used to reserve the bill's outstanding first, post the entry, insert the payment, give the reservation back
    on a failure and then recompute the bill from its payments."""
    vendor_id = data["vendor_id"]
    amount_paise = int(data["amount_paise"])
    payment_date = data["payment_date"]
    purchase_bill_id = data.get("purchase_bill_id")

    if purchase_bill_id:
        # OOS-1 fix: a linked bill must belong to THIS payment's firm+client, validated
        # before anything is written (mirrors the receipt-allocation guard).
        _bill = (db.table("purchase_bills")
                 .select("id, bill_no, status, net_payable_paise, paid_paise, debited_paise, credit_note_paise, vendor_id, txn_currency")
                 .eq("id", purchase_bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
                 .limit(1).execute().data) or []
        if not _bill:
            raise HTTPException(status_code=422, detail="Purchase bill is not part of this client's books.")
        bill = _bill[0]
        if not _same_id(bill.get("vendor_id"), vendor_id):
            raise HTTPException(status_code=422, detail="This bill does not belong to the specified vendor.")
        # M6: never pay a cancelled bill, and never overpay one (payables can't go
        # negative).
        if (bill.get("status") or "") == "cancelled":
            raise HTTPException(status_code=409, detail="This bill is cancelled and cannot be paid.")
        # task #227 audit finding: a draft bill was never received (no AP
        # journal exists yet) — same class of gap as a draft sales invoice.
        if (bill.get("status") or "") == "draft":
            raise HTTPException(status_code=409, detail="This bill is still a draft and has not been received yet.")
        billed_in = (str(bill.get("txn_currency") or "").strip() or "INR").upper()
        if billed_in != "INR":
            raise HTTPException(status_code=422, detail=rupee_payment_against_a_foreign_bill(bill.get("bill_no") or purchase_bill_id, billed_in))
        # Debit notes reduce the payable and purchase credit notes (§34(3), the
        # increase-side mirror) raise the ceiling. The function asks the same of
        # the locked row; this is the answer in a person's words.
        outstanding = (int(bill.get("net_payable_paise") or 0) + int(bill.get("credit_note_paise") or 0)
                       - int(bill.get("paid_paise") or 0) - int(bill.get("debited_paise") or 0))
        if amount_paise > outstanding:
            raise HTTPException(
                status_code=422,
                detail=f"Payment ({rupee_text(amount_paise)}) exceeds the bill's outstanding "
                       f"({rupee_text(outstanding)}).")

    # ── §194 / §195: an advance is the EARLIER event ────────────────────
    # This path gives the whole payment to the linked bill when there is
    # one, so the advance is the whole payment when there is not. A bill-linked
    # payment withholds nothing here: it was charged when the bill was
    # booked, and charging it again would deduct the same sum twice.
    unallocated_paise = 0 if purchase_bill_id else amount_paise
    # The payment has not been applied to the bill yet, so the open payable still
    # includes what it is about to settle: take it off, as the path for several bills does.
    tds_cols = vendor_tds.columns_for_advance(
        vendor, unallocated_paise, payment_date, firm_id, db,
        payment_total_paise=amount_paise,
        open_payable_paise=max(0, vendor_tds.open_payable_paise(
            db, firm_id=firm_id, client_id=client_id, vendor_id=vendor_id) - (amount_paise if purchase_bill_id else 0)))

    now_iso = datetime.now(timezone.utc).isoformat()
    payment_payload = {
        # task #102: pre-generated so the journal can carry source_type/source_id back to this payment,
        # for reverse_payment / any future source_id-keyed lookup.
        "id": str(uuid.uuid4()),
        "firm_id": firm_id,
        "client_id": client_id,
        "vendor_id": vendor_id,
        "purchase_bill_id": purchase_bill_id,
        "payment_date": payment_date,
        "amount_paise": amount_paise,
        "payment_mode": data.get("payment_mode", "bank"),
        # The account the money left: the entry's cash leg is resolved from it, so the payment row says so too.
        "bank_account_id": data.get("bank_account_id"),
        "reference_no": data.get("reference_no"),
        "notes": data.get("notes"),
        # WHAT THIS PAYMENT HAS NOT DISCHARGED: 0 when it names a bill (the whole amount settles it), the whole amount when it
        # does not. `update_allocations_core` and the AP ageing's advances section both read it (PUR-24).
        "unallocated_paise": unallocated_paise,
        "created_at": now_iso,
        "updated_at": now_iso,
        **vendor_tds.strip_non_columns(tds_cols),
    }
    payment, _settled = _record_rupee_payment(
        db, firm_id, client_id, payment_payload,
        [{"purchase_bill_id": purchase_bill_id, "allocated_paise": amount_paise}] if purchase_bill_id else [], actor)
    return payment, tds_cols


def _foreign_payment_minor_unit(db, firm_id: str, client_id: str, ccy: str) -> int:
    """The currency's minor unit, once the three gates are passed: multi-currency is on for this firm and client, and the currency is
    one the product holds and has not retired. Each refusal is in words."""
    from domain.currency import currency_service
    from domain.currency.policy import resolve_currency_policy
    firm = (db.table("firms").select("multi_currency_entitled").eq("id", firm_id).limit(1).execute().data or [None])[0]
    client = (db.table("clients").select("functional_currency, multi_currency_enabled").eq("id", client_id).eq("firm_id", firm_id).limit(1).execute().data or [None])[0]
    if not resolve_currency_policy(firm, client).active:
        raise HTTPException(status_code=422, detail="Multi-currency is not enabled for this client.")
    cur = currency_service.get_currency(db, ccy)
    if not cur:
        raise HTTPException(status_code=422, detail=f"Unsupported currency: {ccy}.")
    if not cur.get("is_active", True):
        raise HTTPException(status_code=422, detail=f"Currency {ccy} is inactive.")
    return int(cur.get("minor_unit", 2))


def _foreign_payment_rate(K, db, data: dict, ccy: str, payment_date: str):
    """The rate the cash leaves at: (rate, where it came from, whether a person typed it). A typed rate wins; otherwise the booking
    rate on the payment's own date. A rate that cannot be read, is not held or is not positive is refused in words."""
    from datetime import date as _date
    from decimal import Decimal, InvalidOperation
    from domain.currency import RateNotFound
    overridden = data.get("exchange_rate") is not None
    if overridden:
        try:
            rate = Decimal(str(data["exchange_rate"]))
        except (InvalidOperation, ValueError, TypeError) as _cause:
            raise HTTPException(status_code=422, detail="Invalid exchange rate.") from _cause
        source = "manual-override"
    else:
        try:
            q = K.exchange_rate_service(db).get_quote(ccy, "INR", _date.fromisoformat(str(payment_date)[:10]), "booking")
        except RateNotFound as _cause:
            raise HTTPException(status_code=422, detail=f"No exchange rate available for {ccy}->INR on {payment_date}.") from _cause
        rate, source = q.rate, q.source
    if rate <= 0:
        raise HTTPException(status_code=422, detail="Exchange rate must be positive.")
    return rate, source, overridden


def _plan_foreign_payment(db, firm_id: str, client_id: str, vendor_id: str, ccy: str, minor: int, foreign_by_bill: dict,
                          *, one_bill: bool = False) -> tuple[list, int]:
    """What a foreign payment settles of each bill, from a read of the bill as it stands now.

    Returns ([(bill row, foreign amount, rupees relieved)], total rupees relieved). Each bill is relieved at ITS OWN booking rate, and
    the rupees are snapped to what is left of it when the foreign amount clears it, so a part-paid bill never ends paid with a rounding
    residue. The rows are a READ: the function that records the payment compares each with the bill once it holds the lock (migration
    784) and refuses the payment if it moved. `one_bill` only chooses the wording of a refusal (the single-bill route's own)."""
    from decimal import Decimal
    from domain.currency.conversion import to_base_minor
    plan, total_relieved = [], 0
    for bill_id, f in foreign_by_bill.items():
        bill = (db.table("purchase_bills")
                .select("id, bill_no, status, vendor_id, txn_currency, exchange_rate, net_payable_paise, paid_paise, paid_txn, "
                        "debited_paise, credit_note_paise, txn_net_payable")
                .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data or [None])[0]
        named = "This bill" if one_bill else f"Bill {bill_id}"
        if not bill:
            raise HTTPException(status_code=422, detail=("Purchase bill is not part of this client's books." if one_bill
                                                         else f"Bill {bill_id} is not part of this client's books."))
        if not _same_id(bill.get("vendor_id"), vendor_id):
            raise HTTPException(status_code=422, detail=("This bill does not belong to the specified vendor." if one_bill
                                                         else bill_of_another_supplier(bill.get("bill_no") or bill_id)))
        if (bill.get("status") or "") == "cancelled":
            raise HTTPException(status_code=409, detail=f"{named} is cancelled and cannot be paid.")
        # task #227 audit finding: a draft bill was never received (no AP
        # journal exists yet) — same class of gap as a draft sales invoice.
        if (bill.get("status") or "") == "draft":
            raise HTTPException(status_code=409, detail=f"{named} is still a draft and has not been received yet.")
        if (bill.get("txn_currency") or "INR").upper() != ccy:
            raise HTTPException(status_code=422, detail=(
                f"Currency mismatch: payment is {ccy} but bill {'' if one_bill else str(bill_id) + ' '}is billed in {bill.get('txn_currency')}."))
        R0 = Decimal(str(bill.get("exchange_rate") or 1))
        base_out = int(bill.get("net_payable_paise") or 0) - int(bill.get("paid_paise") or 0) - int(bill.get("debited_paise") or 0)
        foreign_out = int(bill.get("txn_net_payable") or 0) - int(bill.get("paid_txn") or 0)
        if f > foreign_out:
            raise HTTPException(status_code=422, detail=(
                f"Payment {minor_units_text(f, minor)} exceeds the bill's outstanding {minor_units_text(foreign_out, minor)} {ccy}." if one_bill
                else f"Allocation {minor_units_text(f, minor)} exceeds bill {bill_id} outstanding {minor_units_text(foreign_out, minor)} {ccy}."))
        # Snap the base to clear exactly on full settlement — no rounding drift.
        relieved = base_out if f == foreign_out else to_base_minor(f, R0, minor)
        if relieved < 0:
            # Debit notes have taken more rupees off this bill than were left: clearing its foreign amount would "relieve" a
            # negative figure. The function refuses that; this says it to the person.
            raise HTTPException(status_code=422, detail=(
                f"{named} has nothing left to pay in rupees (its debit notes exceed what was owed), so a payment cannot settle "
                f"its {ccy} amount. Correct the debit note against it first."))
        # The RUPEES this would relieve must still be owed. They can run out before the foreign amount does: a debit note on a foreign
        # bill lowers what is owed in rupees and not the foreign outstanding. The function asks the same of the locked row and would
        # refuse in a log's words; this says it to the person. (A purchase credit note raises what is payable, as the function counts it.)
        rupees_owed = base_out + int(bill.get("credit_note_paise") or 0)
        if relieved > rupees_owed:
            why = "A debit note has reduced what is owed. " if int(bill.get("debited_paise") or 0) > 0 else ""
            raise HTTPException(status_code=422, detail=(
                f"{named} has {rupee_text(max(rupees_owed, 0))} left to pay in rupees, less than "
                f"{minor_units_text(f, minor)} {ccy} would settle at the bill's own rate ({rupee_text(relieved)}). "
                f"{why}Pay a smaller amount against this bill."))
        plan.append((bill, f, relieved))
        total_relieved += relieved
    return plan, total_relieved


def _record_foreign_payment(db, firm_id: str, client_id: str, data: dict, actor: dict, *, payment_date: str, single_bill=None) -> dict:
    """A foreign payment, whole (`settle_payment_atomic`, migration 784, POST-A-575).

    Each bill is relieved at ITS frozen booking rate (R0); the cash leaves at the payment's rate (R1); the difference posts to
    Realized FX Gain/Loss in the one balanced entry. `single_bill` is the bill the payment names on its own row (the older shape, no
    allocation rows; the payment's whole foreign amount settles it); otherwise `data['allocations']` say what each bill takes and the
    unallocated remainder is an advance carried at R1 on the same Trade Payable line.

    The rupee figures come from a read of each bill, taken per attempt: each allocation says what the read saw, the function refuses
    the whole payment if the bill, once locked, no longer says the same, and the payment is then planned again."""
    from domain.currency.conversion import to_base_minor
    from services.phase2_journal_service import phase2_journal_service as K

    ccy = (data.get("currency") or "").strip().upper()
    vendor_id = data["vendor_id"]
    period_validation_service.validate_posting_date(firm_id or "", payment_date)
    _assert_the_clients_year_is_open(db, firm_id, client_id, payment_date)
    minor = _foreign_payment_minor_unit(db, firm_id, client_id, ccy)
    R1, r1_source, overridden = _foreign_payment_rate(K, db, data, ccy, payment_date)

    total_foreign = int(data["amount_paise"])   # foreign cash paid (minor units)
    if total_foreign <= 0:
        raise HTTPException(status_code=422, detail=("amount_paise must be positive" if single_bill else "Payment amount must be positive."))
    if single_bill:
        foreign_by_bill = {single_bill: total_foreign}
    else:
        # One row per BILL: two rows for one bill were each planned from the same read of it, so the second could not be the one that
        # clears the bill and its rupees were not snapped to what was left.
        foreign_by_bill = {}
        for a in data.get("allocations", []):
            if int(a.get("allocated_paise", 0) or 0) > 0:
                foreign_by_bill[a.get("purchase_bill_id")] = foreign_by_bill.get(a.get("purchase_bill_id"), 0) + int(a["allocated_paise"])
    total_foreign_settled = sum(foreign_by_bill.values())
    if total_foreign_settled > total_foreign:
        raise HTTPException(status_code=422, detail="Allocated foreign exceeds the payment amount.")

    cash_base = to_base_minor(total_foreign, R1, minor)
    settled_cash_base = to_base_minor(total_foreign_settled, R1, minor)
    unalloc_base = cash_base - settled_cash_base

    ap_id = K._find_account(db, firm_id, client_id, "%Trade Payable%", system_key="ap")
    # The account the money actually left, not a firm-wide generic Bank ledger (domain/accounting/payment_account.py).
    paid_from = resolve_payment_account(
        db, firm_id=firm_id, client_id=client_id,
        bank_account_id=data.get("bank_account_id"),
        payment_mode=data.get("payment_mode"),
        find_account=K._find_account)
    bank_id = paid_from.account_id

    actor_id = (actor or {}).get("id")
    now_iso = datetime.now(timezone.utc).isoformat()
    rate_date = str(payment_date)[:10]
    payment_id = str(uuid.uuid4())
    entry_payload = {
        "firm_id": firm_id, "client_id": client_id, "entry_date": payment_date,
        "entry_type": "Payment", "is_posted": True, "status": "posted",
        "posted_at": now_iso, "posted_by": actor_id, "created_by": actor_id,
        "source_type": "purchase_payment", "source_id": payment_id,
    }
    # Rate-selection provenance, as the kernel stamps it: only when a rate was actually chosen.
    if overridden:
        entry_payload["rate_overridden"] = True
    if actor_id is not None:
        entry_payload["rate_selected_by"] = actor_id
        entry_payload["rate_selected_at"] = now_iso
    payment_payload = {
        "id": payment_id,
        "firm_id": firm_id, "client_id": client_id, "vendor_id": vendor_id,
        "purchase_bill_id": single_bill or None, "payment_date": payment_date,
        "amount_paise": cash_base, "payment_mode": data.get("payment_mode", "bank"),
        "bank_account_id": data.get("bank_account_id"), "reference_no": data.get("reference_no"),
        "notes": data.get("notes"), "created_at": now_iso, "updated_at": now_iso,
        "txn_currency": ccy, "exchange_rate": str(R1), "txn_amount": total_foreign,
        "rate_source": r1_source, "rate_type": "booking", "rate_date": rate_date,
        "rate_selected_by": actor_id, "rate_overridden": overridden,
    }
    if not single_bill:
        payment_payload["unallocated_paise"] = unalloc_base

    last_fx = {"paise": 0}

    def prepare(payment_no: str) -> dict:
        plan, total_ap_relieved = _plan_foreign_payment(db, firm_id, client_id, vendor_id, ccy, minor, foreign_by_bill,
                                                        one_bill=bool(single_bill))
        fx_diff = total_ap_relieved - settled_cash_base   # + gain (paid less INR) / − loss (paid more)
        last_fx["paise"] = fx_diff
        lines = [
            {"account_id": ap_id, "debit_paise": total_ap_relieved + unalloc_base, "credit_paise": 0,
             "narration": "Trade payable settled at booked rate", "txn_debit": total_foreign, "txn_credit": 0},
            {"account_id": bank_id, "debit_paise": 0, "credit_paise": cash_base,
             "narration": ("Cash payment (foreign)" if paid_from.source == "cash" else "Bank payment (foreign)"),
             "txn_debit": 0, "txn_credit": total_foreign},
        ]
        this_payment = {**payment_payload, "payment_no": payment_no}
        if fx_diff != 0:
            fx_id = K._find_account(db, firm_id, client_id, "%Foreign Exchange%", system_key="fx_realized")
            lines.append({"account_id": fx_id, "debit_paise": max(-fx_diff, 0), "credit_paise": max(fx_diff, 0),
                          "narration": "Realized FX gain" if fx_diff > 0 else "Realized FX loss", "txn_debit": 0, "txn_credit": 0})
            # The record of the realised difference, written by the function with everything else.
            this_payment["fx_adjustment"] = {
                "settlement_rate": str(R1), "base_delta_paise": fx_diff, "rate_source": r1_source, "created_by": actor_id,
            }
        return {
            "payment": this_payment,
            "entry": {**entry_payload, "reference_no": payment_no, "narration": f"Vendor payment {payment_no} (foreign)"},
            # Dual storage, as the kernel writes it: the rupee amount stays authoritative, the foreign amount and the rate sit beside it.
            "lines": [{**l, "txn_currency": ccy, "base_currency": "INR", "exchange_rate": str(R1),
                       "rate_source": r1_source, "rate_type": "booking", "rate_date": rate_date} for l in lines],
            "allocations": [
                {"purchase_bill_id": bill["id"], "allocated_paise": relieved, "allocated_txn": f,
                 # what the read saw of the bill: the function compares it with the locked row
                 "expect_paid_paise": int(bill.get("paid_paise") or 0), "expect_paid_txn": int(bill.get("paid_txn") or 0),
                 "expect_debited_paise": int(bill.get("debited_paise") or 0)}
                for (bill, f, relieved) in plan
            ],
        }

    out, prepared = _record_payment(db, firm_id, client_id, fy=fy_code(payment_date), prepare=prepare)
    payment = _stored_payment({k: v for k, v in prepared["payment"].items() if k != "fx_adjustment"}, out)
    entry_id = out.get("journal_entry_id")
    fx_diff = last_fx["paise"]

    log_event(firm_id, "purchase_payment", payment["id"], "create", actor_id=(actor or {}).get("auth_user_id"),
              actor_email=(actor or {}).get("email"), new_data={"amount_paise": cash_base, "currency": ccy})
    result = {**payment, "journal_entry_id": entry_id, "realized_fx_paise": fx_diff}
    if not single_bill:
        # task #227: the foreign amount too (allocated_paise alone is base-currency), so a later reversal can roll back the bill's
        # paid_txn by the exact amount this allocation added to it.
        result["allocations"] = [
            {"purchase_payment_id": payment["id"], "purchase_bill_id": r.get("purchase_bill_id"),
             "allocated_paise": r.get("allocated_paise"), "allocated_txn": r.get("allocated_txn")}
            for r in (out.get("allocations") or [])
        ]
    return result


def create_foreign_bill_payment(firm_id: str, client_id: str, data: dict, actor: dict, db) -> dict:
    """Foreign vendor payment that names the ONE bill it settles (Multi-Currency Phase 4), the shape
    `routers/purchase_payments.create_purchase_payment` writes for a single-bill request: the bill on the payment's own row, no
    allocation rows, the payment's whole foreign amount against that bill."""
    bill_id = data.get("purchase_bill_id")
    if not bill_id:
        raise HTTPException(status_code=422, detail="A foreign payment must be linked to the purchase bill it settles.")
    return _record_foreign_payment(db, firm_id, client_id, {**data, "client_id": client_id}, actor,
                                   payment_date=data.get("payment_date", str(ist_today())), single_bill=bill_id)


def create_foreign_payment_core(firm_id: str, data: dict, actor: dict, db) -> dict:
    """Foreign vendor payment with realized FX, MULTI-bill — mirrors
    receipt_service.create_foreign_receipt exactly, for the AP side.

    Each allocated bill is relieved at ITS frozen booking rate (R0); the cash
    is taken at the payment's rate (R1); the difference posts to Realized FX
    Gain/Loss in ONE balanced journal. Foreign settled amounts are tracked on
    the bill (paid_txn) so partial settlements never drift. Supports partial /
    multiple / under-allocation (the unallocated remainder is a vendor advance
    carried at R1, folded into the same Trade Payable control-account line —
    same convention as create_foreign_receipt's unalloc_base). Original
    documents/rates are never modified. One database transaction since
    migration 784 (`_record_foreign_payment`)."""
    client_id = data["client_id"]
    out = _record_foreign_payment(db, firm_id, client_id, data, actor, payment_date=data["payment_date"])
    # THE ONE PAYMENT PATH THAT DOES NOT WITHHOLD, SAID OUT LOUD. §194 and §195
    # charge at credit or payment whichever is earlier, so this unallocated
    # remainder is a deduction event exactly as an INR advance is (migration
    # 358). It is not computed here because the vendor is credited in a foreign
    # currency while the tax is remitted in rupees: the cash leg is not
    # "amount − tax", and guessing the split would misstate what the vendor was
    # actually paid. A zero here and a zero on a non-TDS vendor used to be the
    # same number meaning opposite things.
    _v = (db.table("vendors").select("tds_applicable")
          .eq("id", data["vendor_id"]).eq("firm_id", firm_id)
          .limit(1).execute().data or [{}])[0]
    if int(out.get("unallocated_paise") or 0) > 0 and _v.get("tds_applicable"):
        out["statutory_gaps"] = [GAP_FOREIGN_ADVANCE_NOT_WITHHELD]
        out["gap_details"] = describe_gaps([GAP_FOREIGN_ADVANCE_NOT_WITHHELD])
    return out


def _adjust_bill_paid(db, firm_id: str, client_id: str, bill_id: str, delta_paise: int,
                      max_retries: int = 5, *, actor: dict | None = None) -> None:
    """Apply a signed delta to a purchase bill's paid_paise and recompute status.
    Integer paise; paid clamped at >= 0. The AP mirror of routers/receipts.py's
    _adjust_invoice_paid — used to REVERSE then RE-APPLY a payment's allocations
    on re-allocation so paid_paise is recomputed from scratch and never inflated.
    Firm+client scoped so a payment can never read/mutate another tenant's bill.
    CAS-guarded (same shape as reversal_service._rollback_bill_paid /
    the payment function's own bill arithmetic) against a concurrent write to the
    same bill's paid_paise."""
    if not bill_id or delta_paise == 0:
        return
    for _attempt in range(max_retries):
        resp = (db.table("purchase_bills")
                .select("net_payable_paise, paid_paise, debited_paise, credit_note_paise, status")
                .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute())
        if not resp.data:
            return
        bill = resp.data[0]
        raw_paid = bill.get("paid_paise")  # CAS guard must match this exact stored value
        # Purchase credit notes (§34(3)) raise what's payable; debit notes lower
        # what still needs cash — same effective-payable formula as
        # the payment function (settle_payment_atomic, migration 784).
        effective_payable = int(bill.get("net_payable_paise") or 0) + int(bill.get("credit_note_paise") or 0)
        debited = int(bill.get("debited_paise") or 0)
        new_paid = int(raw_paid or 0) + delta_paise
        if new_paid < 0:
            new_paid = 0
        status = ("paid" if new_paid + debited >= effective_payable
                  else "partially_paid" if new_paid > 0 else "received")
        result = update_header(
            db, "purchase_bills", bill_id, {"paid_paise": new_paid, "status": status},
            firm_id=firm_id, client_id=client_id, actor=actor, expect={"paid_paise": raw_paid},
            before={"paid_paise": int(raw_paid or 0), "status": bill.get("status")})
        if result.data:
            return
        # Lost the race — retry against the now-current paid_paise.
    raise HTTPException(status_code=409, detail=f"Bill {bill_id} is being updated concurrently — please retry.")


#: What a person reads when they re-allocate a payment that has been reversed.
REVERSED_PAYMENT_IS_NOT_REALLOCATED = (
    "This payment has been reversed, so there is nothing of it left to allocate. Record a new payment instead. Nothing was changed.")

#: What a person reads when they re-allocate a payment that was recorded against one bill.
PAYMENT_THAT_NAMES_ITS_BILL_IS_NOT_REALLOCATED = (
    "This payment was recorded against one bill and settles it in full, so it has nothing left to move to another bill. "
    "To apply it differently, reverse it and record it again. Nothing was changed.")

#: What a person reads when they re-allocate a payment that was made in a foreign currency.
FOREIGN_PAYMENT_IS_NOT_REALLOCATED = (
    "This payment is in {currency}. A payment in a foreign currency cannot be re-allocated yet, because re-allocation moves the rupee "
    "amounts only. Reverse the payment and record it again with the allocations you want. Nothing was changed.")


def _bills_a_payment_may_be_re_allocated_to(db, firm_id: str, client_id: str, vendor_id, requested_by_bill: dict, prior_by_bill: dict) -> None:
    """Every bill a re-allocation names is in THIS payment's firm and client, was raised by the supplier the payment was made to
    (POST-A-580), is billed in rupees, has been received and not cancelled, and has that much left: net payable + credit notes −
    debited − paid, plus whatever THIS payment already had on it, since that is reversed first."""
    for bill_id, req_amt in requested_by_bill.items():
        chk = (db.table("purchase_bills")
               .select("id, bill_no, status, vendor_id, txn_currency, net_payable_paise, paid_paise, debited_paise, credit_note_paise")
               .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
               .limit(1).execute())
        if not chk.data:
            raise HTTPException(status_code=422, detail=f"Bill {bill_id} is not part of this client's books.")
        bill = chk.data[0]
        if vendor_id and not _same_id(bill.get("vendor_id"), vendor_id):
            raise HTTPException(status_code=422, detail=bill_of_another_supplier(bill.get("bill_no") or bill_id))
        if (bill.get("status") or "") == "cancelled":
            raise HTTPException(status_code=409, detail=f"Bill {bill_id} is cancelled and cannot be paid.")
        # task #227 audit finding: a draft bill was never received (no AP
        # journal exists yet) — same class of gap as a draft sales invoice.
        if (bill.get("status") or "") == "draft":
            raise HTTPException(status_code=409, detail=f"Bill {bill_id} is still a draft and has not been received yet.")
        billed_in = (str(bill.get("txn_currency") or "").strip() or "INR").upper()
        if billed_in != "INR":
            raise HTTPException(status_code=422, detail=rupee_payment_against_a_foreign_bill(bill.get("bill_no") or bill_id, billed_in))
        effective_payable = int(bill.get("net_payable_paise") or 0) + int(bill.get("credit_note_paise") or 0)
        outstanding = (effective_payable - int(bill.get("debited_paise") or 0)
                       - int(bill.get("paid_paise") or 0) + prior_by_bill.get(bill_id, 0))
        if req_amt > outstanding:
            raise HTTPException(
                status_code=422,
                detail=f"Allocation ({rupee_text(req_amt)}) exceeds the bill's outstanding ({rupee_text(max(outstanding, 0))}).")


def update_allocations_core(firm_id: str, payment_id: str, allocations: list, actor: dict, db) -> dict:
    """Re-allocate an existing vendor payment's cash across bills — the AP
    mirror of receipts.py's PATCH /{receipt_id}/allocate. Lets a stranded
    advance (purchase_payments.unallocated_paise > 0 — e.g. from a bank-match
    settlement that exceeded the selected bills, or a payment simply recorded
    before the bill it's meant for existed yet) be applied once a bill is
    available, without creating a second payment.

    Reverses this payment's PRIOR allocations first (so paid_paise is
    recomputed from scratch, never inflated on re-allocation — mirrors
    receipts.py's H3 fix), then re-applies the requested set. Firm+client
    scoped throughout; `allocations` is a list of
    {purchase_bill_id, allocated_paise} dicts.

    This is the sole caller-facing entry point (only
    routers/purchase_payments.py's update_purchase_payment_allocations calls
    it) — the client-assignment check against `actor` lives here rather than
    duplicated at the call site, mirroring compliance_ops.py's
    assign_obligation/transition_obligation call-site convention.
    """
    resp = (db.table("purchase_payments").select("amount_paise, client_id, vendor_id, txn_currency, purchase_bill_id, is_reversed")
            .eq("id", payment_id).eq("firm_id", firm_id).limit(1).execute())
    if not resp.data:
        raise HTTPException(status_code=404, detail=f"Payment {payment_id} not found")
    client_id = resp.data[0].get("client_id")
    if not can_access_client(actor, client_id):
        raise HTTPException(status_code=404, detail=f"Payment {payment_id} not found")
    # TWO PAYMENTS THAT CANNOT BE MOVED, each said in words. A reversed payment's money went back: its allocation rows are voided,
    # and re-applying them would settle bills with money that is no longer there. A payment that names its bill on its own row has
    # already given that bill its whole amount (and the reversal rolls back that one bill): moving it onto other bills would settle
    # twice with one payment.
    if resp.data[0].get("is_reversed"):
        raise HTTPException(status_code=409, detail=REVERSED_PAYMENT_IS_NOT_REALLOCATED)
    if resp.data[0].get("purchase_bill_id"):
        raise HTTPException(status_code=422, detail=PAYMENT_THAT_NAMES_ITS_BILL_IS_NOT_REALLOCATED)
    # Re-allocation moves rupees only, so a payment in a foreign currency is refused in words (the receipt side's rule, POST-A-576).
    paid_in = (str(resp.data[0].get("txn_currency") or "").strip() or "INR").upper()
    if paid_in != "INR":
        raise HTTPException(status_code=422, detail=FOREIGN_PAYMENT_IS_NOT_REALLOCATED.format(currency=paid_in))
    amount_paise = int(resp.data[0]["amount_paise"])

    total_requested = sum(int(a.get("allocated_paise", 0) or 0) for a in allocations)
    if total_requested > amount_paise:
        raise HTTPException(status_code=422, detail="Allocated amount exceeds payment amount")

    # This payment's PRIOR allocations (reversed below before re-applying) —
    # also needed per bill so the over-application check measures the bill's
    # outstanding as it will be AFTER that reversal.
    prior = (db.table("purchase_payment_allocations").select("purchase_bill_id, allocated_paise")
             .eq("purchase_payment_id", payment_id).execute().data) or []
    prior_by_bill: dict = {}
    for old in prior:
        k = old.get("purchase_bill_id")
        prior_by_bill[k] = prior_by_bill.get(k, 0) + int(old.get("allocated_paise", 0) or 0)

    # Requested totals per bill (duplicate rows summed, mirroring
    # create_payment_core's pre-aggregation).
    requested_by_bill: dict = {}
    for a in allocations:
        bill_id = a.get("purchase_bill_id")
        amt = int(a.get("allocated_paise", 0) or 0)
        if bill_id and amt > 0:
            requested_by_bill[bill_id] = requested_by_bill.get(bill_id, 0) + amt

    _bills_a_payment_may_be_re_allocated_to(db, firm_id, client_id, resp.data[0].get("vendor_id"), requested_by_bill, prior_by_bill)

    # Reverse this payment's PRIOR allocations before re-applying, so
    # paid_paise is recomputed from scratch and never inflated by repeated
    # re-allocation.
    for old in prior:
        _adjust_bill_paid(db, firm_id, client_id, old.get("purchase_bill_id"), -int(old.get("allocated_paise", 0) or 0), actor=actor)
    privileged_for(db).table("purchase_payment_allocations").delete().eq("purchase_payment_id", payment_id).execute()

    alloc_payloads = []
    for a in allocations:
        bill_id = a.get("purchase_bill_id")
        amt = int(a.get("allocated_paise", 0) or 0)
        if not bill_id or amt <= 0:
            continue
        alloc_payloads.append({
            "purchase_payment_id": payment_id,
            "purchase_bill_id":    bill_id,
            "allocated_paise":     amt,
        })
        _adjust_bill_paid(db, firm_id, client_id, bill_id, amt, actor=actor)

    if alloc_payloads:
        privileged_for(db).table("purchase_payment_allocations").insert(alloc_payloads).execute()

    unallocated_paise = amount_paise - total_requested
    privileged_for(db).table("purchase_payments").update({"unallocated_paise": unallocated_paise}).eq("id", payment_id).eq("firm_id", firm_id).eq("client_id", client_id).execute()

    log_event(
        firm_id or "", "purchase_payment", payment_id, "update",
        actor_id=(actor or {}).get("auth_user_id"), actor_email=(actor or {}).get("email"),
        new_data={"allocations": alloc_payloads, "unallocated_paise": unallocated_paise},
    )
    return {"payment_id": payment_id, "allocations": alloc_payloads, "unallocated_paise": unallocated_paise}
