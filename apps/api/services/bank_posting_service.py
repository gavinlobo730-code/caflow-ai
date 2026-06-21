"""
Bank posting service (Banking B.3) — Match → Journal → Settlement.

Turns a categorized/matched bank transaction into a balanced journal entry via
the shared double-entry engine (phase2_journal_service), then settles the linked
sales invoice / purchase bill. NEVER auto-posts: the caller (an explicit user
action) drives this; the FY lock is enforced; and a transaction can post exactly
once (posted_journal_id guard). All integer paise.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from services.phase2_journal_service import phase2_journal_service
from services.period_validation_service import period_validation_service
from services.timeline_service import timeline_service
from domain.banking import posting_map as pmap

_logger = logging.getLogger("caflow.bank_posting")

_VALID_CATEGORIES = set(pmap.AUTO_COUNTER) | set(pmap.EXPLICIT_COUNTER) | {pmap.TRANSFER}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _amount(txn: dict) -> tuple[int, bool]:
    debit = int(txn.get("debit_paise") or 0)
    credit = int(txn.get("credit_paise") or 0)
    return max(debit, credit), credit > 0


class BankPostingService:

    def _get_txn(self, db, firm_id: str, txn_id: str) -> dict:
        res = (db.table("bank_transactions").select("*")
               .eq("id", txn_id).eq("firm_id", firm_id).single().execute())
        if not res.data:
            raise HTTPException(status_code=404, detail="Bank transaction not found.")
        return res.data

    def _account_name(self, db, firm_id: str, account_id: str) -> str:
        try:
            r = (db.table("chart_of_accounts").select("account_name")
                 .eq("id", account_id).eq("firm_id", firm_id).single().execute())
            return (r.data or {}).get("account_name", account_id)
        except Exception:
            return account_id

    def _validate_account(self, db, firm_id: str, account_id: str) -> str:
        r = (db.table("chart_of_accounts").select("id")
             .eq("id", account_id).eq("firm_id", firm_id).limit(1).execute())
        if not r.data:
            raise HTTPException(status_code=422, detail="Selected account not found for this firm.")
        return account_id

    # ── account resolution ───────────────────────────────────────────────────
    def _resolve_bank(self, db, firm_id, txn, bank_account_id: Optional[str]) -> str:
        if bank_account_id:
            return self._validate_account(db, firm_id, bank_account_id)
        # From the statement's linked bank account → its GL (coa) account.
        stmt_id = txn.get("statement_id")
        if stmt_id:
            try:
                stmt = (db.table("bank_statements").select("bank_account_id")
                        .eq("id", stmt_id).single().execute().data) or {}
                ba_id = stmt.get("bank_account_id")
                if ba_id:
                    ba = (db.table("bank_accounts").select("coa_account_id")
                          .eq("id", ba_id).single().execute().data) or {}
                    if ba.get("coa_account_id"):
                        return ba["coa_account_id"]
            except Exception:
                pass
        # Fall back to the firm's master Bank account.
        return phase2_journal_service._find_account(db, firm_id, txn["client_id"], "%Bank%", system_key="bank")

    def _resolve_counter(self, db, firm_id, txn, account_id: Optional[str]) -> str:
        cat = txn.get("category")
        matched_type = txn.get("matched_entity_type")
        client_id = txn["client_id"]
        if cat and cat not in _VALID_CATEGORIES:
            raise HTTPException(status_code=422, detail=f"Invalid category '{cat}'.")
        # A matched sales invoice always settles against Trade Receivables.
        if cat in pmap.SETTLES_SALES_INVOICE and matched_type == "sales_invoice":
            return phase2_journal_service._find_account(db, firm_id, client_id, "%Trade Receivable%", system_key="ar")
        if cat in pmap.AUTO_COUNTER:
            sk, pattern = pmap.AUTO_COUNTER[cat]
            return phase2_journal_service._find_account(db, firm_id, client_id, pattern, system_key=sk)
        if cat in pmap.EXPLICIT_COUNTER:
            if not account_id:
                raise HTTPException(status_code=422,
                                    detail=f"Select a GL account for '{cat}' before posting.")
            return self._validate_account(db, firm_id, account_id)
        if not cat and account_id:           # legacy account-mapping post (no category)
            return self._validate_account(db, firm_id, account_id)
        raise HTTPException(status_code=422,
                            detail="Categorize the transaction (or map an account) before posting.")

    def _plan(self, db, firm_id, txn, bank_account_id, account_id, to_bank_account_id):
        """Resolve accounts and build balanced lines. Returns (entry_type, lines, bank_id)."""
        amount, is_credit = _amount(txn)
        if amount <= 0:
            raise HTTPException(status_code=422, detail="Transaction has zero amount.")
        cat = txn.get("category")
        bank_id = self._resolve_bank(db, firm_id, txn, bank_account_id)
        if cat == pmap.TRANSFER:
            if not to_bank_account_id:
                raise HTTPException(status_code=422, detail="Transfer requires a destination bank/cash account.")
            to_id = self._validate_account(db, firm_id, to_bank_account_id)
            lines = pmap.build_transfer_lines(amount, is_credit, bank_id, to_id)
        else:
            counter_id = self._resolve_counter(db, firm_id, txn, account_id)
            lines = pmap.build_lines(amount, is_credit, bank_id, counter_id)
        return pmap.entry_type_for(cat, is_credit), lines, bank_id

    # ── B.3 review preview (no writes) ───────────────────────────────────────
    def preview(self, db, firm_id, txn_id, bank_account_id=None, account_id=None,
                to_bank_account_id=None) -> dict:
        txn = self._get_txn(db, firm_id, txn_id)
        if txn.get("posted_journal_id"):
            raise HTTPException(status_code=409, detail="Transaction already posted.")
        entry_type, lines, _ = self._plan(db, firm_id, txn, bank_account_id, account_id, to_bank_account_id)
        amount, _ = _amount(txn)
        return {
            "transaction_id": txn_id,
            "category": txn.get("category"),
            "entry_type": entry_type,
            "narration": f"Bank: {txn.get('description', '')}".strip(),
            "lines": [{
                "account_id": l["account_id"],
                "account_name": self._account_name(db, firm_id, l["account_id"]),
                "debit_paise": l["debit_paise"], "credit_paise": l["credit_paise"],
            } for l in lines],
            "total_debit_paise": sum(l["debit_paise"] for l in lines),
            "total_credit_paise": sum(l["credit_paise"] for l in lines),
            "settlement": self._settlement_preview(db, firm_id, txn, amount),
        }

    def _settlement_preview(self, db, firm_id, txn, amount) -> Optional[dict]:
        cat, mt, mid = txn.get("category"), txn.get("matched_entity_type"), txn.get("matched_entity_id")
        client_id = txn.get("client_id")
        if cat in pmap.SETTLES_SALES_INVOICE and mt == "sales_invoice" and mid:
            # H4 fix: scope to the txn's firm + client so a foreign matched_entity_id
            # cannot disclose another firm/client's invoice details.
            inv = (db.table("client_sales_invoices").select("invoice_no, total_paise, paid_paise")
                   .eq("id", mid).eq("firm_id", firm_id).eq("client_id", client_id).maybe_single().execute().data) or {}
            total, paid = int(inv.get("total_paise") or 0), int(inv.get("paid_paise") or 0)
            alloc = min(amount, max(total - paid, 0))
            return {"entity": "sales_invoice", "label": inv.get("invoice_no"),
                    "allocate_paise": alloc, "new_paid_paise": paid + alloc, "total_paise": total}
        if cat in pmap.SETTLES_PURCHASE_BILL and mt == "purchase_bill" and mid:
            bill = (db.table("purchase_bills").select("bill_no, total_paise, paid_paise")
                    .eq("id", mid).eq("firm_id", firm_id).eq("client_id", client_id).maybe_single().execute().data) or {}
            total, paid = int(bill.get("total_paise") or 0), int(bill.get("paid_paise") or 0)
            alloc = min(amount, max(total - paid, 0))
            return {"entity": "purchase_bill", "label": bill.get("bill_no"),
                    "allocate_paise": alloc, "new_paid_paise": paid + alloc, "total_paise": total}
        return None

    # ── B.3.2 post → Phase 3.5: create a DRAFT journal (no books impact yet) ───
    def post(self, db, firm_id, txn_id, bank_account_id=None, account_id=None,
             to_bank_account_id=None, actor_id=None) -> dict:
        """Create a DRAFT journal for the bank transaction. The transaction is NOT
        settled, NOT marked posted, and NOT reconciled — those happen only when a
        human approves the draft (journal_posting_service.post_draft →
        settle_on_post). One draft per transaction (idempotent)."""
        txn = self._get_txn(db, firm_id, txn_id)
        if txn.get("posted_journal_id") or txn.get("match_status") == "posted":
            raise HTTPException(status_code=409,
                                detail="A journal has already been created for this transaction.")
        client_id = txn["client_id"]
        entry_date = str(txn["transaction_date"])[:10]

        entry_type, lines, _bank_id = self._plan(
            db, firm_id, txn, bank_account_id, account_id, to_bank_account_id)

        journal_entry_id = phase2_journal_service._create_journal(
            db, firm_id=firm_id, client_id=client_id, entry_date=entry_date,
            reference_no=f"BANK-{txn_id}",       # one journal per txn (dedup)
            narration=f"Bank: {txn.get('description', '')}".strip(),
            entry_type=entry_type, lines=lines,
            is_posted=False, source_type="bank_transaction", source_id=txn_id,
            created_by=actor_id,
        )

        # Link the DRAFT journal. Leave match_status / posted_at / settlement alone
        # until the draft is approved — posted_at is the "truly posted" marker.
        db.table("bank_transactions").update({
            "posted_journal_id": journal_entry_id, "updated_at": _now(),
        }).eq("id", txn_id).eq("firm_id", firm_id).execute()

        try:
            from services.audit_service import log_event
            log_event(firm_id, "bank_transaction", txn_id, "status_change", actor_id=actor_id,
                      new_data={"draft_journal_id": journal_entry_id, "category": txn.get("category")},
                      metadata={"source": "bank_draft", "stage": "draft_created"})
        except Exception:  # pragma: no cover - audit must never block
            pass
        try:
            timeline_service.log(client_id, "accounting", "Draft Journal Created",
                                 f"Draft created from bank transaction ({txn.get('category') or 'mapped'}) — awaiting approval",
                                 "info", firm_id=firm_id, entity_type="bank_transaction",
                                 entity_id=txn_id, actor_id=actor_id)
        except Exception:  # pragma: no cover
            pass

        return {"id": txn_id, "status": "draft", "draft_journal_id": journal_entry_id}

    # ── Deferred settlement — runs only when the draft journal is posted ───────
    def settle_on_post(self, db, firm_id, txn_id, journal_id, actor_id=None) -> Optional[dict]:
        """Called by journal_posting_service.post_draft once the bank draft is on
        the books: mark the transaction posted and settle its invoice/bill. Idempotent."""
        txn = self._get_txn(db, firm_id, txn_id)
        if txn.get("match_status") == "posted":
            return None                                   # already settled (idempotent)
        db.table("bank_transactions").update({
            "match_status": "posted", "posted_at": _now(), "posted_by": actor_id,
            "posted_journal_id": journal_id, "updated_at": _now(),
        }).eq("id", txn_id).eq("firm_id", firm_id).execute()

        amount, _ = _amount(txn)
        settled = self._settle(db, firm_id, txn, amount)
        try:
            timeline_service.log(txn["client_id"], "accounting", "Bank Transaction Posted",
                                 f"Posted to ledger ({txn.get('category') or 'mapped'})", "success",
                                 firm_id=firm_id, entity_type="bank_transaction",
                                 entity_id=txn_id, actor_id=actor_id)
        except Exception:  # pragma: no cover
            pass
        return settled

    # ── B.3.4 settlement ──────────────────────────────────────────────────────
    def _settle(self, db, firm_id, txn, amount) -> Optional[dict]:
        cat, mt, mid = txn.get("category"), txn.get("matched_entity_type"), txn.get("matched_entity_id")
        if cat in pmap.SETTLES_SALES_INVOICE and mt == "sales_invoice" and mid:
            return self._settle_doc(db, firm_id, "client_sales_invoices", mid, amount, "invoice_no")
        if cat in pmap.SETTLES_PURCHASE_BILL and mt == "purchase_bill" and mid:
            return self._settle_doc(db, firm_id, "purchase_bills", mid, amount, "bill_no")
        return None

    def _settle_doc(self, db, firm_id, table, doc_id, amount, label_col) -> Optional[dict]:
        doc = (db.table(table).select(f"id, {label_col}, total_paise, paid_paise, status")
               .eq("id", doc_id).eq("firm_id", firm_id).single().execute().data)
        if not doc:
            return None
        total = int(doc.get("total_paise") or 0)
        paid = int(doc.get("paid_paise") or 0)
        alloc = min(int(amount), max(total - paid, 0))   # never over-allocate
        if alloc <= 0:
            return {"entity": table, "label": doc.get(label_col), "allocated_paise": 0,
                    "status": doc.get("status"), "note": "already fully settled"}
        new_paid = paid + alloc
        status = "paid" if new_paid >= total else "partially_paid"
        db.table(table).update({"paid_paise": new_paid, "status": status, "updated_at": _now()}) \
            .eq("id", doc_id).eq("firm_id", firm_id).execute()
        return {"entity": table, "label": doc.get(label_col), "allocated_paise": alloc,
                "new_paid_paise": new_paid, "total_paise": total, "status": status}

    # ── B.3.1 queues ──────────────────────────────────────────────────────────
    def ready_to_post(self, db, firm_id, client_id: Optional[str]) -> list[dict]:
        q = db.table("bank_transactions").select("*").eq("firm_id", firm_id)
        if client_id:
            q = q.eq("client_id", client_id)
        rows = q.order("transaction_date").execute().data or []
        return [t for t in rows
                if t.get("category") and not t.get("posted_journal_id")
                and t.get("match_status") not in ("posted", "ignored")]

    def pending(self, db, firm_id, client_id: Optional[str]) -> list[dict]:
        """Draft journal created, awaiting approval (linked journal but not yet posted)."""
        q = db.table("bank_transactions").select("*").eq("firm_id", firm_id)
        if client_id:
            q = q.eq("client_id", client_id)
        rows = q.order("transaction_date").execute().data or []
        return [t for t in rows
                if t.get("posted_journal_id") and not t.get("posted_at")
                and t.get("match_status") != "posted"]

    def posted(self, db, firm_id, client_id: Optional[str]) -> list[dict]:
        """Truly posted — the draft was approved (posted_at set)."""
        q = db.table("bank_transactions").select("*").eq("firm_id", firm_id)
        if client_id:
            q = q.eq("client_id", client_id)
        rows = q.order("transaction_date", desc=True).execute().data or []
        return [t for t in rows if t.get("posted_at")]


bank_posting_service = BankPostingService()
