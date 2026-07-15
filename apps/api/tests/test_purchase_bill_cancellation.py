"""
Production Readiness Phase 1 — C3: purchase-bill cancellation.

Mirror of the sales-invoice cancellation, on the AP side. Cancelling a RECEIVED
bill must not mutate or delete the original posted journal; it posts an
equal-and-opposite REVERSAL through the single kernel, so:
  * GL Trade Payables control nets back to 0
  * the trial balance stays balanced
  * the reversal entry carries reversal_of → the original receive journal

Cancellation is BLOCKED where a vendor payment already references the bill
(reversing the bill would strand the payment journal). Drafts are deleted, not
cancelled. Integer paise throughout.
"""
import pytest
from fastapi import HTTPException

import routers.purchase_bills as pb
from models.invoices import PurchaseBillIn, PurchaseBillLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, coa_id, account_balance, trial_balance

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u-int", "auth_user_id": "auth", "email": "ca@firma.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    # Client + vendor share state 27 → intra-state bill (CGST + SGST, no TDS).
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z5",
                        "financial_year_start": "2025-04-01"})
    db.seed("vendors", {"id": "VEND1", "firm_id": FIRM, "client_id": "CLI", "name": "Supplier Co",
                        "state_code": "27", "gstin": "27BBBBB1111B1Z3",
                        "tds_applicable": False, "tds_section": None, "tds_rate_bps": 0})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Raw Material", "kind": "good"})
    return db


def _received_bill(db, bill_no="BILL-1", rate=100000):
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date="2025-06-01", bill_no=bill_no,
        lines=[PurchaseBillLineIn(description="raw material", rate_paise=rate,
                                  quantity=1, gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert res["success"] is True
    bill_id = res["data"]["id"]
    assert pb.receive_purchase_bill(bill_id, CALLER)["success"] is True
    total = res["data"]["total_paise"]                       # 118000 (100000 + 9000 + 9000)
    return bill_id, total


def _ap(db):
    return account_balance(db, coa_id(db, FIRM, "ap"))


def _bill(db, bill_id):
    return next(b for b in db.rows("purchase_bills") if b["id"] == bill_id)


def test_cancel_received_bill_posts_reversal_and_nets_gl_to_zero(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, total = _received_bill(db)
    assert _ap(db) == -total                                  # AP credited by the receive journal
    recv_jrnl = _bill(db, bill_id)["journal_entry_id"]
    assert recv_jrnl

    res = pb.cancel_purchase_bill(bill_id, CALLER)
    assert res["success"] is True

    bill = _bill(db, bill_id)
    assert bill["status"] == "cancelled"
    # Original receive journal untouched (immutable); exactly one reversal, linked back.
    orig = next(e for e in db.rows("journal_entries") if e["id"] == recv_jrnl)
    assert orig.get("is_posted", True) is True and not orig.get("reversal_of")
    reversals = [e for e in db.rows("journal_entries") if e.get("reversal_of") == recv_jrnl]
    assert len(reversals) == 1 and reversals[0].get("is_posted", True) is True

    assert _ap(db) == 0                                       # GL AP control nets to zero
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]  # ledger still balanced


def test_cancel_is_not_duplicated_on_retry(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, total = _received_bill(db)
    recv_jrnl = _bill(db, bill_id)["journal_entry_id"]
    assert pb.cancel_purchase_bill(bill_id, CALLER)["success"] is True
    _bill(db, bill_id)["status"] = "received"                 # pretend the flip was lost
    assert pb.cancel_purchase_bill(bill_id, CALLER)["success"] is True
    reversals = [e for e in db.rows("journal_entries") if e.get("reversal_of") == recv_jrnl]
    assert len(reversals) == 1                                # still exactly one
    assert _ap(db) == 0


def test_cannot_cancel_bill_with_payment(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, total = _received_bill(db)
    # A vendor payment references this bill (its own Dr AP / Cr Bank journal is posted).
    # Cancelling the bill would strand that payment journal, so it must be blocked;
    # the guard scans purchase_payments for a row pointing at the bill.
    db.seed("purchase_payments", {
        "firm_id": FIRM, "client_id": "CLI", "vendor_id": "VEND1",
        "purchase_bill_id": bill_id, "payment_no": "VPMT-1", "payment_date": "2025-06-10",
        "amount_paise": total,
    })
    with pytest.raises(HTTPException) as ex:
        pb.cancel_purchase_bill(bill_id, CALLER)
    assert ex.value.status_code == 409
    assert _bill(db, bill_id)["status"] != "cancelled"
    # No reversal was posted.
    assert not [e for e in db.rows("journal_entries") if e.get("reversal_of")]


def test_cannot_cancel_draft_bill(monkeypatch):
    db = _setup(monkeypatch)
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date="2025-06-01", bill_no="BILL-DRAFT",
        lines=[PurchaseBillLineIn(description="x", rate_paise=100000, quantity=1, gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    bill_id = res["data"]["id"]                               # still draft — not received
    with pytest.raises(HTTPException) as ex:
        pb.cancel_purchase_bill(bill_id, CALLER)
    assert ex.value.status_code == 422


def test_cannot_cancel_already_cancelled_bill(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, _ = _received_bill(db)
    assert pb.cancel_purchase_bill(bill_id, CALLER)["success"] is True
    with pytest.raises(HTTPException) as ex:
        pb.cancel_purchase_bill(bill_id, CALLER)
    assert ex.value.status_code == 422
