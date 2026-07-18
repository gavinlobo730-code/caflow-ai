"""
Bank matching & categorization service (Banking B.2).

Builds SUGGESTIONS for unmatched bank transactions (against open sales invoices /
purchase bills / receipts / payments / journal entries), applies rule-based
category suggestions, and records manual matches/categorization. It NEVER posts a
journal and never auto-reconciles — matching is linkage + classification only
(posting is Phase B.3). All reads/writes are firm-scoped; integer paise.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from domain.banking import (
    Candidate, rank_suggestions, suggest_category, is_valid_category, CATEGORIES,
)
from services.timeline_service import timeline_service

_logger = logging.getLogger("caflow.bank_matching")

_MATCH_ENTITY_TYPES = frozenset({
    "sales_invoice", "purchase_bill", "receipt", "purchase_payment", "journal_entry", "manual",
})

# The unambiguous category implied by a matched entity, applied when the caller
# accepts a suggestion without picking a category (otherwise the transaction is
# left uncategorized and never posts cleanly). Only entities with a single
# obvious classification whose counter is an AUTO control account
# (posting_map.AUTO_COUNTER: Customer Payment → AR, Vendor Payment → AP) — so no
# GL account is guessed and the matched document is settled downstream (Phase
# B.3). journal_entry / manual have no safe default and stay NULL for the CA to
# classify explicitly.
_MATCH_DEFAULT_CATEGORY = {
    "sales_invoice": "Customer Payment",
    "receipt": "Customer Payment",
    "purchase_bill": "Vendor Payment",
    "purchase_payment": "Vendor Payment",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _txn_amount(txn: dict) -> tuple[int, bool]:
    """(amount_paise, is_credit). A bank line has exactly one non-zero side."""
    debit = int(txn.get("debit_paise") or 0)
    credit = int(txn.get("credit_paise") or 0)
    return (max(debit, credit), credit > 0)


class BankMatchingService:

    def _get_txn(self, db, firm_id: str, txn_id: str) -> dict:
        res = (db.table("bank_transactions").select("*")
               .eq("id", txn_id).eq("firm_id", firm_id).single().execute())
        if not res.data:
            raise HTTPException(status_code=404, detail="Bank transaction not found.")
        return res.data

    # ── B.2.1 — ranked match suggestions ─────────────────────────────────────
    def suggestions(self, db, firm_id: str, txn_id: str, max_results: int = 5) -> dict:
        txn = self._get_txn(db, firm_id, txn_id)
        amount, is_credit = _txn_amount(txn)
        client_id = txn["client_id"]
        candidates = self._candidates(db, firm_id, client_id, amount, is_credit)
        ranked = rank_suggestions(amount, str(txn.get("transaction_date"))[:10],
                                  txn.get("description"), candidates, max_results=max_results)
        return {
            "transaction_id": txn_id,
            "amount_paise": amount,
            "direction": "credit" if is_credit else "debit",
            "suggestions": [{
                "matched_entity_type": s.entity_type, "matched_entity_id": s.entity_id,
                "label": s.label, "amount_paise": s.amount_paise,
                "confidence": s.confidence, "confidence_label": s.confidence_label,
                "reasons": s.reasons,
            } for s in ranked],
        }

    def _candidates(self, db, firm_id, client_id, amount, is_credit) -> list[Candidate]:
        out: list[Candidate] = []
        if amount <= 0:
            return out
        try:
            if is_credit:
                out += self._invoice_candidates(db, firm_id, client_id, amount)
                out += self._receipt_candidates(db, firm_id, client_id, amount)
            else:
                out += self._bill_candidates(db, firm_id, client_id, amount)
                out += self._payment_candidates(db, firm_id, client_id, amount)
            out += self._journal_candidates(db, firm_id, client_id, amount)
        except Exception as e:  # pragma: no cover - candidate fetch is best-effort
            _logger.warning("candidate fetch failed for client %s: %s", client_id, e)
        return out

    def _party_names(self, db, table, firm_id, client_id) -> dict:
        try:
            rows = (db.table(table).select("id, name")
                    .eq("firm_id", firm_id).eq("client_id", client_id).execute().data or [])
            return {r["id"]: r.get("name") for r in rows}
        except Exception:
            return {}

    def _invoice_candidates(self, db, firm_id, client_id, amount) -> list[Candidate]:
        # deleted_at filter: a soft-deleted invoice is not a live receivable and
        # must never be suggested as the counterparty for a bank credit.
        rows = (db.table("client_sales_invoices")
                .select("id, invoice_no, invoice_date, total_paise, paid_paise, customer_id, status")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .is_("deleted_at", "null")
                .eq("total_paise", amount).execute().data or [])
        customers = self._party_names(db, "customers", firm_id, client_id)
        out = []
        for r in rows:
            if str(r.get("status")) == "cancelled":
                continue
            paid = int(r.get("paid_paise") or 0)
            total = int(r.get("total_paise") or 0)
            if paid >= total:
                continue  # fully paid → not open
            party = customers.get(r.get("customer_id"))
            out.append(Candidate(
                entity_type="sales_invoice", entity_id=r["id"],
                label=f"{r.get('invoice_no', '')} · {party or 'Customer'}",
                amount_paise=total, entity_date=str(r.get("invoice_date") or "")[:10],
                party_name=party, outstanding_paise=total - paid,
            ))
        return out

    def _bill_candidates(self, db, firm_id, client_id, amount) -> list[Candidate]:
        # Match on net_payable_paise, not total_paise: the money that actually
        # leaves the bank for a vendor equals the bill's NET payable (total minus
        # any TDS withheld / debit-note / credit-note adjustment) — which is also
        # exactly what settlement relieves. Gating on total_paise meant any bill
        # with TDS never surfaced as a candidate for its own outgoing payment.
        # deleted_at filter: a soft-deleted bill is not a live payable.
        rows = (db.table("purchase_bills")
                .select("id, bill_no, bill_date, total_paise, net_payable_paise, vendor_id, status")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .is_("deleted_at", "null")
                .eq("net_payable_paise", amount).execute().data or [])
        vendors = self._party_names(db, "vendors", firm_id, client_id)
        out = []
        for r in rows:
            if str(r.get("status")) in ("cancelled", "paid"):
                continue
            party = vendors.get(r.get("vendor_id"))
            # Present the payable (what's owed), not the gross bill total.
            net_payable = int(r.get("net_payable_paise") or r.get("total_paise") or 0)
            out.append(Candidate(
                entity_type="purchase_bill", entity_id=r["id"],
                label=f"{r.get('bill_no', '')} · {party or 'Vendor'}",
                amount_paise=net_payable, entity_date=str(r.get("bill_date") or "")[:10],
                party_name=party, outstanding_paise=net_payable,
            ))
        return out

    def _receipt_candidates(self, db, firm_id, client_id, amount) -> list[Candidate]:
        rows = (db.table("receipts").select("id, receipt_no, receipt_date, amount_paise")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("amount_paise", amount).execute().data or [])
        return [Candidate(
            entity_type="receipt", entity_id=r["id"],
            label=f"Receipt {r.get('receipt_no', '')}", amount_paise=int(r.get("amount_paise") or 0),
            entity_date=str(r.get("receipt_date") or "")[:10],
        ) for r in rows]

    def _payment_candidates(self, db, firm_id, client_id, amount) -> list[Candidate]:
        rows = (db.table("purchase_payments").select("id, payment_no, payment_date, amount_paise")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("amount_paise", amount).execute().data or [])
        return [Candidate(
            entity_type="purchase_payment", entity_id=r["id"],
            label=f"Payment {r.get('payment_no', '')}", amount_paise=int(r.get("amount_paise") or 0),
            entity_date=str(r.get("payment_date") or "")[:10],
        ) for r in rows]

    def _journal_candidates(self, db, firm_id, client_id, amount) -> list[Candidate]:
        rows = (db.table("journal_entries")
                .select("id, entry_date, narration, reference_no, "
                        "journal_lines(debit_paise, credit_paise)")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("is_posted", True).limit(200).execute().data or [])
        out = []
        for e in rows:
            if any(int(l.get("debit_paise") or 0) == amount or int(l.get("credit_paise") or 0) == amount
                   for l in (e.get("journal_lines") or [])):
                out.append(Candidate(
                    entity_type="journal_entry", entity_id=e["id"],
                    label=f"{e.get('reference_no') or 'JE'} · {(e.get('narration') or '')[:32]}",
                    amount_paise=amount, entity_date=str(e.get("entry_date") or "")[:10],
                ))
        return out

    # ── B.2.4 — unmatched work queue ─────────────────────────────────────────
    _QUEUE_STATUSES = frozenset({"unmatched", "categorized", "matched", "needs_review", "all"})

    def queue(self, db, firm_id: str, client_id: Optional[str], status: str = "unmatched") -> list[dict]:
        if status not in self._QUEUE_STATUSES:
            raise HTTPException(status_code=422, detail="Invalid queue status.")
        q = db.table("bank_transactions").select("*").eq("firm_id", firm_id)
        if client_id:
            q = q.eq("client_id", client_id)
        txns = q.order("transaction_date").execute().data or []

        # View filter (Python-side — avoids NULL-filter quirks; bounded per client).
        def keep(t: dict) -> bool:
            if status == "unmatched":
                return t.get("match_status") == "unmatched" and not t.get("matched_entity_id")
            if status == "categorized":
                return bool(t.get("category"))
            if status == "matched":
                return bool(t.get("matched_entity_id"))
            if status == "needs_review":
                return bool(t.get("needs_review"))
            return True  # all
        txns = [t for t in txns if keep(t)]

        rules = (db.table("bank_matching_rules").select("*")
                 .eq("firm_id", firm_id).eq("is_active", True).execute().data or [])
        for t in txns:
            amount, is_credit = _txn_amount(t)
            t["suggested_category"] = (t.get("category")
                                       or suggest_category(t.get("description"), amount, not is_credit, rules))
        return txns

    # ── B.2.2 — categorize (manual or accepting a rule suggestion) ───────────
    def categorize(self, db, firm_id: str, txn_id: str, category: str) -> dict:
        if not is_valid_category(category):
            raise HTTPException(status_code=422,
                                detail=f"Invalid category. Allowed: {', '.join(CATEGORIES)}")
        self._get_txn(db, firm_id, txn_id)
        db.table("bank_transactions").update({
            "category": category, "updated_at": _now(),
        }).eq("id", txn_id).eq("firm_id", firm_id).execute()
        return {"id": txn_id, "category": category}

    # ── B.2.5 — manual match (accept suggestion / link) ──────────────────────
    def match(self, db, firm_id: str, txn_id: str, entity_type: str, entity_id: str,
              category: Optional[str] = None, actor_id: Optional[str] = None) -> dict:
        if entity_type not in _MATCH_ENTITY_TYPES:
            raise HTTPException(status_code=422, detail="Invalid matched_entity_type.")
        if category is not None and not is_valid_category(category):
            raise HTTPException(status_code=422, detail="Invalid category.")
        # Accepting a suggestion with no explicit category must not leave the
        # transaction uncategorized — derive the category the matched entity
        # implies (see _MATCH_DEFAULT_CATEGORY). An explicit category always wins.
        if category is None:
            category = _MATCH_DEFAULT_CATEGORY.get(entity_type)
        txn = self._get_txn(db, firm_id, txn_id)
        if txn.get("match_status") == "posted":
            raise HTTPException(status_code=409, detail="Transaction already posted to the ledger.")
        update = {
            "matched_entity_type": entity_type, "matched_entity_id": entity_id,
            "matched_by": actor_id, "matched_at": _now(),
            "match_status": "matched", "needs_review": False, "updated_at": _now(),
        }
        if category is not None:
            update["category"] = category
        db.table("bank_transactions").update(update).eq("id", txn_id).eq("firm_id", firm_id).execute()
        try:
            from services.audit_service import log_event
            log_event(firm_id, "bank_transaction", txn_id, "update", actor_id=actor_id,
                      new_data={"matched_entity_type": entity_type, "matched_entity_id": entity_id,
                                "category": update.get("category")},
                      metadata={"source": "bank_match"})
        except Exception:  # pragma: no cover
            pass
        try:
            timeline_service.log(txn["client_id"], "accounting", "Bank Transaction Matched",
                                 f"Matched to {entity_type} (CA reviewed)", "info",
                                 firm_id=firm_id, entity_type="bank_transaction",
                                 entity_id=txn_id, actor_id=actor_id)
        except Exception:  # pragma: no cover
            pass
        return {"id": txn_id, "match_status": "matched", "matched_entity_type": entity_type,
                "matched_entity_id": entity_id, "category": update.get("category")}

    # ── reject suggestion / clear a manual match ─────────────────────────────
    def unmatch(self, db, firm_id: str, txn_id: str) -> dict:
        txn = self._get_txn(db, firm_id, txn_id)
        if txn.get("match_status") == "posted":
            raise HTTPException(status_code=409, detail="Cannot unmatch a posted transaction.")
        db.table("bank_transactions").update({
            "matched_entity_type": None, "matched_entity_id": None,
            "matched_by": None, "matched_at": None,
            "match_status": "unmatched", "updated_at": _now(),
        }).eq("id", txn_id).eq("firm_id", firm_id).execute()
        return {"id": txn_id, "match_status": "unmatched"}


bank_matching_service = BankMatchingService()
