"""
Purchase payment service — the AP mirror of receipt_service.py's multi-bill
settlement engine.

routers/purchase_payments.py's create_purchase_payment endpoint (single-bill,
writes purchase_payments.purchase_bill_id) is UNCHANGED — this module ADDS
multi-bill allocation (purchase_payment_allocations, migration 226) alongside
it, without touching that existing path. Reached today from the Bank Match
Queue's multi-invoice bank allocation feature; reusable by any future
multi-bill "Record Payment" UI.

All monetary values are integer paise.
"""
import os
import uuid
import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from services.audit_service import log_event
from services.period_validation_service import period_validation_service
from services.timeline_service import timeline_service

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.purchase_payment_service")


def _current_fy() -> str:
    now = datetime.now(timezone.utc)
    if now.month >= 4:
        return f"{str(now.year)[2:]}{str(now.year + 1)[2:]}"
    return f"{str(now.year - 1)[2:]}{str(now.year)[2:]}"


def _current_fy_long() -> str:
    """Full FY string like '2025-26' for display/timeline. Indian FY: Apr 1 – Mar 31."""
    now = datetime.now(timezone.utc)
    start = now.year if now.month >= 4 else now.year - 1
    return f"{start}-{str(start + 1)[2:]}"


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


def _is_unique_violation(err: Exception) -> bool:
    """True when a Postgres/PostgREST error is a unique-constraint violation
    (23505) — recognises a payment_no collision against migration 159's
    UNIQUE (firm_id, payment_no) constraint."""
    s = str(err).lower()
    return "23505" in s or "duplicate key" in s or "already exists" in s


def _compensate_failed_settlement(
    db, firm_id: str, client_id: str, payment_id: str, journal_id, actor: dict,
    attempted_bill_ids: list,
) -> None:
    """Undo a payment whose multi-bill AP settlement failed AFTER the journal and
    payment row were already committed. Mirrors receipt_service's
    _compensate_failed_settlement exactly, including the R2.9 guard against
    reversing a journal that a CONCURRENT payment's reference_no collision
    fast-path actually already claimed as its own (see that function's
    docstring for the full race explanation) — the same
    phase2_journal_service._create_journal idempotency fast-path applies here.

    Residual gap (same class as receipt_service's, tracked under roadmap R2.12):
    if this payment allocated to MULTIPLE bills and an EARLIER bill's CAS
    already succeeded before a LATER one failed, that earlier bill's
    paid_paise/status is not rolled back here. attempted_bill_ids is logged so
    that residual case is visible for manual review.
    """
    try:
        if journal_id:
            owned_by_another = (
                db.table("purchase_payments").select("id")
                .eq("journal_entry_id", journal_id).neq("id", payment_id)
                .limit(1).execute().data
            )
            if owned_by_another:
                _logger.warning(
                    "R2.9-class: skipping journal reversal for journal=%s (firm=%s client=%s) — "
                    "it belongs to another already-committed payment (%s), not this failed "
                    "attempt (payment=%s); reversing it would corrupt that other payment's books.",
                    journal_id, firm_id, client_id, owned_by_another[0].get("id"), payment_id,
                )
            else:
                from services.phase2_journal_service import phase2_journal_service
                phase2_journal_service.reverse_entry(
                    db, firm_id, journal_id, str(datetime.now(timezone.utc).date()),
                    narration=f"Compensating reversal — payment {payment_id} settlement failed",
                    created_by=(actor or {}).get("id"),
                )
        db.table("purchase_payments").delete().eq("id", payment_id).execute()
        _logger.warning(
            "Compensation applied: reversed journal=%s and deleted payment=%s "
            "(firm=%s client=%s) after a settlement failure. Bills touched this "
            "request: %s — verify none were left partially settled without this payment.",
            journal_id, payment_id, firm_id, client_id, attempted_bill_ids,
        )
    except Exception:
        _logger.error(
            "Compensation FAILED for payment=%s journal=%s (firm=%s client=%s) — "
            "manual reconciliation required, a phantom GL entry may remain.",
            payment_id, journal_id, firm_id, client_id, exc_info=True,
        )


def create_payment_core(firm_id: str, data: dict, actor: dict, db) -> dict:
    """Create a vendor payment with MULTI-bill allocations — the AP mirror of
    receipt_service.create_receipt_core.

    - sum(allocations.allocated_paise) must be <= amount_paise
    - unallocated_paise = amount_paise - sum(allocated)  (a vendor advance,
      allocatable later — mirrors receipts.unallocated_paise)
    - updates each allocated bill's paid_paise + status (CAS-guarded, mirrors
      purchase_payments._claim_bill_outstanding's effective-payable formula)
    - auto-creates the journal entry (Dr Trade Payables / Cr Bank)
    - audit + timeline logged

    `data['currency']` != INR dispatches to create_foreign_payment_core (a
    per-bill realized-FX path mirroring receipt_service.create_foreign_receipt).
    `actor` supplies audit/timeline attribution: {id, auth_user_id, email}.
    Integer paise throughout.
    """
    client_id = data["client_id"]
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
            detail=f"Total allocated ({total_allocated} paise) exceeds payment amount ({amount_paise} paise).",
        )
    unallocated_paise = amount_paise - total_allocated

    period_validation_service.validate_posting_date(firm_id or "", data["payment_date"])

    fy = _current_fy()

    if db is None:
        payment_id = str(uuid.uuid4())
        payment = {
            "id": payment_id, "firm_id": firm_id, "client_id": client_id,
            "vendor_id": data["vendor_id"], "purchase_bill_id": None,
            "payment_no": f"VPMT-{fy}-0001", "payment_date": data["payment_date"],
            "amount_paise": amount_paise, "unallocated_paise": unallocated_paise,
            "payment_mode": data.get("payment_mode", "bank"),
            "reference_no": data.get("reference_no"), "notes": data.get("notes"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        from services.phase2_journal_service import phase2_journal_service
        phase2_journal_service.journal_for_purchase_payment(payment, firm_id or "", client_id)
        return {**payment, "allocations": allocations}

    # Business guard: never pay a deactivated vendor (mirrors create_purchase_payment).
    _v = (db.table("vendors").select("is_active")
          .eq("id", data["vendor_id"]).eq("firm_id", firm_id).limit(1).execute().data)
    if _v and _v[0].get("is_active") is False:
        raise HTTPException(status_code=422, detail="This vendor is inactive. Reactivate the vendor before recording a payment.")

    # Ownership + status guard — validated BEFORE any posting (mirrors receipt_service's F1).
    for _a in allocations:
        _bill_id = _a.get("purchase_bill_id")
        if _bill_id and int(_a.get("allocated_paise", 0) or 0) > 0:
            chk = (db.table("purchase_bills").select("id, status")
                   .eq("id", _bill_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute())
            if not chk.data:
                raise HTTPException(status_code=422, detail=f"Bill {_bill_id} is not part of this client's books.")
            if (chk.data[0].get("status") or "") == "cancelled":
                raise HTTPException(status_code=409, detail=f"Bill {_bill_id} is cancelled and cannot be paid.")

    # Pre-validate EVERY allocation against LIVE outstanding BEFORE posting anything
    # (mirrors receipt_service's F7 hardening — a same-request over-allocation must
    # never leave a phantom journal behind). Multiple rows for the same bill are
    # summed so the check reflects the whole request.
    _alloc_by_bill: dict = {}
    for _a in allocations:
        _bill_id = _a.get("purchase_bill_id")
        _amt = int(_a.get("allocated_paise", 0) or 0)
        if _bill_id and _amt > 0:
            _alloc_by_bill[_bill_id] = _alloc_by_bill.get(_bill_id, 0) + _amt
    for _bill_id, _cum_amt in _alloc_by_bill.items():
        _row = (db.table("purchase_bills")
                .select("net_payable_paise, paid_paise, debited_paise, credit_note_paise")
                .eq("id", _bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
                .limit(1).execute().data)
        if not _row:
            continue  # already rejected by the ownership check above
        # Purchase credit notes (§34(3)) raise what's payable; debit notes lower
        # what still needs cash — same effective-payable formula as
        # purchase_payments._claim_bill_outstanding.
        _effective_payable = int(_row[0].get("net_payable_paise") or 0) + int(_row[0].get("credit_note_paise") or 0)
        _debited = int(_row[0].get("debited_paise") or 0)
        _paid = int(_row[0].get("paid_paise") or 0)
        if _paid + _debited + _cum_amt > _effective_payable:
            raise HTTPException(status_code=422,
                detail=f"Bill {_bill_id}: allocation would exceed bill outstanding")

    seq = _next_payment_seq(db, firm_id, fy)
    payment_no = f"VPMT-{fy}-{seq:04d}"
    payment_id = str(uuid.uuid4())  # pre-generated so the journal, payment row and allocations share one id

    payment_payload = {
        "id":                payment_id,
        "firm_id":           firm_id,
        "client_id":         client_id,
        "vendor_id":         data["vendor_id"],
        "purchase_bill_id":  None,   # multi-bill => allocations table, not this legacy single-bill FK
        "payment_no":        payment_no,
        "payment_date":      data["payment_date"],
        "amount_paise":      amount_paise,
        "unallocated_paise": unallocated_paise,
        "payment_mode":      data.get("payment_mode", "bank"),
        "reference_no":      data.get("reference_no"),
        "notes":             data.get("notes"),
        "created_at":        datetime.now(timezone.utc).isoformat(),
        "updated_at":        datetime.now(timezone.utc).isoformat(),
    }

    # Post the GL journal FIRST — a posting failure aborts here rather than
    # leaving settled AP with no GL entry (mirrors receipt_service's F7).
    from services.phase2_journal_service import phase2_journal_service
    journal_id = phase2_journal_service.journal_for_purchase_payment(
        {"payment_no": payment_no, "payment_date": data["payment_date"], "amount_paise": amount_paise},
        firm_id or "", client_id,
    )
    if journal_id:
        payment_payload["journal_entry_id"] = journal_id

    # From HERE ON a failure must be compensated (journal reversed, payment
    # deleted) rather than left as a phantom GL entry.
    alloc_payloads = []
    _attempted_bill_ids = [a.get("purchase_bill_id") for a in allocations if a.get("purchase_bill_id")]
    try:
        pay_resp = db.table("purchase_payments").insert(payment_payload).execute()
        payment    = pay_resp.data[0] if pay_resp.data else payment_payload
        payment_id = payment.get("id", payment_id)

        for alloc in allocations:
            bill_id   = alloc.get("purchase_bill_id")
            alloc_amt = int(alloc.get("allocated_paise", 0))
            if not bill_id or alloc_amt <= 0:
                continue
            alloc_payloads.append({
                "purchase_payment_id": payment_id,
                "purchase_bill_id":    bill_id,
                "allocated_paise":     alloc_amt,
            })

            # H4-class CAS retry — lost-update prevention on paid_paise, mirrors
            # purchase_payments._claim_bill_outstanding / receipt_service's own loop.
            for _attempt in range(6):
                bill_resp = (
                    db.table("purchase_bills")
                    .select("net_payable_paise, paid_paise, debited_paise, credit_note_paise")
                    .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
                    .limit(1)
                    .execute()
                )
                if not bill_resp.data:
                    break
                bill = bill_resp.data[0]
                effective_payable = int(bill.get("net_payable_paise") or 0) + int(bill.get("credit_note_paise") or 0)
                debited  = int(bill.get("debited_paise") or 0)
                raw_paid = bill.get("paid_paise")   # CAS guard must match this exact stored value
                old_paid = int(raw_paid or 0)
                new_paid = old_paid + alloc_amt
                if new_paid + debited > effective_payable:
                    raise HTTPException(status_code=422, detail=f"Bill {bill_id}: allocation would exceed bill outstanding")
                new_status = "paid" if new_paid + debited >= effective_payable else "partially_paid"
                upd = (db.table("purchase_bills").update({
                    "paid_paise": new_paid,
                    "status":     new_status,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
                  .eq("paid_paise", raw_paid)   # compare-and-set guard
                  .execute())
                if upd.data:
                    break                        # CAS won
            else:
                raise HTTPException(status_code=409,
                    detail=f"Bill {bill_id} is being paid concurrently — please retry.")

        if alloc_payloads:
            db.table("purchase_payment_allocations").insert(alloc_payloads).execute()
    except HTTPException:
        _compensate_failed_settlement(db, firm_id, client_id, payment_id, journal_id, actor, _attempted_bill_ids)
        raise
    except Exception as e:
        _compensate_failed_settlement(db, firm_id, client_id, payment_id, journal_id, actor, _attempted_bill_ids)
        if _is_unique_violation(e):
            raise HTTPException(status_code=409, detail="A payment numbering collision was detected; please retry.") from e
        raise

    log_event(
        firm_id or "", "purchase_payment", payment_id, "create",
        actor_id=(actor or {}).get("auth_user_id"), actor_email=(actor or {}).get("email"),
        new_data={"amount_paise": amount_paise, "vendor_id": data["vendor_id"]},
    )
    timeline_service.log_timeline_event(
        client_id=client_id, firm_id=firm_id or "", financial_year=_current_fy_long(),
        category="accounting", event_type="payment_recorded",
        title=f"Vendor Payment {payment_no} recorded",
        description=f"Payment of ₹{amount_paise // 100:,} made to vendor across {len(alloc_payloads)} bill(s).",
        severity="success", entity_type="purchase_payment", entity_id=payment_id,
        amount_paise=amount_paise, actor_id=(actor or {}).get("auth_user_id"), actor_name=(actor or {}).get("email"),
    )

    payment["journal_entry_id"] = journal_id
    payment["allocations"]      = alloc_payloads
    return payment


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
    documents/rates are never modified."""
    from decimal import Decimal, InvalidOperation
    from datetime import date as _date
    from domain.currency.policy import resolve_currency_policy, CurrencyPolicy
    from domain.currency.conversion import to_base_minor
    from domain.currency import currency_service, RateNotFound
    from services.phase2_journal_service import phase2_journal_service as K

    client_id = data["client_id"]
    ccy = (data.get("currency") or "").strip().upper()
    period_validation_service.validate_posting_date(firm_id or "", data["payment_date"])

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

    # Cash rate R1: manual override or resolved at the payment date.
    overridden = data.get("exchange_rate") is not None
    if overridden:
        try:
            R1 = Decimal(str(data["exchange_rate"]))
        except (InvalidOperation, ValueError, TypeError):
            raise HTTPException(status_code=422, detail="Invalid exchange rate.")
        r1_source = "manual-override"
    else:
        try:
            q = K.exchange_rate_service(db).get_quote(ccy, "INR", _date.fromisoformat(str(data["payment_date"])[:10]), "booking")
        except RateNotFound:
            raise HTTPException(status_code=422, detail=f"No exchange rate available for {ccy}->INR on {data['payment_date']}.")
        R1, r1_source = q.rate, q.source
    if R1 <= 0:
        raise HTTPException(status_code=422, detail="Exchange rate must be positive.")

    total_foreign = int(data["amount_paise"])   # foreign cash paid (minor units)
    if total_foreign <= 0:
        raise HTTPException(status_code=422, detail="Payment amount must be positive.")
    allocations = [a for a in data.get("allocations", []) if int(a.get("allocated_paise", 0) or 0) > 0]

    total_ap_relieved = 0
    total_foreign_settled = 0
    settle_plan = []
    for a in allocations:
        bill_id = a.get("purchase_bill_id")
        bill = (db.table("purchase_bills")
               .select("id, status, txn_currency, exchange_rate, net_payable_paise, paid_paise, paid_txn, debited_paise, txn_net_payable")
               .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data or [None])[0]
        if not bill:
            raise HTTPException(status_code=422, detail=f"Bill {bill_id} is not part of this client's books.")
        if (bill.get("status") or "") == "cancelled":
            raise HTTPException(status_code=409, detail=f"Bill {bill_id} is cancelled and cannot be paid.")
        if (bill.get("txn_currency") or "INR").upper() != ccy:
            raise HTTPException(status_code=422, detail=(
                f"Currency mismatch: payment is {ccy} but bill {bill_id} is billed in {bill.get('txn_currency')}."))
        R0 = Decimal(str(bill.get("exchange_rate") or 1))
        base_out = int(bill.get("net_payable_paise") or 0) - int(bill.get("paid_paise") or 0) - int(bill.get("debited_paise") or 0)
        foreign_out = int(bill.get("txn_net_payable") or 0) - int(bill.get("paid_txn") or 0)
        f = int(a["allocated_paise"])
        if f > foreign_out:
            raise HTTPException(status_code=422, detail=(
                f"Allocation {f} exceeds bill {bill_id} outstanding {foreign_out} {ccy}."))
        # Snap the base to clear exactly on full settlement — no rounding drift.
        ap_relieved = base_out if f == foreign_out else to_base_minor(f, R0, minor)
        settle_plan.append((bill, f, ap_relieved))
        total_ap_relieved += ap_relieved
        total_foreign_settled += f
    if total_foreign_settled > total_foreign:
        raise HTTPException(status_code=422, detail="Allocated foreign exceeds the payment amount.")

    cash_base = to_base_minor(total_foreign, R1, minor)
    settled_cash_base = to_base_minor(total_foreign_settled, R1, minor)
    unalloc_base = cash_base - settled_cash_base
    fx_diff = total_ap_relieved - settled_cash_base   # + gain (paid less INR) / − loss (paid more)

    ap_id = K._find_account(db, firm_id, client_id, "%Trade Payable%", system_key="ap")
    bank_id = K._find_account(db, firm_id, client_id, "%Bank%", system_key="bank")
    lines = [
        {"account_id": ap_id, "debit_paise": total_ap_relieved + unalloc_base, "credit_paise": 0,
         "narration": "Trade payable settled at booked rate", "txn_debit": total_foreign, "txn_credit": 0},
        {"account_id": bank_id, "debit_paise": 0, "credit_paise": cash_base,
         "narration": "Bank payment (foreign)", "txn_debit": 0, "txn_credit": total_foreign},
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
    payment_id = str(uuid.uuid4())
    entry_id = K._create_journal(
        db=db, firm_id=firm_id, client_id=client_id, entry_date=data["payment_date"],
        reference_no=payment_no, narration=f"Vendor payment {payment_no} (foreign)",
        entry_type="Payment", lines=lines, created_by=(actor or {}).get("id"),
        source_type="purchase_payment", source_id=payment_id,
        txn_currency=ccy, exchange_rate=R1, rate_source=r1_source, rate_type="booking",
        rate_date=str(data["payment_date"])[:10], rate_selected_by=(actor or {}).get("id"),
        rate_overridden=overridden, currency_policy=CurrencyPolicy(active=True, functional_currency="INR"),
    )

    payment_payload = {
        "id": payment_id,
        "firm_id": firm_id, "client_id": client_id, "vendor_id": data["vendor_id"],
        "purchase_bill_id": None, "payment_no": payment_no, "payment_date": data["payment_date"],
        "amount_paise": cash_base, "unallocated_paise": unalloc_base,
        "payment_mode": data.get("payment_mode", "bank"), "reference_no": data.get("reference_no"),
        "notes": data.get("notes"), "journal_entry_id": entry_id,
        "created_at": datetime.now(timezone.utc).isoformat(), "updated_at": datetime.now(timezone.utc).isoformat(),
        "txn_currency": ccy, "exchange_rate": str(R1), "txn_amount": total_foreign,
        "rate_source": r1_source, "rate_type": "booking", "rate_date": str(data["payment_date"])[:10],
        "rate_selected_by": (actor or {}).get("id"), "rate_overridden": overridden,
    }

    # The journal above is already committed, so from HERE ON a failure must be
    # compensated rather than left as a phantom GL entry.
    alloc_rows = []
    try:
        pay_resp = db.table("purchase_payments").insert(payment_payload).execute()
        payment    = pay_resp.data[0] if pay_resp.data else payment_payload
        payment_id = payment.get("id", payment_id)

        for (bill, f, ap_relieved) in settle_plan:
            bill_id = bill["id"]
            for _attempt in range(6):
                cur = (db.table("purchase_bills").select("paid_paise, paid_txn, txn_net_payable")
                       .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
                       .limit(1).execute().data or [None])[0]
                if not cur:
                    break
                raw_paid = cur.get("paid_paise")  # CAS guard must match this exact stored value
                old_paid = int(raw_paid or 0)
                old_paid_txn = int(cur.get("paid_txn") or 0)
                fresh_new_paid = old_paid + ap_relieved
                fresh_new_paid_txn = old_paid_txn + f
                txn_net_payable = int(cur.get("txn_net_payable") or 0)
                if fresh_new_paid_txn > txn_net_payable:
                    raise HTTPException(status_code=422, detail=f"Bill {bill_id}: allocation would exceed bill outstanding")
                fresh_status = "paid" if fresh_new_paid_txn >= txn_net_payable else "partially_paid"
                upd = (db.table("purchase_bills")
                       .update({"paid_paise": fresh_new_paid, "paid_txn": fresh_new_paid_txn, "status": fresh_status})
                       .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id)
                       .eq("paid_paise", raw_paid).execute())
                if upd.data:
                    break                        # CAS won
            else:
                raise HTTPException(status_code=409, detail=f"Bill {bill_id} is being updated concurrently — please retry.")
            alloc_rows.append({"purchase_payment_id": payment_id, "purchase_bill_id": bill_id, "allocated_paise": ap_relieved})
        if alloc_rows:
            db.table("purchase_payment_allocations").insert(alloc_rows).execute()

        if fx_diff != 0:
            db.table("fx_adjustments").insert({
                "firm_id": firm_id, "client_id": client_id, "kind": "realized",
                "document_type": "purchase_payment", "document_id": payment_id, "currency": ccy,
                "settlement_rate": str(R1), "base_delta_paise": fx_diff,
                "journal_entry_id": entry_id, "rate_source": r1_source,
                "created_by": (actor or {}).get("id"),
            }).execute()
    except HTTPException:
        _compensate_failed_settlement(
            db, firm_id, client_id, payment_id, entry_id, actor,
            [bill["id"] for (bill, *_) in settle_plan],
        )
        raise
    except Exception as e:
        _compensate_failed_settlement(
            db, firm_id, client_id, payment_id, entry_id, actor,
            [bill["id"] for (bill, *_) in settle_plan],
        )
        if _is_unique_violation(e):
            raise HTTPException(
                status_code=409,
                detail="A payment numbering collision was detected; please retry.",
            ) from e
        raise

    log_event(firm_id, "purchase_payment", payment_id, "create", actor_id=(actor or {}).get("auth_user_id"),
              actor_email=(actor or {}).get("email"), new_data={"amount_paise": cash_base, "currency": ccy})
    return {**payment, "allocations": alloc_rows, "journal_entry_id": entry_id, "realized_fx_paise": fx_diff}
