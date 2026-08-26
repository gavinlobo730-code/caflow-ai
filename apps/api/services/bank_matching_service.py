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

from core.db_paging import fetch_all

from domain.banking import (
    Candidate, rank_suggestions, match_rule, is_valid_category, CATEGORIES,
    NEAR_MATCH_BAND_BPS, parse_narration, describe_narration,
)
from domain.banking import posting_map as pmap
from services.timeline_service import timeline_service

_logger = logging.getLogger("caflow.bank_matching")

# Cap on rows pulled per candidate type. The amount band (below) is wider than
# the old equality filter, so this bounds the worst case; the ranker keeps only
# `max_results` anyway.
_CANDIDATE_FETCH_LIMIT = 50
# Hard ceiling on a whole-page pool, however many bands it spans. This client
# has 5,655 open invoices; the amount band is the only thing keeping the read
# small, and an unbounded union would undo that.
_POOL_FETCH_CEILING = 1000


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
            "suggestions": [self._suggestion_dict(s) for s in ranked],
        }

    def suggestions_for_many(self, db, firm_id: str, client_id: str, txns: list[dict],
                             max_results: int = 5) -> dict[str, list[dict]]:
        """Ranked candidates for a whole PAGE, in one pass over each pool.

        Every row on a page searches the same pools. Doing it a row at a time
        meant five sequential Mumbai round trips each — sixty-five for a page
        of thirteen — and the reader watched the matches arrive one at a time
        over several seconds. Here each pool is read ONCE:

            credits present  → invoices + customer names + receipts   (3)
            debits present   → bills    + vendor names   + payments   (3)
            either           → journals                               (1)

        Seven round trips for a mixed page of any size, against 5 x N. Same
        candidates, same ranking — `_in_band` re-applies each row's own band to
        the shared pool, so no row is offered a document it would not have been
        offered on its own.
        """
        out: dict[str, list[dict]] = {}
        credits: list[tuple[dict, int]] = []
        debits: list[tuple[dict, int]] = []
        for t in txns:
            amount, is_credit = _txn_amount(t)
            if amount <= 0:
                out[str(t.get("id"))] = []
                continue
            (credits if is_credit else debits).append((t, amount))
        if not credits and not debits:
            return out

        try:
            # Shared by both directions, and unfiltered by amount either way.
            journals = self._fetch_journal_pool(db, firm_id, client_id)
        except Exception as e:  # pragma: no cover - best-effort, as per-row was
            _logger.warning("journal pool fetch failed for client %s: %s", client_id, e)
            journals = []

        for items, is_credit in ((credits, True), (debits, False)):
            if not items:
                continue
            amounts = [a for _t, a in items]
            bands = self._bands(amounts)
            try:
                if is_credit:
                    docs = self._fetch_invoice_pool(db, firm_id, client_id, bands)
                    parties = self._party_names(db, "customers", firm_id, client_id)
                    flat = self._fetch_receipt_pool(db, firm_id, client_id, amounts)
                else:
                    docs = self._fetch_bill_pool(db, firm_id, client_id, bands)
                    parties = self._party_names(db, "vendors", firm_id, client_id)
                    flat = self._fetch_payment_pool(db, firm_id, client_id, amounts)
            except Exception as e:  # pragma: no cover - matches _candidates'
                # Best-effort, exactly as the per-row path was: a pool that
                # cannot be read costs suggestions, never the queue itself.
                _logger.warning("candidate pool fetch failed for client %s: %s", client_id, e)
                docs, parties, flat = [], {}, []

            for t, amount in items:
                if is_credit:
                    cands = (self._invoices_from(docs, parties, amount)
                             + self._receipts_from(flat, amount))
                else:
                    cands = (self._bills_from(docs, parties, amount)
                             + self._payments_from(flat, amount))
                cands += self._journals_from(journals, amount)
                ranked = rank_suggestions(
                    amount, str(t.get("transaction_date"))[:10], t.get("description"),
                    cands, max_results=max_results)
                out[str(t.get("id"))] = [self._suggestion_dict(x) for x in ranked]
        return out

    # ── Candidate pools ──────────────────────────────────────────────────────
    # A page of statement lines all search the SAME pool. Fetching it once per
    # ROW meant 5 sequential Mumbai round trips per line and 65 for a page of
    # thirteen — the matches trickled in over seconds, one row lighting up at a
    # time. These helpers fetch each pool ONCE for the whole page, so the cost
    # is proportional to the number of POOLS, not the number of rows.

    @staticmethod
    def _bands(amounts) -> list[tuple[int, int]]:
        """The per-row amount bands, overlaps merged.

        Each row admits documents from its own amount up to
        _near_match_ceiling(amount) — it may be short by the near-match band
        (withheld TDS, bank charges). Merging overlaps keeps the OR filter
        below as few disjuncts as possible; a page of similar amounts usually
        collapses to one."""
        raw = sorted((int(a), _near_match_ceiling(int(a))) for a in amounts if int(a) > 0)
        merged: list[tuple[int, int]] = []
        for lo, hi in raw:
            if merged and lo <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
            else:
                merged.append((lo, hi))
        return merged

    @staticmethod
    def _in_band(value: int, amount: int) -> bool:
        """This row's OWN band, re-applied in memory. The pool is the union of
        every row's band, so without this a row would be offered a document
        that only some OTHER row could have matched."""
        return amount <= value <= _near_match_ceiling(amount)

    def _banded(self, q, col: str, bands: list[tuple[int, int]], label: str):
        """`col` within any of `bands`, as ONE query.

        One band is a plain gte/lte — byte-for-byte the query this used to make
        per row. Several become PostgREST's or(and(…),and(…)), which is the
        exact union of what the separate queries would have returned: no wider,
        so nothing irrelevant is pulled, and no narrower, so no row loses a
        candidate it would have been offered on its own."""
        if len(bands) == 1:
            lo, hi = bands[0]
            return q.gte(col, lo).lte(col, hi)
        return q.or_(",".join(f"and({col}.gte.{lo},{col}.lte.{hi})" for lo, hi in bands))

    @staticmethod
    def _pool_limit(bands) -> int:
        """Per-row this capped at 50. Scaling with the number of bands keeps a
        paged fetch no more truncated than the per-row fetches it replaces."""
        return min(_CANDIDATE_FETCH_LIMIT * max(len(bands), 1), _POOL_FETCH_CEILING)

    def _warn_if_truncated(self, rows, bands, label) -> None:
        if len(rows) >= self._pool_limit(bands):
            # Loud, because a truncated pool silently costs a row its match and
            # looks identical to "there was nothing to match".
            _logger.warning(
                "%s candidate pool hit its %d-row cap over %d band(s) — some rows "
                "may be offered fewer candidates than they should be",
                label, self._pool_limit(bands), len(bands))

    @staticmethod
    def _suggestion_dict(s) -> dict:
        return {
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

    def _fetch_invoice_pool(self, db, firm_id, client_id, bands) -> list[dict]:
        """Open sales invoices within any of `bands`. ONE query.

        deleted_at filter: a soft-deleted invoice is not a live receivable and
        must never be suggested as the counterparty for a bank credit.

        Amount band, not equality: the bank line may be SHORT of the invoice
        (customer withheld TDS, or the bank took charges). rank_suggestions
        scores those below exact matches and labels the shortfall; fetching
        only exact-amount rows would leave it nothing to score. Upper bound
        only — a receipt LARGER than the invoice isn't settling it."""
        if not bands:
            return []
        q = (db.table("client_sales_invoices")
             .select("id, invoice_no, invoice_date, total_paise, paid_paise, customer_id, status")
             .eq("firm_id", firm_id).eq("client_id", client_id)
             .is_("deleted_at", "null"))
        rows = (self._banded(q, "total_paise", bands, "invoice")
                .limit(self._pool_limit(bands)).execute().data or [])
        self._warn_if_truncated(rows, bands, "invoice")
        return rows

    def _invoice_candidates(self, db, firm_id, client_id, amount) -> list[Candidate]:
        bands = self._bands([amount])
        rows = self._fetch_invoice_pool(db, firm_id, client_id, bands)
        customers = self._party_names(db, "customers", firm_id, client_id)
        return self._invoices_from(rows, customers, amount)

    def _invoices_from(self, rows, customers, amount) -> list[Candidate]:
        out = []
        for r in rows:
            if not self._in_band(int(r.get("total_paise") or 0), amount):
                continue
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

    def _fetch_bill_pool(self, db, firm_id, client_id, bands) -> list[dict]:
        """Open purchase bills within any of `bands`. ONE query.

        Match on net_payable_paise, not total_paise: the money that actually
        leaves the bank for a vendor equals the bill's NET payable (total minus
        any TDS withheld / debit-note / credit-note adjustment) — which is also
        exactly what settlement relieves. Gating on total_paise meant any bill
        with TDS never surfaced as a candidate for its own outgoing payment.
        deleted_at filter: a soft-deleted bill is not a live payable."""
        if not bands:
            return []
        q = (db.table("purchase_bills")
             .select("id, bill_no, bill_date, total_paise, net_payable_paise, vendor_id, status")
             .eq("firm_id", firm_id).eq("client_id", client_id)
             .is_("deleted_at", "null"))
        rows = (self._banded(q, "net_payable_paise", bands, "bill")
                .limit(self._pool_limit(bands)).execute().data or [])
        self._warn_if_truncated(rows, bands, "bill")
        return rows

    def _bill_candidates(self, db, firm_id, client_id, amount) -> list[Candidate]:
        bands = self._bands([amount])
        rows = self._fetch_bill_pool(db, firm_id, client_id, bands)
        vendors = self._party_names(db, "vendors", firm_id, client_id)
        return self._bills_from(rows, vendors, amount)

    def _bills_from(self, rows, vendors, amount) -> list[Candidate]:
        out = []
        for r in rows:
            if not self._in_band(
                    int(r.get("net_payable_paise") or r.get("total_paise") or 0), amount):
                continue
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

    def _fetch_receipt_pool(self, db, firm_id, client_id, amounts) -> list[dict]:
        """Receipts at any of these exact amounts. ONE query — these match on
        equality, so the union is a plain IN rather than banded ORs."""
        if not amounts:
            return []
        return (db.table("receipts").select("id, receipt_no, receipt_date, amount_paise")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .in_("amount_paise", sorted(set(int(a) for a in amounts)))
                .limit(self._pool_limit([(0, 0)] * len(set(amounts)))).execute().data or [])

    def _receipt_candidates(self, db, firm_id, client_id, amount) -> list[Candidate]:
        return self._receipts_from(
            self._fetch_receipt_pool(db, firm_id, client_id, [amount]), amount)

    def _receipts_from(self, rows, amount) -> list[Candidate]:
        rows = [r for r in rows if int(r.get("amount_paise") or 0) == int(amount)]
        return [Candidate(
            entity_type="receipt", entity_id=r["id"],
            label=f"Receipt {r.get('receipt_no', '')}", amount_paise=int(r.get("amount_paise") or 0),
            entity_date=str(r.get("receipt_date") or "")[:10],
        ) for r in rows]

    def _fetch_payment_pool(self, db, firm_id, client_id, amounts) -> list[dict]:
        """Purchase payments at any of these exact amounts. ONE query."""
        if not amounts:
            return []
        return (db.table("purchase_payments").select("id, payment_no, payment_date, amount_paise")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .in_("amount_paise", sorted(set(int(a) for a in amounts)))
                .limit(self._pool_limit([(0, 0)] * len(set(amounts)))).execute().data or [])

    def _payment_candidates(self, db, firm_id, client_id, amount) -> list[Candidate]:
        return self._payments_from(
            self._fetch_payment_pool(db, firm_id, client_id, [amount]), amount)

    def _payments_from(self, rows, amount) -> list[Candidate]:
        rows = [r for r in rows if int(r.get("amount_paise") or 0) == int(amount)]
        return [Candidate(
            entity_type="purchase_payment", entity_id=r["id"],
            label=f"Payment {r.get('payment_no', '')}", amount_paise=int(r.get("amount_paise") or 0),
            entity_date=str(r.get("payment_date") or "")[:10],
        ) for r in rows]

    def _fetch_journal_pool(self, db, firm_id, client_id) -> list[dict]:
        """Posted journals for the client. This query never had an amount
        filter — the amount test is done per line, in Python — so it was
        always ONE query that happened to be re-issued once per row."""
        return (db.table("journal_entries")
                .select("id, entry_date, narration, reference_no, "
                        "journal_lines(debit_paise, credit_paise)")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("is_posted", True).limit(200).execute().data or [])

    def _journal_candidates(self, db, firm_id, client_id, amount) -> list[Candidate]:
        return self._journals_from(self._fetch_journal_pool(db, firm_id, client_id), amount)

    def _journals_from(self, rows, amount) -> list[Candidate]:
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
    # for_review / done / ignored are the three the screen uses; the rest are the
    # older, finer-grained views kept for callers and tests that still ask for
    # them. Five filters on one queue described the DATA's states rather than the
    # WORK's: a line is either still to do, done, or set aside, and splitting
    # "categorized" from "matched" made a reader classify their own queue before
    # they could work it.
    _QUEUE_STATUSES = frozenset({
        "for_review", "done",
        "unmatched", "categorized", "matched", "needs_review", "ignored", "all",
    })

    @staticmethod
    def _view_filter(q, status: str):
        """The queue's view, expressed as SQL rather than as a Python predicate.

        It used to fetch every transaction for the client and filter in
        Python. That is a read proportional to statement volume — thirteen
        cross-region round trips for a client with 12,836 lines, to render a
        page of fifty — and it is the shape CLAUDE.md rules out. Pushing the
        view down means the page is the only thing that crosses the wire.

        Safe in SQL because `match_status` is NOT NULL DEFAULT 'unmatched':
        the NULL-filter quirk the Python version was avoiding cannot arise on
        the column every view keys off. Where a nullable column IS involved
        the predicate says so explicitly — `category <> ''` keeps an empty
        string out of "categorized", which `bool(t.get("category"))` did too.

        An ignored row is out of the working views by definition; it shows in
        its own view and in "all", and nowhere else.
        """
        if status == "all":
            return q
        if status == "ignored":
            return q.eq("match_status", "ignored")
        if status == "for_review":
            # Everything still to do. Posted is done, ignored is set aside;
            # anything else is work, however far through it already is.
            return q.not_.in_("match_status", ["posted", "ignored"])
        if status == "done":
            return q.eq("match_status", "posted")
        q = q.neq("match_status", "ignored")
        if status == "unmatched":
            return q.eq("match_status", "unmatched").is_("matched_entity_id", "null")
        if status == "categorized":
            return q.not_.is_("category", "null").neq("category", "")
        if status == "matched":
            return q.not_.is_("matched_entity_id", "null")
        if status == "needs_review":
            return q.eq("needs_review", True)
        return q

    @staticmethod
    def _search_filter(q, term: Optional[str]):
        """Free-text search, IN SQL and therefore over the whole view.

        It has to be server-side. The screen shows one page; a box that
        filtered the fifty rows already fetched would answer "no match" for a
        line sitting on page four — a wrong answer, not a slow one.

        Searched: what the bank wrote (description), the reference, and the
        payee once a human has confirmed one. Not the amount — a CA types
        1,00,000 or 100000 or 1 lakh for the same figure and none of them is
        the stored paise, so an amount box is a separate control, not this one.
        `%` and `_` are escaped: a description search for "50%" must look for
        the character, not match everything."""
        term = (term or "").strip()
        if not term:
            return q
        safe = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pat = f"*{safe}*"
        return q.or_(",".join([
            f"description.ilike.{pat}",
            f"reference_no.ilike.{pat}",
            f"payee_name.ilike.{pat}",
        ]))

    def _queue_query(self, db, firm_id: str, client_id: Optional[str], status: str,
                     cols: str = "*", count: Optional[str] = None,
                     q_text: Optional[str] = None):
        q = db.table("bank_transactions").select(cols, count=count) if count \
            else db.table("bank_transactions").select(cols)
        q = q.eq("firm_id", firm_id)
        if client_id:
            q = q.eq("client_id", client_id)
        return self._search_filter(self._view_filter(q, status), q_text)

    def queue_total(self, db, firm_id: str, client_id: Optional[str],
                    status: str = "unmatched", q_text: Optional[str] = None) -> int:
        """How many rows the view holds, whatever slice of it is on screen.

        A paged queue that cannot say "50 of 312" hides the other 262 exactly
        the way the un-paged 1000-row ceiling used to."""
        if status not in self._QUEUE_STATUSES:
            raise HTTPException(status_code=422, detail="Invalid queue status.")
        res = self._queue_query(db, firm_id, client_id, status,
                                cols="id", count="exact", q_text=q_text).limit(1).execute()
        return int(getattr(res, "count", None) or 0)

    def queue(self, db, firm_id: str, client_id: Optional[str], status: str = "unmatched",
              limit: Optional[int] = None, offset: int = 0,
              with_suggestions: bool = False, q_text: Optional[str] = None) -> list[dict]:
        """One page of the work queue, enriched with rules and payee history.

        limit=None returns the whole view, as this always did — the enrichment
        below is per-row work, so a caller that wants everything still gets
        everything. The screen passes a limit.

        with_suggestions attaches each row's ranked match candidates, computed
        for the whole page at once. The screen used to fetch them one request
        per row after the queue arrived, which is why the green rows appeared a
        few at a time; asking for them here makes the page ONE request. Off by
        default so callers that only want the rows do not pay for the pools."""
        if status not in self._QUEUE_STATUSES:
            raise HTTPException(status_code=422, detail="Invalid queue status.")
        if limit is None:
            # fetch_all keyset-pages on `id` and imposes its own ORDER BY id,
            # so this query must NOT carry a sort of its own — the cursor would
            # walk a different order than the one it pages over. Sorted after.
            txns = fetch_all(
                lambda: self._queue_query(db, firm_id, client_id, status, q_text=q_text),
                label="matching.queue")
            txns.sort(key=lambda t: (str(t.get("transaction_date") or ""), str(t.get("id"))))
        else:
            # (transaction_date, id) — the id is the tiebreak, not decoration.
            # Dates repeat constantly on a statement, and a paged sort with ties
            # repeats rows on one page and drops them from the next.
            start = max(int(offset), 0)
            txns = (self._queue_query(db, firm_id, client_id, status, q_text=q_text)
                    .order("transaction_date").order("id")
                    .range(start, start + max(int(limit), 1) - 1)
                    .execute().data or [])

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
            # Offered in BOTH directions. Out is input credit (CGST Act s.16),
            # in is output tax (s.9) — the posting engine picks the accounts
            # from the direction, so the rule only has to state the rate.
            t["suggested_gst_rate_bps"] = (hit.gst_rate_bps if hit else None)
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
        # Candidates for the WHOLE page in one pass over each pool — see
        # suggestions_for_many. Never fatal: a pool that cannot be read costs
        # the reader suggestions, not the queue.
        if with_suggestions:
            live = [t for t in txns
                    if t.get("match_status") not in ("posted", "ignored")
                    and not t.get("matched_entity_id")]
            by_client: dict = {}
            for t in live:
                by_client.setdefault(t.get("client_id"), []).append(t)
            found: dict = {}
            for cid, group in by_client.items():
                if cid:
                    found.update(self.suggestions_for_many(db, firm_id, cid, group))
            for t in txns:
                t["suggestions"] = found.get(str(t.get("id")), [])

        self._attach_splits(db, firm_id, txns)
        self._mark_gst_eligibility(txns)
        return txns

    @staticmethod
    def _mark_gst_eligibility(txns: list[dict]) -> None:
        """Say, per row, whether a GST rate may go on it.

        The RULE lives in posting_map.gst_split_allowed and is the same call the
        posting engine makes to refuse one. Computed here rather than in the
        browser for the ordinary reason — it is a statutory rule, not a display
        choice — and, more practically, so the screen can never offer a control
        the server would then reject.

        Depends on `is_split`, so it must run after _attach_splits.
        """
        for t in txns:
            t["gst_allowed"] = pmap.gst_split_allowed(
                t.get("category"),
                settles_document=pmap.settles_document(
                    t.get("category"), t.get("matched_entity_type"),
                    t.get("matched_entity_id")),
                is_split=bool(t.get("is_split")))

    @staticmethod
    def _attach_splits(db, firm_id: str, txns: list[dict]) -> None:
        """Tier 1.2 — the ledgers a line was allocated across, for the WHOLE page.

        One query for the page, not one per row: splits are rare, but a
        per-row lookup would be fifty cross-region round trips to discover that
        forty-eight of them have none.

        Without this the queue could not tell a split row from an uncoded one —
        both carry a NULL category and a NULL account_id — so the screen showed
        a ledger picker over an allocation that was already made, and the first
        thing the CA did with it silently replaced their split.

        Never fatal: a split table that cannot be read costs the reader the
        allocation summary, not the queue.
        """
        ids = [str(t.get("id")) for t in txns if t.get("id")]
        by_txn: dict[str, list[dict]] = {}
        for i in range(0, len(ids), 200):
            chunk = ids[i:i + 200]
            try:
                rows = (db.table("bank_transaction_splits")
                        .select("bank_transaction_id, account_id, amount_paise, narration, sequence_no")
                        .eq("firm_id", firm_id).in_("bank_transaction_id", chunk)
                        .order("sequence_no").execute().data) or []
            except Exception as e:  # pragma: no cover - best effort, logged
                _logger.warning("queue split lookup failed: %s", e)
                rows = []
            for r in rows:
                by_txn.setdefault(str(r.get("bank_transaction_id")), []).append({
                    "account_id": r.get("account_id"),
                    "amount_paise": int(r.get("amount_paise") or 0),
                    "narration": r.get("narration"),
                })
        for t in txns:
            legs = by_txn.get(str(t.get("id")), [])
            t["splits"] = legs
            t["is_split"] = bool(legs)
            t["split_count"] = len(legs)

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
