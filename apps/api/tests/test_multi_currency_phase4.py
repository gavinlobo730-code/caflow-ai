"""
Multi-Currency Phase 4 — FX accounting (realized + unrealized), end-to-end.

Realized: a settlement at a rate different from the document's booked rate posts
the difference to Realized FX Gain/Loss (append-only, through the kernel); the
original document and its rate are never touched; partial/multiple settlements
carry the outstanding correctly with no rounding drift. Unrealized: period-end
revaluation of open foreign AR/AP at the closing rate, auto-reversed next period,
idempotent + self-healing. The GL always balances in base (INR).
"""
import pytest
from fastapi import HTTPException

from models.parties import CustomerIn, VendorIn
from models.invoices import (
    SalesInvoiceIn, InvoiceLineIn, ReceiptIn, ReceiptAllocationIn,
    PurchaseBillIn, PurchaseBillLineIn, PurchasePaymentIn,
)
from domain.currency.fx_revaluation_service import fx_revaluation_service as REVAL
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, trial_balance, account_balance, coa_id

FIRM = "FIRM-MC4"
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
    wire_e2e(monkeypatch, db, [cu, si, rc, pb, pp, ve, rs])
    monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    db.seed("firms", {"id": FIRM, "multi_currency_entitled": True})
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5",
                        "functional_currency": "INR", "multi_currency_enabled": True})
    db.seed("currencies", {"code": "USD", "symbol": "$", "display_name": "US Dollar", "minor_unit": 2, "is_active": True})
    db.seed("currencies", {"code": "INR", "symbol": "₹", "display_name": "Indian Rupee", "minor_unit": 2, "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Services", "kind": "service"})
    return cu, si, rc, pb, pp, ve, db


def _usd_invoice(si, cust_id, rate, *, date="2025-06-01", cents=100000, invoice_no="USD-001"):
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=cust_id, invoice_date=date,
        invoice_no=invoice_no,
        currency="USD", exchange_rate=str(rate),
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Export", hsn_sac="9982", quantity=1,
                             rate_paise=cents, gst_rate_percent=0.0)]), CALLER)["data"]
    si.issue_invoice(inv["id"], CALLER)
    return inv


# ── Realized FX on customer receipt ───────────────────────────────────────────
def test_realized_fx_gain_on_receipt(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="US", state_code="27"), CALLER)["data"]
    inv = _usd_invoice(si, cust["id"], 80.0)                       # AR ₹80,000
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 8_000_000

    rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2025-07-01",
        amount_paise=100000, currency="USD", exchange_rate="83.0",   # rate rose → gain
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=100000)]), CALLER)

    assert account_balance(db, coa_id(db, FIRM, "ar")) == 0                 # settled at R0
    assert account_balance(db, coa_id(db, FIRM, "bank")) == 8_300_000       # cash at R1
    assert account_balance(db, coa_id(db, FIRM, "fx_realized")) == -300_000 # credit = gain
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]
    # original invoice + its rate untouched
    row = db.table("client_sales_invoices").select("*").eq("id", inv["id"]).execute().data[0]
    assert str(row["exchange_rate"]) in ("80", "80.0", "80.00000000") and row["status"] == "paid"


def test_realized_fx_loss_on_receipt(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="US", state_code="27"), CALLER)["data"]
    inv = _usd_invoice(si, cust["id"], 80.0)
    rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2025-07-01",
        amount_paise=100000, currency="USD", exchange_rate="78.0",   # rate fell → loss
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=100000)]), CALLER)
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 0
    assert account_balance(db, coa_id(db, FIRM, "bank")) == 7_800_000
    assert account_balance(db, coa_id(db, FIRM, "fx_realized")) == 200_000  # debit = loss
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


def test_partial_then_final_settlement_no_drift(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="US", state_code="27"), CALLER)["data"]
    inv = _usd_invoice(si, cust["id"], 80.0)                       # $1000 → AR ₹80,000
    # Partial $400 @ 82
    rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2025-07-01",
        amount_paise=40000, currency="USD", exchange_rate="82.0",
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=40000)]), CALLER)
    row = db.table("client_sales_invoices").select("*").eq("id", inv["id"]).execute().data[0]
    assert row["status"] == "partially_paid" and row["paid_txn"] == 40000
    assert row["paid_paise"] == 3_200_000                          # 40000 * 80
    # Final $600 @ 85 clears exactly (base snapped — no drift)
    rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2025-08-01",
        amount_paise=60000, currency="USD", exchange_rate="85.0",
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=60000)]), CALLER)
    row = db.table("client_sales_invoices").select("*").eq("id", inv["id"]).execute().data[0]
    assert row["status"] == "paid" and row["paid_txn"] == 100000 and row["paid_paise"] == 8_000_000
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 0        # no residual paise
    # realized gain = (82-80)*400 + (85-80)*600 = 800 + 3000 = ₹3,800 = 380,000 paise (credit)
    assert account_balance(db, coa_id(db, FIRM, "fx_realized")) == -380_000
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


# ── Realized FX on vendor payment ─────────────────────────────────────────────
def test_realized_fx_on_vendor_payment(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="US V", state_code="27"), CALLER)["data"]
    bill = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=vend["id"], bill_date="2025-06-01", bill_no="UB1",
        currency="USD", exchange_rate="80.0",
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="svc", rate_paise=100000, quantity=1, gst_rate_percent=0.0)]), CALLER)["data"]
    pb.receive_purchase_bill(bill["id"], CALLER)
    assert account_balance(db, coa_id(db, FIRM, "ap")) == -8_000_000        # AP credit
    # Pay $1000 @ 83 → we paid MORE INR than booked → loss
    pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id=vend["id"], payment_date="2025-07-01",
        amount_paise=100000, currency="USD", exchange_rate="83.0", purchase_bill_id=bill["id"]), CALLER)
    assert account_balance(db, coa_id(db, FIRM, "ap")) == 0
    assert account_balance(db, coa_id(db, FIRM, "bank")) == -8_300_000      # cash out at R1
    assert account_balance(db, coa_id(db, FIRM, "fx_realized")) == 300_000  # debit = loss
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


# ── Unrealized period-end revaluation (AR) — post, reverse, idempotent, heal ──
def test_ar_revaluation_idempotent_and_self_healing(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="US", state_code="27"), CALLER)["data"]
    _usd_invoice(si, cust["id"], 80.0)          # open $1000 AR carried at ₹80,000

    # Run 1 @ closing 84 → target +₹4,000 (400000 paise): Dr AR / Cr Unrealized FX + reversal.
    r1 = REVAL.revalue(db, FIRM, "CLI", "2026-03-31", {"USD": "84.0"}, CALLER)
    adj = [a for a in r1["adjustments"] if a["item_type"] == "receivable"][0]
    assert adj["delta_paise"] == 400_000 and adj["journal_entry_id"] and adj["reversal_entry_id"]
    assert len(db.table("fx_revaluations").select("*").eq("period_end", "2026-03-31").execute().data) == 1
    # GL still balances (revaluation + its auto-reversal are both balanced).
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]

    # Run 2 @ same rate → idempotent: delta 0, no new revaluation row/journal.
    r2 = REVAL.revalue(db, FIRM, "CLI", "2026-03-31", {"USD": "84.0"}, CALLER)
    assert [a for a in r2["adjustments"] if a["item_type"] == "receivable"][0]["delta_paise"] == 0
    assert len(db.table("fx_revaluations").select("*").eq("period_end", "2026-03-31").execute().data) == 1

    # Run 3 @ 86 → self-heal: posts only the +₹2,000 delta (target 600000 − prior 400000).
    r3 = REVAL.revalue(db, FIRM, "CLI", "2026-03-31", {"USD": "86.0"}, CALLER)
    assert [a for a in r3["adjustments"] if a["item_type"] == "receivable"][0]["delta_paise"] == 200_000
    assert len(db.table("fx_revaluations").select("*").eq("period_end", "2026-03-31").execute().data) == 2
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


def test_ap_revaluation_posts_loss(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="US V", state_code="27"), CALLER)["data"]
    bill = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=vend["id"], bill_date="2025-06-01", bill_no="UB2",
        currency="USD", exchange_rate="80.0",
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="svc", rate_paise=100000, quantity=1, gst_rate_percent=0.0)]), CALLER)["data"]
    pb.receive_purchase_bill(bill["id"], CALLER)                    # open $1000 AP at ₹80,000
    r = REVAL.revalue(db, FIRM, "CLI", "2026-03-31", {"USD": "84.0"}, CALLER)
    adj = [a for a in r["adjustments"] if a["item_type"] == "payable"][0]
    assert adj["delta_paise"] == 400_000                            # owe ₹4,000 more (loss)
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


# ── Validations (Task 6) ──────────────────────────────────────────────────────
def test_revaluation_missing_closing_rate_rejected(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="US", state_code="27"), CALLER)["data"]
    _usd_invoice(si, cust["id"], 80.0)
    with pytest.raises(HTTPException) as ex:
        REVAL.revalue(db, FIRM, "CLI", "2026-03-31", {}, CALLER)   # no USD rate
    assert ex.value.status_code == 422 and "closing rate" in ex.value.detail.lower()


def test_receipt_unsupported_currency_rejected(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="US", state_code="27"), CALLER)["data"]
    inv = _usd_invoice(si, cust["id"], 80.0)
    with pytest.raises(HTTPException) as ex:
        rc.create_receipt(ReceiptIn(
            client_id="CLI", customer_id=cust["id"], receipt_date="2025-07-01",
            amount_paise=100000, currency="ZZZ", exchange_rate="80.0",
            allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=100000)]), CALLER)
    assert ex.value.status_code == 422
