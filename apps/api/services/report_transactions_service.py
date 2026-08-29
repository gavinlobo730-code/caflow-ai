"""
The unified transaction feed the reporting screens read.

WHY THIS EXISTS
    /reports and /client-portal used to read a `transactions` table: one row per
    sale or purchase, with party, tax split and status on it. Migration 139
    dropped that table as an abandoned parallel model — correctly, the live
    double-entry books are journal_entries + journal_lines — but the two screens
    were never moved, so both have been failing on a missing relation since.

    There is no single live table to point them at. A sale is a row in
    client_sales_invoices and a purchase is a row in purchase_bills, with
    different column names for the same ideas (invoice_no vs bill_no, invoice_date
    vs bill_date) and different parties (customers vs vendors). Something has to
    decide what "a transaction" means now. That decision belongs here rather than
    in the browser — CLAUDE.md, zero business logic in the frontend — so the two
    screens, and anything built on them later, agree by construction.

WHAT COUNTS AS A TRANSACTION
    * A sales invoice that is not a draft and not cancelled.
    * A purchase bill that is not cancelled.
    * Never a soft-deleted row (deleted_at IS NULL) on either side.

    Drafts are excluded because an unissued invoice is not yet a transaction with
    anyone; it has no counterparty obligation and including it would overstate
    turnover in the P&L report. Cancelled rows are excluded for the same reason
    in reverse. Both are decisions, not facts — they are stated here, asserted in
    tests, and easy to change in one place.

MONEY
    Every amount stays in integer paise, end to end (CLAUDE.md). Nothing here
    divides by 100; formatting is the caller's job.
"""
from typing import Any, Optional


# Statuses that represent a real transaction, per source table. Kept as explicit
# sets rather than "not draft" so that a NEW status added to either table fails
# closed — it is excluded until someone decides where it belongs.
_SALES_COUNTED = {"issued"}
_PURCHASE_COUNTED = {"received"}


def _party_names(db, table: str, ids: set[str], firm_id: str) -> dict[str, str]:
    """id -> display name for customers/vendors, fetched in one round trip.

    Firm-scoped even though the ids came from firm-scoped rows: a stray id from
    another firm must not turn into a name.
    """
    if not ids:
        return {}
    rows = (db.table(table).select("id, name")
            .eq("firm_id", firm_id)
            .in_("id", list(ids)).execute().data) or []
    return {str(r["id"]): (r.get("name") or "") for r in rows}


def _outstanding(total: int, paid: int) -> int:
    """What is still owed on a row, floored at zero.

    Floored because an overpayment (paid > total, which happens with advances
    applied against a smaller invoice) must not appear as a NEGATIVE outstanding
    amount that then cancels out someone else's genuine debt in a total.
    """
    return max(0, int(total or 0) - int(paid or 0))


def list_transactions(db, firm_id: str, *, client_ids: Optional[list[str]] = None,
                      date_from: Optional[str] = None,
                      date_to: Optional[str] = None) -> list[dict[str, Any]]:
    """Sales invoices and purchase bills as one list, newest first.

    `client_ids` None means every client in the firm; the caller is responsible
    for having narrowed it to the caller's assigned clients first.
    """
    # Checked BEFORE any query is built: a caller assigned to zero clients gets
    # an empty list, and touching the tables at all would be wasted work whose
    # only possible outcome is []. Also guards against `.in_("client_id", [])`,
    # whose behaviour on an empty list is not something to depend on when the
    # wrong answer is "every client in the firm".
    if client_ids is not None and not client_ids:
        return []

    sales_q = (db.table("client_sales_invoices")
               .select("id, client_id, customer_id, invoice_no, reference_no, invoice_date, "
                       "is_interstate, supply_state_code, taxable_amount_paise, cgst_paise, "
                       "sgst_paise, igst_paise, total_paise, paid_paise, status")
               .eq("firm_id", firm_id).is_("deleted_at", "null")
               .in_("status", sorted(_SALES_COUNTED)))
    bills_q = (db.table("purchase_bills")
               .select("id, client_id, vendor_id, bill_no, our_reference, bill_date, "
                       "is_interstate, taxable_amount_paise, cgst_paise, sgst_paise, "
                       "igst_paise, total_paise, paid_paise, tds_paise, tds_section, status")
               .eq("firm_id", firm_id).is_("deleted_at", "null")
               .in_("status", sorted(_PURCHASE_COUNTED)))

    if client_ids is not None:
        sales_q = sales_q.in_("client_id", client_ids)
        bills_q = bills_q.in_("client_id", client_ids)
    if date_from:
        sales_q = sales_q.gte("invoice_date", date_from)
        bills_q = bills_q.gte("bill_date", date_from)
    if date_to:
        sales_q = sales_q.lte("invoice_date", date_to)
        bills_q = bills_q.lte("bill_date", date_to)

    sales = sales_q.execute().data or []
    bills = bills_q.execute().data or []

    customers = _party_names(db, "customers",
                             {str(r["customer_id"]) for r in sales if r.get("customer_id")},
                             firm_id)
    vendors = _party_names(db, "vendors",
                           {str(r["vendor_id"]) for r in bills if r.get("vendor_id")},
                           firm_id)

    out: list[dict[str, Any]] = []
    for r in sales:
        total, paid = r.get("total_paise") or 0, r.get("paid_paise") or 0
        out.append({
            "id": str(r["id"]),
            "client_id": str(r.get("client_id") or ""),
            # The old vocabulary is kept deliberately: the reporting screens
            # split on these exact strings, and renaming them here would be a
            # silent behaviour change dressed up as a rename.
            "transaction_type": "sales_invoice",
            "transaction_date": r.get("invoice_date"),
            "reference_no": r.get("reference_no") or r.get("invoice_no"),
            "party_name": customers.get(str(r.get("customer_id") or ""), ""),
            "taxable_amount_paise": r.get("taxable_amount_paise") or 0,
            "cgst_paise": r.get("cgst_paise") or 0,
            "sgst_paise": r.get("sgst_paise") or 0,
            "igst_paise": r.get("igst_paise") or 0,
            # Sales carry no TDS of their own here: TDS on a sale is deducted by
            # the CUSTOMER and tracked against their payment, not on the invoice.
            "tds_paise": 0,
            "total_paise": total,
            "paid_paise": paid,
            "outstanding_paise": _outstanding(total, paid),
            "is_interstate": bool(r.get("is_interstate")),
            "place_of_supply": r.get("supply_state_code"),
            "status": r.get("status"),
        })
    for r in bills:
        total, paid = r.get("total_paise") or 0, r.get("paid_paise") or 0
        out.append({
            "id": str(r["id"]),
            "client_id": str(r.get("client_id") or ""),
            "transaction_type": "purchase_invoice",
            "transaction_date": r.get("bill_date"),
            "reference_no": r.get("our_reference") or r.get("bill_no"),
            "party_name": vendors.get(str(r.get("vendor_id") or ""), ""),
            "taxable_amount_paise": r.get("taxable_amount_paise") or 0,
            "cgst_paise": r.get("cgst_paise") or 0,
            "sgst_paise": r.get("sgst_paise") or 0,
            "igst_paise": r.get("igst_paise") or 0,
            "tds_paise": r.get("tds_paise") or 0,
            "tds_section": r.get("tds_section"),
            "total_paise": total,
            "paid_paise": paid,
            "outstanding_paise": _outstanding(total, paid),
            "is_interstate": bool(r.get("is_interstate")),
            "place_of_supply": None,
            "status": r.get("status"),
        })

    # Newest first, matching the order the old query asked Postgres for. A stable
    # tiebreak on id keeps the list from reshuffling between identical dates,
    # which would make a report look different on every refresh.
    out.sort(key=lambda t: (t["transaction_date"] or "", t["id"]), reverse=True)
    return out


def gst_summary(db, firm_id: str, client_id: str, month: str) -> dict[str, Any]:
    """GSTR-1 / GSTR-3B figures for one client-month — the SAME figures the
    return itself computes, plus the documents behind outward supplies.

    WHY THIS NO LONGER DOES ITS OWN ARITHMETIC
        It used to sum client_sales_invoices and purchase_bills directly and
        subtract per head. That produced a second, quieter GST summary that
        could disagree with the one a CA files from, in at least four ways:

          * it ignored credit and debit notes entirely, on both sides, so any
            month with a CGST §34 note overstated output tax;
          * "net" was a raw per-head difference, not the §49(5) set-off, so it
            could show tax payable on one head while credit sat unused on
            another;
          * it never reconciled to the General Ledger, which is the whole point
            of the from-books path;
          * it keyed on a calendar month while the return keys on MMYYYY, so
            even the period could differ.

        Two GST summaries in one product is worse than one imperfect summary: a
        CA who notices the difference cannot tell which is wrong, and one of
        them is what they filed. So this now DELEGATES. There is one
        computation of GST figures in this codebase and this is a view of it.

    `month` stays 'YYYY-MM' because that is what the reports screen sends; it is
    converted to the return's MMYYYY here rather than at the caller.
    """
    import services.gst_return_service as gst_return_service

    y, m = (int(p) for p in month.split("-", 1))
    period = f"{m:02d}{y:04d}"

    gstin = ""
    try:
        rows = (db.table("clients").select("gstin")
                .eq("firm_id", firm_id).eq("id", client_id).limit(1).execute().data) or []
        gstin = (rows[0].get("gstin") or "") if rows else ""
    except Exception:  # noqa: BLE001 — a missing GSTIN must not fail the report
        gstin = ""

    r = gst_return_service.gstr3b_from_books(db, firm_id, client_id, period, gstin)
    w = r["working"]
    out, itc, net = w["outward"], w["itc"], w["net_payable"]

    out_igst = int(out.get("taxable_igst_paise") or 0)
    out_cgst = int(out.get("taxable_cgst_paise") or 0)
    out_sgst = int(out.get("taxable_sgst_paise") or 0)
    taxable = int(out.get("taxable_value_paise") or 0)

    # Table 4(C) — the credit actually claimed, net of the 4(B) reversals. The
    # gross 4(A) would overstate what this month's return may use.
    itc_igst = int(itc.get("net_igst_paise") or 0)
    itc_cgst = int(itc.get("net_cgst_paise") or 0)
    itc_sgst = int(itc.get("net_sgst_paise") or 0)

    # The documents behind outward supplies — the detail half, from the same
    # fetchers, so the listing sums to the figure above it.
    detail = gst_return_service.gstr3b_detail(db, firm_id, client_id, period, "3.1a")

    return {
        "period": month,
        "return_period": period,
        "source": "posted_general_ledger",
        # CGST Act Section 37 — outward supplies.
        "gstr1": {
            "taxable": taxable,
            "cgst": out_cgst, "sgst": out_sgst, "igst": out_igst,
            "total": taxable + out_cgst + out_sgst + out_igst,
            "lines": detail["rows"],
        },
        # CGST Act Section 39 — summary return.
        "gstr3b": {
            "output_cgst": out_cgst, "output_sgst": out_sgst, "output_igst": out_igst,
            "itc_cgst": itc_cgst, "itc_sgst": itc_sgst, "itc_igst": itc_igst,
            # The §49(5) set-off, not a per-head subtraction — IGST credit is
            # used against IGST first and then cross-utilised, so a raw
            # difference can show tax payable on a head whose liability the
            # return actually discharges from another head's credit.
            "net_cgst": int(net.get("cgst_paise") or 0),
            "net_sgst": int(net.get("sgst_paise") or 0),
            "net_igst": int(net.get("igst_paise") or 0),
            # Nil tax payable is true both when liability and credit cancel out
            # and when credit exceeds liability by lakhs. This says which.
            "itc_carried_forward": int(r.get("itc_carried_forward_paise") or 0),
        },
        # Proof the figures above tie to the ledger, which the old arithmetic
        # could not offer at all.
        "reconciliation": r.get("reconciliation"),
        "tds_deducted": _tds_for_month(db, firm_id, client_id, month),
        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. A working view of the return,
        # not a filed one.
        "ca_review_required": True,
    }


def _tds_for_month(db, firm_id: str, client_id: str, month: str) -> int:
    """TDS deducted on purchases in the month.

    Not part of the GST return, and so not something gstr3b_from_books computes
    — it is carried on the same bills and the reports screen shows it alongside.
    Summed here rather than dropped, because removing a figure a screen already
    shows is a different change from correcting the ones that were wrong.
    """
    y, m = (int(p) for p in month.split("-", 1))
    end_y, end_m = (y + 1, 1) if m == 12 else (y, m + 1)
    rows = list_transactions(db, firm_id, client_ids=[client_id],
                             date_from=f"{y:04d}-{m:02d}-01")
    return sum(int(r.get("tds_paise") or 0) for r in rows
               if r["transaction_type"] == "purchase_invoice"
               and (r["transaction_date"] or "") < f"{end_y:04d}-{end_m:02d}-01")
