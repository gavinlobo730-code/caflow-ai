"""
Rule 46(r): the QR code with the embedded IRN, and only where one exists.

WHAT WAS MISSING
    services/invoice_pdf_service.py renders every other Rule 46 particular and
    lists them all in its header. The QR with the embedded IRN was absent —
    the word "irn" appeared nowhere in the module — although einvoice_records
    has held irn, ack_number, ack_date and qr_data since it was created.

WHAT MAY NEVER BE PRINTED
    An IRN is minted by the Invoice Registration Portal and by nothing else.
    This application PREPARES e-invoices (CLAUDE.md: "prepare-only
    e-invoice/e-way/XBRL rails") and einvoice_service.record_irn_generated
    exists to record that "CA has generated IRN on the government portal". It
    is the only writer of those four columns and it sets status "generated".

    So "generated" plus an IRN is a real one and printing it is Rule 46(r).
    Anything else carries none, and a simulated or composed IRN on a document
    that goes to the recipient is a fabricated statutory particular — the same
    line the filing demo holds, for the same reason.

    The QR likewise comes from the IRP's own signed payload, verbatim. It is
    NOT built from the invoice's fields: the whole value of the QR is that it
    carries the portal's signature, and one this application composed would
    scan and verify as nothing.
"""
from __future__ import annotations

import pytest

from services.invoice_pdf_service import (_einvoice_particulars, _qr_flowable,
                                          build_sales_invoice_pdf)

REAL = {
    "status": "generated",
    "irn": "a5c12b8f9d3e4a7b6c1d0e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b",
    "ack_number": "112410036789012",
    "ack_date": "2025-05-14T10:22:31+05:30",
    "qr_data": "eyJhbGciOiJSUzI1NiJ9.SIGNED-BY-THE-IRP.xxx",
}


# ── What is printed ─────────────────────────────────────────────────────────

def test_a_recorded_irn_is_carried_through():
    out = _einvoice_particulars(REAL)
    assert out["irn"] == REAL["irn"]
    assert out["ack_number"] == "112410036789012"
    assert out["ack_date"] == "2025-05-14"
    assert out["qr_data"] == REAL["qr_data"]


def test_the_qr_is_the_portals_payload_and_not_a_composition():
    """Rendered from qr_data verbatim. A QR built from the invoice's own fields
    would carry no signature and verify as nothing."""
    import inspect
    src = inspect.getsource(_qr_flowable)
    assert "qr_data" in src
    for invented in ("invoice_no", "gstin", "total_paise", "irn"):
        assert invented not in src, (
            f"the QR must be the IRP's payload; {invented} has no business "
            f"being encoded into it here")


def test_the_qr_renders():
    d = _qr_flowable(REAL["qr_data"])
    assert d is not None
    assert d.width > 0 and d.height > 0


# ── What is never printed ───────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["draft", "cancelled", "failed", "simulated", ""])
def test_no_irn_is_printed_unless_the_portal_generated_it(status):
    assert _einvoice_particulars({**REAL, "status": status}) == {}


def test_a_generated_record_with_no_irn_prints_nothing():
    """A contradiction, and the safe reading is that nothing was generated."""
    assert _einvoice_particulars({**REAL, "irn": None}) == {}
    assert _einvoice_particulars({**REAL, "irn": ""}) == {}


def test_no_record_at_all_prints_nothing():
    """The NORMAL case — e-invoicing applies by turnover, so most invoices on
    most clients have no record. It must cost the invoice nothing."""
    assert _einvoice_particulars(None) == {}
    assert _einvoice_particulars({}) == {}


def test_a_missing_qr_payload_does_not_stop_the_irn_being_printed():
    out = _einvoice_particulars({**REAL, "qr_data": None})
    assert out["irn"] == REAL["irn"]
    assert out["qr_data"] is None
    assert _qr_flowable(None) is None


# ── End to end, on the document itself ──────────────────────────────────────

def _invoice(**over):
    inv = {
        "invoice_no": "INV-1", "invoice_date": "2025-05-10", "status": "issued",
        "amount_paise": 100_000_00, "cgst_paise": 9_000_00, "sgst_paise": 9_000_00,
        "igst_paise": 0, "total_paise": 118_000_00, "round_off_paise": 0,
        "supply_state_code": "27", "is_interstate": False,
        "is_reverse_charge": False, "lines": [],
    }
    inv.update(over)
    return inv


SUPPLIER = {"name": "Acme Pvt Ltd", "gstin": "27AAAAA0000A1Z2", "pan": "AAAAA0000A",
            "address": "1 Road, Mumbai"}
RECIPIENT = {"name": "Buyer Ltd", "gstin": "27BBBBB1111B1ZN", "address": "2 Road"}


def test_the_pdf_renders_with_an_irn():
    pdf = build_sales_invoice_pdf(
        _invoice(**_einvoice_particulars(REAL)), SUPPLIER, RECIPIENT)
    assert pdf[:4] == b"%PDF"


def test_the_pdf_renders_without_one():
    pdf = build_sales_invoice_pdf(_invoice(), SUPPLIER, RECIPIENT)
    assert pdf[:4] == b"%PDF"


def test_rule_46r_is_named_in_the_modules_own_map():
    """The header lists every Rule 46 particular and where it comes from. A
    particular the module renders and does not list is one the next reader has
    to rediscover."""
    import services.invoice_pdf_service as m
    assert "(r)" in (m.__doc__ or "")
    assert "IRN" in (m.__doc__ or "")
