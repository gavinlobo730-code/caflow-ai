"""
Bulk product/service creation (bulk-select / import-performance work).

POST /api/service-catalogue/bulk replaces the CSV importer's
one-POST-per-row loop with one request: a single HSN/SAC-library snapshot,
a single duplicate-name snapshot, and one batch insert. A bad row is
reported per-item and never aborts the rest of the batch.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from routers.service_catalogue import router as sc_router, MOCK_SERVICES
from routers.firm_hsn_library import MOCK_LIBRARY
from core.auth import get_current_user

USER = {"id": "u-1", "firm_id": "firm-sc-1", "role": "Partner"}
CLIENT_A = "client-a-1"


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


def _seed_hsn(hsn_code: str, firm_id: str = USER["firm_id"]):
    MOCK_LIBRARY.append({
        "id": f"lib-{hsn_code}", "firm_id": firm_id, "hsn_code": hsn_code,
        "description": "seeded for test", "hsn_type": "services",
        "gst_rate_pct": 18.0, "is_active": True, "source": "manual",
    })


def _item(**over):
    return {"client_id": CLIENT_A, "name": "Statutory Audit", "gst_rate_bps": 1800, **over}


def _bulk(client, items):
    return client.post("/api/service-catalogue/bulk", json={"services": items})


def test_bulk_create_all_valid(client):
    items = [_item(name=f"Service {i}") for i in range(3)]
    r = _bulk(client, items)
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data["created"]) == 3
    assert data["duplicates"] == []
    assert data["errors"] == []
    names = {s["name"] for s in data["created"]}
    assert names == {"Service 0", "Service 1", "Service 2"}


def test_bulk_create_only_name_required(client):
    # No description, kind, hsn_sac, gst_rate_bps, price, category, notes —
    # everything except name is optional.
    r = _bulk(client, [{"client_id": CLIENT_A, "name": "Bare Minimum"}])
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data["created"]) == 1
    assert data["created"][0]["name"] == "Bare Minimum"
    assert data["errors"] == []


def test_bulk_create_missing_name_reported_as_error(client):
    items = [_item(name="Good One"), {"client_id": CLIENT_A}, _item(name="Also Good")]
    r = _bulk(client, items)
    data = r.json()["data"]
    assert len(data["created"]) == 2
    assert {s["name"] for s in data["created"]} == {"Good One", "Also Good"}
    assert len(data["errors"]) == 1
    assert data["errors"][0]["index"] == 1


def test_bulk_create_duplicate_name_within_batch(client):
    items = [_item(name="Audit"), _item(name="audit  ")]  # case/space-insensitive dup
    r = _bulk(client, items)
    data = r.json()["data"]
    assert len(data["created"]) == 1
    assert len(data["duplicates"]) == 1
    assert data["duplicates"][0]["index"] == 1


def test_bulk_create_duplicate_name_against_existing_row(client):
    # Seed an existing active service directly, then try to bulk-import a
    # name that collides with it.
    MOCK_SERVICES.append({
        "id": "existing-1", "firm_id": USER["firm_id"], "client_id": CLIENT_A,
        "name": "Bookkeeping", "is_active": True,
    })
    r = _bulk(client, [_item(name="Bookkeeping"), _item(name="Payroll")])
    data = r.json()["data"]
    assert len(data["created"]) == 1
    assert data["created"][0]["name"] == "Payroll"
    assert len(data["duplicates"]) == 1
    assert data["duplicates"][0]["existing_id"] == "existing-1"


def test_bulk_create_unknown_hsn_reported_as_error(client):
    _seed_hsn("998221")
    items = [_item(name="Known HSN", hsn_sac="998221"), _item(name="Unknown HSN", hsn_sac="999999")]
    r = _bulk(client, items)
    data = r.json()["data"]
    assert len(data["created"]) == 1
    assert data["created"][0]["name"] == "Known HSN"
    assert len(data["errors"]) == 1
    assert data["errors"][0]["name"] == "Unknown HSN"
    assert "library" in data["errors"][0]["error"]


def test_bulk_create_empty_batch(client):
    r = _bulk(client, [])
    data = r.json()["data"]
    assert data == {"created": [], "duplicates": [], "errors": []}
