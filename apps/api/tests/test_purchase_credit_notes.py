"""
Purchase credit notes — the §34(3) increase-side mirror of (purchase) debit notes
(a vendor undercharged us on an already-received bill; we now owe them more).

A purchase credit note increases the linked bill's payable in the AP SUB-LEDGER
(credit_note_paise + purchase_credit_note_allocations) and posts a kernel journal
(Dr Purchases / Dr GST Input / Cr Trade Payables), so the sub-ledger, the GL AP
control and the vendor statement reconcile:
  bill net outstanding = (net_payable_paise + credit_note_paise) - paid_paise - debited_paise.

Also covers the direct interaction with the existing (reduction-side) debit note:
issuing a debit note against a bill that already carries a purchase credit note
must use the EFFECTIVE payable (net_payable + credit_note_paise), not the stale
original net_payable, as its ceiling — the exact ripple fix applied to
routers/debit_notes.py alongside this feature.
"""
import pytest
from fastapi import HTTPException

import routers.purchase_bills as pb
import routers.debit_notes as dn
import routers.purchase_credit_notes as pcn
import routers.vendors as ve
import routers.purchase_payments as pp
from models.invoices import PurchaseBillIn, PurchaseBillLineIn, InvoiceLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, coa_id, account_balance, trial_balance

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb, dn, pcn, ve, pp])
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


def _create_pcn(db, bill_id, rate, no="PCN-1"):
    res = pcn.create_purchase_credit_note(pcn.PurchaseCreditNoteIn(
        client_id="CLI", vendor_id="VEND1", credit_note_date="2025-06-05",
        purchase_bill_id=bill_id, reason="Vendor undercharged — rate correction",
        lines=[InvoiceLineIn(description="additional charge", quantity=1, rate_paise=rate, gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert res["success"] is True
    return res["data"]["id"], res["data"]["total_paise"]


def _bill(db, bill_id):
    return next(b for b in db.rows("purchase_bills") if b["id"] == bill_id)


def _ap(db):
    return account_balance(db, coa_id(db, FIRM, "ap"))


def test_purchase_credit_note_increases_payable_and_reconciles(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, net_payable = _received_bill(db, rate=1_00000)      # net_payable 118000
    assert _ap(db) == -net_payable                               # AP credited by the bill
    pcn_id, pcn_total = _create_pcn(db, bill_id, rate=20000)      # 20000 @18% = 23600
    assert pcn.issue_purchase_credit_note(pcn_id, CALLER)["success"] is True

    bill = _bill(db, bill_id)
    assert bill["credit_note_paise"] == pcn_total                 # sub-ledger
    net_out = bill["net_payable_paise"] + bill["credit_note_paise"] - bill.get("paid_paise", 0) - bill.get("debited_paise", 0)
    assert net_out == net_payable + pcn_total                     # 141600
    assert _ap(db) == -(net_payable + pcn_total)                  # GL AP control moved UP, not down
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]
    assert any(a["credit_note_id"] == pcn_id and a["allocated_paise"] == pcn_total
               for a in db.rows("purchase_credit_note_allocations"))
    assert ve.get_vendor_outstanding("VEND1", CALLER)["data"]["outstanding_paise"] == net_payable + pcn_total


def test_purchase_credit_note_has_no_ceiling(monkeypatch):
    """Unlike a debit note, a purchase credit note may exceed the bill's original
    net payable — there is nothing to exceed when you're increasing what's owed."""
    db = _setup(monkeypatch)
    bill_id, net_payable = _received_bill(db, rate=10000)         # net_payable 11800
    pcn_id, pcn_total = _create_pcn(db, bill_id, rate=1_000000)   # far larger than the original bill
    assert pcn_total > net_payable
    res = pcn.issue_purchase_credit_note(pcn_id, CALLER)
    assert res["success"] is True
    assert _bill(db, bill_id)["credit_note_paise"] == pcn_total


def test_cannot_credit_note_a_draft_bill(monkeypatch):
    db = _setup(monkeypatch)
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date="2025-06-01", bill_no="BILL-DRAFT",
        lines=[PurchaseBillLineIn(description="mat", rate_paise=10000, quantity=1, gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    bill_id = res["data"]["id"]                                   # never received — stays draft
    pcn_id, _ = _create_pcn(db, bill_id, rate=1000)
    with pytest.raises(HTTPException) as ex:
        pcn.issue_purchase_credit_note(pcn_id, CALLER)
    assert ex.value.status_code == 422


def test_create_purchase_credit_note_computes_gst_from_percent(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, _ = _received_bill(db)
    res = pcn.create_purchase_credit_note(pcn.PurchaseCreditNoteIn(
        client_id="CLI", vendor_id="VEND1", credit_note_date="2025-06-05",
        purchase_bill_id=bill_id, reason="undercharged",
        lines=[InvoiceLineIn(description="extra", quantity=1, rate_paise=100000, gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert res["success"] is True
    data = res["data"]
    assert data["taxable_amount_paise"] == 100000
    assert (data["cgst_paise"] + data["sgst_paise"] + data["igst_paise"]) == 18000
    assert data["total_paise"] == 118000


def test_draft_purchase_credit_note_can_be_deleted(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, _ = _received_bill(db)
    pcn_id, _ = _create_pcn(db, bill_id, rate=1000)
    res = pcn.delete_purchase_credit_note(pcn_id, CALLER)
    assert res["success"] is True
    with pytest.raises(HTTPException) as ex:
        pcn.get_purchase_credit_note(pcn_id, CALLER)
    assert ex.value.status_code == 404


def test_issued_purchase_credit_note_cannot_be_deleted(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, _ = _received_bill(db)
    pcn_id, _ = _create_pcn(db, bill_id, rate=1000)
    assert pcn.issue_purchase_credit_note(pcn_id, CALLER)["success"] is True
    with pytest.raises(HTTPException) as ex:
        pcn.delete_purchase_credit_note(pcn_id, CALLER)
    assert ex.value.status_code == 422


# ── Interaction with the existing (reduction-side) debit note ───────────────

def test_debit_note_after_credit_note_uses_effective_payable(monkeypatch):
    """A purchase credit note raises what the bill can still absorb — a debit
    note issued afterwards must be checked against (net_payable +
    credit_note_paise), not the stale original net_payable, or a legitimate
    correction gets rejected."""
    db = _setup(monkeypatch)
    bill_id, net_payable = _received_bill(db, rate=1_00000)       # 118000
    pcn_id, pcn_total = _create_pcn(db, bill_id, rate=20000)       # 23600
    assert pcn.issue_purchase_credit_note(pcn_id, CALLER)["success"] is True
    assert _bill(db, bill_id)["credit_note_paise"] == pcn_total

    # A debit note for MORE than the original net_payable (118000) but within
    # the new effective payable (141600) must be accepted, not rejected as
    # "exceeds outstanding" against the stale pre-credit-note net_payable.
    dn_res = dn.create_debit_note(dn.DebitNoteIn(
        client_id="CLI", vendor_id="VEND1", debit_note_date="2025-06-06",
        purchase_bill_id=bill_id, reason="Partial return",
        lines=[InvoiceLineIn(description="return", quantity=1, rate_paise=130000,
                              gst_rate_percent=0.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert dn_res["success"] is True
    dn_id, dn_total = dn_res["data"]["id"], dn_res["data"]["total_paise"]
    assert net_payable < dn_total < net_payable + pcn_total       # exceeds ORIGINAL net_payable, not effective

    issue_res = dn.issue_debit_note(dn_id, CALLER)
    assert issue_res["success"] is True

    bill = _bill(db, bill_id)
    net_out = bill["net_payable_paise"] + bill["credit_note_paise"] - bill.get("paid_paise", 0) - bill["debited_paise"]
    assert net_out == (net_payable + pcn_total) - dn_total
    assert _ap(db) == -((net_payable + pcn_total) - dn_total)
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


def test_vendor_payment_can_settle_the_credit_noted_amount(monkeypatch):
    """The Record Payment flow (routers.purchase_payments) must accept a
    payment for the bill's TRUE outstanding, including a purchase credit
    note's addition — not just the original net_payable."""
    db = _setup(monkeypatch)
    bill_id, net_payable = _received_bill(db, rate=1_00000)        # 118000
    pcn_id, pcn_total = _create_pcn(db, bill_id, rate=20000)        # 23600
    assert pcn.issue_purchase_credit_note(pcn_id, CALLER)["success"] is True
    effective_payable = net_payable + pcn_total                     # 141600

    res = pp.create_purchase_payment(pp.PurchasePaymentIn(
        client_id="CLI", vendor_id="VEND1", payment_date="2025-06-10",
        amount_paise=effective_payable, payment_mode="bank",
        purchase_bill_id=bill_id,
    ), CALLER)
    assert res["success"] is True

    bill = _bill(db, bill_id)
    assert bill["paid_paise"] == effective_payable
    assert bill["status"] == "paid"
    assert _ap(db) == 0


# ── GET single / PATCH (feature-parity build: dedicated edit page + drawer) ──

def test_get_single_purchase_credit_note_returns_lines(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, _ = _received_bill(db)
    pcn_id, total = _create_pcn(db, bill_id, rate=20000)
    res = pcn.get_purchase_credit_note(pcn_id, CALLER)
    assert res["success"] is True
    assert res["data"]["id"] == pcn_id
    assert res["data"]["total_paise"] == total
    assert len(res["data"]["lines"]) == 1
    assert res["data"]["lines"][0]["description"] == "additional charge"


def test_patch_draft_purchase_credit_note_recomputes_totals_from_new_lines(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, _ = _received_bill(db)
    pcn_id, _ = _create_pcn(db, bill_id, rate=20000)               # 23600
    res = pcn.update_purchase_credit_note(pcn_id, pcn.PurchaseCreditNoteUpdateIn(
        lines=[InvoiceLineIn(description="corrected charge", quantity=1, rate_paise=50000,
                              gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert res["success"] is True
    assert res["data"]["total_paise"] == 59000                     # 50000 + 18%
    assert len(res["data"]["lines"]) == 1
    assert res["data"]["lines"][0]["description"] == "corrected charge"
    assert pcn.get_purchase_credit_note(pcn_id, CALLER)["data"]["total_paise"] == 59000


def test_patch_notes_and_document_url_allowed_on_issued_purchase_credit_note(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, _ = _received_bill(db)
    pcn_id, _ = _create_pcn(db, bill_id, rate=20000)
    assert pcn.issue_purchase_credit_note(pcn_id, CALLER)["success"] is True
    res = pcn.update_purchase_credit_note(pcn_id, pcn.PurchaseCreditNoteUpdateIn(
        notes="internal note", document_url="FIRM-A/CLI/purchase_credit_note/x.pdf",
    ), CALLER)
    assert res["success"] is True
    assert res["data"]["notes"] == "internal note"
    assert res["data"]["document_url"] == "FIRM-A/CLI/purchase_credit_note/x.pdf"


def test_patch_lines_rejected_on_issued_purchase_credit_note(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, _ = _received_bill(db)
    pcn_id, _ = _create_pcn(db, bill_id, rate=20000)
    assert pcn.issue_purchase_credit_note(pcn_id, CALLER)["success"] is True
    with pytest.raises(HTTPException) as ex:
        pcn.update_purchase_credit_note(pcn_id, pcn.PurchaseCreditNoteUpdateIn(
            lines=[InvoiceLineIn(description="x", quantity=1, rate_paise=1000,
                                  gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
        ), CALLER)
    assert ex.value.status_code == 422


def test_line_unit_persists_on_create_and_edit(monkeypatch):
    # _compute_lines previously never read ln.get("unit") at all, so every
    # line's unit silently landed NULL regardless of what the editor sent —
    # unlike sales_invoices.py/purchase_bills.py, which always did.
    db = _setup(monkeypatch)
    bill_id, _ = _received_bill(db)
    res = pcn.create_purchase_credit_note(pcn.PurchaseCreditNoteIn(
        client_id="CLI", vendor_id="VEND1", credit_note_date="2025-06-05",
        purchase_bill_id=bill_id, reason="Vendor undercharged — rate correction",
        lines=[InvoiceLineIn(description="additional charge", quantity=2, unit="KGS", rate_paise=20000,
                              gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert res["success"] is True
    pcn_id = res["data"]["id"]
    assert res["data"]["lines"][0]["unit"] == "KGS"
    assert pcn.get_purchase_credit_note(pcn_id, CALLER)["data"]["lines"][0]["unit"] == "KGS"

    upd = pcn.update_purchase_credit_note(pcn_id, pcn.PurchaseCreditNoteUpdateIn(
        lines=[InvoiceLineIn(description="additional charge", quantity=2, unit="BOX", rate_paise=20000,
                              gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert upd["success"] is True
    assert upd["data"]["lines"][0]["unit"] == "BOX"
    assert pcn.get_purchase_credit_note(pcn_id, CALLER)["data"]["lines"][0]["unit"] == "BOX"
