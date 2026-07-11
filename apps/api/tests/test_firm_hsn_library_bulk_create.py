"""
Bulk HSN/SAC library import (bulk-select / import-performance work).

POST /api/firm-hsn-library/bulk replaces a one-POST-per-row loop with one
request: a single existing-codes snapshot for the firm, then one batch
insert for every brand-new code. A code that already exists and is active
is reported as a duplicate; a retired one is reactivated. A bad row is
reported per-item and never aborts the rest of the batch.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from routers.firm_hsn_library import router as hsn_router, MOCK_LIBRARY
from core.auth import get_current_user

USER = {"id": "u-1", "firm_id": "firm-hsn-1", "role": "Partner"}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(hsn_router)
    app.dependency_overrides[get_current_user] = lambda: USER
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def clear_store():
    MOCK_LIBRARY.clear()
    yield
    MOCK_LIBRARY.clear()


def _item(**over):
    return {"hsn_code": "998221", "description": "Statutory audit services", "hsn_type": "services", **over}


def _bulk(client, items):
    return client.post("/api/firm-hsn-library/bulk", json={"codes": items})


def test_bulk_create_all_valid(client):
    items = [_item(hsn_code=f"99822{i}", description=f"Code {i}") for i in range(3)]
    r = _bulk(client, items)
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data["created"]) == 3
    assert data["reactivated"] == []
    assert data["duplicates"] == []
    assert data["errors"] == []
    codes = {c["hsn_code"] for c in data["created"]}
    assert codes == {"998220", "998221", "998222"}
    assert all(c["source"] == "import" or c["source"] == "manual" for c in data["created"])


def test_bulk_create_only_required_fields(client):
    # No gst_rate_pct, uqc, notes — only hsn_code/description/hsn_type required.
    r = _bulk(client, [{"hsn_code": "7214", "description": "Steel bars", "hsn_type": "goods"}])
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data["created"]) == 1
    assert data["created"][0]["hsn_code"] == "7214"
    assert data["errors"] == []


def test_bulk_create_missing_description_reported_as_error(client):
    items = [_item(hsn_code="1111"), {"hsn_code": "2222", "hsn_type": "goods"}, _item(hsn_code="3333")]
    r = _bulk(client, items)
    data = r.json()["data"]
    assert len(data["created"]) == 2
    assert {c["hsn_code"] for c in data["created"]} == {"1111", "3333"}
    assert len(data["errors"]) == 1
    assert data["errors"][0]["index"] == 1


def test_bulk_create_invalid_code_shape_reported_as_error(client):
    items = [_item(hsn_code="998221"), _item(hsn_code="NOT-A-CODE")]
    r = _bulk(client, items)
    data = r.json()["data"]
    assert len(data["created"]) == 1
    assert len(data["errors"]) == 1
    assert data["errors"][0]["hsn_code"] == "NOT-A-CODE"


def test_bulk_create_duplicate_code_within_batch(client):
    items = [_item(hsn_code="998221"), _item(hsn_code="998221")]
    r = _bulk(client, items)
    data = r.json()["data"]
    assert len(data["created"]) == 1
    assert len(data["duplicates"]) == 1
    assert data["duplicates"][0]["index"] == 1
    assert data["duplicates"][0]["hsn_code"] == "998221"


def test_bulk_create_duplicate_code_against_existing_active_row(client):
    MOCK_LIBRARY.append({
        "id": "existing-1", "firm_id": USER["firm_id"], "hsn_code": "998221",
        "description": "Already here", "hsn_type": "services", "is_active": True,
    })
    r = _bulk(client, [_item(hsn_code="998221"), _item(hsn_code="998222")])
    data = r.json()["data"]
    assert len(data["created"]) == 1
    assert data["created"][0]["hsn_code"] == "998222"
    assert len(data["duplicates"]) == 1
    assert data["duplicates"][0]["existing_id"] == "existing-1"


def test_bulk_create_reactivates_retired_code(client):
    MOCK_LIBRARY.append({
        "id": "retired-1", "firm_id": USER["firm_id"], "hsn_code": "998221",
        "description": "Old description", "hsn_type": "services", "is_active": False,
    })
    r = _bulk(client, [_item(hsn_code="998221", description="New description")])
    data = r.json()["data"]
    assert data["created"] == []
    assert data["duplicates"] == []
    assert len(data["reactivated"]) == 1
    assert data["reactivated"][0]["id"] == "retired-1"
    assert data["reactivated"][0]["is_active"] is True
    assert data["reactivated"][0]["description"] == "New description"


def test_bulk_create_ignores_other_firms_codes(client):
    MOCK_LIBRARY.append({
        "id": "other-firm-1", "firm_id": "some-other-firm", "hsn_code": "998221",
        "description": "Belongs to a different firm", "hsn_type": "services", "is_active": True,
    })
    r = _bulk(client, [_item(hsn_code="998221")])
    data = r.json()["data"]
    assert len(data["created"]) == 1
    assert data["duplicates"] == []


def test_bulk_create_empty_batch(client):
    r = _bulk(client, [])
    data = r.json()["data"]
    assert data == {"created": [], "reactivated": [], "duplicates": [], "errors": []}
