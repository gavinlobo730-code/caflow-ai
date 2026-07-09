"""Firm HSN/SAC Rate History (Decision D) — CA-entered validity-dated rate
versions, resolution-as-a-hint, and the guardrails that keep this a
mechanism rather than a tax-determination engine.

Runs in mock mode (no SUPABASE_URL). `resolve_rate` (the pure resolution
helper) is asserted directly since it is the one piece of logic with real
correctness stakes; the endpoints are exercised through the mock store.
"""
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from routers.firm_hsn_rate_history import (
    router as rate_router,
    resolve_rate,
    MOCK_RATE_HISTORY,
)
from routers.firm_hsn_library import router as lib_router, MOCK_LIBRARY
from core.auth import get_current_user

USER = {"id": "u-1", "firm_id": "firm-rate-1", "role": "Partner"}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(rate_router)
    app.include_router(lib_router)
    app.dependency_overrides[get_current_user] = lambda: USER
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def clear_store():
    MOCK_RATE_HISTORY.clear()
    MOCK_LIBRARY.clear()
    yield
    MOCK_RATE_HISTORY.clear()
    MOCK_LIBRARY.clear()


def _add_library_code(client, hsn_code="998221"):
    r = client.post("/api/firm-hsn-library/", json={
        "hsn_code": hsn_code, "description": "Financial auditing services", "hsn_type": "services",
    })
    return r.json()["data"]["id"]


# ── Pure resolution (the only real logic here) ─────────────────────────────────

def test_resolve_picks_the_row_covering_the_date():
    rows = [
        {"effective_from": "2020-07-01", "effective_to": "2025-09-21", "gst_rate_pct": 12.0},
        {"effective_from": "2025-09-22", "effective_to": None, "gst_rate_pct": 18.0},
    ]
    assert resolve_rate(rows, date(2025, 6, 1))["gst_rate_pct"] == 12.0
    assert resolve_rate(rows, date(2025, 9, 22))["gst_rate_pct"] == 18.0
    assert resolve_rate(rows, date(2026, 1, 1))["gst_rate_pct"] == 18.0


def test_resolve_returns_none_before_any_recorded_rate():
    rows = [{"effective_from": "2025-01-01", "effective_to": None, "gst_rate_pct": 18.0}]
    assert resolve_rate(rows, date(2024, 1, 1)) is None


def test_resolve_on_overlap_prefers_most_recently_effective():
    # The router doesn't prevent overlapping CA-entered ranges (Decision D:
    # no automatic slab/overlap logic) — resolution just picks the newest.
    rows = [
        {"effective_from": "2025-01-01", "effective_to": "2025-12-31", "gst_rate_pct": 12.0},
        {"effective_from": "2025-06-01", "effective_to": None, "gst_rate_pct": 18.0},
    ]
    assert resolve_rate(rows, date(2025, 7, 1))["gst_rate_pct"] == 18.0


def test_resolve_empty_history_returns_none():
    assert resolve_rate([], date(2025, 1, 1)) is None


# ── Endpoint: add + list + resolve ─────────────────────────────────────────────

def test_add_and_list_history(client):
    lid = _add_library_code(client)
    r = client.post("/api/firm-hsn-rate-history/", json={
        "firm_hsn_library_id": lid, "gst_rate_pct": 18.0,
        "effective_from": "2025-09-22", "notes": "GST 2.0",
    })
    assert r.json()["success"] is True
    lst = client.get(f"/api/firm-hsn-rate-history/?firm_hsn_library_id={lid}").json()["data"]
    assert len(lst) == 1
    assert lst[0]["gst_rate_pct"] == 18.0


def test_add_rejects_a_code_not_in_the_callers_library(client):
    r = client.post("/api/firm-hsn-rate-history/", json={
        "firm_hsn_library_id": "nonexistent", "gst_rate_pct": 18.0,
        "effective_from": "2025-09-22",
    })
    assert r.status_code == 404
    assert client.get("/api/firm-hsn-rate-history/?firm_hsn_library_id=nonexistent").json()["data"] == []


def test_resolve_endpoint_returns_pre_fill_hint(client):
    lid = _add_library_code(client)
    client.post("/api/firm-hsn-rate-history/", json={
        "firm_hsn_library_id": lid, "gst_rate_pct": 12.0,
        "effective_from": "2020-07-01", "effective_to": "2025-09-21",
    })
    client.post("/api/firm-hsn-rate-history/", json={
        "firm_hsn_library_id": lid, "gst_rate_pct": 18.0,
        "effective_from": "2025-09-22",
    })
    r = client.get(f"/api/firm-hsn-rate-history/resolve?firm_hsn_library_id={lid}&as_of=2026-01-01")
    assert r.json()["data"]["gst_rate_pct"] == 18.0

    r_old = client.get(f"/api/firm-hsn-rate-history/resolve?firm_hsn_library_id={lid}&as_of=2021-01-01")
    assert r_old.json()["data"]["gst_rate_pct"] == 12.0


def test_resolve_with_no_history_returns_null_hint_not_an_error(client):
    lid = _add_library_code(client)
    r = client.get(f"/api/firm-hsn-rate-history/resolve?firm_hsn_library_id={lid}&as_of=2026-01-01")
    assert r.json()["success"] is True
    assert r.json()["data"] is None


# ── Validation (CA-entered, never auto-computed) ───────────────────────────────

def test_rejects_rate_out_of_range(client):
    lid = _add_library_code(client)
    r = client.post("/api/firm-hsn-rate-history/", json={
        "firm_hsn_library_id": lid, "gst_rate_pct": 150.0, "effective_from": "2025-09-22",
    })
    assert r.status_code == 422


def test_rejects_effective_to_before_effective_from(client):
    lid = _add_library_code(client)
    r = client.post("/api/firm-hsn-rate-history/", json={
        "firm_hsn_library_id": lid, "gst_rate_pct": 18.0,
        "effective_from": "2025-09-22", "effective_to": "2025-01-01",
    })
    assert r.status_code == 422


def test_rejects_invalid_supply_type(client):
    lid = _add_library_code(client)
    r = client.post("/api/firm-hsn-rate-history/", json={
        "firm_hsn_library_id": lid, "gst_rate_pct": 18.0,
        "effective_from": "2025-09-22", "supply_type": "wrong",
    })
    assert r.status_code == 422


def test_delete_removes_a_mistaken_entry(client):
    lid = _add_library_code(client)
    hid = client.post("/api/firm-hsn-rate-history/", json={
        "firm_hsn_library_id": lid, "gst_rate_pct": 18.0, "effective_from": "2025-09-22",
    }).json()["data"]["id"]
    client.delete(f"/api/firm-hsn-rate-history/{hid}")
    assert client.get(f"/api/firm-hsn-rate-history/?firm_hsn_library_id={lid}").json()["data"] == []
