"""Reverse-receipt / reverse-payment cascades (task #102) — end to end.

cancel_invoice/cancel_purchase_bill refuse to cancel a document with
receipts/payments applied, directing the caller to "reverse the receipt(s)/
payment(s) first" — these tests prove that path now exists and actually
unblocks cancellation, correctly rolls back the sub-ledger and GL, and that
a reversed receipt/payment stops appearing as live financial activity.
"""
import pytest
from fastapi import HTTPException

import routers.accounting as acct
from models.accounting import JournalReversalIn
from models.parties import CustomerIn, VendorIn
from models.invoices import (
    SalesInvoiceIn, InvoiceLineIn, ReceiptIn, ReceiptAllocationIn,
    PurchaseBillIn, PurchaseBillLineIn, PurchasePaymentIn,
)
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, trial_balance, account_balance, coa_id

FIRM = "FIRM-REV"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    import routers.customers as cu
    import routers.sales_invoices as si
    import routers.receipts as rc
    import routers.purchase_bills as pb
    import routers.purchase_payments as pp
    import routers.vendors as ve
    import services.receipt_service as rs
    db = FakeDB()
    wire_e2e(monkeypatch, db, [cu, si, rc, pb, pp, ve, rs, acct])
    # accounting.reverse_journal_entry checks os.environ directly (not a
    # module _USE_MOCK flag like every other router wire_e2e flips).
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Services", "kind": "service"})
    return cu, si, rc, pb, pp, ve, db


def _invoice(si, cust_id, rate_paise=1_180_000, invoice_no="INV-1"):
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=cust_id, invoice_date="2026-06-01", invoice_no=invoice_no,
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Svc", hsn_sac="9982", quantity=1,
                             rate_paise=1_000_000, gst_rate_percent=18.0)]), CALLER)["data"]
    si.issue_invoice(inv["id"], CALLER)
    return inv


def _bill(pb, vend_id, bill_no="BILL-1"):
    bill = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=vend_id, bill_date="2026-06-01", bill_no=bill_no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="svc", rate_paise=500_000,
                                  quantity=1, gst_rate_percent=18.0)]), CALLER)["data"]
    pb.receive_purchase_bill(bill["id"], CALLER)
    return bill


# ── reverse_receipt ─────────────────────────────────────────────────────────

def test_reverse_receipt_rolls_back_invoice_and_journal(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="Acme", state_code="27"), CALLER)["data"]
    inv = _invoice(si, cust["id"])
    ar_after_invoice = account_balance(db, coa_id(db, FIRM, "ar"))

    rcpt = rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2026-06-10",
        amount_paise=1_180_000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=1_180_000)]), CALLER)["data"]
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 0
    inv_row = db.table("client_sales_invoices").select("*").eq("id", inv["id"]).execute().data[0]
    assert inv_row["paid_paise"] == 1_180_000 and inv_row["status"] == "paid"

    result = rc.reverse_receipt(rcpt["id"], JournalReversalIn(reversal_date="2026-06-15"), CALLER)
    assert result["success"] is True

    inv_row = db.table("client_sales_invoices").select("*").eq("id", inv["id"]).execute().data[0]
    assert inv_row["paid_paise"] == 0 and inv_row["status"] == "issued"
    assert account_balance(db, coa_id(db, FIRM, "ar")) == ar_after_invoice   # AR restored to pre-receipt

    rcpt_row = db.table("receipts").select("*").eq("id", rcpt["id"]).execute().data[0]
    assert rcpt_row["is_reversed"] is True
    allocs = db.table("receipt_allocations").select("*").eq("receipt_id", rcpt["id"]).execute().data
    assert all(a["is_voided"] for a in allocs)

    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


def test_reverse_receipt_with_multiple_allocations(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="Acme", state_code="27"), CALLER)["data"]
    inv1 = _invoice(si, cust["id"], invoice_no="INV-A")
    inv2 = _invoice(si, cust["id"], invoice_no="INV-B")

    rcpt = rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2026-06-10",
        amount_paise=2_360_000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv1["id"], allocated_paise=1_180_000),
                     ReceiptAllocationIn(sales_invoice_id=inv2["id"], allocated_paise=1_180_000)]), CALLER)["data"]

    rc.reverse_receipt(rcpt["id"], JournalReversalIn(reversal_date="2026-06-15"), CALLER)

    row1 = db.table("client_sales_invoices").select("*").eq("id", inv1["id"]).execute().data[0]
    row2 = db.table("client_sales_invoices").select("*").eq("id", inv2["id"]).execute().data[0]
    assert row1["paid_paise"] == 0 and row1["status"] == "issued"
    assert row2["paid_paise"] == 0 and row2["status"] == "issued"


def test_reverse_receipt_unblocks_cancel_invoice(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="Acme", state_code="27"), CALLER)["data"]
    inv = _invoice(si, cust["id"])
    rcpt = rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2026-06-10", amount_paise=1_180_000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=1_180_000)]), CALLER)["data"]

    # Blocked before reversal — the exact scenario task #102 set out to fix.
    with pytest.raises(HTTPException) as ex:
        si.cancel_invoice(inv["id"], CALLER)
    assert ex.value.status_code == 409

    rc.reverse_receipt(rcpt["id"], JournalReversalIn(reversal_date="2026-06-15"), CALLER)

    # Now succeeds.
    result = si.cancel_invoice(inv["id"], CALLER)
    assert result["success"] is True
    assert result["data"]["status"] == "cancelled"


def test_reverse_receipt_already_reversed_rejected(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="Acme", state_code="27"), CALLER)["data"]
    inv = _invoice(si, cust["id"])
    rcpt = rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2026-06-10", amount_paise=1_180_000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=1_180_000)]), CALLER)["data"]
    rc.reverse_receipt(rcpt["id"], JournalReversalIn(reversal_date="2026-06-15"), CALLER)
    with pytest.raises(HTTPException) as ex:
        rc.reverse_receipt(rcpt["id"], JournalReversalIn(reversal_date="2026-06-16"), CALLER)
    assert ex.value.status_code == 422


def test_reversed_receipt_excluded_from_customer_statement(monkeypatch):
    from services.customer_statement_service import customer_statement_service as CS
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="Acme", state_code="27"), CALLER)["data"]
    inv = _invoice(si, cust["id"])
    rcpt = rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2026-06-10", amount_paise=1_180_000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=1_180_000)]), CALLER)["data"]
    rc.reverse_receipt(rcpt["id"], JournalReversalIn(reversal_date="2026-06-15"), CALLER)

    stmt = CS.generate(db, FIRM, "CLI", cust["id"], "2026-04-01", "2027-03-31")
    assert not any(t["type"] == "receipt" for t in stmt["transactions"])
    assert stmt["closing_balance_paise"] == 1_180_000   # invoice still outstanding — receipt undone


# ── reverse_payment ──────────────────────────────────────────────────────────

def test_reverse_payment_rolls_back_bill_and_journal(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="Acme Supplies", state_code="27"), CALLER)["data"]
    bill = _bill(pb, vend["id"])
    bill_row = db.table("purchase_bills").select("net_payable_paise").eq("id", bill["id"]).execute().data[0]
    net_payable = bill_row["net_payable_paise"]
    ap_after_bill = account_balance(db, coa_id(db, FIRM, "ap"))

    payment = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id=vend["id"], payment_date="2026-06-10",
        amount_paise=net_payable, purchase_bill_id=bill["id"]), CALLER)["data"]
    assert account_balance(db, coa_id(db, FIRM, "ap")) == 0

    result = pp.reverse_purchase_payment(payment["id"], JournalReversalIn(reversal_date="2026-06-15"), CALLER)
    assert result["success"] is True

    bill_row = db.table("purchase_bills").select("*").eq("id", bill["id"]).execute().data[0]
    assert bill_row["paid_paise"] == 0 and bill_row["status"] == "received"
    assert account_balance(db, coa_id(db, FIRM, "ap")) == ap_after_bill

    payment_row = db.table("purchase_payments").select("*").eq("id", payment["id"]).execute().data[0]
    assert payment_row["is_reversed"] is True

    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


def test_reverse_payment_unblocks_cancel_purchase_bill(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="Acme Supplies", state_code="27"), CALLER)["data"]
    bill = _bill(pb, vend["id"])
    bill_row = db.table("purchase_bills").select("net_payable_paise").eq("id", bill["id"]).execute().data[0]
    payment = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id=vend["id"], payment_date="2026-06-10",
        amount_paise=bill_row["net_payable_paise"], purchase_bill_id=bill["id"]), CALLER)["data"]

    with pytest.raises(HTTPException) as ex:
        pb.cancel_purchase_bill(bill["id"], CALLER)
    assert ex.value.status_code == 409

    pp.reverse_purchase_payment(payment["id"], JournalReversalIn(reversal_date="2026-06-15"), CALLER)

    result = pb.cancel_purchase_bill(bill["id"], CALLER)
    assert result["success"] is True
    assert result["data"]["status"] == "cancelled"


def test_reverse_payment_already_reversed_rejected(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="Acme Supplies", state_code="27"), CALLER)["data"]
    bill = _bill(pb, vend["id"])
    bill_row = db.table("purchase_bills").select("net_payable_paise").eq("id", bill["id"]).execute().data[0]
    payment = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id=vend["id"], payment_date="2026-06-10",
        amount_paise=bill_row["net_payable_paise"], purchase_bill_id=bill["id"]), CALLER)["data"]
    pp.reverse_purchase_payment(payment["id"], JournalReversalIn(reversal_date="2026-06-15"), CALLER)
    with pytest.raises(HTTPException) as ex:
        pp.reverse_purchase_payment(payment["id"], JournalReversalIn(reversal_date="2026-06-16"), CALLER)
    assert ex.value.status_code == 422


def test_reversed_payment_excluded_from_vendor_statement(monkeypatch):
    from services.vendor_statement_service import vendor_statement_service as VS
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="Acme Supplies", state_code="27"), CALLER)["data"]
    bill = _bill(pb, vend["id"])
    bill_row = db.table("purchase_bills").select("net_payable_paise").eq("id", bill["id"]).execute().data[0]
    net_payable = bill_row["net_payable_paise"]
    payment = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id=vend["id"], payment_date="2026-06-10",
        amount_paise=net_payable, purchase_bill_id=bill["id"]), CALLER)["data"]
    pp.reverse_purchase_payment(payment["id"], JournalReversalIn(reversal_date="2026-06-15"), CALLER)

    stmt = VS.generate(db, FIRM, "CLI", vend["id"], "2026-04-01", "2027-03-31")
    assert not any(t["type"] == "payment" for t in stmt["transactions"])
    assert stmt["closing_balance_paise"] == net_payable   # bill still outstanding — payment undone


# ── generic reverse endpoint must redirect Receipt/Payment journals ──────────

def test_generic_reverse_endpoint_blocks_receipt_journal(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="Acme", state_code="27"), CALLER)["data"]
    inv = _invoice(si, cust["id"])
    rcpt = rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2026-06-10", amount_paise=1_180_000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=1_180_000)]), CALLER)["data"]
    journal_id = rcpt["journal_entry_id"]

    with pytest.raises(HTTPException) as ex:
        acct.reverse_journal_entry(journal_id, JournalReversalIn(reversal_date="2026-06-15"), CALLER)
    assert ex.value.status_code == 422
    assert "receipts/" in ex.value.detail

    # The journal itself must be untouched — no phantom reversal was created.
    dups = [e for e in db.rows("journal_entries") if e.get("reversal_of") == journal_id]
    assert dups == []


def test_generic_reverse_endpoint_blocks_payment_journal(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="Acme Supplies", state_code="27"), CALLER)["data"]
    bill = _bill(pb, vend["id"])
    bill_row = db.table("purchase_bills").select("net_payable_paise").eq("id", bill["id"]).execute().data[0]
    payment = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id=vend["id"], payment_date="2026-06-10",
        amount_paise=bill_row["net_payable_paise"], purchase_bill_id=bill["id"]), CALLER)["data"]
    journal_id = payment["journal_entry_id"]

    with pytest.raises(HTTPException) as ex:
        acct.reverse_journal_entry(journal_id, JournalReversalIn(reversal_date="2026-06-15"), CALLER)
    assert ex.value.status_code == 422
    assert "purchase-payments/" in ex.value.detail
