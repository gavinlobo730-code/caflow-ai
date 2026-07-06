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

from routers.hsn import router as hsn_router, _pct_to_bps, _SAFE_Q, _rank_master_rows
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


# ── Relevance ranking (pure) ─────────────────────────────────────────────────

def _rows(*specs):
    """specs: (hsn_code, description, keywords) → master-shaped dicts."""
    return [{"hsn_code": c, "description": d, "keywords": k} for c, d, k in specs]


def test_rank_exact_code_wins():
    # Typing a full code surfaces that exact code above a prefix sibling.
    rows = _rows(
        ("998221", "Financial auditing services", None),
        ("9982",   "Legal and accounting services", None),
    )
    ranked = _rank_master_rows("998221", rows)
    assert ranked[0]["hsn_code"] == "998221"


def test_rank_code_prefix_before_description_match():
    # "9982" is a code prefix for 998221 but only a description match for the
    # goods row — the code-prefix hit ranks first.
    rows = _rows(
        ("8471", "Computers — data processing 9982 not really", "laptop"),
        ("998221", "Financial auditing services", None),
    )
    ranked = _rank_master_rows("9982", rows)
    assert ranked[0]["hsn_code"] == "998221"


def test_rank_description_search_matches_words_and_keywords():
    # A non-code term ranks description-prefix, then description/keyword substring.
    rows = _rows(
        ("9401", "Office chairs and furniture", "seating"),
        ("8471", "Computers, laptops and peripherals", "laptop notebook"),
    )
    # "laptop" hits only via keywords on 8471.
    ranked = _rank_master_rows("laptop", rows)
    assert ranked[0]["hsn_code"] == "8471"
    # "office" hits the description prefix on 9401.
    assert _rank_master_rows("office", rows)[0]["hsn_code"] == "9401"


def test_rank_no_result_is_stable_passthrough():
    # A term matching nothing keeps every row (endpoint's DB filter already
    # narrowed) in a deterministic order — never raises, never drops rows.
    rows = _rows(("8471", "Computers", None), ("9401", "Chairs", None))
    ranked = _rank_master_rows("zzz-nomatch", rows)
    assert {r["hsn_code"] for r in ranked} == {"8471", "9401"}
    assert _rank_master_rows("anything", []) == []


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


def test_type_filter_services_accepted():
    r = _client().get("/api/hsn/search?q=audit&type=services")
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_empty_query_with_client_scope_returns_envelope():
    # Empty q + client_id is the "recent codes" affordance — must stay a valid
    # envelope (empty in mock mode, recent history against a live DB).
    r = _client().get("/api/hsn/search?q=&client_id=client-xyz")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"] == []
    assert body["error"] is None
