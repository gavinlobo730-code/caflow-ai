"""
GST return service — derives GSTR-1 and GSTR-3B ENTIRELY from posted accounting
data (the sub-ledger of posted invoices/bills that backs the General Ledger), and
reconciles the computed tax to the GL GST control accounts.

Single source of truth (audit H8): returns are NEVER computed from frontend
payloads. The flow is:

    posted invoices / bills   →   domain GST computers   →   GSTR-1 / GSTR-3B
            │
            └── the SAME documents posted the journal entries, so the return's
                output tax must equal the credit movement on gst_cgst/gst_sgst/
                gst_igst and its ITC must equal the debit movement on gst_input.
                gstr3b_from_books returns that reconciliation as proof.

Integer paise throughout. # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
"""
from __future__ import annotations

import calendar
from datetime import date

from domain.gst.gstr3b_computer import (
    SalesTransaction, PurchaseTransaction, compute_gstr3b,
)
from domain.gst.gstr1_builder import InvoiceForGSTR1, build_gstr1
from domain.gst.classifier import classify_transaction, TransactionForClassification

# Posted (on-books) document statuses. Drafts are off-books; cancelled documents
# have an equal-and-opposite reversal in the GL, so excluding them here keeps books
# and ledger in step.
_SALES_POSTED = ("issued", "partially_paid", "paid")
_BILL_POSTED = ("received", "partially_paid", "paid")


def _period_bounds(period: str) -> tuple[str, str]:
    """'MMYYYY' → (first_iso, last_iso) for that calendar month."""
    if len(period) != 6 or not period.isdigit():
        raise ValueError("period must be MMYYYY")
    mm, yyyy = int(period[:2]), int(period[2:])
    if not 1 <= mm <= 12:
        raise ValueError("period month must be 01-12")
    last = calendar.monthrange(yyyy, mm)[1]
    return f"{yyyy:04d}-{mm:02d}-01", f"{yyyy:04d}-{mm:02d}-{last:02d}"


def _gl_gst_movements(db, firm_id: str, client_id: str, start: str, end: str) -> dict:
    """Net GST movements in the General Ledger for the period, by control account.

    Output tax = net CREDIT on gst_cgst/gst_sgst/gst_igst (sales credit, credit-note
    reversals debit). ITC = net DEBIT on gst_input. Reads posted journal_lines only.
    """
    coa = (db.table("chart_of_accounts").select("id, system_account_key")
           .eq("firm_id", firm_id).eq("client_id", client_id).execute().data) or []
    key_by_id = {c["id"]: c.get("system_account_key") for c in coa}
    out_ids = {c["id"] for c in coa if c.get("system_account_key") in ("gst_cgst", "gst_sgst", "gst_igst")}
    in_ids = {c["id"] for c in coa if c.get("system_account_key") == "gst_input"}

    entries = (db.table("journal_entries").select("id, entry_date, is_posted")
               .eq("firm_id", firm_id).eq("client_id", client_id)
               .gte("entry_date", start).lte("entry_date", end).execute().data) or []
    posted_ids = {e["id"] for e in entries if e.get("is_posted", True)}
    if not posted_ids:
        return {"output_paise": 0, "itc_paise": 0, "by_head": {}}

    lines = (db.table("journal_lines").select("journal_entry_id, account_id, debit_paise, credit_paise")
             .in_("journal_entry_id", list(posted_ids)).execute().data) or []

    by_head = {"cgst": 0, "sgst": 0, "igst": 0, "input": 0}
    output_paise = 0
    itc_paise = 0
    for l in lines:
        acc = l.get("account_id")
        dr = int(l.get("debit_paise") or 0)
        cr = int(l.get("credit_paise") or 0)
        if acc in out_ids:
            output_paise += cr - dr                 # liability is a credit balance
            head = (key_by_id.get(acc) or "").replace("gst_", "")
            by_head[head] = by_head.get(head, 0) + (cr - dr)
        elif acc in in_ids:
            itc_paise += dr - cr                     # ITC is a debit balance
            by_head["input"] += dr - cr
    return {"output_paise": output_paise, "itc_paise": itc_paise, "by_head": by_head}


def _posted_sales(db, firm_id, client_id, start, end) -> list[dict]:
    return (db.table("client_sales_invoices").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("status", list(_SALES_POSTED))
            .gte("invoice_date", start).lte("invoice_date", end).execute().data) or []


def _issued_credit_notes(db, firm_id, client_id, start, end) -> list[dict]:
    return (db.table("credit_notes").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("status", "issued")
            .gte("credit_note_date", start).lte("credit_note_date", end).execute().data) or []


def _posted_bills(db, firm_id, client_id, start, end) -> list[dict]:
    return (db.table("purchase_bills").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("status", list(_BILL_POSTED))
            .gte("bill_date", start).lte("bill_date", end).execute().data) or []


def _issued_debit_notes(db, firm_id, client_id, start, end) -> list[dict]:
    return (db.table("debit_notes").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("status", "issued")
            .gte("debit_note_date", start).lte("debit_note_date", end).execute().data) or []


def gstr3b_from_books(db, firm_id: str, client_id: str, period: str, gstin: str) -> dict:
    """Compute GSTR-3B from posted books and reconcile to the General Ledger."""
    start, end = _period_bounds(period)

    sales: list[SalesTransaction] = []
    for inv in _posted_sales(db, firm_id, client_id, start, end):
        sales.append(SalesTransaction(
            transaction_type="sales_invoice",
            taxable_amount_paise=int(inv.get("taxable_amount_paise") or 0),
            cgst_paise=int(inv.get("cgst_paise") or 0),
            sgst_paise=int(inv.get("sgst_paise") or 0),
            igst_paise=int(inv.get("igst_paise") or 0),
            cess_paise=int(inv.get("cess_paise") or 0),
            supply_type=inv.get("supply_type") or "taxable",
            is_reverse_charge=bool(inv.get("is_reverse_charge", False)),
        ))
    for cn in _issued_credit_notes(db, firm_id, client_id, start, end):
        sales.append(SalesTransaction(
            transaction_type="credit_note",
            taxable_amount_paise=int(cn.get("taxable_amount_paise") or 0),
            cgst_paise=int(cn.get("cgst_paise") or 0),
            sgst_paise=int(cn.get("sgst_paise") or 0),
            igst_paise=int(cn.get("igst_paise") or 0),
            cess_paise=int(cn.get("cess_paise") or 0),
            supply_type=cn.get("supply_type") or "taxable",
            is_reverse_charge=bool(cn.get("is_reverse_charge", False)),
        ))

    purchases: list[PurchaseTransaction] = []
    for b in _posted_bills(db, firm_id, client_id, start, end):
        purchases.append(PurchaseTransaction(
            taxable_amount_paise=int(b.get("taxable_amount_paise") or 0),
            cgst_paise=int(b.get("cgst_paise") or 0),
            sgst_paise=int(b.get("sgst_paise") or 0),
            igst_paise=int(b.get("igst_paise") or 0),
            cess_paise=int(b.get("cess_paise") or 0),
            is_reverse_charge=bool(b.get("is_reverse_charge", False)),
        ))
    # Debit notes (purchase returns) REVERSE ITC — they credit gst_input in the GL, so
    # the return's ITC must net them or it over-claims (mirror of credit notes reducing
    # output tax). Fed as negative-tax purchases so book ITC nets them.
    for dn in _issued_debit_notes(db, firm_id, client_id, start, end):
        purchases.append(PurchaseTransaction(
            taxable_amount_paise=-int(dn.get("taxable_amount_paise") or 0),
            cgst_paise=-int(dn.get("cgst_paise") or 0),
            sgst_paise=-int(dn.get("sgst_paise") or 0),
            igst_paise=-int(dn.get("igst_paise") or 0),
            cess_paise=-int(dn.get("cess_paise") or 0),
            is_reverse_charge=bool(dn.get("is_reverse_charge", False)),
        ))

    result = compute_gstr3b(sales, purchases, [])

    # ── Reconcile the return to the posted General Ledger ─────────────────────
    gl = _gl_gst_movements(db, firm_id, client_id, start, end)
    books_output = result.outward_taxable_cgst + result.outward_taxable_sgst + result.outward_taxable_igst
    books_itc = result.itc_book_cgst + result.itc_book_sgst + result.itc_book_igst
    output_matched = books_output == gl["output_paise"]
    itc_matched = books_itc == gl["itc_paise"]

    return {
        "period": period,
        "gstin": gstin,
        "source": "posted_general_ledger",
        "payload": result.as_gstn_payload(gstin, period),
        "working": {
            "outward": {
                "taxable_value_paise": result.outward_taxable_value,
                "taxable_cgst_paise": result.outward_taxable_cgst,
                "taxable_sgst_paise": result.outward_taxable_sgst,
                "taxable_igst_paise": result.outward_taxable_igst,
                "zero_rated_paise": result.outward_zero_rated,
                "nil_exempt_paise": result.outward_nil_exempt,
            },
            "rcm_inward": {
                "cgst_paise": result.rcm_cgst,
                "sgst_paise": result.rcm_sgst,
                "igst_paise": result.rcm_igst,
            },
            "itc": {
                "cgst_paise": result.itc_book_cgst,
                "sgst_paise": result.itc_book_sgst,
                "igst_paise": result.itc_book_igst,
            },
        },
        "reconciliation": {
            "output_gst": {
                "books_paise": books_output,
                "ledger_paise": gl["output_paise"],
                "difference_paise": books_output - gl["output_paise"],
                "matched": output_matched,
            },
            "itc": {
                "books_paise": books_itc,
                "ledger_paise": gl["itc_paise"],
                "difference_paise": books_itc - gl["itc_paise"],
                "matched": itc_matched,
            },
            "reconciled": output_matched and itc_matched,
            "ledger_by_head": gl["by_head"],
        },
        "ca_review_required": True,   # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    }


def gstr1_from_books(db, firm_id: str, client_id: str, period: str, gstin: str,
                     aggregate_turnover_paise: int = 0) -> dict:
    """Build GSTR-1 from posted sales invoices + issued credit notes, and reconcile
    the total output tax to the General Ledger GST-output control accounts."""
    start, end = _period_bounds(period)

    invoices_raw = _posted_sales(db, firm_id, client_id, start, end)
    cns_raw = _issued_credit_notes(db, firm_id, client_id, start, end)

    # Resolve customer GSTIN / name / place of supply (no nested select — join here).
    cust_ids = {r.get("customer_id") for r in (invoices_raw + cns_raw) if r.get("customer_id")}
    cust_by_id: dict = {}
    if cust_ids:
        rows = (db.table("customers").select("id, name, gstin, state_code")
                .eq("firm_id", firm_id).in_("id", list(cust_ids)).execute().data) or []
        cust_by_id = {c["id"]: c for c in rows}

    def _to_gstr1(r: dict, is_cn: bool) -> InvoiceForGSTR1:
        cust = cust_by_id.get(r.get("customer_id"), {})
        gstin_party = cust.get("gstin")
        pos = r.get("supply_state_code") or cust.get("state_code") or ""
        txn = TransactionForClassification(
            id=r.get("id", ""),
            transaction_type="credit_note" if is_cn else "sales_invoice",
            party_gstin=gstin_party,
            is_interstate=bool(r.get("is_interstate", False)),
            taxable_amount_paise=int(r.get("taxable_amount_paise") or 0),
            supply_type=r.get("supply_type") or "taxable",
            invoice_type="Regular",
            place_of_supply=pos,
        )
        return InvoiceForGSTR1(
            id=r.get("id", ""),
            transaction_type="credit_note" if is_cn else "sales_invoice",
            reference_no=(r.get("credit_note_no") if is_cn else r.get("invoice_no")) or "",
            transaction_date=(r.get("credit_note_date") if is_cn else r.get("invoice_date")) or "",
            party_gstin=gstin_party,
            party_name=cust.get("name") or "",
            place_of_supply=pos,
            is_interstate=bool(r.get("is_interstate", False)),
            taxable_amount_paise=int(r.get("taxable_amount_paise") or 0),
            cgst_paise=int(r.get("cgst_paise") or 0),
            sgst_paise=int(r.get("sgst_paise") or 0),
            igst_paise=int(r.get("igst_paise") or 0),
            cess_paise=int(r.get("cess_paise") or 0),
            is_reverse_charge=bool(r.get("is_reverse_charge", False)),
            invoice_type="Regular",
            supply_type=r.get("supply_type") or "taxable",
            gst_invoice_category=classify_transaction(txn),
            original_invoice_ref=r.get("sales_invoice_id") if is_cn else None,
            original_invoice_date=None,
            lines=[],
        )

    invoices = [_to_gstr1(r, False) for r in invoices_raw] + [_to_gstr1(r, True) for r in cns_raw]
    payload = build_gstr1(invoices, gstin, period, aggregate_turnover_paise)

    # Reconcile output tax to the GL. GSTR-1 tax total is gross (before credit notes);
    # compare against sales-only GST in the GL (credit notes are the CDNR reduction).
    gl = _gl_gst_movements(db, firm_id, client_id, start, end)
    inv_output = sum(int(r.get("cgst_paise") or 0) + int(r.get("sgst_paise") or 0)
                     + int(r.get("igst_paise") or 0) for r in invoices_raw)
    cn_output = sum(int(r.get("cgst_paise") or 0) + int(r.get("sgst_paise") or 0)
                    + int(r.get("igst_paise") or 0) for r in cns_raw)
    net_books_output = inv_output - cn_output

    return {
        "period": period,
        "gstin": gstin,
        "source": "posted_general_ledger",
        "payload": payload.payload,
        "summary": payload.summary,
        "invoice_count": payload.invoice_count,
        "taxable_total_paise": payload.taxable_total_paise,
        "tax_total_paise": payload.tax_total_paise,
        "reconciliation": {
            "net_output_gst": {
                "books_paise": net_books_output,
                "ledger_paise": gl["output_paise"],
                "difference_paise": net_books_output - gl["output_paise"],
                "matched": net_books_output == gl["output_paise"],
            },
            "reconciled": net_books_output == gl["output_paise"],
        },
        "ca_review_required": True,   # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    }
