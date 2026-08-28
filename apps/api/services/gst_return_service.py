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
    SalesTransaction, PurchaseTransaction, ITCReversal, GSTR2ARecord,
    compute_gstr3b,
)
from domain.gst.gstr1_builder import InvoiceForGSTR1, build_gstr1
from domain.gst.classifier import classify_transaction, TransactionForClassification

# Posted (on-books) document statuses. Drafts are off-books; cancelled documents
# have an equal-and-opposite reversal in the GL, so excluding them here keeps books
# and ledger in step.
_SALES_POSTED = ("issued", "partially_paid", "paid")
_BILL_POSTED = ("received", "partially_paid", "paid")


def _paginate_all(make_query, key: str = "id", page: int = 1000) -> list:
    """Fetch EVERY row of a Supabase query via keyset paging on `key` (task
    #221, same audit-C6 class as domain/reporting/sources.py's _fetch_all).
    An un-paged .execute() is silently capped at PostgREST's ~1000-row limit —
    for a high-volume client, a single busy filing month can plausibly exceed
    that, understating GSTR-1/3B output tax or ITC with no error and risking a
    wrongly filed government return (CGST Act §37/§39). `make_query` returns a
    fresh query builder each call. Test doubles that don't implement
    order/limit/gt just return their whole (small) fixture from a single
    execute(), which is already correct."""
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
    # FIRM-WIDE ACCOUNTS COUNT. The GST control accounts are normally firm-wide
    # (client_id NULL) — that is how migration 011 seeds them and how
    # services/coa_seed_service.py creates them — and a client-only filter found
    # NONE of them. out_ids and in_ids came back empty, every line fell through
    # both branches, and this returned zero output tax and zero ITC. The
    # reconciliation below then reported the books as differing from the ledger
    # by their full value, on a return a CA is about to file (CGST Act §39).
    # Observed on a live firm whose entire chart is firm-wide.
    coa = _paginate_all(lambda: db.table("chart_of_accounts")
           .select("id, client_id, system_account_key, account_name, account_type")
           .eq("firm_id", firm_id)
           .or_(f"client_id.eq.{client_id},client_id.is.null"))
    key_by_id = {c["id"]: c.get("system_account_key") for c in coa}
    name_by_id = {c["id"]: (c.get("account_name") or "") for c in coa}
    out_ids = {c["id"] for c in coa if c.get("system_account_key") in ("gst_cgst", "gst_sgst", "gst_igst")}
    in_ids = {c["id"] for c in coa if c.get("system_account_key") == "gst_input"}

    # AND THE KEY IS NOT ALWAYS THERE. system_account_key is stamped by
    # migrations 092/098 on the accounts THEY seeded; a chart built by
    # coa_seed_service carries the same accounts with the key left NULL. Same
    # live firm: `1301 GST Input Tax Credit` and `2002 GST Output Tax Payable`,
    # both NULL-keyed, 1,045 and 6,220 lines posted respectively — invisible to
    # a key-only lookup.
    #
    # Fall back to the name, and ONLY for the side the key found nothing on, so
    # a firm whose keys are stamped is completely unaffected. account_type is
    # what keeps the two sides apart: an input credit is an Asset and output tax
    # is a Liability, which is the same separation migration 098 enforces by
    # keying output heads on Liability accounts only. Without it a chart naming
    # both "%GST%" could book input credit as output tax owed.
    if not out_ids:
        out_ids = {c["id"] for c in coa
                   if c.get("account_type") == "Liability"
                   and "gst output" in (c.get("account_name") or "").lower()}
    if not in_ids:
        in_ids = {c["id"] for c in coa
                  if c.get("account_type") == "Asset"
                  and "gst input" in (c.get("account_name") or "").lower()}

    def _head_of(acc: str) -> str:
        """Which tax head a control account reports under.

        From the key where there is one. From the name otherwise — and where a
        single combined account serves all three heads, "output", because it
        genuinely cannot say. by_head is surfaced as `ledger_by_head` for the
        reader and is never compared against anything, so an honest extra
        bucket is better than silently attributing the lot to CGST."""
        key = key_by_id.get(acc)
        if key:
            return key.replace("gst_", "")
        low = name_by_id.get(acc, "").lower()
        for h in ("cgst", "sgst", "igst"):
            if h in low:
                return h
        return "output"

    entries = _paginate_all(lambda: db.table("journal_entries").select("id, entry_date, is_posted")
               .eq("firm_id", firm_id).eq("client_id", client_id)
               .gte("entry_date", start).lte("entry_date", end))
    posted_ids = {e["id"] for e in entries if e.get("is_posted", True)}
    if not posted_ids:
        return {"output_paise": 0, "itc_paise": 0, "by_head": {}}

    # Chunked (PostgREST .in_() with a large entry-id list risks the request
    # URL/payload limit) AND paged per chunk — see _paginate_all's docstring.
    posted_id_list = list(posted_ids)
    lines: list[dict] = []
    for i in range(0, len(posted_id_list), 200):
        chunk = posted_id_list[i:i + 200]
        lines.extend(_paginate_all(lambda chunk=chunk: db.table("journal_lines")
            .select("id, journal_entry_id, account_id, debit_paise, credit_paise")
            .in_("journal_entry_id", chunk)))

    by_head = {"cgst": 0, "sgst": 0, "igst": 0, "input": 0}
    output_paise = 0
    itc_paise = 0
    for l in lines:
        acc = l.get("account_id")
        dr = int(l.get("debit_paise") or 0)
        cr = int(l.get("credit_paise") or 0)
        if acc in out_ids:
            output_paise += cr - dr                 # liability is a credit balance
            by_head[_head_of(acc)] = by_head.get(_head_of(acc), 0) + (cr - dr)
        elif acc in in_ids:
            itc_paise += dr - cr                     # ITC is a debit balance
            by_head["input"] += dr - cr
    return {"output_paise": output_paise, "itc_paise": itc_paise, "by_head": by_head}


def _posted_sales(db, firm_id, client_id, start, end) -> list[dict]:
    return _paginate_all(lambda: db.table("client_sales_invoices").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("status", list(_SALES_POSTED))
            .gte("invoice_date", start).lte("invoice_date", end))


def _issued_credit_notes(db, firm_id, client_id, start, end) -> list[dict]:
    return _paginate_all(lambda: db.table("credit_notes").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("status", "issued")
            .gte("credit_note_date", start).lte("credit_note_date", end))


def _bills_cancelled_in(db, firm_id, client_id, start, end) -> list[dict]:
    """Bills CANCELLED during the period, whatever period they were raised in.

    Credit taken on a purchase that is later cancelled has to be given back, in
    the period the cancellation happens — and that is very often not the period
    the bill belongs to. Apex cancelled four February bills on 17 July 2026:
    the ledger reversed Rs 88,141.67 of ITC that month, and the return, which
    reads documents DATED in the month, saw nothing at all. It is the books-vs-
    ledger reconciliation that surfaced the difference.

    Keyed on cancelled_at, not bill_date, for exactly that reason.

    A bill RAISED and cancelled inside the same period is excluded, and that is
    not a detail. _posted_bills selects status in ('received','partially_paid',
    'paid'), so a cancelled bill is already absent from Table 4(A). Reversing in
    4(B) a credit that 4(A) never claimed would understate 4(C) by the tax and
    make the books-vs-ledger comparator disagree with a ledger that is correct —
    the cancellation reversal nets the original posting to zero inside the same
    month. Only credit availed in an EARLIER period is given back here.
    """
    rows = _paginate_all(lambda: db.table("purchase_bills").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("status", "cancelled")
            .gte("cancelled_at", start).lte("cancelled_at", f"{end}T23:59:59.999999+00:00"))
    return [b for b in rows if str(b.get("bill_date") or "")[:10] < start]


def _posted_bills(db, firm_id, client_id, start, end) -> list[dict]:
    """Bills whose credit was availed in this period — as at the END of it.

    The status filter alone answers "is this bill live TODAY", and for a return
    that is the wrong question. A June bill cancelled in July was live for the
    whole of June: the June return claimed its ITC, the June GL still carries
    the debit, and the reversal belongs to July (see _bills_cancelled_in). With
    the status filter alone, re-opening June after the cancellation drops the
    bill from Table 4(A) while the ledger keeps it, and the reconciliation
    reports a difference in a month where nothing is actually wrong — the same
    Rs 88,141.67 of Apex's July gap, showing up a second time in February.

    A cancelled bill with no cancelled_at cannot be placed in time, so it stays
    excluded: that is the behaviour every existing return was computed under.
    """
    live = _paginate_all(lambda: db.table("purchase_bills").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("status", list(_BILL_POSTED))
            .gte("bill_date", start).lte("bill_date", end))
    cancelled_later = [
        b for b in _paginate_all(lambda: db.table("purchase_bills").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("status", "cancelled")
            .gte("bill_date", start).lte("bill_date", end))
        if str(b.get("cancelled_at") or "")[:10] > end
    ]
    return live + cancelled_later


def _issued_debit_notes(db, firm_id, client_id, start, end) -> list[dict]:
    return _paginate_all(lambda: db.table("debit_notes").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("status", "issued")
            .gte("debit_note_date", start).lte("debit_note_date", end))


def _issued_sales_debit_notes(db, firm_id, client_id, start, end) -> list[dict]:
    return _paginate_all(lambda: db.table("sales_debit_notes").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("status", "issued")
            .gte("debit_note_date", start).lte("debit_note_date", end))


def _document_lines(db, table: str, fk: str, doc_ids: list[str]) -> dict[str, list]:
    """{document_id: [InvoiceLine, ...]} for GSTR-1 table 12.

    Serves sales invoices and both note types — client_sales_invoice_lines,
    credit_note_lines and sales_debit_note_lines share a shape, differing only
    in the owning foreign key.

    WHY THIS EXISTS
        gstr1_from_books built every InvoiceForGSTR1 with `lines=[]`, so
        _build_hsn_summary always took its no-lines fallback and filed the
        whole return as ONE row: hsn_sc "OTH", desc "Other", qty 0. No HSN or
        SAC code ever reached the return, while the line rows behind it all
        carried one.

        That is a filing defect above the turnover thresholds the builder
        already encodes in _required_hsn_digits — 6 digits above ₹5 crore,
        4 above ₹1.5 crore (CGST Rule 59 / the CBIC HSN notifications). The
        digit count was computed correctly and then had nothing to truncate.

    None of the three line tables has a cess column, so cess_paise is 0 here.
    That is their shape, not an assumption about cess: a document carrying cess
    would need a line-level column before table 12 could apportion it.
    """
    if not doc_ids:
        return {}
    from domain.gst.gstr1_builder import InvoiceLine

    rows = _paginate_all(lambda: db.table(table).select("*").in_(fk, list(doc_ids)))
    by_doc: dict[str, list] = {}
    for r in sorted(rows or [], key=lambda x: (x.get(fk) or "", x.get("sort_order") or 0)):
        doc_id = r.get(fk)
        if not doc_id:
            continue
        by_doc.setdefault(doc_id, []).append(InvoiceLine(
            hsn_sac_code=(r.get("hsn_sac") or "").strip(),
            description=r.get("description") or "",
            quantity=float(r.get("quantity") or 0),
            unit=(r.get("unit") or "OTH"),
            rate_paise=int(r.get("rate_paise") or 0),
            taxable_paise=int(r.get("taxable_amount_paise") or 0),
            # Stored in basis points (1800 = 18%); the builder wants percent.
            gst_rate=float(r.get("gst_rate_bps") or 0) / 100.0,
            cgst_paise=int(r.get("cgst_paise") or 0),
            sgst_paise=int(r.get("sgst_paise") or 0),
            igst_paise=int(r.get("igst_paise") or 0),
            cess_paise=0,
        ))
    return by_doc


def _classification_by_parent_invoice(db, firm_id: str, note_rows: list[dict]) -> dict[str, dict]:
    """{sales_invoice_id: {supply_type, invoice_type, is_reverse_charge}} for every
    invoice referenced by these notes.

    WHY NOTES INHERIT RATHER THAN CARRY THEIR OWN
        CGST Act §34: a credit or debit note is always issued "in relation to" a
        specific original tax invoice — it adjusts that invoice's value or tax
        and has no standing to redeclare what kind of supply was made. GSTR-1
        table 9B (CDNR) enforces the same shape, requiring the original invoice
        number and date on every note. So a note against a nil-rated supply IS
        nil-rated; there is nothing for a CA to choose.

        The note tables therefore have no supply_type / invoice_type /
        is_reverse_charge columns, and none are added here — inheriting at build
        time cannot drift from the invoice the way a stored copy could.

    THE BUG THIS CLOSES
        Both builders below read those fields straight off the note row. Absent
        on the note, every one fell back to taxable / Regular / no reverse
        charge — so a credit note against an exempt, nil-rated, SEZ or
        deemed-export invoice was declared as an ordinary taxable adjustment,
        landing in the wrong GSTR-1 table and overstating the credit taken
        against taxable turnover in GSTR-3B.

    The parent invoice is fetched BY ID, not taken from the period's invoices:
    a note issued in August routinely adjusts a June invoice, which no
    period-bounded query would return.
    """
    parent_ids = {r.get("sales_invoice_id") for r in note_rows if r.get("sales_invoice_id")}
    if not parent_ids:
        return {}
    rows = _paginate_all(lambda: db.table("client_sales_invoices")
                         .select("id, supply_type, invoice_type, is_reverse_charge")
                         .eq("firm_id", firm_id).in_("id", list(parent_ids)))
    return {r["id"]: r for r in (rows or []) if r.get("id")}


def _note_classification(row: dict, parents: dict[str, dict]) -> dict:
    """The classification a note declares: its parent invoice's, or the
    defaults when it is unlinked.

    An unlinked note keeps the migration 268 column defaults rather than
    guessing. §34 expects a reference; a note without one is already an
    exception a CA has to stand behind, and inventing a classification for it
    would hide that rather than surface it.
    """
    parent = parents.get(row.get("sales_invoice_id") or "") or {}
    return {
        "supply_type": parent.get("supply_type") or "taxable",
        "invoice_type": parent.get("invoice_type") or "Regular",
        "is_reverse_charge": bool(parent.get("is_reverse_charge") or False),
    }


def _issued_purchase_credit_notes(db, firm_id, client_id, start, end) -> list[dict]:
    return _paginate_all(lambda: db.table("purchase_credit_notes").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("status", "issued")
            .gte("credit_note_date", start).lte("credit_note_date", end))


def _gstr2a_for_period(db, firm_id, client_id, period) -> list[dict]:
    """Supplier-filed records for the period, for the Rule 36(4) comparison.

    The from-books path passed an empty list, so the cap has never been able to
    fire on the return a CA actually files — Rule 36(4) was live code reachable
    only from /gstr3b/compute, which nothing in the product calls.

    Returning [] when nothing has been uploaded is correct and safe:
    _apply_rule_36_4_cap treats a zero 2A total as "no data" and leaves book
    ITC alone rather than capping the whole return to nil.
    """
    return _paginate_all(lambda: db.table("gstr2a_records")
            .select("taxable_value_paise, igst_paise, cgst_paise, sgst_paise")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("return_period", period))


def _customers_for_3b(db, firm_id, rows) -> dict:
    """id -> customer, for the Table 3.2 recipient split."""
    ids = {r.get("customer_id") for r in rows if r.get("customer_id")}
    if not ids:
        return {}
    got = (db.table("customers").select("id, gstin, state_code")
           .eq("firm_id", firm_id).in_("id", list(ids)).execute().data) or []
    return {c["id"]: c for c in got}


def _recipient_type(cust: dict | None) -> str:
    """Which Table 3.2 column a recipient belongs in, if any.

    A GSTIN means registered, and 3.2 does not report ordinary registered
    recipients. Composition dealers and UIN holders also hold a number, so on
    this platform's data they cannot be told apart from any other registered
    recipient — nothing records that a customer is one. They therefore never
    reach comp_details or uin_details, which stay empty. That is a data gap,
    not a classification the code is getting wrong.
    """
    return "registered" if (cust or {}).get("gstin") else "unregistered"


def gstr3b_from_books(db, firm_id: str, client_id: str, period: str, gstin: str) -> dict:
    """Compute GSTR-3B from posted books and reconcile to the General Ledger."""
    start, end = _period_bounds(period)

    invoices_3b = _posted_sales(db, firm_id, client_id, start, end)
    cust_3b = _customers_for_3b(db, firm_id, invoices_3b)

    sales: list[SalesTransaction] = []
    for inv in invoices_3b:
        cust = cust_3b.get(inv.get("customer_id"))
        sales.append(SalesTransaction(
            transaction_type="sales_invoice",
            taxable_amount_paise=int(inv.get("taxable_amount_paise") or 0),
            cgst_paise=int(inv.get("cgst_paise") or 0),
            sgst_paise=int(inv.get("sgst_paise") or 0),
            igst_paise=int(inv.get("igst_paise") or 0),
            cess_paise=int(inv.get("cess_paise") or 0),
            supply_type=inv.get("supply_type") or "taxable",
            is_reverse_charge=bool(inv.get("is_reverse_charge", False)),
            # Table 3.2 — the breakdown of 3.1(a) by recipient and place of
            # supply. supply_state_code is where the supply is made TO.
            is_interstate=bool(inv.get("is_interstate", False)),
            place_of_supply=str(inv.get("supply_state_code") or "")[:2],
            recipient_type=_recipient_type(cust),
        ))
    # Notes inherit their classification from the invoice they adjust (CGST §34)
    # — see _classification_by_parent_invoice.
    cns_3b = _issued_credit_notes(db, firm_id, client_id, start, end)
    sdns_3b = _issued_sales_debit_notes(db, firm_id, client_id, start, end)
    note_parents = _classification_by_parent_invoice(db, firm_id, cns_3b + sdns_3b)
    for cn in cns_3b:
        cls = _note_classification(cn, note_parents)
        sales.append(SalesTransaction(
            transaction_type="credit_note",
            taxable_amount_paise=int(cn.get("taxable_amount_paise") or 0),
            cgst_paise=int(cn.get("cgst_paise") or 0),
            sgst_paise=int(cn.get("sgst_paise") or 0),
            igst_paise=int(cn.get("igst_paise") or 0),
            cess_paise=int(cn.get("cess_paise") or 0),
            supply_type=cls["supply_type"],
            is_reverse_charge=cls["is_reverse_charge"],
        ))
    # Sales debit notes (sales_debit_notes table) INCREASE what the customer owes
    # (CGST Act §34(3)) — e.g. an undercharge correction — so they add to output
    # tax exactly like an invoice. compute_gstr3b only special-cases
    # transaction_type == "credit_note" (sign -1); anything else, including
    # "debit_note", is added at sign +1. Omitting these previously understated
    # every from-books GSTR-3B's output tax whenever a sales debit note was
    # issued, and silently broke the GL reconciliation below (task, 2026-07-24).
    for sdn in sdns_3b:
        cls = _note_classification(sdn, note_parents)
        sales.append(SalesTransaction(
            transaction_type="debit_note",
            taxable_amount_paise=int(sdn.get("taxable_amount_paise") or 0),
            cgst_paise=int(sdn.get("cgst_paise") or 0),
            sgst_paise=int(sdn.get("sgst_paise") or 0),
            igst_paise=int(sdn.get("igst_paise") or 0),
            cess_paise=int(sdn.get("cess_paise") or 0),
            supply_type=cls["supply_type"],
            is_reverse_charge=cls["is_reverse_charge"],
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
            # CGST Act §17(5) — blocked credit (migration 240).
            ineligible_igst_paise=int(b.get("ineligible_itc_igst_paise") or 0),
            ineligible_cgst_paise=int(b.get("ineligible_itc_cgst_paise") or 0),
            ineligible_sgst_paise=int(b.get("ineligible_itc_sgst_paise") or 0),
            ineligible_cess_paise=int(b.get("ineligible_itc_cess_paise") or 0),
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
    # Purchase credit notes (purchase_credit_notes table) — in this codebase's
    # convention (routers/purchase_credit_notes.py) these are an INCREASE to
    # what we owe the vendor (undercharge correction), posted Dr Purchases /
    # Dr GST Input / Cr Trade Payables — the mirror image of the (purchase)
    # debit note above. They add to book ITC exactly like an extra purchase
    # bill. Previously fed nowhere into gstr3b_from_books: the GL's gst_input
    # debit already included them (they post a real journal), so the return's
    # ITC silently undercounted book ITC and the reconciliation below flagged a
    # permanent, unexplained mismatch for any client using this document type
    # (task, 2026-07-24).
    for pcn in _issued_purchase_credit_notes(db, firm_id, client_id, start, end):
        purchases.append(PurchaseTransaction(
            taxable_amount_paise=int(pcn.get("taxable_amount_paise") or 0),
            cgst_paise=int(pcn.get("cgst_paise") or 0),
            sgst_paise=int(pcn.get("sgst_paise") or 0),
            igst_paise=int(pcn.get("igst_paise") or 0),
            cess_paise=int(pcn.get("cess_paise") or 0),
            is_reverse_charge=bool(pcn.get("is_reverse_charge", False)),
        ))

    # ── Table 4(B): credit given back in this period ────────────────────────
    # From the DOCUMENTS, never from the GL. The books-vs-ledger reconciliation
    # below is only worth reading while the two sides are derived
    # independently; sourcing 4(B) from the movement on gst_input would make it
    # compare the ledger with itself and agree by construction.
    #
    # 4(B)(1), and this one is a JUDGEMENT rather than a lookup. Circular
    # 170/02/2022-GST does not name a cancelled purchase anywhere; it names
    # rules 38, 42 and 43 and §17(5). But it names them as examples — the box
    # is for "reversal of ITC that are absolute in nature and not reclaimable
    # ... such as those on account of rule 38 ..." — and a cancelled purchase
    # meets that test exactly: the supply is undone, the credit is gone, and
    # nothing will ever bring it back. 4(B)(2) is defined as "ITC that is to be
    # reclaimed or may be reclaimed on a future date", which this is not, and
    # declaring it there would leave a balance in the electronic credit
    # reversal and re-claimed statement that never clears.
    reversals = [
        ITCReversal(
            igst_paise=int(b.get("igst_paise") or 0),
            cgst_paise=int(b.get("cgst_paise") or 0),
            sgst_paise=int(b.get("sgst_paise") or 0),
            cess_paise=int(b.get("cess_paise") or 0),
            reclaimable=False,
            reason=f"purchase bill {b.get('bill_no') or b.get('id')} cancelled",
        )
        for b in _bills_cancelled_in(db, firm_id, client_id, start, end)
    ]

    # Rule 36(4): ITC is capped at the credit suppliers have actually filed.
    # This used to pass [], so the cap could never fire on the return a CA
    # files. _apply_rule_36_4_cap leaves book ITC alone when no records exist,
    # so a client who has never uploaded 2A is unaffected.
    two_a_rows = _gstr2a_for_period(db, firm_id, client_id, period)
    gstr2a = [
        GSTR2ARecord(
            cgst_paise=int(x.get("cgst_paise") or 0),
            sgst_paise=int(x.get("sgst_paise") or 0),
            igst_paise=int(x.get("igst_paise") or 0),
        )
        for x in two_a_rows
    ]

    result = compute_gstr3b(sales, purchases, gstr2a, reversals)

    # ── Reconcile the return to the posted General Ledger ─────────────────────
    gl = _gl_gst_movements(db, firm_id, client_id, start, end)
    # Output side = Table 3.1(a) outward + Table 3.1(d) reverse-charge inward:
    # journal_for_purchase_bill posts the RCM self-assessed tax as a credit to
    # the GST output accounts (CGST Act §9(3)/(4)), so the ledger's output
    # movement legitimately carries BOTH heads — the books-side comparator
    # must too, or every RCM bill flags a false mismatch.
    books_rcm = result.rcm_cgst + result.rcm_sgst + result.rcm_igst
    books_output = (result.outward_taxable_cgst + result.outward_taxable_sgst
                    + result.outward_taxable_igst + books_rcm)
    # The ledger's gst_input movement is NET of reversals — cancelling a bill
    # credits the account — so the books comparator has to net them too. It did
    # not, and that was the whole of the Rs 88,141.67 the July 2026 reconciliation
    # reported for Apex: four February bills cancelled on 17 July.
    #
    # PERMANENT REVERSALS ONLY. 4(B)(2) carries Rule 37 / §16(2) amounts, and
    # itc_reversal_service deliberately posts no journal for those — it reports
    # them for the CA to act on. Netting an unposted reversal here would create
    # the mismatch it is meant to detect. Anything fed as non-reclaimable must
    # therefore be something the books have actually posted.
    books_reversed = (result.itc_rev_perm_cgst + result.itc_rev_perm_sgst
                      + result.itc_rev_perm_igst)
    books_itc = (result.itc_book_cgst + result.itc_book_sgst + result.itc_book_igst
                 - books_reversed)
    output_matched = books_output == gl["output_paise"]
    itc_matched = books_itc == gl["itc_paise"]

    return {
        "period": period,
        "gstin": gstin,
        "source": "posted_general_ledger",
        # Paise-precise header totals for gst-workspace SaveGSTR3BRequest — kept
        # server-side (CLAUDE.md: zero business logic in the frontend) so the
        # caller never has to derive these from the rupee-rounded payload/summary.
        "tax_liability_paise": books_output,
        # Table 4(C): the credit actually claimed, net of the 4(B) reversals.
        # This is the figure stored on gst_returns and shown as "ITC Claimed",
        # so it has to be the one the return claims, not the gross 4(A).
        "itc_claimed_paise": result.itc_net_igst + result.itc_net_cgst + result.itc_net_sgst,
        "net_tax_paise": result.net_igst + result.net_cgst + result.net_sgst,
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
                # Table 4(A) and 4(C), in paise. 4(A) is GROSS — it includes
                # blocked credit and credit reversed below — because the portal
                # populates it from GSTR-2B. 4(C) is what is actually claimed.
                "avail_cgst_paise": result.itc_avail_cgst,
                "avail_sgst_paise": result.itc_avail_sgst,
                "avail_igst_paise": result.itc_avail_igst,
                "net_cgst_paise": result.itc_net_cgst,
                "net_sgst_paise": result.itc_net_sgst,
                "net_igst_paise": result.itc_net_igst,
            },
            # Table 4 as the portal lays it out since Notification 14/2022 read
            # with Circular 170/02/2022-GST. The payload above carries the same
            # figures in whole rupees; these are the paise a CA reconciles with,
            # and the reasons are what lets them answer "why is 4(B) this much".
            "itc_reversal": {
                "permanent_paise": {          # 4(B)(1) — Rules 38/42/43, §17(5)
                    "cgst_paise": result.itc_ineligible_cgst + result.itc_rev_perm_cgst,
                    "sgst_paise": result.itc_ineligible_sgst + result.itc_rev_perm_sgst,
                    "igst_paise": result.itc_ineligible_igst + result.itc_rev_perm_igst,
                    "cess_paise": result.itc_ineligible_cess + result.itc_rev_perm_cess,
                },
                "reclaimable_paise": {        # 4(B)(2) — Rule 37/37A, §16(2)(b)/(c)
                    "cgst_paise": result.itc_rev_temp_cgst,
                    "sgst_paise": result.itc_rev_temp_sgst,
                    "igst_paise": result.itc_rev_temp_igst,
                    "cess_paise": result.itc_rev_temp_cess,
                },
                "reasons": [
                    {"reason": rv.reason,
                     "reclaimable": rv.reclaimable,
                     "cgst_paise": rv.cgst_paise,
                     "sgst_paise": rv.sgst_paise,
                     "igst_paise": rv.igst_paise,
                     "cess_paise": rv.cess_paise}
                    for rv in reversals
                ],
            },
            # Rule 36(4). A CA reading a capped return needs to know the cap
            # fired and what it was measured against; a CA reading an uncapped
            # one needs to know whether that is because the books agree with 2A
            # or because no 2A has been uploaded at all. Those are very
            # different, and the figures alone cannot tell them apart.
            "rule_36_4": {
                "gstr2a_record_count": len(two_a_rows),
                "gstr2a_cgst_paise": result.itc_2a_cgst,
                "gstr2a_sgst_paise": result.itc_2a_sgst,
                "gstr2a_igst_paise": result.itc_2a_igst,
                "cap_applied": result.itc_capped_by_2a,
                "compared": bool(two_a_rows),
            },
            # Table 6. Computed HERE, not in the browser: the Section 49(5)
            # cross-utilisation order is a statutory rule, and CLAUDE.md keeps
            # those in apps/api. The screen renders these; it derives nothing.
            "net_payable": {
                "igst_paise": result.net_igst,
                "cgst_paise": result.net_cgst,
                "sgst_paise": result.net_sgst,
                "total_paise": result.net_igst + result.net_cgst + result.net_sgst,
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
    """Build GSTR-1 from posted sales invoices + issued credit/debit notes, and
    reconcile the total output tax to the General Ledger GST-output control
    accounts."""
    start, end = _period_bounds(period)

    invoices_raw = _posted_sales(db, firm_id, client_id, start, end)
    cns_raw = _issued_credit_notes(db, firm_id, client_id, start, end)
    # Sales debit notes (sales_debit_notes) belong in Table 9B (CDNR/CDNUR) same
    # as credit notes — domain/gst/classifier.py and gstr1_builder.py already
    # treat transaction_type "debit_note" as a first-class CDNR member (the
    # "ntty": "D" vs "C" flag). This function previously never fetched the
    # table at all, so a sales debit note issued in the period never appeared
    # in the from-books GSTR-1 and the reconciliation below silently ignored
    # its GL output-tax movement (task, 2026-07-24).
    sdns_raw = _issued_sales_debit_notes(db, firm_id, client_id, start, end)

    # Resolve customer GSTIN / name / place of supply (no nested select — join here).
    cust_ids = {r.get("customer_id") for r in (invoices_raw + cns_raw + sdns_raw) if r.get("customer_id")}
    cust_by_id: dict = {}
    if cust_ids:
        rows = (db.table("customers").select("id, name, gstin, state_code")
                .eq("firm_id", firm_id).in_("id", list(cust_ids)).execute().data) or []
        cust_by_id = {c["id"]: c for c in rows}

    _REF_FIELD = {"sales_invoice": "invoice_no", "credit_note": "credit_note_no", "debit_note": "debit_note_no"}
    _DATE_FIELD = {"sales_invoice": "invoice_date", "credit_note": "credit_note_date", "debit_note": "debit_note_date"}

    # A note declares the classification of the invoice it adjusts (CGST §34).
    # Resolved once here; the parent may pre-date the period being filed.
    note_parents = _classification_by_parent_invoice(db, firm_id, cns_raw + sdns_raw)

    # Line items for table 12's HSN summary — invoices AND both note types, so
    # the summary can net (task #166). Each document type keeps its own map;
    # ids are only unique within a table.
    lines_by_doc = {
        "sales_invoice": _document_lines(
            db, "client_sales_invoice_lines", "sales_invoice_id",
            [r["id"] for r in invoices_raw if r.get("id")]),
        "credit_note": _document_lines(
            db, "credit_note_lines", "credit_note_id",
            [r["id"] for r in cns_raw if r.get("id")]),
        "debit_note": _document_lines(
            db, "sales_debit_note_lines", "debit_note_id",
            [r["id"] for r in sdns_raw if r.get("id")]),
    }

    def _to_gstr1(r: dict, doc_type: str) -> InvoiceForGSTR1:
        cust = cust_by_id.get(r.get("customer_id"), {})
        gstin_party = cust.get("gstin")
        pos = r.get("supply_state_code") or cust.get("state_code") or ""
        # Was hardcoded "Regular", so an SEZ supply or a deemed export was
        # declared as an ordinary B2B invoice and the recipient had nothing to
        # match a CGST §16(3) refund claim against. Notes carry no such column
        # of their own and used to keep the default outright — they now inherit
        # from the original invoice instead.
        if doc_type == "sales_invoice":
            cls = {
                "supply_type": r.get("supply_type") or "taxable",
                "invoice_type": r.get("invoice_type") or "Regular",
            }
        else:
            cls = _note_classification(r, note_parents)
        txn = TransactionForClassification(
            id=r.get("id", ""),
            transaction_type=doc_type,
            party_gstin=gstin_party,
            is_interstate=bool(r.get("is_interstate", False)),
            taxable_amount_paise=int(r.get("taxable_amount_paise") or 0),
            supply_type=cls["supply_type"],
            invoice_type=cls["invoice_type"],
            place_of_supply=pos,
            # Rule 59(4) tests the invoice VALUE, and the limit it is tested
            # against depends on the invoice date.
            invoice_value_paise=(int(r.get("taxable_amount_paise") or 0)
                                 + int(r.get("cgst_paise") or 0)
                                 + int(r.get("sgst_paise") or 0)
                                 + int(r.get("igst_paise") or 0)
                                 + int(r.get("cess_paise") or 0)
                                 + int(r.get("round_off_paise") or 0)),
            transaction_date=r.get(_DATE_FIELD[doc_type]) or "",
        )
        return InvoiceForGSTR1(
            id=r.get("id", ""),
            transaction_type=doc_type,
            reference_no=r.get(_REF_FIELD[doc_type]) or "",
            transaction_date=r.get(_DATE_FIELD[doc_type]) or "",
            party_gstin=gstin_party,
            party_name=cust.get("name") or "",
            place_of_supply=pos,
            is_interstate=bool(r.get("is_interstate", False)),
            taxable_amount_paise=int(r.get("taxable_amount_paise") or 0),
            cgst_paise=int(r.get("cgst_paise") or 0),
            sgst_paise=int(r.get("sgst_paise") or 0),
            igst_paise=int(r.get("igst_paise") or 0),
            cess_paise=int(r.get("cess_paise") or 0),
            # Credit/debit notes (credit_notes / sales_debit_notes tables) have no
            # round_off column → .get None → 0.
            round_off_paise=int(r.get("round_off_paise") or 0),
            # Same resolved classification the classifier was handed above —
            # NOT r.get(...) again. _build_nil reads supply_type off this
            # object to split table 8's nil/exempt/non-GST columns, so reading
            # the note's own absent column here would classify it as nil and
            # then report it as taxable.
            is_reverse_charge=cls.get("is_reverse_charge", bool(r.get("is_reverse_charge", False))),
            invoice_type=cls["invoice_type"],
            supply_type=cls["supply_type"],
            gst_invoice_category=classify_transaction(txn),
            original_invoice_ref=r.get("sales_invoice_id") if doc_type != "sales_invoice" else None,
            original_invoice_date=None,
            # Real lines, so table 12 reports actual HSN/SAC codes instead of a
            # single "OTH" row — for notes too, which _build_hsn_summary now
            # nets rather than skipping.
            lines=lines_by_doc.get(doc_type, {}).get(r.get("id") or "", []),
        )

    invoices = ([_to_gstr1(r, "sales_invoice") for r in invoices_raw]
                + [_to_gstr1(r, "credit_note") for r in cns_raw]
                + [_to_gstr1(r, "debit_note") for r in sdns_raw])
    payload = build_gstr1(invoices, gstin, period, aggregate_turnover_paise)

    # Reconcile output tax to the GL. GSTR-1 tax total is gross (before credit
    # notes, before debit notes); compare against sales-only GST in the GL
    # (credit notes are the CDNR reduction, debit notes the CDNR increase).
    gl = _gl_gst_movements(db, firm_id, client_id, start, end)
    inv_output = sum(int(r.get("cgst_paise") or 0) + int(r.get("sgst_paise") or 0)
                     + int(r.get("igst_paise") or 0) for r in invoices_raw)
    cn_output = sum(int(r.get("cgst_paise") or 0) + int(r.get("sgst_paise") or 0)
                    + int(r.get("igst_paise") or 0) for r in cns_raw)
    dn_output = sum(int(r.get("cgst_paise") or 0) + int(r.get("sgst_paise") or 0)
                    + int(r.get("igst_paise") or 0) for r in sdns_raw)
    net_books_output = inv_output - cn_output + dn_output

    return {
        "period": period,
        "gstin": gstin,
        "source": "posted_general_ledger",
        # Paise-precise header totals for gst-workspace SaveGSTR1Request — mirrors
        # build_gstr1()'s own "totals_rupees" (payload.summary), computed in paise
        # here so the caller never rounds a rupee figure back into paise
        # (CLAUDE.md: integer paise arithmetic only, never floats).
        "total_igst_paise": sum(int(r.get("igst_paise") or 0) for r in invoices_raw),
        "total_cgst_paise": sum(int(r.get("cgst_paise") or 0) for r in invoices_raw),
        "total_sgst_paise": sum(int(r.get("sgst_paise") or 0) for r in invoices_raw),
        "total_cess_paise": sum(int(r.get("cess_paise") or 0) for r in invoices_raw),
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
