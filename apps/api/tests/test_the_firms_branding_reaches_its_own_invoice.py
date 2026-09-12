"""SALES-13 — a full Settings UI wrote branding that nothing ever read.

WHAT WAS WRONG
    routers/branding.py persists a logo, secondary logo, tagline, three colours
    and a font (firm_branding); five invoice template types with logo, header,
    footer and signature placement (invoice_templates); and bank_name,
    account_number, account_holder, ifsc_code, upi_id, upi_qr_url and
    footer_text (invoice_settings). Two Settings screens write all of it.

    `grep -rn "branding" apps/api/services apps/api/routers apps/api/domain`
    returned ONLY routers/branding.py. No consumer. So a CA could upload their
    logo, set their accent colour, record their bank account and write a
    footer, and every invoice came out with a fixed #1f2937 header and no way
    for the client to pay it.

THE FINDING'S SUGGESTED FIX IS WRONG, AND THIS IS WHY
    It says "load firm_branding + invoice_settings in get_sales_invoice_pdf".
    That is the PRACTICE's branding on the CLIENT's sales invoice — a document
    the practice is not a party to. Its supplier is the client, its recipient
    is the client's customer, and putting the accountant's bank account on it
    asks that customer to pay the accountant.

    It is the same confusion three commits have already fixed: the sales
    invoice supplier, the customer statement's account holder, and the payslip
    employer. So the branding goes on the FEE invoice, where the practice
    genuinely is the supplier, and this file pins that it goes nowhere else.

    The client's OWN branding would be a different store, and `clients` has no
    logo, bank, UPI or footer column at all — that half is a migration and a
    client-settings screen, not a wiring job, and it is not done here.
"""
from __future__ import annotations

import io

import pdfplumber
import pytest

from services.invoice_pdf_service import (
    _accent_colour, _load_branding, _logo, _remote_image,
    build_invoice_pdf, build_sales_invoice_pdf,
)


FIRM = {"id": "F1", "name": "Gupta & Associates, Chartered Accountants",
        "gstin": "27AAAAA0000A1Z2", "address": "12 MG Road, Pune 411001"}
CLIENT = {"id": "C1", "client_name": "Acme Manufacturing",
          "legal_name": "Acme Manufacturing Private Limited",
          "gstin": "27BBBBB1111B1ZN", "address_line1": "9 Industrial Estate",
          "city": "Pune", "state": "Maharashtra", "pincode": "411018",
          "state_code": "27"}
CUSTOMER = {"id": "CU1", "name": "Zeta Traders", "gstin": "29CCCCC2222C1Z5"}
INVOICE = {"invoice_no": "INV-001", "invoice_date": "2026-06-01",
           "status": "issued", "total_paise": 118_000_00,
           "taxable_amount_paise": 100_000_00, "cgst_paise": 9_000_00,
           "sgst_paise": 9_000_00, "supply_state_code": "27"}

BRANDING = {
    "tagline": "Chartered Accountants since 1994",
    "primary_color": "#0F766E",
    "bank_name": "HDFC Bank, Camp Branch",
    "account_holder": "Gupta & Associates",
    "account_number": "50200012345678",
    "ifsc_code": "HDFC0001234",
    "upi_id": "guptaassociates@hdfcbank",
    "footer_text": "Payment due within 15 days. Interest at 18% p.a. thereafter.",
}


def _text(pdf: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return "\n".join(page.extract_text() or "" for page in doc.pages)


# ─────────── the practice's own invoice carries the practice's branding ──────

def test_the_fee_invoice_carries_the_bank_details_and_the_footer():
    text = _text(build_invoice_pdf(INVOICE, FIRM, CLIENT, None, branding=BRANDING))
    for expected in ("Payment Details", "HDFC Bank, Camp Branch", "50200012345678",
                     "HDFC0001234", "guptaassociates@hdfcbank",
                     "Chartered Accountants since 1994",
                     "Payment due within 15 days"):
        assert expected in text, f"{expected!r} is not on the fee invoice"


def test_a_firm_with_no_branding_still_gets_a_valid_invoice():
    """Every one of these settings is optional, and a tax invoice without them
    is still a Rule 46 tax invoice."""
    text = _text(build_invoice_pdf(INVOICE, FIRM, CLIENT))
    assert "TAX INVOICE" in text
    assert "Gupta & Associates" in text
    assert "Payment Details" not in text


# ─────────── and the CLIENT's invoice carries none of it ───────────

def test_the_practice_never_appears_on_a_clients_sales_invoice():
    """The one that matters. This document's supplier is the client and its
    recipient is the client's customer; the accountant's bank account on it
    would ask that customer to pay the accountant."""
    text = _text(build_sales_invoice_pdf(INVOICE, CLIENT, CUSTOMER))
    for absent in ("Gupta & Associates", "HDFC Bank", "50200012345678",
                   "guptaassociates@hdfcbank", "Payment due within 15 days"):
        assert absent not in text, f"{absent!r} reached the client's sales invoice"
    assert "Acme Manufacturing" in text
    assert "Zeta Traders" in text


def test_the_sales_invoice_builder_takes_no_branding_argument():
    """Pinned as a SIGNATURE, not as an absence in one rendering. A future
    caller must not be able to pass the practice's branding to it at all."""
    import inspect
    assert "branding" not in inspect.signature(build_sales_invoice_pdf).parameters
    assert "branding" in inspect.signature(build_invoice_pdf).parameters


# ─────────── a document builder must not fall over on a bad setting ─────────

def test_a_colour_that_is_not_a_colour_is_no_colour_rather_than_a_crash():
    assert _accent_colour("#0F766E") is not None
    for bad in ("teal", "#GGGGGG", "#0F766", "", None, 12345):
        assert _accent_colour(bad) is None, bad


def test_an_image_url_that_cannot_be_fetched_is_simply_absent():
    """A NETWORK CALL INSIDE A DOCUMENT BUILDER, so every failure is None. An
    invoice without a logo is a valid tax invoice; one that never renders is
    not."""
    assert _logo(None) is None
    assert _logo("") is None
    assert _logo("/local/path.png") is None, "only http(s) is fetched"
    assert _logo("file:///etc/passwd") is None, "a non-http scheme is refused"
    assert _remote_image("https://127.0.0.1:1/nope.png",
                         max_width_mm=10, max_height_mm=10) is None


def test_an_invoice_renders_even_when_the_logo_url_is_dead():
    text = _text(build_invoice_pdf(
        INVOICE, FIRM, CLIENT, None,
        branding={**BRANDING, "logo_url": "https://127.0.0.1:1/logo.png"}))
    assert "TAX INVOICE" in text
    assert "HDFC0001234" in text, "the rest of the branding still rendered"


def test_the_upi_qr_is_fetched_as_an_image_and_never_encoded_as_data():
    """upi_qr_url is an uploaded IMAGE. Passing it to the QR encoder would
    encode the URL STRING, and scanning that opens a web page instead of
    starting a payment."""
    import inspect
    src = inspect.getsource(build_invoice_pdf.__globals__["_render_tax_invoice"])
    assert "_qr_flowable(brand" not in src
    assert '_remote_image(brand.get("upi_qr_url")' in src


def test_branding_that_cannot_be_loaded_is_an_empty_dict():
    assert _load_branding(None) == {}
