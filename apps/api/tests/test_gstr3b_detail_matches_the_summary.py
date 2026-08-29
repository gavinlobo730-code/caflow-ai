"""The documents behind a GSTR-3B figure, and the one property that makes them
worth showing: they add up to it.

WHY THIS EXISTS
    Asked for by name, from experience of UK VAT under MTD: there a CA gets a
    VAT Return (the nine boxes) AND a VAT Detail report listing every
    transaction behind each box. PracticeSync had the first and not the second.

    GSTR-1 already had detail — the firm-level screen lists B2B, B2CS, B2CL and
    HSN invoice by invoice. GSTR-3B had none: a CA could read ITC of
    Rs 54,32,625.99 and had no way to ask which bills that was. The summary is
    what gets filed; the detail is what gets checked before filing.

THE CONTRACT
    A detail report that disagrees with the summary above it is worse than no
    detail report — it turns one trusted figure into two untrusted ones. So the
    detail reuses the return's own fetchers, and every test below is a form of
    "the listing sums to the figure".

    The inclusion rules it has to inherit are the awkward ones: a credit note
    REDUCES outward tax and must be listed negative; a bill cancelled AFTER
    period end still belongs to 4(A); a bill cancelled DURING the period is a
    4(B)(1) reversal and not a 4(A) entry.
"""
from __future__ import annotations

import pytest
from _pytest.monkeypatch import MonkeyPatch

import services.gst_return_service as grs
import tests.test_gstr3b_itc_reversal_from_books as E


@pytest.fixture()
def books():
    mp = MonkeyPatch()
    try:
        db = E._setup(mp)
        E._receive_bill(db, "B-1", 5_00000, "2025-07-04")
        E._receive_bill(db, "B-2", 2_00000, "2025-07-11")
        yield db
    finally:
        mp.undo()


def _detail(db, period, line):
    return grs.gstr3b_detail(db, E.FIRM, "CLI", period, line)


# ── It has to add up ────────────────────────────────────────────────────────

def test_the_4a_detail_sums_to_table_4a(books):
    ret = E._3b(books, E.JULY)
    d = _detail(books, E.JULY, "4A")

    itc = ret["working"]["itc"]
    assert d["count"] == 2, "two bills were posted in July"
    assert d["total_igst_paise"] == itc["avail_igst_paise"]
    assert d["total_cgst_paise"] == itc["avail_cgst_paise"]
    assert d["total_sgst_paise"] == itc["avail_sgst_paise"]


def test_every_row_carries_the_document_a_ca_would_look_up(books):
    """A detail report of anonymous amounts is a second summary. Each row has to
    name the document, its date and the party, or it cannot be checked against
    anything."""
    d = _detail(books, E.JULY, "4A")
    for r in d["rows"]:
        assert r["document_no"], r
        assert r["document_date"].startswith("2025-07"), r
        assert r["kind"], r
        assert r["tax_paise"] == r["igst_paise"] + r["cgst_paise"] + r["sgst_paise"]


def test_the_rows_are_ordered_by_date(books):
    d = _detail(books, E.JULY, "4A")
    dates = [r["document_date"] for r in d["rows"]]
    assert dates == sorted(dates)


def test_a_line_with_no_documents_returns_an_empty_report_not_an_error(books):
    """An empty 3.1(a) is a real answer for a client who sold nothing that
    month, and must not read as a failure."""
    d = _detail(books, E.JULY, "3.1a")
    assert d["count"] == 0
    assert d["rows"] == []
    assert d["total_tax_paise"] == 0


def test_an_unknown_line_is_refused_rather_than_silently_empty(books):
    """An empty report and a mistyped parameter must not look the same."""
    with pytest.raises(ValueError, match="unknown GSTR-3B line"):
        _detail(books, E.JULY, "4Z")
    with pytest.raises(ValueError):
        _detail(books, E.JULY, "")


# ── The awkward inclusion rules it inherits ─────────────────────────────────

def test_a_bill_cancelled_after_period_end_stays_in_4a(books):
    """It was live for the whole of July: the July return claimed its credit and
    the July ledger still carries the debit. The reversal belongs to the period
    of cancellation. If the detail dropped it, the listing would be short by a
    bill against a summary that still counted it."""
    mp = MonkeyPatch()
    try:
        first = _detail(books, E.JULY, "4A")["rows"][0]["id"]
        E._cancel_on(mp, first, "2025-08-15")
        ret = E._3b(books, E.JULY)
        d = _detail(books, E.JULY, "4A")
        assert d["count"] == 2, "the cancelled-later bill must still be listed"
        assert d["total_igst_paise"] == ret["working"]["itc"]["avail_igst_paise"]
        assert d["total_cgst_paise"] == ret["working"]["itc"]["avail_cgst_paise"]
    finally:
        mp.undo()


def test_a_bill_raised_and_cancelled_in_one_period_is_in_neither_table(books):
    """Not the obvious answer, and the detail must inherit it rather than look
    tidier than the return.

    _posted_bills selects status in (received, partially_paid, paid), so a
    cancelled bill is already absent from 4(A) — there is no credit to give
    back. Listing it under 4(B)(1) as well would reverse a claim never made,
    understating 4(C) by the tax, and would disagree with a ledger that is
    correct: the cancellation journal nets the original posting to zero inside
    the same month. Only credit availed in an EARLIER period is reversed here,
    which is why _bills_cancelled_in filters on bill_date < start.

    An earlier version of this test asserted the opposite and failed. The code
    was right.
    """
    mp = MonkeyPatch()
    try:
        first = _detail(books, E.JULY, "4A")["rows"][0]["id"]
        E._cancel_on(mp, first, "2025-07-20")
        a = _detail(books, E.JULY, "4A")
        b1 = _detail(books, E.JULY, "4B1")
        assert first not in [r["id"] for r in a["rows"]], (
            "a bill cancelled inside the period is not available credit"
        )
        assert first not in [r["id"] for r in b1["rows"]], (
            "nor is it a reversal — 4(A) never claimed it"
        )
    finally:
        mp.undo()


def test_a_bill_cancelled_in_a_LATER_period_is_a_4b1_row_there(books):
    """The case 4(B)(1) exists for: credit availed in July, given back in
    August. Apex's real instance was four February bills cancelled on 17 July
    2026, reversing Rs 88,141.67 the return could not see."""
    mp = MonkeyPatch()
    try:
        first = _detail(books, E.JULY, "4A")["rows"][0]["id"]
        E._cancel_on(mp, first, "2025-08-15")
        august = _detail(books, "082025", "4B1")
        assert first in [r["id"] for r in august["rows"]], (
            "credit availed in July and cancelled in August is an August reversal"
        )
        assert august["total_cgst_paise"] > 0
    finally:
        mp.undo()


def test_the_4b1_detail_sums_to_the_permanent_reversal_in_the_return(books):
    """In the period where the reversal actually lands."""
    mp = MonkeyPatch()
    try:
        E._cancel_on(mp, _detail(books, E.JULY, "4A")["rows"][0]["id"], "2025-08-15")
        ret = grs.gstr3b_from_books(books, E.FIRM, "CLI", "082025", E.GSTIN)
        perm = ret["working"]["itc_reversal"]["permanent_paise"]
        d = _detail(books, "082025", "4B1")
        assert d["total_cgst_paise"] == perm["cgst_paise"]
        assert d["total_sgst_paise"] == perm["sgst_paise"]
        assert d["total_igst_paise"] == perm["igst_paise"]
        assert perm["cgst_paise"] > 0, "the fixture must actually reverse something"
    finally:
        mp.undo()


def test_a_reclaimable_reversal_line_is_empty_when_the_register_is(books):
    """4(B)(2) is registered, not derived. No register rows means no detail, and
    that has to be a clean empty rather than an exception."""
    d = _detail(books, E.JULY, "4B2")
    assert d["count"] == 0


# ── The scope guard ─────────────────────────────────────────────────────────

def test_a_different_period_returns_a_different_set(books):
    """The negative control for every 'it sums' test above: if the period bound
    were ignored, they would all pass while showing the whole ledger."""
    june = _detail(books, E.JUNE, "4A")
    july = _detail(books, E.JULY, "4A")
    assert june["count"] == 0
    assert july["count"] == 2


# ── A credit note must REDUCE, and be seen to ───────────────────────────────
#
# The first pass of this file had no note in any fixture, so deleting `sign=-1`
# from the code changed nothing and every test still passed. A sign rule nothing
# exercises is not a tested rule, so the notes are seeded explicitly below.

def _seed_sales(db, no, date, taxable, cgst, sgst):
    db.seed("customers", {"id": "CUS1", "firm_id": E.FIRM, "client_id": "CLI",
                          "name": "Buyer", "state_code": "27", "gstin": None})
    return db.seed("client_sales_invoices", {
        "firm_id": E.FIRM, "client_id": "CLI", "customer_id": "CUS1",
        "invoice_no": no, "invoice_date": date, "status": "issued",
        "taxable_amount_paise": taxable, "cgst_paise": cgst, "sgst_paise": sgst,
        "igst_paise": 0, "cess_paise": 0, "is_interstate": False,
        "supply_state_code": "27", "supply_type": "taxable", "deleted_at": None,
    })


def _seed_credit_note(db, no, date, taxable, cgst, sgst, parent_id):
    return db.seed("credit_notes", {
        "firm_id": E.FIRM, "client_id": "CLI", "customer_id": "CUS1",
        "credit_note_no": no, "credit_note_date": date, "status": "issued",
        "taxable_amount_paise": taxable, "cgst_paise": cgst, "sgst_paise": sgst,
        "igst_paise": 0, "cess_paise": 0, "is_interstate": False,
        "invoice_id": parent_id, "deleted_at": None,
    })


def test_a_credit_note_is_listed_as_a_reduction(books):
    """CGST §34: a credit note reduces outward tax. Listed positive it would
    inflate the detail by twice its value against a summary that netted it."""
    inv = _seed_sales(books, "S-1", "2025-07-05", 100000, 9000, 9000)
    _seed_credit_note(books, "CN-1", "2025-07-20", 40000, 3600, 3600, inv["id"])

    d = _detail(books, E.JULY, "3.1a")
    note = [r for r in d["rows"] if r["kind"] == "Credit note"]
    assert len(note) == 1
    assert note[0]["taxable_paise"] == -40000, "a credit note must carry a minus"
    assert note[0]["cgst_paise"] == -3600
    assert d["total_taxable_paise"] == 60000, "100,000 invoiced less 40,000 credited"


def test_the_31a_detail_with_a_note_still_sums_to_the_return(books):
    """The property the sign exists to preserve, asserted against the summary
    rather than against a number typed into this file."""
    inv = _seed_sales(books, "S-1", "2025-07-05", 100000, 9000, 9000)
    _seed_credit_note(books, "CN-1", "2025-07-20", 40000, 3600, 3600, inv["id"])

    ret = E._3b(books, E.JULY)
    d = _detail(books, E.JULY, "3.1a")
    out = ret["working"]["outward"]
    assert d["total_taxable_paise"] == out["taxable_value_paise"]
    assert d["total_cgst_paise"] == out["taxable_cgst_paise"]
    assert d["total_sgst_paise"] == out["taxable_sgst_paise"]
