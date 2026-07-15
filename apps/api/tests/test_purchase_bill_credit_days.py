"""
Vendor Credit Days = a per-bill DEFAULT, snapshotted onto the purchase bill.
Ports the identical Customer/Sales-Invoice behaviour (test_invoice_credit_days.py)
to Vendors/Purchase Bills via the shared services/credit_terms.py resolver.

Verifies:
  * vendor.credit_days populates a new bill's due_date by default
  * an explicit credit_days or due_date on the request overrides it
  * the resolved terms (due_date + credit_days) are STORED on the bill
  * changing the vendor's Credit Days later does NOT touch existing bills
  * a due_date-only edit on a received bill resyncs credit_days
All dates are plain calendar arithmetic; all money is integer paise elsewhere.
"""
import pytest
from fastapi import HTTPException

import routers.purchase_bills as pb
from services.credit_terms import resolve_credit_terms, apply_credit_days_due_date, apply_due_date_credit_days
from models.invoices import PurchaseBillIn, PurchaseBillLineIn, PurchaseBillUpdateIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}


def _setup(monkeypatch, credit_days=15):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("vendors", {"id": "VEND", "firm_id": FIRM, "client_id": "CLI",
                        "name": "Supplier Co", "state_code": "27", "gstin": "27PQRST9012K1Z8",
                        "pan": "PQRST9012K", "is_active": True, "tds_applicable": False,
                        "credit_days": credit_days})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Consulting", "kind": "service"})
    return db


def _bill(**over):
    kw = dict(client_id="CLI", vendor_id="VEND", bill_date="2026-04-10", bill_no="CD-001",
              lines=[PurchaseBillLineIn(description="X", hsn_sac="9982", quantity=1,
                                        rate_paise=1_000_000, gst_rate_percent=18.0,
                                        service_catalogue_id="SVC-1")])
    kw.update(over)
    return PurchaseBillIn(**kw)


# ── pure resolver (shared module — already covered by its own dedicated unit
# tests in test_credit_terms.py; these just confirm purchase_bills.py imports
# and calls the same functions the sales-invoice side does) ─────────────────

def test_resolve_uses_vendor_default():
    assert resolve_credit_terms("2026-04-10", None, None, 15) == ("2026-04-25", 15)


def test_apply_recompute_on_edit():
    d = {"credit_days": 20}
    apply_credit_days_due_date(d, "2026-04-10")
    assert d["due_date"] == "2026-04-30"


# ── create flow (real DB path via FakeDB) ────────────────────────────────────

def test_new_bill_defaults_due_date_from_vendor(monkeypatch):
    _setup(monkeypatch, credit_days=15)
    bill = pb.create_purchase_bill(_bill(), CALLER)["data"]
    assert bill["credit_days"] == 15
    assert bill["due_date"] == "2026-04-25"   # bill_date + 15


def test_new_bill_credit_days_override(monkeypatch):
    _setup(monkeypatch, credit_days=15)
    bill = pb.create_purchase_bill(_bill(credit_days=45), CALLER)["data"]
    assert bill["credit_days"] == 45
    assert bill["due_date"] == "2026-05-25"   # bill_date + 45


def test_new_bill_explicit_due_date_override(monkeypatch):
    _setup(monkeypatch, credit_days=15)
    bill = pb.create_purchase_bill(_bill(due_date="2026-06-01"), CALLER)["data"]
    assert bill["due_date"] == "2026-06-01"
    assert bill["credit_days"] == 52   # Apr 10 -> Jun 01


def test_new_bill_falls_back_to_30_when_vendor_has_no_credit_days(monkeypatch):
    db = _setup(monkeypatch, credit_days=15)
    for v in db.rows("vendors"):
        v["credit_days"] = None
    bill = pb.create_purchase_bill(_bill(), CALLER)["data"]
    assert bill["credit_days"] == 30
    assert bill["due_date"] == "2026-05-10"


def test_existing_bill_unaffected_by_vendor_credit_days_change(monkeypatch):
    db = _setup(monkeypatch, credit_days=15)
    first = pb.create_purchase_bill(_bill(), CALLER)["data"]
    assert first["due_date"] == "2026-04-25" and first["credit_days"] == 15

    # CA later raises the vendor's Credit Days to 60.
    for v in db.rows("vendors"):
        if v["id"] == "VEND":
            v["credit_days"] = 60

    # The already-saved bill keeps its snapshot — no rewrite.
    stored = next(r for r in db.rows("purchase_bills") if r["id"] == first["id"])
    assert stored["due_date"] == "2026-04-25"
    assert stored["credit_days"] == 15

    # A NEW bill picks up the new default (Apr 10 + 60 = Jun 9).
    second = pb.create_purchase_bill(_bill(bill_no="CD-002"), CALLER)["data"]
    assert second["credit_days"] == 60
    assert second["due_date"] == "2026-06-09"


# ── post-receipt edit: due_date changes directly must resync credit_days ────
# our_reference/notes/due_date/credit_days stay editable post-receipt
# (_SOFT_BILL_UPDATE_FIELDS); bill_no/bill_date/lines do not.

def test_edit_due_date_on_received_bill_resyncs_credit_days(monkeypatch):
    db = _setup(monkeypatch, credit_days=15)
    bill = pb.create_purchase_bill(_bill(), CALLER)["data"]
    assert bill["due_date"] == "2026-04-25" and bill["credit_days"] == 15

    for row in db.rows("purchase_bills"):
        if row["id"] == bill["id"]:
            row["status"] = "received"

    resp = pb.update_purchase_bill(bill["id"], PurchaseBillUpdateIn(due_date="2026-06-01"), CALLER)
    assert resp["success"] is True, resp

    stored = next(r for r in db.rows("purchase_bills") if r["id"] == bill["id"])
    assert stored["due_date"] == "2026-06-01"
    assert stored["credit_days"] == 52  # Apr 10 -> Jun 01


def test_edit_credit_days_on_received_bill_resyncs_due_date(monkeypatch):
    db = _setup(monkeypatch, credit_days=15)
    bill = pb.create_purchase_bill(_bill(), CALLER)["data"]

    for row in db.rows("purchase_bills"):
        if row["id"] == bill["id"]:
            row["status"] = "received"

    resp = pb.update_purchase_bill(bill["id"], PurchaseBillUpdateIn(credit_days=60), CALLER)
    assert resp["success"] is True, resp

    stored = next(r for r in db.rows("purchase_bills") if r["id"] == bill["id"])
    assert stored["credit_days"] == 60
    assert stored["due_date"] == "2026-06-09"  # Apr 10 -> +60


def test_bill_no_locked_post_receipt_still_rejected(monkeypatch):
    db = _setup(monkeypatch, credit_days=15)
    bill = pb.create_purchase_bill(_bill(), CALLER)["data"]

    for row in db.rows("purchase_bills"):
        if row["id"] == bill["id"]:
            row["status"] = "received"

    with pytest.raises(HTTPException) as ei:
        pb.update_purchase_bill(bill["id"], PurchaseBillUpdateIn(bill_no="NEW-NO"), CALLER)
    assert "bill_no" in str(ei.value.detail)
