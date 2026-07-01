"""
Beta hardening — Phase B (numbering retry) and Phase D (inactive-master guards).
"""
import pytest
from fastapi import HTTPException

import routers.purchase_bills as pb
import routers.purchase_payments as pp
import services.receipt_service as rsvc
from models.invoices import PurchaseBillIn, PurchaseBillLineIn, PurchasePaymentIn
from services.numbering import insert_with_number
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-BH"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@bh.test", "role": "Partner"}


# ── Phase B: numbering retries past a unique-number collision ──────────────────
def test_numbering_retries_on_collision():
    seqs = iter([1, 2])          # first attempt → 1 (collides), retry → 2
    inserted = []

    class _Q:
        def __init__(self, t): self.t = t; self.payload = None
        def insert(self, p): self.payload = p; return self
        def execute(self):
            if self.payload["invoice_no"] == "SINV-1":
                raise RuntimeError("duplicate key value violates unique constraint ... (23505)")
            inserted.append(self.payload)
            class R: data = [{**self.payload, "id": "x"}]
            return R()

    class _DB:
        def table(self, t): return _Q(t)

    row = insert_with_number(_DB(), "client_sales_invoices", {"firm_id": FIRM}, "invoice_no",
                             lambda s: f"SINV-{s}", lambda: next(seqs))
    assert row["invoice_no"] == "SINV-2"     # transparently retried past the collision
    assert len(inserted) == 1                # exactly one row persisted


def test_numbering_no_collision_uses_first():
    row = insert_with_number(
        type("D", (), {"table": lambda self, t: type("Q", (), {
            "insert": lambda s, p: setattr(s, "p", p) or s,
            "execute": lambda s: type("R", (), {"data": [s.p]})()})()})(),
        "credit_notes", {"firm_id": FIRM}, "credit_note_no",
        lambda s: f"CN-{s}", lambda: 5)
    assert row["credit_note_no"] == "CN-5"


def test_numbering_non_unique_error_propagates():
    class _DB:
        def table(self, t):
            return type("Q", (), {"insert": lambda s, p: s,
                                  "execute": lambda s: (_ for _ in ()).throw(RuntimeError("connection reset"))})()
    with pytest.raises(RuntimeError, match="connection reset"):
        insert_with_number(_DB(), "credit_notes", {}, "credit_note_no", lambda s: f"CN-{s}", lambda: 1)


# ── Phase D: inactive-master guards ───────────────────────────────────────────
def _setup(monkeypatch, *, customer_active=True, vendor_active=True):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb, pp, rsvc])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z5"})
    db.seed("customers", {"id": "CUST1", "firm_id": FIRM, "client_id": "CLI", "name": "C",
                          "is_active": customer_active, "opening_balance_paise": 0})
    db.seed("vendors", {"id": "VEND1", "firm_id": FIRM, "client_id": "CLI", "name": "V",
                        "state_code": "27", "tds_applicable": False, "is_active": vendor_active})
    seed_standard_coa(db, FIRM, "CLI")
    return db


def test_inactive_vendor_bill_rejected(monkeypatch):
    db = _setup(monkeypatch, vendor_active=False)
    with pytest.raises(HTTPException) as ex:
        pb.create_purchase_bill(PurchaseBillIn(
            client_id="CLI", vendor_id="VEND1", bill_date="2025-06-01", bill_no="B1",
            lines=[PurchaseBillLineIn(description="m", rate_paise=1000, quantity=1, gst_rate_percent=18.0)],
        ), CALLER)
    assert ex.value.status_code == 422 and "inactive" in ex.value.detail.lower()


def test_inactive_customer_receipt_rejected(monkeypatch):
    db = _setup(monkeypatch, customer_active=False)
    with pytest.raises(HTTPException) as ex:
        rsvc.create_receipt_core(FIRM, {
            "client_id": "CLI", "customer_id": "CUST1", "receipt_date": "2025-06-10",
            "amount_paise": 5000, "allocations": []}, CALLER, db)
    assert ex.value.status_code == 422 and "inactive" in ex.value.detail.lower()


def test_inactive_vendor_payment_rejected(monkeypatch):
    db = _setup(monkeypatch, vendor_active=False)
    with pytest.raises(HTTPException) as ex:
        pp.create_purchase_payment(PurchasePaymentIn(
            client_id="CLI", vendor_id="VEND1", payment_date="2025-06-10", amount_paise=5000), CALLER)
    assert ex.value.status_code == 422 and "inactive" in ex.value.detail.lower()


def test_active_masters_still_work(monkeypatch):
    db = _setup(monkeypatch)                      # both active
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date="2025-06-01", bill_no="B-OK",
        lines=[PurchaseBillLineIn(description="m", rate_paise=1000, quantity=1, gst_rate_percent=18.0)],
    ), CALLER)
    assert res["success"] is True
