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

from services.audit_service import log_event
from services.period_validation_service import period_validation_service
from services.timeline_service import timeline_service

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.receipt_service")

# In-memory mock stores (re-exported by routers.receipts for backward compat;
# also read by collections_service). Same list objects everywhere they appear.
MOCK_RECEIPTS: list[dict] = []
MOCK_RECEIPT_ALLOCATIONS: list[dict] = []


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


def _resolve_foreign_receipt(db, firm_id: str, client_id: str, data: dict, actor: dict) -> dict:
    """Validate + convert a FOREIGN customer receipt to base (INR) at each invoice's
    frozen rate (Multi-Currency Phase 3). Mutates `data` in place: amount_paise and
    each allocation's allocated_paise are rewritten to base paise. Returns the
    receipt's currency columns. Enforces the Phase-3 limits (Task 3/6): active
    policy, supported+active currency, currency match with every allocated invoice,
    the invoice's frozen rate (no cross-rate), and FULL settlement (partial / TDS /
    unallocated foreign advances are deferred to the realized-FX phase)."""
    from decimal import Decimal, InvalidOperation
    from domain.currency.policy import resolve_currency_policy
    from domain.currency.conversion import to_txn_minor
    from domain.currency import currency_service

    ccy = (data.get("currency") or "").strip().upper()
    if int(data.get("tds_paise", 0) or 0) != 0:
        raise HTTPException(status_code=422, detail="TDS on a foreign receipt is not supported yet (arrives with realized FX).")

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

    allocations = [a for a in data.get("allocations", []) if int(a.get("allocated_paise", 0) or 0) > 0]
    if not allocations:
        raise HTTPException(status_code=422, detail="A foreign receipt must be fully allocated to a same-currency invoice.")

    total_foreign, total_base, rate_used = 0, 0, None
    for a in allocations:
        inv_id = a.get("sales_invoice_id")
        inv = (db.table("client_sales_invoices")
               .select("txn_currency, exchange_rate, total_paise, paid_paise, credited_paise")
               .eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data or [None])[0]
        if not inv:
            raise HTTPException(status_code=422, detail=f"Invoice {inv_id} is not part of this client's books.")
        inv_ccy = (inv.get("txn_currency") or "INR").upper()
        if inv_ccy != ccy:
            raise HTTPException(status_code=422, detail=(
                f"Currency mismatch: receipt is {ccy} but invoice {inv_id} is billed in {inv_ccy}."))
        inv_rate = Decimal(str(inv.get("exchange_rate") or 1))
        if override is not None and override != inv_rate:
            raise HTTPException(status_code=422, detail=(
                "Settling at a rate different from the invoice's booked rate would realise an FX "
                "gain/loss — that arrives in the next phase. Settle at the invoice's rate."))
        base_out = int(inv["total_paise"]) - int(inv.get("paid_paise") or 0) - int(inv.get("credited_paise") or 0)
        foreign_out = to_txn_minor(base_out, inv_rate, minor)
        if int(a["allocated_paise"]) != foreign_out:
            raise HTTPException(status_code=422, detail=(
                "Phase 3 settles a foreign invoice in full at its booked rate; partial foreign "
                "settlement arrives with realized FX in the next phase."))
        a["allocated_paise"] = base_out       # rewrite to base for the settlement below
        total_foreign += foreign_out
        total_base += base_out
        rate_used = inv_rate

    data["amount_paise"] = total_base          # receipt cash, now in base paise
    return {
        "txn_currency": ccy, "exchange_rate": str(rate_used), "txn_amount": total_foreign,
        "rate_source": "settlement", "rate_type": "booking", "rate_date": data.get("receipt_date"),
        "rate_selected_by": (actor or {}).get("id"), "rate_overridden": override is not None,
    }


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
    # ── Multi-Currency (Phase 3): a foreign receipt settles same-currency invoices
    # at each invoice's FROZEN booking rate (no realized FX yet). We convert the
    # foreign inputs to base (INR) up front and rewrite `data`, so every settlement
    # step below runs in base exactly as for an INR receipt. INR ⇒ no-op.
    _ccy_cols: dict = {}
    if db is not None and (data.get("currency") or "INR").strip().upper() != "INR":
        _ccy_cols = _resolve_foreign_receipt(db, firm_id, client_id, data, actor)
    amount_paise = data["amount_paise"]
    tds_paise    = int(data.get("tds_paise", 0) or 0)   # TDS deducted by client (§194J)
    settlement   = amount_paise + tds_paise              # value applied against invoices
    allocations  = data.get("allocations", [])

    # Validate allocation totals — integer arithmetic. Settlement includes TDS at source.
    total_allocated = sum(int(a.get("allocated_paise", 0)) for a in allocations)
    if total_allocated > settlement:
        raise HTTPException(
            status_code=422,
            detail=f"Total allocated ({total_allocated} paise) exceeds settlement value "
                   f"({settlement} paise = amount {amount_paise} + TDS {tds_paise})",
        )
    unallocated_paise = settlement - total_allocated

    # Posting date must not be in a locked financial year (migration 020).
    period_validation_service.validate_posting_date(firm_id or "", data["receipt_date"])

    fy = _current_fy()

    if db is None:
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
            "tds_paise":         tds_paise,
            "unallocated_paise": unallocated_paise,
            "payment_mode":      data.get("payment_mode", ""),
            "reference_no":      data.get("reference_no", ""),
            "notes":             data.get("notes", ""),
            "created_at":        datetime.now(timezone.utc).isoformat(),
        }
        MOCK_RECEIPTS.append(receipt)
        from services.phase2_journal_service import phase2_journal_service
        phase2_journal_service.journal_for_receipt(receipt, firm_id or "", client_id)
        return {**receipt, "allocations": allocations}

    # Business guard: never record a receipt against a deactivated customer.
    _cust = (db.table("customers").select("is_active")
             .eq("id", data["customer_id"]).eq("firm_id", firm_id or "").eq("client_id", client_id)
             .limit(1).execute().data)
    if _cust and _cust[0].get("is_active") is False:
        raise HTTPException(status_code=422, detail="This customer is inactive. Reactivate the customer before recording a receipt.")

    # F1 fix: allocations must reference THIS client's invoices (firm+client scope),
    # validated BEFORE the receipt is created so a foreign invoice id can never be
    # recorded or have its paid_paise mutated.
    for _a in allocations:
        _inv = _a.get("sales_invoice_id")
        if _inv and int(_a.get("allocated_paise", 0) or 0) > 0:
            chk = (db.table("client_sales_invoices").select("id")
                   .eq("id", _inv).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute())
            if not chk.data:
                raise HTTPException(status_code=422, detail=f"Invoice {_inv} is not part of this client's books.")

    seq = _next_receipt_seq(db, firm_id, client_id, fy)
    receipt_no = f"RCPT-{fy}-{seq:04d}"

    receipt_payload = {
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
        **_ccy_cols,
    }

    rcpt_resp  = db.table("receipts").insert(receipt_payload).execute()
    receipt    = rcpt_resp.data[0] if rcpt_resp.data else receipt_payload
    receipt_id = receipt.get("id", str(uuid.uuid4()))

    # Insert allocations and update invoice statuses.
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

        # H1 — lost-update prevention: read-modify-write on paid_paise is guarded by an
        # optimistic compare-and-set (UPDATE ... WHERE paid_paise = <value we read>). If
        # a concurrent receipt changed paid_paise between our read and write, the CAS
        # matches 0 rows and we re-read and retry, so concurrent settlements can never
        # lose an update or overshoot the invoice total.
        for _attempt in range(6):
            inv_resp = (
                db.table("client_sales_invoices")
                .select("total_paise,paid_paise,credited_paise")
                .eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id)
                .limit(1)
                .execute()
            )
            if not inv_resp.data:
                break
            inv = inv_resp.data[0]
            total    = int(inv.get("total_paise", 0))
            credited = int(inv.get("credited_paise", 0) or 0)   # credit notes already applied
            old_paid = int(inv.get("paid_paise", 0) or 0)
            new_paid = old_paid + alloc_amt
            # Fully settled when cash paid + credit notes reach the total; the allocation
            # may not push settlement past the total.
            if new_paid + credited > total:
                raise HTTPException(status_code=422, detail=f"Invoice {inv_id}: allocation would exceed invoice outstanding")
            new_status = "paid" if (new_paid + credited) >= total else "partially_paid"
            upd = (db.table("client_sales_invoices").update({
                "paid_paise": new_paid,
                "status":     new_status,
            }).eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id)
              .eq("paid_paise", old_paid)   # compare-and-set guard
              .execute())
            if upd.data:
                break                        # CAS won
        else:
            raise HTTPException(status_code=409,
                detail=f"Invoice {inv_id} is being updated concurrently — please retry.")

    if alloc_payloads:
        db.table("receipt_allocations").insert(alloc_payloads).execute()

    # Auto-create journal entry (Dr Bank / Cr Trade Receivables).
    from services.phase2_journal_service import phase2_journal_service
    journal_id = phase2_journal_service.journal_for_receipt(
        receipt=receipt,
        firm_id=firm_id or "",
        client_id=client_id,
    )

    log_event(
        firm_id or "", "receipt", receipt_id,
        "create", actor_id=actor.get("auth_user_id"),
        actor_email=actor.get("email"), new_data=receipt,
    )

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
        actor_id=actor.get("auth_user_id"),
        actor_name=actor.get("email"),
    )

    receipt["journal_entry_id"] = journal_id
    receipt["allocations"]      = alloc_payloads
    return receipt
