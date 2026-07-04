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


def create_foreign_receipt(firm_id: str, data: dict, actor: dict, db) -> dict:
    """Foreign customer receipt with realized FX (Multi-Currency Phase 4).

    Each allocated invoice is relieved at ITS frozen booking rate (R0); the cash is
    taken at the receipt's rate (R1); the difference posts to Realized FX Gain/Loss
    in ONE balanced journal through the kernel. Foreign settled amounts are tracked
    on the invoice (paid_txn) so partial settlements never drift and the final
    settlement clears the base exactly. Original documents/rates are never modified.
    Supports partial / multiple / over-payment (the unallocated excess is a customer
    advance carried at R1)."""
    from decimal import Decimal, InvalidOperation
    from datetime import date as _date
    from domain.currency.policy import resolve_currency_policy, CurrencyPolicy
    from domain.currency.conversion import to_base_minor
    from domain.currency import currency_service, RateNotFound
    from services.phase2_journal_service import phase2_journal_service as K

    client_id = data["client_id"]
    ccy = (data.get("currency") or "").strip().upper()
    if int(data.get("tds_paise", 0) or 0) != 0:
        raise HTTPException(status_code=422, detail="TDS on a foreign receipt is not supported yet.")
    period_validation_service.validate_posting_date(firm_id or "", data["receipt_date"])

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

    # Cash rate R1: manual override or resolved at the receipt date.
    overridden = data.get("exchange_rate") is not None
    if overridden:
        try:
            R1 = Decimal(str(data["exchange_rate"]))
        except (InvalidOperation, ValueError, TypeError):
            raise HTTPException(status_code=422, detail="Invalid exchange rate.")
        r1_source = "manual-override"
    else:
        try:
            q = K.exchange_rate_service(db).get_quote(ccy, "INR", _date.fromisoformat(str(data["receipt_date"])[:10]), "booking")
        except RateNotFound:
            raise HTTPException(status_code=422, detail=f"No exchange rate available for {ccy}->INR on {data['receipt_date']}.")
        R1, r1_source = q.rate, q.source
    if R1 <= 0:
        raise HTTPException(status_code=422, detail="Exchange rate must be positive.")

    total_foreign = int(data["amount_paise"])   # foreign cash received (minor units)
    allocations = [a for a in data.get("allocations", []) if int(a.get("allocated_paise", 0) or 0) > 0]

    total_ar_relieved = 0
    total_foreign_settled = 0
    settle_plan = []
    for a in allocations:
        inv_id = a.get("sales_invoice_id")
        inv = (db.table("client_sales_invoices")
               .select("id, txn_currency, exchange_rate, total_paise, paid_paise, paid_txn, credited_paise, txn_total")
               .eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data or [None])[0]
        if not inv:
            raise HTTPException(status_code=422, detail=f"Invoice {inv_id} is not part of this client's books.")
        if (inv.get("txn_currency") or "INR").upper() != ccy:
            raise HTTPException(status_code=422, detail=(
                f"Currency mismatch: receipt is {ccy} but invoice {inv_id} is billed in {inv.get('txn_currency')}."))
        R0 = Decimal(str(inv.get("exchange_rate") or 1))
        base_out = int(inv["total_paise"]) - int(inv.get("paid_paise") or 0) - int(inv.get("credited_paise") or 0)
        foreign_out = int(inv.get("txn_total") or 0) - int(inv.get("paid_txn") or 0)
        f = int(a["allocated_paise"])
        if f > foreign_out:
            raise HTTPException(status_code=422, detail=(
                f"Allocation {f} exceeds invoice {inv_id} outstanding {foreign_out} {ccy}."))
        # Snap the base to clear exactly on full settlement — no rounding drift.
        ar_relieved = base_out if f == foreign_out else to_base_minor(f, R0, minor)
        new_paid = int(inv.get("paid_paise") or 0) + ar_relieved
        new_paid_txn = int(inv.get("paid_txn") or 0) + f
        status = "paid" if new_paid_txn >= int(inv.get("txn_total") or 0) else "partially_paid"
        settle_plan.append((inv, f, ar_relieved, new_paid, new_paid_txn, status))
        total_ar_relieved += ar_relieved
        total_foreign_settled += f
    if total_foreign_settled > total_foreign:
        raise HTTPException(status_code=422, detail="Allocated foreign exceeds the receipt amount.")

    cash_base = to_base_minor(total_foreign, R1, minor)
    settled_cash_base = to_base_minor(total_foreign_settled, R1, minor)
    unalloc_base = cash_base - settled_cash_base
    fx_diff = settled_cash_base - total_ar_relieved   # + gain / − loss (receivable)

    bank_id = K._find_account(db, firm_id, client_id, "%Bank%", system_key="bank")
    ar_id = K._find_account(db, firm_id, client_id, "%Trade Receivable%", system_key="ar")
    lines = [
        {"account_id": bank_id, "debit_paise": cash_base, "credit_paise": 0,
         "narration": "Cash/bank received (foreign)", "txn_debit": total_foreign, "txn_credit": 0},
        {"account_id": ar_id, "debit_paise": 0, "credit_paise": total_ar_relieved + unalloc_base,
         "narration": "Trade receivable settled at booked rate", "txn_debit": 0, "txn_credit": total_foreign},
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
    seq = _next_receipt_seq(db, firm_id, client_id, fy)
    receipt_no = f"RCPT-{fy}-{seq:04d}"
    entry_id = K._create_journal(
        db=db, firm_id=firm_id, client_id=client_id, entry_date=data["receipt_date"],
        reference_no=receipt_no, narration=f"Receipt {receipt_no} (foreign) from customer",
        entry_type="Receipt", lines=lines, created_by=(actor or {}).get("id"),
        txn_currency=ccy, exchange_rate=R1, rate_source=r1_source, rate_type="booking",
        rate_date=str(data["receipt_date"])[:10], rate_selected_by=(actor or {}).get("id"),
        rate_overridden=overridden, currency_policy=CurrencyPolicy(active=True, functional_currency="INR"),
    )

    receipt_id = str(uuid.uuid4())
    receipt_payload = {
        "id": receipt_id,
        "firm_id": firm_id, "client_id": client_id, "customer_id": data["customer_id"],
        "receipt_no": receipt_no, "receipt_date": data["receipt_date"],
        "amount_paise": cash_base, "tds_paise": 0, "unallocated_paise": unalloc_base,
        "payment_mode": data.get("payment_mode", ""), "reference_no": data.get("reference_no", ""),
        "notes": data.get("notes", ""), "journal_entry_id": entry_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "txn_currency": ccy, "exchange_rate": str(R1), "txn_amount": total_foreign,
        "rate_source": r1_source, "rate_type": "booking", "rate_date": str(data["receipt_date"])[:10],
        "rate_selected_by": (actor or {}).get("id"), "rate_overridden": overridden,
    }

    # F7/R2.9 hardening: the journal above is already committed (this path always
    # posts the journal first), so from HERE ON (starting with the receipt insert
    # itself) a failure must be compensated (journal reversed, receipt deleted)
    # rather than left as a phantom GL entry. This now also covers a receipt_no
    # unique-constraint collision (migration 159, R2.9) — previously impossible
    # to hit since no constraint existed, so the insert itself was never in this
    # try block. Settlement amounts were already validated against each invoice's
    # live outstanding when settle_plan was built (before the journal posted), so
    # the loop's 409 is now only reachable via a genuine concurrent race.
    alloc_rows = []
    try:
        receipt = (db.table("receipts").insert(receipt_payload).execute().data or [receipt_payload])[0]
        receipt_id = receipt.get("id", receipt_id)

        for (inv, f, ar_relieved, _new_paid, _new_paid_txn, _status) in settle_plan:
            # R2.12 adversarial-review fix: settle_plan's new_paid/new_paid_txn/
            # status were computed from a read taken BEFORE the journal posted
            # (a wide staleness window), and the original CAS below had NO
            # retry at all — a single collision failed immediately, a weaker
            # guarantee than the plain-INR path's 6-attempt retry loop this
            # milestone's atomic rewrite replaced (finding: leaving this path
            # unfixed was a HIGHER concurrency risk than the framing implied,
            # not a lower one). Re-read fresh on every attempt instead of
            # trusting settle_plan's stale snapshot.
            inv_id = inv["id"]
            for _attempt in range(6):
                cur = (db.table("client_sales_invoices")
                       .select("paid_paise,paid_txn,txn_total")
                       .eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id)
                       .limit(1).execute().data or [None])[0]
                if not cur:
                    break
                old_paid = int(cur.get("paid_paise") or 0)
                old_paid_txn = int(cur.get("paid_txn") or 0)
                fresh_new_paid = old_paid + ar_relieved
                fresh_new_paid_txn = old_paid_txn + f
                txn_total = int(cur.get("txn_total") or 0)
                if fresh_new_paid_txn > txn_total:
                    raise HTTPException(status_code=422, detail=f"Invoice {inv_id}: allocation would exceed invoice outstanding")
                fresh_status = "paid" if fresh_new_paid_txn >= txn_total else "partially_paid"
                upd = (db.table("client_sales_invoices")
                       .update({"paid_paise": fresh_new_paid, "paid_txn": fresh_new_paid_txn, "status": fresh_status})
                       .eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id)
                       .eq("paid_paise", old_paid).execute())
                if upd.data:
                    break                        # CAS won
            else:
                raise HTTPException(status_code=409, detail=f"Invoice {inv_id} is being updated concurrently — please retry.")
            alloc_rows.append({"receipt_id": receipt_id, "sales_invoice_id": inv_id, "allocated_paise": ar_relieved})
        if alloc_rows:
            db.table("receipt_allocations").insert(alloc_rows).execute()

        if fx_diff != 0:
            db.table("fx_adjustments").insert({
                "firm_id": firm_id, "client_id": client_id, "kind": "realized",
                "document_type": "receipt", "document_id": receipt_id, "currency": ccy,
                "settlement_rate": str(R1), "base_delta_paise": fx_diff,
                "journal_entry_id": entry_id, "rate_source": r1_source,
                "created_by": (actor or {}).get("id"),
            }).execute()
    except HTTPException:
        _compensate_failed_settlement(
            db, firm_id, client_id, receipt_id, entry_id, actor,
            [inv["id"] for (inv, *_ ) in settle_plan],
        )
        raise
    except Exception as e:
        _compensate_failed_settlement(
            db, firm_id, client_id, receipt_id, entry_id, actor,
            [inv["id"] for (inv, *_ ) in settle_plan],
        )
        if _is_unique_violation(e):
            raise HTTPException(
                status_code=409,
                detail="A receipt numbering collision was detected; please retry.",
            ) from e
        raise

    log_event(firm_id, "receipt", receipt_id, "create", actor_id=(actor or {}).get("auth_user_id"),
              actor_email=(actor or {}).get("email"), new_data={"amount_paise": cash_base, "currency": ccy})
    return {**receipt, "allocations": alloc_rows, "journal_entry_id": entry_id, "realized_fx_paise": fx_diff}


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
                    db, firm_id, journal_id, str(datetime.now(timezone.utc).date()),
                    narration=f"Compensating reversal — receipt {receipt_id} settlement failed",
                    created_by=(actor or {}).get("id"),
                )
        db.table("receipts").delete().eq("id", receipt_id).execute()
        _logger.warning(
            "F7 compensation applied: reversed journal=%s and deleted receipt=%s "
            "(firm=%s client=%s) after a settlement failure. Invoices touched this "
            "request: %s — verify none were left partially settled without this receipt.",
            journal_id, receipt_id, firm_id, client_id, attempted_invoice_ids,
        )
    except Exception:
        _logger.error(
            "F7 compensation FAILED for receipt=%s journal=%s (firm=%s client=%s) — "
            "manual reconciliation required, a phantom GL entry may remain.",
            receipt_id, journal_id, firm_id, client_id, exc_info=True,
        )


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
        result = db.rpc("settle_receipt_atomic", {
            "p_receipt": receipt_payload,
            "p_journal_entry": entry_payload,
            "p_journal_lines": line_payloads,
            "p_allocations": alloc_payloads,
        }).execute()
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
        title=f"Receipt {receipt_payload.get('receipt_no', '')} recorded",
        description=f"Payment of ₹{receipt_payload['amount_paise'] // 100:,} received from customer.",
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
        _row = (db.table("client_sales_invoices").select("total_paise,paid_paise,credited_paise")
                .eq("id", _inv_id).eq("firm_id", firm_id).eq("client_id", client_id)
                .limit(1).execute().data)
        if not _row:
            continue  # already rejected by the ownership check above
        _total = int(_row[0].get("total_paise", 0))
        _credited = int(_row[0].get("credited_paise", 0) or 0)
        _paid = int(_row[0].get("paid_paise", 0) or 0)
        if _paid + _credited + _cum_amt > _total:
            raise HTTPException(status_code=422,
                detail=f"Invoice {_inv_id}: allocation would exceed invoice outstanding")

    seq = _next_receipt_seq(db, firm_id, client_id, fy)
    receipt_no = f"RCPT-{fy}-{seq:04d}"

    receipt_id = str(uuid.uuid4())
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
        "reference_no":      data.get("reference_no", ""),
        "notes":             data.get("notes", ""),
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
        rcpt_resp  = db.table("receipts").insert(receipt_payload).execute()
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
                # may not push settlement past the total. (Defense-in-depth: pre-validated
                # above already, so this is now only reachable via a concurrent race.)
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
