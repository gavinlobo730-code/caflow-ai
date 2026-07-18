"""
Multi-invoice bank allocation — end to end.

A single bank transaction can now settle MULTIPLE sales invoices (AR, a credit
transaction -> a receipt with receipt_allocations, the existing engine) or
MULTIPLE purchase bills (AP, a debit transaction -> a NEW purchase_payment with
purchase_payment_allocations, migration 226) in one settlement, instead of only
matching 1:1. These tests drive the REAL engines (services.purchase_payment_service,
services.bank_posting_service.match_and_settle_multi, services.reversal_service)
against the shared FakeDB harness so the accounting is actually computed, not mocked.
"""
import pytest
from fastapi import HTTPException

from models.parties import CustomerIn, VendorIn
from models.invoices import SalesInvoiceIn, InvoiceLineIn, PurchaseBillIn, PurchaseBillLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, trial_balance, account_balance, coa_id

FIRM = "FIRM-MULTI"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    import routers.customers as cu
    import routers.vendors as ve
    import routers.sales_invoices as si
    import routers.purchase_bills as pb
    import services.receipt_service as rs
    import services.purchase_payment_service as pps
    import services.bank_posting_service as bps
    import services.reversal_service as rvs

    db = FakeDB()
    wire_e2e(monkeypatch, db, [cu, ve, si, pb, rs, pps])
    # bank_posting_service / reversal_service have no _USE_MOCK flag (always
    # db-driven) but DO import period_validation_service — neutralise it the
    # same way wire_e2e does for the others.
    monkeypatch.setattr(bps.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    monkeypatch.setattr(rvs.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    monkeypatch.setattr(bps.timeline_service, "log", lambda *a, **k: None)

    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Services", "kind": "service"})
    return cu, ve, si, pb, db


def _invoice(si, cust_id, amount_paise, invoice_no):
    """Issue a plain (no-GST-line simplification via a single rated line) invoice
    for exactly amount_paise total by using a GST-free line rate == amount_paise."""
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=cust_id, invoice_date="2026-06-01", invoice_no=invoice_no,
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Svc", hsn_sac="9982",
                             quantity=1, rate_paise=amount_paise, gst_rate_percent=0.0)]), CALLER)["data"]
    si.issue_invoice(inv["id"], CALLER)
    return inv


def _bill(pb, vend_id, amount_paise, bill_no):
    bill = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=vend_id, bill_date="2026-06-01", bill_no=bill_no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="svc", rate_paise=amount_paise,
                                  quantity=1, gst_rate_percent=0.0)]), CALLER)["data"]
    pb.receive_purchase_bill(bill["id"], CALLER)
    return bill


def _enable_multi_currency(db, monkeypatch):
    monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    db.seed("firms", {"id": FIRM, "multi_currency_entitled": True})
    db.seed("clients", {"id": "CLI2", "firm_id": FIRM, "gstin": "27ABCDE5678F1Z5",
                        "functional_currency": "INR", "multi_currency_enabled": True})
    db.seed("currencies", {"code": "USD", "symbol": "$", "display_name": "US Dollar", "minor_unit": 2, "is_active": True})
    db.seed("currencies", {"code": "INR", "symbol": "₹", "display_name": "Indian Rupee", "minor_unit": 2, "is_active": True})
    seed_standard_coa(db, FIRM, "CLI2")
    db.seed("service_catalogue", {"id": "SVC-FX", "firm_id": FIRM, "client_id": "CLI2",
                                  "name": "Export Services", "kind": "service"})


def _usd_bill(pb, vend_id, rate, cents, bill_no):
    bill = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI2", vendor_id=vend_id, bill_date="2025-06-01", bill_no=bill_no,
        currency="USD", exchange_rate=str(rate),
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-FX", description="svc", rate_paise=cents,
                                  quantity=1, gst_rate_percent=0.0)]), CALLER)["data"]
    pb.receive_purchase_bill(bill["id"], CALLER)
    return bill


def _txn(db, amount_paise, is_credit, reference_no="STMT-1"):
    return db.seed("bank_transactions", {
        "firm_id": FIRM, "client_id": "CLI", "transaction_date": "2026-06-15",
        "description": "Bulk settlement", "reference_no": reference_no,
        "debit_paise": 0 if is_credit else amount_paise,
        "credit_paise": amount_paise if is_credit else 0,
        "balance_paise": 0, "match_status": "unmatched",
    })


# ── AP: domestic multi-bill payment (purchase_payment_service.create_payment_core) ──

def test_multi_bill_payment_settles_two_bills_fully(monkeypatch):
    cu, ve, si, pb, db = _setup(monkeypatch)
    import services.purchase_payment_service as pps
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="Acme Supplies", state_code="27"), CALLER)["data"]
    bill1 = _bill(pb, vend["id"], 100_000, "BILL-1")
    bill2 = _bill(pb, vend["id"], 50_000, "BILL-2")

    payment = pps.create_payment_core(FIRM, {
        "client_id": "CLI", "vendor_id": vend["id"], "payment_date": "2026-06-20",
        "amount_paise": 150_000, "payment_mode": "bank",
        "allocations": [
            {"purchase_bill_id": bill1["id"], "allocated_paise": 100_000},
            {"purchase_bill_id": bill2["id"], "allocated_paise": 50_000},
        ],
    }, CALLER, db)

    assert payment["unallocated_paise"] == 0
    assert payment["purchase_bill_id"] is None   # multi-bill => allocations table, not the legacy FK
    allocs = db.table("purchase_payment_allocations").select("*").eq("purchase_payment_id", payment["id"]).execute().data
    assert {(a["purchase_bill_id"], a["allocated_paise"]) for a in allocs} == {
        (bill1["id"], 100_000), (bill2["id"], 50_000),
    }

    b1 = db.table("purchase_bills").select("*").eq("id", bill1["id"]).execute().data[0]
    b2 = db.table("purchase_bills").select("*").eq("id", bill2["id"]).execute().data[0]
    assert b1["paid_paise"] == 100_000 and b1["status"] == "paid"
    assert b2["paid_paise"] == 50_000 and b2["status"] == "paid"

    # Dr Trade Payables 150,000 / Cr Bank 150,000 — one balanced journal.
    lines = db.table("journal_lines").select("*").eq("journal_entry_id", payment["journal_entry_id"]).execute().data
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines) == 150_000


def test_multi_bill_payment_partial_allocation_leaves_unallocated(monkeypatch):
    cu, ve, si, pb, db = _setup(monkeypatch)
    import services.purchase_payment_service as pps
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="Beta Traders", state_code="27"), CALLER)["data"]
    bill1 = _bill(pb, vend["id"], 100_000, "BILL-3")

    payment = pps.create_payment_core(FIRM, {
        "client_id": "CLI", "vendor_id": vend["id"], "payment_date": "2026-06-20",
        "amount_paise": 130_000, "payment_mode": "bank",
        "allocations": [{"purchase_bill_id": bill1["id"], "allocated_paise": 100_000}],
    }, CALLER, db)

    assert payment["unallocated_paise"] == 30_000
    b1 = db.table("purchase_bills").select("*").eq("id", bill1["id"]).execute().data[0]
    assert b1["paid_paise"] == 100_000 and b1["status"] == "paid"
    # The full cash amount (including the unallocated advance) still hits Trade Payables/Bank.
    lines = db.table("journal_lines").select("*").eq("journal_entry_id", payment["journal_entry_id"]).execute().data
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines) == 130_000


def test_multi_bill_payment_rejects_over_allocation(monkeypatch):
    cu, ve, si, pb, db = _setup(monkeypatch)
    import services.purchase_payment_service as pps
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="Gamma Co", state_code="27"), CALLER)["data"]
    bill1 = _bill(pb, vend["id"], 100_000, "BILL-4")

    with pytest.raises(HTTPException) as exc:
        pps.create_payment_core(FIRM, {
            "client_id": "CLI", "vendor_id": vend["id"], "payment_date": "2026-06-20",
            "amount_paise": 50_000, "payment_mode": "bank",
            "allocations": [{"purchase_bill_id": bill1["id"], "allocated_paise": 100_000}],
        }, CALLER, db)
    assert exc.value.status_code == 422
    assert "exceeds payment amount" in exc.value.detail


def test_multi_bill_payment_rejects_allocation_exceeding_bill_outstanding(monkeypatch):
    cu, ve, si, pb, db = _setup(monkeypatch)
    import services.purchase_payment_service as pps
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="Delta Ltd", state_code="27"), CALLER)["data"]
    bill1 = _bill(pb, vend["id"], 100_000, "BILL-5")

    with pytest.raises(HTTPException) as exc:
        pps.create_payment_core(FIRM, {
            "client_id": "CLI", "vendor_id": vend["id"], "payment_date": "2026-06-20",
            "amount_paise": 150_000, "payment_mode": "bank",
            "allocations": [{"purchase_bill_id": bill1["id"], "allocated_paise": 150_000}],
        }, CALLER, db)
    assert exc.value.status_code == 422
    assert "exceed bill outstanding" in exc.value.detail


# ── Bank multi-match: AR (credit txn -> multiple invoices, one receipt) ──────────

def test_bank_multi_match_settles_two_invoices_via_one_receipt(monkeypatch):
    cu, ve, si, pb, db = _setup(monkeypatch)
    import services.bank_posting_service as bps
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="United Traders", state_code="27"), CALLER)["data"]
    inv1 = _invoice(si, cust["id"], 60_000, "INV-BULK-1")
    inv2 = _invoice(si, cust["id"], 40_000, "INV-BULK-2")
    txn = _txn(db, 100_000, is_credit=True)

    result = bps.bank_posting_service.match_and_settle_multi(
        db, FIRM, txn["id"], "sales_invoice",
        [{"entity_id": inv1["id"], "allocated_paise": 60_000},
         {"entity_id": inv2["id"], "allocated_paise": 40_000}],
        actor=CALLER,
    )
    assert result["matched_entity_type"] == "receipt"
    assert result["allocations_count"] == 2

    txn_row = db.table("bank_transactions").select("*").eq("id", txn["id"]).execute().data[0]
    assert txn_row["match_status"] == "posted"
    assert txn_row["matched_entity_id"] == result["matched_entity_id"]
    assert txn_row["posted_journal_id"] == result["journal_entry_id"]

    inv1_row = db.table("client_sales_invoices").select("*").eq("id", inv1["id"]).execute().data[0]
    inv2_row = db.table("client_sales_invoices").select("*").eq("id", inv2["id"]).execute().data[0]
    assert inv1_row["status"] == "paid" and inv2_row["status"] == "paid"

    # Exactly ONE journal for this cash movement — Dr Bank 100,000 / Cr Trade Receivables 100,000.
    lines = db.table("journal_lines").select("*").eq("journal_entry_id", result["journal_entry_id"]).execute().data
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines) == 100_000


def test_bank_multi_match_rejects_mixed_customers(monkeypatch):
    cu, ve, si, pb, db = _setup(monkeypatch)
    import services.bank_posting_service as bps
    cust1 = cu.create_customer(CustomerIn(client_id="CLI", name="Cust A", state_code="27"), CALLER)["data"]
    cust2 = cu.create_customer(CustomerIn(client_id="CLI", name="Cust B", state_code="27"), CALLER)["data"]
    inv1 = _invoice(si, cust1["id"], 60_000, "INV-MIX-1")
    inv2 = _invoice(si, cust2["id"], 40_000, "INV-MIX-2")
    txn = _txn(db, 100_000, is_credit=True)

    with pytest.raises(HTTPException) as exc:
        bps.bank_posting_service.match_and_settle_multi(
            db, FIRM, txn["id"], "sales_invoice",
            [{"entity_id": inv1["id"], "allocated_paise": 60_000},
             {"entity_id": inv2["id"], "allocated_paise": 40_000}],
            actor=CALLER,
        )
    assert exc.value.status_code == 422
    assert "SAME customer/vendor" in exc.value.detail


def test_bank_multi_match_rejects_wrong_direction(monkeypatch):
    cu, ve, si, pb, db = _setup(monkeypatch)
    import services.bank_posting_service as bps
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="Cust C", state_code="27"), CALLER)["data"]
    inv1 = _invoice(si, cust["id"], 60_000, "INV-DIR-1")
    txn = _txn(db, 60_000, is_credit=False)   # a DEBIT (money leaving) can't settle a sales invoice

    with pytest.raises(HTTPException) as exc:
        bps.bank_posting_service.match_and_settle_multi(
            db, FIRM, txn["id"], "sales_invoice",
            [{"entity_id": inv1["id"], "allocated_paise": 60_000}],
            actor=CALLER,
        )
    assert exc.value.status_code == 422
    assert "cannot settle sales invoices" in exc.value.detail


def test_bank_multi_match_rejects_already_posted_transaction(monkeypatch):
    cu, ve, si, pb, db = _setup(monkeypatch)
    import services.bank_posting_service as bps
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="Cust D", state_code="27"), CALLER)["data"]
    inv1 = _invoice(si, cust["id"], 60_000, "INV-DUP-1")
    txn = _txn(db, 60_000, is_credit=True)
    db.table("bank_transactions").update({"match_status": "posted"}).eq("id", txn["id"]).execute()

    with pytest.raises(HTTPException) as exc:
        bps.bank_posting_service.match_and_settle_multi(
            db, FIRM, txn["id"], "sales_invoice",
            [{"entity_id": inv1["id"], "allocated_paise": 60_000}],
            actor=CALLER,
        )
    assert exc.value.status_code == 409


# ── Bank multi-match: AP (debit txn -> multiple bills, one payment) ──────────────

def test_bank_multi_match_settles_two_bills_via_one_payment(monkeypatch):
    cu, ve, si, pb, db = _setup(monkeypatch)
    import services.bank_posting_service as bps
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="Vendor Bulk", state_code="27"), CALLER)["data"]
    bill1 = _bill(pb, vend["id"], 70_000, "BILL-BULK-1")
    bill2 = _bill(pb, vend["id"], 30_000, "BILL-BULK-2")
    txn = _txn(db, 100_000, is_credit=False)

    result = bps.bank_posting_service.match_and_settle_multi(
        db, FIRM, txn["id"], "purchase_bill",
        [{"entity_id": bill1["id"], "allocated_paise": 70_000},
         {"entity_id": bill2["id"], "allocated_paise": 30_000}],
        actor=CALLER,
    )
    assert result["matched_entity_type"] == "purchase_payment"

    txn_row = db.table("bank_transactions").select("*").eq("id", txn["id"]).execute().data[0]
    assert txn_row["match_status"] == "posted"
    assert txn_row["matched_entity_id"] == result["matched_entity_id"]

    b1 = db.table("purchase_bills").select("*").eq("id", bill1["id"]).execute().data[0]
    b2 = db.table("purchase_bills").select("*").eq("id", bill2["id"]).execute().data[0]
    assert b1["status"] == "paid" and b2["status"] == "paid"

    lines = db.table("journal_lines").select("*").eq("journal_entry_id", result["journal_entry_id"]).execute().data
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines) == 100_000


# ── Reversal of a multi-bill payment ─────────────────────────────────────────────

def test_reverse_multi_bill_payment_rolls_back_both_bills(monkeypatch):
    cu, ve, si, pb, db = _setup(monkeypatch)
    import services.purchase_payment_service as pps
    import services.reversal_service as rvs
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="Epsilon Inc", state_code="27"), CALLER)["data"]
    bill1 = _bill(pb, vend["id"], 100_000, "BILL-REV-1")
    bill2 = _bill(pb, vend["id"], 50_000, "BILL-REV-2")
    ap_after_bills = account_balance(db, coa_id(db, FIRM, "ap"))

    payment = pps.create_payment_core(FIRM, {
        "client_id": "CLI", "vendor_id": vend["id"], "payment_date": "2026-06-20",
        "amount_paise": 150_000, "payment_mode": "bank",
        "allocations": [
            {"purchase_bill_id": bill1["id"], "allocated_paise": 100_000},
            {"purchase_bill_id": bill2["id"], "allocated_paise": 50_000},
        ],
    }, CALLER, db)

    result = rvs.reverse_payment(db, FIRM, payment["id"], "2026-06-25", created_by=CALLER["id"])
    assert result["reversed"] is True
    assert set(result["bills_adjusted"]) == {bill1["id"], bill2["id"]}

    b1 = db.table("purchase_bills").select("*").eq("id", bill1["id"]).execute().data[0]
    b2 = db.table("purchase_bills").select("*").eq("id", bill2["id"]).execute().data[0]
    assert b1["paid_paise"] == 0 and b1["status"] == "received"
    assert b2["paid_paise"] == 0 and b2["status"] == "received"
    assert account_balance(db, coa_id(db, FIRM, "ap")) == ap_after_bills   # AP restored

    pay_row = db.table("purchase_payments").select("*").eq("id", payment["id"]).execute().data[0]
    assert pay_row["is_reversed"] is True
    allocs = db.table("purchase_payment_allocations").select("*").eq("purchase_payment_id", payment["id"]).execute().data
    assert all(a["is_voided"] for a in allocs)


def test_reverse_multi_bill_payment_rejects_double_reversal(monkeypatch):
    cu, ve, si, pb, db = _setup(monkeypatch)
    import services.purchase_payment_service as pps
    import services.reversal_service as rvs
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="Zeta LLP", state_code="27"), CALLER)["data"]
    bill1 = _bill(pb, vend["id"], 100_000, "BILL-REV-3")

    payment = pps.create_payment_core(FIRM, {
        "client_id": "CLI", "vendor_id": vend["id"], "payment_date": "2026-06-20",
        "amount_paise": 100_000, "payment_mode": "bank",
        "allocations": [{"purchase_bill_id": bill1["id"], "allocated_paise": 100_000}],
    }, CALLER, db)

    rvs.reverse_payment(db, FIRM, payment["id"], "2026-06-25", created_by=CALLER["id"])
    with pytest.raises(HTTPException) as exc:
        rvs.reverse_payment(db, FIRM, payment["id"], "2026-06-26", created_by=CALLER["id"])
    assert exc.value.status_code == 422


# ── AP: foreign-currency multi-bill payment (realized FX) ───────────────────────

def test_multi_bill_foreign_payment_settles_two_bills_with_realized_fx(monkeypatch):
    cu, ve, si, pb, db = _setup(monkeypatch)
    import services.purchase_payment_service as pps
    _enable_multi_currency(db, monkeypatch)
    vend = ve.create_vendor(VendorIn(client_id="CLI2", name="US Vendor", state_code="27"), CALLER)["data"]
    # Two $1,000 bills booked at 80 -> AP ₹80,000 each (₹160,000 total booked).
    # AP is credit-normal, so account_balance (debit - credit) reads negative.
    bill1 = _usd_bill(pb, vend["id"], 80.0, 100000, "USB-1")
    bill2 = _usd_bill(pb, vend["id"], 80.0, 100000, "USB-2")
    assert account_balance(db, coa_id(db, FIRM, "ap")) == -16_000_000

    # Pay both bills in full, $2,000 total, at a WORSE rate (83) -> a realized loss.
    payment = pps.create_payment_core(FIRM, {
        "client_id": "CLI2", "vendor_id": vend["id"], "payment_date": "2025-07-01",
        "amount_paise": 200000, "payment_mode": "bank", "currency": "USD", "exchange_rate": "83.0",
        "allocations": [
            {"purchase_bill_id": bill1["id"], "allocated_paise": 100000},
            {"purchase_bill_id": bill2["id"], "allocated_paise": 100000},
        ],
    }, CALLER, db)

    # Both bills relieved EXACTLY at their booked rate (₹160,000 total), not the
    # cash rate — the extra ₹6,000 paid is a realized FX LOSS, not extra AP relief.
    assert account_balance(db, coa_id(db, FIRM, "ap")) == 0
    assert account_balance(db, coa_id(db, FIRM, "bank")) == -16_600_000   # cash paid at R1
    assert account_balance(db, coa_id(db, FIRM, "fx_realized")) == 600_000  # debit = loss
    b1 = db.table("purchase_bills").select("*").eq("id", bill1["id"]).execute().data[0]
    b2 = db.table("purchase_bills").select("*").eq("id", bill2["id"]).execute().data[0]
    assert b1["status"] == "paid" and b2["status"] == "paid"
    tb = trial_balance(db, FIRM, "CLI2")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]

    allocs = db.table("purchase_payment_allocations").select("*").eq("purchase_payment_id", payment["id"]).execute().data
    # Allocations are recorded at the BOOKED-rate relief (₹80,000 each), not the cash rate.
    assert {a["allocated_paise"] for a in allocs} == {8_000_000}
    assert len(allocs) == 2


def test_bank_multi_match_foreign_bills(monkeypatch):
    cu, ve, si, pb, db = _setup(monkeypatch)
    import services.bank_posting_service as bps
    _enable_multi_currency(db, monkeypatch)
    vend = ve.create_vendor(VendorIn(client_id="CLI2", name="US Vendor 2", state_code="27"), CALLER)["data"]
    bill1 = _usd_bill(pb, vend["id"], 80.0, 60000, "USB-3")
    bill2 = _usd_bill(pb, vend["id"], 80.0, 40000, "USB-4")
    txn = db.seed("bank_transactions", {
        "firm_id": FIRM, "client_id": "CLI2", "transaction_date": "2025-07-01",
        "description": "USD wire", "reference_no": "WIRE-1",
        "debit_paise": 100000, "credit_paise": 0, "balance_paise": 0, "match_status": "unmatched",
    })

    result = bps.bank_posting_service.match_and_settle_multi(
        db, FIRM, txn["id"], "purchase_bill",
        [{"entity_id": bill1["id"], "allocated_paise": 60000},
         {"entity_id": bill2["id"], "allocated_paise": 40000}],
        currency="USD", exchange_rate="80.0", actor=CALLER,
    )
    assert result["matched_entity_type"] == "purchase_payment"
    b1 = db.table("purchase_bills").select("*").eq("id", bill1["id"]).execute().data[0]
    b2 = db.table("purchase_bills").select("*").eq("id", bill2["id"]).execute().data[0]
    assert b1["status"] == "paid" and b2["status"] == "paid"
    tb = trial_balance(db, FIRM, "CLI2")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


# ── Model validation (pure Pydantic, no DB) ──────────────────────────────────────

def test_bank_match_multi_model_validation():
    from models.banking import BankMatchMultiIn, BankMatchAllocationIn
    from pydantic import ValidationError

    # Valid.
    m = BankMatchMultiIn(entity_type="sales_invoice",
                         allocations=[BankMatchAllocationIn(entity_id="i1", allocated_paise=100)])
    assert m.entity_type == "sales_invoice"

    # Bad entity_type.
    with pytest.raises(ValidationError):
        BankMatchMultiIn(entity_type="journal_entry", allocations=[{"entity_id": "i1", "allocated_paise": 100}])

    # Empty allocations rejected.
    with pytest.raises(ValidationError):
        BankMatchMultiIn(entity_type="sales_invoice", allocations=[])

    # Non-positive allocated_paise rejected.
    with pytest.raises(ValidationError):
        BankMatchAllocationIn(entity_id="i1", allocated_paise=0)
    with pytest.raises(ValidationError):
        BankMatchAllocationIn(entity_id="i1", allocated_paise=-5)

    # Negative tds_paise rejected.
    with pytest.raises(ValidationError):
        BankMatchMultiIn(entity_type="sales_invoice",
                         allocations=[{"entity_id": "i1", "allocated_paise": 100}], tds_paise=-1)
