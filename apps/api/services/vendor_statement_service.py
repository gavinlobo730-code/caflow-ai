"""
Vendor statement + AP aging (Phase 5) — the AP-side mirror of the customer
statement / AR aging. READ-ONLY: reconstructs the vendor's PAYABLE from posted
purchase bills, vendor payments and issued debit notes. No posting.

Sign convention (payable / credit-positive — what we owe the vendor):
  • Bill        → +net_payable  (increases the payable; net of TDS withheld)
  • Payment     → −amount       (reduces the payable)
  • Debit note  → −total        (purchase return reduces the payable)

Bill net outstanding = net_payable − paid − debited, matching the sub-ledger the
GL AP control is built from. Integer paise throughout.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone, timedelta
from typing import Optional

from fastapi import HTTPException

_logger = logging.getLogger("caflow.vendor_statement")

_DEAD_BILL = {"draft", "cancelled"}
_DEAD_DEBIT_NOTE = {"draft", "cancelled"}


def _d(v) -> str:
    return str(v)[:10]


def build_statement(vendor: dict, start: str, end: str,
                    bills: list[dict], payments: list[dict], debit_notes: list[dict]) -> dict:
    """Pure builder — opening, ordered transactions with running payable, closing."""
    start, end = _d(start), _d(end)
    events: list[dict] = []
    for b in bills:
        events.append({"date": _d(b.get("bill_date")), "rank": 0, "type": "bill",
                       "reference": b.get("bill_no"),
                       "particulars": f"Bill {b.get('bill_no', '')}".strip(),
                       "credit_paise": int(b.get("net_payable_paise") or 0), "debit_paise": 0})
    for dn in debit_notes:
        events.append({"date": _d(dn.get("debit_note_date")), "rank": 1, "type": "debit_note",
                       "reference": dn.get("debit_note_no"),
                       "particulars": f"Debit Note {dn.get('debit_note_no', '')}".strip(),
                       "credit_paise": 0, "debit_paise": int(dn.get("total_paise") or 0)})
    for p in payments:
        events.append({"date": _d(p.get("payment_date")), "rank": 2, "type": "payment",
                       "reference": p.get("payment_no"),
                       "particulars": f"Payment {p.get('payment_no', '')}".strip(),
                       "credit_paise": 0, "debit_paise": int(p.get("amount_paise") or 0)})

    events.sort(key=lambda e: (e["date"], e["rank"], str(e["reference"] or "")))

    # Payable-positive running balance. Opening = seed + everything before the window.
    opening = int(vendor.get("opening_balance_paise") or 0)
    for e in events:
        if e["date"] < start:
            opening += e["credit_paise"] - e["debit_paise"]

    running = opening
    transactions, billed, paid, debited = [], 0, 0, 0
    for e in events:
        if e["date"] < start or e["date"] > end:
            continue
        running += e["credit_paise"] - e["debit_paise"]
        billed += e["credit_paise"] if e["type"] == "bill" else 0
        paid += e["debit_paise"] if e["type"] == "payment" else 0
        debited += e["debit_paise"] if e["type"] == "debit_note" else 0
        transactions.append({
            "date": e["date"], "type": e["type"], "reference": e["reference"],
            "particulars": e["particulars"], "debit_paise": e["debit_paise"],
            "credit_paise": e["credit_paise"], "running_balance_paise": running,
        })

    return {
        "vendor": {"id": vendor.get("id"), "name": vendor.get("name"),
                   "gstin": vendor.get("gstin"), "email": vendor.get("email"),
                   "phone": vendor.get("phone")},
        "period": {"start_date": start, "end_date": end},
        "opening_balance_paise": opening,
        "transactions": transactions,
        "closing_balance_paise": running,
        "totals": {"billed_paise": billed, "paid_paise": paid, "debited_paise": debited,
                   "transaction_count": len(transactions)},
    }


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

        b = (db.table("purchase_bills")
             .select("bill_no, bill_date, net_payable_paise, status")
             .eq("firm_id", firm_id).eq("client_id", client_id).eq("vendor_id", vendor_id)
             .execute().data or [])
        bills = [x for x in b if (x.get("status") or "") not in _DEAD_BILL]

        payments = (db.table("purchase_payments")
                    .select("payment_no, payment_date, amount_paise")
                    .eq("firm_id", firm_id).eq("client_id", client_id).eq("vendor_id", vendor_id)
                    .execute().data or [])

        dn = (db.table("debit_notes")
              .select("debit_note_no, debit_note_date, total_paise, status")
              .eq("firm_id", firm_id).eq("client_id", client_id).eq("vendor_id", vendor_id)
              .execute().data or [])
        debit_notes = [x for x in dn if (x.get("status") or "") not in _DEAD_DEBIT_NOTE]

        return build_statement(vendor, start_date, end_date, bills, payments, debit_notes)

    def ap_aging(self, db, firm_id: str, client_id: str, as_of: Optional[str] = None) -> dict:
        """Accounts-payable aging: per non-cancelled bill, outstanding = net_payable −
        paid − debited, bucketed by age from due_date (or bill_date). Mirrors AR aging."""
        today = date.fromisoformat(_d(as_of)) if as_of else datetime.now(timezone.utc).date()
        bills = (db.table("purchase_bills")
                 .select("id, vendor_id, bill_no, bill_date, due_date, net_payable_paise, paid_paise, debited_paise, status")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .neq("status", "cancelled").execute().data or [])
        vnames = {v["id"]: v.get("name") for v in (db.table("vendors").select("id, name")
                  .eq("firm_id", firm_id).eq("client_id", client_id).execute().data or [])}

        buckets = {"not_due": 0, "0-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
        rows, total = [], 0
        for b in bills:
            outstanding = (int(b.get("net_payable_paise") or 0)
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
            rows.append({
                "bill_id": b.get("id"), "bill_no": b.get("bill_no"),
                "vendor_id": b.get("vendor_id"), "vendor_name": vnames.get(b.get("vendor_id")),
                "bill_date": _d(b.get("bill_date")), "outstanding_paise": outstanding,
                "days_overdue": max(days, 0), "aging_bucket": bucket,
            })
        return {"as_of": today.isoformat(), "buckets": buckets,
                "total_outstanding_paise": total, "bills": rows}


vendor_statement_service = VendorStatementService()
