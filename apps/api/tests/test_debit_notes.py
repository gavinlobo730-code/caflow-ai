"""
Production Readiness Phase 5 — debit notes (vendor purchase returns; audit H23).

A debit note relieves the linked bill's payable in the AP SUB-LEDGER (debited_paise
+ debit_note_allocations) and posts a kernel journal (Dr AP / Cr Purchases / Cr GST
Input), so the sub-ledger, the GL AP control and the vendor statement reconcile:
  bill net outstanding = net_payable − paid − debited.
"""
import pytest
from fastapi import HTTPException

import routers.purchase_bills as pb
import routers.debit_notes as dn
import routers.vendors as ve
from models.invoices import PurchaseBillIn, PurchaseBillLineIn
from models.invoices import InvoiceLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, coa_id, account_balance, trial_balance

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb, dn, ve])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z5", "financial_year_start": "2025-04-01"})
    db.seed("vendors", {"id": "VEND1", "firm_id": FIRM, "client_id": "CLI", "name": "Supplier",
                        "state_code": "27", "gstin": "27CCCCC2222C1Z5", "tds_applicable": False,
                        "opening_balance_paise": 0})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Materials", "kind": "good"})
    return db


def _received_bill(db, no="BILL-1", rate=1_00000):
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date="2025-06-01", bill_no=no,
        lines=[PurchaseBillLineIn(description="mat", rate_paise=rate, quantity=1, gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert res["success"] is True
    bill_id = res["data"]["id"]
    assert pb.receive_purchase_bill(bill_id, CALLER)["success"] is True
    return bill_id, res["data"]["net_payable_paise"]


def _create_dn(db, bill_id, rate, no="DN-1"):
    res = dn.create_debit_note(dn.DebitNoteIn(
        client_id="CLI", vendor_id="VEND1", debit_note_date="2025-06-05",
        purchase_bill_id=bill_id,
        lines=[InvoiceLineIn(description="return", quantity=1, rate_paise=rate, gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert res["success"] is True
    return res["data"]["id"], res["data"]["total_paise"]


def _bill(db, bill_id):
    return next(b for b in db.rows("purchase_bills") if b["id"] == bill_id)


def _ap(db):
    return account_balance(db, coa_id(db, FIRM, "ap"))


def test_debit_note_relieves_payable_and_reconciles(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, net_payable = _received_bill(db, rate=1_00000)      # net_payable 118000
    assert _ap(db) == -net_payable                              # AP credited by the bill
    dn_id, dn_total = _create_dn(db, bill_id, rate=20000)        # 20000 @18% = 23600
    assert dn.issue_debit_note(dn_id, CALLER)["success"] is True

    bill = _bill(db, bill_id)
    assert bill["debited_paise"] == dn_total                     # sub-ledger
    net_out = net_payable - int(bill.get("paid_paise") or 0) - bill["debited_paise"]
    assert net_out == net_payable - dn_total                     # 94400
    assert _ap(db) == -(net_payable - dn_total)                  # GL AP control moved
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]
    assert any(a["debit_note_id"] == dn_id and a["allocated_paise"] == dn_total
               for a in db.rows("debit_note_allocations"))
    # Vendor outstanding reflects the relief.
    assert ve.get_vendor_outstanding("VEND1", CALLER)["data"]["outstanding_paise"] == net_payable - dn_total


def test_full_debit_note_marks_bill_paid(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, net_payable = _received_bill(db, rate=1_00000)
    # Debit note for the full net payable (taxable chosen so total == net_payable).
    dn_id, dn_total = _create_dn(db, bill_id, rate=1_00000)      # 118000 == net_payable
    assert dn_total == net_payable
    assert dn.issue_debit_note(dn_id, CALLER)["success"] is True
    assert _bill(db, bill_id)["status"] == "paid"
    assert _ap(db) == 0
    assert ve.get_vendor_outstanding("VEND1", CALLER)["data"]["outstanding_paise"] == 0


def test_debit_note_exceeding_outstanding_rejected(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, net_payable = _received_bill(db, rate=1_00000)      # outstanding 118000
    dn_id, _ = _create_dn(db, bill_id, rate=2_00000)             # 236000 > 118000
    with pytest.raises(HTTPException) as ex:
        dn.issue_debit_note(dn_id, CALLER)
    assert ex.value.status_code == 422
    assert _bill(db, bill_id).get("debited_paise", 0) == 0      # nothing applied
    assert not db.rows("debit_note_allocations")


def test_create_debit_note_computes_gst_from_percent(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, _ = _received_bill(db)
    _dn_id, total = _create_dn(db, bill_id, rate=1_00000)
    assert total == 1_18000                                     # 100000 + 18% GST
