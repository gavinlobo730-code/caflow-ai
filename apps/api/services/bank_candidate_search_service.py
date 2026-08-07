"""
"Find other matches" (Tier 1.6) — the searchable candidate picker.

`bank_matching_service.suggestions()` offers the best five candidates within an
amount band. This is the same candidate model with the band LIFTED, so a CA who
knows which invoice it is can simply find it.

WHAT IS DELIBERATELY DIFFERENT FROM suggestions()
    * NO amount band. The band is what makes automatic ranking safe; it is also
      exactly what hides the answer when the bank line differs from the document
      by more than a TDS-shaped shortfall. Lifting it is the feature.
    * Receipts, payments and journals are fetched by DATE window rather than
      exact amount, for the same reason — `suggestions()` requires
      amount equality on those, which is right for a suggestion and wrong for a
      search.
    * Paged, with a total, so "narrow it further" is visible rather than implied.

WHAT IS NOT DIFFERENT
    Direction still decides what can be settled at all, and the same document
    states are excluded — draft, cancelled, fully-paid, soft-deleted. Those are
    rules about what the ledger permits, not preferences about what to show, so
    a search box does not get to override them.

Every read is firm + client scoped. A free-text search over financial documents
is exactly where a missing tenant filter would surface.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import HTTPException

from core.authz import assert_client_access
from domain.banking.matcher import Candidate
from domain.banking.candidate_search import (
    search as search_candidates, describe, allowed_types, CandidateHit, MAX_RESULTS,
)

_logger = logging.getLogger("caflow.bank_candidate_search")

# How far either side of the bank line to look when no date filter is given.
# Wide enough to cover a quarter-old invoice settled late; bounded so a search
# over a client with years of history stays one quick query.
DEFAULT_WINDOW_DAYS = 400
FETCH_LIMIT = 500

SEARCHABLE_TYPES = ("sales_invoice", "purchase_bill", "receipt",
                    "purchase_payment", "journal_entry")


def _iso(d: date) -> str:
    return d.isoformat()


class BankCandidateSearchService:

    def _get_txn(self, db, firm_id: str, txn_id: str) -> dict:
        rows = (db.table("bank_transactions").select("*")
                .eq("id", txn_id).eq("firm_id", firm_id).limit(1).execute().data) or []
        if not rows:
            raise HTTPException(status_code=404, detail="Bank transaction not found.")
        return rows[0]

    def _party_names(self, db, table, firm_id, client_id) -> dict:
        try:
            rows = (db.table(table).select("id, name")
                    .eq("firm_id", firm_id).eq("client_id", client_id).execute().data) or []
            return {r["id"]: r.get("name") for r in rows}
        except Exception:  # pragma: no cover - a name is a nicety, not the match
            return {}

    # ── candidate fetch, WITHOUT an amount band ─────────────────────────────
    def _fetch(self, db, firm_id, client_id, is_credit, d_from, d_to) -> list[Candidate]:
        out: list[Candidate] = []
        try:
            if is_credit:
                out += self._invoices(db, firm_id, client_id, d_from, d_to)
                out += self._simple(db, firm_id, client_id, "receipts", "receipt",
                                    "receipt_no", "receipt_date", "Receipt", d_from, d_to)
            else:
                out += self._bills(db, firm_id, client_id, d_from, d_to)
                out += self._simple(db, firm_id, client_id, "purchase_payments",
                                    "purchase_payment", "payment_no", "payment_date",
                                    "Payment", d_from, d_to)
            out += self._journals(db, firm_id, client_id, d_from, d_to)
        except Exception as e:  # pragma: no cover - a search must degrade, not 500
            _logger.warning("candidate search fetch failed for client %s: %s", client_id, e)
        return out

    def _invoices(self, db, firm_id, client_id, d_from, d_to) -> list[Candidate]:
        rows = (db.table("client_sales_invoices")
                .select("id, invoice_no, invoice_date, total_paise, paid_paise, "
                        "customer_id, status")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .is_("deleted_at", "null")
                .gte("invoice_date", d_from).lte("invoice_date", d_to)
                .limit(FETCH_LIMIT).execute().data) or []
        customers = self._party_names(db, "customers", firm_id, client_id)
        out = []
        for r in rows:
            # Same exclusions as suggestions(): a draft was never issued, so no
            # AR journal exists for a bank line to settle against.
            if str(r.get("status")) in ("cancelled", "draft"):
                continue
            total = int(r.get("total_paise") or 0)
            paid = int(r.get("paid_paise") or 0)
            if paid >= total:
                continue
            party = customers.get(r.get("customer_id"))
            out.append(Candidate(
                entity_type="sales_invoice", entity_id=r["id"],
                label=f"{r.get('invoice_no', '')} · {party or 'Customer'}",
                amount_paise=total, entity_date=str(r.get("invoice_date") or "")[:10],
                party_name=party, party_id=r.get("customer_id"),
                outstanding_paise=total - paid,
            ))
        return out

    def _bills(self, db, firm_id, client_id, d_from, d_to) -> list[Candidate]:
        rows = (db.table("purchase_bills")
                .select("id, bill_no, bill_date, total_paise, net_payable_paise, "
                        "vendor_id, status")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .is_("deleted_at", "null")
                .gte("bill_date", d_from).lte("bill_date", d_to)
                .limit(FETCH_LIMIT).execute().data) or []
        vendors = self._party_names(db, "vendors", firm_id, client_id)
        out = []
        for r in rows:
            if str(r.get("status")) in ("cancelled", "paid", "draft"):
                continue
            party = vendors.get(r.get("vendor_id"))
            # The payable (TDS-net), not the gross total — that is what actually
            # leaves the bank and what settlement relieves.
            net = int(r.get("net_payable_paise") or r.get("total_paise") or 0)
            out.append(Candidate(
                entity_type="purchase_bill", entity_id=r["id"],
                label=f"{r.get('bill_no', '')} · {party or 'Vendor'}",
                amount_paise=net, entity_date=str(r.get("bill_date") or "")[:10],
                party_name=party, party_id=r.get("vendor_id"),
                outstanding_paise=net,
            ))
        return out

    def _simple(self, db, firm_id, client_id, table, entity_type, no_col, date_col,
                prefix, d_from, d_to) -> list[Candidate]:
        """Receipts and payments — fetched by DATE, not by exact amount.

        suggestions() requires amount equality on these, which is right for an
        automatic offer and wrong for a search: the reason someone is searching
        is that the amounts do not line up.
        """
        rows = (db.table(table).select(f"id, {no_col}, {date_col}, amount_paise")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .gte(date_col, d_from).lte(date_col, d_to)
                .limit(FETCH_LIMIT).execute().data) or []
        return [Candidate(
            entity_type=entity_type, entity_id=r["id"],
            label=f"{prefix} {r.get(no_col, '')}".strip(),
            amount_paise=int(r.get("amount_paise") or 0),
            entity_date=str(r.get(date_col) or "")[:10],
        ) for r in rows]

    def _journals(self, db, firm_id, client_id, d_from, d_to) -> list[Candidate]:
        rows = (db.table("journal_entries")
                .select("id, entry_date, narration, reference_no, "
                        "journal_lines(debit_paise, credit_paise)")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("is_posted", True)
                .gte("entry_date", d_from).lte("entry_date", d_to)
                .limit(FETCH_LIMIT).execute().data) or []
        out = []
        for e in rows:
            lines = e.get("journal_lines") or []
            if not lines:
                continue
            # The entry's size, for comparison against the bank line. Debits and
            # credits are equal on a posted entry, so either side describes it.
            amount = max(int(l.get("debit_paise") or 0) for l in lines) if lines else 0
            out.append(Candidate(
                entity_type="journal_entry", entity_id=e["id"],
                label=f"{e.get('reference_no') or 'JE'} · {(e.get('narration') or '')[:40]}",
                amount_paise=amount, entity_date=str(e.get("entry_date") or "")[:10],
            ))
        return out

    # ── the search ──────────────────────────────────────────────────────────
    def search(self, db, firm_id: str, txn_id: str, current_user: dict, *,
               q: Optional[str] = None,
               date_from: Optional[str] = None, date_to: Optional[str] = None,
               min_amount_paise: Optional[int] = None,
               max_amount_paise: Optional[int] = None,
               entity_type: Optional[str] = None,
               party_id: Optional[str] = None,
               limit: int = 25, offset: int = 0) -> dict:
        if entity_type and entity_type not in SEARCHABLE_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown type '{entity_type}'. Allowed: {', '.join(SEARCHABLE_TYPES)}")
        if date_from and date_to and date_from > date_to:
            raise HTTPException(status_code=422,
                                detail="The start date must not follow the end date.")
        if (min_amount_paise is not None and max_amount_paise is not None
                and min_amount_paise > max_amount_paise):
            raise HTTPException(status_code=422,
                                detail="The minimum amount cannot exceed the maximum.")

        txn = self._get_txn(db, firm_id, txn_id)
        # Only a Partner is firm-wide (core.authz._FIRMWIDE_ROLES); a Manager or
        # Executive sees only their assigned book. Firm scoping alone is not
        # enough here: this endpoint is addressed by transaction id and answers
        # with a list of that client's open invoices, bills and party names, so
        # without this line a transaction id from another manager's client reads
        # out their receivables. 404, not 403 — existence is not disclosed.
        assert_client_access(current_user, txn.get("client_id"))

        debit = int(txn.get("debit_paise") or 0)
        credit = int(txn.get("credit_paise") or 0)
        amount, is_credit = max(debit, credit), credit > 0

        # A type the caller asked for that this DIRECTION cannot settle is a
        # refusal, not an empty result — silently returning nothing would read
        # as "there are none", which is a different and misleading answer.
        permitted = allowed_types(is_credit)
        if entity_type and entity_type not in permitted:
            raise HTTPException(
                status_code=422,
                detail=(f"Money {'arriving in' if is_credit else 'leaving'} the bank cannot "
                        f"settle a {entity_type.replace('_', ' ')}. "
                        f"Allowed here: {', '.join(permitted)}."))

        txn_date = str(txn.get("transaction_date") or "")[:10]
        base = date.fromisoformat(txn_date) if txn_date else date.today()
        fetch_from = date_from or _iso(base - timedelta(days=DEFAULT_WINDOW_DAYS))
        fetch_to = date_to or _iso(base + timedelta(days=DEFAULT_WINDOW_DAYS))

        candidates = self._fetch(db, firm_id, txn["client_id"], is_credit,
                                 fetch_from, fetch_to)
        hits, total = search_candidates(
            candidates, bank_amount_paise=amount, bank_date=txn_date,
            is_credit=is_credit, q=q, date_from=date_from, date_to=date_to,
            min_amount_paise=min_amount_paise, max_amount_paise=max_amount_paise,
            entity_type=entity_type, party_id=party_id, limit=limit, offset=offset)

        return {
            "transaction_id": txn_id,
            "amount_paise": amount,
            "direction": "credit" if is_credit else "debit",
            "allowed_types": list(permitted),
            "results": [self._out(h) for h in hits],
            "total": total,
            "limit": max(1, min(int(limit), MAX_RESULTS)),
            "offset": max(0, int(offset)),
            # True when the fetch itself may have truncated, so a CA can tell
            # "nothing matches" from "too much matched to look at".
            "truncated": len(candidates) >= FETCH_LIMIT,
        }

    @staticmethod
    def _out(h: CandidateHit) -> dict:
        return {
            "matched_entity_type": h.entity_type,
            "matched_entity_id": h.entity_id,
            "label": h.label,
            "amount_paise": h.amount_paise,
            "entity_date": h.entity_date,
            "party_name": h.party_name,
            "party_id": h.party_id,
            "outstanding_paise": h.outstanding_paise,
            "difference_paise": h.difference_paise,
            "tds_rate_bps": h.tds_rate_bps,
            "is_exact": h.is_exact,
            "summary": describe(h),
        }


bank_candidate_search_service = BankCandidateSearchService()
