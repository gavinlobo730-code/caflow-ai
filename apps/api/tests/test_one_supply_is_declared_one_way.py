"""An e-invoice record cannot contradict the invoice it names (SALES-19).

WHAT WAS WRONG

The treatment of a supply is settled by the invoice's own `supply_type` and
`invoice_type` — the pair GSTR-1 is actually built from — and
`domain/gst/treatment.treatment_for_invoice` has derived it since the first half
of this finding. `einvoice_records` carries a SECOND `gst_treatment`, captured
independently when a CA prepares an IRN, and `POST /api/einvoice/records` stored
whatever the caller sent.

The Prepare IRN picker opened on "Regular" and was never seeded from the
invoice. So a CA who had marked an invoice SEZ-without-payment, and then left
the picker alone, stored a record saying `regular` — and the compliance panel
rendered BOTH: "Record prepared (Regular)" above a treatment summary correctly
reading "SEZ under LUT/Bond". Two labels on one screen, disagreeing, on the
document a human keys the IRP from.

WHY REFUSE RATHER THAN RESOLVE

Taking the caller's value keeps the wrong export route on that document, and
IGST s.16(3)(a) under an LUT against (b) on payment of tax are different refund
routes under different rules. Taking the derived value silently discards what
somebody just chose on a screen that offered them the choice. So the door says
so, and the screen no longer offers a choice the door will refuse.

WHAT IS DELIBERATELY NOT REFUSED: a record naming no invoice this product holds.
`sales_invoice_id` is optional — a record may be prepared for an invoice raised
elsewhere — so there is nothing to reconcile against and the caller's value
stands. Refusing would make the link mandatory by accident.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user
from domain.gst.treatment import treatment_for_record
from routers.einvoice import router as einvoice_router

USER = {"id": "u-s19", "firm_id": "firm-s19", "role": "Partner"}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(einvoice_router)
    app.dependency_overrides[get_current_user] = lambda: USER
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def stores():
    from domain.income_tax import einvoice_service
    from routers.sales_invoices import MOCK_SALES_INVOICES
    einvoice_service._MOCK_RECORDS.clear()
    before = list(MOCK_SALES_INVOICES)
    MOCK_SALES_INVOICES.clear()
    yield MOCK_SALES_INVOICES
    MOCK_SALES_INVOICES.clear()
    MOCK_SALES_INVOICES.extend(before)


def _seed(stores, **over):
    row = {
        "id": "si-s19", "firm_id": USER["firm_id"], "client_id": "cl-s19",
        "supply_type": "taxable", "invoice_type": "Regular", "igst_paise": 0,
    }
    row.update(over)
    stores.append(row)
    return row


def _prepare(client, **body):
    payload = {
        "client_id": "cl-s19", "invoice_number": "INV-9", "invoice_date": "2026-07-06",
        "sales_invoice_id": "si-s19",
    }
    payload.update(body)
    return client.post("/api/einvoice/records", json=payload)


# ── the rule itself ───────────────────────────────────────────────────────────

def test_the_invoice_settles_it_when_the_caller_says_nothing():
    assert treatment_for_record(stated=None, derived="sez_without_payment") == (
        "sez_without_payment", None)


def test_agreement_is_stored_and_case_is_not_a_disagreement():
    assert treatment_for_record(stated="Regular", derived="regular") == ("regular", None)


def test_a_disagreement_names_both_and_stores_neither():
    value, refusal = treatment_for_record(stated="regular", derived="sez_without_payment")
    assert value is None
    assert refusal and "regular" in refusal and "sez_without_payment" in refusal


def test_no_invoice_to_reconcile_against_is_not_a_refusal():
    # The link is optional; a record prepared for an invoice raised elsewhere
    # has nothing to check, and refusing would make the link mandatory.
    assert treatment_for_record(stated="deemed_export", derived=None) == (
        "deemed_export", None)
    assert treatment_for_record(stated=None, derived=None) == (None, None)


# ── the write door ────────────────────────────────────────────────────────────

def test_the_record_takes_the_invoices_treatment_when_none_is_sent(client, stores):
    _seed(stores, invoice_type="sez_without_payment")
    r = _prepare(client)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["gst_treatment"] == "sez_without_payment"


def test_a_record_contradicting_its_own_invoice_is_refused(client, stores):
    _seed(stores, invoice_type="sez_without_payment")
    r = _prepare(client, gst_treatment="regular")
    assert r.status_code == 422, r.text
    assert "sez_without_payment" in r.json()["detail"]


def test_the_export_route_is_read_off_the_tax_actually_charged(client, stores):
    # IGST s.16(3): (b) on payment of IGST, (a) under an LUT with nothing
    # charged. Asking for the wrong one asks for the wrong refund.
    _seed(stores, supply_type="zero_rated", igst_paise=180_00)
    assert _prepare(client).json()["data"]["gst_treatment"] == "export_with_payment"
    assert _prepare(client, gst_treatment="export_without_payment").status_code == 422


def test_an_invoice_in_another_book_is_not_reached_for_a_treatment(client, stores):
    # The read is scoped to the firm AND the client, so a record cannot borrow
    # a treatment from somebody else's invoice — it falls back to the caller's.
    _seed(stores, client_id="cl-other", invoice_type="sez_without_payment")
    r = _prepare(client, gst_treatment="regular")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["gst_treatment"] == "regular"


def test_a_record_naming_no_invoice_still_takes_what_the_caller_sent(client, stores):
    r = client.post("/api/einvoice/records", json={
        "client_id": "cl-s19", "invoice_number": "INV-ELSEWHERE",
        "invoice_date": "2026-07-06", "gst_treatment": "deemed_export",
    })
    assert r.status_code == 200, r.text
    assert r.json()["data"]["gst_treatment"] == "deemed_export"
