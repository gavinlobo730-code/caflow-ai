"""
Task #223 — wire existing GSTIN/CIN/DIN/PAN validators into write endpoints.

Working validators already existed (core/validators.py, domain/tds/tds_validator.py)
but several write endpoints accepted these Indian tax/company identifiers as raw
unvalidated strings:

  - mca_workspace.py::create_company()  — cin (Companies Act 2013)
  - mca_workspace.py::create_director() — din (§153/154), pan (IT Act §139A)
  - tds_workspace.py::create_certificate() — deductee_pan (§203, §206AA sentinels)
  - tds_workspace.py::create_return()      — deductee_details[].deductee_pan
  - gst_workspace.py::save_gstr1/save_gstr3b — gstin (CGST Act §37/§39)

Also: vendors.py/customers.py each carried a fully-written but DEAD GSTIN
validator (never called — models.parties.py's Pydantic validators are the real
enforcement path) — removed. And GSTIN/PAN validated-but-not-normalized case
drift in models/parties.py — a lowercase-typed GSTIN/PAN now persists uppercase,
matching what was actually validated.
"""
import pytest
from fastapi.testclient import TestClient

from core.validators import validate_din, validate_cin, validate_gstin, validate_pan

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
    from routers.mca_workspace import _MOCK_COMPANIES, _MOCK_DIRECTORS
    from routers.gst_workspace import _MOCK_GSTR1, _MOCK_GSTR3B
    from routers.tds_workspace import _MOCK_RETURNS, _MOCK_CERTIFICATES
    _MOCK_COMPANIES.clear(); _MOCK_DIRECTORS.clear()
    _MOCK_GSTR1.clear(); _MOCK_GSTR3B.clear()
    _MOCK_RETURNS.clear(); _MOCK_CERTIFICATES.clear()
    yield


_HEADERS = {"X-User-Email": "partner@test.com", "X-User-Role": "partner", "X-Firm-ID": "firm-1"}
_CLIENT_ID = "client-123"


# ── core.validators.validate_din (new) ─────────────────────────────────────────

def test_validate_din_accepts_8_digits():
    assert validate_din("00012345") is None


@pytest.mark.parametrize("din", ["1234567", "123456789", "ABCD1234", ""])
def test_validate_din_rejects_bad_format(din):
    assert validate_din(din) is not None


# ── mca_workspace.py::create_company — CIN ─────────────────────────────────────

def test_create_company_rejects_invalid_cin(client):
    resp = client.post("/api/mca-workspace/companies", json={
        "client_id": _CLIENT_ID, "cin": "NOT-A-CIN", "company_name": "Bad Co",
    }, headers=_HEADERS)
    assert resp.status_code == 422


def test_create_company_accepts_valid_cin_and_normalizes_case(client):
    resp = client.post("/api/mca-workspace/companies", json={
        "client_id": _CLIENT_ID, "cin": "u74999mh2020ptc123456", "company_name": "Good Co",
    }, headers=_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["data"]["cin"] == "U74999MH2020PTC123456"


# ── mca_workspace.py::create_director — DIN + PAN ──────────────────────────────

def test_create_director_rejects_invalid_din(client):
    resp = client.post("/api/mca-workspace/directors", json={
        "client_id": _CLIENT_ID, "din": "123", "name": "Bad Director",
        "designation": "Director", "date_of_appointment": "2020-01-15",
    }, headers=_HEADERS)
    assert resp.status_code == 422


def test_create_director_rejects_invalid_pan(client):
    resp = client.post("/api/mca-workspace/directors", json={
        "client_id": _CLIENT_ID, "din": "12345678", "name": "Bad PAN Director",
        "designation": "Director", "date_of_appointment": "2020-01-15",
        "pan": "NOTAPAN",
    }, headers=_HEADERS)
    assert resp.status_code == 422


def test_create_director_accepts_valid_din_and_pan(client):
    resp = client.post("/api/mca-workspace/directors", json={
        "client_id": _CLIENT_ID, "din": "12345678", "name": "Good Director",
        "designation": "Director", "date_of_appointment": "2020-01-15",
        "pan": "abcde1234f",
    }, headers=_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["data"]["din"] == "12345678"
    assert resp.json()["data"]["pan"] == "ABCDE1234F"


# ── tds_workspace.py::create_certificate — deductee PAN (§203) ────────────────

def test_create_certificate_rejects_invalid_deductee_pan(client):
    resp = client.post("/api/tds-workspace/certificates", json={
        "client_id": _CLIENT_ID, "deductee_pan": "BADPAN", "deductee_name": "V",
        "financial_year": "2025-26", "certificate_type": "Form 16A", "section": "194C",
    }, headers=_HEADERS)
    assert resp.status_code == 422


def test_create_certificate_accepts_valid_deductee_pan(client):
    resp = client.post("/api/tds-workspace/certificates", json={
        "client_id": _CLIENT_ID, "deductee_pan": "abcde1234f", "deductee_name": "V",
        "financial_year": "2025-26", "certificate_type": "Form 16A", "section": "194C",
    }, headers=_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["data"]["deductee_pan"] == "ABCDE1234F"


# ── tds_workspace.py::create_return — deductee_details PAN (§206AA sentinels) ──

def test_create_return_rejects_invalid_deductee_pan_in_details(client):
    resp = client.post("/api/tds-workspace/returns", json={
        "client_id": _CLIENT_ID, "return_type": "26Q", "quarter": "Q1",
        "financial_year": "2025-26",
        "deductee_details": [{"deductee_pan": "BADPAN", "section": "194C"}],
    }, headers=_HEADERS)
    assert resp.status_code == 422


def test_create_return_allows_206aa_pan_not_available_sentinel(client):
    """IT Act §206AA: a deductee with no PAN on file is deducted at the higher
    floor rate, not rejected outright — the return itself must still save."""
    resp = client.post("/api/tds-workspace/returns", json={
        "client_id": _CLIENT_ID, "return_type": "26Q", "quarter": "Q1",
        "financial_year": "2025-26",
        "deductee_details": [{"deductee_pan": "PANNOTAVBL", "section": "194C"}],
    }, headers=_HEADERS)
    assert resp.status_code == 200


# ── gst_workspace.py::save_gstr1 / save_gstr3b — GSTIN (CGST §37/§39) ─────────

def test_save_gstr1_rejects_invalid_gstin(client):
    resp = client.post("/api/gst-workspace/gstr1", json={
        "client_id": _CLIENT_ID, "period": "042025", "gstin": "NOTAGSTIN",
    }, headers=_HEADERS)
    assert resp.status_code == 422


def test_save_gstr1_accepts_valid_gstin_and_normalizes_case(client):
    resp = client.post("/api/gst-workspace/gstr1", json={
        "client_id": _CLIENT_ID, "period": "042025", "gstin": "27aabcu9603r1zx",
    }, headers=_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["data"]["gstin"] == "27AABCU9603R1ZX"


def test_save_gstr3b_rejects_invalid_gstin(client):
    resp = client.post("/api/gst-workspace/gstr3b", json={
        "client_id": _CLIENT_ID, "period": "042025", "gstin": "NOTAGSTIN",
    }, headers=_HEADERS)
    assert resp.status_code == 422


def test_save_gstr3b_accepts_valid_gstin(client):
    resp = client.post("/api/gst-workspace/gstr3b", json={
        "client_id": _CLIENT_ID, "period": "042025", "gstin": "27AABCU9603R1ZX",
    }, headers=_HEADERS)
    assert resp.status_code == 200


# ── models/parties.py — GSTIN/PAN case normalization on write ─────────────────

def test_customer_gstin_and_pan_normalized_to_uppercase():
    from models.parties import CustomerIn
    c = CustomerIn(client_id="CLI", name="Acme", gstin="27aabcu9603r1zx", pan="abcde1234f")
    assert c.gstin == "27AABCU9603R1ZX"
    assert c.pan == "ABCDE1234F"


def test_vendor_gstin_and_pan_normalized_to_uppercase():
    from models.parties import VendorIn
    v = VendorIn(client_id="CLI", name="Supplier", gstin="27aabcu9603r1zx", pan="abcde1234f")
    assert v.gstin == "27AABCU9603R1ZX"
    assert v.pan == "ABCDE1234F"
