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

from core.db_paging import fetch_all

from services.phase2_journal_service import phase2_journal_service
from services.period_validation_service import period_validation_service
from services.timeline_service import timeline_service
from domain.banking import posting_map as pmap
from domain.banking.charge_gst import split_inclusive_charge, build_inclusive_lines
from domain.banking.rules import match_rule
from domain.banking.splits import build_split_lines, SplitError
from services.bank_split_service import bank_split_service
from services.bank_transfer_service import bank_transfer_service

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
            except Exception as e:
                # Was a fully silent `except: pass` — the caller falls through to
                # the firm's GENERIC master Bank account below, which posts and
                # balances fine but potentially to the WRONG bank sub-ledger,
                # corrupting that specific account's balance/reconciliation with
                # no trace of why (task #244 comparative-reliability finding).
                from core.observability import capture_posting_failure
                capture_posting_failure(
                    e, operation="bank_posting._resolve_bank",
                    firm_id=firm_id, client_id=client_id, statement_id=stmt_id,
                )
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
        # The account the CA already chose, when the caller did not name one in
        # this request. It was written by banking_service.set_account, which
        # scope-checks it — so it is at least as trustworthy as the id in the
        # request body, and it is what the screen SHOWS on the row.
        #
        # Without this fallback, coding a line to an account and then pressing
        # Add failed with "Select a GL account", because only the post request's
        # own account_id was consulted. That was reachable today through "Use the
        # rule" and "Use last time's", both of which set the account through
        # set_account and leave the post body empty.
        chosen = account_id or txn.get("account_id")
        if cat in pmap.EXPLICIT_COUNTER:
            if not chosen:
                raise HTTPException(status_code=422,
                                    detail=f"Select a GL account for '{cat}' before posting.")
            return self._validate_account(db, firm_id, chosen)
        if not cat and chosen:               # legacy account-mapping post (no category)
            return self._validate_account(db, firm_id, chosen)
        raise HTTPException(status_code=422,
                            detail="Categorize the transaction (or map an account) before posting.")

    def _gst_input_account(self, db, firm_id, client_id, head: str) -> str:
        """The GST Input Credit account for one tax head.

        The seeded chart carries three (CGST / SGST / IGST, migration 011) and
        migration 092 stamps system_account_key='gst_input' on ALL THREE, so the
        key alone cannot tell them apart — the head has to come from the name.
        The GST return nets all three into one ITC figure either way
        (gst_return_service), so keeping the heads separate in the ledger costs
        nothing and preserves the detail GSTR-3B table 4 wants.
        """
        rows = (db.table("chart_of_accounts").select("id, account_name")
                .eq("firm_id", firm_id)
                .or_(f"client_id.eq.{client_id},client_id.is.null")
                .ilike("account_name", f"%GST Input%{head}%")
                .eq("is_active", True).limit(1).execute().data or [])
        if not rows:
            raise HTTPException(
                status_code=422,
                detail=(f"No active 'GST Input Credit - {head}' account in this client's chart. "
                        "Add one, or post the charge without a GST split."))
        return rows[0]["id"]

    @staticmethod
    def _gst_output_account(db, firm_id, client_id, head: str) -> str:
        """The GST Output (payable) account for one tax head.

        Unlike the input side, migration 098 keys these PER HEAD — 'gst_cgst',
        'gst_sgst', 'gst_igst', and only on Liability accounts, deliberately so
        that an output head can never resolve to a GST Input asset. So the key
        alone identifies the account and the name is only a fallback.

        Resolved through phase2_journal_service._find_account, the same call the
        sales side makes, rather than a second lookup of our own: a receipt
        recorded from the bank and the same receipt recorded from an invoice
        must land on the SAME liability, or GSTR-3B reports two different
        worlds. gst_return_service reads output tax as the net credit on exactly
        these three keys.
        """
        try:
            return phase2_journal_service._find_account(
                db, firm_id, client_id, "%GST Output%", system_key=f"gst_{head.lower()}")
        except Exception:
            raise HTTPException(
                status_code=422,
                detail=(f"No active 'GST Output - {head}' account in this client's chart. "
                        "Add one, or record this receipt without a GST split."))

    def _charge_lines(self, db, firm_id, txn, amount, bank_id, counter_id,
                      gst_rate_bps: int, is_interstate: bool,
                      is_credit: bool = False) -> list[dict]:
        """A tax-inclusive amount that crossed the bank, with its GST separated.

        The figure on the statement is tax-INCLUSIVE either way, so the taxable
        value is backed out of it rather than computed on it — see
        domain/banking/charge_gst for why that distinction matters and why the
        split is exact.

        DIRECTION DECIDES THE TAX ACCOUNTS, not the arithmetic. Money out is an
        inward supply: the tax is input credit (CGST Act s.16) and debits the
        GST Input asset. Money in is an outward supply: the tax is output tax
        (CGST Act s.9) and credits the GST Output liability. Using one set for
        both would claim ITC on a sale, so the two lookups are separate even
        though the split above them is the same call.
        """
        client_id = txn["client_id"]
        try:
            split = split_inclusive_charge(amount, gst_rate_bps, is_interstate)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        find = ((lambda h: self._gst_output_account(db, firm_id, client_id, h))
                if is_credit
                else (lambda h: self._gst_input_account(db, firm_id, client_id, h)))

        cgst_id = sgst_id = igst_id = None
        if split.has_gst:
            if is_interstate:
                igst_id = find("IGST")
            else:
                cgst_id = find("CGST")
                sgst_id = find("SGST")
        try:
            return build_inclusive_lines(
                split, bank_account_id=bank_id, counter_account_id=counter_id,
                is_credit=is_credit, cgst_account_id=cgst_id,
                sgst_account_id=sgst_id, igst_account_id=igst_id)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @staticmethod
    def _settles_a_document(txn: dict) -> bool:
        """True when posting this transaction will also settle an invoice/bill.

        The same condition _settle uses, kept in one place so the split guard and
        the settlement cannot drift apart. The rule itself lives in posting_map
        because the review queue has to ask it too, to decide whether to offer a
        GST rate at all.
        """
        return pmap.settles_document(txn.get("category"), txn.get("matched_entity_type"),
                                     txn.get("matched_entity_id"))

    def _plan(self, db, firm_id, txn, bank_account_id, account_id, to_bank_account_id,
              gst_rate_bps: Optional[int] = None, is_interstate: bool = False):
        """Resolve accounts and build balanced lines. Returns (entry_type, lines, bank_id).

        `gst_rate_bps` is None for the ordinary two-line post. Supplying it splits
        the tax-inclusive charge into taxable value + input GST. It is passed by
        the caller (ultimately a CA confirming the posting drawer), never inferred
        — see charge_gst's PLACE OF SUPPLY note.
        """
        amount, is_credit = _amount(txn)
        if amount <= 0:
            raise HTTPException(status_code=422, detail="Transaction has zero amount.")
        cat = txn.get("category")
        bank_id = self._resolve_bank(db, firm_id, txn, bank_account_id)

        # Tier 1.2: a transaction the CA has split across several GL accounts
        # posts as an n-leg journal. Checked BEFORE anything else builds lines —
        # falling through to the two-leg builder would silently code the whole
        # amount to one account and throw the split away, which is the bug this
        # feature exists to prevent.
        splits = bank_split_service.splits_for_posting(db, firm_id, txn["id"], amount)
        if splits:
            if cat == pmap.TRANSFER:
                raise HTTPException(
                    status_code=422,
                    detail="A transfer moves money between two accounts — it cannot be split.")
            if gst_rate_bps is not None:
                # Both want to decide the non-bank legs. Doing them together
                # needs a rate PER split, which is a bigger design than 1.2 —
                # refuse clearly rather than silently applying one and dropping
                # the other.
                raise HTTPException(
                    status_code=422,
                    detail=("A GST split and a multi-account split cannot be combined yet. "
                            "Post the GST separately, or split without a GST rate."))
            if self._settles_a_document(txn):
                # The journal would credit the split accounts instead of Trade
                # Receivables/Payables, but settle_on_post would still mark the
                # invoice paid — leaving the control account and the sub-ledger
                # describing different worlds, with nothing to say which is right.
                raise HTTPException(
                    status_code=422,
                    detail=("This transaction is matched to an invoice or bill, so it settles "
                            "that document in full. Unmatch it before splitting it across "
                            "accounts."))
            try:
                lines = build_split_lines(splits, is_credit=is_credit,
                                          bank_account_id=bank_id, amount_paise=amount)
            except SplitError as e:
                raise HTTPException(status_code=422, detail=str(e))
            return pmap.entry_type_for(cat, is_credit), lines, bank_id

        if cat == pmap.TRANSFER:
            if gst_rate_bps is not None:
                raise HTTPException(status_code=422,
                                    detail="A transfer between own accounts is not a supply — no GST split.")
            # Tier 1.5 — THE double-count guard. build_transfer_lines writes the
            # COMPLETE double entry (Dr destination, Cr source), so a paired
            # transfer must produce exactly ONE journal. The counterpart is the
            # same cash seen from the other statement; letting it post its own
            # entry is precisely the overstatement transfer detection exists to
            # prevent, just arrived at more tidily.
            if txn.get("transfer_pair_id") and txn.get("transfer_is_primary") is False:
                raise HTTPException(
                    status_code=422,
                    detail=("This is the receiving side of a transfer that is already posted "
                            "from the paying account. Posting it again would count the same "
                            "money twice."))
            if not to_bank_account_id and txn.get("transfer_pair_id"):
                # The CA already identified the destination by confirming the
                # pair; making them pick it again invites a different answer.
                to_bank_account_id = bank_transfer_service.counterpart_bank_account(
                    db, firm_id, txn)
            if not to_bank_account_id:
                # Account-first coding: picking the OTHER bank or cash ledger is
                # what made this a Transfer in the first place, so that ledger is
                # the destination. This is how a transfer with no counterpart
                # line — cash withdrawn at a branch, a sweep the other statement
                # has not arrived for — becomes postable at all. The paired case
                # above still wins, because a confirmed pair is a stronger
                # statement than a picked account.
                to_bank_account_id = txn.get("account_id")
            if not to_bank_account_id:
                raise HTTPException(status_code=422, detail="Transfer requires a destination bank/cash account.")
            to_id = self._validate_account(db, firm_id, to_bank_account_id)
            lines = pmap.build_transfer_lines(amount, is_credit, bank_id, to_id)
        else:
            counter_id = self._resolve_counter(db, firm_id, txn, account_id)
            # A GST split works in BOTH directions — out is input credit, in is
            # output tax — but only against an explicitly chosen ledger.
            #
            # It is refused on the control-account categories (Customer Payment
            # → Trade Receivables, Vendor Payment → Trade Payables, GST Payment)
            # because that would put tax on a balance-sheet control account. And
            # it is refused on a row that SETTLES a document, because the
            # invoice or bill already carries its own GST: taxing the bank line
            # too counts the same tax twice, once in the document's journal and
            # once here. Both refuse rather than silently ignoring — a caller
            # that asked for a split and got a gross post would never find out.
            if gst_rate_bps is not None:
                settles = self._settles_a_document(txn)
                if not pmap.gst_split_allowed(cat, settles_document=settles):
                    raise HTTPException(
                        status_code=422,
                        detail=("This transaction settles an invoice or bill, which already "
                                "carries its own GST. Adding a rate here would count that tax "
                                "twice. Unmatch it first if the GST belongs on the bank line.")
                        if settles else
                        ("A GST split needs an explicitly chosen ledger — it cannot go on "
                         "a control account like Trade Receivables or Trade Payables."))
                lines = self._charge_lines(db, firm_id, txn, amount, bank_id, counter_id,
                                           gst_rate_bps, is_interstate, is_credit=is_credit)
            else:
                lines = pmap.build_lines(amount, is_credit, bank_id, counter_id)
        return pmap.entry_type_for(cat, is_credit), lines, bank_id

    # ── B.3 review preview (no writes) ───────────────────────────────────────
    def preview(self, db, firm_id, txn_id, bank_account_id=None, account_id=None,
                to_bank_account_id=None, gst_rate_bps=None, is_interstate=False) -> dict:
        txn = self._get_txn(db, firm_id, txn_id)
        if txn.get("posted_journal_id"):
            raise HTTPException(status_code=409, detail="Transaction already posted.")
        entry_type, lines, _ = self._plan(db, firm_id, txn, bank_account_id, account_id,
                                          to_bank_account_id, gst_rate_bps, is_interstate)
        amount, _ = _amount(txn)
        out = {
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
        if gst_rate_bps is not None:
            # Show the CA the arithmetic, not just the resulting lines: the whole
            # point of an inclusive split is that ₹590 becomes ₹500 + ₹90, and a
            # figure they cannot check is a figure they cannot certify.
            split = split_inclusive_charge(amount, int(gst_rate_bps), bool(is_interstate))
            out["gst"] = {
                "rate_bps": split.rate_bps, "is_interstate": split.is_interstate,
                "gross_paise": split.gross_paise, "taxable_paise": split.taxable_paise,
                "cgst_paise": split.cgst_paise, "sgst_paise": split.sgst_paise,
                "igst_paise": split.igst_paise, "tax_paise": split.tax_paise,
            }
        return out

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

    # ── B.3.2 post — categorise and post in ONE action ────────────────────────
    def post(self, db, firm_id, txn_id, bank_account_id=None, account_id=None,
             to_bank_account_id=None, actor_id=None, gst_rate_bps=None,
             is_interstate=False, actor_auth_id=None) -> dict:
        """Post the bank transaction to the ledger and settle its document.

        actor_id MUST be the internal public.users.id — it becomes
        journal_entries.created_by, which FKs to users(id), NOT the Supabase
        auth id. actor_auth_id is the Supabase auth id and is used only for
        audit_log attribution, where every other router writes the auth id;
        it defaults to actor_id when the caller has nothing better.

        WHY THIS NO LONGER CREATES A DRAFT
            It used to write an unposted journal that a Partner had to approve
            before anything reached the books. For a firm with 50 clients at
            ~300 statement lines a month that is 15,000 approvals — which nobody
            performs, so what actually happens is rubber-stamping, and a
            rubber-stamped queue is worse than none: it manufactures a record of
            a review that did not happen.

            Bank categorisation is also the wrong work to gate. It is mechanical,
            it is reversible (a correction is an ordinary append-only reversal,
            and the transaction can be unmatched and re-posted), and the person
            hired to do it is the person doing it. Manual journals still route
            through the draft/approve path in journal_posting_service, because
            those are judgement rather than clerical — that distinction is the
            reason `banking` has its own RBAC resource.

        Idempotent: one journal per transaction, guarded on posted_journal_id."""
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
            db, firm_id, txn, bank_account_id, account_id, to_bank_account_id,
            gst_rate_bps, is_interstate)

        journal_entry_id = phase2_journal_service._create_journal(
            db, firm_id=firm_id, client_id=client_id, entry_date=entry_date,
            reference_no=f"BANK-{txn_id}",       # one journal per txn (dedup)
            narration=f"Bank: {txn.get('description', '')}".strip(),
            entry_type=entry_type, lines=lines,
            is_posted=True, source_type="bank_transaction", source_id=txn_id,
            created_by=actor_id,
        )

        # Mark the transaction posted and settle its invoice/bill in the same
        # action. settle_on_post carries the CAS guard that makes a double-click
        # safe, so it is reused here rather than reimplemented.
        settled = self.settle_on_post(db, firm_id, txn_id, journal_entry_id, actor_id=actor_id)

        try:
            from services.audit_service import log_event
            new_data = {"posted_journal_id": journal_entry_id, "category": txn.get("category")}
            if gst_rate_bps is not None:
                # Who decided this charge carried 18% IGST, and when. An input
                # credit claimed under s.16 has to be defensible years later.
                new_data["gst_rate_bps"] = int(gst_rate_bps)
                new_data["gst_is_interstate"] = bool(is_interstate)
            log_event(firm_id, "bank_transaction", txn_id, "status_change",
                      actor_id=actor_auth_id or actor_id, new_data=new_data,
                      metadata={"source": "bank_post", "stage": "posted"})
        except Exception:  # pragma: no cover - audit must never block
            pass
        # settle_on_post already writes the timeline entry for a posted
        # transaction, so there is no second one here.

        return {"id": txn_id, "status": "posted", "match_status": "posted",
                "posted_journal_id": journal_entry_id, "settled": settled}

    # ── Deferred settlement — runs only when the draft journal is posted ───────
    def settle_on_post(self, db, firm_id, txn_id, journal_id, actor_id=None) -> Optional[dict]:
        """Called by journal_posting_service.post_draft once the bank draft is on
        the books: mark the transaction posted and settle its invoice/bill. Idempotent.

        Concurrency guard: two near-simultaneous calls (e.g. a double-click on
        "approve draft") could both read match_status as not-yet-posted before
        either write lands, then both proceed to _settle -- double-allocating
        paid_paise and/or double-granting party credit on an overpayment. The
        claiming UPDATE below is CAS-guarded on the status this call actually
        read (same idiom as match_and_settle_multi's task #220 fix); a
        concurrent loser gets zero rows back and must not run _settle again."""
        txn = self._get_txn(db, firm_id, txn_id)
        prior_status = txn.get("match_status")
        if prior_status == "posted":
            return None                                   # already settled (idempotent)
        claim = db.table("bank_transactions").update({
            "match_status": "posted", "posted_at": _now(), "posted_by": actor_id,
            "posted_journal_id": journal_id, "updated_at": _now(),
        }).eq("id", txn_id).eq("firm_id", firm_id).eq("match_status", prior_status).execute()
        if not claim.data:
            return None                                   # lost the race to a concurrent caller

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

    # ── Undo a posted transaction ────────────────────────────────────────────

    def undo(self, db, firm_id: str, txn_id: str, actor_id: Optional[str] = None,
             actor_auth_id: Optional[str] = None) -> dict:
        """Put a POSTED bank transaction back in the queue.

        WHAT WAS WRONG
            The screen has shown an "Undo" button on every posted row since the
            queue was built, wired to bank_matching_service.unmatch — which
            begins by REFUSING a posted transaction. Every click was a 409. It
            survived because the route has a mock-mode early return that claims
            success without touching anything, so the whole suite exercised a
            no-op.

        WHY THIS IS NOT unmatch
            Posting did three things, and all three have to come back:
              1. a balanced journal on the books,
              2. paid_paise and a status on the invoice or bill it settled,
              3. possibly a party credit, when it settled MORE than was owed.

        APPEND-ONLY, ALWAYS
            The journal is REVERSED through phase2_journal_service.reverse_entry
            — the one reversal path — never deleted or edited. CLAUDE.md: a
            posted entry can never be hard-DELETEd, and a correction to a real
            transaction is an append-only reversal.

        THE REVERSAL DATE
            The ORIGINAL entry date while that period is still open, so the
            books read as if the mistake never happened — which is what "undo"
            means for a same-period correction. Today's date when the original
            period is locked, because a reversal must never reopen a filed or
            locked year. The CA chose this rule; period_validation_service is
            what decides which case applies.

        WHAT IT REFUSES
            A multi-invoice settlement. That path (match_and_settle_multi)
            creates a whole receipt document with its own allocations through
            receipt_service, and undoing it is cancelling that receipt — a
            different operation with a different audit trail. Refusing is the
            honest answer; half-undoing it would leave a receipt pointing at
            allocations that no longer exist.
        """
        txn = self._get_txn(db, firm_id, txn_id)
        journal_id = txn.get("posted_journal_id")
        if txn.get("match_status") != "posted" or not journal_id:
            raise HTTPException(status_code=409,
                                detail="This transaction is not posted, so there is nothing to undo.")
        client_id = txn["client_id"]

        # A multi-invoice settlement is a receipt, not a bank journal. Told apart
        # by the journal's own source_type: match_and_settle_multi books through
        # receipt_service, so the entry it leaves behind is not ours to reverse.
        je = (db.table("journal_entries").select("id, source_type, entry_date, reversal_of")
              .eq("id", journal_id).eq("firm_id", firm_id).limit(1).execute().data or [None])[0]
        if je and je.get("source_type") not in (None, "bank_transaction"):
            raise HTTPException(
                status_code=422,
                detail=("This line was settled across several documents, which created a receipt. "
                        "Cancel that receipt to undo it — undoing only the bank line would leave "
                        "the receipt's allocations pointing at nothing."))

        # The original date while its period is open; today otherwise. Asking
        # period_validation_service rather than reading a lock flag ourselves
        # keeps ONE definition of "open" — it is fail-closed, so an unverifiable
        # lock sends the reversal to today rather than into a possibly-locked year.
        original_date = str((je or {}).get("entry_date") or txn["transaction_date"])[:10]
        reversal_date = original_date
        try:
            period_validation_service.validate_posting_date(firm_id or "", original_date)
        except HTTPException:
            reversal_date = _now()[:10]
            # Today has to be postable too, or there is nowhere to put the
            # reversal — and that is a real answer, not something to paper over.
            period_validation_service.validate_posting_date(firm_id or "", reversal_date)

        reversal_id = phase2_journal_service.reverse_entry(
            db, firm_id, journal_id, reversal_date,
            narration=f"Undo of bank transaction {txn_id}", created_by=actor_id)

        # 2 and 3, in that order: the credit was granted out of the settlement's
        # excess, so it is unwound before the settlement that produced it.
        revoked = self._revoke_overpayment_credit(db, firm_id, client_id, txn_id, actor_id)
        unsettled = self._unsettle(db, firm_id, txn)

        # Back to "matched" rather than "unmatched" when a document is still
        # linked: the CA's identification of WHICH invoice this is was not the
        # mistake, and making them find it again is a second job they did not ask
        # for. Undo takes back the posting, not the matching.
        back_to = "matched" if txn.get("matched_entity_id") else "unmatched"
        db.table("bank_transactions").update({
            "match_status": back_to, "posted_at": None, "posted_by": None,
            "posted_journal_id": None, "updated_at": _now(),
        }).eq("id", txn_id).eq("firm_id", firm_id).eq("match_status", "posted").execute()

        try:
            from services.audit_service import log_event
            log_event(firm_id, "bank_transaction", txn_id, "status_change",
                      actor_id=actor_auth_id or actor_id,
                      old_data={"match_status": "posted", "posted_journal_id": journal_id},
                      new_data={"match_status": back_to, "reversal_journal_id": reversal_id},
                      metadata={"source": "bank_undo", "reversal_date": reversal_date})
        except Exception:  # pragma: no cover - audit must never block
            pass
        try:
            timeline_service.log(client_id, "accounting", "Bank Transaction Undone",
                                 f"Posting reversed ({reversal_date}); back in the queue", "warning",
                                 firm_id=firm_id, entity_type="bank_transaction",
                                 entity_id=txn_id, actor_id=actor_id)
        except Exception:  # pragma: no cover
            pass

        return {"id": txn_id, "match_status": back_to, "reversal_journal_id": reversal_id,
                "reversal_date": reversal_date, "unsettled": unsettled,
                "credit_revoked": revoked}

    @staticmethod
    def _revoke_overpayment_credit(db, firm_id, client_id, txn_id, actor_id) -> Optional[dict]:
        """Take back whatever credit THIS transaction's overpayment granted.

        Found by source rather than recomputed: the excess depended on what was
        outstanding at the moment of posting, and re-deriving it now — after
        other payments may have landed — would revoke the wrong figure.

        Netted by outstanding_for_source, because post → undo → post → undo is
        an ordinary correction loop and each posting grants against the same
        transaction id. Taking the raw grant rows made the second undo try to
        revoke the first round's credit again.
        """
        from services.party_credit_service import party_credit_service
        grants = party_credit_service.outstanding_for_source(
            db, firm_id, client_id, "bank_overpayment", txn_id)
        if not grants:
            return None
        out = []
        for g in grants:
            out.append(party_credit_service.revoke_credit(
                db, firm_id, client_id, g["party_type"], g["party_id"],
                int(g["amount_paise"]), source_type="bank_overpayment", source_id=txn_id,
                created_by=actor_id, notes=f"Undo of bank transaction {txn_id}"))
        return {"revocations": len(out), "paise": sum(int(g["amount_paise"]) for g in grants)}

    def _unsettle(self, db, firm_id, txn) -> Optional[dict]:
        """Give the invoice or bill back what this transaction paid off.

        The allocation is NOT stored per transaction, so it is recovered as
        `min(this line's amount, what the document currently shows as paid)`.
        The clamp is the point: if part of that payment has already been
        unwound, or another correction reduced paid_paise, subtracting the full
        amount would drive it negative and make the document look overdue for
        money nobody owes.
        """
        cat, mt, mid = txn.get("category"), txn.get("matched_entity_type"), txn.get("matched_entity_id")
        client_id = txn.get("client_id")
        if not pmap.settles_document(cat, mt, mid):
            return None
        if mt == "sales_invoice":
            table, label_col = "client_sales_invoices", "invoice_no"
            extra, outstanding_fn = "total_paise, debit_note_paise, credited_paise", self._invoice_outstanding
        else:
            table, label_col = "purchase_bills", "bill_no"
            extra = "total_paise, net_payable_paise, credit_note_paise, debited_paise"
            outstanding_fn = self._bill_outstanding

        rows = (db.table(table).select(f"id, {label_col}, paid_paise, status, {extra}")
                .eq("id", mid).eq("firm_id", firm_id).eq("client_id", client_id)
                .limit(1).execute().data) or []
        if not rows:
            return None
        doc = rows[0]
        paid = int(doc.get("paid_paise") or 0)
        amount, _ = _amount(txn)
        give_back = min(int(amount), paid)
        if give_back <= 0:
            return {"entity": table, "label": doc.get(label_col), "reversed_paise": 0,
                    "status": doc.get("status"), "note": "nothing was allocated to this document"}
        new_paid = paid - give_back
        # Recomputed from the document's own figures, never assumed to be
        # "unpaid": a partly-paid invoice that this line topped up must go back
        # to partially_paid, not to a state saying nobody has paid anything.
        probe = dict(doc); probe["paid_paise"] = new_paid
        status = "unpaid" if new_paid <= 0 else (
            "paid" if outstanding_fn(probe) <= 0 else "partially_paid")
        db.table(table).update({"paid_paise": new_paid, "status": status, "updated_at": _now()}) \
            .eq("id", mid).eq("firm_id", firm_id).eq("client_id", client_id).execute()
        return {"entity": table, "label": doc.get(label_col), "reversed_paise": give_back,
                "new_paid_paise": new_paid, "status": status}

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
            "matched_by": (actor or {}).get("id"), "matched_at": _now(),
            "match_status": "posted", "posted_at": _now(), "posted_by": (actor or {}).get("id"),
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
    def _all_txns(self, db, firm_id, client_id: Optional[str], *, label: str) -> list[dict]:
        """Every transaction for the scope, PAGED, sorted by date here.

        The three queues below each read the whole set and filter in Python, so
        an unpaged read did not make them slow — it made them WRONG. Past
        PostgREST's ~1000-row cap the rows simply were not there to filter, so
        "Ready to Post" quietly stopped listing work that was ready, and nothing
        distinguished that from having none.
        """
        def _page():
            q = db.table("bank_transactions").select("*").eq("firm_id", firm_id)
            return q.eq("client_id", client_id) if client_id else q
        rows = fetch_all(_page, label=label)
        rows.sort(key=lambda t: (str(t.get("transaction_date") or ""), str(t.get("id"))))
        return rows

    def ready_to_post(self, db, firm_id, client_id: Optional[str]) -> list[dict]:
        rows = self._all_txns(db, firm_id, client_id, label="posting.ready_to_post")
        out = [t for t in rows
               if t.get("category") and not t.get("posted_journal_id")
               and t.get("match_status") not in ("posted", "ignored")
               # Tier 1.5: the receiving side of a paired transfer is the same
               # cash as the paying side and never posts on its own. Offering it
               # here would invite exactly the double-count the pairing prevents.
               and t.get("transfer_is_primary") is not False]
        self._annotate_rule_suggestions(db, firm_id, out)
        return out

    def _annotate_rule_suggestions(self, db, firm_id, txns: list[dict]) -> None:
        """Prefill hints for the posting drawer, from the client's own rules.

        The categorize queue has read rules since B.2.3, but this queue — the one
        that actually feeds the posting drawer — never did, so a rule that knew
        "HDFC charges go to Bank Charges at 18%" still made the CA re-enter both
        on every single charge. Suggestions only: the drawer prefills them and
        the person clicking Post is the one asserting them.
        """
        if not txns:
            return
        try:
            rules = (db.table("bank_matching_rules").select("*")
                     .eq("firm_id", firm_id).eq("is_active", True)
                     .order("created_at").execute().data or [])
        except Exception:  # pragma: no cover - a hint must never break the queue
            return
        by_client: dict = {}
        for r in rules:
            by_client.setdefault(r.get("client_id"), []).append(r)
        for t in txns:
            # Only the transaction's OWN client's rules — same scoping as
            # bank_matching_service.queue, for the same reason.
            client_rules = by_client.get(t.get("client_id"), [])
            amount, is_credit = _amount(t)
            hit = match_rule(t.get("description"), amount, not is_credit, client_rules)
            t["suggested_account_id"] = (hit.account_id if hit else None) if not t.get("account_id") else None
            # Offered in BOTH directions. Out is input credit (CGST Act s.16),
            # in is output tax (s.9) — the posting engine picks the accounts
            # from the direction, so the rule only has to state the rate.
            t["suggested_gst_rate_bps"] = (hit.gst_rate_bps if hit else None)
            t["suggested_is_interstate"] = bool(hit.is_interstate) if hit else False

    def pending(self, db, firm_id, client_id: Optional[str]) -> list[dict]:
        """Draft journal created, awaiting approval (linked journal but not yet posted)."""
        rows = self._all_txns(db, firm_id, client_id, label="posting.pending")
        return [t for t in rows
                if t.get("posted_journal_id") and not t.get("posted_at")
                and t.get("match_status") != "posted"]

    def posted(self, db, firm_id, client_id: Optional[str]) -> list[dict]:
        """Truly posted — the draft was approved (posted_at set)."""
        rows = self._all_txns(db, firm_id, client_id, label="posting.posted")
        rows.reverse()  # newest first, as before
        return [t for t in rows if t.get("posted_at")]


bank_posting_service = BankPostingService()
