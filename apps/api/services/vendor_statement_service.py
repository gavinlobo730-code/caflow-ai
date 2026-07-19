"""
Vendor statement + AP aging (Phase 5) — the AP-side mirror of the customer
statement / AR aging. READ-ONLY: reconstructs the vendor's PAYABLE from posted
purchase bills, vendor payments, issued debit notes and issued purchase
credit notes. No posting.

Sign convention (payable / credit-positive — what we owe the vendor):
  • Bill        → +net_payable  (increases the payable; net of TDS withheld)
  • Credit note → +total        (§34(3) undercharge correction — increases the payable)
  • Payment     → −amount       (reduces the payable)
  • Debit note  → −total        (purchase return reduces the payable)

Bill net outstanding = (net_payable + credit_note_paise) − paid − debited, matching
the sub-ledger the GL AP control is built from. Integer paise throughout.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone, timedelta
from typing import Optional

from fastapi import HTTPException

from services.statement_currency import attach_currency_outstanding, summarize_by_currency

_logger = logging.getLogger("caflow.vendor_statement")

_DEAD_BILL = {"draft", "cancelled"}
_DEAD_DEBIT_NOTE = {"draft", "cancelled"}
_DEAD_CREDIT_NOTE = {"draft", "cancelled"}


def _d(v) -> str:
    return str(v)[:10]


def _paginate_all(make_query, key: str = "id", page: int = 1000) -> list:
    """Fetch EVERY row of a Supabase query via keyset paging on `key` (task
    #221, same audit-C6 class as domain/reporting/sources.py's _fetch_all).
    An un-paged .execute() is silently capped at PostgREST's ~1000-row limit,
    understating a client's AP aging / statement totals with no error.
    `make_query` returns a fresh query builder each call. Test doubles that
    don't implement order/limit/gt just return their whole (small) fixture
    from a single execute(), which is already correct."""
    first = make_query()
    if not (hasattr(first, "gt") and hasattr(first, "order") and hasattr(first, "limit")):
        return first.execute().data or []
    out: list = []
    cursor = None
    while True:
        q = make_query()
        if cursor is not None:
            q = q.gt(key, cursor)
        rows = q.order(key).limit(page).execute().data or []
        out.extend(rows)
        if len(rows) < page:
            break
        cursor = rows[-1][key]
    return out


def _ccy_view(row: dict, base_paise: int, txn_amount) -> dict:
    """Dual-currency display for a statement line (Multi-Currency Phase 3): txn
    currency + frozen rate + foreign amount alongside the authoritative BASE amount.
    INR rows resolve to the identity (INR / rate 1 / txn == base)."""
    return {
        "txn_currency": (row.get("txn_currency") or "INR"),
        "exchange_rate": str(row.get("exchange_rate") or 1),
        "txn_amount": int(txn_amount if txn_amount is not None else base_paise),
    }


def build_statement(vendor: dict, start: str, end: str,
                    bills: list[dict], payments: list[dict], debit_notes: list[dict],
                    credit_notes: list[dict] | None = None) -> dict:
    """Pure builder — opening, ordered transactions with running payable, closing."""
    start, end = _d(start), _d(end)
    events: list[dict] = []
    for b in bills:
        _np = int(b.get("net_payable_paise") or 0)
        events.append({"date": _d(b.get("bill_date")), "rank": 0, "type": "bill",
                       "reference": b.get("bill_no"),
                       "particulars": f"Bill {b.get('bill_no', '')}".strip(),
                       "credit_paise": _np, "debit_paise": 0,
                       **_ccy_view(b, _np, b.get("txn_net_payable"))})
    for cn in (credit_notes or []):
        _ct = int(cn.get("total_paise") or 0)
        events.append({"date": _d(cn.get("credit_note_date")), "rank": 1, "type": "credit_note",
                       "reference": cn.get("credit_note_no"),
                       "particulars": f"Credit Note {cn.get('credit_note_no', '')}".strip(),
                       "credit_paise": _ct, "debit_paise": 0,
                       **_ccy_view(cn, _ct, cn.get("total_paise"))})
    for dn in debit_notes:
        _dt = int(dn.get("total_paise") or 0)
        events.append({"date": _d(dn.get("debit_note_date")), "rank": 2, "type": "debit_note",
                       "reference": dn.get("debit_note_no"),
                       "particulars": f"Debit Note {dn.get('debit_note_no', '')}".strip(),
                       "credit_paise": 0, "debit_paise": _dt,
                       **_ccy_view(dn, _dt, dn.get("total_paise"))})
    for p in payments:
        # A payment relieves AP by its true settlement. For INR payments,
        # amount_paise IS that (journal_for_purchase_payment debits Trade
        # Payables for amount_paise directly). For a FOREIGN payment,
        # amount_paise is the CASH-rate total, but the journal
        # (_create_foreign_payment) debits AP at the bill's frozen BOOKED
        # rate, routing the cash/booked-rate delta to Realized FX Gain/Loss —
        # so amount_paise alone is off by exactly that delta (task #102
        # finding). ap_relief_paise, when the caller supplies it
        # (vendor_statement_service.generate(), derived from amount_paise +
        # fx_adjustments.base_delta_paise — 0 for INR payments, a no-op
        # there), is the authoritative figure; amount_paise remains the
        # fallback for pure-builder callers without fx_adjustments on hand.
        _amt = (int(p["ap_relief_paise"]) if p.get("ap_relief_paise") is not None
                else int(p.get("amount_paise") or 0))
        events.append({"date": _d(p.get("payment_date")), "rank": 3, "type": "payment",
                       "reference": p.get("payment_no"),
                       "particulars": f"Payment {p.get('payment_no', '')}".strip(),
                       "credit_paise": 0, "debit_paise": _amt,
                       **_ccy_view(p, _amt, p.get("txn_amount"))})

    events.sort(key=lambda e: (e["date"], e["rank"], str(e["reference"] or "")))

    # Payable-positive running balance. Opening = seed + everything before the window.
    opening = int(vendor.get("opening_balance_paise") or 0)
    for e in events:
        if e["date"] < start:
            opening += e["credit_paise"] - e["debit_paise"]

    running = opening
    transactions, billed, paid, debited, credited = [], 0, 0, 0, 0
    for e in events:
        if e["date"] < start or e["date"] > end:
            continue
        running += e["credit_paise"] - e["debit_paise"]
        billed += e["credit_paise"] if e["type"] == "bill" else 0
        paid += e["debit_paise"] if e["type"] == "payment" else 0
        debited += e["debit_paise"] if e["type"] == "debit_note" else 0
        credited += e["credit_paise"] if e["type"] == "credit_note" else 0
        transactions.append({
            "date": e["date"], "type": e["type"], "reference": e["reference"],
            "particulars": e["particulars"], "debit_paise": e["debit_paise"],
            "credit_paise": e["credit_paise"], "running_balance_paise": running,
            # Dual-currency display (base amounts above are authoritative).
            "txn_currency": e["txn_currency"], "exchange_rate": e["exchange_rate"],
            "txn_amount": e["txn_amount"],
        })

    result = {
        "vendor": {"id": vendor.get("id"), "name": vendor.get("name"),
                   "gstin": vendor.get("gstin"), "email": vendor.get("email"),
                   "phone": vendor.get("phone")},
        "period": {"start_date": start, "end_date": end},
        "opening_balance_paise": opening,
        "transactions": transactions,
        "closing_balance_paise": running,
        "totals": {"billed_paise": billed, "paid_paise": paid, "debited_paise": debited,
                   "credited_paise": credited, "transaction_count": len(transactions)},
    }
    # Multi-Currency Phase 5 — closing payable split by transaction currency (foreign
    # + base), reconciling to closing_balance_paise. Payable = credit-positive.
    # Emitted only when the vendor has foreign activity (INR vendors unchanged).
    attach_currency_outstanding(result, vendor, events, end, credit_positive=True)
    return result


def _aging_bucket(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "not_due"
    if days_overdue <= 30:
        return "0-30"
    if days_overdue <= 60:
        return "31-60"
    if days_overdue <= 90:
        return "61-90"
    return "90+"


class VendorStatementService:

    def _vendor(self, db, firm_id, client_id, vendor_id) -> dict:
        res = (db.table("vendors").select("*")
               .eq("id", vendor_id).eq("firm_id", firm_id).eq("client_id", client_id)
               .limit(1).execute())
        row = (res.data or [None])[0]
        if not row:
            raise HTTPException(status_code=404, detail="Vendor not found for this client.")
        return row

    def generate(self, db, firm_id: str, client_id: str, vendor_id: str,
                 start_date: str, end_date: str) -> dict:
        if end_date < start_date:
            raise HTTPException(status_code=422, detail="end_date must not precede start_date.")
        vendor = self._vendor(db, firm_id, client_id, vendor_id)

        b = _paginate_all(lambda: db.table("purchase_bills")
             .select("id, bill_no, bill_date, net_payable_paise, status, txn_currency, exchange_rate, txn_net_payable")
             .eq("firm_id", firm_id).eq("client_id", client_id).eq("vendor_id", vendor_id)
             .is_("deleted_at", "null"))
        bills = [x for x in b if (x.get("status") or "") not in _DEAD_BILL]

        _pay = _paginate_all(lambda: db.table("purchase_payments")
                .select("id, payment_no, payment_date, amount_paise, is_reversed, "
                        "txn_currency, exchange_rate, txn_amount")
                .eq("firm_id", firm_id).eq("client_id", client_id).eq("vendor_id", vendor_id))
        # A reversed payment no longer represents real money movement (task
        # #102) — filtered in Python, not .eq(), so a test double lacking the
        # key (impossible on the real NOT NULL DEFAULT false column) isn't
        # incorrectly excluded — see customer_statement_service's identical note.
        payments = [p for p in _pay if not p.get("is_reversed")]
        # ap_relief_paise = true AP debit per payment (task #102 FX statement
        # fix, see build_statement's payment loop). fx_adjustments carries the
        # cash/booked-rate delta per document; absent for INR payments (delta
        # always 0 there), so this is additive.
        payment_ids = [p["id"] for p in payments if p.get("id")]
        fx_delta: dict[str, int] = {}
        if payment_ids:
            adjs = _paginate_all(lambda: db.table("fx_adjustments").select("id, document_id, base_delta_paise")
                    .eq("firm_id", firm_id).eq("client_id", client_id)
                    .eq("document_type", "purchase_payment").in_("document_id", payment_ids))
            for a in adjs:
                fx_delta[a.get("document_id")] = fx_delta.get(a.get("document_id"), 0) + int(a.get("base_delta_paise") or 0)
        for p in payments:
            p["ap_relief_paise"] = int(p.get("amount_paise") or 0) + fx_delta.get(p.get("id"), 0)

        dn = _paginate_all(lambda: db.table("debit_notes")
              .select("id, debit_note_no, debit_note_date, total_paise, status")
              .eq("firm_id", firm_id).eq("client_id", client_id).eq("vendor_id", vendor_id)
              .is_("deleted_at", "null"))
        debit_notes = [x for x in dn if (x.get("status") or "") not in _DEAD_DEBIT_NOTE]

        cn = _paginate_all(lambda: db.table("purchase_credit_notes")
              .select("id, credit_note_no, credit_note_date, total_paise, status")
              .eq("firm_id", firm_id).eq("client_id", client_id).eq("vendor_id", vendor_id)
              .is_("deleted_at", "null"))
        credit_notes = [x for x in cn if (x.get("status") or "") not in _DEAD_CREDIT_NOTE]

        return build_statement(vendor, start_date, end_date, bills, payments, debit_notes, credit_notes)

    def ap_aging(self, db, firm_id: str, client_id: str, as_of: Optional[str] = None) -> dict:
        """Accounts-payable aging: per non-cancelled bill, outstanding = net_payable −
        paid − debited, bucketed by age from due_date (or bill_date). Mirrors AR aging."""
        today = date.fromisoformat(_d(as_of)) if as_of else datetime.now(timezone.utc).date()
        bills = _paginate_all(lambda: db.table("purchase_bills")
                 .select("id, vendor_id, bill_no, bill_date, due_date, net_payable_paise, paid_paise, "
                         "debited_paise, credit_note_paise, status, txn_currency, exchange_rate, txn_net_payable, paid_txn")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .is_("deleted_at", "null"))
        vnames = {v["id"]: v.get("name") for v in _paginate_all(lambda: db.table("vendors").select("id, name")
                  .eq("firm_id", firm_id).eq("client_id", client_id))}

        buckets = {"not_due": 0, "0-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
        rows, total = [], 0
        ccy_entries: list[tuple] = []   # (currency, base_paise, foreign_minor) for the breakdown
        for b in bills:
            if (b.get("status") or "") in _DEAD_BILL:
                continue
            # (net_payable + credit notes) − paid − debited (CGST Act §34).
            outstanding = (int(b.get("net_payable_paise") or 0) + int(b.get("credit_note_paise") or 0)
                           - int(b.get("paid_paise") or 0) - int(b.get("debited_paise") or 0))
            if outstanding <= 0:
                continue
            ref = b.get("due_date") or b.get("bill_date")
            try:
                days = (today - date.fromisoformat(_d(ref))).days if ref else 0
            except (ValueError, TypeError):
                days = 0
            bucket = _aging_bucket(days)
            buckets[bucket] += outstanding
            total += outstanding
            row = {
                "bill_id": b.get("id"), "bill_no": b.get("bill_no"),
                "vendor_id": b.get("vendor_id"), "vendor_name": vnames.get(b.get("vendor_id")),
                "bill_date": _d(b.get("bill_date")), "outstanding_paise": outstanding,
                "days_overdue": max(days, 0), "aging_bucket": bucket,
            }
            # Multi-Currency Phase 5 — foreign outstanding on FOREIGN bills only, so an
            # INR-only aging keeps its exact shape. base outstanding stays authoritative.
            cur = (b.get("txn_currency") or "INR").upper()
            foreign_out = 0
            if cur != "INR":
                foreign_out = int(b.get("txn_net_payable") or 0) - int(b.get("paid_txn") or 0)
                row["txn_currency"] = cur
                row["exchange_rate"] = str(b.get("exchange_rate") or 1)
                row["outstanding_base_paise"] = outstanding
                row["outstanding_foreign_minor"] = foreign_out
            ccy_entries.append((cur, outstanding, foreign_out))
            rows.append(row)

        out = {"as_of": today.isoformat(), "buckets": buckets,
               "total_outstanding_paise": total, "bills": rows}
        base_cur, by_ccy = summarize_by_currency(ccy_entries)
        if by_ccy is not None:
            out["base_currency"] = base_cur
            out["by_currency"] = by_ccy
        return out


vendor_statement_service = VendorStatementService()
