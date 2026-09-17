"""
GST-18 — GSTR-1 Table 13 declares SERIAL RANGES, and the builder emitted a count.

WHAT WAS WRONG
    `_build_doc_summary` emitted, per nature,

        {"num": count, "cancel": 0, "net_issue": count}

    and three of those four were wrong.

      * `num` is the ROW's index within the nature — Table 13 allows several
        ranges per nature and numbers them 1, 2, 3 — not a count of documents.
        `totnum` is the count, and `grep totnum apps/api` returned nothing.
      * `from` and `to` were absent entirely. They are the point of the table:
        it declares the range of numbers ISSUED, which is how CGST Rule 46(b)'s
        "consecutive serial number ... unique for a financial year" is checked
        against what was actually filed.
      * `cancel` was a literal 0 for every client and every period, so
        `net_issue` was always the whole count. A cancelled invoice is exactly
        what this table exists to declare: the number was consumed and no
        supply was made under it.

THE INVARIANT THIS FILE EXISTS TO HOLD
    `totnum == to - from + 1` on every numbered row, because the rows ARE the
    contiguous runs. A single row spanning the lowest to the highest number
    would break it the moment a client runs two series in one month, which
    Rule 46(b) expressly allows.
"""
from __future__ import annotations

import pytest

from domain.gst import document_series as ds
from domain.gst.classifier import GSTInvoiceCategory
from domain.gst.gstr1_builder import (
    GAP_CANCELLED_NOT_READ, CancelledDocument, InvoiceForGSTR1,
    _build_doc_summary, build_gstr1,
)

D = ds.IssuedDocument


# ── The ranges ───────────────────────────────────────────────────────────────

def test_a_run_of_consecutive_numbers_is_ONE_row():
    rows = ds.ranges_for([D("INV/2026-27/0001"), D("INV/2026-27/0002"),
                          D("INV/2026-27/0003")])
    assert len(rows) == 1
    assert rows[0] == {"num": 1, "from": "INV/2026-27/0001",
                       "to": "INV/2026-27/0003", "totnum": 3, "cancel": 0,
                       "net_issue": 3}


def test_a_gap_in_the_series_becomes_TWO_rows():
    # Not one row spanning 1..7 with totnum 5 — that declares two numbers
    # nobody issued. Table 13's several-rows-per-nature shape is for exactly
    # this, and a gap is what Rule 46(b)'s "consecutive" is checked against.
    rows = ds.ranges_for([D("INV/1"), D("INV/2"), D("INV/7")])
    assert [(r["from"], r["to"], r["totnum"]) for r in rows] == [
        ("INV/1", "INV/2", 2), ("INV/7", "INV/7", 1)]


def test_two_series_are_two_rows_and_never_one_span():
    # Rule 46(b) allows "one or multiple series". A single row from EXP/001 to
    # INV/042 contains documents from neither.
    rows = ds.ranges_for([D("EXP/2026-27/001"), D("INV/2026-27/0001"),
                          D("INV/2026-27/0002")])
    assert [r["from"] for r in rows] == ["EXP/2026-27/001", "INV/2026-27/0001"]
    assert [r["totnum"] for r in rows] == [1, 2]


@pytest.mark.parametrize("numbers", [
    ["INV/1", "INV/2", "INV/3"],
    ["INV/1", "INV/5", "INV/6", "INV/9"],
    ["A/1", "B/1", "B/2"],
    ["INV/0007", "INV/0008"],
])
def test_totnum_is_always_the_span(numbers):
    """The invariant. A row whose count disagrees with its own range is a row
    the portal's own totals check rejects."""
    for r in ds.ranges_for([D(n) for n in numbers]):
        head_from, seq_from = ds.split_number(r["from"])
        head_to, seq_to = ds.split_number(r["to"])
        assert head_from == head_to
        assert r["totnum"] == seq_to - seq_from + 1


def test_num_is_the_ROW_index_not_a_count():
    rows = ds.ranges_for([D("INV/1"), D("INV/2"), D("INV/9")])
    assert [r["num"] for r in rows] == [1, 2]


def test_the_number_is_declared_AS_WRITTEN():
    # A series padded to four digits writes 0007. Rebuilding it from the head
    # and the integer would declare INV/7, which appears on no document.
    rows = ds.ranges_for([D("INV/2026-27/0007"), D("INV/2026-27/0008")])
    assert rows[0]["from"] == "INV/2026-27/0007"
    assert rows[0]["to"] == "INV/2026-27/0008"


def test_a_number_with_no_trailing_digit_is_its_own_range_of_one():
    rows = ds.ranges_for([D("ADHOC-NOTE")])
    assert rows == [{"num": 1, "from": "ADHOC-NOTE", "to": "ADHOC-NOTE",
                     "totnum": 1, "cancel": 0, "net_issue": 1}]


def test_no_documents_is_no_rows():
    assert ds.ranges_for([]) == []


# ── Cancellation ─────────────────────────────────────────────────────────────

def test_a_cancelled_document_is_COUNTED_in_the_range_and_netted_out():
    # Its number WAS issued — that is why it is in from..to — and no supply
    # was made under it, which is why net_issue drops.
    rows = ds.ranges_for([D("INV/1"), D("INV/2", is_cancelled=True), D("INV/3")])
    assert rows[0]["totnum"] == 3
    assert rows[0]["cancel"] == 1
    assert rows[0]["net_issue"] == 2


def test_a_cancelled_duplicate_keeps_the_cancellation():
    # A number repeated in one period is a real conflict for the CA (migration
    # 151's per-client uniqueness). Whichever row arrives second must not
    # silently un-cancel the other.
    rows = ds.ranges_for([D("INV/1", is_cancelled=True), D("INV/1")])
    assert rows[0]["cancel"] == 1
    rows = ds.ranges_for([D("INV/1"), D("INV/1", is_cancelled=True)])
    assert rows[0]["cancel"] == 1


def test_every_document_cancelled_nets_to_zero():
    rows = ds.ranges_for([D("INV/1", True), D("INV/2", True)])
    assert rows[0]["totnum"] == 2 and rows[0]["net_issue"] == 0


# ── What the builder files ───────────────────────────────────────────────────

def _inv(ref, ttype="sales_invoice"):
    return InvoiceForGSTR1(
        id=ref, transaction_type=ttype, reference_no=ref,
        transaction_date="2026-06-10", party_gstin="27AAACI1195H1ZT",
        party_name="Acme", place_of_supply="27", is_interstate=False,
        taxable_amount_paise=100_000, cgst_paise=9_000, sgst_paise=9_000,
        igst_paise=0, cess_paise=0, is_reverse_charge=False,
        invoice_type="Regular", supply_type="B2B",
        gst_invoice_category=GSTInvoiceCategory.B2B,
        original_invoice_ref=None, original_invoice_date=None, lines=[])


def test_the_nature_keeps_the_forms_own_position():
    # doc_num is `_DOC_NATURES.index + 1`, fixed by the form: Debit Note is 4
    # and Credit Note 5, whatever the period happens to contain.
    out = _build_doc_summary([_inv("CN/1", "credit_note"),
                              _inv("DN/1", "debit_note")])
    assert [(d["doc_num"], d["doc_typ"]) for d in out] == [
        (4, "Debit Note"), (5, "Credit Note")]


def test_the_builder_files_the_range_not_a_count():
    out = _build_doc_summary([_inv("INV/1"), _inv("INV/2"), _inv("INV/3")])
    assert out[0]["docs"] == [{"num": 1, "from": "INV/1", "to": "INV/3",
                               "totnum": 3, "cancel": 0, "net_issue": 3}]


def test_a_cancelled_invoice_reaches_Table_13_and_no_other_table():
    out = build_gstr1([_inv("INV/1")], gstin="27AAACI1195H1ZT", period="062026",
                      cancelled_documents=[CancelledDocument("INV/2", "sales_invoice")])
    docs = out.payload["doc_issue"]["doc_det"][0]["docs"][0]
    assert docs["totnum"] == 2 and docs["cancel"] == 1 and docs["net_issue"] == 1
    # It carries no taxable value, so nothing else may have moved.
    assert out.payload["b2b"][0]["inv"][0]["inum"] == "INV/1"
    assert len(out.payload["b2b"][0]["inv"]) == 1


def test_a_transaction_type_with_no_nature_is_SKIPPED_not_miscounted():
    # It used to fall through an if/elif chain; a map makes an unmapped type
    # absent rather than counted as an outward-supply invoice.
    out = _build_doc_summary([_inv("RCPT/1", "receipt_voucher")])
    assert out == []


# ── "Nobody looked" is not "none were cancelled" ─────────────────────────────

def test_supplying_NOTHING_names_the_gap():
    out = build_gstr1([_inv("INV/1")], gstin="27AAACI1195H1ZT", period="062026")
    assert GAP_CANCELLED_NOT_READ in {g["kind"] for g in out.gaps}


def test_supplying_an_EMPTY_list_is_somebody_having_looked():
    out = build_gstr1([_inv("INV/1")], gstin="27AAACI1195H1ZT", period="062026",
                      cancelled_documents=[])
    assert GAP_CANCELLED_NOT_READ not in {g["kind"] for g in out.gaps}
    assert out.payload["doc_issue"]["doc_det"][0]["docs"][0]["cancel"] == 0


def test_a_return_with_no_documents_says_nothing_about_cancellations():
    # No Table 13 at all, so there is no nil to misread.
    out = build_gstr1([], gstin="27AAACI1195H1ZT", period="062026")
    assert GAP_CANCELLED_NOT_READ not in {g["kind"] for g in out.gaps}


def test_the_service_reads_cancelled_invoices_and_nothing_else_can_be():
    # `client_sales_invoices.status` admits 'cancelled' (migration 050);
    # `credit_notes.status` is CHECKed to draft/issued/applied and
    # `sales_debit_notes.status` to draft/issued. A note recorded in error is
    # discarded while still a draft, and a draft consumed no number.
    import inspect

    from services import gst_return_service as svc

    assert svc._CANCELLABLE_NATURES == ("sales_invoice",)
    src = inspect.getsource(svc._cancelled_sales)
    assert 'eq("status", "cancelled")' in src
    assert "client_sales_invoices" in src
