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


def _paginate_all(make_query, key: str = "id", page: int = 1000) -> list:
    """Fetch EVERY row via keyset paging on `key`.

    An un-paged `.execute()` is silently capped at PostgREST's ~1000-row limit.
    Eleven other services in this codebase carry this helper and this module
    shipped without it, so `read_book_bills` truncated a busy month's purchase
    register — and every 2B document belonging to a dropped bill was then
    reported as `missing_in_books`, telling the CA to chase a document they
    already hold. `read_reconciliation` truncated the answer the screen reads
    back.

    Test doubles that do not implement order/limit/gt return their whole (small)
    fixture from one execute(), which is already correct.
    """
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
    rows = _paginate_all(lambda: db.table("purchase_bills")
            .select("id, vendor_id, bill_no, bill_date, taxable_amount_paise, "
                    "igst_paise, cgst_paise, sgst_paise, status")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("status", list(BILL_ON_THE_BOOKS))
            .is_("deleted_at", "null")
            .gte("bill_date", start).lte("bill_date", end))

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

    # A FILE THAT IS NOT A 2B IS REPORTED AND NEVER PERSISTED. Writing zero rows
    # and calling it reconciled is exactly the false clean result this module
    # replaces. `docdata_seen` is the test, not `documents` — see below.
    if not parsed.docdata_seen:
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

    # A 2B THAT PARSED AND CARRIES NO DOCUMENTS IS AN ANSWER, and it is recorded.
    # It means nobody the client bought from filed anything for the month, which
    # under §16(2)(aa) means NO input credit is available — the single most
    # consequential thing this reconciliation can discover. Treating it as "not
    # reconciled", which is what the first version did by returning early here,
    # left Rule 36(4) uncapped and let the return claim the whole book ITC.
    bills = read_book_bills(db, firm_id, client_id, period)
    rec = reconcile(bills, _portal_documents(parsed))
    rows = _record_rows(firm_id, client_id, period, parsed, rec)

    problems = list(parsed.problems)
    if parsed.return_period and parsed.return_period != period:
        problems.append(
            f"This file is GSTR-2B for {parsed.return_period} and you are "
            f"reconciling {period}. The documents below were matched against "
            f"{period}'s bills, which is almost certainly not what you meant.")

    # Replace, do not accumulate. A CA re-uploads when the first download was
    # for the wrong month, and two runs of the same 2B must not double the
    # credit the Rule 36(4) working reads back.
    #
    # THE HEADER IS WRITTEN EVEN WHEN `rows` IS EMPTY, and that is the point of
    # it: it is the only record that this period was reconciled at all, and
    # everything downstream — the Rule 36(4) cap, the Purchases column, the
    # read-back — asks it rather than inferring from the presence of document
    # rows.
    _replace_period(db, firm_id=firm_id, client_id=client_id, period=period,
                    rows=rows, parsed=parsed, book_bill_count=len(bills),
                    problems=problems)

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
    rows = _paginate_all(lambda: db.table("gstr2a_records").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("return_period", period))
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.get("match_status") or "unmatched"] = counts.get(
            r.get("match_status") or "unmatched", 0) + 1

    # The HEADER, so the screen can tell "reconciled, and the 2B was empty" from
    # "never reconciled". Zero records means opposite things in those two cases
    # and the record count alone cannot say which.
    header = (db.table("gstr2b_reconciliations").select("*")
              .eq("firm_id", firm_id).eq("client_id", client_id)
              .eq("return_period", period).limit(1).execute().data) or []
    head = header[0] if header else None

    return {
        "period": period,
        "reconciled": head is not None,
        "reconciled_at": (head or {}).get("reconciled_at"),
        "gstin": (head or {}).get("gstin"),
        "generated_on": (head or {}).get("generated_on"),
        "book_bill_count": (head or {}).get("book_bill_count"),
        "problems": (head or {}).get("problems") or [],
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


def _header_row(parsed: GSTR2BFile, document_count: int,
                book_bill_count: int, problems: list[str]) -> dict:
    """The one header fact, built once so both write paths write the same row."""
    return {
        "gstin": parsed.gstin or None,
        "file_return_period": parsed.return_period or None,
        "generated_on": parsed.generated_on or None,
        "sections_seen": sorted(parsed.sections_seen),
        "document_count": int(document_count),
        "book_bill_count": int(book_bill_count),
        "parsed_ok": True,
        "problems": list(problems),
    }


def _replace_period(db, *, firm_id: str, client_id: str, period: str,
                    rows: list[dict], parsed: GSTR2BFile,
                    book_bill_count: int, problems: list[str]) -> None:
    """Replace this period's documents AND header, atomically where possible.

    WHY THE ATOMICITY MATTERS, and it is not a tidiness argument. Over PostgREST
    this is four statements and therefore four transactions: delete documents,
    insert documents, delete header, insert header. Anything interrupting the
    middle — and `apps/api` runs in Singapore against Postgres in Mumbai, so
    every one is a cross-region round trip — leaves the period with its previous
    reconciliation DESTROYED and nothing in its place.

    WHICH WAY IT GOES WRONG DEPENDS ON WHERE IT FAILS, and both directions are
    reachable. A failure during the DOCUMENT insert destroys the documents and
    leaves the PREVIOUS HEADER standing — it is deleted later — so
    `was_reconciled` is true over zero documents and Rule 36(4) caps the month's
    ITC AT NIL. A failure during the HEADER insert leaves the documents with no
    header, so the period reads back as never reconciled, `have_2b` is false,
    nothing caps, and the return claims credit §16(2)(aa) may withhold.

    The first was MEASURED against a real Postgres: a period holding one
    document and one header came back holding zero documents and one header
    after a single failed insert. Both are recoverable by re-uploading and both
    are visible on the screen — but nothing tells the CA to look, and the first
    puts a wrong figure on a filed return.

    Migration 366's `replace_gstr2b_reconciliation` does the whole replacement
    in one transaction: it commits entirely or leaves the tables as they were.

    THE FALLBACK IS NOT A SECOND IMPLEMENTATION OF A RULE. Mock mode has no
    DATABASE_URL and the in-memory source has no SQL functions, so the
    statement-by-statement path stays for it. Both write the same rows, from the
    same `rows` list and the same `_header_row`; only the atomicity differs, and
    atomicity is exactly what an in-memory double cannot offer. That is the same
    arrangement as cash_flow_report, schedule_iii_ageing and
    stock_position_as_at — except that those two paths compute, so they are
    pinned by a parity test, while these two only WRITE.
    """
    header = _header_row(parsed, len(rows), book_bill_count, problems)

    rpc = getattr(db, "rpc", None)
    if callable(rpc):
        try:
            rpc("replace_gstr2b_reconciliation", {
                "p_firm_id": firm_id,
                "p_client_id": client_id,
                "p_period": period,
                # The function takes firm, client and period from its PARAMETERS
                # and ignores whatever the payload says, so these are stripped
                # rather than sent — a document row cannot address another firm.
                "p_documents": [
                    {k: v for k, v in r.items()
                     if k not in ("firm_id", "client_id", "return_period")}
                    for r in rows],
                "p_header": header,
            }).execute()
            return
        except Exception:
            # A database that does not yet carry migration 366 — a local dev
            # copy, or the window between a deploy and the migration job — must
            # still be able to reconcile. Falling through is strictly better
            # than refusing: it is the behaviour that shipped for months.
            _logger.warning(
                "caflow.gst2b: replace_gstr2b_reconciliation unavailable; "
                "falling back to a non-atomic replace for %s %s",
                client_id, period)

    (db.table("gstr2a_records")
       .delete().eq("firm_id", firm_id).eq("client_id", client_id)
       .eq("return_period", period).execute())
    for i in range(0, len(rows), 500):
        db.table("gstr2a_records").insert(rows[i:i + 500]).execute()

    # Written AFTER the documents so a failed document insert leaves no header
    # claiming a reconciliation that did not land.
    _record_reconciliation(
        db, firm_id=firm_id, client_id=client_id, period=period,
        header=header)


def _record_reconciliation(db, *, firm_id: str, client_id: str, period: str,
                           header: dict) -> None:
    """One row per (client, period) saying a 2B was reconciled — see migration 341.

    The NON-ATOMIC path only; _replace_period prefers migration 366's RPC and
    calls this when the database has no SQL functions (mock mode, local dev).

    Replace, not upsert-by-id: a re-upload for the same period supersedes the
    earlier answer completely, exactly as the document rows do. Two statements
    rather than one because the FakeDB used by the mock suite has no upsert.
    """
    (db.table("gstr2b_reconciliations")
       .delete().eq("firm_id", firm_id).eq("client_id", client_id)
       .eq("return_period", period).execute())
    now = datetime.now(timezone.utc).isoformat()
    # WRITTEN OUT, not `**header`. tests/test_backend_inserts_supply_every_
    # required_column_pg.py reads this payload STATICALLY to check it against
    # the real schema, and a dict spread is opaque to it — the ratchet caught
    # the spread the moment it was introduced. The keys are restated; the
    # VALUES still come from the one _header_row, so the two write paths cannot
    # disagree about what a header says.
    db.table("gstr2b_reconciliations").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "return_period": period,
        "gstin": header["gstin"],
        "file_return_period": header["file_return_period"],
        "generated_on": header["generated_on"],
        "sections_seen": header["sections_seen"],
        "document_count": header["document_count"],
        "book_bill_count": header["book_bill_count"],
        "parsed_ok": header["parsed_ok"],
        "problems": header["problems"],
        "reconciled_at": now,
        "updated_at": now,
    }).execute()


def was_reconciled(db, *, firm_id: str, client_id: str, period: str) -> bool:
    """Has a GSTR-2B been reconciled for this period at all?

    THE QUESTION RULE 36(4) NEEDS, and it is not the same question as "are there
    any 2B rows". A 2B on file showing no eligible credit caps the head at NIL;
    no 2B at all leaves book ITC alone. Asking the document rows conflates them
    and answers "no cap" to both — which claims the credit §16(2)(aa) withholds.
    """
    rows = (db.table("gstr2b_reconciliations").select("id")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("return_period", period).limit(1).execute().data) or []
    return len(rows) > 0


def reconciled_periods(db, *, firm_id: str, client_id: str) -> list[str]:
    """Every period this client has had a 2B reconciled for.

    For the Purchases tab, which must tell "this period was never reconciled"
    apart from "reconciled, and the supplier has not filed this bill". Those are
    different sentences to a CA: one is their own job, the other is a phone call
    to the supplier.
    """
    rows = _paginate_all(lambda: db.table("gstr2b_reconciliations")
                         .select("id, return_period")
                         .eq("firm_id", firm_id).eq("client_id", client_id))
    return sorted({str(r.get("return_period") or "") for r in rows if r.get("return_period")})
