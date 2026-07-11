"""Firm HSN/SAC Library — permanent delete (purge_code / bulk_purge_codes).

firm_hsn_library carries no live foreign key from anywhere else (every
consumer snapshots the hsn_sac string at pick time), so a real delete never
orphans a row technically — but a code that HAS been used is still blocked,
to preserve it as an audit trail, checked by string match across every place
a code can be picked from. Mirrors service_catalogue.py's delete_service
guard test style; runs in mock mode (no SUPABASE_URL).
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from routers.firm_hsn_library import router as lib_router, MOCK_LIBRARY
from routers.service_catalogue import MOCK_SERVICES
from routers.sales_invoices import MOCK_SALES_INVOICE_LINES
from routers.credit_notes import MOCK_CREDIT_NOTE_LINES
from routers.debit_notes import MOCK_DEBIT_NOTE_LINES
from routers.purchase_bills import MOCK_PURCHASE_BILL_LINES
from core.auth import get_current_user

USER = {"id": "u-1", "firm_id": "firm-lib-1", "role": "Partner"}
OTHER_FIRM_USER = {"id": "u-2", "firm_id": "firm-lib-2", "role": "Partner"}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(lib_router)
    app.dependency_overrides[get_current_user] = lambda: USER
    return TestClient(app, raise_server_exceptions=False)


def _client_as(user):
    app = FastAPI()
    app.include_router(lib_router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def clear_stores():
    for store in (MOCK_LIBRARY, MOCK_SERVICES, MOCK_SALES_INVOICE_LINES,
                  MOCK_CREDIT_NOTE_LINES, MOCK_DEBIT_NOTE_LINES, MOCK_PURCHASE_BILL_LINES):
        store.clear()
    yield
    for store in (MOCK_LIBRARY, MOCK_SERVICES, MOCK_SALES_INVOICE_LINES,
                  MOCK_CREDIT_NOTE_LINES, MOCK_DEBIT_NOTE_LINES, MOCK_PURCHASE_BILL_LINES):
        store.clear()


def _add(client, **over):
    body = {
        "hsn_code": "998221", "description": "Financial auditing services",
        "hsn_type": "services", "gst_rate_pct": 18.0, "uqc": "OTH", **over,
    }
    return client.post("/api/firm-hsn-library/", json=body)


# ── Unused code — purge succeeds ─────────────────────────────────────────────

def test_purge_unused_code_removes_it(client):
    lid = _add(client).json()["data"]["id"]
    r = client.delete(f"/api/firm-hsn-library/{lid}/purge")
    assert r.json()["success"] is True
    assert client.get("/api/firm-hsn-library/?include_archived=true").json()["data"] == []


def test_purge_missing_code_404s(client):
    r = client.delete("/api/firm-hsn-library/does-not-exist/purge")
    assert r.status_code == 404


def test_purge_unused_retired_code_still_works(client):
    # No restriction to Archived-only — a retired code with zero usage can
    # also be purged directly.
    lid = _add(client).json()["data"]["id"]
    client.delete(f"/api/firm-hsn-library/{lid}")  # retire first
    r = client.delete(f"/api/firm-hsn-library/{lid}/purge")
    assert r.json()["success"] is True


# ── Used code — blocked, per source ──────────────────────────────────────────

def test_purge_blocked_when_used_on_product_service(client):
    lid = _add(client).json()["data"]["id"]
    MOCK_SERVICES.append({"id": "svc-1", "firm_id": "firm-lib-1", "hsn_sac": "998221"})
    r = client.delete(f"/api/firm-hsn-library/{lid}/purge")
    assert r.json()["success"] is False
    assert "Product/Service catalogue" in r.json()["error"]
    # Never removed.
    assert len(client.get("/api/firm-hsn-library/?include_archived=true").json()["data"]) == 1


def test_purge_blocked_when_used_on_sales_invoice_line(client):
    lid = _add(client).json()["data"]["id"]
    MOCK_SALES_INVOICE_LINES.append({"id": "ln-1", "invoice_id": "inv-1", "hsn_sac": "998221"})
    r = client.delete(f"/api/firm-hsn-library/{lid}/purge")
    assert r.json()["success"] is False
    assert "sales invoice" in r.json()["error"]


def test_purge_blocked_when_used_on_credit_note_line(client):
    lid = _add(client).json()["data"]["id"]
    MOCK_CREDIT_NOTE_LINES.append({"id": "cnl-1", "credit_note_id": "cn-1", "hsn_sac": "998221"})
    r = client.delete(f"/api/firm-hsn-library/{lid}/purge")
    assert r.json()["success"] is False
    assert "credit note" in r.json()["error"]


def test_purge_blocked_when_used_on_debit_note_line(client):
    lid = _add(client).json()["data"]["id"]
    MOCK_DEBIT_NOTE_LINES.append({"id": "dnl-1", "debit_note_id": "dn-1", "hsn_sac": "998221"})
    r = client.delete(f"/api/firm-hsn-library/{lid}/purge")
    assert r.json()["success"] is False
    assert "debit note" in r.json()["error"]


def test_purge_blocked_when_used_on_purchase_bill_line(client):
    lid = _add(client).json()["data"]["id"]
    MOCK_PURCHASE_BILL_LINES.append({"id": "pbl-1", "bill_id": "pb-1", "hsn_sac": "998221"})
    r = client.delete(f"/api/firm-hsn-library/{lid}/purge")
    assert r.json()["success"] is False
    assert "purchase bill" in r.json()["error"]


def test_purge_usage_check_is_scoped_to_the_code_itself(client):
    # A different code's usage doesn't block this one.
    lid = _add(client, hsn_code="998221").json()["data"]["id"]
    MOCK_SERVICES.append({"id": "svc-1", "firm_id": "firm-lib-1", "hsn_sac": "998231"})
    r = client.delete(f"/api/firm-hsn-library/{lid}/purge")
    assert r.json()["success"] is True


# ── Bulk purge ────────────────────────────────────────────────────────────────

def test_bulk_purge_deletes_unused_and_blocks_used(client):
    unused_id = _add(client, hsn_code="998221").json()["data"]["id"]
    used_id = _add(client, hsn_code="998231", description="Corporate tax consulting").json()["data"]["id"]
    MOCK_SERVICES.append({"id": "svc-1", "firm_id": "firm-lib-1", "hsn_sac": "998231"})

    r = client.post("/api/firm-hsn-library/bulk-delete", json={"ids": [unused_id, used_id]})
    body = r.json()["data"]
    assert body["deleted"] == [unused_id]
    assert len(body["blocked"]) == 1
    assert body["blocked"][0]["id"] == used_id
    assert body["blocked"][0]["used_in"] == ["your Product/Service catalogue"]

    remaining = client.get("/api/firm-hsn-library/?include_archived=true").json()["data"]
    assert [r["id"] for r in remaining] == [used_id]


def test_bulk_purge_empty_ids_is_a_noop(client):
    r = client.post("/api/firm-hsn-library/bulk-delete", json={"ids": []})
    assert r.json()["data"] == {"deleted": [], "blocked": []}


# ── Firm isolation ─────────────────────────────────────────────────────────────

def test_purge_respects_firm_isolation(client):
    lid = _add(client).json()["data"]["id"]
    other = _client_as(OTHER_FIRM_USER)
    r = other.delete(f"/api/firm-hsn-library/{lid}/purge")
    assert r.status_code == 404
    # Untouched from the owning firm's side.
    assert len(client.get("/api/firm-hsn-library/?include_archived=true").json()["data"]) == 1


def test_bulk_purge_respects_firm_isolation(client):
    lid = _add(client).json()["data"]["id"]
    other = _client_as(OTHER_FIRM_USER)
    r = other.post("/api/firm-hsn-library/bulk-delete", json={"ids": [lid]})
    assert r.json()["data"] == {"deleted": [], "blocked": []}
    assert len(client.get("/api/firm-hsn-library/?include_archived=true").json()["data"]) == 1
