"""
Unit tests — GST tax invoice PDF tax-split logic.

Verifies that _compute_tax_splits() uses stored cgst_paise/sgst_paise/igst_paise
and never re-derives the tax-head split from GSTIN geography.

Scenarios:
  B2B intra-state  — both parties have matching state-code GSTINs → CGST+SGST
  B2B inter-state  — different state codes → IGST
  B2C intra-state  — no customer GSTIN (geography would fail) → CGST+SGST from stored values

References: CGST Act §8; CGST Rule 46, CGST Rules 2017; Section 12, IGST Act 2017.
"""
import pytest
from services.invoice_pdf_service import _compute_tax_splits


_FIRM = {
    "name": "Test CA Firm",
    "gstin": "27AAAAA0000A1Z5",  # state code 27 = Maharashtra
}

_INVOICE_BASE = {
    "invoice_no":   "INV-TEST-001",
    "invoice_date": "2026-06-01",
    "amount_paise": 100_000,   # ₹1,000 taxable
    "total_paise":  118_000,   # ₹1,180 total (18% GST)
}


class TestComputeTaxSplits:
    def test_b2b_intra_state_uses_stored_cgst_sgst(self):
        """B2B intra-state: stored cgst/sgst returned directly without re-derivation."""
        invoice = {
            **_INVOICE_BASE,
            "cgst_paise": 9_000,
            "sgst_paise": 9_000,
            "igst_paise": 0,
        }
        client = {"name": "Intra-State Client", "gstin": "27BBBBB1111B1Z3"}  # MH state code 27
        cgst, sgst, igst, gst, total = _compute_tax_splits(invoice, _FIRM, client)
        assert cgst == 9_000
        assert sgst == 9_000
        assert igst == 0
        assert gst == 18_000
        assert total == 118_000

    def test_b2b_inter_state_uses_stored_igst(self):
        """B2B inter-state: stored igst returned directly."""
        invoice = {
            **_INVOICE_BASE,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "igst_paise": 18_000,
        }
        client = {"name": "Inter-State Client", "gstin": "07BBBBB1111B1Z3"}  # DL = 07
        cgst, sgst, igst, gst, total = _compute_tax_splits(invoice, _FIRM, client)
        assert cgst == 0
        assert sgst == 0
        assert igst == 18_000
        assert gst == 18_000
        assert total == 118_000

    def test_b2c_intra_state_uses_stored_values_not_geography(self):
        """
        B2C intra-state: no customer GSTIN.
        Geography-based derivation would yield intra_state=False → igst=18000.
        Stored cgst/sgst must be returned unchanged → CGST+SGST.
        """
        invoice = {
            **_INVOICE_BASE,
            "cgst_paise": 9_000,
            "sgst_paise": 9_000,
            "igst_paise": 0,
        }
        client = {"name": "Individual B2C Client"}  # no gstin — the bug-trigger case
        cgst, sgst, igst, gst, total = _compute_tax_splits(invoice, _FIRM, client)
        assert cgst == 9_000, "B2C intra-state must use stored CGST, not geography"
        assert sgst == 9_000, "B2C intra-state must use stored SGST, not geography"
        assert igst == 0,     "B2C intra-state must NOT produce IGST from re-derivation"
        assert gst == 18_000
        assert total == 118_000
