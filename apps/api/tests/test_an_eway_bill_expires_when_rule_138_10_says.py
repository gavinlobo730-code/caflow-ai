"""
SALES-28 — how long an e-way bill is valid for, and the input nobody asked for.

WHAT WAS WRONG. `distance_km` has been a column on `eway_bill_records` since
migration 156 and a field on the create request since the router was written.
No screen ever asked for it, nothing ever read it, and `ewb_valid_upto` arrived
as a date the CA re-keyed off the NIC portal into a box that defaulted to
TODAY — a default that is wrong for every bill that has ever existed, because
Rule 138(10) grants at least one day past the date of generation.

That is not a paperwork problem. An expired e-way bill exposes the consignment
to detention and the goods and conveyance to seizure under §129, and Rule
138(10)'s proviso allows an extension only within eight hours either side of
expiry — so a CA who cannot see the expiry cannot act on it.

WHAT IT DOES NOW. `domain/gst/eway_validity.py` computes the rule; the Prepare
modal asks for the distance, vehicle type and transport mode; `GET /records/
{id}/validity` pre-fills the expiry; and recording a date that disagrees with
the computed one reports the disagreement without refusing it. The PORTAL stays
authoritative throughout — every answer carries `source`, and a missing
distance returns a gap rather than a guess.

⚠️  The 200 km slab, the 20 km ODC slab and the midnight Explanation are graded
[S] in the module: this environment's egress proxy refuses every .gov.in, so
they were written from knowledge. These tests pin the ARITHMETIC and the
WIRING, which is all a test can pin — they cannot confirm the slab.
"""
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user
from domain.gst.eway_validity import (
    ODC_SLAB_KM, ORDINARY_SLAB_KM, SHIP_MULTIMODAL_CAVEAT,
    days_for, expiry_gap, slab_km_for, validity_for,
)
from routers.eway_bill import router as eway_router

USER = {"id": "u-e1", "firm_id": "firm-e1", "role": "Partner"}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(eway_router)
    app.dependency_overrides[get_current_user] = lambda: USER
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def clear_store():
    from domain.income_tax import eway_service
    for attr in ("_MOCK_RECORDS", "_MOCK_EWAY_RECORDS"):
        store = getattr(eway_service, attr, None)
        if isinstance(store, dict):
            store.clear()
    yield


# ---------------------------------------------------------------------------
# The rule.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("km,days", [
    (1, 1), (199, 1), (200, 1),      # one day for the FIRST 200 km
    (201, 2), (400, 2),              # "or part thereof" — 201 is a second day
    (401, 3), (600, 3),
    (1000, 5),
])
def test_the_ordinary_slab_is_one_day_per_200_km_or_part(km, days):
    assert days_for(km) == days


@pytest.mark.parametrize("km,days", [(1, 1), (20, 1), (21, 2), (25, 2), (100, 5)])
def test_over_dimensional_cargo_takes_the_20_km_slab(km, days):
    assert days_for(km, vehicle_type="over_dimensional") == days


def test_the_odc_value_is_the_one_the_database_actually_holds():
    # `eway_bill_records.vehicle_type` is CHECK-constrained to
    # 'regular'/'over_dimensional' (migration 156, restated in 319). An earlier
    # draft matched invented spellings and would have given every ODC
    # consignment the 200 km slab while appearing to handle them.
    assert slab_km_for("over_dimensional") == ODC_SLAB_KM
    assert slab_km_for("regular") == ORDINARY_SLAB_KM
    assert slab_km_for(None) == ORDINARY_SLAB_KM
    # Anything unrecognised falls to the ordinary slab — fewer days, which is
    # the direction that cannot show an expired bill as live.
    assert slab_km_for("odc") == ORDINARY_SLAB_KM


def test_a_zero_or_missing_distance_still_grants_one_day():
    assert days_for(0) == 1 and days_for(-5) == 1


def test_validity_ends_at_MIDNIGHT_not_twenty_four_hours_later():
    # The Explanation counts a day as the period expiring at midnight of the
    # day immediately following generation. A bill raised at 23:55 therefore has
    # five minutes of its first day left — computing `generated + 24h` would
    # overstate validity on every bill and understate it on none.
    late = datetime(2026, 4, 10, 23, 55, tzinfo=timezone.utc)
    v = validity_for(150, late)
    assert v.days == 1
    assert v.valid_upto == datetime(2026, 4, 11, 0, 0, tzinfo=timezone.utc)


def test_each_further_day_adds_one_more_midnight():
    g = datetime(2026, 4, 10, 6, 0, tzinfo=timezone.utc)
    assert validity_for(600, g).valid_upto == datetime(2026, 4, 13, 0, 0, tzinfo=timezone.utc)


def test_a_ship_movement_takes_the_ordinary_slab_and_says_so():
    # The 20 km slab reaches multimodal movement with a ship LEG, and the row
    # holds one mode — so a ship leg and a wholly-by-ship movement are the same
    # record. The generous reading would show an expired bill as live, so the
    # ordinary slab applies and the caveat is returned beside the answer.
    g = datetime(2026, 4, 10, 6, 0, tzinfo=timezone.utc)
    v = validity_for(100, g, transport_mode="ship")
    assert v.slab_km == ORDINARY_SLAB_KM and v.days == 1
    assert v.caveat == SHIP_MULTIMODAL_CAVEAT


def test_odc_by_ship_is_odc_and_carries_no_caveat():
    g = datetime(2026, 4, 10, 6, 0, tzinfo=timezone.utc)
    v = validity_for(100, g, vehicle_type="over_dimensional", transport_mode="ship")
    assert v.slab_km == ODC_SLAB_KM and v.days == 5 and v.caveat is None


def test_no_distance_is_a_named_gap_not_a_guess():
    assert expiry_gap(None) and "distance" in expiry_gap(None)
    assert expiry_gap(0)
    assert expiry_gap(120) is None


# ---------------------------------------------------------------------------
# The wiring.
# ---------------------------------------------------------------------------
def _prepare(client, **extra):
    body = {"client_id": "cl-1", "invoice_number": "INV-1", "dispatch_from": "27",
            "ship_to": "29", "goods_description": "Laptops",
            "taxable_value_paise": 6_000_000, "sales_invoice_id": "si-1", **extra}
    r = client.post("/api/eway-bill/records", json=body)
    assert r.status_code == 200, r.text
    return r.json()["data"]["id"]


def test_the_prepared_record_keeps_the_distance_it_was_given(client):
    rid = _prepare(client, distance_km=480, vehicle_type="regular", transport_mode="road")
    r = client.get(f"/api/eway-bill/records/{rid}/validity?ewb_date=2026-07-06")
    d = r.json()["data"]
    assert d["distance_km"] == 480
    assert d["days"] == 3 and d["valid_upto"] == "2026-07-09"
    assert d["source"] and d["gap"] is None


def test_a_record_prepared_without_a_distance_refuses_to_compute(client):
    rid = _prepare(client)
    d = client.get(f"/api/eway-bill/records/{rid}/validity?ewb_date=2026-07-06").json()["data"]
    assert d["valid_upto"] is None and d["gap"]


def test_the_validity_route_needs_the_bills_own_date(client):
    rid = _prepare(client, distance_km=480)
    d = client.get(f"/api/eway-bill/records/{rid}/validity").json()["data"]
    assert d["valid_upto"] is None and "date" in d["gap"]


def test_recording_the_computed_date_agrees(client):
    rid = _prepare(client, distance_km=480, vehicle_type="regular", transport_mode="road")
    g = client.post(f"/api/eway-bill/records/{rid}/generated", json={
        "ewb_number": "EWB123456789012", "ewb_date": "2026-07-06",
        "ewb_valid_upto": "2026-07-09"})
    check = g.json()["data"]["validity_check"]
    assert check["agrees"] is True and check["valid_upto"] == "2026-07-09"


def test_recording_a_date_that_disagrees_is_reported_and_NOT_refused(client):
    # The portal computes the real figure and this cannot see a leg by ship or
    # an extension already granted. So the typed date is stored and the
    # disagreement is reported — a refusal here would stop a CA recording a
    # bill that genuinely exists.
    rid = _prepare(client, distance_km=480)
    g = client.post(f"/api/eway-bill/records/{rid}/generated", json={
        "ewb_number": "EWB123456789012", "ewb_date": "2026-07-06",
        "ewb_valid_upto": "2026-07-20"})
    assert g.status_code == 200
    data = g.json()["data"]
    assert data["ewb_valid_upto"] == "2026-07-20"      # what the portal said, stored
    assert data["validity_check"]["agrees"] is False
    assert data["validity_check"]["valid_upto"] == "2026-07-09"


def test_a_record_with_no_distance_reports_no_disagreement_only_the_gap(client):
    rid = _prepare(client)
    g = client.post(f"/api/eway-bill/records/{rid}/generated", json={
        "ewb_number": "EWB123456789012", "ewb_date": "2026-07-06",
        "ewb_valid_upto": "2026-07-20"})
    check = g.json()["data"]["validity_check"]
    assert check["agrees"] is None and check["gap"]


def test_a_vehicle_type_the_table_forbids_is_refused_at_the_boundary(client):
    # It used to reach Postgres and come back as a 500 carrying a constraint
    # name. And it is now load-bearing: vehicle_type is what the 20 km slab
    # keys on, so a value nothing recognises is a wrong validity, not a typo.
    r = client.post("/api/eway-bill/records", json={
        "client_id": "cl-1", "invoice_number": "INV-1", "dispatch_from": "27",
        "ship_to": "29", "goods_description": "Laptops",
        "taxable_value_paise": 6_000_000, "vehicle_type": "lorry"})
    assert r.status_code == 422


def test_a_negative_distance_is_refused_at_the_boundary(client):
    r = client.post("/api/eway-bill/records", json={
        "client_id": "cl-1", "invoice_number": "INV-1", "dispatch_from": "27",
        "ship_to": "29", "goods_description": "Laptops",
        "taxable_value_paise": 6_000_000, "distance_km": -10})
    assert r.status_code == 422
