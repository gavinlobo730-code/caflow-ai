"""An emptied box on the product or service edit is cleared, and a unit is not removed from under an alternate unit (POST-A-399, fifth slice).

WHAT WAS WRONG
    The product form built its request with `value || undefined`, which `JSON.stringify` drops, and the route read its body by dropping
    every null. So a person who emptied an item's description, its item group, its note, its HSN/SAC code, its unit, its purchase price
    or its reorder level and pressed Save was told it was saved, and the old value was still there: the next invoice line picked from
    the item started from a description or a code the person had removed, and the reorder list went on measuring against a level they
    had taken away. The alternate unit could be cleared by the route (an empty string, through `model_fields_set`) only when another
    field came with it (alone it was answered "No fields to update"), and no form ever sent it.

WHAT IS ASSERTED
    * the edit clears exactly the fields its model names in `CLEARABLE` when they are SENT null or blank, and writes NULL;
    * a field that is NOT sent is left as it was, and a null for a field outside `CLEARABLE` (the selling price, the GST rate, the
      name) still reads "not sent";
    * a cleared HSN/SAC code is not looked up in the firm's library (there is nothing to look up), and a code that IS sent still is;
    * a unit that is emptied while the item keeps an alternate unit is refused in the pair's own words and nothing is written, and the
      two cleared together are taken;
    * a reorder level of 0 is a level and is stored as 0, never read as a clear;
    * the same holds on the database path as on the stand-in store.

Driven through the route in mock mode (the store the router itself falls back to), and through the handler on the shared in-memory
database client for the database path.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.service_catalogue as sc
from core.auth import get_current_user
from models.clearable import clearable_fields
from models.service_catalogue import ServiceCatalogueUpdateIn
from routers.firm_hsn_library import MOCK_LIBRARY
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-clear-ps"
USER = {"id": "u-1", "firm_id": FIRM, "role": "Partner", "auth_user_id": "a-1", "email": "p@firm.test"}
CLIENT = "client-ps-1"
CLEARED = ("description", "category", "notes", "hsn_sac", "unit", "purchase_price_paise", "reorder_level_units")


def test_what_the_product_or_service_edit_may_clear():
    assert clearable_fields(ServiceCatalogueUpdateIn()) == set(CLEARED)


@pytest.fixture
def client(monkeypatch):
    # The file is about the route's own behaviour, so it runs the route as it runs with no database configured, whatever the
    # environment of the run says.
    monkeypatch.setattr(sc, "_USE_MOCK", True)
    sc.MOCK_SERVICES.clear()
    MOCK_LIBRARY.clear()
    app = FastAPI()
    app.include_router(sc.router)
    app.dependency_overrides[get_current_user] = lambda: USER
    yield TestClient(app, raise_server_exceptions=False)
    sc.MOCK_SERVICES.clear()
    MOCK_LIBRARY.clear()


def _library(code):
    MOCK_LIBRARY.append({"id": f"lib-{code}", "firm_id": FIRM, "hsn_code": code, "description": "seeded", "hsn_type": "goods",
                         "gst_rate_pct": 18.0, "is_active": True, "source": "manual"})


def _good(client, **over):
    _library("7214")
    body = {"client_id": CLIENT, "name": "TMT bar 12mm", "kind": "good", "description": "TMT bar, 12mm", "hsn_sac": "7214",
            "gst_rate_bps": 1800, "default_rate_paise": 5_500_000, "purchase_price_paise": 4_200_000, "unit": "KGS",
            "category": "Raw Material", "notes": "Buy in lots of 50", "reorder_level_units": 25, **over}
    out = client.post("/api/service-catalogue/", json=body).json()
    assert out["success"] is True, out
    return out["data"]["id"]


def _row(sid):
    return next(s for s in sc.MOCK_SERVICES if s["id"] == sid)


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_each_text_box_sent_empty_is_cleared(client, empty):
    sid = _good(client)
    out = client.patch(f"/api/service-catalogue/{sid}", json={k: empty for k in ("description", "category", "notes", "hsn_sac", "unit")}).json()
    assert out["success"] is True, out
    row = _row(sid)
    for key in ("description", "category", "notes", "hsn_sac", "unit"):
        assert row[key] is None, f"{key} was sent empty and is still {row[key]!r}"
    # What was not sent is as it was.
    assert row["purchase_price_paise"] == 4_200_000 and row["reorder_level_units"] == 25 and row["name"] == "TMT bar 12mm"


def test_the_two_figures_sent_null_are_cleared_and_a_level_of_zero_is_a_level(client):
    sid = _good(client)
    out = client.patch(f"/api/service-catalogue/{sid}", json={"purchase_price_paise": None, "reorder_level_units": None}).json()
    assert out["success"] is True, out
    assert _row(sid)["purchase_price_paise"] is None and _row(sid)["reorder_level_units"] is None
    assert _row(sid)["description"] == "TMT bar, 12mm"
    out = client.patch(f"/api/service-catalogue/{sid}", json={"reorder_level_units": 0}).json()
    assert out["success"] is True and _row(sid)["reorder_level_units"] == 0


def test_a_field_that_is_not_sent_is_untouched_and_a_null_outside_the_set_reads_as_not_sent(client):
    sid = _good(client)
    before = dict(_row(sid))
    out = client.patch(f"/api/service-catalogue/{sid}",
                       json={"notes": "Buy in lots of 100", "default_rate_paise": None, "gst_rate_bps": None, "name": None, "is_active": None}).json()
    assert out["success"] is True, out
    row = _row(sid)
    assert row["notes"] == "Buy in lots of 100"
    for key in ("name", "default_rate_paise", "gst_rate_bps", "description", "category", "hsn_sac", "unit", "purchase_price_paise",
                "reorder_level_units"):
        assert row[key] == before[key], key
    assert row.get("is_active", True) is True


def test_an_edit_that_sends_nothing_is_still_refused(client):
    sid = _good(client)
    assert client.patch(f"/api/service-catalogue/{sid}", json={}).status_code == 422
    # Nulls for fields outside the set are nothing sent.
    assert client.patch(f"/api/service-catalogue/{sid}", json={"name": None, "default_rate_paise": None}).status_code == 422


def test_a_cleared_code_is_not_looked_up_and_a_code_that_is_sent_still_is(client):
    sid = _good(client)
    MOCK_LIBRARY.clear()   # the library no longer holds 7214, or anything
    out = client.patch(f"/api/service-catalogue/{sid}", json={"hsn_sac": None}).json()
    assert out["success"] is True, out
    assert _row(sid)["hsn_sac"] is None
    refused = client.patch(f"/api/service-catalogue/{sid}", json={"hsn_sac": "7308"}).json()
    assert refused["success"] is False and "not in your firm's library" in refused["error"]
    assert _row(sid)["hsn_sac"] is None


def test_a_unit_is_not_removed_from_under_an_alternate_unit(client):
    sid = _good(client, alternate_unit="BOX", units_per_alternate=12)
    refused = client.patch(f"/api/service-catalogue/{sid}", json={"unit": None}).json()
    assert refused["success"] is False, refused
    assert "An alternate unit needs a primary unit" in refused["error"]
    row = _row(sid)
    assert row["unit"] == "KGS" and row["alternate_unit"] == "BOX" and row["units_per_alternate"] == 12
    # Both taken away in one edit is a whole answer.
    out = client.patch(f"/api/service-catalogue/{sid}", json={"unit": None, "alternate_unit": None}).json()
    assert out["success"] is True, out
    row = _row(sid)
    assert row["unit"] is None and row["alternate_unit"] is None and row["units_per_alternate"] is None


def test_an_alternate_unit_sent_empty_clears_the_pair_even_when_it_is_the_only_thing_sent(client):
    for empty in (None, ""):
        sid = _good(client, name=f"Bar {empty!r}", alternate_unit="BOX", units_per_alternate=12)
        out = client.patch(f"/api/service-catalogue/{sid}", json={"alternate_unit": empty}).json()
        assert out["success"] is True, out
        row = _row(sid)
        assert row["alternate_unit"] is None and row["units_per_alternate"] is None and row["unit"] == "KGS"


# ── the database path ────────────────────────────────────────────────────────────────────────────────────────────────────

def _database(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [sc])
    monkeypatch.setattr(sc, "_assert_service_scope", lambda *a, **k: None)
    monkeypatch.setattr(sc, "_hsn_in_library", lambda firm_id, code: False)   # any code that IS looked up is refused
    db.seed("service_catalogue", {
        "id": "svc-1", "firm_id": FIRM, "client_id": CLIENT, "name": "TMT bar 12mm", "kind": "good", "description": "TMT bar, 12mm",
        "hsn_sac": "7214", "gst_rate_bps": 1800, "default_rate_paise": 5_500_000, "purchase_price_paise": 4_200_000, "unit": "KGS",
        "category": "Raw Material", "notes": "Buy in lots of 50", "reorder_level_units": 25, "alternate_unit": None,
        "units_per_alternate": None, "is_active": True})
    return db


def test_the_database_path_writes_null_for_what_was_emptied_and_leaves_the_rest(monkeypatch):
    db = _database(monkeypatch)
    body = ServiceCatalogueUpdateIn(description="", category=None, notes="  ", hsn_sac=None, unit=None, purchase_price_paise=None,
                                    reorder_level_units=None)
    out = sc.update_service("svc-1", body, USER)
    assert out["success"] is True, out
    row = db.rows("service_catalogue")[0]
    for key in CLEARED:
        assert row[key] is None, f"{key} was sent empty and is still {row[key]!r}"
    assert row["name"] == "TMT bar 12mm" and row["default_rate_paise"] == 5_500_000 and row["gst_rate_bps"] == 1800


def test_the_database_path_leaves_an_unsent_field_and_refuses_a_unit_taken_from_under_its_alternate(monkeypatch):
    db = _database(monkeypatch)
    db.rows("service_catalogue")[0].update({"alternate_unit": "BOX", "units_per_alternate": 12})
    out = sc.update_service("svc-1", ServiceCatalogueUpdateIn(notes="Buy in lots of 100"), USER)
    assert out["success"] is True, out
    row = db.rows("service_catalogue")[0]
    assert row["notes"] == "Buy in lots of 100" and row["description"] == "TMT bar, 12mm" and row["hsn_sac"] == "7214"
    refused = sc.update_service("svc-1", ServiceCatalogueUpdateIn(unit=None), USER)
    assert refused["success"] is False and "An alternate unit needs a primary unit" in refused["error"]
    assert db.rows("service_catalogue")[0]["unit"] == "KGS"
