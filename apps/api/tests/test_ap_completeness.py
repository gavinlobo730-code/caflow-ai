"""
Production Readiness Phase 5 — AP completeness:
  * H11 — vendor payment links to the bill and sets paid_paise (AP reconciles).
  * M6  — overpayment / cancelled-bill payment blocked.
  * M5  — vendor outstanding = Σ(net_payable − paid − debited), no double-count.
  * H10 — purchase journal debits each line's own expense account.
  * H23 — vendor statement + AP aging derive from posted data.
"""
import pytest
from fastapi import HTTPException

import routers.purchase_bills as pb
import routers.purchase_payments as pp
import routers.vendors as ve
from models.invoices import PurchaseBillIn, PurchaseBillLineIn, PurchasePaymentIn
from services.vendor_statement_service import vendor_statement_service
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, coa_id, account_balance

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb, pp, ve])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z5"})
    db.seed("vendors", {"id": "VEND1", "firm_id": FIRM, "client_id": "CLI", "name": "Supplier",
                        "state_code": "27", "gstin": "27CCCCC2222C1Z5", "tds_applicable": False,
                        "opening_balance_paise": 0})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Materials", "kind": "good"})
    return db


def _bill(db, bid):
    return next(b for b in db.rows("purchase_bills") if b["id"] == bid)


def _received_bill(db, no="B1", rate=1_00000):
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date="2025-06-01", bill_no=no,
        lines=[PurchaseBillLineIn(description="m", rate_paise=rate, quantity=1, gst_rate_percent=18.0,
                                  service_catalogue_id="SVC-1")],
    ), CALLER)
    bid = res["data"]["id"]
    assert pb.receive_purchase_bill(bid, CALLER)["success"] is True
    return bid, res["data"]["net_payable_paise"]


def _pay(db, bid, amount, no_check=False):
    return pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id="VEND1", payment_date="2025-06-10",
        amount_paise=amount, purchase_bill_id=bid,
    ), CALLER)


# ── H11: payment links to bill, sets paid_paise ───────────────────────────────
def test_payment_links_and_sets_paid(monkeypatch):
    db = _setup(monkeypatch)
    bid, net = _received_bill(db, rate=1_00000)        # net_payable 118000
    _pay(db, bid, 50000)
    bill = _bill(db, bid)
    assert bill["paid_paise"] == 50000 and bill["status"] == "partially_paid"
    _pay(db, bid, 68000)
    bill = _bill(db, bid)
    assert bill["paid_paise"] == 118000 and bill["status"] == "paid"


# ── M6: overpayment and cancelled-bill payment blocked ────────────────────────
def test_overpayment_blocked(monkeypatch):
    db = _setup(monkeypatch)
    bid, net = _received_bill(db, rate=1_00000)
    with pytest.raises(HTTPException) as ex:
        _pay(db, bid, net + 1)
    assert ex.value.status_code == 422


def test_payment_on_cancelled_bill_blocked(monkeypatch):
    db = _setup(monkeypatch)
    bid, net = _received_bill(db, rate=1_00000)
    _bill(db, bid)["status"] = "cancelled"
    with pytest.raises(HTTPException) as ex:
        _pay(db, bid, 1000)
    assert ex.value.status_code == 409


# ── M5: vendor outstanding nets payments correctly (no double-count) ──────────
def test_vendor_outstanding_after_full_payment_is_zero(monkeypatch):
    db = _setup(monkeypatch)
    bid, net = _received_bill(db, rate=1_00000)
    _pay(db, bid, net)                                  # fully paid → bill excluded
    # Old bug: paid bill dropped from the sum but payment still subtracted → negative.
    assert ve.get_vendor_outstanding("VEND1", CALLER)["data"]["outstanding_paise"] == 0


# ── H10: purchase journal debits each line's own expense account ──────────────
def test_per_line_expense_accounts(monkeypatch):
    db = _setup(monkeypatch)
    a = db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": "CLI", "system_account_key": None,
                                      "account_name": "Rent", "account_type": "Expense", "is_active": True})["id"]
    b = db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": "CLI", "system_account_key": None,
                                      "account_name": "Consumables", "account_type": "Expense", "is_active": True})["id"]
    svc_rent = db.seed("service_catalogue", {"firm_id": FIRM, "client_id": "CLI",
                                             "name": "Rent", "kind": "service"})["id"]
    svc_cons = db.seed("service_catalogue", {"firm_id": FIRM, "client_id": "CLI",
                                             "name": "Consumables", "kind": "good"})["id"]
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date="2025-06-01", bill_no="B-2LINE",
        lines=[
            PurchaseBillLineIn(description="rent", rate_paise=60000, quantity=1, gst_rate_percent=18.0, expense_account_id=a, service_catalogue_id=svc_rent),
            PurchaseBillLineIn(description="cons", rate_paise=40000, quantity=1, gst_rate_percent=18.0, expense_account_id=b, service_catalogue_id=svc_cons),
        ],
    ), CALLER)
    assert pb.receive_purchase_bill(res["data"]["id"], CALLER)["success"] is True
    assert account_balance(db, a) == 60000            # each expense hits its own ledger
    assert account_balance(db, b) == 40000


# ── H23: vendor statement + AP aging ──────────────────────────────────────────
def test_vendor_statement_and_ap_aging(monkeypatch):
    db = _setup(monkeypatch)
    bid, net = _received_bill(db, rate=1_00000)         # payable 118000
    _pay(db, bid, 18000)                                # pay 18000 → outstanding 100000

    stmt = vendor_statement_service.generate(db, FIRM, "CLI", "VEND1", "2025-04-01", "2026-03-31")
    assert stmt["opening_balance_paise"] == 0
    assert stmt["closing_balance_paise"] == net - 18000  # 100000 payable
    assert stmt["totals"]["billed_paise"] == net and stmt["totals"]["paid_paise"] == 18000

    aging = vendor_statement_service.ap_aging(db, FIRM, "CLI", as_of="2025-06-15")
    assert aging["total_outstanding_paise"] == net - 18000
    assert sum(aging["buckets"].values()) == net - 18000
