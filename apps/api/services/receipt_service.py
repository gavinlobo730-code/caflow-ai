"""
Receipt service — the single customer-receipt engine.

Phase 4.6 extraction: the receipt-creation core (validation → receipt number →
insert → invoice AR update (paid_paise/status) → allocations → journal posting →
audit → timeline) previously lived inline in routers/receipts.py. It is moved
here VERBATIM (behaviour-preserving) so that BOTH the staff receipts router AND
the online-payment success path call the exact same engine — no duplicated
receipt math, no parallel AR. Online payments create a receipt ONLY through
create_receipt_core; a payment gateway never performs any accounting itself.

All monetary values are integer paise.
"""
import os
import uuid
import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from domain.accounting.payment_account import resolve_payment_account
from core.db_provider import privileged_for
from services.audit_service import log_event
from services.document_header_writer import update_header
from services.ledger_door import ledger_rpc
from services.period_validation_service import period_validation_service
from services import named_row_ownership
from services import period_lock_service
from services.timeline_service import timeline_service
from services.numbering import sequence_after
from core.ist_clock import fy_code, ist_fy_label, ist_today
from core.observability import capture_soft_failure
from domain.money_text import minor_units_text
from domain.money_sentence import rupee_text, rupee_whole_text

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.receipt_service")

# In-memory mock stores (re-exported by routers.receipts for backward compat;
# also read by collections_service). Same list objects everywhere they appear.
MOCK_RECEIPTS: list[dict] = []
MOCK_RECEIPT_ALLOCATIONS: list[dict] = []


def _is_unique_violation(err: Exception) -> bool:
    """True when a Postgres/PostgREST error is a unique-constraint violation
    (23505) — used to recognise a receipt_no collision against migration 159's
    UNIQUE (firm_id, client_id, receipt_no) constraint."""
    s = str(err).lower()
    return "23505" in s or "duplicate key" in s or "already exists" in s


def _is_missing_rpc_function(err: Exception) -> bool:
    """True only for PostgREST/Postgres's OWN 'no such function' signature —
    deliberately does NOT match on the function's own name (adversarial-review
    fix, R2.12): settle_receipt_atomic's legitimate business-rule
    RAISE EXCEPTIONs (invoice-not-found, exceeds-outstanding) are themselves
    prefixed with 'settle_receipt_atomic: ...', so a bare substring check on
    that name previously misclassified those as 'migration not applied' —
    masking the real error with a false diagnosis, including for a genuine
    concurrent-race exceeds-outstanding case this milestone was built to
    handle correctly."""
    s = str(err).lower()
    return "pgrst202" in s or ("function" in s and ("does not exist" in s or "could not find the function" in s))






def _advance_treatment(db, firm_id: str, client_id: str, data: dict) -> tuple:
    """(gst_rate_bps, place_of_supply, is_interstate) for a GSTR-1 Table 11A row.

    THE SPLIT IS DERIVED HERE, NOT TAKEN FROM THE REQUEST. The receipt form
    computed `advancePos !== clientStateCode` in the browser and this service
    stored the answer verbatim — a statutory rule (IGST §§7-8) on the wrong
    side of the wire, and wrong outright for a client whose `state_code` is
    NULL, where every advance came out inter-state and put IGST in Table 11A
    against CGST and SGST due.

    `domain/gst/place_of_supply.py` is the rule and may answer None; None is
    stored as None, because `gst_advance_service` already names an advance it
    cannot declare and an undecided treatment belongs in that list rather than
    in a default. The invoice path derives the same fact the same way.
    """
    from domain.gst.place_of_supply import is_interstate as _is_interstate
    rate = data.get("gst_rate_bps")
    pos = data.get("place_of_supply")
    client = None
    try:
        rows = (db.table("clients").select("gstin, state_code")
                .eq("id", client_id).eq("firm_id", firm_id).limit(1).execute().data) or []
        client = rows[0] if rows else None
    except Exception as exc:                                       # noqa: BLE001
        # A read that fails must not stop a receipt being recorded. The
        # treatment is then undecided, which is the honest answer and the one
        # the advances report already reports — but it is REPORTED rather than
        # swallowed, because an advance that quietly stops being declarable is
        # exactly the class of silent truth-loss capture_soft_failure exists
        # for: the receipt still saves and Table 11A quietly loses a row.
        capture_soft_failure(exc, operation="advance_treatment_client_lookup",
                             firm_id=firm_id, client_id=client_id)
        client = None
    return rate, pos, _is_interstate(client, pos)


def _next_receipt_seq(db, firm_id: str, client_id: str, fy: str) -> int:
    from services.numbering import next_sequence
    return next_sequence(db, "receipts", f"RCPT-{fy}-",
                         firm_id=firm_id, client_id=client_id)


def _assert_open_where_a_receipt_feeds_a_return(db, firm_id: str, client_id: str,
                                                receipt_date: str) -> None:
    """The portal lock, for the clients whose receipts reach a filed return.

    SALES-15. Both receipt paths ask `period_validation_service` — the CA's own
    financial-year lock — and deliberately NOT `period_lock_service.assert_open`,
    the portal one, on the argument that "a receipt moves Bank and Debtors and
    touches no output tax". That argument was right when it was written and
    GST-15 falsified half of it.

    For a client marked `gst_advance_tax_applicable`, a receipt IS a document
    that feeds a return: CGST s.13(2) puts the time of supply for SERVICES at
    the earlier of invoice or payment, so `gst_advance_service.table_11_sections`
    declares the advance in GSTR-1 Table 11A and `gst_return_service` carries the
    same buckets into GSTR-3B Table 3.1(a). A receipt dated 20 June and entered
    on 15 July — after June's GSTR-1 was filed on the 11th — changes what June's
    Table 11A should have said, with nothing refusing it and nothing recording
    why.

    IT IS UNCONDITIONAL ON THE RECEIPT'S OWN SHAPE, for the reason the fixed
    asset's acquisition is (CLAUDE.md): a rule that depends on which fields
    happen to be filled in is not a rule. It would be tempting to ask only where
    the receipt leaves an unallocated balance, and that would be wrong twice
    over. `table_11_sections` measures what was adjusted BY THE PERIOD END using
    the allocation's `created_at`, so a back-dated receipt allocated in full
    today has no allocations dated inside June and its WHOLE amount lands in
    June's 11A. And a receipt with no rate or place of supply is not silently
    dropped either — it is NAMED in that return's `gaps`, which is also part of
    what was filed.

    EVERY OTHER CLIENT IS UNTOUCHED, and that is the point: the flag is off by
    default (Notification 66/2017-Central Tax removed the charge on advances for
    GOODS), so the original argument still governs the ordinary case — recording
    a payment received on 20 June on 15 July stays an ordinary thing to do.

    TWO QUESTIONS, IN ONE HELPER BECAUSE BOTH DOORS ALREADY ASK IT (POST-A-316):
    the CLOSURES (the client's finalised year-end), asked of every client and
    first; then the filed-return lock, for the clients above only. They are
    different questions with different scopes, and a door that asked the second
    and not the first let a receipt into a year the CA had finalised.

    WHAT WOULD CHANGE THIS AGAIN: a filing type whose figures depend on the
    balance sheet or on collections — an ITR, a tax audit report, GSTR-9 — being
    recorded in public.filings. `gst_filing_record_service.FILING_TYPE_*` is the
    list; when it grows past the two GST returns, this decision has to be taken
    a third time.
    """
    if db is None:
        return
    # THE CLOSURES COME FIRST AND ARE ASKED OF EVERY CLIENT (POST-A-316). The firm's locked year is the validator's, asked by
    # the door above; this is the CLIENT's finalised year-end, which a plain rupee receipt never reached because it posts
    # through `settle_receipt_atomic` and not through the kernel that asks `closure_reason` for every other posting. Nothing
    # about it depends on the receipt's shape or on the client's advance-tax flag: a finalised year is the CA saying these
    # books are finished. It is asked here, before a number is taken or a row is written, with the closure's own sentence
    # (it names the remedy: reopen the year), and asked again by the database function itself (migration 533), which is what
    # a direct call reaches. The FILED-RETURN branch is the part below and stays gated on the flag.
    period_lock_service.assert_not_closed(db, firm_id or "", client_id, receipt_date)
    from services.gst_advance_service import advance_tax_applicable
    if not advance_tax_applicable(db, firm_id or "", client_id):
        return
    period_lock_service.assert_open(db, firm_id or "", client_id, receipt_date)


def create_foreign_receipt(firm_id: str, data: dict, actor: dict, db) -> dict:
    """Foreign customer receipt with realized FX (Multi-Currency Phase 4).

    Each allocated invoice is relieved at ITS frozen booking rate (R0); the cash is
    taken at the receipt's rate (R1); the difference posts to Realized FX Gain/Loss
    in ONE balanced journal, written with the receipt, its allocations and the
    invoices' settlement by the database function a rupee receipt uses
    (`settle_receipt_atomic`, migration 781). Foreign settled amounts are tracked
    on the invoice (paid_txn) so partial settlements never drift and the final
    settlement clears the base exactly. Original documents/rates are never modified.
    Supports partial / multiple / over-payment (the unallocated excess is a customer
    advance carried at R1)."""
    from domain.currency.conversion import to_base_minor
    from services.phase2_journal_service import phase2_journal_service as K

    client_id = data["client_id"]
    ccy = (data.get("currency") or "").strip().upper()
    if int(data.get("tds_paise", 0) or 0) != 0:
        raise HTTPException(status_code=422, detail="TDS on a foreign receipt is not supported yet.")
    period_validation_service.validate_posting_date(firm_id or "", data["receipt_date"])
    _assert_open_where_a_receipt_feeds_a_return(db, firm_id, client_id, data["receipt_date"])

    minor = _foreign_receipt_minor_unit(db, firm_id, client_id, ccy)
    R1, r1_source, overridden = _foreign_receipt_rate(K, db, data, ccy)

    total_foreign = int(data["amount_paise"])   # foreign cash received (minor units)
    allocations = _one_allocation_per_invoice(data.get("allocations", []))

    total_foreign_settled = sum(int(a["allocated_paise"]) for a in allocations)
    cash_base = to_base_minor(total_foreign, R1, minor)
    settled_cash_base = to_base_minor(total_foreign_settled, R1, minor)
    unalloc_base = cash_base - settled_cash_base

    # The FOREIGN-currency receipt has the same defect as the rupee one, and the
    # finding did not name it: a firm-wide Bank ledger regardless of which
    # account received the money or whether it was cash.
    paid_into = resolve_payment_account(
        db, firm_id=firm_id, client_id=client_id,
        bank_account_id=data.get("bank_account_id"),
        payment_mode=data.get("payment_mode"),
        find_account=K._find_account)
    bank_id = paid_into.account_id
    ar_id = K._find_account(db, firm_id, client_id, "%Trade Receivable%", system_key="ar")
    # The FY of the NUMBER comes from the DOCUMENT'S OWN DATE, not from today
    # (SALES-24) — see core.ist_clock.fy_code. The number itself is taken per attempt, below.
    fy = fy_code(data["receipt_date"])
    # task #102: pre-generated (matching create_receipt_core's atomic-path
    # convention) so the journal can carry source_type/source_id back to this
    # receipt, for reverse_receipt / any future source_id-keyed lookup.
    receipt_id = str(uuid.uuid4())
    # ONE TRANSACTION (POST-A-095, migration 781). This path used to post the entry through the kernel, then insert the receipt, then
    # update each invoice with a compare-and-set it retried, then write the allocations and the realised-difference record, and on a
    # failure compensate (reverse the entry, delete the receipt). Under a real race an earlier invoice's paid amount stayed when a later
    # one failed. The entry, the receipt, every invoice it settles and the realised difference now go to the database function a rupee
    # receipt uses, which writes all of them or none. The rupee figures are worked out below, per attempt, from a read of each invoice
    # taken before that transaction, so each allocation says what the read saw and the function refuses the whole receipt if the
    # invoice, once locked, no longer says the same.
    actor_id = (actor or {}).get("id")
    now_iso = datetime.now(timezone.utc).isoformat()
    rate_date = str(data["receipt_date"])[:10]
    entry_payload = {
        "firm_id": firm_id, "client_id": client_id, "entry_date": data["receipt_date"],
        "entry_type": "Receipt", "is_posted": True, "status": "posted",
        "posted_at": now_iso, "posted_by": actor_id, "created_by": actor_id,
        "source_type": "receipt", "source_id": receipt_id,
    }
    # Rate-selection provenance, as the kernel stamps it: only when a rate was actually chosen.
    if overridden:
        entry_payload["rate_overridden"] = True
    if actor_id is not None:
        entry_payload["rate_selected_by"] = actor_id
        entry_payload["rate_selected_at"] = now_iso
    _adv_rate, _adv_pos, _adv_interstate = _advance_treatment(
        db, firm_id, client_id, data)
    receipt_payload = {
        "id": receipt_id,
        "firm_id": firm_id, "client_id": client_id, "customer_id": data["customer_id"],
        "receipt_date": data["receipt_date"],
        "amount_paise": cash_base, "tds_paise": 0, "unallocated_paise": unalloc_base,
        "payment_mode": data.get("payment_mode", ""), "reference_no": data.get("reference_no", ""),
        "notes": data.get("notes", ""),
        # The account the money was paid into: the journal above resolved its cash leg from it, so the receipt row has to say so too, or
        # the Receipts tab tells a CA the receipt went to the general Bank ledger when the journal debited the bank they chose.
        "bank_account_id": data.get("bank_account_id"),
        # GSTR-1 Table 11A — see the note on the other receipt payload. A
        # foreign-currency advance can bear tax under s.13(2) exactly as a
        # rupee one can, so this path carries them too.
        "gst_rate_bps": _adv_rate,
        "place_of_supply": _adv_pos,
        "is_interstate": _adv_interstate,
        "created_at": now_iso,
        "txn_currency": ccy, "exchange_rate": str(R1), "txn_amount": total_foreign,
        "rate_source": r1_source, "rate_type": "booking", "rate_date": rate_date,
        "rate_selected_by": actor_id, "rate_overridden": overridden,
    }

    # WHAT DEPENDS ON A READ IS WORKED OUT PER ATTEMPT: the receipt's number and the plan. The rupees each invoice is relieved of come
    # from its own booking rate and from what was already paid when it was read, so the receivable's credit, the realised difference and
    # each allocation's expectation are built from one read and handed to the function with it. If the function finds an invoice moved
    # since that read it refuses the whole receipt and writes nothing, and the receipt is prepared again: a fresh number, a fresh read,
    # a new plan, the same id. The NUMBER is taken per attempt for the commonest race of all, two receipts of one client recorded at the
    # same moment: both read the same last number, the second is refused for the duplicate before any invoice is looked at, and taking
    # the next number is all it needs. A receipt that keeps losing either way is refused in words after FOREIGN_RECEIPT_ATTEMPTS.
    attempt = 0
    refused_number = None
    while True:
        attempt += 1
        seq = _next_receipt_seq(db, firm_id, client_id, fy)
        receipt_no = f"RCPT-{fy}-{seq:04d}"
        settle_plan, total_ar_relieved = _plan_foreign_settlement(db, firm_id, client_id, ccy, minor, allocations)
        if total_foreign_settled > total_foreign:
            raise HTTPException(status_code=422, detail="Allocated foreign exceeds the receipt amount.")
        fx_diff = settled_cash_base - total_ar_relieved   # + gain / − loss (receivable)
        lines = [
            {"account_id": bank_id, "debit_paise": cash_base, "credit_paise": 0,
             "narration": ("Cash received (foreign)" if paid_into.source == "cash"
                           else "Bank receipt (foreign)"), "txn_debit": total_foreign, "txn_credit": 0},
            {"account_id": ar_id, "debit_paise": 0, "credit_paise": total_ar_relieved + unalloc_base,
             "narration": "Trade receivable settled at booked rate", "txn_debit": 0, "txn_credit": total_foreign},
        ]
        this_receipt = {**receipt_payload, "receipt_no": receipt_no}
        this_entry = {**entry_payload, "reference_no": receipt_no, "narration": f"Receipt {receipt_no} (foreign) from customer"}
        if fx_diff != 0:
            fx_id = K._find_account(db, firm_id, client_id, "%Foreign Exchange%", system_key="fx_realized")
            lines.append({"account_id": fx_id, "debit_paise": max(-fx_diff, 0), "credit_paise": max(fx_diff, 0),
                          "narration": "Realized FX gain" if fx_diff > 0 else "Realized FX loss", "txn_debit": 0, "txn_credit": 0})
            # The record of the realised difference, written by the function with everything else.
            this_receipt["fx_adjustment"] = {
                "settlement_rate": str(R1), "base_delta_paise": fx_diff, "rate_source": r1_source, "created_by": actor_id,
            }
        try:
            result = ledger_rpc(db, "settle_receipt_atomic", {
                "p_receipt": this_receipt,
                "p_journal_entry": this_entry,
                # Dual storage, as the kernel writes it: the rupee amount stays authoritative, the foreign amount and the rate sit beside it.
                "p_journal_lines": [{**l, "txn_currency": ccy, "base_currency": "INR", "exchange_rate": str(R1),
                                     "rate_source": r1_source, "rate_type": "booking", "rate_date": rate_date} for l in lines],
                "p_allocations": [
                    {"sales_invoice_id": inv["id"], "allocated_paise": ar_relieved, "allocated_txn": f,
                     # what the read saw of the invoice: the function compares it with the locked row
                     "expect_paid_paise": int(inv.get("paid_paise") or 0), "expect_paid_txn": int(inv.get("paid_txn") or 0),
                     "expect_credited_paise": int(inv.get("credited_paise") or 0)}
                    for (inv, f, ar_relieved) in settle_plan
                ],
            }, firm_id=firm_id, client_id=client_id).execute()
            break
        except Exception as e:
            # Both refusals are the function's own and leave nothing written (it is one transaction), so preparing the receipt again
            # builds on nothing of the attempt that lost.
            if _is_unique_violation(e):
                if receipt_no == refused_number:
                    # The series still offers the number that was just refused, so no RECEIPT took it: something else in this
                    # client's books carries it (a journal typed with that reference on that date, say). Taking it again cannot
                    # work, and "please retry" would be untrue.
                    raise HTTPException(status_code=409, detail=receipt_number_carried_elsewhere(receipt_no)) from e
                refused_number = receipt_no
            if (_invoice_changed_under_the_receipt(e) or _is_unique_violation(e)) and attempt < FOREIGN_RECEIPT_ATTEMPTS:
                continue
            refusal = _foreign_receipt_refusal(e)
            if refusal is e:
                raise
            raise refusal from e

    out = result.data or {}
    receipt_id = out.get("receipt_id") or receipt_id
    entry_id = out.get("journal_entry_id")
    alloc_rows = [
        {"receipt_id": receipt_id, "sales_invoice_id": r.get("sales_invoice_id"),
         "allocated_paise": r.get("allocated_paise"), "allocated_txn": r.get("allocated_txn")}
        for r in (out.get("allocations") or [])
    ]
    receipt = {**receipt_payload, "receipt_no": receipt_no, **(out.get("receipt") or {}), "id": receipt_id, "journal_entry_id": entry_id}

    log_event(firm_id, "receipt", receipt_id, "create", actor_id=(actor or {}).get("auth_user_id"),
              actor_email=(actor or {}).get("email"), new_data={"amount_paise": cash_base, "currency": ccy})
    return {**_with_allocated_total(receipt, alloc_rows), "allocations": alloc_rows, "journal_entry_id": entry_id, "realized_fx_paise": fx_diff}


def _foreign_receipt_minor_unit(db, firm_id: str, client_id: str, ccy: str) -> int:
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


def _one_allocation_per_invoice(rows: list) -> list:
    """One allocation per INVOICE. Two rows for one invoice were each planned from the same read of it, so the second could not be the
    one that clears the invoice and its rupees were not snapped to what was left: the invoice ended 'paid' with a rounding residue."""
    per_invoice: dict = {}
    for a in rows:
        if int(a.get("allocated_paise", 0) or 0) > 0:
            per_invoice[a.get("sales_invoice_id")] = per_invoice.get(a.get("sales_invoice_id"), 0) + int(a["allocated_paise"])
    return [{"sales_invoice_id": k, "allocated_paise": v} for k, v in per_invoice.items()]


def _foreign_receipt_rate(K, db, data: dict, ccy: str):
    """The rate the cash is taken at: (rate, where it came from, whether a person typed it). A typed rate wins; otherwise the booking
    rate on the receipt's own date. A rate that cannot be read, is not held or is not positive is refused in words."""
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
            q = K.exchange_rate_service(db).get_quote(ccy, "INR", _date.fromisoformat(str(data["receipt_date"])[:10]), "booking")
        except RateNotFound as _cause:
            raise HTTPException(status_code=422, detail=f"No exchange rate available for {ccy}->INR on {data['receipt_date']}.") from _cause
        rate, source = q.rate, q.source
    if rate <= 0:
        raise HTTPException(status_code=422, detail="Exchange rate must be positive.")
    return rate, source, overridden


#: How many times a foreign receipt is planned from a fresh read of its invoices before it is refused. Each attempt is one whole
#: transaction that writes everything or nothing, so a later attempt never builds on a part of an earlier one.
FOREIGN_RECEIPT_ATTEMPTS = 3


def _plan_foreign_settlement(db, firm_id: str, client_id: str, ccy: str, minor: int, allocations: list) -> tuple[list, int]:
    """What a foreign receipt settles of each invoice, from a read of the invoice as it stands now.

    Returns ([(invoice row, foreign amount, rupees relieved)], total rupees relieved). Each invoice is relieved at ITS OWN booking rate,
    and the rupees are snapped to what is left of it when the foreign amount clears it, so a part-settled invoice never ends paid with a
    rounding residue. The rows are a READ: the function that records the receipt compares each with the invoice once it holds the lock
    (migration 781) and refuses the receipt if it moved."""
    from decimal import Decimal
    from domain.currency.conversion import to_base_minor
    plan, total_ar_relieved = [], 0
    for a in allocations:
        inv_id = a.get("sales_invoice_id")
        inv = (db.table("client_sales_invoices")
               .select("id, status, txn_currency, exchange_rate, total_paise, paid_paise, paid_txn, credited_paise, debit_note_paise, txn_total")
               .eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data or [None])[0]
        if not inv:
            raise HTTPException(status_code=422, detail=f"Invoice {inv_id} is not part of this client's books.")
        if inv.get("status") in ("draft", "cancelled"):
            raise HTTPException(status_code=422,
                detail=f"Invoice {inv_id} is {inv.get('status')} and cannot receive a payment.")
        if (inv.get("txn_currency") or "INR").upper() != ccy:
            raise HTTPException(status_code=422, detail=(
                f"Currency mismatch: receipt is {ccy} but invoice {inv_id} is billed in {inv.get('txn_currency')}."))
        R0 = Decimal(str(inv.get("exchange_rate") or 1))
        base_out = int(inv["total_paise"]) - int(inv.get("paid_paise") or 0) - int(inv.get("credited_paise") or 0)
        foreign_out = int(inv.get("txn_total") or 0) - int(inv.get("paid_txn") or 0)
        f = int(a["allocated_paise"])
        if f > foreign_out:
            raise HTTPException(status_code=422, detail=(
                f"Allocation {minor_units_text(f, minor)} exceeds invoice {inv_id} outstanding {minor_units_text(foreign_out, minor)} {ccy}."))
        # Snap the base to clear exactly on full settlement — no rounding drift.
        ar_relieved = base_out if f == foreign_out else to_base_minor(f, R0, minor)
        # The RUPEES this would relieve must still be owed. They can run out before the foreign amount does: a credit note on a foreign
        # invoice lowers what is owed in rupees and not the foreign outstanding. The function asks the same of the locked row and would
        # refuse in a log's words; this says it to the person. (A sales debit note raises what is collectible, as the function counts it.)
        rupees_owed = base_out + int(inv.get("debit_note_paise") or 0)
        if ar_relieved > rupees_owed:
            why = "A credit note has reduced what is owed. " if int(inv.get("credited_paise") or 0) > 0 else ""
            raise HTTPException(status_code=422, detail=(
                f"Invoice {inv_id} has {rupee_text(max(rupees_owed, 0))} left to settle in rupees, less than this allocation of "
                f"{minor_units_text(f, minor)} {ccy} would settle at the invoice's own rate ({rupee_text(ar_relieved)}). "
                f"{why}Allocate a smaller amount to this invoice."))
        plan.append((inv, f, ar_relieved))
        total_ar_relieved += ar_relieved
    return plan, total_ar_relieved


def _foreign_receipt_refusal(e: Exception) -> Exception:
    """What to raise for a failure of the function that records a foreign receipt: the error in a person's words where it is a known
    refusal, and the error itself (so the caller re-raises it untouched) where it is not."""
    if _is_missing_rpc_function(e):
        return RuntimeError(
            "settle_receipt_atomic RPC not found — migrations 160/162 and 781 "
            "(apps/api/migrations/781_a_foreign_currency_receipt_is_recorded_in_one_transaction_by_the_function_that_records_a_rupee_one.sql) "
            "must be applied to this database before the API is deployed."
        )
    if _is_unique_violation(e):
        return HTTPException(status_code=409, detail="A receipt numbering collision was detected; please retry.")
    if _invoice_changed_under_the_receipt(e):
        # Another receipt or a credit note reached one of these invoices between each read and the function's lock, every time. Nothing
        # was written (the function is one transaction); the person is asked to look at what is still owed and record it again.
        return HTTPException(status_code=409, detail=FOREIGN_RECEIPT_RACE_SENTENCE)
    refusal = period_lock_service.closure_sentence_in(e)
    if refusal:
        return HTTPException(status_code=422, detail=refusal)
    return e


def receipt_number_carried_elsewhere(receipt_no: str) -> str:
    """What a person reads when the number a receipt would take is refused as a duplicate and no receipt carries it."""
    return (f"The number this receipt would take, {receipt_no}, is already carried by another entry in this client's books "
            "(a journal typed with that reference on the same date, for example), so the receipt cannot be recorded under it. "
            "Nothing was recorded. Change that entry's reference, or record the receipt under another date.")


def rupee_receipt_against_a_foreign_invoice(invoice: str, currency: str) -> str:
    """What a person reads when a receipt in rupees names an invoice billed in another currency (POST-A-576)."""
    return (f"Invoice {invoice} is billed in {currency}, and this receipt is in rupees. Record the receipt in {currency}, with the "
            "rate the money was received at, so the invoice's own amount is settled and the exchange difference is recorded. "
            "Nothing was recorded.")


#: The state migration 781's function raises when an invoice no longer reads as the plan read it.
INVOICE_MOVED_STATE = "RC001"

#: What a person reads when two receipts (or a receipt and a credit note) reached the same invoice at the same moment.
FOREIGN_RECEIPT_RACE_SENTENCE = (
    "One of these invoices was settled or credited by somebody else while this receipt was being recorded. "
    "Nothing was recorded. Open the receipt again, so it shows what is still owed, and record it again.")


def _invoice_changed_under_the_receipt(err: Exception) -> bool:
    """The receipt function's refusal of a foreign receipt whose invoice moved after it was read (migration 781): its own state
    RC001, or its own words where the client lost the code. Deliberately not serialization_failure (40001), which PostgREST re-runs
    by itself; the migration says why."""
    from core.exceptions import _sqlstate
    return _sqlstate(err) == INVOICE_MOVED_STATE or "changed while this receipt was being prepared" in str(err)


def _compensate_failed_settlement(
    db, firm_id: str, client_id: str, receipt_id: str, journal_id, actor: dict,
    attempted_invoice_ids: list,
) -> None:
    """F7 hardening: undo a receipt whose AR settlement failed AFTER the journal
    and receipt row were already committed.

    Reachable only via a genuine CONCURRENT settlement race on one of the
    allocated invoices (CAS exhaustion) — a same-request over-allocation is now
    rejected by upfront validation before anything posts, so it can no longer
    reach this point. Reverses the journal (append-only — the kernel's standard
    reversal path) and deletes the now-orphaned receipt row, so the failed
    operation leaves no phantom cash/AR entry for a receipt the caller was told
    failed. Best-effort: if compensation itself fails, log loudly rather than
    mask the original error — a human must reconcile.

    Residual gap (tracked under roadmap R2.12 — full receipt/AR/journal
    atomicity): if this receipt allocated to MULTIPLE invoices and an EARLIER
    invoice's compare-and-set already succeeded before a LATER one failed, that
    earlier invoice's paid_paise/status is not rolled back here (safely reverting
    a concurrent CAS write requires its own transaction). `attempted_invoice_ids`
    is logged so that residual case is visible for manual review.

    R2.9 adversarial review finding (CONFIRMED): phase2_journal_service._create_journal
    has an idempotency fast-path (_find_existing) keyed only on
    (firm_id, client_id, reference_no, entry_date) — no receipt id involved. When two
    receipts race to the same auto-generated receipt_no (the exact scenario migration
    159's UNIQUE constraint now catches), the LOSING request's journal_for_receipt call
    can match the WINNING request's already-committed journal via that fast-path and
    receive ITS journal_entry_id back — not a journal of its own. Blindly reversing
    that journal here would corrupt the winning receipt's already-settled, successful
    books. So before reversing, confirm no OTHER receipt already claims this exact
    journal_id — if one does, the journal belongs to that other, successful receipt and
    must be left alone; only this (failed) attempt's own artifacts are cleaned up.
    """
    try:
        if journal_id:
            owned_by_another = (
                db.table("receipts").select("id")
                .eq("journal_entry_id", journal_id).neq("id", receipt_id)
                .limit(1).execute().data
            )
            if owned_by_another:
                _logger.warning(
                    "R2.9: skipping journal reversal for journal=%s (firm=%s client=%s) — "
                    "it belongs to another already-committed receipt (%s), not this failed "
                    "attempt (receipt=%s); reversing it would corrupt that other receipt's "
                    "books. Only this attempt's own artifacts are being cleaned up.",
                    journal_id, firm_id, client_id, owned_by_another[0].get("id"), receipt_id,
                )
            else:
                from services.phase2_journal_service import phase2_journal_service
                phase2_journal_service.reverse_entry(
                    db, firm_id, journal_id, str(ist_today()),
                    narration=f"Compensating reversal — receipt {receipt_id} settlement failed",
                    created_by=(actor or {}).get("id"),
                )
        privileged_for(db).table("receipts").delete().eq("id", receipt_id).eq("firm_id", firm_id).eq("client_id", client_id).execute()
        _logger.warning(
            "F7 compensation applied: reversed journal=%s and deleted receipt=%s "
            "(firm=%s client=%s) after a settlement failure. Invoices touched this "
            "request: %s — verify none were left partially settled without this receipt.",
            journal_id, receipt_id, firm_id, client_id, attempted_invoice_ids,
        )
    except Exception as e:
        from core.observability import capture_posting_failure
        capture_posting_failure(
            e, operation="receipt_service._compensate_failed_settlement",
            firm_id=firm_id, client_id=client_id, receipt_id=receipt_id, journal_id=journal_id,
            attempted_invoice_ids=attempted_invoice_ids,
        )


def _with_allocated_total(receipt: dict, allocations: list) -> dict:
    """The receipt as the database now holds it: `allocated_paise` is the sum of the allocation rows written for it (migration 571 keeps that
    figure with a trigger on those rows). Every path inserts the receipt FIRST, with the column at its default of 0, and the allocations after
    it, so the row a path holds in hand says 0 beside allocation lines that cover it; the response and the edit-log event are built from this
    copy instead, and a receipt created with no allocation still says 0."""
    return {**receipt, "allocated_paise": sum(int(a.get("allocated_paise") or 0) for a in allocations)}


def _settle_receipt_via_atomic_rpc(
    db, firm_id: str, client_id: str, receipt_payload: dict, allocations: list, actor: dict,
) -> dict:
    """R2.12: post the journal, the receipt row, and every allocation's invoice
    row-locked update in ONE database transaction via settle_receipt_atomic
    (migration 160) — see that migration's docstring for why this supersedes
    the journal-first + compensate pattern for the plain-INR receipt path. Any
    failure (bad account, receipt_no collision, over-allocation) rolls back
    the WHOLE transaction; nothing partial is ever left to compensate.
    """
    from services.phase2_journal_service import phase2_journal_service

    lines = phase2_journal_service.receipt_journal_lines(db, receipt_payload, firm_id, client_id)
    entry_date = receipt_payload["receipt_date"]
    actor_id = (actor or {}).get("id")
    now_iso = datetime.now(timezone.utc).isoformat()
    entry_payload = {
        "firm_id": firm_id, "client_id": client_id, "entry_date": entry_date,
        "reference_no": receipt_payload["receipt_no"],
        "narration": f"Receipt {receipt_payload['receipt_no']} from customer",
        "entry_type": "Receipt", "is_posted": True, "status": "posted",
        "posted_at": now_iso, "posted_by": actor_id, "created_by": actor_id,
        # task #102: lets reverse_receipt (services/reversal_service) — and any
        # future source_id-keyed lookup — trace this journal back to its receipt.
        "source_type": "receipt", "source_id": receipt_payload["id"],
    }
    line_payloads = [
        {
            "account_id": l["account_id"], "debit_paise": l["debit_paise"],
            "credit_paise": l["credit_paise"], "narration": l.get("narration", ""),
            "txn_currency": "INR", "base_currency": "INR", "exchange_rate": "1",
            "txn_debit": l["debit_paise"], "txn_credit": l["credit_paise"],
            "rate_source": "identity", "rate_type": "booking", "rate_date": entry_date,
        }
        for l in lines
    ]
    alloc_payloads = [
        {"sales_invoice_id": a.get("sales_invoice_id"), "allocated_paise": int(a.get("allocated_paise", 0) or 0)}
        for a in allocations
        if a.get("sales_invoice_id") and int(a.get("allocated_paise", 0) or 0) > 0
    ]

    try:
        # POST-A-317: the privileged client, after the route's own checks (services/ledger_door.py says why and what stays asked).
        result = ledger_rpc(db, "settle_receipt_atomic", {
            "p_receipt": receipt_payload,
            "p_journal_entry": entry_payload,
            "p_journal_lines": line_payloads,
            "p_allocations": alloc_payloads,
        }, firm_id=firm_id, client_id=client_id).execute()
    except Exception as e:
        if _is_missing_rpc_function(e):
            raise RuntimeError(
                "settle_receipt_atomic RPC not found — migrations 160/162 "
                "(apps/api/migrations/160_atomic_receipt_settlement.sql, "
                "162_atomic_receipt_settlement_hardening.sql) must be applied to "
                "this database before the API is deployed."
            ) from e
        if _is_unique_violation(e):
            raise HTTPException(
                status_code=409,
                detail="A receipt numbering collision was detected; please retry.",
            ) from e
        # The database function asks the same closure question the door asked (migration 533); when it is the one that
        # speaks (a year closed between the two, or a call that skipped the door) the person reads the sentence, not a failure.
        refusal = period_lock_service.closure_sentence_in(e)
        if refusal:
            raise HTTPException(status_code=422, detail=refusal) from e
        raise

    out = result.data or {}
    receipt_id = out.get("receipt_id") or receipt_payload["id"]
    journal_id = out.get("journal_entry_id")
    alloc_results = out.get("allocations") or []
    # R2.12 fix phase: log the ACTUAL DB row (migration 162 returns it) rather
    # than reconstructing one from the Python-side payload, which silently
    # omitted DB-default columns (allocated_paise, updated_at) the
    # pre-atomicity path's equivalent audit entries always included.
    db_receipt_row = out.get("receipt")

    receipt = {**receipt_payload, **(db_receipt_row or {}), "id": receipt_id, "journal_entry_id": journal_id}
    receipt = _with_allocated_total(receipt, alloc_results)

    log_event(
        firm_id or "", "receipt", receipt_id,
        "create", actor_id=actor.get("auth_user_id"),
        actor_email=actor.get("email"), new_data=receipt,
    )
    timeline_service.log_timeline_event(
        client_id=client_id,
        firm_id=firm_id or "",
        financial_year=ist_fy_label(receipt.get("receipt_date")),
        category="accounting",
        event_type="receipt_recorded",
        title=f"Receipt {receipt_payload.get('receipt_no', '')} recorded",
        description=f"Payment of {rupee_whole_text(receipt_payload['amount_paise'])} received from customer.",
        severity="success",
        entity_type="receipt",
        entity_id=receipt_id,
        amount_paise=receipt_payload["amount_paise"],
        actor_id=actor.get("auth_user_id"),
        actor_name=actor.get("email"),
    )

    receipt["allocations"] = [
        {
            "receipt_id": receipt_id,
            "sales_invoice_id": r.get("sales_invoice_id"),
            "allocated_paise": r.get("allocated_paise"),
        }
        for r in alloc_results
    ]
    return receipt


def _assert_the_customer_and_the_account_are_the_clients(db, firm_id, client_id: str, data: dict) -> None:
    """The customer a receipt names is in THIS client's books and active, and so is the account the money was paid into.

    The account is asked because `resolve_payment_account` reads it by firm alone: without this a receipt under one client naming
    another client's bank account posted to that client's bank ledger (the ledger trigger refused it later, as a 500) (POST-A-350)."""
    _cust = (db.table("customers").select("is_active")
             .eq("id", data["customer_id"]).eq("firm_id", firm_id or "").eq("client_id", client_id)
             .limit(1).execute().data)
    if not _cust:
        raise HTTPException(status_code=422, detail="This customer is not part of this client's books.")
    if _cust[0].get("is_active") is False:
        raise HTTPException(status_code=422, detail="This customer is inactive. Reactivate the customer before recording a receipt.")
    named_row_ownership.bank_account_is_the_clients(db, firm_id or "", client_id, data.get("bank_account_id"))


def _assert_invoices_can_take_a_rupee_receipt(db, firm_id: str, client_id: str, allocations: list) -> None:
    """Every invoice a rupee receipt names is this client's, is issued and live, and is billed in rupees. Asked before anything is
    written."""
    # F1 fix: allocations must reference THIS client's invoices (firm+client scope),
    # validated BEFORE the receipt is created so a foreign invoice id can never be
    # recorded or have its paid_paise mutated. A draft invoice was never issued
    # (no AR journal exists) and a cancelled one is terminal — neither can be
    # settled (task #227 audit finding).
    for _a in allocations:
        _inv = _a.get("sales_invoice_id")
        if _inv and int(_a.get("allocated_paise", 0) or 0) > 0:
            chk = (db.table("client_sales_invoices").select("id, status, txn_currency, invoice_no")
                   .eq("id", _inv).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute())
            if not chk.data:
                raise HTTPException(status_code=422, detail=f"Invoice {_inv} is not part of this client's books.")
            if chk.data[0].get("status") in ("draft", "cancelled"):
                raise HTTPException(status_code=422,
                    detail=f"Invoice {_inv} is {chk.data[0].get('status')} and cannot receive a payment.")
            # POST-A-576. A rupee receipt does not settle an invoice billed in a foreign currency: it would move the rupees paid and
            # leave the foreign amount paid at nothing, and the invoice would read "paid" by its rupee total with its whole foreign
            # amount still outstanding and no realised exchange difference recorded. The receipt function refuses the same
            # (migration 782); this says it to the person.
            _billed_in = (str(chk.data[0].get("txn_currency") or "").strip() or "INR").upper()
            if _billed_in != "INR":
                raise HTTPException(status_code=422, detail=rupee_receipt_against_a_foreign_invoice(
                    chk.data[0].get("invoice_no") or _inv, _billed_in))


def create_receipt_core(firm_id: str, data: dict, actor: dict, db) -> dict:
    """Create a customer receipt with optional invoice allocations — the single
    source of truth for receipt creation.

    - sum(allocations.allocated_paise) must be <= settlement (amount + TDS)
    - unallocated_paise = settlement - sum(allocated)
    - updates each allocated invoice's paid_paise + status (partially_paid/paid)
    - auto-creates the journal entry (Dr Bank / Cr Trade Receivables)
    - audit + timeline logged

    `db is None` selects the in-memory mock path. `actor` supplies audit/timeline
    attribution: {auth_user_id, email}. Returns the receipt dict (with allocations
    and, in real mode, journal_entry_id). Integer paise throughout.
    """
    client_id    = data["client_id"]

    # Ownership + business guard (task #227 audit finding): checked here, BEFORE
    # the foreign-receipt dispatch below, so a non-INR receipt can no longer
    # bypass it entirely — the old placement (after the dispatch) meant this
    # check never ran for any foreign-currency receipt at all. Scoped by
    # firm+client (customers.client_id is NOT NULL — every customer belongs to
    # exactly one client) and rejects when the customer can't be found in
    # THIS client's books at all, not just when found-but-inactive.
    if db is not None:
        _assert_the_customer_and_the_account_are_the_clients(db, firm_id, client_id, data)

    # ── Multi-Currency (Phase 4): a foreign receipt runs a dedicated realized-FX
    # path — each invoice is settled at ITS frozen booking rate, the cash is taken
    # at the receipt's rate, and the difference posts to Realized FX Gain/Loss. The
    # INR path below is byte-for-byte unchanged.
    _ccy_cols: dict = {}
    if db is not None and (data.get("currency") or "INR").strip().upper() != "INR":
        return create_foreign_receipt(firm_id, data, actor, db)
    amount_paise = data["amount_paise"]
    tds_paise    = int(data.get("tds_paise", 0) or 0)   # TDS deducted by client (§194J)
    settlement   = amount_paise + tds_paise              # value applied against invoices
    allocations  = data.get("allocations", [])

    # Validate allocation totals — integer arithmetic. Settlement includes TDS at source.
    total_allocated = sum(int(a.get("allocated_paise", 0)) for a in allocations)
    if total_allocated > settlement:
        raise HTTPException(
            status_code=422,
            detail=f"Total allocated ({rupee_text(total_allocated)}) exceeds settlement value "
                   f"({rupee_text(settlement)} = amount {rupee_text(amount_paise)} + TDS {rupee_text(tds_paise)})",
        )
    unallocated_paise = settlement - total_allocated

    # Posting date must not be in a locked financial year (migration 020).
    period_validation_service.validate_posting_date(firm_id or "", data["receipt_date"])

    # The portal lock is asked ONLY where a receipt feeds a return, which is a
    # narrower set than the invoice, credit-note and debit-note paths and a
    # wider one than this comment used to claim (SALES-15).
    #
    # It said: "A receipt moves Bank and Debtors and touches no output tax, and
    # the only filing types written to public.filings today are GSTR-1 and
    # GSTR-3B — returns of SUPPLIES, not of collections." The first clause
    # stopped being true when GST-15 landed. For a client marked
    # `gst_advance_tax_applicable`, CGST s.13(2) charges tax on an advance for
    # services WHEN IT IS RECEIVED, so the receipt is declared in GSTR-1
    # Table 11A and discharged in GSTR-3B Table 3.1(a) — the receipt IS the
    # document. For every other client, which is most of them, the argument is
    # unchanged and the refusal stands: recording a payment received on 20 June
    # on 15 July, after June's GSTR-1 was filed on the 11th, is an ordinary
    # thing to do and must not be blocked.
    #
    # `_assert_open_where_a_receipt_feeds_a_return` is where that is decided,
    # and its docstring carries the rest of the argument — including what would
    # change it a third time.
    _assert_open_where_a_receipt_feeds_a_return(db, firm_id, client_id, data["receipt_date"])

    # The FY of the NUMBER comes from the DOCUMENT'S OWN DATE, not from today
    # (SALES-24) — see core.ist_clock.fy_code.
    fy = fy_code(data["receipt_date"])

    if db is None:
        seq = sequence_after(
            (r.get("receipt_no") for r in MOCK_RECEIPTS
             if r["client_id"] == client_id), f"RCPT-{fy}-")
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
            "tds_paise":         tds_paise,
            "unallocated_paise": unallocated_paise,
            "payment_mode":      data.get("payment_mode", ""),
            "reference_no":      data.get("reference_no", ""),
            "notes":             data.get("notes", ""),
            "created_at":        datetime.now(timezone.utc).isoformat(),
        }
        MOCK_RECEIPTS.append(receipt)
        from services.phase2_journal_service import phase2_journal_service
        phase2_journal_service.journal_for_receipt(receipt, firm_id or "", client_id, created_by=(actor or {}).get("id"))
        return {**receipt, "allocations": allocations}

    _assert_invoices_can_take_a_rupee_receipt(db, firm_id, client_id, allocations)

    # F7 hardening: validate EVERY allocation against LIVE invoice outstanding
    # BEFORE posting anything (journal or receipt). Previously this check only ran
    # deep inside the settlement loop, AFTER the journal and receipt had already
    # committed — so a single over-allocated request left a phantom Dr Bank / Cr
    # Trade Receivables entry and a receipt row for an operation the API reported
    # as failed. Multiple allocation rows for the same invoice are summed so the
    # check reflects the whole request, not just one row at a time.
    _alloc_by_invoice: dict = {}
    for _a in allocations:
        _inv = _a.get("sales_invoice_id")
        _amt = int(_a.get("allocated_paise", 0) or 0)
        if _inv and _amt > 0:
            _alloc_by_invoice[_inv] = _alloc_by_invoice.get(_inv, 0) + _amt
    for _inv_id, _cum_amt in _alloc_by_invoice.items():
        _row = (db.table("client_sales_invoices").select("total_paise,paid_paise,credited_paise,debit_note_paise")
                .eq("id", _inv_id).eq("firm_id", firm_id).eq("client_id", client_id)
                .limit(1).execute().data)
        if not _row:
            continue  # already rejected by the ownership check above
        # (total + debit notes) is the true ceiling — a sales debit note
        # (CGST Act §34(3)) increases what the invoice can still collect.
        _total = int(_row[0].get("total_paise", 0)) + int(_row[0].get("debit_note_paise", 0) or 0)
        _credited = int(_row[0].get("credited_paise", 0) or 0)
        _paid = int(_row[0].get("paid_paise", 0) or 0)
        if _paid + _credited + _cum_amt > _total:
            raise HTTPException(status_code=422,
                detail=f"Invoice {_inv_id}: allocation would exceed invoice outstanding")

    seq = _next_receipt_seq(db, firm_id, client_id, fy)
    receipt_no = f"RCPT-{fy}-{seq:04d}"

    receipt_id = str(uuid.uuid4())
    _adv_rate, _adv_pos, _adv_interstate = _advance_treatment(
        db, firm_id, client_id, data)
    receipt_payload = {
        "id":                receipt_id,   # pre-generated so the GL journal, the receipt row and its allocations share one id
        "firm_id":           firm_id,
        "client_id":         client_id,
        "customer_id":       data["customer_id"],
        "receipt_no":        receipt_no,
        "receipt_date":      data["receipt_date"],
        "amount_paise":      amount_paise,
        "tds_paise":         tds_paise,
        "unallocated_paise": unallocated_paise,
        "payment_mode":      data.get("payment_mode", ""),
        # ReceiptIn.bank_account_id has been ACCEPTED BY THE API since the model
        # was written and dropped here — absent from this dict, so a caller that
        # supplied it got no error and no effect (SALES-08). Migration 342 gives
        # it a column; receipt_journal_lines resolves the ledger from it.
        "bank_account_id":   data.get("bank_account_id"),
        "reference_no":      data.get("reference_no", ""),
        "notes":             data.get("notes", ""),
        # GSTR-1 Table 11A (migration 286). Accepted by ReceiptIn and dropped
        # here until now — the columns existed, gst_advance_service read them,
        # and nothing wrote them, so Table 11 could never be anything but
        # empty. Same shape as bank_account_id above. NULL where the CA has not
        # supplied them, which is the state the advances report already names.
        "gst_rate_bps":      _adv_rate,
        "place_of_supply":   _adv_pos,
        "is_interstate":     _adv_interstate,
        "created_at":        datetime.now(timezone.utc).isoformat(),
        **_ccy_cols,
    }

    # R2.12: the real Supabase client always exposes .rpc, so production always
    # takes this atomic path — settle_receipt_atomic (migration 160) posts the
    # journal, the receipt row, and every allocation's invoice update in ONE
    # database transaction, so no partial state can ever be observed and no
    # app-level compensation is needed (there is nothing to compensate). Test
    # doubles without .rpc fall through to the pre-atomicity journal-first +
    # insert + CAS-retry path below, preserved byte-for-byte — the same
    # established fallback pattern as phase2_journal_service._create_journal's
    # own hasattr(db, "rpc") branch.
    if hasattr(db, "rpc"):
        return _settle_receipt_via_atomic_rpc(db, firm_id, client_id, receipt_payload, allocations, actor)

    # F7: post the GL journal FIRST — resolve the CoA accounts and post before any
    # AR mutation, so a missing-account / posting failure aborts here (the journal
    # helper now re-raises instead of swallowing) rather than leaving settled AR
    # with no GL entry. In mock mode the helper returns None (no GL) which is fine;
    # in real mode a failure propagates and nothing below runs.
    from services.phase2_journal_service import phase2_journal_service
    journal_id = phase2_journal_service.journal_for_receipt(
        receipt=receipt_payload,
        firm_id=firm_id or "",
        client_id=client_id,
        created_by=(actor or {}).get("id"),
    )
    if journal_id:
        receipt_payload["journal_entry_id"] = journal_id

    # F7/R2.9 hardening: the journal above is already committed, so from HERE ON
    # (starting with the receipt insert itself) a failure must be compensated
    # (journal reversed, receipt deleted) rather than left as a phantom GL
    # entry. This now also covers a receipt_no unique-constraint collision
    # (migration 159, R2.9) — previously impossible to hit since no constraint
    # existed, so the insert itself was never in this try block. With
    # allocations pre-validated above, the loop's own 422 is no longer
    # reachable on a single request; it now only fires under a genuine
    # concurrent settlement race (CAS exhaustion, 409), which the same
    # compensation below also covers.
    alloc_payloads = []
    _attempted_invoice_ids = [a.get("sales_invoice_id") for a in allocations if a.get("sales_invoice_id")]
    try:
        rcpt_resp  = privileged_for(db).table("receipts").insert(receipt_payload).execute()
        receipt    = rcpt_resp.data[0] if rcpt_resp.data else receipt_payload
        receipt_id = receipt.get("id", receipt_id)

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

            # H1 — lost-update prevention: read-modify-write on paid_paise is guarded by an
            # optimistic compare-and-set (UPDATE ... WHERE paid_paise = <value we read>). If
            # a concurrent receipt changed paid_paise between our read and write, the CAS
            # matches 0 rows and we re-read and retry, so concurrent settlements can never
            # lose an update or overshoot the invoice total.
            for _attempt in range(6):
                inv_resp = (
                    db.table("client_sales_invoices")
                    .select("total_paise,paid_paise,credited_paise,debit_note_paise,status")
                    .eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id)
                    .limit(1)
                    .execute()
                )
                if not inv_resp.data:
                    break
                inv = inv_resp.data[0]
                # (total + debit notes) is the true ceiling (CGST Act §34(3)).
                total    = int(inv.get("total_paise", 0)) + int(inv.get("debit_note_paise", 0) or 0)
                credited = int(inv.get("credited_paise", 0) or 0)   # credit notes already applied
                old_paid = int(inv.get("paid_paise", 0) or 0)
                new_paid = old_paid + alloc_amt
                # Fully settled when cash paid + credit notes reach the total; the allocation
                # may not push settlement past the total. (Defense-in-depth: pre-validated
                # above already, so this is now only reachable via a concurrent race.)
                if new_paid + credited > total:
                    raise HTTPException(status_code=422, detail=f"Invoice {inv_id}: allocation would exceed invoice outstanding")
                new_status = "paid" if (new_paid + credited) >= total else "partially_paid"
                upd = update_header(
                    db, "client_sales_invoices", inv_id, {"paid_paise": new_paid, "status": new_status},
                    firm_id=firm_id, client_id=client_id, actor=actor,
                    expect={"paid_paise": old_paid},   # compare-and-set guard
                    before={"paid_paise": old_paid, "status": inv.get("status")})
                if upd.data:
                    break                        # CAS won
            else:
                raise HTTPException(status_code=409,
                    detail=f"Invoice {inv_id} is being updated concurrently — please retry.")

        if alloc_payloads:
            privileged_for(db).table("receipt_allocations").insert(alloc_payloads).execute()
    except HTTPException:
        _compensate_failed_settlement(
            db, firm_id, client_id, receipt_id, journal_id, actor, _attempted_invoice_ids,
        )
        raise
    except Exception as e:
        _compensate_failed_settlement(
            db, firm_id, client_id, receipt_id, journal_id, actor, _attempted_invoice_ids,
        )
        if _is_unique_violation(e):
            raise HTTPException(
                status_code=409,
                detail="A receipt numbering collision was detected; please retry.",
            ) from e
        raise

    # (The GL journal was already posted above, BEFORE settling AR — see F7.)

    log_event(
        firm_id or "", "receipt", receipt_id,
        "create", actor_id=actor.get("auth_user_id"),
        actor_email=actor.get("email"), new_data=_with_allocated_total(receipt, alloc_payloads),
    )

    timeline_service.log_timeline_event(
        client_id=client_id,
        firm_id=firm_id or "",
        financial_year=ist_fy_label(receipt.get("receipt_date")),
        category="accounting",
        event_type="receipt_recorded",
        title=f"Receipt {receipt.get('receipt_no', '')} recorded",
        description=f"Payment of {rupee_whole_text(amount_paise)} received from customer.",
        severity="success",
        entity_type="receipt",
        entity_id=receipt_id,
        amount_paise=amount_paise,
        actor_id=actor.get("auth_user_id"),
        actor_name=actor.get("email"),
    )

    receipt["journal_entry_id"] = journal_id
    receipt["allocations"]      = alloc_payloads
    return _with_allocated_total(receipt, alloc_payloads)
