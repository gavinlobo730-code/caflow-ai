"""
Task #227 finding #1 — a receipt must never settle against a draft or
cancelled sales invoice.

A draft invoice was never issued (CGST Act §31 — no supply has been billed,
no AR journal exists for a receipt to settle against); a cancelled one is
terminal. Before this fix, create_receipt_core, create_foreign_receipt, and
update_allocations (the re-allocation endpoint) all fetched an invoice's
paid_paise/total_paise/etc. without ever checking status, so a receipt could
post a real Dr Bank / Cr Trade Receivable journal and mark paid/
partially_paid an invoice with no real receivable behind it.

Exercised end-to-end (real router + service code, not the invoice-status
check in isolation) via the shared e2e_harness FakeDB, which dispatches
create_receipt_core through the SAME settle_receipt_atomic RPC path
production uses (FakeDB exposes .rpc) — so these tests prove the guard holds
for the actual call path, not just a bypassable fallback.
"""
import pytest
from fastapi import HTTPException

from models.parties import CustomerIn
from models.invoices import (
    SalesInvoiceIn, InvoiceLineIn, ReceiptIn, ReceiptAllocationIn, ReceiptAllocationsUpdateIn,
)
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-R227-1"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    import routers.customers as cu
    import routers.sales_invoices as si
    import routers.receipts as rc
    import services.receipt_service as rs
    db = FakeDB()
    wire_e2e(monkeypatch, db, [cu, si, rc, rs])
    db.seed("firms", {"id": FIRM, "multi_currency_entitled": True})
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5",
                        "functional_currency": "INR", "multi_currency_enabled": True})
    db.seed("currencies", {"code": "USD", "symbol": "$", "display_name": "US Dollar", "minor_unit": 2, "is_active": True})
    db.seed("currencies", {"code": "INR", "symbol": "₹", "display_name": "Indian Rupee", "minor_unit": 2, "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Services", "kind": "service"})
    return cu, si, rc, db


def _customer(cu):
    return cu.create_customer(CustomerIn(client_id="CLI", name="Acme Co", state_code="27"), CALLER)["data"]


def _draft_invoice(si, cust_id, invoice_no="INV-DRAFT-1", *, currency=None, exchange_rate=None):
    kwargs = {}
    if currency:
        kwargs["currency"] = currency
        kwargs["exchange_rate"] = exchange_rate
    return si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=cust_id, invoice_date="2026-04-01",
        invoice_no=invoice_no,
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Consulting", hsn_sac="9982",
                             quantity=1, rate_paise=100000, gst_rate_percent=18.0)],
        **kwargs), CALLER)["data"]


def _issued_invoice(si, cust_id, invoice_no="INV-ISSUED-1", **kwargs):
    inv = _draft_invoice(si, cust_id, invoice_no, **kwargs)
    si.issue_invoice(inv["id"], CALLER)
    return inv


def _cancelled_invoice(si, cust_id, invoice_no="INV-CANC-1", **kwargs):
    inv = _issued_invoice(si, cust_id, invoice_no, **kwargs)
    si.cancel_invoice(inv["id"], CALLER)
    return inv


# ── create_receipt_core (plain INR path, through settle_receipt_atomic) ─────

def test_create_receipt_rejects_draft_invoice(monkeypatch):
    cu, si, rc, db = _setup(monkeypatch)
    cust = _customer(cu)
    inv = _draft_invoice(si, cust["id"])

    with pytest.raises(HTTPException) as ex:
        rc.create_receipt(ReceiptIn(
            client_id="CLI", customer_id=cust["id"], receipt_date="2026-04-05",
            amount_paise=118000,
            allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=118000)]),
            CALLER)
    assert ex.value.status_code == 422
    assert "draft" in ex.value.detail.lower()
    assert db.rows("receipts") == []
    assert db.rows("journal_entries") == []


def test_create_receipt_rejects_cancelled_invoice(monkeypatch):
    cu, si, rc, db = _setup(monkeypatch)
    cust = _customer(cu)
    inv = _cancelled_invoice(si, cust["id"])

    with pytest.raises(HTTPException) as ex:
        rc.create_receipt(ReceiptIn(
            client_id="CLI", customer_id=cust["id"], receipt_date="2026-04-05",
            amount_paise=118000,
            allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=118000)]),
            CALLER)
    assert ex.value.status_code == 422
    assert "cancelled" in ex.value.detail.lower()
    receipts_for_this_invoice = [
        a for a in db.rows("receipt_allocations") if a.get("sales_invoice_id") == inv["id"]
    ]
    assert receipts_for_this_invoice == []


def test_create_receipt_still_accepts_issued_invoice(monkeypatch):
    """Sanity check: the guard doesn't over-reject a normal, valid receipt."""
    cu, si, rc, db = _setup(monkeypatch)
    cust = _customer(cu)
    inv = _issued_invoice(si, cust["id"])

    result = rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2026-04-05",
        amount_paise=118000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=118000)]),
        CALLER)
    assert result["success"] is True
    updated = next(r for r in db.rows("client_sales_invoices") if r["id"] == inv["id"])
    assert updated["status"] == "paid"


# ── create_foreign_receipt (FX path) ─────────────────────────────────────────

def test_create_foreign_receipt_rejects_draft_invoice(monkeypatch):
    cu, si, rc, db = _setup(monkeypatch)
    monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    cust = _customer(cu)
    inv = _draft_invoice(si, cust["id"], "USD-DRAFT-1", currency="USD", exchange_rate="80.0")

    with pytest.raises(HTTPException) as ex:
        rc.create_receipt(ReceiptIn(
            client_id="CLI", customer_id=cust["id"], receipt_date="2026-04-05",
            amount_paise=100000, currency="USD", exchange_rate="83.0",
            allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=100000)]),
            CALLER)
    assert ex.value.status_code == 422
    assert "draft" in ex.value.detail.lower()
    assert db.rows("receipts") == []
    assert db.rows("journal_entries") == []


def test_create_foreign_receipt_rejects_cancelled_invoice(monkeypatch):
    cu, si, rc, db = _setup(monkeypatch)
    monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    cust = _customer(cu)
    inv = _cancelled_invoice(si, cust["id"], "USD-CANC-1", currency="USD", exchange_rate="80.0")

    with pytest.raises(HTTPException) as ex:
        rc.create_receipt(ReceiptIn(
            client_id="CLI", customer_id=cust["id"], receipt_date="2026-04-05",
            amount_paise=100000, currency="USD", exchange_rate="83.0",
            allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=100000)]),
            CALLER)
    assert ex.value.status_code == 422
    assert "cancelled" in ex.value.detail.lower()
    assert db.rows("receipts") == []


# ── update_allocations (re-allocation endpoint) ──────────────────────────────

def test_update_allocations_rejects_draft_invoice(monkeypatch):
    cu, si, rc, db = _setup(monkeypatch)
    cust = _customer(cu)
    good_inv = _issued_invoice(si, cust["id"], "INV-GOOD-1")
    bad_inv = _draft_invoice(si, cust["id"], "INV-DRAFT-2")

    created = rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2026-04-05",
        amount_paise=118000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=good_inv["id"], allocated_paise=118000)]),
        CALLER)
    assert created["success"] is True
    receipt_id = created["data"]["id"]

    with pytest.raises(HTTPException) as ex:
        rc.update_allocations(
            receipt_id,
            ReceiptAllocationsUpdateIn(allocations=[
                ReceiptAllocationIn(sales_invoice_id=bad_inv["id"], allocated_paise=50000),
            ]),
            CALLER,
        )
    assert ex.value.status_code == 422
    assert "draft" in ex.value.detail.lower()
    # The receipt's original (valid) allocation must survive untouched.
    remaining = [a for a in db.rows("receipt_allocations") if a.get("receipt_id") == receipt_id]
    assert len(remaining) == 1
    assert remaining[0]["sales_invoice_id"] == good_inv["id"]


def test_update_allocations_rejects_cancelled_invoice(monkeypatch):
    cu, si, rc, db = _setup(monkeypatch)
    cust = _customer(cu)
    good_inv = _issued_invoice(si, cust["id"], "INV-GOOD-2")
    bad_inv = _cancelled_invoice(si, cust["id"], "INV-CANC-2")

    created = rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2026-04-05",
        amount_paise=118000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=good_inv["id"], allocated_paise=118000)]),
        CALLER)
    assert created["success"] is True
    receipt_id = created["data"]["id"]

    with pytest.raises(HTTPException) as ex:
        rc.update_allocations(
            receipt_id,
            ReceiptAllocationsUpdateIn(allocations=[
                ReceiptAllocationIn(sales_invoice_id=bad_inv["id"], allocated_paise=50000),
            ]),
            CALLER,
        )
    assert ex.value.status_code == 422
    assert "cancelled" in ex.value.detail.lower()
