"""Tests for Pre-Phase 4 Hardening Sprint — P0 fixes, pagination, period validation."""
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
HEADERS = {"X-User-Role": "partner", "X-Firm-Id": "firm-001", "X-User-Id": "user-001"}
MANAGER_HEADERS = {"X-User-Role": "manager", "X-Firm-Id": "firm-001", "X-User-Id": "user-002"}
EXEC_HEADERS = {"X-User-Role": "executive", "X-Firm-Id": "firm-001", "X-User-Id": "user-003"}


def test_tds_challan_requires_challan_date():
    """P0-2: TDS challan creation requires challan_date field."""
    resp = client.post("/api/tds-workspace/challans", json={
        "client_id": "client-001",
        "customer_id": "customer-001",
        "bsr_code": "0001234",
        "section": "194C",
        "amount_paise": 100000,
        # missing challan_date intentionally
    }, headers=HEADERS)
    assert resp.status_code == 422


def test_tds_challan_period_validation_accepts_valid_date():
    """P0-2: TDS challan with valid date should succeed."""
    resp = client.post("/api/tds-workspace/challans", json={
        "client_id": "client-001",
        "bsr_code": "0001234",
        "challan_date": "2025-07-10",
        "section": "194C",
        "amount_paise": 100000,
        "challan_no": "CHALLAN001",
        "financial_year": "2025-26",
        "quarter": "Q1",
    }, headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


def test_tds_return_period_validation():
    """P0-2: TDS return creation validates FY period."""
    resp = client.post("/api/tds-workspace/returns", json={
        "client_id": "client-001",
        "return_type": "26Q",
        "fy": "2025-26",
        "quarter": "Q1",
        "financial_year": "2025-26",
    }, headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


def test_gstr9_save():
    """P3: GSTR-9 save endpoint creates draft record."""
    resp = client.post("/api/gst-workspace/gstr9", json={
        "client_id": "client-001",
        "financial_year": "2025-26",
        "gstin": "27AABCU9603R1ZX",
        "total_taxable_paise": 1000000,
        "total_tax_paise": 180000,
    }, headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["return_type"] == "gstr9"
    assert data["data"]["status"] == "draft"


def test_mca_filing_status_filed_requires_manager():
    """P3: Only Manager+ can mark MCA filings as filed."""
    # Create a filing first
    create_resp = client.post("/api/mca-workspace/filings", json={
        "client_id": "client-001",
        "form_type": "AOC-4",
        "financial_year": "2025-26",
        "company_name": "Test Co",
    }, headers=HEADERS)
    assert create_resp.status_code == 200
    filing_id = create_resp.json()["data"]["id"]

    # Executive should NOT be able to mark as filed
    exec_resp = client.patch(f"/api/mca-workspace/filings/{filing_id}/status",
        json={"status": "filed", "ca_approved": True}, headers=EXEC_HEADERS)
    assert exec_resp.status_code == 403

    # Manager should be able to mark as filed
    mgr_resp = client.patch(f"/api/mca-workspace/filings/{filing_id}/status",
        json={"status": "filed", "ca_approved": True}, headers=MANAGER_HEADERS)
    assert mgr_resp.status_code == 200


def test_sales_invoice_list_pagination():
    """P4: Sales invoice list supports limit/offset."""
    resp = client.get("/api/sales-invoices/?client_id=client-001&limit=5&offset=0", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_notices_list_pagination():
    """P4: Government notices list supports pagination."""
    resp = client.get("/api/document-intelligence-v2/notices?client_id=client-001&limit=10&offset=0", headers=HEADERS)
    assert resp.status_code == 200


def test_receipts_list_date_filter():
    """P4: Receipts list supports date range filter."""
    resp = client.get(
        "/api/receipts/?client_id=client-001&from_date=2025-04-01&to_date=2026-03-31",
        headers=HEADERS
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_mca_approval_permission_exists():
    """P3: MCA approve permission is defined in RBAC."""
    from core.permissions import can
    assert can("partner", "mca", "approve") is True
    assert can("manager", "mca", "approve") is True
    assert can("executive", "mca", "approve") is False
