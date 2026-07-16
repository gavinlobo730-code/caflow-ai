"""Party credit balances (task #102) — QuickBooks-style tracking of a
customer/vendor cash credit sitting against their account, with no GST/supply
implication (see migration 214 for why this is deliberately NOT a
credit_notes/purchase_credit_notes row).

grant_credit() is called by bank_posting_service._settle_doc when a matched
bank transaction settles more than a document's true outstanding — the GL
side is already correct (the transaction's full amount was posted to Trade
Receivables/Payables by the journal), so granting a credit here is a pure
SUB-LEDGER move: no new journal entry. apply_credit() later re-associates
that credit to a specific invoice/bill (again no new journal — the AR/AP
control account was already correctly credited/debited when the credit was
granted; applying it is bookkeeping recognition, not a new cash movement).

Integer paise throughout. Firm+client scoped on every read/write.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

_logger = logging.getLogger("caflow.party_credit")

_VALID_PARTY_TYPES = {"customer", "vendor"}
_DOC_TABLE = {"sales_invoice": "client_sales_invoices", "purchase_bill": "purchase_bills"}
_DOC_LABEL_COL = {"sales_invoice": "invoice_no", "purchase_bill": "bill_no"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _outstanding(doc: dict, applied_to_type: str) -> int:
    # Same formula as bank_posting_service (CGST Act §34 / IT Act §194C/194J
    # TDS-net payable) so a credit application reconciles with aging/statements.
    from services.bank_posting_service import bank_posting_service as bps
    if applied_to_type == "sales_invoice":
        return bps._invoice_outstanding(doc)
    return bps._bill_outstanding(doc)


class PartyCreditService:

    def _validate_party_type(self, party_type: str) -> None:
        if party_type not in _VALID_PARTY_TYPES:
            raise HTTPException(status_code=422, detail=f"Invalid party_type '{party_type}'.")

    def get_balance(self, db, firm_id: str, client_id: str, party_type: str, party_id: str) -> int:
        row = (db.table("party_credit_balances").select("balance_paise")
               .eq("firm_id", firm_id).eq("client_id", client_id)
               .eq("party_type", party_type).eq("party_id", party_id)
               .limit(1).execute().data or [None])[0]
        return int(row.get("balance_paise") or 0) if row else 0

    def list_balances(self, db, firm_id: str, client_id: str, party_type: Optional[str] = None) -> list[dict]:
        q = (db.table("party_credit_balances").select("*")
             .eq("firm_id", firm_id).eq("client_id", client_id))
        if party_type:
            q = q.eq("party_type", party_type)
        return [r for r in (q.execute().data or []) if int(r.get("balance_paise") or 0) > 0]

    def ledger(self, db, firm_id: str, client_id: str, party_type: str, party_id: str) -> list[dict]:
        self._validate_party_type(party_type)
        return (db.table("party_credit_ledger").select("*")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("party_type", party_type).eq("party_id", party_id)
                .order("created_at", desc=True).execute().data or [])

    def grant_credit(
        self, db, firm_id: str, client_id: str, party_type: str, party_id: str,
        amount_paise: int, source_type: str, source_id: Optional[str] = None,
        created_by: Optional[str] = None, notes: Optional[str] = None,
        max_retries: int = 5,
    ) -> dict:
        """Increment (or create) the party's credit balance by amount_paise and
        append a 'grant' ledger row. CAS-safe against a concurrent grant/apply on
        the same party."""
        self._validate_party_type(party_type)
        if amount_paise <= 0:
            raise HTTPException(status_code=422, detail="amount_paise must be positive")

        for _attempt in range(max_retries):
            existing = (db.table("party_credit_balances").select("id, balance_paise")
                        .eq("firm_id", firm_id).eq("client_id", client_id)
                        .eq("party_type", party_type).eq("party_id", party_id)
                        .limit(1).execute().data or [None])[0]
            if not existing:
                try:
                    db.table("party_credit_balances").insert({
                        "firm_id": firm_id, "client_id": client_id, "party_type": party_type,
                        "party_id": party_id, "balance_paise": amount_paise, "updated_at": _now(),
                    }).execute()
                    break
                except Exception as e:
                    if "23505" in str(e).lower() or "duplicate" in str(e).lower():
                        continue   # another grant created the row first — retry as an update
                    raise
            else:
                raw_balance = existing.get("balance_paise")
                new_balance = int(raw_balance or 0) + amount_paise
                upd = (db.table("party_credit_balances")
                       .update({"balance_paise": new_balance, "updated_at": _now()})
                       .eq("id", existing["id"]).eq("balance_paise", raw_balance).execute())
                if upd.data:
                    break
        else:
            raise HTTPException(status_code=409, detail="Party credit balance is being updated concurrently — please retry.")

        ledger_row = (db.table("party_credit_ledger").insert({
            "firm_id": firm_id, "client_id": client_id, "party_type": party_type, "party_id": party_id,
            "amount_paise": amount_paise, "kind": "grant", "source_type": source_type,
            "source_id": source_id, "notes": notes, "created_by": created_by,
        }).execute().data or [{}])[0]
        _logger.info("Granted party credit %d paise to %s %s (firm=%s client=%s, source=%s/%s)",
                    amount_paise, party_type, party_id, firm_id, client_id, source_type, source_id)
        return ledger_row

    def apply_credit(
        self, db, firm_id: str, client_id: str, party_type: str, party_id: str,
        amount_paise: int, applied_to_type: str, applied_to_id: str,
        created_by: Optional[str] = None, max_retries: int = 5,
    ) -> dict:
        """Consume amount_paise of the party's credit balance against a specific
        invoice/bill: decrements the balance (CAS), appends an 'application'
        ledger row, and increments the target document's paid_paise/status via
        the same CAS-retry pattern as bank settlement / purchase payments. No
        new journal entry — the GL was already correct when the credit was
        granted; this is a pure sub-ledger reassignment."""
        self._validate_party_type(party_type)
        if applied_to_type not in _DOC_TABLE:
            raise HTTPException(status_code=422, detail=f"Invalid applied_to_type '{applied_to_type}'.")
        if amount_paise <= 0:
            raise HTTPException(status_code=422, detail="amount_paise must be positive")
        expected_party_type = "customer" if applied_to_type == "sales_invoice" else "vendor"
        if party_type != expected_party_type:
            raise HTTPException(status_code=422,
                                detail=f"A {party_type} credit cannot be applied to a {applied_to_type}.")

        table = _DOC_TABLE[applied_to_type]
        label_col = _DOC_LABEL_COL[applied_to_type]
        party_col = "customer_id" if applied_to_type == "sales_invoice" else "vendor_id"

        # 1) Decrement the credit balance (CAS) — validated against FRESH state
        #    on every attempt so a concurrent application can't overdraw it.
        for _attempt in range(max_retries):
            existing = (db.table("party_credit_balances").select("id, balance_paise")
                        .eq("firm_id", firm_id).eq("client_id", client_id)
                        .eq("party_type", party_type).eq("party_id", party_id)
                        .limit(1).execute().data or [None])[0]
            if not existing:
                raise HTTPException(status_code=422, detail="This party has no credit balance.")
            raw_balance = existing.get("balance_paise")
            current_balance = int(raw_balance or 0)
            if amount_paise > current_balance:
                raise HTTPException(status_code=422,
                                    detail=f"Requested application (₹{amount_paise/100:,.2f}) exceeds "
                                           f"the available credit (₹{current_balance/100:,.2f}).")
            new_balance = current_balance - amount_paise
            upd = (db.table("party_credit_balances")
                   .update({"balance_paise": new_balance, "updated_at": _now()})
                   .eq("id", existing["id"]).eq("balance_paise", raw_balance).execute())
            if upd.data:
                break
        else:
            raise HTTPException(status_code=409, detail="Party credit balance is being updated concurrently — please retry.")

        # 2) Verify the target document belongs to this firm+client+party and has
        #    room for this amount, then apply it — CAS-guarded, re-validated
        #    against fresh state (mirrors purchase_payments._update_bill_payment_status).
        #    ANY failure past this point (validation OR CAS exhaustion) must
        #    restore the balance decremented in step 1 — a failed application
        #    must never silently burn the party's credit.
        try:
            doc_applied = False
            for _attempt in range(max_retries):
                extra_cols = ("total_paise, debit_note_paise, credited_paise" if applied_to_type == "sales_invoice"
                              else "total_paise, net_payable_paise, credit_note_paise, debited_paise")
                rows = (db.table(table).select(f"id, {label_col}, {party_col}, paid_paise, status, {extra_cols}")
                        .eq("id", applied_to_id).eq("firm_id", firm_id).eq("client_id", client_id)
                        .limit(1).execute().data or [])
                doc = rows[0] if rows else None
                if not doc:
                    raise HTTPException(status_code=422, detail=f"{applied_to_type} {applied_to_id} is not part of this client's books.")
                if doc.get(party_col) != party_id:
                    raise HTTPException(status_code=422,
                                        detail=f"This credit belongs to a different {party_type} than the one on {applied_to_type} {applied_to_id}.")
                outstanding = _outstanding(doc, applied_to_type)
                if amount_paise > outstanding:
                    raise HTTPException(status_code=422,
                                        detail=f"{applied_to_type} {applied_to_id}: application would exceed its outstanding "
                                               f"(₹{outstanding/100:,.2f}).")
                raw_paid = doc.get("paid_paise")
                new_paid = int(raw_paid or 0) + amount_paise
                new_status = "paid" if amount_paise >= outstanding else "partially_paid"
                upd = (db.table(table).update({"paid_paise": new_paid, "status": new_status, "updated_at": _now()})
                       .eq("id", applied_to_id).eq("firm_id", firm_id).eq("client_id", client_id)
                       .eq("paid_paise", raw_paid).execute())
                if upd.data:
                    doc_applied = True
                    break
            if not doc_applied:
                raise HTTPException(status_code=409, detail=f"{applied_to_type} {applied_to_id} is being updated concurrently — please retry.")
        except Exception:
            self._restore_balance(db, firm_id, client_id, party_type, party_id, amount_paise, max_retries)
            raise

        ledger_row = (db.table("party_credit_ledger").insert({
            "firm_id": firm_id, "client_id": client_id, "party_type": party_type, "party_id": party_id,
            "amount_paise": -amount_paise, "kind": "application",
            "applied_to_type": applied_to_type, "applied_to_id": applied_to_id, "created_by": created_by,
        }).execute().data or [{}])[0]
        _logger.info("Applied party credit %d paise from %s %s to %s %s (firm=%s client=%s)",
                    amount_paise, party_type, party_id, applied_to_type, applied_to_id, firm_id, client_id)
        return ledger_row

    def _restore_balance(self, db, firm_id, client_id, party_type, party_id, amount_paise, max_retries) -> None:
        """Best-effort compensation: undo step 1's decrement after step 2 failed
        for ANY reason (validation or CAS exhaustion), so a rejected application
        never silently burns the party's credit."""
        for _attempt in range(max_retries):
            cur = (db.table("party_credit_balances").select("id, balance_paise")
                   .eq("firm_id", firm_id).eq("client_id", client_id)
                   .eq("party_type", party_type).eq("party_id", party_id)
                   .limit(1).execute().data or [None])[0]
            if not cur:
                return
            raw = cur.get("balance_paise")
            upd = (db.table("party_credit_balances")
                   .update({"balance_paise": int(raw or 0) + amount_paise, "updated_at": _now()})
                   .eq("id", cur["id"]).eq("balance_paise", raw).execute())
            if upd.data:
                return
        _logger.error(
            "party_credit_service: compensation FAILED restoring %d paise for %s %s (firm=%s client=%s) "
            "after a rejected application — manual reconciliation required.",
            amount_paise, party_type, party_id, firm_id, client_id,
        )


party_credit_service = PartyCreditService()
