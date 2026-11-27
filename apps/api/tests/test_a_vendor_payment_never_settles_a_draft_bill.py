"""
Task #227 finding #4 — a vendor payment must never settle against a DRAFT
purchase bill, not just a cancelled one.

receive_purchase_bill (draft -> received) posts the AP journal (Dr Expense /
Cr Trade Payable) — a draft bill was never received and has no such journal.
Every payment code path already blocked "cancelled" but not "draft", so a
payment against a still-draft bill posted a real Dr Trade Payable / Cr Bank
journal and marked paid/partially_paid a bill with no real payable behind it
— the exact same class of bug as finding #1 (draft sales invoices).

Exercised across all 5 locations the audit flagged: the two single-bill
router paths (INR + foreign) in routers/purchase_payments.py, and the three
multi-bill service paths in services/purchase_payment_service.py (create,
create_foreign, update_allocations_core).
"""
import pytest
from fastapi import HTTPException

from models.parties import VendorIn
from models.invoices import PurchaseBillIn, PurchaseBillLineIn, PurchasePaymentIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-R227-4"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    import routers.vendors as ve
    import routers.purchase_bills as pb
    import routers.purchase_payments as pp
    import services.purchase_payment_service as pps
    db = FakeDB()
    wire_e2e(monkeypatch, db, [ve, pb, pp, pps])
    monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    db.seed("firms", {"id": FIRM, "multi_currency_entitled": True})
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5",
                        "functional_currency": "INR", "multi_currency_enabled": True})
    db.seed("currencies", {"code": "USD", "symbol": "$", "display_name": "US Dollar", "minor_unit": 2, "is_active": True})
    db.seed("currencies", {"code": "INR", "symbol": "₹", "display_name": "Indian Rupee", "minor_unit": 2, "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Services", "kind": "service"})
    return ve, pb, pp, db


def _draft_bill(pb, vendor_id, bill_no="BILL-DRAFT-1", **kwargs):
    return pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=vendor_id, bill_date="2026-04-01", bill_no=bill_no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="Supplies", hsn_sac="9982",
                                  quantity=1, rate_paise=100000, gst_rate_percent=18.0)],
        **kwargs), CALLER)["data"]


def _received_bill(pb, vendor_id, bill_no="BILL-RCVD-1", **kwargs):
    bill = _draft_bill(pb, vendor_id, bill_no, **kwargs)
    pb.receive_purchase_bill(bill["id"], CALLER)
    return bill


# ── routers/purchase_payments.py: single-bill INR path ──────────────────────

def test_create_purchase_payment_rejects_draft_bill(monkeypatch):
    ve, pb, pp, db = _setup(monkeypatch)
    vendor = ve.create_vendor(VendorIn(client_id="CLI", name="A Supplies", state_code="27"), CALLER)["data"]
    bill = _draft_bill(pb, vendor["id"])

    with pytest.raises(HTTPException) as ex:
        pp.create_purchase_payment(PurchasePaymentIn(
            client_id="CLI", vendor_id=vendor["id"], payment_date="2026-04-05",
            amount_paise=118000, purchase_bill_id=bill["id"]), CALLER)
    assert ex.value.status_code == 409
    assert "draft" in ex.value.detail.lower()
    assert db.rows("purchase_payments") == []


def test_create_purchase_payment_still_accepts_received_bill(monkeypatch):
    ve, pb, pp, db = _setup(monkeypatch)
    vendor = ve.create_vendor(VendorIn(client_id="CLI", name="A Supplies", state_code="27"), CALLER)["data"]
    bill = _received_bill(pb, vendor["id"])

    result = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id=vendor["id"], payment_date="2026-04-05",
        amount_paise=118000, purchase_bill_id=bill["id"]), CALLER)
    assert result["success"] is True


# ── routers/purchase_payments.py: single-bill FOREIGN path ──────────────────

def test_create_foreign_payment_rejects_draft_bill(monkeypatch):
    ve, pb, pp, db = _setup(monkeypatch)
    vendor = ve.create_vendor(VendorIn(client_id="CLI", name="US Supplies", state_code="27"), CALLER)["data"]
    bill = _draft_bill(pb, vendor["id"], "BILL-USD-DRAFT-1", currency="USD", exchange_rate="80.0")

    with pytest.raises(HTTPException) as ex:
        pp.create_purchase_payment(PurchasePaymentIn(
            client_id="CLI", vendor_id=vendor["id"], payment_date="2026-04-05",
            amount_paise=100000, purchase_bill_id=bill["id"],
            currency="USD", exchange_rate="83.0"), CALLER)
    assert ex.value.status_code == 409
    assert "draft" in ex.value.detail.lower()
    assert db.rows("purchase_payments") == []


# ── services/purchase_payment_service.py: multi-bill INR path ───────────────

def test_create_payment_core_rejects_draft_bill(monkeypatch):
    ve, pb, pp, db = _setup(monkeypatch)
    import services.purchase_payment_service as pps
    vendor = ve.create_vendor(VendorIn(client_id="CLI", name="A Supplies", state_code="27"), CALLER)["data"]
    bill = _draft_bill(pb, vendor["id"])

    with pytest.raises(HTTPException) as ex:
        pps.create_payment_core(FIRM, {
            "client_id": "CLI", "vendor_id": vendor["id"], "payment_date": "2026-04-05",
            "amount_paise": 118000,
            "allocations": [{"purchase_bill_id": bill["id"], "allocated_paise": 118000}],
        }, CALLER, db)
    assert ex.value.status_code == 409
    assert "draft" in ex.value.detail.lower()
    assert db.rows("purchase_payments") == []


# ── services/purchase_payment_service.py: multi-bill FOREIGN path ───────────

def test_create_foreign_payment_core_rejects_draft_bill(monkeypatch):
    ve, pb, pp, db = _setup(monkeypatch)
    import services.purchase_payment_service as pps
    vendor = ve.create_vendor(VendorIn(client_id="CLI", name="US Supplies", state_code="27"), CALLER)["data"]
    bill = _draft_bill(pb, vendor["id"], "BILL-USD-DRAFT-2", currency="USD", exchange_rate="80.0")

    with pytest.raises(HTTPException) as ex:
        pps.create_payment_core(FIRM, {
            "client_id": "CLI", "vendor_id": vendor["id"], "payment_date": "2026-04-05",
            "amount_paise": 100000, "currency": "USD", "exchange_rate": "83.0",
            "allocations": [{"purchase_bill_id": bill["id"], "allocated_paise": 100000}],
        }, CALLER, db)
    assert ex.value.status_code == 409
    assert "draft" in ex.value.detail.lower()
    assert db.rows("purchase_payments") == []


# ── services/purchase_payment_service.py: update_allocations_core (re-allocation) ──

def test_update_allocations_core_rejects_draft_bill(monkeypatch):
    ve, pb, pp, db = _setup(monkeypatch)
    import services.purchase_payment_service as pps
    vendor = ve.create_vendor(VendorIn(client_id="CLI", name="A Supplies", state_code="27"), CALLER)["data"]
    good_bill = _received_bill(pb, vendor["id"], "BILL-GOOD-1")
    draft_bill = _draft_bill(pb, vendor["id"], "BILL-DRAFT-2")

    payment = pps.create_payment_core(FIRM, {
        "client_id": "CLI", "vendor_id": vendor["id"], "payment_date": "2026-04-05",
        "amount_paise": 118000,
        "allocations": [{"purchase_bill_id": good_bill["id"], "allocated_paise": 118000}],
    }, CALLER, db)

    with pytest.raises(HTTPException) as ex:
        pps.update_allocations_core(
            FIRM, payment["id"],
            [{"purchase_bill_id": draft_bill["id"], "allocated_paise": 50000}],
            CALLER, db,
        )
    assert ex.value.status_code == 409
    assert "draft" in ex.value.detail.lower()
    # The payment's original (valid) allocation must survive untouched.
    remaining = [a for a in db.rows("purchase_payment_allocations") if a.get("purchase_payment_id") == payment["id"]]
    assert len(remaining) == 1
    assert remaining[0]["purchase_bill_id"] == good_bill["id"]
