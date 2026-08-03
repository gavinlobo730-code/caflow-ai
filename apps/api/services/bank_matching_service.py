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
    Candidate, rank_suggestions, match_rule, is_valid_category, CATEGORIES,
    NEAR_MATCH_BAND_BPS, parse_narration, describe_narration,
)
from services.timeline_service import timeline_service

_logger = logging.getLogger("caflow.bank_matching")

# Cap on rows pulled per candidate type. The amount band (below) is wider than
# the old equality filter, so this bounds the worst case; the ranker keeps only
# `max_results` anyway.
_CANDIDATE_FETCH_LIMIT = 50


def _near_match_ceiling(amount_paise: int) -> int:
    """Largest document amount a bank line of `amount_paise` may be offered
    against. Mirrors matcher.near_match_floor_paise from the other side: a line
    short by up to NEAR_MATCH_BAND_BPS of the DOCUMENT is in band, so the ceiling
    is amount / (1 - band). Integer paise, computed in basis points."""
    amount = int(amount_paise)
    if amount <= 0:
        return 0
    # ceil division keeps the boundary document inside the band.
    return -(-amount * 10000 // (10000 - NEAR_MATCH_BAND_BPS))

_MATCH_ENTITY_TYPES = frozenset({
    "sales_invoice", "purchase_bill", "receipt", "purchase_payment", "journal_entry", "manual",
})

# Backing table for each matchable entity type, used to verify the caller's
# firm/client actually owns the entity_id before linking it to a bank
# transaction (a "manual" match has no backing document, so it's unchecked).
_MATCH_ENTITY_TABLES = {
    "sales_invoice": "client_sales_invoices",
    "purchase_bill": "purchase_bills",
    "receipt": "receipts",
    "purchase_payment": "purchase_payments",
    "journal_entry": "journal_entries",
}

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
                # >0 when the bank line is SHORT of the document (TDS withheld,
                # bank charges). The UI must show this rather than let a partial
                # settlement look like a full one.
                "difference_paise": s.difference_paise,
                "tds_rate_bps": s.tds_rate_bps,
                "party_id": s.party_id,
                "outstanding_paise": s.outstanding_paise,
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
        #
        # Amount band, not equality: the bank line may be SHORT of the invoice
        # (customer withheld TDS, or the bank took charges). rank_suggestions
        # scores those below exact matches and labels the shortfall; fetching
        # only exact-amount rows here would leave it nothing to score. Upper
        # bound only — a receipt LARGER than the invoice isn't settling it.
        rows = (db.table("client_sales_invoices")
                .select("id, invoice_no, invoice_date, total_paise, paid_paise, customer_id, status")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .is_("deleted_at", "null")
                .gte("total_paise", amount)
                .lte("total_paise", _near_match_ceiling(amount))
                .limit(_CANDIDATE_FETCH_LIMIT).execute().data or [])
        customers = self._party_names(db, "customers", firm_id, client_id)
        out = []
        for r in rows:
            # A draft invoice was never issued — no AR journal exists for a bank
            # transaction to settle against (task #222: same pattern as the
            # outstanding-balance functions excluding draft/cancelled).
            if str(r.get("status")) in ("cancelled", "draft"):
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
                party_name=party, party_id=r.get("customer_id"),
                outstanding_paise=total - paid,
            ))
        return out

    def _bill_candidates(self, db, firm_id, client_id, amount) -> list[Candidate]:
        # Match on net_payable_paise, not total_paise: the money that actually
        # leaves the bank for a vendor equals the bill's NET payable (total minus
        # any TDS withheld / debit-note / credit-note adjustment) — which is also
        # exactly what settlement relieves. Gating on total_paise meant any bill
        # with TDS never surfaced as a candidate for its own outgoing payment.
        # deleted_at filter: a soft-deleted bill is not a live payable.
        # Amount band rather than equality — same reasoning as
        # _invoice_candidates: a payment can fall short of the payable (bank
        # charges on a remittance, a small withheld amount). rank_suggestions
        # ranks and labels the difference.
        rows = (db.table("purchase_bills")
                .select("id, bill_no, bill_date, total_paise, net_payable_paise, vendor_id, status")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .is_("deleted_at", "null")
                .gte("net_payable_paise", amount)
                .lte("net_payable_paise", _near_match_ceiling(amount))
                .limit(_CANDIDATE_FETCH_LIMIT).execute().data or [])
        vendors = self._party_names(db, "vendors", firm_id, client_id)
        out = []
        for r in rows:
            # A draft bill was never received — no AP journal exists for a bank
            # transaction to settle against (task #222: same pattern as the
            # outstanding-balance functions excluding draft/cancelled).
            if str(r.get("status")) in ("cancelled", "paid", "draft"):
                continue
            party = vendors.get(r.get("vendor_id"))
            # Present the payable (what's owed), not the gross bill total.
            net_payable = int(r.get("net_payable_paise") or r.get("total_paise") or 0)
            out.append(Candidate(
                entity_type="purchase_bill", entity_id=r["id"],
                label=f"{r.get('bill_no', '')} · {party or 'Vendor'}",
                amount_paise=net_payable, entity_date=str(r.get("bill_date") or "")[:10],
                party_name=party, party_id=r.get("vendor_id"),
                outstanding_paise=net_payable,
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
    # "ignored" is a first-class view, not a hole: a row can only leave the queue
    # by being posted or ignored, and an ignored row that nobody can see again is
    # a statement line silently dropped from the books.
    _QUEUE_STATUSES = frozenset({"unmatched", "categorized", "matched", "needs_review", "ignored", "all"})

    def queue(self, db, firm_id: str, client_id: Optional[str], status: str = "unmatched") -> list[dict]:
        if status not in self._QUEUE_STATUSES:
            raise HTTPException(status_code=422, detail="Invalid queue status.")
        q = db.table("bank_transactions").select("*").eq("firm_id", firm_id)
        if client_id:
            q = q.eq("client_id", client_id)
        txns = q.order("transaction_date").execute().data or []

        # View filter (Python-side — avoids NULL-filter quirks; bounded per client).
        def keep(t: dict) -> bool:
            # An ignored row is out of the working views by definition — it only
            # shows in its own view and in "all". Without this, an ignored row
            # that still carried a category or a link reappeared under
            # "Categorized"/"Matched" as if it were live work.
            if status not in ("ignored", "all") and t.get("match_status") == "ignored":
                return False
            if status == "unmatched":
                return t.get("match_status") == "unmatched" and not t.get("matched_entity_id")
            if status == "categorized":
                return bool(t.get("category"))
            if status == "matched":
                return bool(t.get("matched_entity_id"))
            if status == "needs_review":
                return bool(t.get("needs_review"))
            if status == "ignored":
                return t.get("match_status") == "ignored"
            return True  # all
        txns = [t for t in txns if keep(t)]

        # Matching rules are always created per-client (MatchingRuleIn.client_id
        # is required) -- group by client_id and only apply a transaction's
        # OWN client's rules to it. Previously this fetched every rule for the
        # firm and applied all of them to every transaction regardless of
        # which client it belonged to, so one client's configured rule (e.g.
        # a narration-contains match on that client's own vendor name) could
        # surface as a suggested category on an unrelated client's transaction.
        #
        # Ordered by created_at so precedence is deterministic: match_rule takes
        # the FIRST firing rule, and an unordered fetch made "first" depend on
        # whatever order Postgres happened to return.
        rules = (db.table("bank_matching_rules").select("*")
                 .eq("firm_id", firm_id).eq("is_active", True)
                 .order("created_at").execute().data or [])
        rules_by_client: dict = {}
        for r in rules:
            rules_by_client.setdefault(r.get("client_id"), []).append(r)

        # Tier 1.3/1.4 — the payee and what was done with it before. Both are
        # built ONCE for the whole queue rather than per row: a hundred
        # transactions must not mean a hundred round trips. A posted row on
        # screen still teaches the unposted ones beside it; only a transaction's
        # OWN row is kept out of its evidence (suggest_for).
        from services.bank_payee_service import bank_payee_service
        history_clients = {t.get("client_id") for t in txns if t.get("client_id")}
        history_by_client: dict = {}
        parties_by_client: dict = {}
        for cid in history_clients:
            history_by_client[cid] = bank_payee_service.history_index(db, firm_id, cid)
            parties_by_client[cid] = bank_payee_service.parties(db, firm_id, cid)

        for t in txns:
            amount, is_credit = _txn_amount(t)
            client_rules = rules_by_client.get(t.get("client_id"), [])
            hit = match_rule(t.get("description"), amount, not is_credit, client_rules)
            # An existing category always wins over a rule's suggestion — the
            # rule proposes, the CA disposes.
            t["suggested_category"] = t.get("category") or (hit.category if hit else None)
            # The counter GL account and narration a rule proposes. Previously
            # these two columns were stored and read by nothing, so a rule could
            # only ever say "Expense", never "code it to Bank Charges".
            t["suggested_account_id"] = (hit.account_id if hit else None) if not t.get("account_id") else None
            t["suggested_narration"] = hit.narration if hit else None
            t["suggested_by_rule"] = hit.rule_name if hit else None
            # The GST treatment of a bank charge (migration 254). Prefills the
            # posting drawer; the CA still confirms it before anything is booked.
            # Only offered on a DEBIT — money arriving is not a charge, and a
            # rate on a receipt would book negative input credit.
            t["suggested_gst_rate_bps"] = (hit.gst_rate_bps if hit and not is_credit else None)
            t["suggested_is_interstate"] = bool(hit.is_interstate) if hit else False
            # What the bank already wrote down (channel, UTR, counterparty, VPA).
            # The raw narration stays untouched as the record of what arrived;
            # this is a parsed view alongside it, so the queue can show
            # "UPI · RAMESH KUMAR · UTR 412345678901" instead of a wall of
            # slashes. Pure regex over a string already in hand — no extra query.
            n = parse_narration(t.get("description"))
            t["parsed"] = {
                "channel": n.channel, "utr": n.utr, "vpa": n.vpa,
                "counterparty": n.counterparty, "ifsc": n.ifsc,
                "summary": describe_narration(n),
            }
            # Tier 1.3 — who this looks like it was with. Only proposed when the
            # CA has not already named one; a human's answer is never overwritten.
            cid = t.get("client_id")
            t["suggested_payee"] = bank_payee_service.suggest_payee(
                db, firm_id, cid, t, parties=parties_by_client.get(cid, []))
            # Tier 1.4 — what was done with this payee before, WITH the evidence.
            t["history"] = bank_payee_service.as_dict(
                bank_payee_service.suggest_for(t, history_by_client.get(cid, {})))
        return txns

    # ── B.2.2 — categorize (manual or accepting a rule suggestion) ───────────
    def categorize(self, db, firm_id: str, txn_id: str, category: str) -> dict:
        if not is_valid_category(category):
            raise HTTPException(status_code=422,
                                detail=f"Invalid category. Allowed: {', '.join(CATEGORIES)}")
        txn = self._get_txn(db, firm_id, txn_id)
        # task #228 audit finding: bank_posting_service.post() builds a DRAFT
        # journal from the category/match linkage AS THEY EXIST at that moment,
        # then leaves match_status alone until a human approves the draft
        # (settle_on_post re-reads category/matched_entity_* from the LIVE row at
        # approval time). Recategorizing while a draft is pending silently
        # changes what settle_on_post will act on without touching the
        # already-created journal — the two can now disagree about what was
        # posted. No "reject draft" flow exists yet to get out of this state
        # once a draft is created; that is a separate, pre-existing gap.
        if txn.get("posted_journal_id"):
            raise HTTPException(status_code=409,
                detail="A journal has already been created for this transaction — it cannot be recategorized until that draft is approved.")
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
        # task #228 audit finding: a DRAFT journal (posted_journal_id set,
        # match_status deliberately left alone until approval — see post()'s own
        # docstring) must block re-matching too, not just an already-posted
        # transaction — see categorize()'s identical guard for the full
        # rationale (settle_on_post re-reads this linkage at approval time).
        if txn.get("posted_journal_id"):
            raise HTTPException(status_code=409,
                detail="A journal has already been created for this transaction — it cannot be re-matched until that draft is approved.")
        # Tenant-ownership check: entity_id is caller-supplied and must actually
        # belong to this transaction's firm+client, not just be well-formed
        # (mirrors bank_posting_service.match_and_settle_multi's doc lookup).
        table = _MATCH_ENTITY_TABLES.get(entity_type)
        if table is not None:
            owned = (db.table(table).select("id").eq("id", entity_id)
                     .eq("firm_id", firm_id).eq("client_id", txn["client_id"])
                     .execute().data or [])
            if not owned:
                raise HTTPException(status_code=422, detail="Not part of this client's books.")
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
        # task #228 audit finding: same DRAFT-journal guard as categorize()/
        # match() — unmatching while a draft is pending clears
        # matched_entity_type/matched_entity_id out from under settle_on_post,
        # which will find nothing to settle when the draft is later approved
        # even though a real Dr/Cr journal already posted for that "settlement".
        if txn.get("posted_journal_id"):
            raise HTTPException(status_code=409,
                detail="A journal has already been created for this transaction — it cannot be unmatched until that draft is approved.")
        db.table("bank_transactions").update({
            "matched_entity_type": None, "matched_entity_id": None,
            "matched_by": None, "matched_at": None,
            "match_status": "unmatched", "updated_at": _now(),
        }).eq("id", txn_id).eq("firm_id", firm_id).execute()
        return {"id": txn_id, "match_status": "unmatched"}


bank_matching_service = BankMatchingService()
