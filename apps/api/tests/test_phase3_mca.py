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
    """Create company master with CIN and capital in integer paise.

    mca_companies (migration 038) has no incorporation_date/registered_address/
    company_type columns — the real columns are incorp_date/registered_office/
    company_category, and company_category's CHECK constraint requires the full
    Companies Act 2013 term ("Private Limited"), not the frontend's short form
    ("PVT"). The request keeps the frontend's field names; the router maps them
    internally (task #219 schema-drift fix) — assert the mapped shape here so a
    regression back to the old (non-existent) column names is caught even
    though _MOCK stores don't enforce a real Postgres schema."""
    resp = client.post("/api/mca-workspace/companies", json={
        "client_id": _CLIENT_ID,
        "cin": "U74999MH2020PTC123456",
        "company_name": "Test Pvt Ltd",
        "incorporation_date": "2020-01-15",
        "registered_address": "123 MG Road, Mumbai",
        "authorized_capital_paise": 100000000,   # ₹10 lakh
        "paid_up_capital_paise": 100000,          # ₹1,000
        "company_type": "PVT",
    }, headers=_HEADERS)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["cin"] == "U74999MH2020PTC123456"
    assert data["authorized_capital_paise"] == 100000000
    assert data["incorp_date"] == "2020-01-15"
    assert data["registered_office"] == "123 MG Road, Mumbai"
    assert data["company_category"] == "Private Limited"


def test_create_company_type_passthrough_for_full_term(client):
    """A caller sending the CHECK-valid full term directly ("LLP", "Section 8")
    is not garbled by the PVT/PUB abbreviation map."""
    resp = client.post("/api/mca-workspace/companies", json={
        "client_id": _CLIENT_ID, "cin": "U74999MH2020PTC000001",
        "company_name": "Test LLP", "company_type": "Section 8",
    }, headers=_HEADERS)
    assert resp.json()["data"]["company_category"] == "Section 8"


def test_add_director_and_update_kyc(client):
    """Add director then update KYC status. Companies Act 2013 §165.

    mca_directors has no "name" column (real column is director_name,
    migration 038); request keeps the frontend's "name" field, mapped
    internally (task #219). The DirectorsTab "Mark KYC Active" button sends
    kyc_status="active" — migration 038's original CHECK constraint didn't
    allow it, widened by migration 233."""
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
    data = resp.json()["data"]
    director_id = data["id"]
    assert data["director_name"] == "Ravi Kumar"

    # Update KYC ("Mark KYC Active" — DirectorsTab.updateKYC)
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
            "description": "Draft prepared, awaiting auditor sign-off",
        }, headers=_HEADERS)
        assert resp.status_code == 200, f"Failed for {form}"
        data = resp.json()["data"]
        assert data["form_type"] == form
        assert data["category"] == "annual"
        assert data["status"] == "not_started"
        # mca_filings has no "description" column — reuses the existing
        # "notes" column instead of adding a duplicate one (task #219).
        assert data["notes"] == "Draft prepared, awaiting auditor sign-off"


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

    # filed with flag + SRN + filing_date — should succeed
    r4 = client.patch(f"/api/mca-workspace/filings/{filing_id}/status",
                      json={"status": "filed", "ca_approved": True, "srn": "SRN123",
                            "filing_date": "2026-05-20"}, headers=_HEADERS)
    assert r4.json()["success"] is True
    assert r4.json()["data"]["srn"] == "SRN123"
    # mca_filings' real column is filed_date (migration 012); request keeps
    # the frontend's "filing_date" field, mapped internally (task #219).
    assert r4.json()["data"]["filed_date"] == "2026-05-20"


def test_get_company_returns_linked_directors(client):
    """GET /companies/{id} joins directors by company_id — mca_directors had
    no company_id column until migration 233, so this endpoint always failed
    against a real Postgres instance."""
    company_id = client.post("/api/mca-workspace/companies", json={
        "client_id": _CLIENT_ID, "cin": "U74999MH2020PTC999999", "company_name": "Linked Co",
    }, headers=_HEADERS).json()["data"]["id"]

    linked = client.post("/api/mca-workspace/directors", json={
        "client_id": _CLIENT_ID, "company_id": company_id, "din": "87654321",
        "name": "Priya Shah", "designation": "Director", "date_of_appointment": "2021-04-01",
    }, headers=_HEADERS).json()["data"]["id"]
    # A director not linked to this company must not appear.
    client.post("/api/mca-workspace/directors", json={
        "client_id": _CLIENT_ID, "din": "11223344",
        "name": "Unlinked Director", "designation": "Director", "date_of_appointment": "2021-04-01",
    }, headers=_HEADERS)

    resp = client.get(f"/api/mca-workspace/companies/{company_id}", headers=_HEADERS)
    assert resp.json()["success"] is True
    director_ids = [d["id"] for d in resp.json()["data"]["directors"]]
    assert director_ids == [linked]


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
