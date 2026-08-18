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
    coa = _paginate_all(lambda: db.table("chart_of_accounts").select("id, system_account_key")
           .eq("firm_id", firm_id).eq("client_id", client_id))
    key_by_id = {c["id"]: c.get("system_account_key") for c in coa}
    out_ids = {c["id"] for c in coa if c.get("system_account_key") in ("gst_cgst", "gst_sgst", "gst_igst")}
    in_ids = {c["id"] for c in coa if c.get("system_account_key") == "gst_input"}

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
            head = (key_by_id.get(acc) or "").replace("gst_", "")
            by_head[head] = by_head.get(head, 0) + (cr - dr)
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


def _posted_bills(db, firm_id, client_id, start, end) -> list[dict]:
    return _paginate_all(lambda: db.table("purchase_bills").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("status", list(_BILL_POSTED))
            .gte("bill_date", start).lte("bill_date", end))


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

    result = compute_gstr3b(sales, purchases, [])

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
    books_itc = result.itc_book_cgst + result.itc_book_sgst + result.itc_book_igst
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
        "itc_claimed_paise": result.itc_igst + result.itc_cgst + result.itc_sgst,
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
            lines=[],
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
