"""Phase 3 TDS workspace tests — challans, returns, 26AS reconciliation, certificates."""
import pytest
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
    # tds_challans has no amount_paise column (migration 037) — the amount is
    # the TOTAL and lands on total_paise. The surcharge, interest and penalty
    # heads are optional (TDS-08/TDS-30) and this request sends none, so the
    # tax is the whole of it: sending nothing extra keeps exactly the old
    # behaviour, which is what made the split safe to add.
    assert data["tds_paise"] == 500000
    assert data["total_paise"] == 500000
    assert data["interest_paise"] == 0
    assert data["penalty_paise"] == 0
    assert data["minor_head"] == "200"
    assert data["payment_date"] == "2025-07-07"
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
    """IT Act §203 — certificates always start as status='pending' (the only
    CHECK-allowed "not yet issued" value — migration 037; 'draft' is NOT in
    the CHECK and was task #226's schema-drift bug). The CA-review-required
    signal is the frontend's own badge, not the stored status value."""
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
    assert data["status"] == "pending"
    # tds_amount_paise (request field) persists as tds_deducted_paise (real column).
    assert data["tds_deducted_paise"] == 100000
    assert data["section"] == "194C"


def test_return_approval_requires_manager_role(client):
    """IT Act §200/§203: only Manager+ can approve/file a TDS return —
    ca_approved=true alone is a caller-supplied flag, not proof of role
    (task #226 audit finding). An Executive gets rejected even with the flag
    set; a Manager succeeds."""
    exec_headers = {"X-User-Email": "exec@test.com", "X-User-Role": "executive", "X-Firm-ID": "firm-1"}
    manager_headers = {"X-User-Email": "mgr@test.com", "X-User-Role": "manager", "X-Firm-ID": "firm-1"}

    resp = client.post("/api/tds-workspace/returns", json={
        "client_id": _CLIENT_ID, "return_type": "26Q", "quarter": "Q1",
        "financial_year": "2025-26",
    }, headers=exec_headers)
    return_id = resp.json()["data"]["id"]

    r_exec = client.patch(f"/api/tds-workspace/returns/{return_id}/status",
                          json={"status": "ca_approved", "ca_approved": True},
                          headers=exec_headers)
    assert r_exec.json()["success"] is False
    assert "Manager" in r_exec.json()["error"]

    r_mgr = client.patch(f"/api/tds-workspace/returns/{return_id}/status",
                         json={"status": "ca_approved", "ca_approved": True},
                         headers=manager_headers)
    assert r_mgr.json()["success"] is True
    assert r_mgr.json()["data"]["status"] == "ca_approved"


def _seed_register(**over):
    """A row in the client's own TDS register.

    The register is READ by the reconciliation now (TDS-21); it used to be
    pasted into the request beside the 26AS extract, which is why this test
    supplied both sides and never touched the database.
    """
    from routers.tds_workspace import _MOCK_DEDUCTIONS
    import uuid as _uuid
    row = {"id": str(_uuid.uuid4()), "firm_id": "firm-1", "client_id": _CLIENT_ID,
           "deductee_name": "Vendor", "deductee_pan": "ABCDE1234F",
           "section": "194C", "tds_paise": 10000,
           "transaction_date": "2025-06-10", "financial_year": "2025-26"}
    row.update(over)
    _MOCK_DEDUCTIONS[row["id"]] = row
    return row


def test_the_reconciliation_finds_a_deduction_the_api_created(client):
    """The whole chain, not a seeded shortcut (TDS-21).

    A deduction recorded through POST /deductions must be the one the
    reconciliation reads. The register used to arrive in the request instead,
    so nothing anywhere asserted that the two halves of the product agree about
    what a deduction is.
    """
    made = client.post("/api/tds-workspace/deductions", headers=_HEADERS, json={
        "client_id": _CLIENT_ID, "deductee_name": "Sharma & Co",
        "deductee_pan": "ABCDE1234F", "section": "194J",
        "payment_amount_paise": 5_00_000_00, "transaction_date": "2025-06-10",
    })
    assert made.json()["success"] is True, made.json()
    tds_paise = made.json()["data"]["tds_paise"]
    assert tds_paise > 0, "the engine withheld nothing — the rest proves nothing"

    resp = client.post("/api/tds-workspace/form26as/upload", headers=_HEADERS, json={
        "client_id": _CLIENT_ID, "financial_year": "2025-26",
        "raw_data": {"tds_entries": [
            {"pan": "ABCDE1234F", "section": "194J", "amount_paise": tds_paise}]},
    })
    summary = resp.json()["data"]["reconciliation_result"]["summary"]
    assert summary["total_book"] == 1, (
        "the register was not read — the reconciliation is looking at nothing")
    assert summary["matched_count"] == 1
    assert summary["missing_count"] == 0 and summary["missing_in_books_count"] == 0


def test_a_register_row_with_no_financial_year_is_still_found(client):
    """The fallback guards no live path — all three writers set the column —
    and it stays because of the direction it fails in. A row this filter drops
    does not raise: it makes the register look SHORTER than it is, and a
    reconciliation over a short register reports a CLEAN result."""
    _seed_register(deductee_pan="ABCDE1234F", section="194C", tds_paise=10000,
                   financial_year=None, transaction_date="2025-06-10")
    resp = client.post("/api/tds-workspace/form26as/upload", headers=_HEADERS, json={
        "client_id": _CLIENT_ID, "financial_year": "2025-26",
        "raw_data": {"tds_entries": [
            {"pan": "ABCDE1234F", "section": "194C", "amount_paise": 10000}]},
    })
    summary = resp.json()["data"]["reconciliation_result"]["summary"]
    assert summary["total_book"] == 1, "the row vanished from the register"
    assert summary["matched_count"] == 1


def test_a_row_dated_outside_the_year_is_not_in_it(client):
    """The fallback must not become "everything matches everything"."""
    _seed_register(deductee_pan="ABCDE1234F", section="194C", tds_paise=10000,
                   financial_year=None, transaction_date="2024-06-10")
    resp = client.post("/api/tds-workspace/form26as/upload", headers=_HEADERS, json={
        "client_id": _CLIENT_ID, "financial_year": "2025-26",
        "raw_data": {"tds_entries": [
            {"pan": "ABCDE1234F", "section": "194C", "amount_paise": 10000}]},
    })
    summary = resp.json()["data"]["reconciliation_result"]["summary"]
    assert summary["total_book"] == 0
    assert summary["missing_in_books_count"] == 1


def test_a_book_side_in_the_request_is_ignored_and_said_so(client):
    """An older caller still pasting `book_deductions` must not silently get a
    different answer than it asked for."""
    _seed_register(deductee_pan="ABCDE1234F", section="194C", tds_paise=10000)
    resp = client.post("/api/tds-workspace/form26as/upload", headers=_HEADERS, json={
        "client_id": _CLIENT_ID, "financial_year": "2025-26",
        "raw_data": {
            "tds_entries": [{"pan": "ABCDE1234F", "section": "194C", "amount_paise": 10000}],
            "book_deductions": [{"deductee_pan": "ZZZZZ9999Z", "section": "194I",
                                 "amount_paise": 99999}],
        },
    })
    result = resp.json()["data"]["reconciliation_result"]
    assert result["summary"]["matched_count"] == 1, "the pasted side was used"
    assert result["summary"]["total_book"] == 1
    assert "book_deductions" in result["ignored_request_keys"]


def test_a_portal_row_the_register_lacks_reaches_the_response(client):
    """The bucket that did not exist. Nothing reported a 26AS row the client's
    own register has no deduction for."""
    resp = client.post("/api/tds-workspace/form26as/upload", headers=_HEADERS, json={
        "client_id": _CLIENT_ID, "financial_year": "2025-26",
        "raw_data": {"tds_entries": [
            {"pan": "ABCDE1234F", "section": "194C", "amount_paise": 10000}]},
    })
    result = resp.json()["data"]["reconciliation_result"]
    assert result["summary"]["missing_in_books_count"] == 1
    assert result["missing_in_books"][0]["key"] == ["ABCDE1234F", "194C"]


def test_form26as_reconciliation(client):
    """IT Act s.285BB — 26AS reconciliation: 2 deductions, 1 mismatch."""
    _seed_register(deductee_pan="ABCDE1234F", section="194C", tds_paise=10000)
    _seed_register(deductee_pan="FGHIJ5678K", section="194I", tds_paise=25000)
    body = {
        "client_id": _CLIENT_ID,
        "financial_year": "2025-26",
        "raw_data": {
            "tds_entries": [
                {"pan": "ABCDE1234F", "section": "194C", "amount_paise": 10000},
                {"pan": "FGHIJ5678K", "section": "194I", "amount_paise": 20000},
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
