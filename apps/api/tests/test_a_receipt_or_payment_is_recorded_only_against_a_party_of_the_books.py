"""
Task #227 findings #2 and #6 — a receipt/payment must never be recorded
against a customer/vendor that doesn't belong to THIS firm+client's books,
and this check must run for foreign-currency documents too, not just INR.

Before this fix:
  - receipt_service.create_receipt_core's customer lookup was correctly
    scoped by firm+client but failed OPEN when no row came back (nonexistent
    or cross-client customer_id silently passed through).
  - purchase_payment_service.create_payment_core and
    routers/purchase_payments.create_purchase_payment's vendor lookups were
    scoped by firm ONLY (not client) and also failed open on no match — a
    vendor belonging to a DIFFERENT client of the same firm passed straight
    through to a real payment.
  - Both checks ran AFTER the foreign-currency dispatch, so a non-INR
    receipt/payment bypassed the check entirely regardless of the above.

Exercised via the shared e2e_harness FakeDB (real router/service code, not
the check in isolation).
"""
import pytest
from fastapi import HTTPException

from models.parties import CustomerIn, VendorIn
from models.invoices import (
    SalesInvoiceIn, InvoiceLineIn, ReceiptIn, ReceiptAllocationIn,
    PurchaseBillIn, PurchaseBillLineIn, PurchasePaymentIn,
)
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-R227-2"
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
    db.seed("firms", {"id": FIRM, "multi_currency_entitled": True})
    for cid in ("CLI-A", "CLI-B"):
        db.seed("clients", {"id": cid, "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5",
                            "functional_currency": "INR", "multi_currency_enabled": True})
        seed_standard_coa(db, FIRM, cid)
    db.seed("currencies", {"code": "USD", "symbol": "$", "display_name": "US Dollar", "minor_unit": 2, "is_active": True})
    db.seed("currencies", {"code": "INR", "symbol": "₹", "display_name": "Indian Rupee", "minor_unit": 2, "is_active": True})
    for cid in ("CLI-A", "CLI-B"):
        db.seed("service_catalogue", {"id": f"SVC-{cid}", "firm_id": FIRM, "client_id": cid,
                                      "name": "Services", "kind": "service"})
    return cu, ve, si, pb, rc, pp, db


def _issued_invoice(si, client_id, cust_id, invoice_no, **kwargs):
    inv = si.create_invoice(SalesInvoiceIn(
        client_id=client_id, customer_id=cust_id, invoice_date="2026-04-01",
        invoice_no=invoice_no,
        lines=[InvoiceLineIn(service_catalogue_id=f"SVC-{client_id}", description="Consulting", hsn_sac="9982",
                             quantity=1, rate_paise=100000, gst_rate_percent=18.0)],
        **kwargs), CALLER)["data"]
    si.issue_invoice(inv["id"], CALLER)
    return inv


def _received_bill(pb, client_id, vendor_id, bill_no, **kwargs):
    bill = pb.create_purchase_bill(PurchaseBillIn(
        client_id=client_id, vendor_id=vendor_id, bill_date="2026-04-01",
        bill_no=bill_no,
        lines=[PurchaseBillLineIn(service_catalogue_id=f"SVC-{client_id}", description="Supplies", hsn_sac="9982",
                                  quantity=1, rate_paise=100000, gst_rate_percent=18.0)],
        **kwargs), CALLER)["data"]
    pb.receive_purchase_bill(bill["id"], CALLER)
    return bill


# ── receipts: customer must belong to THIS client's books ───────────────────

def test_create_receipt_rejects_nonexistent_customer(monkeypatch):
    cu, ve, si, pb, rc, pp, db = _setup(monkeypatch)

    with pytest.raises(HTTPException) as ex:
        rc.create_receipt(ReceiptIn(
            client_id="CLI-A", customer_id="does-not-exist", receipt_date="2026-04-05",
            amount_paise=1000, allocations=[]), CALLER)
    assert ex.value.status_code == 422
    assert "not part of this client" in ex.value.detail.lower()
    assert db.rows("receipts") == []


def test_create_receipt_rejects_customer_from_another_client(monkeypatch):
    cu, ve, si, pb, rc, pp, db = _setup(monkeypatch)
    cust_b = cu.create_customer(CustomerIn(client_id="CLI-B", name="B Co", state_code="27"), CALLER)["data"]

    with pytest.raises(HTTPException) as ex:
        rc.create_receipt(ReceiptIn(
            client_id="CLI-A", customer_id=cust_b["id"], receipt_date="2026-04-05",
            amount_paise=1000, allocations=[]), CALLER)
    assert ex.value.status_code == 422
    assert "not part of this client" in ex.value.detail.lower()
    assert db.rows("receipts") == []


def test_create_foreign_receipt_rejects_customer_from_another_client(monkeypatch):
    """Finding #6: the FX path used to dispatch BEFORE this check ran at all."""
    cu, ve, si, pb, rc, pp, db = _setup(monkeypatch)
    monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    cust_b = cu.create_customer(CustomerIn(client_id="CLI-B", name="B Co", state_code="27"), CALLER)["data"]

    with pytest.raises(HTTPException) as ex:
        rc.create_receipt(ReceiptIn(
            client_id="CLI-A", customer_id=cust_b["id"], receipt_date="2026-04-05",
            amount_paise=100000, currency="USD", exchange_rate="83.0", allocations=[]), CALLER)
    assert ex.value.status_code == 422
    assert "not part of this client" in ex.value.detail.lower()
    assert db.rows("receipts") == []


def test_create_receipt_still_accepts_own_client_customer(monkeypatch):
    cu, ve, si, pb, rc, pp, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI-A", name="Acme", state_code="27"), CALLER)["data"]
    inv = _issued_invoice(si, "CLI-A", cust["id"], "INV-OK-1")

    result = rc.create_receipt(ReceiptIn(
        client_id="CLI-A", customer_id=cust["id"], receipt_date="2026-04-05",
        amount_paise=118000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=118000)]), CALLER)
    assert result["success"] is True


# ── vendor payments (single-bill router path): vendor must belong to THIS client ──

def test_create_purchase_payment_rejects_nonexistent_vendor(monkeypatch):
    cu, ve, si, pb, rc, pp, db = _setup(monkeypatch)

    with pytest.raises(HTTPException) as ex:
        pp.create_purchase_payment(PurchasePaymentIn(
            client_id="CLI-A", vendor_id="does-not-exist", payment_date="2026-04-05",
            amount_paise=1000), CALLER)
    assert ex.value.status_code == 422
    assert "not part of this client" in ex.value.detail.lower()
    assert db.rows("purchase_payments") == []


def test_create_purchase_payment_rejects_vendor_from_another_client(monkeypatch):
    cu, ve, si, pb, rc, pp, db = _setup(monkeypatch)
    vendor_b = ve.create_vendor(VendorIn(client_id="CLI-B", name="B Supplies", state_code="27"), CALLER)["data"]

    with pytest.raises(HTTPException) as ex:
        pp.create_purchase_payment(PurchasePaymentIn(
            client_id="CLI-A", vendor_id=vendor_b["id"], payment_date="2026-04-05",
            amount_paise=1000), CALLER)
    assert ex.value.status_code == 422
    assert "not part of this client" in ex.value.detail.lower()
    assert db.rows("purchase_payments") == []


def test_create_foreign_payment_rejects_vendor_from_another_client(monkeypatch):
    """Finding #6 (AP side): the FX path used to dispatch BEFORE this check
    ran at all."""
    cu, ve, si, pb, rc, pp, db = _setup(monkeypatch)
    monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    vendor_b = ve.create_vendor(VendorIn(client_id="CLI-B", name="B Supplies", state_code="27"), CALLER)["data"]

    with pytest.raises(HTTPException) as ex:
        pp.create_purchase_payment(PurchasePaymentIn(
            client_id="CLI-A", vendor_id=vendor_b["id"], payment_date="2026-04-05",
            amount_paise=100000, currency="USD", exchange_rate="83.0"), CALLER)
    assert ex.value.status_code == 422
    assert "not part of this client" in ex.value.detail.lower()
    assert db.rows("purchase_payments") == []


def test_create_purchase_payment_still_accepts_own_client_vendor(monkeypatch):
    cu, ve, si, pb, rc, pp, db = _setup(monkeypatch)
    vendor = ve.create_vendor(VendorIn(client_id="CLI-A", name="A Supplies", state_code="27"), CALLER)["data"]
    bill = _received_bill(pb, "CLI-A", vendor["id"], "BILL-OK-1")

    result = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI-A", vendor_id=vendor["id"], payment_date="2026-04-05",
        amount_paise=118000, purchase_bill_id=bill["id"]), CALLER)
    assert result["success"] is True


# ── vendor payments (multi-bill service path): purchase_payment_service.create_payment_core ──

def test_create_payment_core_rejects_vendor_from_another_client(monkeypatch):
    cu, ve, si, pb, rc, pp, db = _setup(monkeypatch)
    import services.purchase_payment_service as pps
    vendor_b = ve.create_vendor(VendorIn(client_id="CLI-B", name="B Supplies", state_code="27"), CALLER)["data"]

    with pytest.raises(HTTPException) as ex:
        pps.create_payment_core(FIRM, {
            "client_id": "CLI-A", "vendor_id": vendor_b["id"], "payment_date": "2026-04-05",
            "amount_paise": 1000, "allocations": [],
        }, CALLER, db)
    assert ex.value.status_code == 422
    assert "not part of this client" in ex.value.detail.lower()
    assert db.rows("purchase_payments") == []
