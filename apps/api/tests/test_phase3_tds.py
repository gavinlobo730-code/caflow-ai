"""Phase 3 TDS workspace tests — challans, returns, 26AS reconciliation, certificates."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_mock_stores():
    from routers.tds_workspace import (
        _MOCK_CHALLANS, _MOCK_RETURNS, _MOCK_CERTIFICATES, _MOCK_FORM26AS, _MOCK_DEDUCTIONS
    )
    _MOCK_CHALLANS.clear()
    _MOCK_RETURNS.clear()
    _MOCK_CERTIFICATES.clear()
    _MOCK_FORM26AS.clear()
    _MOCK_DEDUCTIONS.clear()
    yield


_HEADERS = {"X-User-Email": "partner@test.com", "X-User-Role": "partner", "X-Firm-ID": "firm-1"}
_CLIENT_ID = "client-123"


def test_create_challan(client):
    """IT Act §200 — challan creation with BSR code in integer paise."""
    resp = client.post("/api/tds-workspace/challans", json={
        "client_id": _CLIENT_ID,
        "bsr_code": "1234567",
        "challan_date": "2025-07-07",
        "amount_paise": 500000,  # ₹5,000
        "challan_no": "CHL-001",
        "section": "194C",
        "financial_year": "2025-26",
        "quarter": "Q1",
    }, headers=_HEADERS)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["amount_paise"] == 500000
    assert data["bsr_code"] == "1234567"
    assert data["status"] == "deposited"


def test_tds_return_status_transitions(client):
    """Return must require ca_approved=true to move to ca_approved/filed."""
    resp = client.post("/api/tds-workspace/returns", json={
        "client_id": _CLIENT_ID,
        "return_type": "26Q",
        "quarter": "Q1",
        "financial_year": "2025-26",
    }, headers=_HEADERS)
    return_id = resp.json()["data"]["id"]

    # Prepare — no flag needed
    r2 = client.patch(f"/api/tds-workspace/returns/{return_id}/status",
                      json={"status": "prepared"}, headers=_HEADERS)
    assert r2.json()["success"] is True

    # filed without flag — should fail
    r3 = client.patch(f"/api/tds-workspace/returns/{return_id}/status",
                      json={"status": "filed", "ca_approved": False}, headers=_HEADERS)
    assert r3.json()["success"] is False

    # filed with flag — still needs a PRN (TRACES proof-of-filing captured
    # server-side, migration 037). With the flag AND a PRN it should succeed.
    r4 = client.patch(f"/api/tds-workspace/returns/{return_id}/status",
                      json={"status": "filed", "ca_approved": True,
                            "prn": "PRN2526Q1000001", "ack_number": "ACK123456789"},
                      headers=_HEADERS)
    assert r4.json()["success"] is True
    assert r4.json()["data"]["status"] == "filed"
    assert r4.json()["data"]["prn"] == "PRN2526Q1000001"

    # filed WITHOUT a PRN must be rejected (a return can't be "filed" with no
    # acknowledgement) — guards the migration-037 requirement.
    resp2 = client.post("/api/tds-workspace/returns", json={
        "client_id": _CLIENT_ID, "return_type": "26Q", "quarter": "Q2",
        "financial_year": "2025-26",
    }, headers=_HEADERS)
    rid2 = resp2.json()["data"]["id"]
    r5 = client.patch(f"/api/tds-workspace/returns/{rid2}/status",
                      json={"status": "filed", "ca_approved": True}, headers=_HEADERS)
    assert r5.json()["success"] is False


def test_certificate_generation_draft_only(client):
    """IT Act §203 — certificates always draft, ca_review_required=True."""
    resp = client.post("/api/tds-workspace/certificates", json={
        "client_id": _CLIENT_ID,
        "deductee_pan": "ABCDE1234F",
        "deductee_name": "Test Vendor",
        "financial_year": "2025-26",
        "certificate_type": "Form 16A",
        "tds_amount_paise": 100000,
        "section": "194C",
    }, headers=_HEADERS)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "draft"
    assert data["ca_review_required"] is True


def test_form26as_reconciliation(client):
    """IT Act §203AA — 26AS reconciliation: 2 deductions, 1 mismatch."""
    body = {
        "client_id": _CLIENT_ID,
        "financial_year": "2025-26",
        "raw_data": {
            "tds_entries": [
                {"pan": "ABCDE1234F", "section": "194C", "amount_paise": 10000},
                {"pan": "FGHIJ5678K", "section": "194I", "amount_paise": 20000},
            ],
            "book_deductions": [
                {"deductee_pan": "ABCDE1234F", "section": "194C", "amount_paise": 10000},
                {"deductee_pan": "FGHIJ5678K", "section": "194I", "amount_paise": 25000},  # mismatch
            ],
        },
    }
    resp = client.post("/api/tds-workspace/form26as/upload", json=body, headers=_HEADERS)
    assert resp.status_code == 200
    result = resp.json()["data"]["reconciliation_result"]
    assert result["summary"]["matched_count"] == 1
    assert result["summary"]["mismatch_count"] == 1
    mismatch = result["mismatched"][0]
    assert mismatch["diff_paise"] == 5000
