"""HSN/SAC smart-lookup endpoint (GET /api/hsn/search).

Pure helpers (rate conversion, query sanitisation) are asserted directly; the
endpoint is exercised through a throwaway app (get_current_user overridden),
mirroring test_search.py. Tests run in mock mode (no SUPABASE_URL), where the
endpoint returns an empty list — so the response-shape/envelope contract and the
CA-safety guarantees (never errors, always {success, data, error}) are verified
without a live DB. The pure helpers cover the merge/rate logic.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.hsn import router as hsn_router, _pct_to_bps, _SAFE_Q
from core.auth import get_current_user

USER = {"id": "u-hsn-1", "firm_id": "firm-hsn-0001", "role": "Partner"}


def _client():
    app = FastAPI()
    app.include_router(hsn_router)
    app.dependency_overrides[get_current_user] = lambda: USER
    return TestClient(app, raise_server_exceptions=False)


# ── Pure helpers ─────────────────────────────────────────────────────────────

def test_pct_to_bps_converts_percent_to_integer_basis_points():
    # 18% → 1800 bps; integer bps mirrors the history table's gst_rate_bps.
    assert _pct_to_bps(18.00) == 1800
    assert _pct_to_bps(3.00) == 300
    assert _pct_to_bps(0.00) == 0
    assert _pct_to_bps(12.5) == 1250


def test_pct_to_bps_null_rate_stays_none():
    # NULL gst_rate_pct (multiple/again-review rates) must not become 0.
    assert _pct_to_bps(None) is None
    assert _pct_to_bps("nonsense") is None


def test_safe_query_strips_filter_breaking_chars():
    # Commas/parens/dots would break the PostgREST or() string; only
    # alphanumerics + space survive.
    assert _SAFE_Q.sub(" ", "998,314(x)").strip() == "998 314 x"
    # '&' → space; surrounding spaces are kept (harmless collapse not required).
    assert "," not in _SAFE_Q.sub(" ", "audit & tax, co.")
    assert "(" not in _SAFE_Q.sub(" ", "leasing (other)")


# ── Endpoint contract (mock mode) ────────────────────────────────────────────

def test_search_returns_envelope_and_empty_in_mock():
    r = _client().get("/api/hsn/search?q=998")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"] == []
    assert body["error"] is None


def test_blank_query_returns_empty():
    r = _client().get("/api/hsn/search?q=%20%20")
    assert r.status_code == 200
    assert r.json()["data"] == []


def test_type_filter_accepted():
    # 'type' is an optional goods/services filter — must not 422.
    r = _client().get("/api/hsn/search?q=chair&type=goods")
    assert r.status_code == 200
    assert r.json()["success"] is True
