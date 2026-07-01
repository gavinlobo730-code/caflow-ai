"""
Customer statement service (Phase 4.1) — a READ-ONLY consolidated account
statement for a client's customer: opening balance, the period's invoices /
receipts / credit notes, a running balance, and the closing outstanding.

Reuses existing accounting data only. It does NOT touch the journal engine,
banking, GST or any financial statement — it reads client_sales_invoices,
receipts and credit_notes and reconstructs the customer's receivable balance.

Sign convention (receivable / debit-positive):
  • Invoice    → DEBIT  (increases what the customer owes)
  • Receipt    → CREDIT (payment received — reduces the balance)
  • Credit note→ CREDIT (reduces the balance)
Opening balance carries forward the customer's seed balance plus all prior-period
activity, so a statement for any window is correct. Integer paise throughout.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import HTTPException

from services.statement_currency import attach_currency_outstanding, summarize_by_currency

_logger = logging.getLogger("caflow.customer_statement")

# Invoices/credit notes in these states are not real receivable movements.
_DEAD_INVOICE = {"draft", "cancelled"}
_DEAD_CREDIT_NOTE = {"draft", "cancelled"}


def _d(v) -> str:
    return str(v)[:10]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _ccy_view(row: dict, base_paise: int, txn_amount) -> dict:
    """Dual-currency display for a statement line (Multi-Currency Phase 3): the txn
    currency + frozen rate + foreign amount alongside the authoritative BASE amount.
    INR rows resolve to the identity (INR / rate 1 / txn == base)."""
    return {
        "txn_currency": (row.get("txn_currency") or "INR"),
        "exchange_rate": str(row.get("exchange_rate") or 1),
        "txn_amount": int(txn_amount if txn_amount is not None else base_paise),
    }


def build_statement(customer: dict, start: str, end: str,
                    invoices: list[dict], receipts: list[dict],
                    credit_notes: list[dict]) -> dict:
    """Pure builder — no DB. Computes opening, ordered transactions with running
    balance, and closing outstanding from the supplied documents."""
    start, end = _d(start), _d(end)

    events: list[dict] = []   # (date, rank, debit, credit, type, reference, particulars)
    for inv in invoices:
        events.append({"date": _d(inv.get("invoice_date")), "rank": 0, "type": "invoice",
                       "reference": inv.get("invoice_no"),
                       "particulars": f"Invoice {inv.get('invoice_no', '')}".strip(),
                       "debit_paise": int(inv.get("total_paise") or 0), "credit_paise": 0,
                       **_ccy_view(inv, int(inv.get("total_paise") or 0), inv.get("txn_total"))})
    for cn in credit_notes:
        events.append({"date": _d(cn.get("credit_note_date")), "rank": 1, "type": "credit_note",
                       "reference": cn.get("credit_note_no"),
                       "particulars": f"Credit Note {cn.get('credit_note_no', '')}".strip(),
                       "debit_paise": 0, "credit_paise": int(cn.get("total_paise") or 0),
                       **_ccy_view(cn, int(cn.get("total_paise") or 0), cn.get("total_paise"))})
    for r in receipts:
        # A receipt relieves AR by its full SETTLEMENT (cash + TDS deducted at source),
        # exactly as journal_for_receipt credits Trade Receivables. Counting only the cash
        # would overstate the closing balance by the TDS and break reconciliation with the
        # AR sub-ledger / GL control (audit H9).
        settlement = int(r.get("amount_paise") or 0) + int(r.get("tds_paise") or 0)
        events.append({"date": _d(r.get("receipt_date")), "rank": 2, "type": "receipt",
                       "reference": r.get("receipt_no"),
                       "particulars": f"Receipt {r.get('receipt_no', '')}".strip(),
                       "debit_paise": 0, "credit_paise": settlement,
                       **_ccy_view(r, settlement, r.get("txn_amount"))})

    events.sort(key=lambda e: (e["date"], e["rank"], str(e["reference"] or "")))

    # Opening = seed balance + everything strictly before the period start.
    opening = int(customer.get("opening_balance_paise") or 0)
    for e in events:
        if e["date"] < start:
            opening += e["debit_paise"] - e["credit_paise"]

    running = opening
    transactions: list[dict] = []
    invoiced = received = credited = 0
    for e in events:
        if e["date"] < start or e["date"] > end:
            continue
        running += e["debit_paise"] - e["credit_paise"]
        invoiced += e["debit_paise"] if e["type"] == "invoice" else 0
        received += e["credit_paise"] if e["type"] == "receipt" else 0
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
        "customer": {
            "id": customer.get("id"), "name": customer.get("name"),
            "email": customer.get("email"), "gstin": customer.get("gstin"),
            "phone": customer.get("phone"),
            "address": customer.get("address"), "city": customer.get("city"),
            "state": customer.get("state"), "pincode": customer.get("pincode"),
        },
        "period": {"start_date": start, "end_date": end},
        "opening_balance_paise": opening,
        "transactions": transactions,
        "closing_balance_paise": running,
        "totals": {
            "invoiced_paise": invoiced, "received_paise": received,
            "credited_paise": credited, "transaction_count": len(transactions),
        },
    }
    # Multi-Currency Phase 5 — closing outstanding split by transaction currency
    # (foreign + base), reconciling to closing_balance_paise. EMITTED ONLY when the
    # customer has foreign activity, so an INR-only statement is byte-for-byte today's.
    attach_currency_outstanding(result, customer, events, end)
    return result


class CustomerStatementService:

    def _customer(self, db, firm_id, client_id, customer_id) -> dict:
        res = (db.table("customers").select("*")
               .eq("id", customer_id).eq("firm_id", firm_id).eq("client_id", client_id)
               .limit(1).execute())
        row = (res.data or [None])[0]
        if not row:
            raise HTTPException(status_code=404, detail="Customer not found for this client.")
        return row

    def generate(self, db, firm_id: str, client_id: str, customer_id: str,
                 start_date: str, end_date: str) -> dict:
        if end_date < start_date:
            raise HTTPException(status_code=422, detail="end_date must not precede start_date.")
        customer = self._customer(db, firm_id, client_id, customer_id)

        inv = (db.table("client_sales_invoices")
               .select("invoice_no, invoice_date, total_paise, status, txn_currency, exchange_rate, txn_total")
               .eq("firm_id", firm_id).eq("client_id", client_id).eq("customer_id", customer_id)
               .is_("deleted_at", "null").execute().data or [])
        invoices = [i for i in inv if (i.get("status") or "") not in _DEAD_INVOICE]

        receipts = (db.table("receipts")
                    .select("receipt_no, receipt_date, amount_paise, tds_paise, txn_currency, exchange_rate, txn_amount")
                    .eq("firm_id", firm_id).eq("client_id", client_id).eq("customer_id", customer_id)
                    .execute().data or [])

        cns = (db.table("credit_notes")
               .select("credit_note_no, credit_note_date, total_paise, status")
               .eq("firm_id", firm_id).eq("client_id", client_id).eq("customer_id", customer_id)
               .execute().data or [])
        credit_notes = [c for c in cns if (c.get("status") or "") not in _DEAD_CREDIT_NOTE]

        return build_statement(customer, start_date, end_date, invoices, receipts, credit_notes)

    def ar_aging(self, db, firm_id: str, client_id: str, as_of: Optional[str] = None) -> dict:
        """Client-scoped accounts-receivable aging (the AR mirror of ap_aging): per
        open invoice, outstanding = total − paid − credited, bucketed by age from
        due_date (or invoice_date). Adds dual-currency detail on FOREIGN invoices only
        and a per-currency breakdown, so an INR-only client's aging is unchanged.
        Base amounts stay authoritative and reconcile with the AR sub-ledger / GL."""
        today = date.fromisoformat(_d(as_of)) if as_of else datetime.now(timezone.utc).date()
        invs = (db.table("client_sales_invoices")
                .select("id, customer_id, invoice_no, invoice_date, due_date, total_paise, paid_paise, "
                        "credited_paise, status, txn_currency, exchange_rate, txn_total, paid_txn")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .is_("deleted_at", "null").execute().data or [])
        cnames = {c["id"]: c.get("name") for c in (db.table("customers").select("id, name")
                  .eq("firm_id", firm_id).eq("client_id", client_id).execute().data or [])}

        buckets = {"not_due": 0, "0-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
        rows, total = [], 0
        ccy_entries: list[tuple] = []
        for inv in invs:
            if (inv.get("status") or "") in _DEAD_INVOICE:
                continue
            outstanding = (int(inv.get("total_paise") or 0)
                           - int(inv.get("paid_paise") or 0) - int(inv.get("credited_paise") or 0))
            if outstanding <= 0:
                continue
            ref = inv.get("due_date") or inv.get("invoice_date")
            try:
                days = (today - date.fromisoformat(_d(ref))).days if ref else 0
            except (ValueError, TypeError):
                days = 0
            bucket = _aging_bucket(days)
            buckets[bucket] += outstanding
            total += outstanding
            row = {
                "invoice_id": inv.get("id"), "invoice_no": inv.get("invoice_no"),
                "customer_id": inv.get("customer_id"), "customer_name": cnames.get(inv.get("customer_id")),
                "invoice_date": _d(inv.get("invoice_date")), "outstanding_paise": outstanding,
                "days_overdue": max(days, 0), "aging_bucket": bucket,
            }
            cur = (inv.get("txn_currency") or "INR").upper()
            foreign_out = 0
            if cur != "INR":
                foreign_out = int(inv.get("txn_total") or 0) - int(inv.get("paid_txn") or 0)
                row["txn_currency"] = cur
                row["exchange_rate"] = str(inv.get("exchange_rate") or 1)
                row["outstanding_base_paise"] = outstanding
                row["outstanding_foreign_minor"] = foreign_out
            ccy_entries.append((cur, outstanding, foreign_out))
            rows.append(row)

        out = {"as_of": today.isoformat(), "buckets": buckets,
               "total_outstanding_paise": total, "invoices": rows}
        base_cur, by_ccy = summarize_by_currency(ccy_entries)
        if by_ccy is not None:
            out["base_currency"] = base_cur
            out["by_currency"] = by_ccy
        return out

    # ── email delivery tracking (mirrors invoice_deliveries) ───────────────────
    def record_delivery(self, db, firm_id, client_id, customer_id, start, end,
                        sent_to, actor_id, actor_email) -> str:
        row = (db.table("customer_statement_deliveries").insert({
            "firm_id": firm_id, "client_id": client_id, "customer_id": customer_id,
            "period_start": _d(start), "period_end": _d(end), "sent_to": sent_to,
            "sent_by_id": actor_id, "sent_by_email": actor_email, "status": "sending",
        }).execute().data or [{}])[0]
        return row.get("id")

    def finish_delivery(self, db, delivery_id, success, provider_id=None, error=None) -> None:
        update: dict = {"status": "sent" if success else "failed"}
        if provider_id:
            update["provider_message_id"] = provider_id
        if success:
            update["sent_at"] = _now()
        elif error:
            update["error_message"] = error[:200]
        db.table("customer_statement_deliveries").update(update).eq("id", delivery_id).execute()

    def deliveries(self, db, firm_id, client_id, customer_id) -> list[dict]:
        return (db.table("customer_statement_deliveries").select("*")
                .eq("firm_id", firm_id).eq("client_id", client_id).eq("customer_id", customer_id)
                .order("created_at", desc=True).execute().data or [])


customer_statement_service = CustomerStatementService()
