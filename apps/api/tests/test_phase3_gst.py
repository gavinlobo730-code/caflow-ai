"""Phase 3 GST workspace tests — GSTR-1/3B persistence and GSTR-2B reconciliation."""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

# These tests authenticate with X-User-Role / X-Firm-Id headers, which
# core.auth only honours in the documented dev/test mode. Opt in per module
# rather than globally — see the fixture docstring in conftest.py.
pytestmark = pytest.mark.usefixtures("dev_header_auth")



@pytest.fixture
def client():
    from main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_mock_stores():
    from routers.gst_workspace import _MOCK_GSTR1, _MOCK_GSTR3B, _MOCK_GSTR2B
    _MOCK_GSTR1.clear()
    _MOCK_GSTR3B.clear()
    _MOCK_GSTR2B.clear()
    yield


_HEADERS = {"X-User-Email": "partner@test.com", "X-User-Role": "partner", "X-Firm-ID": "firm-1"}
_CLIENT_ID = "client-123"


def test_save_gstr1(client):
    resp = client.post("/api/gst-workspace/gstr1", json={
        "client_id": _CLIENT_ID,
        "period": "042025",
        "gstin": "27AABCU9603R1ZX",
        "total_taxable_paise": 100000,
        "total_igst_paise": 0,
        "total_cgst_paise": 9000,
        "total_sgst_paise": 9000,
    }, headers=_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["status"] == "draft"
    assert data["data"]["period"] == "042025"
    assert data["data"]["total_taxable_paise"] == 100000


def test_gstr1_status_transition(client):
    # Create draft
    resp = client.post("/api/gst-workspace/gstr1", json={
        "client_id": _CLIENT_ID,
        "period": "042025",
        "gstin": "27AABCU9603R1ZX",
    }, headers=_HEADERS)
    return_id = resp.json()["data"]["id"]

    # Advance to validated
    resp2 = client.patch(f"/api/gst-workspace/gstr1/{return_id}/status",
                         json={"status": "validated"}, headers=_HEADERS)
    assert resp2.json()["data"]["status"] == "validated"

    # ca_approved requires explicit flag
    resp3 = client.patch(f"/api/gst-workspace/gstr1/{return_id}/status",
                         json={"status": "ca_approved", "ca_approved": False}, headers=_HEADERS)
    assert resp3.json()["success"] is False

    # With flag — OK
    resp4 = client.patch(f"/api/gst-workspace/gstr1/{return_id}/status",
                         json={"status": "ca_approved", "ca_approved": True}, headers=_HEADERS)
    assert resp4.json()["success"] is True
    assert resp4.json()["data"]["status"] == "ca_approved"


def test_gstr3b_save_and_retrieve(client):
    resp = client.post("/api/gst-workspace/gstr3b", json={
        "client_id": _CLIENT_ID,
        "period": "042025",
        "gstin": "27AABCU9603R1ZX",
        "tax_liability_paise": 18000,
        "itc_claimed_paise": 5000,
        "net_tax_paise": 13000,
    }, headers=_HEADERS)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["net_tax_paise"] == 13000

    # Retrieve by ID
    ret_id = data["id"]
    get_resp = client.get(f"/api/gst-workspace/gstr3b/{ret_id}", headers=_HEADERS)
    assert get_resp.json()["success"] is True
    assert get_resp.json()["data"]["id"] == ret_id


def test_save_gstr1_propagates_locked_period_rejection(client, monkeypatch):
    """A locked-FY rejection from period_validation_service (raised deep
    inside save_gstr1's try, CGST §37) must propagate as its real 422 +
    detail — not get collapsed by the generic except-Exception handler into
    "Please try again", which the CA could never fix by retrying (task #97).

    Patches through routers.gst_workspace's own binding (not a fresh import
    of the service module) — some other test in the suite reloads
    services.period_validation_service, which would otherwise leave a
    monkeypatch on the stale pre-reload singleton the router never calls."""
    import routers.gst_workspace as gw

    def _locked(firm_id, date_str):
        raise HTTPException(status_code=422, detail="Financial year 2025-26 is locked for posting.")
    monkeypatch.setattr(gw.period_validation_service, "validate_posting_date", _locked)

    resp = client.post("/api/gst-workspace/gstr1", json={
        "client_id": _CLIENT_ID, "period": "042025", "gstin": "27AABCU9603R1ZX",
    }, headers=_HEADERS)
    assert resp.status_code == 422
    assert "locked" in resp.json()["detail"].lower()


def test_save_gstr3b_propagates_locked_period_rejection(client, monkeypatch):
    """Same task #97 fix, applied to GSTR-3B (CGST §39)."""
    import routers.gst_workspace as gw

    def _locked(firm_id, date_str):
        raise HTTPException(status_code=422, detail="Financial year 2025-26 is locked for posting.")
    monkeypatch.setattr(gw.period_validation_service, "validate_posting_date", _locked)

    resp = client.post("/api/gst-workspace/gstr3b", json={
        "client_id": _CLIENT_ID, "period": "042025", "gstin": "27AABCU9603R1ZX",
    }, headers=_HEADERS)
    assert resp.status_code == 422
    assert "locked" in resp.json()["detail"].lower()


def test_gstr1_approval_requires_manager_role(client):
    """CGST Act §37: only Manager+ can approve/submit a GSTR-1 return —
    ca_approved=true alone is a caller-supplied flag, not proof of role
    (task #226 audit finding). An Executive gets rejected even with the flag
    set; a Manager succeeds."""
    exec_headers = {"X-User-Email": "exec@test.com", "X-User-Role": "executive", "X-Firm-ID": "firm-1"}
    manager_headers = {"X-User-Email": "mgr@test.com", "X-User-Role": "manager", "X-Firm-ID": "firm-1"}

    resp = client.post("/api/gst-workspace/gstr1", json={
        "client_id": _CLIENT_ID, "period": "042025", "gstin": "27AABCU9603R1ZX",
    }, headers=exec_headers)
    return_id = resp.json()["data"]["id"]

    r_exec = client.patch(f"/api/gst-workspace/gstr1/{return_id}/status",
                          json={"status": "ca_approved", "ca_approved": True},
                          headers=exec_headers)
    assert r_exec.json()["success"] is False
    assert "Manager" in r_exec.json()["error"]

    r_mgr = client.patch(f"/api/gst-workspace/gstr1/{return_id}/status",
                         json={"status": "ca_approved", "ca_approved": True},
                         headers=manager_headers)
    assert r_mgr.json()["success"] is True
    assert r_mgr.json()["data"]["status"] == "ca_approved"


def test_gstr3b_approval_requires_manager_role(client):
    """Same task #226 fix, applied to GSTR-3B (CGST Act §39)."""
    exec_headers = {"X-User-Email": "exec@test.com", "X-User-Role": "executive", "X-Firm-ID": "firm-1"}
    manager_headers = {"X-User-Email": "mgr@test.com", "X-User-Role": "manager", "X-Firm-ID": "firm-1"}

    resp = client.post("/api/gst-workspace/gstr3b", json={
        "client_id": _CLIENT_ID, "period": "042025", "gstin": "27AABCU9603R1ZX",
    }, headers=exec_headers)
    return_id = resp.json()["data"]["id"]

    r_exec = client.patch(f"/api/gst-workspace/gstr3b/{return_id}/status",
                          json={"status": "ca_approved", "ca_approved": True},
                          headers=exec_headers)
    assert r_exec.json()["success"] is False
    assert "Manager" in r_exec.json()["error"]

    r_mgr = client.patch(f"/api/gst-workspace/gstr3b/{return_id}/status",
                         json={"status": "ca_approved", "ca_approved": True},
                         headers=manager_headers)
    assert r_mgr.json()["success"] is True
    assert r_mgr.json()["data"]["status"] == "ca_approved"


def test_filing_history_only_submitted(client):
    # Save two returns — one draft, one submitted
    r1 = client.post("/api/gst-workspace/gstr1", json={
        "client_id": _CLIENT_ID, "period": "042025", "gstin": "27AABCU9603R1ZX",
    }, headers=_HEADERS).json()["data"]["id"]

    r2 = client.post("/api/gst-workspace/gstr1", json={
        "client_id": _CLIENT_ID, "period": "052025", "gstin": "27AABCU9603R1ZX",
    }, headers=_HEADERS).json()["data"]["id"]

    # Submit r2
    client.patch(f"/api/gst-workspace/gstr1/{r2}/status",
                 json={"status": "submitted", "ca_approved": True}, headers=_HEADERS)

    history = client.get(f"/api/gst-workspace/filing-history?client_id={_CLIENT_ID}",
                         headers=_HEADERS).json()["data"]
    filed_ids = [r["id"] for r in history["gstr1_filed"]]
    assert r2 in filed_ids
    assert r1 not in filed_ids


def test_save_gstr9_requires_and_stores_gstin(client):
    """CGST Act §44 — GSTR-9 annual return draft. gstin is required: the
    underlying table (gstr1_returns, shared via return_type='gstr9') has
    gstin as NOT NULL, and the request model previously didn't collect it at
    all — a save would have violated the NOT NULL constraint on real
    Postgres (task #226 audit finding)."""
    resp = client.post("/api/gst-workspace/gstr9", json={
        "client_id": _CLIENT_ID,
        "financial_year": "2025-26",
        "gstin": "27AABCU9603R1ZX",
        "total_taxable_paise": 500000000,
        "total_tax_paise": 90000000,
    }, headers=_HEADERS)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["gstin"] == "27AABCU9603R1ZX"
    assert data["return_type"] == "gstr9"
    assert data["financial_year"] == "2025-26"

    # Invalid GSTIN format must be rejected (same validate_gstin as GSTR-1/3B).
    bad = client.post("/api/gst-workspace/gstr9", json={
        "client_id": _CLIENT_ID, "financial_year": "2025-26", "gstin": "not-a-gstin",
    }, headers=_HEADERS)
    assert bad.status_code == 422


def test_gstr2b_reconciliation(client):
    """3 book invoices; 2 match, 1 missing in 2B."""
    body = {
        "client_id": _CLIENT_ID,
        "period": "042025",
        "raw_data": {
            "invoices": [
                {"inum": "INV-001", "sgstin": "29AAA", "txval": 1000.0},
                {"inum": "INV-002", "sgstin": "29BBB", "txval": 2000.0},
            ],
            "book_invoices": [
                {"invoice_no": "INV-001", "gstin": "29AAA", "taxable_paise": 100000},
                {"invoice_no": "INV-002", "gstin": "29BBB", "taxable_paise": 200000},
                {"invoice_no": "INV-003", "gstin": "29CCC", "taxable_paise": 300000},
            ],
        },
    }
    resp = client.post("/api/gst-workspace/gstr2b/upload", json=body, headers=_HEADERS)
    assert resp.status_code == 200
    result = resp.json()["data"]["reconciliation_result"]
    assert result["summary"]["total_book"] == 3
    assert result["summary"]["missing_count"] == 1
    assert len(result["missing_in_2b"]) == 1
