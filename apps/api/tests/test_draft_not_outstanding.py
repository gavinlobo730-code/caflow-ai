"""
Task #222 — draft documents wrongly counted as receivable/payable.

Task #104 fixed customer_statement_service.py/vendor_statement_service.py's
generate()/ar_aging()/ap_aging() to exclude draft documents (a draft invoice/bill
was never issued/received — no journal posted, so it isn't a real receivable or
payable yet). Four other functions computing the same kind of outstanding total
were missed and still counted drafts:

  * vendors.py::get_vendor_outstanding()      — only excluded "cancelled"
  * customers.py::get_outstanding_summary()   — only excluded "paid"/"cancelled"
  * customers.py::get_customer_outstanding()  — only excluded "paid"/"cancelled"
  * sales_invoices.py::get_outstanding()      — only excluded "paid"/"cancelled"

Grepping the same pattern also found:
  * fx_reporting_service.py::exchange_rate_audit() — no status filter at all
    (draft/cancelled documents' provisional rates polluted the audit trail;
    "paid" is intentionally kept — a settled FX transaction is exactly what
    the audit trail exists to show).
  * bank_matching_service.py::_invoice_candidates()/_bill_candidates() — a
    draft invoice/bill (no AR/AP journal posted) could surface as a bank-match
    suggestion and, if accepted, get "settled" downstream against a document
    that was never posted to the ledger.

Each test proves the draft is excluded while a live (issued/received) document
of the same shape still counts — so the fix narrows the filter without breaking
the happy path.
"""
import pytest

import routers.customers as cu
import routers.purchase_bills as pb
import routers.sales_invoices as si
import routers.vendors as ve
from models.invoices import PurchaseBillIn, PurchaseBillLineIn, SalesInvoiceIn, InvoiceLineIn
from models.parties import CustomerIn
from services.fx_reporting_service import FXReportingService
from services.bank_matching_service import bank_matching_service
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


# ── vendors.py::get_vendor_outstanding ─────────────────────────────────────────

def _vendor_setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb, ve])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z5"})
    db.seed("vendors", {"id": "VEND1", "firm_id": FIRM, "client_id": "CLI", "name": "Supplier",
                        "state_code": "27", "gstin": "27CCCCC2222C1Z5", "tds_applicable": False,
                        "opening_balance_paise": 0})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Materials", "kind": "good"})
    return db


def _draft_bill(db, no="B-DRAFT"):
    return pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date="2025-06-01", bill_no=no,
        lines=[PurchaseBillLineIn(description="m", rate_paise=1_00000, quantity=1, gst_rate_percent=18.0,
                                  service_catalogue_id="SVC-1")],
    ), CALLER)["data"]["id"]


def test_vendor_outstanding_excludes_draft_bill(monkeypatch):
    db = _vendor_setup(monkeypatch)
    _draft_bill(db)  # never received — no AP journal, not a payable yet
    assert ve.get_vendor_outstanding("VEND1", CALLER)["data"]["outstanding_paise"] == 0


def test_vendor_outstanding_still_counts_received_bill(monkeypatch):
    db = _vendor_setup(monkeypatch)
    _draft_bill(db, "B-DRAFT")
    bid = _draft_bill(db, "B-RECEIVED")
    assert pb.receive_purchase_bill(bid, CALLER)["success"] is True
    assert ve.get_vendor_outstanding("VEND1", CALLER)["data"]["outstanding_paise"] == 1_18000


# ── customers.py::get_outstanding_summary / get_customer_outstanding ──────────
# ── sales_invoices.py::get_outstanding ─────────────────────────────────────────

def _customer_setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [cu, si])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Consulting", "kind": "service"})
    cust_id = cu.create_customer(CustomerIn(
        client_id="CLI", name="Acme Buyer", state_code="27", email="buyer@acme.test"), CALLER)["data"]["id"]
    return db, cust_id


def _draft_invoice(db, cust_id, no="INV-DRAFT"):
    return si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=cust_id, invoice_date="2025-06-01", invoice_no=no,
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Consulting", hsn_sac="9982",
                             quantity=1, rate_paise=1_00000, gst_rate_percent=18.0)],
    ), CALLER)["data"]["id"]


def test_outstanding_summary_excludes_draft_invoice(monkeypatch):
    db, cust_id = _customer_setup(monkeypatch)
    _draft_invoice(db, cust_id)  # never issued — no AR journal, not a receivable yet
    summary = cu.get_outstanding_summary(client_id="CLI", current_user=CALLER)["data"]
    assert summary["total_outstanding_paise"] == 0
    assert summary["customers"][0]["outstanding_paise"] == 0


def test_customer_outstanding_excludes_draft_invoice(monkeypatch):
    db, cust_id = _customer_setup(monkeypatch)
    _draft_invoice(db, cust_id)
    out = cu.get_customer_outstanding(cust_id, CALLER)["data"]
    assert out["outstanding_paise"] == 0
    assert out["invoices"] == []


def test_sales_invoice_get_outstanding_excludes_draft(monkeypatch):
    db, cust_id = _customer_setup(monkeypatch)
    _draft_invoice(db, cust_id)
    assert si.get_outstanding(client_id="CLI", current_user=CALLER)["data"]["outstanding_paise"] == 0


def test_outstanding_functions_still_count_issued_invoice(monkeypatch):
    db, cust_id = _customer_setup(monkeypatch)
    _draft_invoice(db, cust_id, "INV-DRAFT")
    inv_id = _draft_invoice(db, cust_id, "INV-ISSUED")
    assert si.issue_invoice(inv_id, CALLER)["data"]["status"] == "issued"

    assert cu.get_outstanding_summary(client_id="CLI", current_user=CALLER)["data"]["total_outstanding_paise"] == 1_18000
    assert cu.get_customer_outstanding(cust_id, CALLER)["data"]["outstanding_paise"] == 1_18000
    assert si.get_outstanding(client_id="CLI", current_user=CALLER)["data"]["outstanding_paise"] == 1_18000


# ── fx_reporting_service.py::exchange_rate_audit ───────────────────────────────

FXR = FXReportingService()


def _fx_invoice(status, currency="USD"):
    return {"firm_id": FIRM, "client_id": "CLI", "invoice_no": f"FX-{status}", "invoice_date": "2026-01-10",
            "txn_currency": currency, "exchange_rate": "83.5", "rate_source": "RBI",
            "rate_type": "spot", "rate_date": "2026-01-10", "rate_selected_by": "u1",
            "rate_overridden": False, "status": status}


def test_exchange_rate_audit_excludes_draft_and_cancelled_but_keeps_paid(monkeypatch):
    db = FakeDB()
    db.seed("client_sales_invoices", _fx_invoice("draft"))
    db.seed("client_sales_invoices", _fx_invoice("cancelled"))
    db.seed("client_sales_invoices", _fx_invoice("issued"))
    db.seed("client_sales_invoices", _fx_invoice("paid"))

    audit = FXR.exchange_rate_audit(db, FIRM, "CLI", "2025-04-01", "2026-03-31")
    statuses_seen = {d["document_no"] for d in audit["documents"]}
    assert statuses_seen == {"FX-issued", "FX-paid"}  # draft + cancelled dropped, paid kept


# ── bank_matching_service.py::_invoice_candidates / _bill_candidates ──────────

def test_bank_match_suggestions_exclude_draft_invoice(monkeypatch):
    db = FakeDB()
    db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST1", "invoice_no": "INV-DRAFT",
        "invoice_date": "2026-04-10", "total_paise": 118000, "paid_paise": 0, "status": "draft",
    })
    db.seed("bank_transactions", {
        "id": "t1", "firm_id": FIRM, "client_id": "CLI", "transaction_date": "2026-04-10",
        "description": "NEFT", "debit_paise": 0, "credit_paise": 118000, "match_status": "unmatched",
    })
    res = bank_matching_service.suggestions(db, FIRM, "t1")
    assert res["suggestions"] == []  # the only candidate is a draft invoice — must not surface


def test_bank_match_suggestions_exclude_draft_bill(monkeypatch):
    db = FakeDB()
    db.seed("purchase_bills", {
        "firm_id": FIRM, "client_id": "CLI", "vendor_id": "VEND1", "bill_no": "B-DRAFT",
        "bill_date": "2026-04-10", "total_paise": 59000, "net_payable_paise": 59000, "status": "draft",
    })
    db.seed("bank_transactions", {
        "id": "t1", "firm_id": FIRM, "client_id": "CLI", "transaction_date": "2026-04-10",
        "description": "NEFT OUT", "debit_paise": 59000, "credit_paise": 0, "match_status": "unmatched",
    })
    res = bank_matching_service.suggestions(db, FIRM, "t1")
    assert res["suggestions"] == []
