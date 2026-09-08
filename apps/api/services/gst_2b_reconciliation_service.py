"""
GSTR-2B reconciliation — read the books here, persist the answer (GST-04, PUR-11).

WHAT THIS REPLACES
    Two things that both looked like a reconciliation and were not.

    1. `POST /gst-workspace/gstr2b/upload` took the BOOKS side out of the same
       pasted JSON — `raw.get("book_invoices", [])` — and looked for
       `data.docDetails[]` keyed on `sgstin`, neither of which appears in a
       real GSTR-2B. So a CA who pasted a genuine download got "Matched 0,
       Mismatched 0, Missing 0": a clean result produced by comparing nothing
       against nothing.

    2. `/gst/reconciliation` matched in the BROWSER, over a purchase register
       the CA had to export from this product and upload back into it, and
       persisted nothing. Reopening it next month started from zero, and there
       was no way to see from the Purchases tab that a bill was unmatched.

    Nothing anywhere INSERTed into `gstr2a_records`, so every GSTR-3B ever
    computed printed `gstr2a_record_count: 0` in its Rule 36(4) working.

WHAT IT DOES INSTEAD
    Parses the real envelope (domain/gst/gstr2b), reads `purchase_bills` for
    the period SERVER-SIDE, matches with domain/gst/itc_matching, and writes one
    `gstr2a_records` row per portal document carrying its match, its `itcavl`
    flag and the bill it matched. The answer survives a refresh, and the
    Purchases tab can ask a bill whether the supplier filed it.

WHAT IS DELIBERATELY NOT AUTOMATIC
    Nothing is posted, no credit is claimed, and no return is changed. This
    reports; the CA decides. §16(2)(aa) makes the credit turn on what 2B says,
    and a piece of software that quietly reduced a client's claimed ITC because
    a supplier was late would be acting on a judgement that is not its to make.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from domain.gst.gstr2b import GSTR2BFile, parse_gstr2b
from domain.gst.itc_matching import (
    BookBill, PortalDocument, Reconciliation, defaulters, reconcile,
)

_logger = logging.getLogger("caflow.gst_2b_reconciliation")

#: A bill is on the books once it has been received. A draft is not a document
#: the supplier could have filed against, and a cancelled one is not a claim.
#: The same set gst_return_service uses for Table 4(A).
BILL_ON_THE_BOOKS = ("received", "partially_paid", "paid")


def _period_bounds(period: str) -> tuple[str, str]:
    """'MMYYYY' → (first_iso, last_iso). Deliberately a duplicate of
    gst_return_service._period_bounds rather than an import: this module must
    not drag the whole return engine in to get a date pair."""
    import calendar
    if len(period) != 6 or not period.isdigit():
        raise ValueError("period must be MMYYYY, e.g. 042025")
    mm, yyyy = int(period[:2]), int(period[2:])
    if not 1 <= mm <= 12:
        raise ValueError("period month must be 01-12")
    last = calendar.monthrange(yyyy, mm)[1]
    return f"{yyyy:04d}-{mm:02d}-01", f"{yyyy:04d}-{mm:02d}-{last:02d}"


def read_book_bills(db, firm_id: str, client_id: str, period: str) -> list[BookBill]:
    """The client's purchase bills for the period, with their supplier GSTIN.

    THE GSTIN IS ON THE VENDOR, not the bill, so it is joined here. A bill whose
    vendor has no GSTIN recorded cannot be matched to a portal document at all —
    it is kept, with an empty GSTIN, so it surfaces as missing_in_2b rather than
    disappearing. Dropping it would hide a bill from the one report that exists
    to find unfiled ones.
    """
    start, end = _period_bounds(period)
    rows = (db.table("purchase_bills")
            .select("id, vendor_id, bill_no, bill_date, taxable_amount_paise, "
                    "igst_paise, cgst_paise, sgst_paise, status")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("status", list(BILL_ON_THE_BOOKS))
            .is_("deleted_at", "null")
            .gte("bill_date", start).lte("bill_date", end)
            .execute().data) or []

    vendor_ids = sorted({r.get("vendor_id") for r in rows if r.get("vendor_id")})
    gstins: dict[str, str] = {}
    for i in range(0, len(vendor_ids), 200):
        got = (db.table("vendors").select("id, gstin")
               .eq("firm_id", firm_id).in_("id", vendor_ids[i:i + 200])
               .execute().data) or []
        gstins.update({v["id"]: (v.get("gstin") or "").strip().upper() for v in got})

    return [
        BookBill(
            bill_id=str(r["id"]),
            supplier_gstin=gstins.get(r.get("vendor_id"), ""),
            bill_no=r.get("bill_no") or "",
            bill_date=str(r.get("bill_date") or "") or None,
            taxable_paise=int(r.get("taxable_amount_paise") or 0),
            igst_paise=int(r.get("igst_paise") or 0),
            cgst_paise=int(r.get("cgst_paise") or 0),
            sgst_paise=int(r.get("sgst_paise") or 0),
        )
        for r in rows
    ]


def _portal_documents(parsed: GSTR2BFile) -> list[PortalDocument]:
    return [
        PortalDocument(
            section=d.section,
            document_type=d.document_type,
            supplier_gstin=d.supplier_gstin,
            supplier_name=d.supplier_name,
            document_number=d.document_number,
            document_date=d.document_date,
            taxable_paise=d.taxable_value_paise,
            igst_paise=d.igst_paise,
            cgst_paise=d.cgst_paise,
            sgst_paise=d.sgst_paise,
            cess_paise=d.cess_paise,
            itc_available=d.itc_available,
        )
        for d in parsed.documents
    ]


def _record_rows(firm_id: str, client_id: str, period: str,
                 parsed: GSTR2BFile, rec: Reconciliation) -> list[dict]:
    """One gstr2a_records row per PORTAL document.

    Per portal document and not per match: the table is the portal's side of
    the reconciliation, and a bill the supplier never filed has no document to
    be a row of. `missing_in_2b` lives on the bill instead, and the screen and
    the defaulter list read it off the reconciliation.
    """
    by_number: dict[tuple[str, str, str], object] = {}
    for m in rec.matches:
        if m.document is not None:
            by_number[(m.document.section, m.document.supplier_gstin,
                       m.document.document_number)] = m

    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for d in parsed.documents:
        m = by_number.get((d.section, d.supplier_gstin, d.document_number))
        rows.append({
            "firm_id": firm_id,
            "client_id": client_id,
            "return_period": period,
            "section": d.section,
            "document_type": d.document_type,
            "supplier_gstin": d.supplier_gstin,
            "supplier_name": d.supplier_name,
            "supplier_trade_name": d.supplier_name,
            "invoice_number": d.document_number,
            "invoice_date": d.document_date,
            "taxable_value_paise": d.taxable_value_paise,
            "igst_paise": d.igst_paise,
            "cgst_paise": d.cgst_paise,
            "sgst_paise": d.sgst_paise,
            "cess_paise": d.cess_paise,
            "invoice_value_paise": d.invoice_value_paise,
            "itc_available": d.itc_available,
            "itc_unavailable_reason_code": d.itc_unavailable_reason_code,
            "itc_unavailable_reason": d.itc_unavailable_reason,
            "supplier_filed_on": d.supplier_filed_on,
            "is_amendment": d.is_amendment,
            "amends_document_number": d.amends_document_number,
            "source": "upload",
            "purchase_bill_id": getattr(m, "bill_id", None) if m else None,
            "match_status": getattr(m, "status", "unmatched") if m else "unmatched",
            "match_difference_paise": getattr(m, "difference_paise", 0) if m else 0,
            "reconciled_at": now,
            "updated_at": now,
        })
    return rows


def reconcile_2b(db, *, firm_id: str, client_id: str, period: str,
                 raw: object) -> dict:
    """Parse, match against the books, persist, and answer.

    Returns the whole picture rather than a count: the four buckets, the
    defaulter list, and the ITC figures §16(2)(aa) actually turns on. A summary
    of "Matched 12" is not an answer to "how much credit may I take".
    """
    parsed = parse_gstr2b(raw)
    if not parsed.documents:
        # An empty parse is REPORTED, never persisted. Writing zero rows and
        # calling it reconciled is exactly the false clean result this replaces.
        return {
            "period": period,
            "gstin": parsed.gstin,
            "return_period_in_file": parsed.return_period,
            "generated_on": parsed.generated_on,
            "sections_seen": parsed.sections_seen,
            "problems": parsed.problems,
            "persisted": False,
            "summary": None,
            "matches": [],
            "defaulters": [],
        }

    bills = read_book_bills(db, firm_id, client_id, period)
    rec = reconcile(bills, _portal_documents(parsed))
    rows = _record_rows(firm_id, client_id, period, parsed, rec)

    # Replace, do not accumulate. A CA re-uploads when the first download was
    # for the wrong month, and two runs of the same 2B must not double the
    # credit the Rule 36(4) working reads back.
    (db.table("gstr2a_records")
       .delete().eq("firm_id", firm_id).eq("client_id", client_id)
       .eq("return_period", period).execute())
    for i in range(0, len(rows), 500):
        db.table("gstr2a_records").insert(rows[i:i + 500]).execute()

    problems = list(parsed.problems)
    if parsed.return_period and parsed.return_period != period:
        problems.append(
            f"This file is GSTR-2B for {parsed.return_period} and you are "
            f"reconciling {period}. The documents below were matched against "
            f"{period}'s bills, which is almost certainly not what you meant.")

    return {
        "period": period,
        "gstin": parsed.gstin,
        "return_period_in_file": parsed.return_period,
        "generated_on": parsed.generated_on,
        "sections_seen": parsed.sections_seen,
        "problems": problems,
        "persisted": True,
        "book_bill_count": len(bills),
        "portal_document_count": len(parsed.documents),
        "summary": rec.summary(),
        "matches": [_match_json(m) for m in rec.matches],
        "defaulters": defaulters(rec),
    }


def _match_json(m) -> dict:
    d, b = m.document, m.bill
    return {
        "status": m.status,
        "reason": m.reason,
        "difference_paise": m.difference_paise,
        "bill_id": m.bill_id,
        "bill_no": b.bill_no if b else None,
        "bill_date": b.bill_date if b else None,
        "book_taxable_paise": b.taxable_paise if b else None,
        "book_tax_paise": b.tax_paise if b else None,
        "supplier_gstin": (d.supplier_gstin if d else (b.supplier_gstin if b else "")),
        "supplier_name": d.supplier_name if d else None,
        "document_number": d.document_number if d else (b.bill_no if b else None),
        "document_date": d.document_date if d else None,
        "document_type": d.document_type if d else None,
        "portal_taxable_paise": d.taxable_paise if d else None,
        "portal_tax_paise": d.tax_paise if d else None,
        "itc_available": d.itc_available if d else None,
    }


def read_reconciliation(db, *, firm_id: str, client_id: str, period: str) -> dict:
    """What was persisted, for a screen reopening next month.

    The whole point of persisting: the browser reconciliation this replaces
    started from zero every time it was opened.
    """
    rows = (db.table("gstr2a_records").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("return_period", period).execute().data) or []
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.get("match_status") or "unmatched"] = counts.get(
            r.get("match_status") or "unmatched", 0) + 1
    return {
        "period": period,
        "record_count": len(rows),
        "by_status": counts,
        "records": rows,
    }


def status_for_bills(db, *, firm_id: str, client_id: str,
                     bill_ids: list[str]) -> dict[str, dict]:
    """{bill_id: the 2B row that matched it}, for the Purchases tab.

    A bill with no entry here has not been reconciled OR was not filed by its
    supplier, and those are different — which is why the caller is given the
    row rather than a boolean.
    """
    if not bill_ids:
        return {}
    out: dict[str, dict] = {}
    for i in range(0, len(bill_ids), 200):
        rows = (db.table("gstr2a_records")
                .select("purchase_bill_id, return_period, match_status, "
                        "match_difference_paise, itc_available, "
                        "itc_unavailable_reason, supplier_filed_on")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .in_("purchase_bill_id", bill_ids[i:i + 200])
                .execute().data) or []
        for r in rows:
            if r.get("purchase_bill_id"):
                out[str(r["purchase_bill_id"])] = r
    return out
