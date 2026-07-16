"""
Multi-Currency Phase 3 — foreign-currency business documents (end-to-end).

Drives the REAL document endpoints against one FakeDB with the feature fully
enabled, and asserts: the GL balances entirely in base (INR); the document stores
both foreign and base amounts + a frozen rate; settlement clears AR/AP at the
booked rate; and every Task-6 validation fires on the backend. INR behaviour is
covered by the full existing suite (unchanged).
"""
import pytest
from fastapi import HTTPException

from models.parties import CustomerIn, VendorIn
from models.invoices import (
    SalesInvoiceIn, InvoiceLineIn, ReceiptIn, ReceiptAllocationIn,
    PurchaseBillIn, PurchaseBillLineIn, PurchasePaymentIn, SalesInvoiceUpdateIn,
)
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, trial_balance, account_balance, coa_id

FIRM = "FIRM-MC3"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch, *, entitled=True, client_enabled=True, platform=True):
    import routers.customers as cu
    import routers.sales_invoices as si
    import routers.receipts as rc
    import routers.purchase_bills as pb
    import routers.purchase_payments as pp
    import routers.vendors as ve
    import services.receipt_service as rs
    db = FakeDB()
    wire_e2e(monkeypatch, db, [cu, si, rc, pb, pp, ve, rs])
    if platform:
        monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    else:
        monkeypatch.delenv("MULTI_CURRENCY_ENABLED", raising=False)
    db.seed("firms", {"id": FIRM, "multi_currency_entitled": entitled})
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5",
                        "functional_currency": "INR", "multi_currency_enabled": client_enabled})
    db.seed("currencies", {"code": "USD", "symbol": "$", "display_name": "US Dollar", "minor_unit": 2, "is_active": True})
    db.seed("currencies", {"code": "INR", "symbol": "₹", "display_name": "Indian Rupee", "minor_unit": 2, "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Services", "kind": "service"})
    return cu, si, rc, pb, pp, ve, db


# ── Foreign sales invoice → issue → receipt (settle at booked rate) ───────────
def test_foreign_sales_cycle_gl_balances_in_base(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="US Buyer", state_code="27"), CALLER)["data"]

    # USD 1000.00 taxable @ 18% intra-state, rate 83.5 (INR per USD).
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=cust["id"], invoice_no="MC3-001", invoice_date="2025-06-01",
        currency="USD", exchange_rate="83.5",
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Export consulting", hsn_sac="9982",
                             quantity=1, rate_paise=100000, gst_rate_percent=18.0)]), CALLER)["data"]

    # Foreign + base both stored; base is authoritative.
    assert inv["txn_currency"] == "USD"
    assert str(inv["exchange_rate"]) in ("83.5", "83.50000000")
    assert inv["txn_taxable"] == 100000 and inv["txn_total"] == 118000
    assert inv["taxable_amount_paise"] == 8_350_000            # 100000 * 83.5
    assert inv["total_paise"] == 9_853_000                     # (100000+9000+9000)*83.5, summed components

    si.issue_invoice(inv["id"], CALLER)
    # GL balances entirely in base INR.
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 9_853_000
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"] == 9_853_000

    # Journal lines carry the frozen foreign metadata (G4).
    je = db.table("journal_entries").select("*").eq("reference_no", inv["invoice_no"]).execute().data[0]
    jls = db.table("journal_lines").select("*").eq("journal_entry_id", je["id"]).execute().data
    assert all(l["txn_currency"] == "USD" for l in jls)
    assert str(je.get("rate_overridden")) in ("True", "true")  # manual rate → overridden

    # Settle in full in USD at the SAME rate → AR cleared, Bank debited (base), no FX.
    rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2025-07-01",
        amount_paise=118000, currency="USD", exchange_rate="83.5",
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=118000)]), CALLER)
    paid = db.table("client_sales_invoices").select("*").eq("id", inv["id"]).execute().data[0]
    assert paid["status"] == "paid" and paid["paid_paise"] == 9_853_000
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 0
    assert account_balance(db, coa_id(db, FIRM, "bank")) == 9_853_000
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


# ── Editing a foreign-currency DRAFT invoice must reconvert to base (task #103) ──
def test_foreign_draft_invoice_edit_converts_totals_to_base(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="US Buyer", state_code="27"), CALLER)["data"]

    # USD 1000.00 taxable @ 18% intra-state, rate 83.5 — left as a DRAFT (not issued).
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=cust["id"], invoice_no="MC3-006", invoice_date="2025-06-01",
        currency="USD", exchange_rate="83.5",
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Export consulting", hsn_sac="9982",
                             quantity=1, rate_paise=100000, gst_rate_percent=18.0)]), CALLER)["data"]
    assert inv["taxable_amount_paise"] == 8_350_000            # 1000 * 83.5
    assert inv["total_paise"] == 9_853_000

    # Edit the draft: bump quantity to 2 (rate/GST% unchanged, currency/rate frozen
    # — SalesInvoiceUpdateIn has no currency/exchange_rate field to edit).
    updated = si.update_invoice(inv["id"], SalesInvoiceUpdateIn(
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Export consulting", hsn_sac="9982",
                             quantity=2, rate_paise=100000, gst_rate_percent=18.0)]), CALLER)["data"]

    # New txn-currency (USD) totals: taxable 2000, GST 360 (18%), total 2360.
    assert updated["txn_taxable"] == 200000
    assert updated["txn_total_gst"] == 36000
    assert updated["txn_total"] == 236000
    # Base (INR) columns must be dc.to_base-converted at the frozen rate 83.5,
    # NOT the raw txn-currency figures (the pre-fix bug wrote 200000/236000 here).
    assert updated["taxable_amount_paise"] == 16_700_000        # 200000 * 83.5
    assert updated["total_gst_paise"] == 3_006_000              # 36000 * 83.5
    assert updated["total_paise"] == 19_706_000                 # 236000 * 83.5
    # Frozen currency metadata is untouched by the edit.
    assert updated["txn_currency"] == "USD"
    assert str(updated["exchange_rate"]) in ("83.5", "83.50000000")

    # Issuing now posts the CORRECTED base total to the GL (proves the edit's
    # base columns, not stale creation-time ones, are what get journalised).
    si.issue_invoice(inv["id"], CALLER)
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 19_706_000
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"] == 19_706_000


# ── Foreign purchase bill → payment (settle at booked rate) ───────────────────
def test_foreign_purchase_cycle_gl_balances_in_base(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="US Vendor", state_code="27"), CALLER)["data"]

    bill = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=vend["id"], bill_date="2025-06-01", bill_no="USB-1",
        currency="USD", exchange_rate="83.5",
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="Imported service", rate_paise=100000,
                                  quantity=1, gst_rate_percent=18.0)]), CALLER)["data"]
    assert bill["txn_currency"] == "USD" and bill["txn_total"] == 118000
    assert bill["net_payable_paise"] == 9_853_000             # no TDS → base total
    pb.receive_purchase_bill(bill["id"], CALLER)              # posts the base journal
    assert account_balance(db, coa_id(db, FIRM, "ap")) == -9_853_000   # AP credited (liability)
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"] == 9_853_000

    pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id=vend["id"], payment_date="2025-07-01",
        amount_paise=118000, currency="USD", exchange_rate="83.5", purchase_bill_id=bill["id"]), CALLER)
    paid = db.table("purchase_bills").select("*").eq("id", bill["id"]).execute().data[0]
    assert paid["status"] == "paid" and paid["paid_paise"] == 9_853_000
    assert account_balance(db, coa_id(db, FIRM, "ap")) == 0
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


# ── Task 6 validations (all backend) ──────────────────────────────────────────
def test_foreign_invoice_rejected_when_policy_off(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch, platform=False)  # L1 kill switch off
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="B", state_code="27"), CALLER)["data"]
    with pytest.raises(HTTPException) as ex:
        si.create_invoice(SalesInvoiceIn(
            client_id="CLI", customer_id=cust["id"], invoice_no="MC3-002", invoice_date="2025-06-01",
            currency="USD", exchange_rate="83.5",
            lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="x", rate_paise=100000, gst_rate_percent=0.0)]), CALLER)
    assert ex.value.status_code == 422 and "multi-currency" in ex.value.detail.lower()


def test_unsupported_currency_rejected(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="B", state_code="27"), CALLER)["data"]
    with pytest.raises(HTTPException) as ex:
        si.create_invoice(SalesInvoiceIn(
            client_id="CLI", customer_id=cust["id"], invoice_no="MC3-003", invoice_date="2025-06-01",
            currency="ZZZ", exchange_rate="1.0",
            lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="x", rate_paise=100000, gst_rate_percent=0.0)]), CALLER)
    assert ex.value.status_code == 422 and "unsupported currency" in ex.value.detail.lower()


def test_zero_rate_rejected(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="B", state_code="27"), CALLER)["data"]
    with pytest.raises(HTTPException) as ex:
        si.create_invoice(SalesInvoiceIn(
            client_id="CLI", customer_id=cust["id"], invoice_no="MC3-004", invoice_date="2025-06-01",
            currency="USD", exchange_rate="0",
            lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="x", rate_paise=100000, gst_rate_percent=0.0)]), CALLER)
    assert ex.value.status_code == 422


def test_receipt_currency_mismatch_rejected(monkeypatch):
    cu, si, rc, pb, pp, ve, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="B", state_code="27"), CALLER)["data"]
    # An INR invoice cannot be settled by a USD receipt.
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=cust["id"], invoice_no="MC3-005", invoice_date="2025-06-01",
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="x", rate_paise=100000, gst_rate_percent=0.0)]), CALLER)["data"]
    si.issue_invoice(inv["id"], CALLER)
    with pytest.raises(HTTPException) as ex:
        rc.create_receipt(ReceiptIn(
            client_id="CLI", customer_id=cust["id"], receipt_date="2025-07-01",
            amount_paise=1000, currency="USD", exchange_rate="83.0",
            allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=1000)]), CALLER)
    assert ex.value.status_code == 422 and "mismatch" in ex.value.detail.lower()


# (Cross-rate settlement is no longer rejected — Phase 4 posts realized FX for it;
#  see test_multi_currency_phase4.py.)
