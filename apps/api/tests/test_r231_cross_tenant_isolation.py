"""
Task #231 — high/medium cross-tenant isolation gaps (GST saves, party
creation, relationships).

Task assignment (routers/assignments.py) and notes (routers/year_end_notes.py)
were independently audited and found already properly firm/client-scoped —
no fix needed there, so no regression tests are added for those areas.

All findings share the same root cause as task #230: a caller-supplied
client_id/entity_id used in a write path without checking it belongs to the
caller's own firm — the platform's established core.authz.assert_client_access
guard was simply missing. Tests use the same core.authz enforcement-path
fixture established in test_authz_engine.py / test_r230_cross_tenant_isolation.py.
"""
import pytest
from fastapi import HTTPException

import core.authz as authz
import routers.gst_workspace as gst_router
import routers.customers as customers_router
import routers.vendors as vendors_router
import routers.relationships as relationships_router
import services.opening_balance_service as obs
from routers.gst_workspace import SaveGSTR1Request, SaveGSTR3BRequest, GSTR2BUploadRequest, GSTR9In
from routers.customers import CustomerBulkIn
from models.parties import CustomerIn, VendorIn
from routers.vendors import VendorBulkIn
from routers.relationships import EntityRoleIn, EntityToEntityRelIn, LoanIn, PropertyIn
from tests.e2e_harness import FakeDB

PARTNER_F1 = {"firm_id": "F1", "role": "Partner", "auth_user_id": "p1", "id": "u1", "email": "p1@f1.test"}


@pytest.fixture
def enforced(monkeypatch):
    """Force the real (non-mock) client-ownership enforcement path. C1
    belongs to F1 (every fixture user's firm); C-OTHER belongs to F2."""
    monkeypatch.setattr(authz, "_USE_MOCK", False)

    def fake_belongs(client_id, firm_id):
        if client_id == "C-OTHER":
            return firm_id == "F2"
        return firm_id == "F1"
    monkeypatch.setattr(authz, "_client_belongs_to_firm", fake_belongs)
    yield


@pytest.fixture(autouse=True)
def _clear_mock_stores():
    gst_router._MOCK_GSTR1.clear()
    gst_router._MOCK_GSTR3B.clear()
    gst_router._MOCK_GSTR2B.clear()
    customers_router.MOCK_CUSTOMERS.clear()
    vendors_router.MOCK_VENDORS.clear()
    yield
    gst_router._MOCK_GSTR1.clear()
    gst_router._MOCK_GSTR3B.clear()
    gst_router._MOCK_GSTR2B.clear()
    customers_router.MOCK_CUSTOMERS.clear()
    vendors_router.MOCK_VENDORS.clear()


# ── GST saves ──────────────────────────────────────────────────────────────

def test_save_gstr1_rejects_another_firms_client(enforced):
    body = SaveGSTR1Request(client_id="C-OTHER", period="042026", gstin="27AAAAA0000A1Z5")
    with pytest.raises(HTTPException) as ei:
        gst_router.save_gstr1(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_save_gstr1_accepts_own_firms_client(enforced):
    body = SaveGSTR1Request(client_id="C1", period="042026", gstin="27AAAAA0000A1Z5")
    result = gst_router.save_gstr1(body, PARTNER_F1)
    assert result["success"] is True


def test_save_gstr3b_rejects_another_firms_client(enforced):
    body = SaveGSTR3BRequest(client_id="C-OTHER", period="042026", gstin="27AAAAA0000A1Z5")
    with pytest.raises(HTTPException) as ei:
        gst_router.save_gstr3b(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_save_gstr3b_accepts_own_firms_client(enforced):
    body = SaveGSTR3BRequest(client_id="C1", period="042026", gstin="27AAAAA0000A1Z5")
    result = gst_router.save_gstr3b(body, PARTNER_F1)
    assert result["success"] is True


def test_upload_gstr2b_rejects_another_firms_client(enforced):
    body = GSTR2BUploadRequest(client_id="C-OTHER", period="042026")
    with pytest.raises(HTTPException) as ei:
        gst_router.upload_gstr2b(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_upload_gstr2b_accepts_own_firms_client(enforced):
    body = GSTR2BUploadRequest(client_id="C1", period="042026")
    result = gst_router.upload_gstr2b(body, PARTNER_F1)
    assert result["success"] is True


def test_save_gstr9_rejects_another_firms_client(enforced):
    body = GSTR9In(client_id="C-OTHER", financial_year="2025-26", gstin="27AAAAA0000A1Z5")
    with pytest.raises(HTTPException) as ei:
        gst_router.save_gstr9(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_save_gstr9_accepts_own_firms_client(enforced):
    body = GSTR9In(client_id="C1", financial_year="2025-26", gstin="27AAAAA0000A1Z5")
    result = gst_router.save_gstr9(body, PARTNER_F1)
    assert result["success"] is True


# ── Party creation: customers ────────────────────────────────────────────────

def test_create_customer_rejects_another_firms_client(enforced):
    body = CustomerIn(client_id="C-OTHER", name="Sneaky Co")
    with pytest.raises(HTTPException) as ei:
        customers_router.create_customer(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_customer_accepts_own_firms_client(enforced):
    body = CustomerIn(client_id="C1", name="Legit Co")
    result = customers_router.create_customer(body, PARTNER_F1)
    assert result["success"] is True
    assert result["data"]["client_id"] == "C1"


def test_bulk_create_customers_rejects_another_firms_client_per_item(enforced):
    body = CustomerBulkIn(customers=[
        {"client_id": "C1", "name": "Own Co"},
        {"client_id": "C-OTHER", "name": "Sneaky Co"},
    ])
    result = customers_router.bulk_create_customers(body, PARTNER_F1)
    assert result["success"] is True
    data = result["data"]
    assert len(data["created"]) == 1 and data["created"][0]["client_id"] == "C1"
    assert len(data["errors"]) == 1
    assert data["errors"][0]["name"] == "Sneaky Co"


# ── Party creation: vendors ───────────────────────────────────────────────────

def test_create_vendor_rejects_another_firms_client(enforced):
    body = VendorIn(client_id="C-OTHER", name="Sneaky Vendor")
    with pytest.raises(HTTPException) as ei:
        vendors_router.create_vendor(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_vendor_accepts_own_firms_client(enforced):
    body = VendorIn(client_id="C1", name="Legit Vendor")
    result = vendors_router.create_vendor(body, PARTNER_F1)
    assert result["success"] is True
    assert result["data"]["client_id"] == "C1"


def test_create_vendors_bulk_rejects_another_firms_client_per_item(enforced):
    body = VendorBulkIn(vendors=[
        {"client_id": "C1", "name": "Own Vendor"},
        {"client_id": "C-OTHER", "name": "Sneaky Vendor"},
    ])
    result = vendors_router.create_vendors_bulk(body, PARTNER_F1)
    assert result["success"] is True
    data = result["data"]
    assert len(data["created"]) == 1 and data["created"][0]["client_id"] == "C1"
    assert len(data["errors"]) == 1
    assert data["errors"][0]["name"] == "Sneaky Vendor"


# ── Opening-balance sync defense-in-depth (services/opening_balance_service.py) ─

def test_fetch_masters_is_scoped_by_firm_id_not_just_client_id():
    """The amplification path task #230/#231's write-guard fixes close off:
    even if a cross-firm row somehow existed, _fetch_masters must not
    aggregate it into another firm's opening-balance journal."""
    db = FakeDB()
    db.seed("customers", {"firm_id": "F1", "client_id": "C1", "opening_balance_paise": 100000})
    db.seed("customers", {"firm_id": "F2", "client_id": "C1", "opening_balance_paise": 999999999})
    customers, _, _ = obs._fetch_masters(db, "F1", "C1")
    assert len(customers) == 1
    assert customers[0]["opening_balance_paise"] == 100000


# ── Relationships ──────────────────────────────────────────────────────────────
# relationships.py's own _db() returns None without SUPABASE_URL (this test
# env), so these exercise the guard added BEFORE the db-dependent code path —
# proving the check fires even in mock mode, matching how the router itself
# executes it unconditionally ahead of the `if not db:` branches.

def test_add_entity_role_rejects_another_firms_client(enforced):
    body = EntityRoleIn(client_id="C-OTHER", role_type="Director")
    with pytest.raises(HTTPException) as ei:
        relationships_router.add_entity_role("some-entity", body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_add_entity_role_accepts_own_firms_client(enforced):
    body = EntityRoleIn(client_id="C1", role_type="Director")
    result = relationships_router.add_entity_role("some-entity", body, PARTNER_F1)
    assert result["success"] is True


def test_create_loan_rejects_another_firms_client(enforced):
    body = LoanIn(client_id="C-OTHER", entity_id="some-entity", loan_type="to_director",
                  principal_paise=100000, interest_rate=10.0)
    with pytest.raises(HTTPException) as ei:
        relationships_router.create_loan(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_loan_accepts_own_firms_client(enforced):
    body = LoanIn(client_id="C1", entity_id="some-entity", loan_type="to_director",
                  principal_paise=100000, interest_rate=10.0)
    result = relationships_router.create_loan(body, PARTNER_F1)
    assert result["success"] is True


def test_create_property_rejects_another_firms_client(enforced):
    body = PropertyIn(client_id="C-OTHER", address="1 Sneaky St", property_type="residential",
                      cost_paise=1000000)
    with pytest.raises(HTTPException) as ei:
        relationships_router.create_property(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_property_accepts_own_firms_client(enforced):
    body = PropertyIn(client_id="C1", address="1 Legit St", property_type="residential",
                      cost_paise=1000000)
    result = relationships_router.create_property(body, PARTNER_F1)
    assert result["success"] is True


def test_create_entity_to_entity_relationship_rejects_unowned_entities(monkeypatch):
    """Unlike the other relationships.py findings (client_id, gated by
    core.authz), this one is entity_id ownership checked directly against the
    `entities` table inside the router — exercised with a real (non-mock) db
    so the .eq("firm_id", ...) filter actually runs.

    Mirrors create_relationship's pre-existing identical .single() pattern
    exactly (not introducing new error-handling behavior) — the FakeDB
    harness's .single() raises on a zero-row match (mimicking real
    PostgREST's PGRST116), same as it would for create_relationship's own
    from_e/to_e checks today. The point under test is that the write is
    blocked at all, not the exact exception shape."""
    db = FakeDB()
    monkeypatch.setattr(relationships_router, "_db", lambda: db)
    db.seed("entities", {"id": "e-owned", "firm_id": "F1"})
    db.seed("entities", {"id": "e-foreign", "firm_id": "F2"})
    body = EntityToEntityRelIn(from_entity_id="e-owned", to_entity_id="e-foreign",
                               relationship_type="subsidiary")
    with pytest.raises(Exception):
        relationships_router.create_entity_to_entity_relationship(body, PARTNER_F1)
    assert db.rows("entity_to_entity_relationships") == []


def test_create_entity_to_entity_relationship_accepts_owned_entities(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(relationships_router, "_db", lambda: db)
    db.seed("entities", {"id": "e1", "firm_id": "F1"})
    db.seed("entities", {"id": "e2", "firm_id": "F1"})
    body = EntityToEntityRelIn(from_entity_id="e1", to_entity_id="e2", relationship_type="subsidiary")
    result = relationships_router.create_entity_to_entity_relationship(body, PARTNER_F1)
    assert result["success"] is True
    assert len(db.rows("entity_to_entity_relationships")) == 1
