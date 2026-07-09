"""Product & Service master — CRUD, archive/restore, duplicate prevention,
search, ranking, validation. Runs in mock mode (no SUPABASE_URL): the router
keeps an in-memory store so the full lifecycle is exercised without a live
DB, mirroring test_customers-style coverage. Pure ranking is asserted
directly.

Batch 6 guardrail, still enforced after the HSN/SAC redesign broadened this
from services-only to goods+services: these tests assert that no
stock/inventory concept exists on a row.

HSN/SAC redesign (Decision C): `hsn_sac` must be a code already in the
firm's own `firm_hsn_library` — `_seed_hsn` below seeds that library in mock
mode so existing tests keep working, and a dedicated section tests the
rejection path.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from routers.service_catalogue import router as sc_router, _rank_services, MOCK_SERVICES
from routers.firm_hsn_library import MOCK_LIBRARY
from core.auth import get_current_user

USER = {"id": "u-1", "firm_id": "firm-sc-1", "role": "Partner"}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(sc_router)
    app.dependency_overrides[get_current_user] = lambda: USER
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def clear_store():
    MOCK_SERVICES.clear()
    MOCK_LIBRARY.clear()
    yield
    MOCK_SERVICES.clear()
    MOCK_LIBRARY.clear()


def _seed_hsn(hsn_code: str, hsn_type: str = "services", firm_id: str = USER["firm_id"]):
    """Seed an active firm_hsn_library row so a product/service test can
    legally reference `hsn_code` (Decision C: HSN/SAC only from the firm's
    own library)."""
    MOCK_LIBRARY.append({
        "id": f"lib-{hsn_code}", "firm_id": firm_id, "hsn_code": hsn_code,
        "description": "seeded for test", "hsn_type": hsn_type,
        "gst_rate_pct": 18.0, "is_active": True, "source": "manual",
    })


def _create(client, **over):
    hsn = over.get("hsn_sac", "998221")
    if hsn:
        _seed_hsn(hsn)
    body = {
        "name": "Statutory Audit", "description": "Statutory audit FY 2025-26",
        "hsn_sac": "998221", "gst_rate_bps": 1800, "default_rate_paise": 5000000,
        "unit": "OTH", **over,
    }
    return client.post("/api/service-catalogue/", json=body)


# ── Pure ranking ──────────────────────────────────────────────────────────────

def _rows(*names):
    return [{"name": n, "description": "", "notes": "", "hsn_sac": ""} for n in names]


def test_rank_exact_name_then_prefix_then_substring():
    rows = _rows("Tax Audit", "Audit of accounts", "Statutory Audit")
    ranked = [r["name"] for r in _rank_services("audit", rows)]
    # "Audit of accounts" is a name prefix for 'audit'; the others are substrings.
    assert ranked[0] == "Audit of accounts"


def test_rank_hsn_and_description_match():
    rows = [
        {"name": "GST Filing", "description": "monthly returns", "notes": "", "hsn_sac": "998231"},
        {"name": "Bookkeeping", "description": "ledgers", "notes": "", "hsn_sac": "998222"},
    ]
    assert _rank_services("998231", rows)[0]["name"] == "GST Filing"       # hsn prefix
    assert _rank_services("ledgers", rows)[0]["name"] == "Bookkeeping"     # description substring


def test_rank_no_match_keeps_all_rows_stable():
    rows = _rows("Alpha", "Beta")
    ranked = _rank_services("zzz", rows)
    assert [r["name"] for r in ranked] == ["Alpha", "Beta"]
    assert _rank_services("x", []) == []


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_create_and_list(client):
    r = _create(client)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["name"] == "Statutory Audit"
    assert data["is_active"] is True
    assert data["default_rate_paise"] == 5000000
    # No inventory concept ever leaks onto a service row.
    for banned in ("stock", "quantity_on_hand", "valuation", "warehouse", "reorder"):
        assert banned not in data
    lst = client.get("/api/service-catalogue/").json()["data"]
    assert len(lst) == 1


def test_edit_service(client):
    sid = _create(client).json()["data"]["id"]
    r = client.patch(f"/api/service-catalogue/{sid}", json={"default_rate_paise": 7500000})
    assert r.json()["data"]["default_rate_paise"] == 7500000


def test_validation_blank_name_and_negative_rate(client):
    assert _create(client, name="   ").status_code == 422
    assert _create(client, default_rate_paise=-1).status_code == 422
    assert _create(client, gst_rate_bps=20000).status_code == 422


# ── Duplicate prevention ──────────────────────────────────────────────────────

def test_duplicate_active_name_blocked(client):
    _create(client, name="GST Filing")
    dup = _create(client, name="  gst   filing ")  # case/space-insensitive
    body = dup.json()["data"]
    assert body.get("duplicate") is True
    assert len([s for s in client.get("/api/service-catalogue/").json()["data"]]) == 1


# ── Archive / restore ─────────────────────────────────────────────────────────

def test_archive_hides_then_restore_shows(client):
    sid = _create(client, name="One-time Advisory").json()["data"]["id"]
    client.patch(f"/api/service-catalogue/{sid}", json={"is_active": False})
    # Archived is hidden by default…
    assert client.get("/api/service-catalogue/").json()["data"] == []
    # …but visible with include_archived, and restorable.
    assert len(client.get("/api/service-catalogue/?include_archived=true").json()["data"]) == 1
    client.patch(f"/api/service-catalogue/{sid}", json={"is_active": True})
    assert len(client.get("/api/service-catalogue/").json()["data"]) == 1


def test_archived_name_can_be_reused(client):
    sid = _create(client, name="Seasonal Package").json()["data"]["id"]
    client.patch(f"/api/service-catalogue/{sid}", json={"is_active": False})
    again = _create(client, name="Seasonal Package")  # not a duplicate — old one archived
    assert again.json()["data"].get("duplicate") is not True


# ── Search + ranking + usage bump ─────────────────────────────────────────────

def test_search_by_name_and_hsn(client):
    _create(client, name="Statutory Audit", hsn_sac="998221")
    _create(client, name="GST Filing", hsn_sac="998231")
    assert [s["name"] for s in client.get("/api/service-catalogue/?q=gst").json()["data"]] == ["GST Filing"]
    assert [s["name"] for s in client.get("/api/service-catalogue/?q=998221").json()["data"]] == ["Statutory Audit"]
    assert client.get("/api/service-catalogue/?q=nothingmatches").json()["data"] == []


def test_used_bump_ranks_recent_first(client):
    a = _create(client, name="Service A").json()["data"]["id"]
    b = _create(client, name="Service B").json()["data"]["id"]
    client.post(f"/api/service-catalogue/{b}/used")
    # Empty query = recent/frequent list; the just-used one leads.
    names = [s["name"] for s in client.get("/api/service-catalogue/").json()["data"]]
    assert names[0] == "Service B"
    assert client.post(f"/api/service-catalogue/{a}/used").json()["data"]["use_count"] == 1


# ── Product & Service master fields (HSN/SAC redesign, Decision B) ────────────

def test_defaults_to_service_kind(client):
    assert _create(client).json()["data"]["kind"] == "service"


def test_kind_accepts_good(client):
    _seed_hsn("2202", hsn_type="goods")
    r = _create(client, name="Bottled Water", kind="good", hsn_sac="2202")
    assert r.json()["data"]["kind"] == "good"


def test_kind_rejects_invalid_value(client):
    assert _create(client, kind="widget").status_code == 422


def test_purchase_price_and_category_are_optional_and_stored(client):
    r = _create(client, purchase_price_paise=250000, category="Compliance")
    data = r.json()["data"]
    assert data["purchase_price_paise"] == 250000
    assert data["category"] == "Compliance"


def test_purchase_price_negative_rejected(client):
    assert _create(client, purchase_price_paise=-1).status_code == 422


def test_still_no_inventory_fields_with_goods_kind(client):
    _seed_hsn("2202", hsn_type="goods")
    data = _create(client, name="Bottled Water", kind="good", hsn_sac="2202").json()["data"]
    for banned in ("sku", "barcode", "stock", "quantity_on_hand", "valuation", "warehouse"):
        assert banned not in data


# ── HSN/SAC must come from the firm's library (Decision C) ────────────────────

def test_hsn_not_in_library_is_rejected(client):
    # No _seed_hsn call — "997199" was never added to this firm's library.
    r = client.post("/api/service-catalogue/", json={
        "name": "Unlisted Service", "hsn_sac": "997199",
        "gst_rate_bps": 1800, "default_rate_paise": 1000,
    })
    body = r.json()
    assert body["success"] is False
    assert "library" in body["error"].lower()
    assert client.get("/api/service-catalogue/").json()["data"] == []


def test_hsn_in_library_is_accepted(client):
    _seed_hsn("998231")
    r = client.post("/api/service-catalogue/", json={
        "name": "GST Return Filing", "hsn_sac": "998231",
        "gst_rate_bps": 1800, "default_rate_paise": 500000,
    })
    assert r.json()["data"]["hsn_sac"] == "998231"


def test_retired_library_code_is_rejected_on_new_create(client):
    _seed_hsn("998231")
    MOCK_LIBRARY[0]["is_active"] = False
    r = client.post("/api/service-catalogue/", json={
        "name": "GST Return Filing", "hsn_sac": "998231",
        "gst_rate_bps": 1800, "default_rate_paise": 500000,
    })
    assert r.json()["success"] is False


def test_editing_hsn_sac_also_validated_against_library(client):
    sid = _create(client).json()["data"]["id"]  # seeded with 998221
    r = client.patch(f"/api/service-catalogue/{sid}", json={"hsn_sac": "999999"})
    assert r.json()["success"] is False
    # Unchanged on rejection.
    assert client.get("/api/service-catalogue/").json()["data"][0]["hsn_sac"] == "998221"


def test_blank_hsn_sac_always_allowed(client):
    r = _create(client, hsn_sac="")
    assert r.json()["data"]["hsn_sac"] == ""
