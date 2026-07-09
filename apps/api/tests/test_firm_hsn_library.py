"""Firm HSN/SAC Library — CRUD, retire/restore (never hard-delete), search,
ranking, format validation. Runs in mock mode (no SUPABASE_URL): the router
keeps an in-memory store so the full lifecycle is exercised without a live
DB, mirroring test_service_catalogue-style coverage.

HSN/SAC redesign guardrail: this router never reads `hsn_master` — every
result is exactly what the firm itself added. These tests also assert firm
isolation (a second firm never sees another firm's library).
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from routers.firm_hsn_library import router as lib_router, _rank_library, MOCK_LIBRARY
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
def clear_store():
    MOCK_LIBRARY.clear()
    yield
    MOCK_LIBRARY.clear()


def _add(client, **over):
    body = {
        "hsn_code": "998221", "description": "Financial auditing services",
        "hsn_type": "services", "gst_rate_pct": 18.0, "uqc": "OTH", **over,
    }
    return client.post("/api/firm-hsn-library/", json=body)


# ── Pure ranking ──────────────────────────────────────────────────────────────

def _rows(*specs):
    return [{"hsn_code": c, "description": d, "gst_rate_pct": None} for c, d in specs]


def test_rank_exact_code_then_prefix_then_description():
    rows = _rows(("998221", "Financial auditing services"), ("9982", "Legal and accounting services"))
    assert _rank_library("998221", rows)[0]["hsn_code"] == "998221"


def test_rank_no_match_keeps_all_rows_stable():
    rows = _rows(("8471", "Computers"), ("9401", "Chairs"))
    assert [r["hsn_code"] for r in _rank_library("zzz", rows)] == ["8471", "9401"]
    assert _rank_library("x", []) == []


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_add_and_list(client):
    r = _add(client)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["hsn_code"] == "998221"
    assert data["is_active"] is True
    assert data["source"] == "manual"
    lst = client.get("/api/firm-hsn-library/").json()["data"]
    assert len(lst) == 1


def test_import_source_accepted(client):
    r = _add(client, source="import")
    assert r.json()["data"]["source"] == "import"


def test_edit_code(client):
    lid = _add(client).json()["data"]["id"]
    r = client.patch(f"/api/firm-hsn-library/{lid}", json={"gst_rate_pct": 12.0})
    assert r.json()["data"]["gst_rate_pct"] == 12.0


def test_hsn_code_is_immutable_via_update_model(client):
    # FirmHsnLibraryUpdateIn has no hsn_code/hsn_type fields at all, so a
    # PATCH attempting to change them is silently ignored (extra fields
    # dropped by Pydantic) rather than mutating the code's identity.
    lid = _add(client).json()["data"]["id"]
    client.patch(f"/api/firm-hsn-library/{lid}", json={"hsn_code": "999999", "description": "still valid"})
    row = client.get("/api/firm-hsn-library/").json()["data"][0]
    assert row["hsn_code"] == "998221"
    assert row["description"] == "still valid"


# ── Validation ──────────────────────────────────────────────────────────────

def test_rejects_non_digit_code(client):
    assert _add(client, hsn_code="98A221").status_code == 422


def test_rejects_blank_description(client):
    assert _add(client, description="   ").status_code == 422


def test_rejects_invalid_hsn_type(client):
    assert _add(client, hsn_type="widgets").status_code == 422


def test_rejects_rate_out_of_range(client):
    assert _add(client, gst_rate_pct=150).status_code == 422


def test_accepts_goods_code_without_rate(client):
    # Chapter/heading-level codes legitimately have no single rate.
    r = _add(client, hsn_code="84", description="Machinery", hsn_type="goods", gst_rate_pct=None)
    assert r.json()["data"]["gst_rate_pct"] is None


# ── Retire, don't delete ──────────────────────────────────────────────────────

def test_retire_hides_then_restore_shows(client):
    lid = _add(client).json()["data"]["id"]
    client.delete(f"/api/firm-hsn-library/{lid}")
    assert client.get("/api/firm-hsn-library/").json()["data"] == []
    assert len(client.get("/api/firm-hsn-library/?include_archived=true").json()["data"]) == 1
    client.patch(f"/api/firm-hsn-library/{lid}", json={"is_active": True})
    assert len(client.get("/api/firm-hsn-library/").json()["data"]) == 1


def test_readding_a_retired_code_reactivates_not_duplicates(client):
    lid = _add(client).json()["data"]["id"]
    client.delete(f"/api/firm-hsn-library/{lid}")
    again = _add(client, description="Financial auditing services (updated)")
    assert again.json()["data"]["id"] == lid
    assert again.json()["data"]["is_active"] is True
    assert len(client.get("/api/firm-hsn-library/").json()["data"]) == 1


def test_readding_an_active_code_returns_duplicate_flag(client):
    _add(client)
    again = _add(client)
    assert again.json()["data"].get("duplicate") is True
    assert len(client.get("/api/firm-hsn-library/").json()["data"]) == 1


# ── Search + type filter ───────────────────────────────────────────────────────

def test_search_by_code_and_description(client):
    _add(client, hsn_code="998221", description="Financial auditing services")
    _add(client, hsn_code="998231", description="Corporate tax consulting")
    assert [r["hsn_code"] for r in client.get("/api/firm-hsn-library/?q=tax").json()["data"]] == ["998231"]
    assert [r["hsn_code"] for r in client.get("/api/firm-hsn-library/?q=998221").json()["data"]] == ["998221"]


def test_type_filter(client):
    _add(client, hsn_code="998221", hsn_type="services")
    _add(client, hsn_code="8471", description="Computers", hsn_type="goods")
    goods = client.get("/api/firm-hsn-library/?hsn_type=goods").json()["data"]
    assert [r["hsn_code"] for r in goods] == ["8471"]


# ── Firm isolation ─────────────────────────────────────────────────────────────

def test_firm_isolation(client):
    _add(client, hsn_code="998221")
    other = _client_as(OTHER_FIRM_USER)
    assert other.get("/api/firm-hsn-library/").json()["data"] == []
    other.post("/api/firm-hsn-library/", json={
        "hsn_code": "998231", "description": "Tax consulting", "hsn_type": "services",
    })
    # Each firm sees only its own rows.
    assert len(client.get("/api/firm-hsn-library/").json()["data"]) == 1
    assert len(other.get("/api/firm-hsn-library/").json()["data"]) == 1
