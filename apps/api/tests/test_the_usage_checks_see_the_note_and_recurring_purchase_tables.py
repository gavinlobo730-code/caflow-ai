"""The "is this code / service still used?" checks read the sales debit note, purchase credit note and recurring purchase bill
template lines (ledger POST-A-312).

THE DEFECT
    `firm_hsn_library._USAGE_CHECKS` and `service_catalogue._SERVICE_USAGE_CHECKS` (and their mock twins) listed the invoice,
    credit-note, debit-note, purchase-bill and recurring-invoice-template lines, but not the three line tables migrations 210 and
    379 added, which carry the same two columns (`hsn_sac`, `service_catalogue_id`). A code or a service used only on a sales
    debit note, a purchase credit note or a recurring purchase bill template was reported unused and could be purged or
    deleted. Nothing was orphaned (the line stores the code as text, and the service link is ON DELETE SET NULL on the template lines and a bare column on the note lines), which is why it
    was filed low; the guard exists to keep a used code visible for the audit trail and to stop a delete quietly cutting the link
    from a template that is still billing.

WHAT IS HELD (no database; the real-Postgres half is `test_the_usage_checks_read_the_note_and_recurring_purchase_tables_pg.py`)
    * a code used on one of the three tables blocks the purge, named by its own label, and a different code does not;
    * a service used on an ISSUED sales debit note or purchase credit note is reported, on a DRAFT one it is not (the two tables
      allow only draft and issued, migration 210), through the real path (a double that answers eq / in_) and the mock twin;
    * a service on a recurring purchase bill template is reported unless the template is archived (active and paused both
      still bill or may again), the sales-side rule;
    * a service on one table is not reported as another.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.service_catalogue as service_catalogue
from core.auth import get_current_user
from routers.credit_notes import MOCK_CREDIT_NOTE_LINES, MOCK_CREDIT_NOTES
from routers.debit_notes import MOCK_DEBIT_NOTE_LINES, MOCK_DEBIT_NOTES
from routers.firm_hsn_library import MOCK_LIBRARY, router as lib_router
from routers.purchase_bills import MOCK_PURCHASE_BILL_LINES, MOCK_PURCHASE_BILLS
from routers.purchase_credit_notes import MOCK_PURCHASE_CREDIT_NOTE_LINES, MOCK_PURCHASE_CREDIT_NOTES
from routers.sales_debit_notes import MOCK_SALES_DEBIT_NOTE_LINES, MOCK_SALES_DEBIT_NOTES
from routers.sales_invoices import MOCK_SALES_INVOICE_LINES, MOCK_SALES_INVOICES
from routers.service_catalogue import MOCK_SERVICES
from tests.e2e_harness import FakeDB

FIRM = "firm-312"
SERVICE = "11111111-0000-0000-0000-000000000312"
OTHER_SERVICE = "11111111-0000-0000-0000-000000000313"
USER = {"id": "u-312", "firm_id": FIRM, "role": "Partner"}

_STORES = (MOCK_LIBRARY, MOCK_SERVICES, MOCK_SALES_INVOICE_LINES, MOCK_SALES_INVOICES, MOCK_CREDIT_NOTE_LINES, MOCK_CREDIT_NOTES,
           MOCK_DEBIT_NOTE_LINES, MOCK_DEBIT_NOTES, MOCK_PURCHASE_BILL_LINES, MOCK_PURCHASE_BILLS, MOCK_SALES_DEBIT_NOTE_LINES,
           MOCK_SALES_DEBIT_NOTES, MOCK_PURCHASE_CREDIT_NOTE_LINES, MOCK_PURCHASE_CREDIT_NOTES)


@pytest.fixture(autouse=True)
def clear_stores():
    for store in _STORES:
        store.clear()
    yield
    for store in _STORES:
        store.clear()


@pytest.fixture()
def http():
    app = FastAPI()
    app.include_router(lib_router)
    app.dependency_overrides[get_current_user] = lambda: USER
    return TestClient(app, raise_server_exceptions=False)


def _add_code(http, code="998312"):
    body = {"hsn_code": code, "description": "Usage check", "hsn_type": "services", "gst_rate_pct": 18.0, "uqc": "OTH"}
    return http.post("/api/firm-hsn-library/", json=body).json()["data"]["id"]


# ── a code ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("store,label", [
    (MOCK_SALES_DEBIT_NOTE_LINES, "a sales debit note"),
    (MOCK_PURCHASE_CREDIT_NOTE_LINES, "a purchase credit note"),
])
def test_a_code_used_on_one_of_the_note_tables_cannot_be_purged(http, store, label):
    lid = _add_code(http)
    store.append({"id": "l-1", "hsn_sac": "998312"})
    resp = http.delete(f"/api/firm-hsn-library/{lid}/purge").json()
    assert resp["success"] is False and label in resp["error"], resp
    assert len(http.get("/api/firm-hsn-library/?include_archived=true").json()["data"]["codes"]) == 1      # never removed


def test_a_different_codes_use_on_those_tables_does_not_block_this_one(http):
    lid = _add_code(http, "998312")
    MOCK_SALES_DEBIT_NOTE_LINES.append({"id": "l-1", "hsn_sac": "998313"})
    MOCK_PURCHASE_CREDIT_NOTE_LINES.append({"id": "l-2", "hsn_sac": "998314"})
    assert http.delete(f"/api/firm-hsn-library/{lid}/purge").json()["success"] is True


# ── a service, through the real path (a double that answers eq / in_) ────────────

def _db():
    return FakeDB()


def _debit_note(db, *, status, line_service=SERVICE):
    db.seed("sales_debit_notes", {"id": f"sdn-{status}", "firm_id": FIRM, "status": status})
    db.seed("sales_debit_note_lines", {"id": f"sdnl-{status}", "debit_note_id": f"sdn-{status}", "service_catalogue_id": line_service})


def _credit_note(db, *, status, line_service=SERVICE):
    db.seed("purchase_credit_notes", {"id": f"pcn-{status}", "firm_id": FIRM, "status": status})
    db.seed("purchase_credit_note_lines", {"id": f"pcnl-{status}", "credit_note_id": f"pcn-{status}", "service_catalogue_id": line_service})


def _template(db, *, status, line_service=SERVICE):
    db.seed("recurring_purchase_bill_templates", {"id": f"rpb-{status}", "firm_id": FIRM, "status": status})
    db.seed("recurring_purchase_bill_template_lines", {"id": f"rpbl-{status}", "template_id": f"rpb-{status}",
                                                       "service_catalogue_id": line_service})


def test_a_service_on_an_issued_sales_debit_note_is_reported():
    db = _db()
    _debit_note(db, status="issued")
    assert service_catalogue._find_service_usage(db, SERVICE) == ["a sales debit note"]


def test_a_service_on_a_draft_sales_debit_note_is_not():
    db = _db()
    _debit_note(db, status="draft")
    assert service_catalogue._find_service_usage(db, SERVICE) == []


def test_a_service_on_an_issued_purchase_credit_note_is_reported():
    db = _db()
    _credit_note(db, status="issued")
    assert service_catalogue._find_service_usage(db, SERVICE) == ["a purchase credit note"]


def test_a_service_on_a_draft_purchase_credit_note_is_not():
    db = _db()
    _credit_note(db, status="draft")
    assert service_catalogue._find_service_usage(db, SERVICE) == []


@pytest.mark.parametrize("status", ["active", "paused"])
def test_a_service_on_a_recurring_purchase_bill_template_that_can_still_bill_is_reported(status):
    db = _db()
    _template(db, status=status)
    assert service_catalogue._find_service_usage(db, SERVICE) == ["a recurring purchase bill template"]


def test_a_service_on_an_archived_recurring_purchase_bill_template_is_not():
    db = _db()
    _template(db, status="archived")
    assert service_catalogue._find_service_usage(db, SERVICE) == []


def test_a_template_that_is_archived_does_not_hide_one_that_is_not():
    db = _db()
    db.seed("recurring_purchase_bill_templates", {"id": "rpb-old", "firm_id": FIRM, "status": "archived"})
    db.seed("recurring_purchase_bill_templates", {"id": "rpb-live", "firm_id": FIRM, "status": "active"})
    db.seed("recurring_purchase_bill_template_lines", {"id": "l-a", "template_id": "rpb-old", "service_catalogue_id": SERVICE})
    db.seed("recurring_purchase_bill_template_lines", {"id": "l-b", "template_id": "rpb-live", "service_catalogue_id": SERVICE})
    assert service_catalogue._find_service_usage(db, SERVICE) == ["a recurring purchase bill template"]


def test_each_table_is_reported_under_its_own_label_and_only_for_its_own_service():
    db = _db()
    _debit_note(db, status="issued")
    _credit_note(db, status="issued")
    _template(db, status="active")
    assert service_catalogue._find_service_usage(db, SERVICE) == [
        "a sales debit note", "a purchase credit note", "a recurring purchase bill template"]
    assert service_catalogue._find_service_usage(db, OTHER_SERVICE) == []


# ── the same answers through the mock twin ───────────────────────────────────────

def test_the_mock_twin_reports_an_issued_sales_debit_note_and_not_a_draft_or_a_cancelled_one():
    MOCK_SALES_DEBIT_NOTES.extend([{"id": "d-issued", "status": "issued"}, {"id": "d-draft", "status": "draft"}])
    MOCK_SALES_DEBIT_NOTE_LINES.append({"id": "l-1", "debit_note_id": "d-draft", "service_catalogue_id": SERVICE})
    assert service_catalogue._find_service_usage_mock(SERVICE) == []
    MOCK_SALES_DEBIT_NOTE_LINES.append({"id": "l-2", "debit_note_id": "d-issued", "service_catalogue_id": SERVICE})
    assert service_catalogue._find_service_usage_mock(SERVICE) == ["a sales debit note"]
    assert service_catalogue._find_service_usage_mock(OTHER_SERVICE) == []


def test_the_mock_twin_reports_an_issued_purchase_credit_note_and_not_a_draft_one():
    MOCK_PURCHASE_CREDIT_NOTES.extend([{"id": "c-issued", "status": "issued"}, {"id": "c-draft", "status": "draft"}])
    MOCK_PURCHASE_CREDIT_NOTE_LINES.append({"id": "l-1", "credit_note_id": "c-draft", "service_catalogue_id": SERVICE})
    assert service_catalogue._find_service_usage_mock(SERVICE) == []
    MOCK_PURCHASE_CREDIT_NOTE_LINES.append({"id": "l-2", "credit_note_id": "c-issued", "service_catalogue_id": SERVICE})
    assert service_catalogue._find_service_usage_mock(SERVICE) == ["a purchase credit note"]
    assert service_catalogue._find_service_usage_mock(OTHER_SERVICE) == []
