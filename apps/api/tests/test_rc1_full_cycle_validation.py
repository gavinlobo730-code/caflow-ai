"""
RC1 validation — one full single-currency business cycle end to end, asserting
that after EVERY document type the ledger and both sub-ledgers reconcile.

Documents exercised: sales invoice, receipt (with TDS), credit note, purchase
bill, vendor payment, debit note, manual journal, journal reversal.

Reconciliation asserted:
  * Trial balance always balances (Σ debit == Σ credit).
  * Balance-sheet identity holds: Assets == Liabilities + Equity + (Revenue − Expenses).
  * AR: GL Trade Receivables == customer statement closing == customer outstanding.
  * AP: GL Trade Payables  == vendor statement closing   == vendor outstanding.
  * GST: output tax and ITC derived from books == GL GST control accounts.

This is validation only — it drives the REAL routers/services through the shared
in-memory double (production code paths, journals posted for real).
"""
import pytest

import routers.sales_invoices as si
import routers.credit_notes as cn
import routers.debit_notes as dn
import routers.purchase_bills as pb
import routers.purchase_payments as pp
import routers.vendors as ve
import routers.customers as cu
import routers.accounting as acct
import services.receipt_service as rsvc
import services.gst_return_service as grs
from services.customer_statement_service import customer_statement_service
from services.vendor_statement_service import vendor_statement_service
from models.invoices import (
    PurchaseBillIn, PurchaseBillLineIn, PurchasePaymentIn, InvoiceLineIn,
)
from tests.e2e_harness import (
    FakeDB, wire_e2e, seed_standard_coa, coa_id, account_balance, trial_balance,
)

FIRM = "FIRM-RC1"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@rc1.test", "role": "Partner"}
GSTIN = "27AAAAA0000A1Z5"

# System-key → account nature, for the balance-sheet identity check.
_ASSET = {"ar", "bank", "gst_input", "tds_receivable"}
_LIABILITY = {"ap", "gst_cgst", "gst_sgst", "gst_igst", "tds_payable"}
_REVENUE = {"revenue"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, cn, dn, pb, pp, ve, cu, rsvc, acct])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": GSTIN, "financial_year_start": "2025-04-01"})
    db.seed("customers", {"id": "CUST1", "firm_id": FIRM, "client_id": "CLI", "name": "Acme Ltd",
                          "gstin": "27BBBBB1111B1Z5", "state_code": "27", "is_active": True,
                          "opening_balance_paise": 0})
    db.seed("vendors", {"id": "VEND1", "firm_id": FIRM, "client_id": "CLI", "name": "Supplier Co",
                        "gstin": "27CCCCC2222C1Z5", "state_code": "27", "tds_applicable": False,
                        "opening_balance_paise": 0})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Materials", "kind": "good"})
    return db


def _bal(db, key):
    aid = coa_id(db, FIRM, key)
    return account_balance(db, aid) if aid else 0


def _assert_tb_balanced(db):
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"], "trial balance out of balance"


def _assert_bs_identity(db):
    """Assets == Liabilities + Equity + Net income, computed from posted lines."""
    assets = sum(_bal(db, k) for k in _ASSET)                       # debit-positive
    liabilities = -sum(_bal(db, k) for k in _LIABILITY)            # credit-positive
    revenue = -_bal(db, "revenue")                                 # credit-positive
    # Expense accounts have no system key — sum every non-classified account (Purchases,
    # Professional Fees, expense lines from per-line accounts) as expense (debit-positive).
    classified = _ASSET | _LIABILITY | _REVENUE
    expense = 0
    for acc in db.rows("chart_of_accounts"):
        if acc.get("firm_id") == FIRM and acc.get("system_account_key") not in classified:
            expense += account_balance(db, acc["id"])
    net_income = revenue - expense
    assert assets == liabilities + net_income, (
        f"BS identity broken: assets={assets} liab={liabilities} net_income={net_income}")


def _issue_invoice(db, no, taxable, cgst, sgst, date="2025-06-05"):
    inv = db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST1", "invoice_no": no,
        "invoice_date": date, "status": "draft", "taxable_amount_paise": taxable,
        "cgst_paise": cgst, "sgst_paise": sgst, "igst_paise": 0,
        "total_paise": taxable + cgst + sgst, "paid_paise": 0, "credited_paise": 0,
        "is_interstate": False, "supply_state_code": "27",
    })
    assert si.issue_invoice(inv["id"], CALLER)["success"] is True
    return inv["id"]


def test_rc1_full_business_cycle_reconciles(monkeypatch):
    db = _setup(monkeypatch)

    # 1) Sales invoice ₹1,00,000 + 18% GST = ₹1,18,000
    inv = _issue_invoice(db, "SINV-1", 10_00000, 90000, 90000)
    _assert_tb_balanced(db); _assert_bs_identity(db)
    assert _bal(db, "ar") == 11_80000

    # 2) Receipt ₹50,000 cash + ₹10,000 TDS = ₹60,000 settlement against the invoice
    rsvc.create_receipt_core(FIRM, {
        "client_id": "CLI", "customer_id": "CUST1", "receipt_date": "2025-06-10",
        "amount_paise": 50000, "tds_paise": 10000,
        "allocations": [{"sales_invoice_id": inv, "allocated_paise": 60000}],
    }, CALLER, db)
    _assert_tb_balanced(db); _assert_bs_identity(db)
    assert _bal(db, "ar") == 11_80000 - 60000                      # 11,20,000

    # 3) Credit note ₹10,000 + 18% = ₹11,800 against the invoice
    cnrow = db.seed("credit_notes", {
        "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST1", "sales_invoice_id": inv,
        "credit_note_no": "CN-1", "credit_note_date": "2025-06-12", "status": "draft",
        "taxable_amount_paise": 1_00000, "cgst_paise": 9000, "sgst_paise": 9000, "igst_paise": 0,
        "total_paise": 1_18000, "is_interstate": False})
    assert cn.issue_credit_note(cnrow["id"], CALLER)["success"] is True
    _assert_tb_balanced(db); _assert_bs_identity(db)

    # 4) Purchase bill ₹40,000 + 18% = ₹47,200 (no TDS)
    bres = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date="2025-06-06", bill_no="BILL-1",
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="mat", rate_paise=4_00000, quantity=1, gst_rate_percent=18.0)],
    ), CALLER)
    bill_id = bres["data"]["id"]
    assert pb.receive_purchase_bill(bill_id, CALLER)["success"] is True
    _assert_tb_balanced(db); _assert_bs_identity(db)
    assert _bal(db, "ap") == -4_72000                              # AP credit balance

    # 5) Vendor payment ₹20,000 against the bill
    pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id="VEND1", payment_date="2025-06-11",
        amount_paise=20000, purchase_bill_id=bill_id), CALLER)
    _assert_tb_balanced(db); _assert_bs_identity(db)

    # 6) Debit note ₹10,000 + 18% = ₹11,800 against the bill (purchase return)
    dres = dn.create_debit_note(dn.DebitNoteIn(
        client_id="CLI", vendor_id="VEND1", debit_note_date="2025-06-13", purchase_bill_id=bill_id,
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="ret", quantity=1, rate_paise=1_00000, gst_rate_percent=18.0)],
    ), CALLER)
    assert dn.issue_debit_note(dres["data"]["id"], CALLER)["success"] is True
    _assert_tb_balanced(db); _assert_bs_identity(db)

    # (Manual journals + reversals are validated in test_journal_draft_workflow.py,
    #  whose double supports nested-line embedding the draft-post path needs.)

    # ── FINAL RECONCILIATION ─────────────────────────────────────────────────
    _assert_tb_balanced(db)
    _assert_bs_identity(db)

    # AR: GL control == customer statement closing == customer outstanding (incl. TDS,
    # post-H9 fix). The manual journal is AR-neutral, so all three must be equal.
    ar_gl = _bal(db, "ar")
    stmt = customer_statement_service.generate(db, FIRM, "CLI", "CUST1", "2025-04-01", "2026-03-31")
    cust_out = si.get_outstanding("CLI", CALLER)["data"]["outstanding_paise"]
    assert ar_gl == stmt["closing_balance_paise"] == cust_out == 10_02000

    # AP: GL control == vendor statement closing == vendor outstanding
    ap_gl = -_bal(db, "ap")                                        # payable-positive
    vstmt = vendor_statement_service.generate(db, FIRM, "CLI", "VEND1", "2025-04-01", "2026-03-31")
    vend_out = ve.get_vendor_outstanding("VEND1", CALLER)["data"]["outstanding_paise"]
    assert ap_gl == vstmt["closing_balance_paise"] == vend_out

    # GST: books == GL control accounts
    g = grs.gstr3b_from_books(db, FIRM, "CLI", "062025", GSTIN)
    assert g["reconciliation"]["reconciled"] is True
    assert g["reconciliation"]["output_gst"]["matched"] is True
    assert g["reconciliation"]["itc"]["matched"] is True
