"""
Task #225 — PATCH /purchase-payments/{id}/allocate: resolve a stranded vendor
advance (purchase_payments.unallocated_paise) once a bill is available to
apply it against, without recording a second payment. The AP mirror of
receipts.py's PATCH /{receipt_id}/allocate, which already existed on the AR
side — vendor payments had no equivalent.
"""
import pytest
from fastapi import HTTPException

from models.parties import VendorIn
from models.invoices import PurchaseBillIn, PurchaseBillLineIn
from services import purchase_payment_service as pps
import routers.purchase_bills as pb
import routers.vendors as ve
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb, ve, pps])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Materials", "kind": "good"})
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="Supplier", state_code="27"), CALLER)["data"]
    return db, vend["id"]


def _bill(vend_id, amount_paise, bill_no):
    b = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=vend_id, bill_date="2026-06-01", bill_no=bill_no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="m", rate_paise=amount_paise,
                                  quantity=1, gst_rate_percent=0.0)]), CALLER)["data"]
    pb.receive_purchase_bill(b["id"], CALLER)
    return b


def _bill_row(db, bill_id):
    return next(r for r in db.rows("purchase_bills") if r["id"] == bill_id)


def _payment_row(db, payment_id):
    return next(r for r in db.rows("purchase_payments") if r["id"] == payment_id)


def test_allocate_resolves_stranded_advance(monkeypatch):
    db, vend_id = _setup(monkeypatch)
    bill1 = _bill(vend_id, 50000, "B1")

    # Overpay bill1 by 30000 — a stranded advance (no bill2 exists yet).
    payment = pps.create_payment_core(FIRM, {
        "client_id": "CLI", "vendor_id": vend_id, "payment_date": "2026-06-05",
        "amount_paise": 80000, "allocations": [{"purchase_bill_id": bill1["id"], "allocated_paise": 50000}],
    }, CALLER, db)
    assert payment["unallocated_paise"] == 30000
    assert _bill_row(db, bill1["id"])["paid_paise"] == 50000
    assert _bill_row(db, bill1["id"])["status"] == "paid"

    # Bill2 now arrives — allocate the stranded advance to it.
    bill2 = _bill(vend_id, 30000, "B2")
    result = pps.update_allocations_core(FIRM, payment["id"], [
        {"purchase_bill_id": bill1["id"], "allocated_paise": 50000},
        {"purchase_bill_id": bill2["id"], "allocated_paise": 30000},
    ], CALLER, db)
    assert result["unallocated_paise"] == 0
    assert _bill_row(db, bill2["id"])["paid_paise"] == 30000
    assert _bill_row(db, bill2["id"])["status"] == "paid"
    assert _payment_row(db, payment["id"])["unallocated_paise"] == 0


def test_reallocation_reverses_prior_before_reapplying(monkeypatch):
    db, vend_id = _setup(monkeypatch)
    bill1 = _bill(vend_id, 50000, "B1")
    bill2 = _bill(vend_id, 30000, "B2")

    payment = pps.create_payment_core(FIRM, {
        "client_id": "CLI", "vendor_id": vend_id, "payment_date": "2026-06-05",
        "amount_paise": 80000, "allocations": [{"purchase_bill_id": bill1["id"], "allocated_paise": 50000}],
    }, CALLER, db)

    # Re-allocate away from bill1 entirely, onto bill2 instead.
    pps.update_allocations_core(FIRM, payment["id"], [
        {"purchase_bill_id": bill2["id"], "allocated_paise": 30000},
    ], CALLER, db)
    # bill1 must be fully un-paid again (H3-class fix — no double counting).
    assert _bill_row(db, bill1["id"])["paid_paise"] == 0
    assert _bill_row(db, bill1["id"])["status"] == "received"
    assert _bill_row(db, bill2["id"])["paid_paise"] == 30000

    # Re-allocate back to nothing — the whole payment becomes unallocated again.
    result = pps.update_allocations_core(FIRM, payment["id"], [], CALLER, db)
    assert result["unallocated_paise"] == 80000
    assert _bill_row(db, bill2["id"])["paid_paise"] == 0
    assert _bill_row(db, bill2["id"])["status"] == "received"


def test_allocate_rejects_over_allocation(monkeypatch):
    db, vend_id = _setup(monkeypatch)
    bill1 = _bill(vend_id, 50000, "B1")
    payment = pps.create_payment_core(FIRM, {
        "client_id": "CLI", "vendor_id": vend_id, "payment_date": "2026-06-05",
        "amount_paise": 50000, "allocations": [],
    }, CALLER, db)
    with pytest.raises(HTTPException) as ex:
        pps.update_allocations_core(FIRM, payment["id"], [
            {"purchase_bill_id": bill1["id"], "allocated_paise": 60000},
        ], CALLER, db)
    assert ex.value.status_code == 422
    assert "exceeds payment amount" in ex.value.detail


def test_allocate_rejects_bill_exceeding_outstanding(monkeypatch):
    db, vend_id = _setup(monkeypatch)
    bill1 = _bill(vend_id, 30000, "B1")
    payment = pps.create_payment_core(FIRM, {
        "client_id": "CLI", "vendor_id": vend_id, "payment_date": "2026-06-05",
        "amount_paise": 50000, "allocations": [],
    }, CALLER, db)
    with pytest.raises(HTTPException) as ex:
        pps.update_allocations_core(FIRM, payment["id"], [
            {"purchase_bill_id": bill1["id"], "allocated_paise": 40000},
        ], CALLER, db)
    assert ex.value.status_code == 422
    assert "outstanding" in ex.value.detail


def test_allocate_rejects_cancelled_bill(monkeypatch):
    db, vend_id = _setup(monkeypatch)
    bill1 = _bill(vend_id, 50000, "B1")
    _bill_row(db, bill1["id"])["status"] = "cancelled"
    payment = pps.create_payment_core(FIRM, {
        "client_id": "CLI", "vendor_id": vend_id, "payment_date": "2026-06-05",
        "amount_paise": 50000, "allocations": [],
    }, CALLER, db)
    with pytest.raises(HTTPException) as ex:
        pps.update_allocations_core(FIRM, payment["id"], [
            {"purchase_bill_id": bill1["id"], "allocated_paise": 50000},
        ], CALLER, db)
    assert ex.value.status_code == 409


def test_allocate_rejects_bill_from_another_client(monkeypatch):
    db, vend_id = _setup(monkeypatch)
    db.seed("clients", {"id": "CLI2", "firm_id": FIRM, "gstin": "27ABCDE9999F1Z5"})
    seed_standard_coa(db, FIRM, "CLI2")
    other_vend = ve.create_vendor(VendorIn(client_id="CLI2", name="Other Vendor", state_code="27"), CALLER)["data"]
    other_bill = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI2", vendor_id=other_vend["id"], bill_date="2026-06-01", bill_no="OTHER-1",
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="m", rate_paise=50000,
                                  quantity=1, gst_rate_percent=0.0)]), CALLER)["data"]

    payment = pps.create_payment_core(FIRM, {
        "client_id": "CLI", "vendor_id": vend_id, "payment_date": "2026-06-05",
        "amount_paise": 50000, "allocations": [],
    }, CALLER, db)
    with pytest.raises(HTTPException) as ex:
        pps.update_allocations_core(FIRM, payment["id"], [
            {"purchase_bill_id": other_bill["id"], "allocated_paise": 50000},
        ], CALLER, db)
    assert ex.value.status_code == 422
    assert "not part of this client's books" in ex.value.detail


def test_allocate_payment_not_found(monkeypatch):
    db, vend_id = _setup(monkeypatch)
    with pytest.raises(HTTPException) as ex:
        pps.update_allocations_core(FIRM, "nonexistent-payment", [], CALLER, db)
    assert ex.value.status_code == 404
