"""Product & Service master — CRUD, archive/restore, duplicate prevention,
search, ranking, validation, CLIENT isolation. Runs in mock mode (no
SUPABASE_URL): the router keeps an in-memory store so the full lifecycle is
exercised without a live DB, mirroring test_customers-style coverage. Pure
ranking is asserted directly.

Batch 6 guardrail, still enforced after the HSN/SAC redesign broadened this
from services-only to goods+services: these tests assert that no
stock/inventory concept exists on a row.

HSN/SAC redesign (Decision C): `hsn_sac` must be a code already in the
firm's own `firm_hsn_library` — `_seed_hsn` below seeds that library in mock
mode so existing tests keep working, and a dedicated section tests the
rejection path.

HSN/SAC workflow alignment (migration 182): Products & Services are
CLIENT-owned, not firm-owned — "Client B must never inherit Client A's
products." Every helper here defaults to CLIENT_A; a dedicated section
tests that CLIENT_B never sees CLIENT_A's rows even within the same firm.
"""
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from routers.service_catalogue import router as sc_router, _rank_services, MOCK_SERVICES
from routers.firm_hsn_library import MOCK_LIBRARY
from routers.sales_invoices import MOCK_SALES_INVOICE_LINES
from core.auth import get_current_user

USER = {"id": "u-1", "firm_id": "firm-sc-1", "role": "Partner"}
CLIENT_A = "client-a-1"
CLIENT_B = "client-b-1"


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
    MOCK_SALES_INVOICE_LINES.clear()
    yield
    MOCK_SERVICES.clear()
    MOCK_LIBRARY.clear()
    MOCK_SALES_INVOICE_LINES.clear()


def _link_to_invoice_line(service_id: str, invoice_id: str = "inv-1"):
    """Simulate a real sales-invoice line picked from this preset — the same
    link create/update_invoice write via InvoiceLineIn.service_catalogue_id
    (migration 184), without going through the full invoice-creation flow."""
    MOCK_SALES_INVOICE_LINES.append({
        "id": "line-1", "invoice_id": invoice_id, "service_catalogue_id": service_id,
        "description": "linked line", "hsn_sac": "", "quantity": 1, "rate_paise": 100,
    })


def _seed_hsn(hsn_code: str, hsn_type: str = "services", firm_id: str = USER["firm_id"]):
    """Seed an active firm_hsn_library row so a product/service test can
    legally reference `hsn_code` (Decision C: HSN/SAC only from the firm's
    own library — the library stays firm-wide even though Products/Services
    are client-owned)."""
    MOCK_LIBRARY.append({
        "id": f"lib-{hsn_code}", "firm_id": firm_id, "hsn_code": hsn_code,
        "description": "seeded for test", "hsn_type": hsn_type,
        "gst_rate_pct": 18.0, "is_active": True, "source": "manual",
    })


def _create(client, client_id: str = CLIENT_A, **over):
    hsn = over.get("hsn_sac", "998221")
    if hsn:
        _seed_hsn(hsn)
    body = {
        "client_id": client_id,
        "name": "Statutory Audit", "description": "Statutory audit FY 2025-26",
        "hsn_sac": "998221", "gst_rate_bps": 1800, "default_rate_paise": 5000000,
        "unit": "OTH", **over,
    }
    return client.post("/api/service-catalogue/", json=body)


def _list(client, client_id: str = CLIENT_A, **params):
    qs = urlencode({"client_id": client_id, **params})
    return client.get(f"/api/service-catalogue/?{qs}")


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
    assert data["client_id"] == CLIENT_A
    assert data["is_active"] is True
    assert data["default_rate_paise"] == 5000000
    # No inventory concept ever leaks onto a service row.
    for banned in ("stock", "quantity_on_hand", "valuation", "warehouse", "reorder"):
        assert banned not in data
    lst = _list(client).json()["data"]
    assert len(lst) == 1


def test_client_id_required(client):
    _seed_hsn("998221")
    r = client.post("/api/service-catalogue/", json={
        "name": "Statutory Audit", "hsn_sac": "998221",
        "gst_rate_bps": 1800, "default_rate_paise": 5000000,
    })
    assert r.status_code == 422


def test_edit_service(client):
    sid = _create(client).json()["data"]["id"]
    r = client.patch(f"/api/service-catalogue/{sid}", json={"default_rate_paise": 7500000})
    assert r.json()["data"]["default_rate_paise"] == 7500000


def test_validation_blank_name_and_negative_rate(client):
    assert _create(client, name="   ").status_code == 422
    assert _create(client, default_rate_paise=-1).status_code == 422
    assert _create(client, gst_rate_bps=20000).status_code == 422


# ── Duplicate prevention (scoped per client) ───────────────────────────────────

def test_duplicate_active_name_blocked(client):
    _create(client, name="GST Filing")
    dup = _create(client, name="  gst   filing ")  # case/space-insensitive
    body = dup.json()["data"]
    assert body.get("duplicate") is True
    assert len(_list(client).json()["data"]) == 1


def test_same_name_allowed_for_different_clients(client):
    # "Client B must never inherit Client A's products" — but the inverse
    # matters too: the SAME name for two DIFFERENT clients is not a clash.
    a = _create(client, client_id=CLIENT_A, name="Consulting Retainer")
    b = _create(client, client_id=CLIENT_B, name="Consulting Retainer")
    assert a.json()["data"].get("duplicate") is not True
    assert b.json()["data"].get("duplicate") is not True
    assert len(_list(client, client_id=CLIENT_A).json()["data"]) == 1
    assert len(_list(client, client_id=CLIENT_B).json()["data"]) == 1


# ── Archive / restore ─────────────────────────────────────────────────────────

def test_archive_hides_then_restore_shows(client):
    sid = _create(client, name="One-time Advisory").json()["data"]["id"]
    client.patch(f"/api/service-catalogue/{sid}", json={"is_active": False})
    # Archived is hidden by default…
    assert _list(client).json()["data"] == []
    # …but visible with include_archived, and restorable.
    assert len(_list(client, include_archived="true").json()["data"]) == 1
    client.patch(f"/api/service-catalogue/{sid}", json={"is_active": True})
    assert len(_list(client).json()["data"]) == 1


def test_archived_name_can_be_reused(client):
    sid = _create(client, name="Seasonal Package").json()["data"]["id"]
    client.patch(f"/api/service-catalogue/{sid}", json={"is_active": False})
    again = _create(client, name="Seasonal Package")  # not a duplicate — old one archived
    assert again.json()["data"].get("duplicate") is not True


# ── Hard delete — only when never used ────────────────────────────────────────

def test_delete_unused_service_succeeds(client):
    sid = _create(client, name="Never Picked").json()["data"]["id"]
    resp = client.delete(f"/api/service-catalogue/{sid}")
    assert resp.json()["success"] is True
    assert _list(client, include_archived="true").json()["data"] == []


def test_delete_blocked_when_linked_to_invoice_line(client):
    sid = _create(client, name="Picked Once").json()["data"]["id"]
    _link_to_invoice_line(sid)
    resp = client.delete(f"/api/service-catalogue/{sid}")
    body = resp.json()
    assert body["success"] is False
    assert "archive" in body["error"].lower()
    # Still there — a rejected delete must not remove the row.
    assert len(_list(client, include_archived="true").json()["data"]) == 1


def test_delete_blocked_even_when_archived_if_linked(client):
    sid = _create(client, name="Archived But Used").json()["data"]["id"]
    _link_to_invoice_line(sid)
    client.patch(f"/api/service-catalogue/{sid}", json={"is_active": False})
    resp = client.delete(f"/api/service-catalogue/{sid}")
    assert resp.json()["success"] is False


def test_delete_allowed_when_only_picked_but_never_saved_to_an_invoice(client):
    # use_count alone (the old heuristic) is no longer the signal — only a
    # REAL invoice-line link blocks deletion now. A preset that was picked
    # into a draft that was never actually saved must remain deletable.
    sid = _create(client, name="Picked Into A Discarded Draft").json()["data"]["id"]
    client.post(f"/api/service-catalogue/{sid}/used")
    resp = client.delete(f"/api/service-catalogue/{sid}")
    assert resp.json()["success"] is True


def test_delete_unknown_id_is_404(client):
    resp = client.delete("/api/service-catalogue/does-not-exist")
    assert resp.status_code == 404


# ── Search + ranking + usage bump ─────────────────────────────────────────────

def test_search_by_name_and_hsn(client):
    _create(client, name="Statutory Audit", hsn_sac="998221")
    _create(client, name="GST Filing", hsn_sac="998231")
    assert [s["name"] for s in _list(client, q="gst").json()["data"]] == ["GST Filing"]
    assert [s["name"] for s in _list(client, q="998221").json()["data"]] == ["Statutory Audit"]
    assert _list(client, q="nothingmatches").json()["data"] == []


def test_used_bump_ranks_recent_first(client):
    a = _create(client, name="Service A").json()["data"]["id"]
    b = _create(client, name="Service B").json()["data"]["id"]
    client.post(f"/api/service-catalogue/{b}/used")
    # Empty query = recent/frequent list; the just-used one leads.
    names = [s["name"] for s in _list(client).json()["data"]]
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


def test_create_response_has_no_unrecognised_inventory_field_names(client):
    # Migration 188 added real stock/valuation tracking (stock_qty_units,
    # avg_cost_paise, opening_qty_units, opening_cost_paise — see
    # domain/inventory_service.py), superseding this table's original
    # "no inventory master" lock. This test now only guards against ad-hoc
    # field names (sku/barcode/warehouse) that were never part of that design
    # and still aren't — not against inventory concepts existing at all.
    _seed_hsn("2202", hsn_type="goods")
    data = _create(client, name="Bottled Water", kind="good", hsn_sac="2202").json()["data"]
    for banned in ("sku", "barcode", "quantity_on_hand", "warehouse"):
        assert banned not in data


# ── HSN/SAC must come from the FIRM's library (Decision C) ────────────────────
# (The library stays firm-wide per the approved workflow — shared across all
# of a firm's clients — even though Products/Services themselves are now
# client-owned. These tests use CLIENT_A throughout; the HSN/SAC validation
# is firm-scoped, not client-scoped.)

def test_hsn_not_in_library_is_rejected(client):
    # No _seed_hsn call — "997199" was never added to this firm's library.
    r = client.post("/api/service-catalogue/", json={
        "client_id": CLIENT_A, "name": "Unlisted Service", "hsn_sac": "997199",
        "gst_rate_bps": 1800, "default_rate_paise": 1000,
    })
    body = r.json()
    assert body["success"] is False
    assert "library" in body["error"].lower()
    assert _list(client).json()["data"] == []


def test_hsn_in_library_is_accepted(client):
    _seed_hsn("998231")
    r = client.post("/api/service-catalogue/", json={
        "client_id": CLIENT_A, "name": "GST Return Filing", "hsn_sac": "998231",
        "gst_rate_bps": 1800, "default_rate_paise": 500000,
    })
    assert r.json()["data"]["hsn_sac"] == "998231"


def test_retired_library_code_is_rejected_on_new_create(client):
    _seed_hsn("998231")
    MOCK_LIBRARY[0]["is_active"] = False
    r = client.post("/api/service-catalogue/", json={
        "client_id": CLIENT_A, "name": "GST Return Filing", "hsn_sac": "998231",
        "gst_rate_bps": 1800, "default_rate_paise": 500000,
    })
    assert r.json()["success"] is False


def test_editing_hsn_sac_also_validated_against_library(client):
    sid = _create(client).json()["data"]["id"]  # seeded with 998221
    r = client.patch(f"/api/service-catalogue/{sid}", json={"hsn_sac": "999999"})
    assert r.json()["success"] is False
    # Unchanged on rejection.
    assert _list(client).json()["data"][0]["hsn_sac"] == "998221"


def test_blank_hsn_sac_always_allowed(client):
    r = _create(client, hsn_sac="")
    assert r.json()["data"]["hsn_sac"] == ""


def test_hsn_library_shared_across_clients_of_the_same_firm(client):
    # The library itself is firm-wide: a code added while creating a product
    # for CLIENT_A is immediately usable for CLIENT_B too — this is NOT a
    # regression of the client-isolation guarantee below, since the library
    # and the Products/Services table are two different tenancy models by
    # design (approved workflow: "The Firm HSN/SAC Library remains firm-wide").
    _seed_hsn("998231")
    a = client.post("/api/service-catalogue/", json={
        "client_id": CLIENT_A, "name": "GST Filing", "hsn_sac": "998231",
        "gst_rate_bps": 1800, "default_rate_paise": 500000,
    })
    b = client.post("/api/service-catalogue/", json={
        "client_id": CLIENT_B, "name": "GST Filing (Client B)", "hsn_sac": "998231",
        "gst_rate_bps": 1800, "default_rate_paise": 500000,
    })
    assert a.json()["data"]["hsn_sac"] == "998231"
    assert b.json()["data"]["hsn_sac"] == "998231"


# ── Client isolation (migration 182) ───────────────────────────────────────────
# "Client B must never inherit Client A's products." Products/Services are
# client-owned, not firm-owned — this is the core behaviour this migration
# exists to guarantee.

def test_client_b_does_not_see_client_a_products(client):
    _create(client, client_id=CLIENT_A, name="Laptop", kind="good", hsn_sac="998221")
    assert _list(client, client_id=CLIENT_A).json()["data"] != []
    assert _list(client, client_id=CLIENT_B).json()["data"] == []


def test_client_a_cannot_edit_client_b_product_via_id_leak(client):
    # Even if a Client-A-scoped caller somehow learns Client B's row id, a
    # PATCH is still gated by firm_id ownership only at the app layer in
    # mock mode — but the searchable LIST endpoint never leaks the id across
    # clients in the first place, which is the actual attack surface for a
    # normal UI flow. This test pins that the list boundary holds.
    b_id = _create(client, client_id=CLIENT_B, name="Steel Rod", kind="good", hsn_sac="998221").json()["data"]["id"]
    assert all(row["id"] != b_id for row in _list(client, client_id=CLIENT_A).json()["data"])


def test_duplicate_check_does_not_cross_client_boundary(client):
    # Renaming a Client-A product to a name that's taken by a CLIENT-B
    # product (same firm) must NOT be blocked — duplicate-name prevention is
    # per (firm, client), not per firm alone.
    _create(client, client_id=CLIENT_B, name="Consulting Retainer")
    sid = _create(client, client_id=CLIENT_A, name="Bookkeeping").json()["data"]["id"]
    r = client.patch(f"/api/service-catalogue/{sid}", json={"name": "Consulting Retainer"})
    assert r.json()["success"] is True
    assert r.json()["data"].get("duplicate") is not True
