"""
Production Readiness Phase 1 — C1: credit-note application.

A credit note must reduce the linked invoice's receivable in the SUB-LEDGER (not
just the GL), so the three views reconcile:
  * invoice net outstanding  = total − paid − credited
  * GL AR control account    (moved by the credit-note journal)
  * customer statement closing balance
All post through the single kernel; append-only; integer paise.
"""
import pytest
from fastapi import HTTPException

import routers.sales_invoices as si
import routers.credit_notes as cn
from models.invoices import InvoiceLineIn
from services.customer_statement_service import customer_statement_service
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, coa_id, account_balance, trial_balance

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u-int", "auth_user_id": "auth", "email": "ca@firma.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, cn])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "financial_year_start": "2025-04-01"})
    db.seed("customers", {"id": "CUST1", "firm_id": FIRM, "client_id": "CLI", "name": "Acme",
                          "is_active": True, "opening_balance_paise": 0})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Returned Goods", "kind": "good"})
    return db


def _issue_invoice(db, inv_no="INV-1", taxable=100000, cgst=9000, sgst=9000, igst=0, status="draft"):
    total = taxable + cgst + sgst + igst
    inv = db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST1",
        "invoice_no": inv_no, "invoice_date": "2025-06-01", "status": status,
        "total_paise": total, "taxable_amount_paise": taxable,
        "cgst_paise": cgst, "sgst_paise": sgst, "igst_paise": igst,
        "paid_paise": 0, "credited_paise": 0, "is_interstate": bool(igst),
    })
    if status == "draft":
        assert si.issue_invoice(inv["id"], CALLER)["success"] is True
    return inv["id"], total


def _seed_cn(db, inv_id, taxable=100000, cgst=9000, sgst=9000, igst=0, cn_no="CN-1"):
    total = taxable + cgst + sgst + igst
    row = db.seed("credit_notes", {
        "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST1", "sales_invoice_id": inv_id,
        "credit_note_no": cn_no, "credit_note_date": "2025-06-05", "status": "draft",
        "taxable_amount_paise": taxable, "cgst_paise": cgst, "sgst_paise": sgst, "igst_paise": igst,
        "total_paise": total, "is_interstate": bool(igst),
    })
    return row["id"], total


def _statement_closing(db):
    return customer_statement_service.generate(db, FIRM, "CLI", "CUST1", "2025-04-01", "2026-03-31")["closing_balance_paise"]


def _ar(db):
    return account_balance(db, coa_id(db, FIRM, "ar"))


def test_full_credit_note_reconciles_subledger_gl_and_statement(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, total = _issue_invoice(db)                       # AR = 118000
    assert _ar(db) == total
    cn_id, cn_total = _seed_cn(db, inv_id)                   # full credit
    res = cn.issue_credit_note(cn_id, CALLER)
    assert res["success"] is True

    inv = next(i for i in db.rows("client_sales_invoices") if i["id"] == inv_id)
    assert inv["credited_paise"] == cn_total and inv["status"] == "paid"     # sub-ledger
    assert (inv["total_paise"] - inv["paid_paise"] - inv["credited_paise"]) == 0  # net outstanding
    assert _ar(db) == 0                                                       # GL AR control
    assert si.get_outstanding("CLI", CALLER)["data"]["outstanding_paise"] == 0
    assert _statement_closing(db) == 0                                        # statement
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]
    # An allocation record was written.
    assert any(a["credit_note_id"] == cn_id and a["allocated_paise"] == cn_total
               for a in db.rows("credit_note_allocations"))


def test_partial_credit_note_reconciles(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, total = _issue_invoice(db)                       # 118000
    cn_id, cn_total = _seed_cn(db, inv_id, taxable=40000, cgst=3600, sgst=3600, igst=0)   # 47200
    assert cn.issue_credit_note(cn_id, CALLER)["success"] is True

    inv = next(i for i in db.rows("client_sales_invoices") if i["id"] == inv_id)
    net = inv["total_paise"] - inv["paid_paise"] - inv["credited_paise"]
    assert inv["status"] == "partially_paid" and net == total - cn_total      # 70800
    assert _ar(db) == total - cn_total
    assert si.get_outstanding("CLI", CALLER)["data"]["outstanding_paise"] == total - cn_total
    assert _statement_closing(db) == total - cn_total


def test_credit_note_exceeding_invoice_outstanding_is_rejected(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, total = _issue_invoice(db)                       # 118000
    cn_id, _ = _seed_cn(db, inv_id, taxable=200000, cgst=18000, sgst=18000)   # 236000 > 118000
    with pytest.raises(HTTPException) as ex:
        cn.issue_credit_note(cn_id, CALLER)
    assert ex.value.status_code == 422
    # Nothing applied — invoice untouched, no allocation, CN still draft.
    inv = next(i for i in db.rows("client_sales_invoices") if i["id"] == inv_id)
    assert inv["credited_paise"] == 0
    assert not db.rows("credit_note_allocations")
    assert next(c for c in db.rows("credit_notes") if c["id"] == cn_id)["status"] == "draft"


def test_cannot_credit_a_draft_invoice(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, _ = _issue_invoice(db, status="draft-keep")     # seed but do NOT issue
    # force it to remain a real draft
    for i in db.rows("client_sales_invoices"):
        if i["id"] == inv_id:
            i["status"] = "draft"
    cn_id, _ = _seed_cn(db, inv_id, taxable=10000, cgst=900, sgst=900)
    with pytest.raises(HTTPException) as ex:
        cn.issue_credit_note(cn_id, CALLER)
    assert ex.value.status_code == 422


def test_create_credit_note_computes_gst_from_percent(monkeypatch):
    # Regression (L1): a credit note created from the shared line model must compute
    # GST from gst_rate_percent, not silently 0.
    db = _setup(monkeypatch)
    inv_id, _ = _issue_invoice(db)
    res = cn.create_credit_note(cn.CreditNoteIn(
        client_id="CLI", customer_id="CUST1", credit_note_date="2025-06-05",
        sales_invoice_id=inv_id,
        lines=[InvoiceLineIn(description="return", quantity=1, rate_paise=100000, gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert res["success"] is True
    data = res["data"]
    assert data["taxable_amount_paise"] == 100000
    assert (data["cgst_paise"] + data["sgst_paise"] + data["igst_paise"]) == 18000  # 18% GST, not 0
    assert data["total_paise"] == 118000
