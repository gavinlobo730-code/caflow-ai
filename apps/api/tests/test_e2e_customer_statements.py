"""
Phase 5.2 WS-1 — Customer statements E2E.

Feeds the statement engine with REAL documents (invoices + receipt created
through the sales endpoints, plus an issued credit note) and asserts the
consolidated statement reconciles:

  closing = opening + Σ invoices − Σ receipts − Σ credit-notes   (receivable sign)

Also verifies opening-balance carry-forward for a mid-period window, and the
built-in tenant isolation (a foreign-firm caller gets 404 — the statement
engine scopes the customer by firm+client).
"""
import pytest
from fastapi import HTTPException

from models.invoices import SalesInvoiceIn, InvoiceLineIn, ReceiptIn, ReceiptAllocationIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa


FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}
OTHER = {"firm_id": "FIRM-B", "auth_user_id": "u2", "email": "ca@firmb.test", "role": "Partner"}


def _setup(monkeypatch):
    import routers.sales_invoices as si
    import routers.receipts as rc
    import routers.customer_statements as cs
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, rc, cs])
    monkeypatch.setattr(cs, "_db", lambda: db)           # endpoint uses _db(), not _USE_MOCK
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI",
                          "name": "Acme Buyer", "email": "buyer@acme.test", "state_code": "27",
                          "is_active": True, "opening_balance_paise": 50_000})
    seed_standard_coa(db, FIRM, "CLI")
    return si, rc, cs, db


def _make_invoice(si, rate_paise, date):
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id="CUST", invoice_date=date,
        lines=[InvoiceLineIn(description="Svc", hsn_sac="9982", quantity=1,
                             rate_paise=rate_paise, gst_rate_percent=18.0)],
    ), CALLER)["data"]
    si.issue_invoice(inv["id"], CALLER)
    return inv


def _seed_setup_with_activity(monkeypatch):
    si, rc, cs, db = _setup(monkeypatch)
    inv1 = _make_invoice(si, 1_000_000, "2026-04-10")   # total 1,180,000
    inv2 = _make_invoice(si, 500_000, "2026-04-15")     # total   590,000
    rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id="CUST", receipt_date="2026-04-20",
        amount_paise=1_180_000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv1["id"], allocated_paise=1_180_000)],
    ), CALLER)
    db.seed("credit_notes", {"firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST",
                             "credit_note_no": "CN-001", "credit_note_date": "2026-04-18",
                             "total_paise": 118_000, "status": "issued"})
    return si, rc, cs, db


def test_statement_full_period_reconciles(monkeypatch):
    si, rc, cs, db = _seed_setup_with_activity(monkeypatch)

    resp = cs.get_statement("CLI", "CUST", "2026-04-01", "2026-04-30", CALLER)
    assert resp["success"] is True, resp
    stmt = resp["data"]

    assert stmt["opening_balance_paise"] == 50_000           # seed only (no prior activity)
    assert stmt["totals"]["invoiced_paise"] == 1_770_000
    assert stmt["totals"]["received_paise"] == 1_180_000
    assert stmt["totals"]["credited_paise"] == 118_000
    assert stmt["totals"]["transaction_count"] == 4
    # closing = 50,000 + 1,770,000 − 1,180,000 − 118,000
    assert stmt["closing_balance_paise"] == 522_000


def test_statement_window_carries_opening_forward(monkeypatch):
    si, rc, cs, db = _seed_setup_with_activity(monkeypatch)

    # Window starts 2026-04-12 ⇒ inv1 (04-10) falls into the opening balance.
    resp = cs.get_statement("CLI", "CUST", "2026-04-12", "2026-04-30", CALLER)
    stmt = resp["data"]
    assert stmt["opening_balance_paise"] == 50_000 + 1_180_000      # seed + prior invoice
    assert stmt["totals"]["transaction_count"] == 3                 # inv2 + receipt + CN
    assert stmt["closing_balance_paise"] == 522_000                 # closing is window-invariant


def test_statement_excludes_draft_invoices(monkeypatch):
    si, rc, cs, db = _setup(monkeypatch)
    # A draft (un-issued) invoice must NOT appear on the statement.
    si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id="CUST", invoice_date="2026-04-10",
        lines=[InvoiceLineIn(description="Draft", hsn_sac="9982", quantity=1,
                             rate_paise=1_000_000, gst_rate_percent=18.0)],
    ), CALLER)
    stmt = cs.get_statement("CLI", "CUST", "2026-04-01", "2026-04-30", CALLER)["data"]
    assert stmt["totals"]["transaction_count"] == 0
    assert stmt["closing_balance_paise"] == 50_000                  # opening only


def test_statement_foreign_firm_404(monkeypatch):
    si, rc, cs, db = _seed_setup_with_activity(monkeypatch)
    with pytest.raises(HTTPException) as ei:
        cs.get_statement("CLI", "CUST", "2026-04-01", "2026-04-30", OTHER)
    assert ei.value.status_code == 404
