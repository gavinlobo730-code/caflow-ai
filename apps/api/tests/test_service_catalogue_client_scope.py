"""
Client-assignment scope (M2) on service_catalogue.py.

The Product/Service catalogue is CLIENT-owned by design (migration 182 —
"Client B must never inherit Client A's products"), but the router never
imported core.authz at all: list_services/create_service/bulk_create_services
took client_id from the query/body and never checked it; update_service/
delete_service/record_service_used are row-addressed and checked only
firm_id — so any Executive/Reviewer/Manager in the firm could list, create,
edit, delete or bump usage on another staff member's assigned client's
products and services.

_assert_service_scope resolves (row_exists, client_id) then applies
can_access_client (not assert_client_access) with ONE fixed message for
every failure branch — missing, wrong firm, and right firm but unassigned
all read identically, in both mock and live mode — mirroring year_end.py's
_assert_engagement_scope / credit_notes.py's _assert_cn_scope, the shape
established earlier in this sweep. list_services/create_service take
client_id directly (query/body), so they use assert_client_access straight,
like sales_invoices.py's list_invoices/create_invoice. bulk_create_services
checks every DISTINCT client_id in the batch up front, before any row is
processed (mirrors sales_invoices.py's own _assert_batch_scope).
"""
import pytest
from fastapi import HTTPException

import routers.service_catalogue as sc
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
EXEC_USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "e@f.test", "role": "Executive"}
MANAGER_USER = {"id": "u2", "firm_id": FIRM, "auth_user_id": "u2", "email": "m@f.test", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow the rest."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(sc, "assert_client_access", _assert)
    monkeypatch.setattr(sc, "can_access_client", _can)
    return seen


@pytest.fixture(autouse=True)
def _clear_mock_store():
    sc.MOCK_SERVICES.clear()


def _row(client_id, service_id, **extra):
    return {"id": service_id, "firm_id": FIRM, "client_id": client_id, "name": "Consulting", "is_active": True, **extra}


# ══════════════════════════════════════════════════════════════════════════
# list_services / create_service / bulk_create_services (client_id known up front)
# ══════════════════════════════════════════════════════════════════════════

def test_listing_services_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        sc.list_services(client_id=THEIRS, current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_listing_services_for_an_own_client_is_allowed(deny):
    resp = sc.list_services(client_id=MINE, q="", include_archived=False, limit=20, current_user=EXEC_USER)
    assert resp["success"] is True


def test_creating_a_service_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        sc.create_service(sc.ServiceCatalogueIn(client_id=THEIRS, name="Consulting"), current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert sc.MOCK_SERVICES == []


def test_creating_a_service_for_an_own_client_is_allowed(deny):
    resp = sc.create_service(sc.ServiceCatalogueIn(client_id=MINE, name="Consulting"), current_user=MANAGER_USER)
    assert resp["success"] is True


def test_bulk_creating_services_with_any_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        sc.bulk_create_services(
            sc.ServiceBulkIn(services=[{"client_id": MINE, "name": "A"}, {"client_id": THEIRS, "name": "B"}]),
            current_user=MANAGER_USER,
        )
    assert exc.value.status_code == 404
    # All-or-nothing: the scope check runs before any row is processed, so
    # not even the MINE row from this mixed batch was written.
    assert sc.MOCK_SERVICES == []


def test_bulk_creating_services_for_own_clients_is_allowed(deny):
    resp = sc.bulk_create_services(
        sc.ServiceBulkIn(services=[{"client_id": MINE, "name": "A"}]),
        current_user=MANAGER_USER,
    )
    assert resp["success"] is True
    assert len(resp["data"]["created"]) == 1


# ══════════════════════════════════════════════════════════════════════════
# update_service / delete_service / record_service_used (row-addressed)
# ══════════════════════════════════════════════════════════════════════════

def test_updating_a_hidden_clients_service_is_refused(deny):
    sc.MOCK_SERVICES.append(_row(THEIRS, "SVC1"))
    with pytest.raises(HTTPException) as exc:
        sc.update_service("SVC1", sc.ServiceCatalogueUpdateIn(notes="x"), current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert sc.MOCK_SERVICES[0].get("notes") is None


def test_updating_an_own_clients_service_is_allowed(deny):
    sc.MOCK_SERVICES.append(_row(MINE, "SVC1"))
    resp = sc.update_service("SVC1", sc.ServiceCatalogueUpdateIn(notes="x"), current_user=MANAGER_USER)
    assert resp["success"] is True


def test_deleting_a_hidden_clients_service_is_refused(deny):
    sc.MOCK_SERVICES.append(_row(THEIRS, "SVC1"))
    with pytest.raises(HTTPException) as exc:
        sc.delete_service("SVC1", current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert len(sc.MOCK_SERVICES) == 1


def test_deleting_an_own_clients_service_is_allowed(deny):
    sc.MOCK_SERVICES.append(_row(MINE, "SVC1"))
    resp = sc.delete_service("SVC1", current_user=MANAGER_USER)
    assert resp["success"] is True


def test_recording_usage_for_a_hidden_clients_service_is_refused(deny):
    sc.MOCK_SERVICES.append(_row(THEIRS, "SVC1", use_count=0))
    with pytest.raises(HTTPException) as exc:
        sc.record_service_used("SVC1", current_user=EXEC_USER)
    assert exc.value.status_code == 404
    assert sc.MOCK_SERVICES[0]["use_count"] == 0


def test_recording_usage_for_an_own_clients_service_is_allowed(deny):
    sc.MOCK_SERVICES.append(_row(MINE, "SVC1", use_count=0))
    resp = sc.record_service_used("SVC1", current_user=EXEC_USER)
    assert resp["success"] is True


def test_hidden_and_missing_service_errors_match(deny):
    # Same id in both scenarios — absent from the store, then present but
    # belonging to another client — so the message can only differ if the
    # wording itself differs between the two branches.
    with pytest.raises(HTTPException) as exc_missing:
        sc.update_service("SVC1", sc.ServiceCatalogueUpdateIn(notes="x"), current_user=EXEC_USER)
    sc.MOCK_SERVICES.append(_row(THEIRS, "SVC1"))
    with pytest.raises(HTTPException) as exc_hidden:
        sc.update_service("SVC1", sc.ServiceCatalogueUpdateIn(notes="x"), current_user=EXEC_USER)
    assert exc_missing.value.status_code == exc_hidden.value.status_code == 404
    assert exc_missing.value.detail == exc_hidden.value.detail


# ══════════════════════════════════════════════════════════════════════════
# Live-mode (FakeDB) — exercises _assert_service_scope's own SQL lookup
# branch, not just the mock-store branch above. can_access_client stays
# patched by `deny`; FakeDB only backs the resolver's own row fetch — same
# split as test_notes_client_scope.py's e2e tests.
# ══════════════════════════════════════════════════════════════════════════

def _e2e_setup(monkeypatch, modules):
    db = FakeDB()
    wire_e2e(monkeypatch, db, modules)
    return db


def test_e2e_updating_a_hidden_clients_service_is_refused(deny, monkeypatch):
    db = _e2e_setup(monkeypatch, [sc])
    db.seed("service_catalogue", {"id": "SVC1", "firm_id": FIRM, "client_id": THEIRS, "name": "Consulting", "is_active": True})
    with pytest.raises(HTTPException) as exc:
        sc.update_service("SVC1", sc.ServiceCatalogueUpdateIn(notes="x"), current_user=EXEC_USER)
    assert exc.value.status_code == 404
    assert deny == [THEIRS]


def test_e2e_updating_an_own_clients_service_is_allowed(deny, monkeypatch):
    db = _e2e_setup(monkeypatch, [sc])
    db.seed("service_catalogue", {"id": "SVC1", "firm_id": FIRM, "client_id": MINE, "name": "Consulting", "is_active": True})
    resp = sc.update_service("SVC1", sc.ServiceCatalogueUpdateIn(notes="x"), current_user=EXEC_USER)
    assert resp["success"] is True
    assert deny == [MINE]


def test_e2e_deleting_a_hidden_clients_service_is_refused(deny, monkeypatch):
    db = _e2e_setup(monkeypatch, [sc])
    db.seed("service_catalogue", {"id": "SVC1", "firm_id": FIRM, "client_id": THEIRS, "name": "Consulting", "is_active": True})
    with pytest.raises(HTTPException) as exc:
        sc.delete_service("SVC1", current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert deny == [THEIRS]


def test_e2e_missing_and_hidden_services_use_the_identical_message(deny, monkeypatch):
    db = _e2e_setup(monkeypatch, [sc])
    db.seed("service_catalogue", {"id": "SVC-THEIRS", "firm_id": FIRM, "client_id": THEIRS, "name": "X", "is_active": True})
    with pytest.raises(HTTPException) as missing:
        sc._assert_service_scope(EXEC_USER, "SVC-NOPE")
    with pytest.raises(HTTPException) as hidden:
        sc._assert_service_scope(EXEC_USER, "SVC-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail
