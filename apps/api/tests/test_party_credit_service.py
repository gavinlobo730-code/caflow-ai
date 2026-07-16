"""Party credit balances (task #102) — QuickBooks-style non-GST tracking of a
bank overpayment sitting against a customer/vendor, and its later application
to a specific invoice/bill. Service-level + router-level + bank-posting
integration."""
import pytest
from fastapi import HTTPException

import routers.party_credits as pc_router
from services.party_credit_service import party_credit_service as PCS
from tests.e2e_harness import FakeDB, wire_e2e

FIRM, CLIENT, CUST, VENDOR = "firm-1", "client-1", "cust-1", "vendor-1"


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pc_router])
    return db


# ── grant_credit ────────────────────────────────────────────────────────────

def test_grant_creates_balance_and_ledger_row(monkeypatch):
    db = _setup(monkeypatch)
    row = PCS.grant_credit(db, FIRM, CLIENT, "customer", CUST, 5000,
                           source_type="bank_overpayment", source_id="txn-1", created_by="u1")
    assert row["kind"] == "grant" and row["amount_paise"] == 5000
    assert PCS.get_balance(db, FIRM, CLIENT, "customer", CUST) == 5000


def test_grant_accumulates_on_existing_balance(monkeypatch):
    db = _setup(monkeypatch)
    PCS.grant_credit(db, FIRM, CLIENT, "customer", CUST, 5000, source_type="bank_overpayment")
    PCS.grant_credit(db, FIRM, CLIENT, "customer", CUST, 3000, source_type="bank_overpayment")
    assert PCS.get_balance(db, FIRM, CLIENT, "customer", CUST) == 8000
    ledger = PCS.ledger(db, FIRM, CLIENT, "customer", CUST)
    assert len(ledger) == 2 and all(r["kind"] == "grant" for r in ledger)


def test_grant_rejects_non_positive_amount(monkeypatch):
    db = _setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        PCS.grant_credit(db, FIRM, CLIENT, "customer", CUST, 0, source_type="bank_overpayment")
    assert e.value.status_code == 422


def test_grant_rejects_invalid_party_type(monkeypatch):
    db = _setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        PCS.grant_credit(db, FIRM, CLIENT, "supplier", CUST, 1000, source_type="x")
    assert e.value.status_code == 422


def test_different_parties_and_clients_are_isolated(monkeypatch):
    db = _setup(monkeypatch)
    PCS.grant_credit(db, FIRM, CLIENT, "customer", CUST, 5000, source_type="bank_overpayment")
    PCS.grant_credit(db, FIRM, CLIENT, "vendor", VENDOR, 2000, source_type="bank_overpayment")
    PCS.grant_credit(db, FIRM, "other-client", "customer", CUST, 9000, source_type="bank_overpayment")
    assert PCS.get_balance(db, FIRM, CLIENT, "customer", CUST) == 5000
    assert PCS.get_balance(db, FIRM, CLIENT, "vendor", VENDOR) == 2000
    assert PCS.get_balance(db, FIRM, "other-client", "customer", CUST) == 9000


# ── apply_credit ─────────────────────────────────────────────────────────────

def _seed_invoice(db, **overrides):
    row = {"id": "inv-1", "firm_id": FIRM, "client_id": CLIENT, "customer_id": CUST,
           "invoice_no": "INV-1", "total_paise": 100000, "paid_paise": 0, "status": "issued"}
    row.update(overrides)
    db.seed("client_sales_invoices", row)
    return row


def _seed_bill(db, **overrides):
    row = {"id": "bill-1", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": VENDOR,
           "bill_no": "BILL-1", "total_paise": 50000, "paid_paise": 0, "status": "received"}
    row.update(overrides)
    db.seed("purchase_bills", row)
    return row


def test_apply_credit_settles_invoice_and_debits_balance(monkeypatch):
    db = _setup(monkeypatch)
    inv = _seed_invoice(db)
    PCS.grant_credit(db, FIRM, CLIENT, "customer", CUST, 40000, source_type="bank_overpayment")
    PCS.apply_credit(db, FIRM, CLIENT, "customer", CUST, 40000, "sales_invoice", inv["id"], created_by="u1")

    assert PCS.get_balance(db, FIRM, CLIENT, "customer", CUST) == 0
    row = next(r for r in db.rows("client_sales_invoices") if r["id"] == inv["id"])
    assert row["paid_paise"] == 40000 and row["status"] == "partially_paid"
    ledger = PCS.ledger(db, FIRM, CLIENT, "customer", CUST)
    application = next(r for r in ledger if r["kind"] == "application")
    assert application["amount_paise"] == -40000
    assert application["applied_to_type"] == "sales_invoice" and application["applied_to_id"] == inv["id"]


def test_apply_credit_can_fully_settle_bill(monkeypatch):
    db = _setup(monkeypatch)
    bill = _seed_bill(db)
    PCS.grant_credit(db, FIRM, CLIENT, "vendor", VENDOR, 50000, source_type="bank_overpayment")
    PCS.apply_credit(db, FIRM, CLIENT, "vendor", VENDOR, 50000, "purchase_bill", bill["id"], created_by="u1")

    assert PCS.get_balance(db, FIRM, CLIENT, "vendor", VENDOR) == 0
    row = next(r for r in db.rows("purchase_bills") if r["id"] == bill["id"])
    assert row["paid_paise"] == 50000 and row["status"] == "paid"


def test_apply_credit_rejects_insufficient_balance(monkeypatch):
    db = _setup(monkeypatch)
    inv = _seed_invoice(db)
    PCS.grant_credit(db, FIRM, CLIENT, "customer", CUST, 10000, source_type="bank_overpayment")
    with pytest.raises(HTTPException) as e:
        PCS.apply_credit(db, FIRM, CLIENT, "customer", CUST, 40000, "sales_invoice", inv["id"])
    assert e.value.status_code == 422
    assert PCS.get_balance(db, FIRM, CLIENT, "customer", CUST) == 10000   # untouched


def test_apply_credit_rejects_amount_exceeding_document_outstanding(monkeypatch):
    db = _setup(monkeypatch)
    inv = _seed_invoice(db, total_paise=10000)
    PCS.grant_credit(db, FIRM, CLIENT, "customer", CUST, 40000, source_type="bank_overpayment")
    with pytest.raises(HTTPException) as e:
        PCS.apply_credit(db, FIRM, CLIENT, "customer", CUST, 40000, "sales_invoice", inv["id"])
    assert e.value.status_code == 422
    # Balance is restored (compensation), not silently lost on the failed application.
    assert PCS.get_balance(db, FIRM, CLIENT, "customer", CUST) == 40000


def test_apply_credit_rejects_mismatched_party_type(monkeypatch):
    db = _setup(monkeypatch)
    bill = _seed_bill(db)
    PCS.grant_credit(db, FIRM, CLIENT, "customer", CUST, 40000, source_type="bank_overpayment")
    with pytest.raises(HTTPException) as e:
        PCS.apply_credit(db, FIRM, CLIENT, "customer", CUST, 40000, "purchase_bill", bill["id"])
    assert e.value.status_code == 422


def test_apply_credit_rejects_document_belonging_to_a_different_party(monkeypatch):
    db = _setup(monkeypatch)
    inv = _seed_invoice(db, customer_id="some-other-customer")
    PCS.grant_credit(db, FIRM, CLIENT, "customer", CUST, 40000, source_type="bank_overpayment")
    with pytest.raises(HTTPException) as e:
        PCS.apply_credit(db, FIRM, CLIENT, "customer", CUST, 40000, "sales_invoice", inv["id"])
    assert e.value.status_code == 422
    assert PCS.get_balance(db, FIRM, CLIENT, "customer", CUST) == 40000   # restored


def test_apply_credit_no_new_journal_entry(monkeypatch):
    # The GL was already correct when the credit was granted (the original
    # bank transaction's journal posted the FULL amount) — applying it later
    # must be a pure sub-ledger move, not a new posting.
    db = _setup(monkeypatch)
    inv = _seed_invoice(db)
    PCS.grant_credit(db, FIRM, CLIENT, "customer", CUST, 40000, source_type="bank_overpayment")
    before = len(db.rows("journal_entries"))
    PCS.apply_credit(db, FIRM, CLIENT, "customer", CUST, 40000, "sales_invoice", inv["id"])
    assert len(db.rows("journal_entries")) == before


# ── list_balances ────────────────────────────────────────────────────────────

def test_list_balances_excludes_zero_and_other_clients(monkeypatch):
    db = _setup(monkeypatch)
    inv = _seed_invoice(db)
    PCS.grant_credit(db, FIRM, CLIENT, "customer", CUST, 40000, source_type="bank_overpayment")
    PCS.grant_credit(db, FIRM, CLIENT, "vendor", VENDOR, 15000, source_type="bank_overpayment")
    PCS.apply_credit(db, FIRM, CLIENT, "customer", CUST, 40000, "sales_invoice", inv["id"])  # zeroes it out
    PCS.grant_credit(db, FIRM, "other-client", "customer", "other-cust", 9000, source_type="bank_overpayment")

    rows = PCS.list_balances(db, FIRM, CLIENT)
    assert len(rows) == 1 and rows[0]["party_id"] == VENDOR and rows[0]["balance_paise"] == 15000


# ── router ───────────────────────────────────────────────────────────────────

def test_router_apply_end_to_end(monkeypatch):
    db = _setup(monkeypatch)
    inv = _seed_invoice(db)
    PCS.grant_credit(db, FIRM, CLIENT, "customer", CUST, 40000, source_type="bank_overpayment")

    res = pc_router.apply_party_credit(
        pc_router.ApplyPartyCreditIn(client_id=CLIENT, party_type="customer", party_id=CUST,
                                     amount_paise=40000, applied_to_type="sales_invoice", applied_to_id=inv["id"]),
        {"firm_id": FIRM, "id": "u1"},
    )
    assert res["success"] is True
    assert PCS.get_balance(db, FIRM, CLIENT, "customer", CUST) == 0


def test_router_get_returns_balance_and_ledger(monkeypatch):
    db = _setup(monkeypatch)
    PCS.grant_credit(db, FIRM, CLIENT, "vendor", VENDOR, 7000, source_type="bank_overpayment")
    res = pc_router.get_party_credit("vendor", VENDOR, client_id=CLIENT, current_user={"firm_id": FIRM})
    assert res["success"] is True
    assert res["data"]["balance_paise"] == 7000
    assert len(res["data"]["ledger"]) == 1
