"""
Production Readiness Phase 2 — GST returns derive from posted books and reconcile
to the General Ledger (audit H8; Task 4). The return is NEVER computed from
frontend data: we post real sales invoices / purchase bills through the engine,
then derive GSTR-3B from the books and assert its output tax == GL GST-output
credit movement and its ITC == GL gst_input debit movement.
"""
import pytest

import routers.sales_invoices as si
import routers.purchase_bills as pb
import routers.credit_notes as cn
import routers.sales_debit_notes as sdn
import routers.purchase_credit_notes as pcn
import services.gst_return_service as grs
from models.invoices import PurchaseBillIn, PurchaseBillLineIn, InvoiceLineIn
from tests.e2e_harness import (
    FakeDB, wire_e2e, seed_standard_coa, coa_id, account_balance, trial_balance,
)

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u-int", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}
PERIOD = "062025"
GSTIN = "27AAAAA0000A1Z5"


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, pb, cn, sdn, pcn])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": GSTIN, "financial_year_start": "2025-04-01"})
    db.seed("customers", {"id": "CUST1", "firm_id": FIRM, "client_id": "CLI", "name": "Acme",
                          "gstin": "27BBBBB1111B1Z5", "state_code": "27", "is_active": True,
                          "opening_balance_paise": 0})
    db.seed("vendors", {"id": "VEND1", "firm_id": FIRM, "client_id": "CLI", "name": "Supplier",
                        "state_code": "27", "gstin": "27CCCCC2222C1Z5", "tds_applicable": False})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Materials", "kind": "good"})
    return db


def _issue_invoice(db, no, taxable, cgst, sgst, igst=0, date="2025-06-10"):
    inv = db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST1", "invoice_no": no,
        "invoice_date": date, "status": "draft", "taxable_amount_paise": taxable,
        "cgst_paise": cgst, "sgst_paise": sgst, "igst_paise": igst,
        "total_paise": taxable + cgst + sgst + igst, "paid_paise": 0, "credited_paise": 0,
        "is_interstate": bool(igst), "supply_state_code": "27",
    })
    assert si.issue_invoice(inv["id"], CALLER)["success"] is True
    return inv["id"]


def _receive_bill(db, no, rate, date="2025-06-12", rcm=False):
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date=date, bill_no=no,
        is_reverse_charge=rcm,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="mat", rate_paise=rate, quantity=1, gst_rate_percent=18.0)],
    ), CALLER)
    assert res["success"] is True
    assert pb.receive_purchase_bill(res["data"]["id"], CALLER)["success"] is True
    return res["data"]


def _gl_output(db):
    return (account_balance(db, coa_id(db, FIRM, "gst_cgst"))
            + account_balance(db, coa_id(db, FIRM, "gst_sgst"))
            + account_balance(db, coa_id(db, FIRM, "gst_igst")))  # credit balances → negative


def test_gstr3b_output_and_itc_reconcile_to_ledger(monkeypatch):
    db = _setup(monkeypatch)
    _issue_invoice(db, "INV-1", taxable=10_00000, cgst=90000, sgst=90000)   # ₹10,000 @18% intra
    _receive_bill(db, "BILL-1", rate=5_00000)                               # ₹5,000 @18% intra → ITC 90,000

    out = grs.gstr3b_from_books(db, FIRM, "CLI", PERIOD, GSTIN)
    rec = out["reconciliation"]

    # Output GST: books 180000 == GL credit movement on gst_cgst+gst_sgst.
    assert rec["output_gst"]["books_paise"] == 180000
    assert rec["output_gst"]["ledger_paise"] == 180000
    assert rec["output_gst"]["matched"] is True
    # ITC: books 90000 == GL debit movement on gst_input.
    assert rec["itc"]["books_paise"] == 90000
    assert rec["itc"]["ledger_paise"] == 90000
    assert rec["itc"]["matched"] is True
    assert rec["reconciled"] is True
    # H7: taxable value carried, not the tax.
    assert out["working"]["outward"]["taxable_value_paise"] == 10_00000


def test_credit_note_reduces_output_and_still_reconciles(monkeypatch):
    db = _setup(monkeypatch)
    inv_id = _issue_invoice(db, "INV-2", taxable=10_00000, cgst=90000, sgst=90000)
    # Issue a credit note for ₹2,000 @18% against the invoice → posts a GL reversal.
    cnrow = db.seed("credit_notes", {
        "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST1", "sales_invoice_id": inv_id,
        "credit_note_no": "CN-1", "credit_note_date": "2025-06-20", "status": "draft",
        "taxable_amount_paise": 2_00000, "cgst_paise": 18000, "sgst_paise": 18000, "igst_paise": 0,
        "total_paise": 2_36000, "is_interstate": False, "supply_state_code": "27",
    })
    assert cn.issue_credit_note(cnrow["id"], CALLER)["success"] is True

    out = grs.gstr3b_from_books(db, FIRM, "CLI", PERIOD, GSTIN)
    rec = out["reconciliation"]
    # Net output = 180000 − 36000 = 144000, matching the GL after the CN reversal.
    assert rec["output_gst"]["books_paise"] == 144000
    assert rec["output_gst"]["ledger_paise"] == 144000
    assert rec["reconciled"] is True


def test_rcm_purchase_itc_reconciles_and_liability_reported(monkeypatch):
    db = _setup(monkeypatch)
    _issue_invoice(db, "INV-3", taxable=10_00000, cgst=90000, sgst=90000)
    _receive_bill(db, "BILL-RCM", rate=1_00000, rcm=True)   # ₹1,000 @18% intra, reverse charge

    out = grs.gstr3b_from_books(db, FIRM, "CLI", PERIOD, GSTIN)
    rec = out["reconciliation"]
    # ITC includes the RCM input tax ONCE (₹1,000@18% = 18000) and ties to gst_input.
    assert rec["itc"]["books_paise"] == 18000
    assert rec["itc"]["ledger_paise"] == 18000
    assert rec["reconciled"] is True
    # RCM inward liability (Table 3.2) is reported from the posted bill (C5).
    assert (out["working"]["rcm_inward"]["cgst_paise"]
            + out["working"]["rcm_inward"]["sgst_paise"]
            + out["working"]["rcm_inward"]["igst_paise"]) == 18000


def test_out_of_period_documents_are_excluded(monkeypatch):
    db = _setup(monkeypatch)
    _issue_invoice(db, "INV-JUN", taxable=10_00000, cgst=90000, sgst=90000, date="2025-06-10")
    _issue_invoice(db, "INV-JUL", taxable=99_00000, cgst=900000, sgst=900000, date="2025-07-10")

    out = grs.gstr3b_from_books(db, FIRM, "CLI", PERIOD, GSTIN)   # June only
    assert out["reconciliation"]["output_gst"]["books_paise"] == 180000
    assert out["reconciliation"]["reconciled"] is True


def test_sales_debit_note_increases_output_and_reconciles(monkeypatch):
    # Regression pin: gstr3b_from_books/gstr1_from_books never fetched
    # sales_debit_notes at all — a sales debit note (§34(3) undercharge
    # correction, INCREASES output tax) posted a real GL journal but silently
    # never appeared in either from-books return, understating output tax and
    # permanently breaking the GL reconciliation for any client using this
    # document type (task, 2026-07-24).
    db = _setup(monkeypatch)
    inv_id = _issue_invoice(db, "INV-4", taxable=10_00000, cgst=90000, sgst=90000)
    sdn_res = sdn.create_sales_debit_note(sdn.SalesDebitNoteIn(
        client_id="CLI", customer_id="CUST1", debit_note_date="2025-06-20",
        sales_invoice_id=inv_id, reason="Undercharged — rate correction",
        lines=[InvoiceLineIn(description="extra", quantity=1, rate_paise=2_00000,
                              gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert sdn_res["success"] is True
    assert sdn.issue_sales_debit_note(sdn_res["data"]["id"], CALLER)["success"] is True

    out = grs.gstr3b_from_books(db, FIRM, "CLI", PERIOD, GSTIN)
    rec = out["reconciliation"]
    # Net output = 180000 (invoice) + 36000 (debit note @18% on ₹2,00,000) = 216000
    assert rec["output_gst"]["books_paise"] == 216000
    assert rec["output_gst"]["ledger_paise"] == 216000
    assert rec["reconciled"] is True

    gstr1 = grs.gstr1_from_books(db, FIRM, "CLI", PERIOD, GSTIN)
    assert gstr1["reconciliation"]["net_output_gst"]["books_paise"] == 216000
    assert gstr1["reconciliation"]["reconciled"] is True


def test_purchase_credit_note_increases_itc_and_reconciles(monkeypatch):
    # Regression pin: gstr3b_from_books never fetched purchase_credit_notes —
    # a purchase credit note (§34(3) undercharge correction, INCREASES ITC,
    # this codebase's naming convention per routers/purchase_credit_notes.py)
    # posted a real Dr GST Input journal line but was never counted as book
    # ITC, permanently under-claiming ITC in the return and breaking the GL
    # reconciliation for any client using this document type (task, 2026-07-24).
    db = _setup(monkeypatch)
    _issue_invoice(db, "INV-5", taxable=10_00000, cgst=90000, sgst=90000)
    bill_id = _receive_bill(db, "BILL-2", rate=5_00000)["id"]   # ITC 90000

    pcn_res = pcn.create_purchase_credit_note(pcn.PurchaseCreditNoteIn(
        client_id="CLI", vendor_id="VEND1", credit_note_date="2025-06-20",
        purchase_bill_id=bill_id, reason="Vendor undercharged — rate correction",
        lines=[InvoiceLineIn(description="extra", quantity=1, rate_paise=1_00000,
                              gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert pcn_res["success"] is True
    assert pcn.issue_purchase_credit_note(pcn_res["data"]["id"], CALLER)["success"] is True

    out = grs.gstr3b_from_books(db, FIRM, "CLI", PERIOD, GSTIN)
    rec = out["reconciliation"]
    # ITC = 90000 (bill) + 18000 (purchase credit note @18% on ₹1,00,000) = 108000
    assert rec["itc"]["books_paise"] == 108000
    assert rec["itc"]["ledger_paise"] == 108000
    assert rec["reconciled"] is True
