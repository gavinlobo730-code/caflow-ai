"""
Production Readiness Phase 2 — GSTR-1 invoice value includes cess (audit M12) and
AR aging nets credit notes (audit M13).
"""
from domain.gst.gstr1_builder import InvoiceForGSTR1, build_gstr1
from domain.gst.classifier import GSTInvoiceCategory
from services import collections_service as cs


def _b2b_invoice(cess):
    return InvoiceForGSTR1(
        id="i1", transaction_type="sales_invoice", reference_no="INV-1",
        transaction_date="2025-06-10", party_gstin="27BBBBB1111B1Z5", party_name="Acme",
        place_of_supply="27", is_interstate=False,
        taxable_amount_paise=1_00_000_00, cgst_paise=9_000_00, sgst_paise=9_000_00,
        igst_paise=0, cess_paise=cess, is_reverse_charge=False, invoice_type="Regular",
        supply_type="taxable", gst_invoice_category=GSTInvoiceCategory.B2B,
        original_invoice_ref=None, original_invoice_date=None, lines=[],
    )


def test_m12_gstr1_b2b_val_includes_cess():
    out = build_gstr1([_b2b_invoice(cess=5_000_00)], "27AAAAA0000A1Z5", "062025", 0)
    b2b = out.payload["b2b"]
    val = b2b[0]["inv"][0]["val"]
    # taxable 1,00,000 + cgst 9,000 + sgst 9,000 + cess 5,000 = 1,23,000
    assert val == 1_23_000.00


def test_m12_val_without_cess_unchanged():
    out = build_gstr1([_b2b_invoice(cess=0)], "27AAAAA0000A1Z5", "062025", 0)
    assert out.payload["b2b"][0]["inv"][0]["val"] == 1_18_000.00


def test_m13_aging_subtracts_credit_notes():
    # Fully credit-noted invoice → zero outstanding, not aged.
    inv = {"total_paise": 1_18_000, "paid_paise": 0, "credited_paise": 1_18_000, "status": "issued"}
    a = cs.assess_invoice(inv)
    assert a["outstanding_paise"] == 0
    assert a["is_overdue"] is False and a["aging_bucket"] is None


def test_m13_aging_partial_credit_and_cash():
    # total 1,18,000; cash 50,000; credit note 20,000 → outstanding 48,000.
    inv = {"total_paise": 1_18_000, "paid_paise": 50_000, "credited_paise": 20_000,
           "status": "partially_paid", "invoice_date": "2025-01-01"}
    a = cs.assess_invoice(inv)
    assert a["outstanding_paise"] == 48_000


def test_m13_tds_settlement_still_clears_invoice():
    # TDS is part of paid_paise (settlement incl. §194 TDS). A fully settled invoice
    # (cash + TDS = total) must not age.
    inv = {"total_paise": 1_18_000, "paid_paise": 1_18_000, "credited_paise": 0, "status": "paid"}
    a = cs.assess_invoice(inv)
    assert a["outstanding_paise"] == 0 and a["is_overdue"] is False
