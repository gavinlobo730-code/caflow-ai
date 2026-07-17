"""
Purchase bill audit fixes, driven through the real create/update endpoints
(tests/e2e_harness.py — no mock-mode shortcuts, so these actually exercise
the INSERT payload that hits the database):

  1. service_catalogue_id round-trip bug (found while wiring #58 below): the
     Product/Service link a CA picks on a bill line was accepted by the
     Pydantic model and sent by the frontend picker, but the actual INSERT
     into purchase_bill_lines never included the key — every purchase bill
     ever created silently lost the link, so domain.inventory_service.
     apply_purchase_to_inventory's later SELECT of this column always saw
     NULL and skipped stock-in. Migration 190 also adds the missing `unit`
     column purchase_bill_lines never had at all (unlike
     client_sales_invoice_lines/credit_note_lines/debit_note_lines).
  2. our_reference — existed on the table and was shown in the UI ("Our
     Ref" column) but was never written by create or update.
  3. Post-receipt soft-field edits (mirrors the sales-invoice audit fix):
     our_reference/notes/due_date/line_units stay editable once received;
     everything else (bill_no, bill_date, lines, is_inter_state) is locked.
"""
import pytest
from fastapi import HTTPException

import routers.purchase_bills as pb
from models.invoices import PurchaseBillIn, PurchaseBillLineIn, PurchaseBillUpdateIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z5"})
    db.seed("vendors", {"id": "VEND1", "firm_id": FIRM, "client_id": "CLI", "name": "Supplier Co",
                        "state_code": "27", "gstin": "27BBBBB1111B1Z3",
                        "tds_applicable": False, "tds_section": None, "tds_rate_bps": 0})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "PROD-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Steel Rod", "kind": "good"})
    return db


def test_create_persists_service_catalogue_id_on_the_line(monkeypatch):
    db = _setup(monkeypatch)
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date="2025-06-01", bill_no="B1",
        lines=[PurchaseBillLineIn(
            description="Steel Rod x10", rate_paise=1_000_00, quantity=10,
            gst_rate_percent=18.0, service_catalogue_id="PROD-1",
        )],
    ), CALLER)
    assert res["success"] is True

    lines = db.rows("purchase_bill_lines")
    assert len(lines) == 1
    assert lines[0]["service_catalogue_id"] == "PROD-1", (
        "the Product/Service link must actually be written to the DB row, "
        "not just accepted by the model and silently dropped"
    )


def test_create_persists_unit_defaulting_to_nos(monkeypatch):
    db = _setup(monkeypatch)
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date="2025-06-01", bill_no="B2",
        lines=[
            PurchaseBillLineIn(service_catalogue_id="PROD-1", description="With unit", rate_paise=100_00, quantity=1,
                               gst_rate_percent=18.0, unit="kgs"),
            PurchaseBillLineIn(service_catalogue_id="PROD-1", description="No unit given", rate_paise=100_00, quantity=1,
                               gst_rate_percent=18.0),
        ],
    ), CALLER)
    assert res["success"] is True

    lines = {ln["description"]: ln for ln in db.rows("purchase_bill_lines")}
    assert lines["With unit"]["unit"] == "KGS"
    assert lines["No unit given"]["unit"] == "NOS"


def test_create_persists_our_reference(monkeypatch):
    db = _setup(monkeypatch)
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date="2025-06-01", bill_no="B3",
        our_reference="INTERNAL-REF-42",
        lines=[PurchaseBillLineIn(service_catalogue_id="PROD-1", description="svc", rate_paise=100_00, quantity=1, gst_rate_percent=18.0)],
    ), CALLER)
    assert res["success"] is True
    assert res["data"]["our_reference"] == "INTERNAL-REF-42"
    assert db.rows("purchase_bills")[0]["our_reference"] == "INTERNAL-REF-42"


def _received_bill(db, bill_no="B-RECV"):
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date="2025-06-01", bill_no=bill_no,
        lines=[PurchaseBillLineIn(service_catalogue_id="PROD-1", description="svc", rate_paise=100_00, quantity=1, gst_rate_percent=18.0)],
    ), CALLER)
    assert res["success"] is True
    bill_id = res["data"]["id"]
    line_id = db.rows("purchase_bill_lines")[-1]["id"]
    assert pb.receive_purchase_bill(bill_id, CALLER)["success"] is True
    return bill_id, line_id


def test_update_rejects_locked_field_once_received(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, _ = _received_bill(db)
    with pytest.raises(HTTPException) as exc:
        pb.update_purchase_bill(bill_id, PurchaseBillUpdateIn(bill_no="NEW-NO"), CALLER)
    assert exc.value.status_code == 422


def test_update_allows_our_reference_notes_due_date_once_received(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, _ = _received_bill(db)
    resp = pb.update_purchase_bill(bill_id, PurchaseBillUpdateIn(
        our_reference="POST-RECEIPT-REF", notes="vendor confirmed", due_date="2026-08-01",
    ), CALLER)
    assert resp["success"] is True
    bill = next(b for b in db.rows("purchase_bills") if b["id"] == bill_id)
    assert bill["our_reference"] == "POST-RECEIPT-REF"
    assert bill["notes"] == "vendor confirmed"
    assert bill["due_date"] == "2026-08-01"


def test_update_line_units_once_received(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, line_id = _received_bill(db)
    resp = pb.update_purchase_bill(bill_id, PurchaseBillUpdateIn(line_units={line_id: "kgs"}), CALLER)
    assert resp["success"] is True
    line = next(ln for ln in db.rows("purchase_bill_lines") if ln["id"] == line_id)
    assert line["unit"] == "KGS"


def test_update_rejects_any_edit_once_cancelled(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, _ = _received_bill(db)
    assert pb.cancel_purchase_bill(bill_id, CALLER)["success"] is True
    with pytest.raises(HTTPException) as exc:
        pb.update_purchase_bill(bill_id, PurchaseBillUpdateIn(notes="too late"), CALLER)
    assert exc.value.status_code == 422


def test_update_draft_recomputes_lines_and_replaces_old_ones(monkeypatch):
    """Draft bills accept a full lines replace (Edit Draft flow) — the update
    endpoint previously declared PurchaseBillUpdateIn.lines but never handled
    it at all (would 400: purchase_bills has no `lines` column). Now it must
    recompute GST via the same engine create uses and delete-then-reinsert
    purchase_bill_lines, matching sales_invoices.py's update_invoice."""
    db = _setup(monkeypatch)
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date="2025-06-01", bill_no="B-EDIT",
        lines=[PurchaseBillLineIn(service_catalogue_id="PROD-1", description="Original line", rate_paise=1_000_00, quantity=1, gst_rate_percent=18.0)],
    ), CALLER)
    assert res["success"] is True
    bill_id = res["data"]["id"]
    assert res["data"]["taxable_amount_paise"] == 1_000_00

    resp = pb.update_purchase_bill(bill_id, PurchaseBillUpdateIn(
        lines=[PurchaseBillLineIn(service_catalogue_id="PROD-1", description="Replacement line", rate_paise=2_500_00, quantity=2, gst_rate_percent=18.0)],
    ), CALLER)
    assert resp["success"] is True

    lines = db.rows("purchase_bill_lines")
    assert len(lines) == 1, "the stale line must be deleted, not left alongside the new one"
    assert lines[0]["description"] == "Replacement line"
    assert lines[0]["taxable_amount_paise"] == 5_000_00  # 2 x 2500

    bill = next(b for b in db.rows("purchase_bills") if b["id"] == bill_id)
    assert bill["taxable_amount_paise"] == 5_000_00
    assert bill["cgst_paise"] == 45_000  # 9% of 500000
    assert bill["sgst_paise"] == 45_000
    assert bill["total_paise"] == 5_000_00 + 45_000 + 45_000


def test_update_draft_lines_rejects_empty_list(monkeypatch):
    db = _setup(monkeypatch)
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date="2025-06-01", bill_no="B-EMPTY",
        lines=[PurchaseBillLineIn(service_catalogue_id="PROD-1", description="Only line", rate_paise=100_00, quantity=1, gst_rate_percent=18.0)],
    ), CALLER)
    bill_id = res["data"]["id"]
    with pytest.raises(HTTPException) as exc:
        pb.update_purchase_bill(bill_id, PurchaseBillUpdateIn(lines=[]), CALLER)
    assert exc.value.status_code == 422


def test_update_draft_lines_tds_fy_aggregate_excludes_bills_own_stale_amount(monkeypatch):
    """§194C's ₹1L FY-aggregate threshold (domain/tds/section_rates.py) must be
    checked against OTHER bills only — the bill being edited already exists in
    the DB with its pre-edit taxable_amount_paise, which would otherwise be
    counted as "prior" against itself, double-counting and applying TDS a step
    too early. Numbers are engineered so the two readings disagree: with the
    bill's own stale value wrongly included, the aggregate crosses ₹1L and TDS
    incorrectly applies; correctly excluded, it stays under and TDS does not."""
    db = _setup(monkeypatch)
    db.seed("vendors", {"id": "VEND-TDS", "firm_id": FIRM, "client_id": "CLI", "name": "TDS Contractor",
                        "state_code": "27", "gstin": "27CCCCC2222C1Z1",
                        "tds_applicable": True, "tds_section": "194C", "tds_rate_bps": 200})

    # Other bill contributing ₹78,000 to this vendor's FY-194C aggregate.
    other = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND-TDS", bill_date="2025-06-01", bill_no="B-OTHER",
        lines=[PurchaseBillLineIn(service_catalogue_id="PROD-1", description="Other work", rate_paise=78_000_00, quantity=1, gst_rate_percent=18.0)],
    ), CALLER)
    assert other["success"] is True

    # This bill originally ₹15,000 — well under both the ₹30k single threshold
    # and, combined with the ₹78k above (₹93k total), under the ₹1L aggregate.
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND-TDS", bill_date="2025-06-15", bill_no="B-EDITME",
        lines=[PurchaseBillLineIn(service_catalogue_id="PROD-1", description="Small job", rate_paise=15_000_00, quantity=1, gst_rate_percent=18.0)],
    ), CALLER)
    assert res["success"] is True
    assert res["data"]["tds_paise"] == 0
    bill_id = res["data"]["id"]

    # Edit to ₹19,000 (still under the ₹30k single threshold on its own).
    # Correct: prior = ₹78,000 (other bill only) -> total ₹97,000 <= ₹1L -> no TDS.
    # Buggy (self-counted): prior = ₹78,000 + ₹15,000 (this bill's stale value)
    #   = ₹93,000 -> total ₹112,000 > ₹1L -> TDS would incorrectly apply.
    resp = pb.update_purchase_bill(bill_id, PurchaseBillUpdateIn(
        lines=[PurchaseBillLineIn(service_catalogue_id="PROD-1", description="Small job, revised", rate_paise=19_000_00, quantity=1, gst_rate_percent=18.0)],
    ), CALLER)
    assert resp["success"] is True
    bill = next(b for b in db.rows("purchase_bills") if b["id"] == bill_id)
    assert bill["taxable_amount_paise"] == 19_000_00
    assert bill["tds_paise"] == 0, (
        "TDS FY-aggregate must exclude this bill's own pre-edit amount — "
        "counting it against itself falsely crosses the §194C ₹1L threshold"
    )


def _draft_bill(db, bill_no="B-DRAFT"):
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date="2025-06-01", bill_no=bill_no,
        lines=[PurchaseBillLineIn(service_catalogue_id="PROD-1", description="svc", rate_paise=100_00, quantity=1, gst_rate_percent=18.0)],
    ), CALLER)
    assert res["success"] is True
    return res["data"]["id"]


def test_delete_draft_bill_hard_deletes_and_disappears_from_list(monkeypatch):
    db = _setup(monkeypatch)
    bill_id = _draft_bill(db)
    resp = pb.delete_purchase_bill(bill_id, CALLER)
    assert resp["success"] is True
    # Genuine hard delete — the row is gone, not just deleted_at-stamped.
    assert not any(b["id"] == bill_id for b in db.rows("purchase_bills"))

    listed = pb.list_purchase_bills(client_id="CLI", vendor_id=None, status=None, from_date=None, to_date=None, limit=50, offset=0, current_user=CALLER)
    assert bill_id not in [b["id"] for b in listed["data"]]

    with pytest.raises(HTTPException) as exc:
        pb.get_purchase_bill(bill_id, CALLER)
    assert exc.value.status_code == 404


def test_delete_rejects_once_received(monkeypatch):
    db = _setup(monkeypatch)
    bill_id, _ = _received_bill(db)
    with pytest.raises(HTTPException) as exc:
        pb.delete_purchase_bill(bill_id, CALLER)
    assert exc.value.status_code == 422
    bill = next(b for b in db.rows("purchase_bills") if b["id"] == bill_id)
    assert bill.get("deleted_at") is None


def test_delete_missing_bill_404s(monkeypatch):
    _setup(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        pb.delete_purchase_bill("does-not-exist", CALLER)
    assert exc.value.status_code == 404
