"""
SALES-31, SALES-32, SALES-10 and SALES-07 — from the 12 September probe pass.

Four defects in the sales cycle, and three of them are the same shape: an
engine that works, a field that is declared, and a path that does not carry it.

  SALES-31  the place of supply had TWO resolutions — mock read
            `place_of_supply or supply_state_code`, the real create path read
            only the second — and no validator on either.
  SALES-32  §206C(1H)'s registry comment still said "unchanged, 0.1%" a year
            after the charge ceased to operate.
  SALES-10  the §37(3) amendment path emitted three empty strings for an
            export's shipping bill, which the main build has carried since
            migration 349.
  SALES-07  the receipt form never sent `tds_paise`, so a customer's §194J
            withholding left the invoice looking part-unpaid.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from domain.gst import amendments, exception_report
from domain.gst import place_of_supply as pos

WEB = Path("../web")


# ── SALES-31: one place of supply, resolved in one place ─────────────────────

def test_a_stated_place_of_supply_outranks_everything_derived():
    """CGST Rule 46(n) makes it a particular of the document."""
    code, source = pos.recipient_place_of_supply(
        stated="29", customer={"state_code": "27"}, supplier_state="27")
    assert (code, source) == ("29", pos.SOURCE_STATED)


def test_the_supplier_state_is_the_last_resort_and_not_the_first():
    """IGST §12(2)(b)(ii) — the unregistered walk-in with no address. It has to
    be LAST, or a registered customer in another state is billed CGST+SGST."""
    code, source = pos.recipient_place_of_supply(
        stated=None, customer={"state_code": "29"}, supplier_state="27")
    assert (code, source) == ("29", pos.SOURCE_CUSTOMER_STATE)


def test_an_unknown_place_of_supply_is_not_dressed_up_as_a_state():
    assert pos.recipient_place_of_supply(
        stated=None, customer={}, supplier_state=None) == ("", pos.SOURCE_UNKNOWN)


def test_both_spellings_of_the_field_reach_the_same_resolution():
    """`SalesInvoiceIn` declares `supply_state_code` AND `place_of_supply`, and
    the real create path used to read only the first while the mock branch read
    both. A divergence between the two branches is the one kind of defect a
    test suite structurally cannot see, so the router now reads one value and
    the model refuses a request whose two disagree."""
    import inspect
    import routers.sales_invoices as si

    src = inspect.getsource(si._create_invoice_core)
    src_no_comments = re.sub(r"#[^\n]*", "", src)
    assert 'data.get("place_of_supply")' in src_no_comments, (
        "the real create path is ignoring `place_of_supply` again — a caller "
        "who fills it in gets their answer honoured under test and discarded "
        "in production")
    assert "recipient_place_of_supply(" in src_no_comments, (
        "the four-source chain belongs in domain/gst/place_of_supply.py, where "
        "both branches call the same one")


def test_two_disagreeing_places_of_supply_are_refused():
    from models.invoices import SalesInvoiceIn
    line = {"service_catalogue_id": "SVC-1", "description": "x", "quantity": 1,
            "rate_paise": 100, "gst_rate_bps": 1800}
    with pytest.raises(Exception) as exc:
        SalesInvoiceIn(client_id="c", customer_id="k", invoice_no="INV-1",
                       invoice_date="2025-06-01", lines=[line],
                       place_of_supply="27", supply_state_code="29")
    assert "disagree" in str(exc.value)


def test_the_same_place_of_supply_twice_is_fine():
    from models.invoices import SalesInvoiceIn
    line = {"service_catalogue_id": "SVC-1", "description": "x", "quantity": 1,
            "rate_paise": 100, "gst_rate_bps": 1800}
    inv = SalesInvoiceIn(client_id="c", customer_id="k", invoice_no="INV-1",
                         invoice_date="2025-06-01", lines=[line],
                         place_of_supply="27", supply_state_code="27")
    assert inv.place_of_supply == "27"


@pytest.mark.parametrize("field", ["place_of_supply", "supply_state_code"])
def test_a_place_of_supply_that_is_not_a_state_is_refused(field):
    """`ReceiptIn.place_of_supply` has been validated since GST-15 and the
    invoice's two spellings of the same field were not, so a typo reached the
    document, the ledger and the return."""
    from models.invoices import SalesInvoiceIn
    line = {"service_catalogue_id": "SVC-1", "description": "x", "quantity": 1,
            "rate_paise": 100, "gst_rate_bps": 1800}
    with pytest.raises(Exception) as exc:
        SalesInvoiceIn(client_id="c", customer_id="k", invoice_no="INV-1",
                       invoice_date="2025-06-01", lines=[line], **{field: "99"})
    assert "not a GST state code" in str(exc.value)


def test_the_correction_path_validates_it_too():
    """A validator only at the create door is one PATCH away from being none."""
    from models.invoices import SalesInvoiceUpdateIn
    with pytest.raises(Exception):
        SalesInvoiceUpdateIn(supply_state_code="99")
    assert SalesInvoiceUpdateIn(supply_state_code="27").supply_state_code == "27"


def test_a_customer_gstin_names_its_state_even_with_a_bad_check_digit():
    """The question is WHICH STATE, not whether the registration number is
    well-formed. Falling through to the supplier's state on a bad check digit
    would silently turn an inter-state supply intra-state."""
    code, source = pos.recipient_place_of_supply(
        stated=None, customer={"gstin": "29AABCU9603R1ZM"}, supplier_state="24")
    assert (code, source) == ("29", pos.SOURCE_CUSTOMER_GSTIN)
    # Garbage is still refused, so nothing becomes a state that is not one.
    assert pos.recipient_place_of_supply(
        stated=None, customer={"gstin": "ZZZZ"},
        supplier_state="24") == ("24", pos.SOURCE_SUPPLIER_STATE)


# ── SALES-32: §206C(1H) ceased to operate on 01-04-2025 ──────────────────────

def test_the_cessation_is_a_named_constant_not_a_rate_gap():
    """`rate_gap` means "this LIMB's own rate is not held and the parent's is
    used instead", and
    tests/test_a_section_with_two_limbs_says_which_one_it_priced.py holds it to
    exactly that. "The charge ceased to operate" is a different fact, so it
    gets the shape §206AB's omission already has — a named constant, so
    confirming or correcting an `[S]`-graded reading is a one-line change."""
    from domain.tds import section_rates
    assert section_rates.SECTION_206C_1H_CEASED_FROM_FY == "2025-26"
    assert section_rates.rate_gap_for("206C", "2025-26") is None


def test_the_registry_records_the_cessation_where_the_rate_is():
    """Not a text scan for the phrase it replaced — the corrected comment
    QUOTES that phrase, and a raw scan cannot tell a quotation from a claim.
    What is asserted is that the cessation is written down beside the rate,
    and reachable from code rather than only from a comment."""
    src = Path("domain/tds/section_rates.py").read_text()
    # The ENTRY's own comment block, not the file. A reader looking at the
    # 0.1% has to see it there; a sentence a hundred lines away beside the
    # constant is not where the misreading happens.
    entry = src[src.index("# TCS on sale of goods"):src.index('"206C":')].lower()
    assert "ceased to operate" in entry
    assert "01-04-2025" in entry
    assert "194q" in entry, (
        "the overlap is resolved in §194Q's favour and a reader needs to know "
        "which section now applies")


def test_the_historic_rate_is_kept_because_an_earlier_year_still_uses_it():
    """A belated or revised 27EQ for FY 2024-25 is filed at 0.1% — the same
    fork shape as the TDS vocabulary and §206AB."""
    from domain.tds import section_rates
    rates = section_rates.tds_rates_for("2025-26")
    assert rates.sections["206C"].individual_rate_bps == 10


def test_a_vendor_still_cannot_be_marked_tcs():
    """SALES-32 is the comment half. The refusal is the other half and stays."""
    from domain.tds.residency import deduction_section_refusal
    assert deduction_section_refusal("206C")


# ── SALES-10: an export amendment carries its shipping bill ──────────────────

_EXPORT_PAYLOAD = {
    "exp": [{
        "exp_typ": "WPAY",
        "inv": [{
            "inum": "EXP-1", "idt": "01-06-2025", "val": 100000.0,
            "sbpcode": "INMAA1", "sbnum": "1234567", "sbdt": "05-06-2025",
            "itms": [{"itm_det": {"txval": 100000.0, "iamt": 18000.0,
                                  "camt": 0.0, "samt": 0.0, "csamt": 0.0}}],
        }],
    }],
}


def _books_payload(taxable: float) -> dict:
    import copy
    out = copy.deepcopy(_EXPORT_PAYLOAD)
    out["exp"][0]["inv"][0]["itms"][0]["itm_det"]["txval"] = taxable
    return out


def test_the_index_carries_an_exports_shipping_bill():
    docs = exception_report.index_documents(_EXPORT_PAYLOAD)
    entry = next(iter(docs.values()))
    assert entry["shipping_bill"] == {
        "sbpcode": "INMAA1", "sbnum": "1234567", "sbdt": "05-06-2025"}


def test_a_non_export_carries_none_rather_than_three_blanks():
    """Only Table 6A has these fields; a b2b entry with three empty strings
    would read as an export whose shipping bill is not recorded."""
    b2b = {"b2b": [{"ctin": "27AABCU9603R1ZM", "inv": [{
        "inum": "INV-1", "idt": "01-06-2025", "inv_typ": "R",
        "itms": [{"itm_det": {"txval": 100.0}}]}]}]}
    entry = next(iter(exception_report.index_documents(b2b).values()))
    assert entry["shipping_bill"] is None


def test_an_amended_export_re_declares_its_shipping_bill():
    """§37(3) re-declares the WHOLE entry, so an amendment built without the
    shipping bill replaces a filed export that had one with one that does not
    — and CGST Rule 96(1) matches the refund against exactly those fields."""
    from domain.gst.amendment_proposal import propose
    report = exception_report.compare_payloads(
        _EXPORT_PAYLOAD, _books_payload(90000.0))
    changed = report["documents"]["amount_changed"]
    assert changed, "the fixture must produce an amount change to amend"
    proposal = propose(report, original_period="062025")
    node = proposal["entries"][0]["node"]
    assert node["sbpcode"] == "INMAA1"
    assert node["sbnum"] == "1234567"
    assert node["sbdt"] == "05-06-2025"


def test_an_export_with_no_shipping_bill_recorded_still_amends_to_blanks():
    """The portal accepts an export declared before the shipping bill exists,
    so "" is a real recorded state and not a failure."""
    node = amendments.build_invoice_amendment(
        original_no="EXP-1", original_date="2025-06-01", section="expa",
        corrected={"taxable_paise": 100, "igst_paise": 0, "cgst_paise": 0,
                   "sgst_paise": 0, "cess_paise": 0})
    assert node["sbpcode"] == node["sbnum"] == node["sbdt"] == ""


def test_a_b2b_amendment_does_not_grow_shipping_bill_keys():
    node = amendments.build_invoice_amendment(
        original_no="INV-1", original_date="2025-06-01", section="b2ba",
        corrected={"taxable_paise": 100, "igst_paise": 0, "cgst_paise": 0,
                   "sgst_paise": 0, "cess_paise": 0},
        shipping_bill={"sbpcode": "INMAA1", "sbnum": "1", "sbdt": "x"})
    assert "sbpcode" not in node


# ── SALES-07: the receipt carries the customer's TDS ─────────────────────────

def _receipt_form() -> str:
    page = (WEB / "app/clients/[id]/sales/page.tsx").read_text()
    start = page.index("function ReceiptForm") if "function ReceiptForm" in page \
        else page.index('const amountPaise = paiseFromRupeeInput(amount || "0");')
    return page[start:]


def test_the_receipt_payload_sends_the_tds():
    form = _receipt_form()
    body = form[form.index('"/api/receipts/"'):form.index("if (!result.success)")]
    assert "tds_paise" in body, (
        "ReceiptIn.tds_paise and receipt_service have handled this since the "
        "model was written — the journal is Dr Bank + Dr TDS Receivable / Cr "
        "Trade Receivables and the settlement is amount + TDS — and no screen "
        "filled it in")


def test_the_typed_tds_goes_through_the_one_money_parser():
    form = _receipt_form()
    assert "paiseFromRupeeInput(tds" in form, (
        'parseFloat("1,25,000") is 1, and a receipt is cash the client banked')


def test_the_settlement_and_not_the_cash_measures_what_is_unallocated():
    """The server's over-allocation refusal is amount + TDS, so measuring
    against the cash alone showed a receipt with TDS as over-allocated on a
    screen the server would have accepted."""
    form = _receipt_form()
    assert "settlementPaise" in form
    assert "amountPaise - totalAllocated" not in form


def test_tds_is_refused_on_a_foreign_receipt_before_the_round_trip():
    """`create_foreign_receipt` raises 422 for any non-zero TDS. Offering a box
    whose only outcome is a rejection is worse than not having one."""
    form = _receipt_form()
    assert "isForeign && tdsPaise > 0" in form
    assert "{!isForeign && (" in form, "the box must be hidden on a foreign receipt"


def test_the_server_still_refuses_tds_on_a_foreign_receipt():
    """The screen's guard is the same rule said earlier, never instead."""
    src = Path("services/receipt_service.py").read_text()
    assert "TDS on a foreign receipt is not supported yet" in src


def test_the_field_comment_names_the_right_deductor():
    """It said "deducted by the client on the firm fee", which is the CA firm's
    own billing. This is the CLIENT's sales receipt and the deductor is the
    client's customer."""
    src = Path("models/invoices.py").read_text()
    assert "TDS deducted by the client on the firm fee" not in src
    assert "the deductor is the\n    # client's customer" in src
