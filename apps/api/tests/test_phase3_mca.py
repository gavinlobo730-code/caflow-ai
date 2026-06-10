"""Phase 3 MCA workspace tests — company master, directors, filings."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_mock_stores():
    from routers.mca_workspace import _MOCK_COMPANIES, _MOCK_DIRECTORS, _MOCK_FILINGS
    _MOCK_COMPANIES.clear()
    _MOCK_DIRECTORS.clear()
    _MOCK_FILINGS.clear()
    yield


_HEADERS = {"X-User-Email": "partner@test.com", "X-User-Role": "partner", "X-Firm-ID": "firm-1"}
_CLIENT_ID = "client-123"


def test_create_company(client):
    """Create company master with CIN and capital in integer paise."""
    resp = client.post("/api/mca-workspace/companies", json={
        "client_id": _CLIENT_ID,
        "cin": "U74999MH2020PTC123456",
        "company_name": "Test Pvt Ltd",
        "incorporation_date": "2020-01-15",
        "authorized_capital_paise": 100000000,   # ₹10 lakh
        "paid_up_capital_paise": 100000,          # ₹1,000
        "company_type": "PVT",
    }, headers=_HEADERS)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["cin"] == "U74999MH2020PTC123456"
    assert data["authorized_capital_paise"] == 100000000


def test_add_director_and_update_kyc(client):
    """Add director then update KYC status. Companies Act 2013 §165."""
    resp = client.post("/api/mca-workspace/directors", json={
        "client_id": _CLIENT_ID,
        "din": "12345678",
        "name": "Ravi Kumar",
        "designation": "Managing Director",
        "date_of_appointment": "2020-01-15",
        "pan": "ABCDE1234F",
        "kyc_status": "pending",
    }, headers=_HEADERS)
    assert resp.status_code == 200
    director_id = resp.json()["data"]["id"]

    # Update KYC
    upd = client.patch(f"/api/mca-workspace/directors/{director_id}",
                       json={"kyc_status": "active"}, headers=_HEADERS)
    assert upd.json()["success"] is True
    assert upd.json()["data"]["kyc_status"] == "active"


def test_create_annual_filings(client):
    """Create AOC-4, MGT-7, ADT-1 annual filings. Companies Act §137, §92, §139."""
    for form in ["AOC-4", "MGT-7", "ADT-1"]:
        resp = client.post("/api/mca-workspace/filings", json={
            "client_id": _CLIENT_ID,
            "form_type": form,
            "financial_year": "2025-26",
        }, headers=_HEADERS)
        assert resp.status_code == 200, f"Failed for {form}"
        data = resp.json()["data"]
        assert data["form_type"] == form
        assert data["category"] == "annual"
        assert data["status"] == "not_started"


def test_filing_status_transition_requires_ca_approval(client):
    """Filing → filed requires ca_approved=True."""
    resp = client.post("/api/mca-workspace/filings", json={
        "client_id": _CLIENT_ID,
        "form_type": "MGT-7",
        "financial_year": "2025-26",
    }, headers=_HEADERS)
    filing_id = resp.json()["data"]["id"]

    # in_progress — no flag needed
    r2 = client.patch(f"/api/mca-workspace/filings/{filing_id}/status",
                      json={"status": "in_progress"}, headers=_HEADERS)
    assert r2.json()["success"] is True

    # filed without flag — should fail (CA REVIEW REQUIRED)
    r3 = client.patch(f"/api/mca-workspace/filings/{filing_id}/status",
                      json={"status": "filed", "ca_approved": False}, headers=_HEADERS)
    assert r3.json()["success"] is False

    # filed with flag + SRN — should succeed
    r4 = client.patch(f"/api/mca-workspace/filings/{filing_id}/status",
                      json={"status": "filed", "ca_approved": True, "srn": "SRN123"}, headers=_HEADERS)
    assert r4.json()["success"] is True
    assert r4.json()["data"]["srn"] == "SRN123"


def test_filing_history_only_filed(client):
    """Filing history only returns filed records."""
    # Create two filings; file only one
    r1 = client.post("/api/mca-workspace/filings", json={
        "client_id": _CLIENT_ID, "form_type": "AOC-4", "financial_year": "2025-26",
    }, headers=_HEADERS).json()["data"]["id"]
    r2 = client.post("/api/mca-workspace/filings", json={
        "client_id": _CLIENT_ID, "form_type": "MGT-7", "financial_year": "2025-26",
    }, headers=_HEADERS).json()["data"]["id"]

    client.patch(f"/api/mca-workspace/filings/{r2}/status",
                 json={"status": "filed", "ca_approved": True, "srn": "SRN999"}, headers=_HEADERS)

    history = client.get(f"/api/mca-workspace/filing-history?client_id={_CLIENT_ID}",
                         headers=_HEADERS).json()["data"]
    ids = [f["id"] for f in history]
    assert r2 in ids
    assert r1 not in ids


def test_invalid_form_type_rejected(client):
    """Unsupported form type should return error."""
    resp = client.post("/api/mca-workspace/filings", json={
        "client_id": _CLIENT_ID,
        "form_type": "FAKE-99",
        "financial_year": "2025-26",
    }, headers=_HEADERS)
    assert resp.json()["success"] is False
