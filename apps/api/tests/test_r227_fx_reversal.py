"""
Task #227 finding #3 — reversing a receipt/payment that touched a
foreign-currency invoice/bill must roll back paid_txn (the cumulative
SETTLED FOREIGN amount, tracked separately from paid_paise so partial FX
settlements never drift — see create_foreign_receipt/create_foreign_payment_core),
not just paid_paise.

Before this fix, reversal_service._rollback_invoice_paid/_rollback_bill_paid
only ever touched paid_paise — reversing a receipt/payment against a foreign
document left paid_txn permanently inflated, understating that document's
true outstanding in its billing currency (foreign_out = txn_total - paid_txn)
forever after, even though the base-currency AR/AP and GL were correctly
restored.

Migration 236 adds receipt_allocations.allocated_txn /
purchase_payment_allocations.allocated_txn so the exact foreign amount each
allocation added to paid_txn is recoverable at reversal time; the legacy
single-bill foreign payment path already stores it directly on the payment
row (payment.txn_amount), used instead.
"""
import pytest
from fastapi import HTTPException

from models.accounting import JournalReversalIn
from models.parties import CustomerIn, VendorIn
from models.invoices import (
    SalesInvoiceIn, InvoiceLineIn, ReceiptIn, ReceiptAllocationIn,
    PurchaseBillIn, PurchaseBillLineIn, PurchasePaymentIn,
)
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-R227-FX"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    import routers.customers as cu
    import routers.vendors as ve
    import routers.sales_invoices as si
    import routers.purchase_bills as pb
    import routers.receipts as rc
    import routers.purchase_payments as pp
    import services.receipt_service as rs
    import services.purchase_payment_service as pps
    db = FakeDB()
    wire_e2e(monkeypatch, db, [cu, ve, si, pb, rc, pp, rs, pps])
    monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    db.seed("firms", {"id": FIRM, "multi_currency_entitled": True})
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5",
                        "functional_currency": "INR", "multi_currency_enabled": True})
    db.seed("currencies", {"code": "USD", "symbol": "$", "display_name": "US Dollar", "minor_unit": 2, "is_active": True})
    db.seed("currencies", {"code": "INR", "symbol": "₹", "display_name": "Indian Rupee", "minor_unit": 2, "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Services", "kind": "service"})
    return cu, ve, si, pb, rc, pp, db


def _usd_invoice(si, cust_id, rate=80.0, *, cents=100000, invoice_no="USD-INV-1"):
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=cust_id, invoice_date="2026-06-01",
        invoice_no=invoice_no, currency="USD", exchange_rate=str(rate),
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Export", hsn_sac="9982", quantity=1,
                             rate_paise=cents, gst_rate_percent=0.0)]), CALLER)["data"]
    si.issue_invoice(inv["id"], CALLER)
    return inv


def _usd_bill(pb, vend_id, rate=80.0, *, cents=100000, bill_no="USD-BILL-1"):
    bill = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=vend_id, bill_date="2026-06-01", bill_no=bill_no,
        currency="USD", exchange_rate=str(rate),
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="Import", hsn_sac="9982",
                                  quantity=1, rate_paise=cents, gst_rate_percent=0.0)]), CALLER)["data"]
    pb.receive_purchase_bill(bill["id"], CALLER)
    return bill


def _inv_row(db, inv_id):
    return db.table("client_sales_invoices").select("*").eq("id", inv_id).execute().data[0]


def _bill_row(db, bill_id):
    return db.table("purchase_bills").select("*").eq("id", bill_id).execute().data[0]


# ── receipts: full settlement ────────────────────────────────────────────────

def test_reverse_receipt_rolls_back_paid_txn_on_fully_settled_foreign_invoice(monkeypatch):
    cu, ve, si, pb, rc, pp, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="US Co", state_code="27"), CALLER)["data"]
    inv = _usd_invoice(si, cust["id"])

    rcpt = rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2026-06-10",
        amount_paise=100000, currency="USD", exchange_rate="83.0",
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=100000)]), CALLER)["data"]

    row = _inv_row(db, inv["id"])
    assert row["paid_txn"] == 100000 and row["status"] == "paid"

    result = rc.reverse_receipt(rcpt["id"], JournalReversalIn(reversal_date="2026-06-15"), CALLER)
    assert result["success"] is True

    row = _inv_row(db, inv["id"])
    assert row["paid_txn"] == 0, "paid_txn must roll back to 0, not stay inflated"
    assert row["paid_paise"] == 0
    assert row["status"] == "issued"


def test_reverse_receipt_rolls_back_paid_txn_exactly_on_partial_foreign_settlement(monkeypatch):
    cu, ve, si, pb, rc, pp, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="US Co", state_code="27"), CALLER)["data"]
    inv = _usd_invoice(si, cust["id"], cents=100000)

    rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2026-06-10",
        amount_paise=40000, currency="USD", exchange_rate="83.0",
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=40000)]), CALLER)["data"]
    paid_paise_after_first = _inv_row(db, inv["id"])["paid_paise"]

    second = rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2026-06-12",
        amount_paise=60000, currency="USD", exchange_rate="84.0",
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=60000)]), CALLER)["data"]

    row = _inv_row(db, inv["id"])
    assert row["paid_txn"] == 100000 and row["status"] == "paid"

    # Reversing only the SECOND receipt must decrement paid_txn by exactly its
    # own 60000 — not zero it out, not touch the first receipt's 40000.
    rc.reverse_receipt(second["id"], JournalReversalIn(reversal_date="2026-06-15"), CALLER)

    row = _inv_row(db, inv["id"])
    assert row["paid_txn"] == 40000
    assert row["paid_paise"] == paid_paise_after_first
    assert row["status"] == "partially_paid"


# ── vendor payments: legacy single-bill foreign path ─────────────────────────

def test_reverse_purchase_payment_rolls_back_paid_txn_on_single_bill_foreign_path(monkeypatch):
    cu, ve, si, pb, rc, pp, db = _setup(monkeypatch)
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="US Supplies", state_code="27"), CALLER)["data"]
    bill = _usd_bill(pb, vend["id"], cents=100000)

    payment = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id=vend["id"], payment_date="2026-06-10",
        amount_paise=100000, purchase_bill_id=bill["id"],
        currency="USD", exchange_rate="83.0"), CALLER)["data"]

    row = _bill_row(db, bill["id"])
    assert row["paid_txn"] == 100000 and row["status"] == "paid"

    result = pp.reverse_purchase_payment(payment["id"], JournalReversalIn(reversal_date="2026-06-15"), CALLER)
    assert result["success"] is True

    row = _bill_row(db, bill["id"])
    assert row["paid_txn"] == 0, "paid_txn must roll back to 0, not stay inflated"
    assert row["paid_paise"] == 0
    assert row["status"] == "received"


# ── vendor payments: multi-bill foreign path (purchase_payment_service) ──────

def test_reverse_purchase_payment_rolls_back_paid_txn_on_multi_bill_foreign_path(monkeypatch):
    cu, ve, si, pb, rc, pp, db = _setup(monkeypatch)
    import services.purchase_payment_service as pps
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="US Supplies", state_code="27"), CALLER)["data"]
    bill1 = _usd_bill(pb, vend["id"], cents=50000, bill_no="USD-BILL-A")
    bill2 = _usd_bill(pb, vend["id"], cents=50000, bill_no="USD-BILL-B")

    payment = pps.create_payment_core(FIRM, {
        "client_id": "CLI", "vendor_id": vend["id"], "payment_date": "2026-06-10",
        "amount_paise": 100000, "currency": "USD", "exchange_rate": "83.0",
        "allocations": [
            {"purchase_bill_id": bill1["id"], "allocated_paise": 50000},
            {"purchase_bill_id": bill2["id"], "allocated_paise": 50000},
        ],
    }, CALLER, db)

    row1 = _bill_row(db, bill1["id"])
    row2 = _bill_row(db, bill2["id"])
    assert row1["paid_txn"] == 50000 and row1["status"] == "paid"
    assert row2["paid_txn"] == 50000 and row2["status"] == "paid"

    result = pp.reverse_purchase_payment(payment["id"], JournalReversalIn(reversal_date="2026-06-15"), CALLER)
    assert result["success"] is True

    row1 = _bill_row(db, bill1["id"])
    row2 = _bill_row(db, bill2["id"])
    assert row1["paid_txn"] == 0 and row1["paid_paise"] == 0 and row1["status"] == "received"
    assert row2["paid_txn"] == 0 and row2["paid_paise"] == 0 and row2["status"] == "received"
