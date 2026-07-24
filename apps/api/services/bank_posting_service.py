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
        # task #228 audit finding: neither lookup was scoped by firm/client —
        # an unscoped read-by-id in a money-posting path, the exact "query
        # returns a row but the code never verifies it belongs to the
        # caller's tenant" pattern task #227 fixed for AR/AP. Scoped here to
        # THIS transaction's firm+client, mirroring _validate_account's own
        # scoping just above.
        stmt_id = txn.get("statement_id")
        client_id = txn["client_id"]
        if stmt_id:
            try:
                stmt = (db.table("bank_statements").select("bank_account_id")
                        .eq("id", stmt_id).eq("firm_id", firm_id).eq("client_id", client_id)
                        .single().execute().data) or {}
                ba_id = stmt.get("bank_account_id")
                if ba_id:
                    ba = (db.table("bank_accounts").select("coa_account_id")
                          .eq("id", ba_id).eq("firm_id", firm_id).eq("client_id", client_id)
                          .single().execute().data) or {}
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
            inv = (db.table("client_sales_invoices")
                   .select("invoice_no, total_paise, paid_paise, credited_paise, debit_note_paise")
                   .eq("id", mid).eq("firm_id", firm_id).eq("client_id", client_id).maybe_single().execute().data) or {}
            total = int(inv.get("total_paise") or 0)
            paid = int(inv.get("paid_paise") or 0)
            outstanding = self._invoice_outstanding(inv)
            alloc = min(amount, outstanding)
            out = {"entity": "sales_invoice", "label": inv.get("invoice_no"),
                   "allocate_paise": alloc, "new_paid_paise": paid + alloc, "total_paise": total}
            if amount > alloc:
                out["credited_to_party_paise"] = amount - alloc   # task #102: excess → party credit, not lost
            return out
        if cat in pmap.SETTLES_PURCHASE_BILL and mt == "purchase_bill" and mid:
            bill = (db.table("purchase_bills")
                    .select("bill_no, total_paise, net_payable_paise, paid_paise, debited_paise, credit_note_paise")
                    .eq("id", mid).eq("firm_id", firm_id).eq("client_id", client_id).maybe_single().execute().data) or {}
            total = int(bill.get("total_paise") or 0)
            paid = int(bill.get("paid_paise") or 0)
            outstanding = self._bill_outstanding(bill)
            alloc = min(amount, outstanding)
            out = {"entity": "purchase_bill", "label": bill.get("bill_no"),
                   "allocate_paise": alloc, "new_paid_paise": paid + alloc, "total_paise": total}
            if amount > alloc:
                out["credited_to_party_paise"] = amount - alloc   # task #102: excess → party credit, not lost
            return out
        return None

    # ── True outstanding (task #102: _settle_doc used total_paise − paid_paise,
    # ignoring credit/debit notes and (for bills) the TDS-net net_payable_paise vs
    # gross total_paise — the SAME formula ar_aging/ap_aging already use elsewhere
    # (CGST Act §34), so the bank settlement sub-ledger reconciles with them. ──
    @staticmethod
    def _invoice_outstanding(inv: dict) -> int:
        total = int(inv.get("total_paise") or 0) + int(inv.get("debit_note_paise") or 0)
        paid = int(inv.get("paid_paise") or 0)
        credited = int(inv.get("credited_paise") or 0)
        return max(total - paid - credited, 0)

    @staticmethod
    def _bill_outstanding(bill: dict) -> int:
        net_payable = int(bill.get("net_payable_paise") or bill.get("total_paise") or 0)
        net_payable += int(bill.get("credit_note_paise") or 0)
        paid = int(bill.get("paid_paise") or 0)
        debited = int(bill.get("debited_paise") or 0)
        return max(net_payable - paid - debited, 0)

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
        # M9: block creating a draft destined for a locked financial year — consistent
        # with the invoice/bill posting paths (this path previously skipped the check).
        period_validation_service.validate_posting_date(firm_id or "", entry_date)

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
        settled = self._settle(db, firm_id, txn, amount, actor_id)
        try:
            timeline_service.log(txn["client_id"], "accounting", "Bank Transaction Posted",
                                 f"Posted to ledger ({txn.get('category') or 'mapped'})", "success",
                                 firm_id=firm_id, entity_type="bank_transaction",
                                 entity_id=txn_id, actor_id=actor_id)
        except Exception:  # pragma: no cover
            pass
        return settled

    # ── B.3.4 settlement ──────────────────────────────────────────────────────
    def _settle(self, db, firm_id, txn, amount, actor_id=None) -> Optional[dict]:
        cat, mt, mid = txn.get("category"), txn.get("matched_entity_type"), txn.get("matched_entity_id")
        client_id = txn.get("client_id")
        if cat in pmap.SETTLES_SALES_INVOICE and mt == "sales_invoice" and mid:
            return self._settle_doc(db, firm_id, client_id, "client_sales_invoices", mid, amount, "invoice_no",
                                    "total_paise, debit_note_paise, credited_paise, customer_id",
                                    self._invoice_outstanding, "customer_id", "customer", txn, actor_id)
        if cat in pmap.SETTLES_PURCHASE_BILL and mt == "purchase_bill" and mid:
            return self._settle_doc(db, firm_id, client_id, "purchase_bills", mid, amount, "bill_no",
                                    "total_paise, net_payable_paise, credit_note_paise, debited_paise, vendor_id",
                                    self._bill_outstanding, "vendor_id", "vendor", txn, actor_id)
        return None

    def _settle_doc(self, db, firm_id, client_id, table, doc_id, amount, label_col,
                    extra_cols, outstanding_fn, party_col, party_type, txn, actor_id=None) -> Optional[dict]:
        # F3 fix: scope the settled doc to the txn's firm AND client so a
        # matched_entity_id belonging to another client (even within the firm)
        # cannot be settled / have its accounting state altered. Mirrors the
        # preview-path scoping (H4). maybe_single ⇒ no row → no settlement.
        _rows = (db.table(table).select(f"id, {label_col}, paid_paise, status, {extra_cols}")
                 .eq("id", doc_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data) or []
        doc = _rows[0] if _rows else None
        if not doc:
            return None
        total = int(doc.get("total_paise") or 0)
        paid = int(doc.get("paid_paise") or 0)
        # task #102: this used to allocate against (total_paise − paid_paise),
        # ignoring credit/debit notes entirely and — for bills — using the
        # GROSS total_paise instead of the TDS-net net_payable_paise, so a
        # bill with TDS withheld (or either document with a credit/debit
        # note applied) could be under- or over-allocated relative to what's
        # actually outstanding. outstanding_fn matches ar_aging/ap_aging's
        # formula (CGST Act §34) so the sub-ledger reconciles with them.
        outstanding = outstanding_fn(doc)
        alloc = min(int(amount), outstanding)   # never over-allocate the DOCUMENT
        excess = int(amount) - alloc            # the rest — a genuine overpayment
        if excess > 0:
            # task #102: the GL side is already correct (the transaction's FULL
            # amount was posted to Trade Receivables/Payables by the draft
            # journal) — only the sub-ledger tracking of "whose money is this"
            # was missing. Grant it as a non-GST party credit rather than
            # silently letting it vanish from tracking.
            from services.party_credit_service import party_credit_service
            party_id = doc.get(party_col)
            if party_id:
                party_credit_service.grant_credit(
                    db, firm_id, client_id, party_type, party_id, excess,
                    source_type="bank_overpayment", source_id=txn.get("id"), created_by=actor_id,
                    notes=f"Overpayment on {table} {doc.get(label_col)} via bank transaction {txn.get('id')}",
                )
        if alloc <= 0:
            return {"entity": table, "label": doc.get(label_col), "allocated_paise": 0,
                    "status": doc.get("status"), "note": "already fully settled",
                    **({"credited_to_party_paise": excess} if excess > 0 else {})}
        new_paid = paid + alloc
        status = "paid" if alloc >= outstanding else "partially_paid"
        db.table(table).update({"paid_paise": new_paid, "status": status, "updated_at": _now()}) \
            .eq("id", doc_id).eq("firm_id", firm_id).eq("client_id", client_id).execute()
        result = {"entity": table, "label": doc.get(label_col), "allocated_paise": alloc,
                  "new_paid_paise": new_paid, "total_paise": total, "status": status}
        if excess > 0:
            result["credited_to_party_paise"] = excess
        return result

    # ── Multi-invoice bank allocation ────────────────────────────────────────
    def match_and_settle_multi(
        self, db, firm_id: str, txn_id: str, entity_type: str, allocations: list[dict],
        reference_no: Optional[str] = None, notes: Optional[str] = None,
        tds_paise: int = 0, currency: Optional[str] = None, exchange_rate=None,
        actor: Optional[dict] = None,
    ) -> dict:
        """Match ONE bank transaction to MULTIPLE sales invoices / purchase bills
        in a single settlement.

        Unlike the 1:1 flow (match -> post a DRAFT 'BANK-{txn_id}' journal ->
        approve -> settle_on_post, which settles the ALREADY-linked document
        separately from posting), this creates the REAL receipt / purchase_payment
        record with its own allocations — reusing receipt_service.create_receipt_core
        / purchase_payment_service.create_payment_core VERBATIM, so the same
        CAS-guarded settlement, live-outstanding pre-validation, and
        compensation-on-failure machinery already hardened for the manual
        Receipts/Payments pages applies here too, for both INR and foreign
        currency (create_receipt_core/create_payment_core auto-dispatch to their
        FX path when `currency` isn't INR).

        Exactly ONE journal is posted — the receipt/payment's own — so the bank
        transaction is linked to IT (matched_entity_type='receipt' /
        'purchase_payment') rather than getting a second, separate
        'BANK-{txn_id}' journal; posting both would double-count the cash
        movement (the same class of gap that would exist if a bank transaction
        were 1:1-matched to an ALREADY-existing receipt/payment and then posted
        through the normal draft-journal flow).
        """
        txn = self._get_txn(db, firm_id, txn_id)
        raw_match_status = txn.get("match_status")
        if raw_match_status in ("posted", "matched") or txn.get("posted_journal_id"):
            raise HTTPException(status_code=409, detail="Transaction already matched/posted.")
        amount, is_credit = _amount(txn)
        if amount <= 0:
            raise HTTPException(status_code=422, detail="Transaction has zero amount.")
        if entity_type == "sales_invoice" and not is_credit:
            raise HTTPException(status_code=422,
                detail="A debit transaction (money leaving the bank) cannot settle sales invoices.")
        if entity_type == "purchase_bill" and is_credit:
            raise HTTPException(status_code=422,
                detail="A credit transaction (money arriving in the bank) cannot settle purchase bills.")
        if not allocations:
            raise HTTPException(status_code=422, detail="Select at least one invoice/bill to allocate.")

        client_id = txn["client_id"]
        total_alloc = sum(int(a["allocated_paise"]) for a in allocations)
        settlement_cap = amount + (tds_paise if entity_type == "sales_invoice" else 0)
        if total_alloc > settlement_cap:
            raise HTTPException(status_code=422,
                detail=f"Total allocated ({total_alloc} paise) exceeds the transaction amount ({settlement_cap} paise).")

        if entity_type == "sales_invoice":
            party_col, doc_table, alloc_key = "customer_id", "client_sales_invoices", "sales_invoice_id"
        else:
            party_col, doc_table, alloc_key = "vendor_id", "purchase_bills", "purchase_bill_id"

        doc_ids = [a["entity_id"] for a in allocations]
        docs = (db.table(doc_table).select(f"id, {party_col}")
                .in_("id", doc_ids).eq("firm_id", firm_id).eq("client_id", client_id).execute().data or [])
        found = {d["id"] for d in docs}
        missing = [d for d in doc_ids if d not in found]
        if missing:
            raise HTTPException(status_code=422,
                detail=f"Not part of this client's books: {', '.join(missing)}")
        party_ids = {d[party_col] for d in docs}
        if len(party_ids) != 1:
            raise HTTPException(status_code=422,
                detail="All selected invoices/bills must belong to the SAME customer/vendor — "
                       "a single bank transaction settles one party's documents.")
        party_id = party_ids.pop()

        # Concurrency guard (task #220): claim exclusive posting rights on this
        # transaction BEFORE creating the receipt/payment. Unlike the 1:1 post()
        # flow — naturally protected by _create_journal's deterministic
        # BANK-{txn_id} reference idempotency — this flow creates a REAL
        # receipt/payment with its own freshly-sequenced reference each call, so
        # two near-simultaneous calls that both read the txn as unmatched above
        # would otherwise both create one, double-posting the cash movement.
        # "matched" is the same real status bank_matching_service.match() already
        # uses for a linked-but-not-yet-posted transaction — no schema change.
        # A concurrent loser's CAS finds match_status already changed and gets
        # zero rows back.
        claim = (db.table("bank_transactions").update({
            "match_status": "matched", "updated_at": _now(),
        }).eq("id", txn_id).eq("firm_id", firm_id)
          .eq("match_status", raw_match_status)
          .is_("posted_journal_id", "null")
          .execute())
        if not claim.data:
            raise HTTPException(status_code=409, detail="Transaction already matched/posted.")

        date = str(txn["transaction_date"])[:10]
        alloc_payloads = [{alloc_key: a["entity_id"], "allocated_paise": int(a["allocated_paise"])} for a in allocations]

        try:
            if entity_type == "sales_invoice":
                from services import receipt_service
                data = {
                    "client_id": client_id, "customer_id": party_id, "receipt_date": date,
                    "amount_paise": amount, "tds_paise": tds_paise, "payment_mode": "bank",
                    "reference_no": reference_no or txn.get("reference_no"), "notes": notes,
                    "allocations": alloc_payloads,
                }
                if currency:
                    data["currency"] = currency
                if exchange_rate is not None:
                    data["exchange_rate"] = exchange_rate
                result = receipt_service.create_receipt_core(firm_id, data, actor or {}, db)
                new_entity_type, category = "receipt", "Customer Payment"
            else:
                from services import purchase_payment_service
                data = {
                    "client_id": client_id, "vendor_id": party_id, "payment_date": date,
                    "amount_paise": amount, "payment_mode": "bank",
                    "reference_no": reference_no or txn.get("reference_no"), "notes": notes,
                    "allocations": alloc_payloads,
                }
                if currency:
                    data["currency"] = currency
                if exchange_rate is not None:
                    data["exchange_rate"] = exchange_rate
                result = purchase_payment_service.create_payment_core(firm_id, data, actor or {}, db)
                new_entity_type, category = "purchase_payment", "Vendor Payment"
        except Exception:
            # Release the claim so a failed settlement (e.g. a 422 business-rule
            # rejection) doesn't leave the transaction permanently stuck
            # "matched" with no receipt/payment behind it — the CA can retry.
            db.table("bank_transactions").update({
                "match_status": raw_match_status, "updated_at": _now(),
            }).eq("id", txn_id).eq("firm_id", firm_id).eq("match_status", "matched").execute()
            raise

        journal_id = result.get("journal_entry_id")
        db.table("bank_transactions").update({
            "matched_entity_type": new_entity_type, "matched_entity_id": result["id"],
            "matched_by": (actor or {}).get("auth_user_id"), "matched_at": _now(),
            "match_status": "posted", "posted_at": _now(), "posted_by": (actor or {}).get("auth_user_id"),
            "posted_journal_id": journal_id, "category": category, "needs_review": False,
            "updated_at": _now(),
        }).eq("id", txn_id).eq("firm_id", firm_id).execute()

        try:
            timeline_service.log(
                client_id, "accounting", "Bank Transaction Matched (multi)",
                f"Matched to {len(allocations)} {'invoice(s)' if entity_type == 'sales_invoice' else 'bill(s)'} "
                f"via {new_entity_type} {result.get('receipt_no') or result.get('payment_no') or ''}".strip(),
                "success", firm_id=firm_id, entity_type="bank_transaction",
                entity_id=txn_id, actor_id=(actor or {}).get("auth_user_id"),
            )
        except Exception:  # pragma: no cover
            pass

        return {
            "id": txn_id, "match_status": "posted", "matched_entity_type": new_entity_type,
            "matched_entity_id": result["id"], "journal_entry_id": journal_id,
            "allocations_count": len(allocations), new_entity_type: result,
        }

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
