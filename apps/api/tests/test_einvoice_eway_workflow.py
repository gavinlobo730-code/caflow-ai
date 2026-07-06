"""Batch 7 — e-invoice (IRN) and e-way bill compliance workflows.

Exercises the full record lifecycle (draft → generated → cancelled) through the
existing routers in mock mode, plus the new GST-treatment capture on the IRN
record. These record-keeping flows never auto-submit to a government portal:
the CA generates the IRN/EWB on the portal and records the result here.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from routers.einvoice import router as einvoice_router
from routers.eway_bill import router as eway_router
from core.auth import get_current_user

USER = {"id": "u-c1", "firm_id": "firm-c1", "role": "Partner"}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(einvoice_router)
    app.include_router(eway_router)
    app.dependency_overrides[get_current_user] = lambda: USER
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def clear_stores():
    from domain.income_tax import einvoice_service, eway_service
    einvoice_service._MOCK_RECORDS.clear()
    # eway service keeps its own mock store; clear if present.
    for attr in ("_MOCK_RECORDS", "_MOCK_EWAY_RECORDS"):
        store = getattr(eway_service, attr, None)
        if isinstance(store, dict):
            store.clear()
    yield


# ── IRN workflow ──────────────────────────────────────────────────────────────

def test_irn_full_lifecycle_with_treatment(client):
    # 1) Create draft with an export-without-payment treatment + LUT ref.
    r = client.post("/api/einvoice/records", json={
        "client_id": "cl-1", "invoice_number": "INV-1", "invoice_date": "2026-07-06",
        "sales_invoice_id": "si-1", "gst_treatment": "export_without_payment", "lut_number": "LUT/2026/001",
    })
    assert r.status_code == 200
    rec = r.json()["data"]
    assert rec["status"] == "draft"
    assert rec["irn"] is None
    assert rec["gst_treatment"] == "export_without_payment"
    assert rec["lut_number"] == "LUT/2026/001"
    assert rec["ca_review_required"] is True
    rid = rec["id"]

    # 2) Record the IRN the CA generated on the IRP portal.
    g = client.post(f"/api/einvoice/records/{rid}/irn-generated", json={
        "irn": "IRN1234567890", "ack_number": "ACK99", "ack_date": "2026-07-06", "qr_data": "QRPAYLOAD",
    })
    assert g.status_code == 200
    gen = g.json()["data"]
    assert gen["status"] == "generated"
    assert gen["irn"] == "IRN1234567890"
    assert gen["qr_data"] == "QRPAYLOAD"

    # 3) It appears in the list; 4) cancellation moves it to cancelled.
    listed = client.get("/api/einvoice/records?client_id=cl-1").json()["data"]
    assert any(x["id"] == rid and x["status"] == "generated" for x in listed)

    c = client.post(f"/api/einvoice/records/{rid}/cancel", json={"cancellation_reason": "wrong value"})
    assert c.json()["data"]["status"] == "cancelled"
    assert c.json()["data"]["cancellation_reason"] == "wrong value"


def test_irn_rejects_unknown_treatment(client):
    r = client.post("/api/einvoice/records", json={
        "client_id": "cl-1", "invoice_number": "INV-2", "invoice_date": "2026-07-06",
        "gst_treatment": "not_a_real_treatment",
    })
    assert r.status_code == 422


def test_irn_default_treatment_is_null(client):
    r = client.post("/api/einvoice/records", json={
        "client_id": "cl-1", "invoice_number": "INV-3", "invoice_date": "2026-07-06",
    })
    assert r.json()["data"]["gst_treatment"] is None


# ── E-Way workflow ────────────────────────────────────────────────────────────

def test_eway_full_lifecycle(client):
    r = client.post("/api/eway-bill/records", json={
        "client_id": "cl-1", "invoice_number": "INV-1",
        "dispatch_from": "27", "ship_to": "29", "goods_description": "Laptops",
        "taxable_value_paise": 6000000, "sales_invoice_id": "si-1", "hsn_code": "8471",
    })
    assert r.status_code == 200
    rec = r.json()["data"]
    assert rec["status"] == "draft"
    rid = rec["id"]

    g = client.post(f"/api/eway-bill/records/{rid}/generated", json={
        "ewb_number": "EWB123456789012", "ewb_date": "2026-07-06", "ewb_valid_upto": "2026-07-08",
    })
    assert g.json()["data"]["status"] == "generated"
    assert g.json()["data"]["ewb_number"] == "EWB123456789012"

    c = client.post(f"/api/eway-bill/records/{rid}/cancel", json={"cancellation_reason": "trip cancelled"})
    assert c.json()["data"]["status"] == "cancelled"
