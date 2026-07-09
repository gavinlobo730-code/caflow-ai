"""HSN/SAC smart-lookup endpoint (GET /api/hsn/search).

Pure helpers (rate conversion, query sanitisation, ranking) are asserted
directly; the endpoint is exercised through a throwaway app (get_current_user
overridden), mirroring test_search.py. Tests run in mock mode (no
SUPABASE_URL), where the endpoint returns an empty list — so the
response-shape/envelope contract and the CA-safety guarantees (never errors,
always {success, data, error}) are verified without a live DB.

Architecture note (HSN/SAC redesign): this endpoint now sources its second
tier from `firm_hsn_library` (a firm's own curated codes), not the retired
`hsn_master` global list — see routers/hsn.py's module docstring. Library
rows have no `keywords` column (unlike the old master), so ranking is
code/description only.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.hsn import router as hsn_router, _pct_to_bps, _SAFE_Q, _rank_library_rows
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
    """specs: (hsn_code, description) or, to also exercise the has-a-rate
    tie-break, (hsn_code, description, gst_rate_pct) → firm_hsn_library-shaped
    dicts. Rate defaults to None."""
    out = []
    for spec in specs:
        c, d, *rest = spec
        out.append({"hsn_code": c, "description": d, "gst_rate_pct": rest[0] if rest else None})
    return out


def test_rank_exact_code_wins():
    # Typing a full code surfaces that exact code above a prefix sibling.
    rows = _rows(
        ("998221", "Financial auditing services"),
        ("9982",   "Legal and accounting services"),
    )
    ranked = _rank_library_rows("998221", rows)
    assert ranked[0]["hsn_code"] == "998221"


def test_rank_code_prefix_before_description_match():
    # "9982" is a code prefix for 998221 but only a description match for the
    # goods row — the code-prefix hit ranks first.
    rows = _rows(
        ("8471", "Computers — data processing 9982 not really"),
        ("998221", "Financial auditing services"),
    )
    ranked = _rank_library_rows("9982", rows)
    assert ranked[0]["hsn_code"] == "998221"


def test_rank_description_prefix_before_substring():
    # A description-PREFIX match ("office" leads "Office chairs...") ranks
    # above a same-term hit buried mid-description elsewhere.
    rows = _rows(
        ("9403", "Furniture parts including an office desk accessory"),
        ("9401", "Office chairs and furniture"),
    )
    ranked = _rank_library_rows("office", rows)
    assert ranked[0]["hsn_code"] == "9401"


def test_rank_prefers_a_rated_leaf_over_a_rateless_group_on_a_tie():
    # Two rows in the SAME bucket (both match only via description substring)
    # — the specific, billable code (has a GST rate hint) must rank above a
    # broader code with no rate set (e.g. a chapter/group-level entry a firm
    # added for prefix search but never bills against directly).
    tied = _rows(
        ("49", "Accounting adjacent printed bookkeeping ledger stationery"),
        ("998222", "Accounting and bookkeeping services", 18.00),
    )
    ranked = _rank_library_rows("bookkeeping", tied)
    assert ranked[0]["hsn_code"] == "998222"


def test_rank_no_result_is_stable_passthrough():
    # A term matching nothing keeps every row (endpoint's DB filter already
    # narrowed) in a deterministic order — never raises, never drops rows.
    rows = _rows(("8471", "Computers"), ("9401", "Chairs"))
    ranked = _rank_library_rows("zzz-nomatch", rows)
    assert {r["hsn_code"] for r in ranked} == {"8471", "9401"}
    assert _rank_library_rows("anything", []) == []


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
