"""
Module 9.0 / M3 — assignment administration API + lifecycle→authz enforcement.

Covers all roles (Partner administers; Manager+ reads; Executive/Reviewer/Client
denied write), validation, audit logging, and that creating/removing an assignment
actually flips authorization (access granted/revoked → search/notification/AI all
read the same core.authz primitives).
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.assignments as amod
import repositories.assignment_repository as arepo_mod
from routers.assignments import router as assignments_router
from core.auth import get_current_user

PARTNER = {"id": "p", "firm_id": "F1", "role": "Partner", "email": "p@firm.com"}
MANAGER = {"id": "m", "firm_id": "F1", "role": "Manager", "email": "m@firm.com"}
EXEC = {"id": "e", "firm_id": "F1", "role": "Executive", "email": "e@firm.com"}
REVIEWER = {"id": "r", "firm_id": "F1", "role": "Reviewer", "email": "r@firm.com"}
CLIENT = {"id": "c", "firm_id": "F1", "role": "Client", "email": "c@firm.com"}

_FAKE_CLIENTS = {
    "C1": {"id": "C1", "firm_id": "F1", "is_internal": False},
    "INT": {"id": "INT", "firm_id": "F1", "is_internal": True},
}


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    arepo_mod._MOCK_ASSIGNMENTS.clear()
    # client validation uses client_repo.find_by_id(id, firm_id)
    monkeypatch.setattr(amod.client_repo, "find_by_id",
                        lambda cid, firm_id=None: _FAKE_CLIENTS.get(cid))
    # capture audit events
    audit = []
    monkeypatch.setattr(amod, "log_event",
                        lambda *a, **k: audit.append({"args": a, "kwargs": k}))
    yield audit
    arepo_mod._MOCK_ASSIGNMENTS.clear()


def _client(user):
    app = FastAPI()
    app.include_router(assignments_router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


# ── RBAC: who may administer ──────────────────────────────────────────────────

def test_partner_can_create():
    r = _client(PARTNER).post("/api/assignments", json={"user_id": "e", "client_id": "C1"})
    assert r.status_code == 200
    assert arepo_mod.assignment_repo.list_for_user("F1", "e") == ["C1"]


@pytest.mark.parametrize("user", [EXEC, REVIEWER, CLIENT])
def test_non_partner_cannot_write(user):
    r = _client(user).post("/api/assignments", json={"user_id": "e", "client_id": "C1"})
    assert r.status_code == 403


def test_manager_can_read_not_write():
    assert _client(MANAGER).get("/api/assignments/users/e").status_code == 200
    assert _client(MANAGER).post("/api/assignments", json={"user_id": "e", "client_id": "C1"}).status_code == 403


# ── Validation ────────────────────────────────────────────────────────────────

def test_unknown_client_rejected():
    r = _client(PARTNER).post("/api/assignments", json={"user_id": "e", "client_id": "NOPE"})
    assert r.status_code == 404


def test_internal_client_cannot_be_assigned():
    r = _client(PARTNER).post("/api/assignments", json={"user_id": "e", "client_id": "INT"})
    assert r.status_code == 400


# ── Audit ─────────────────────────────────────────────────────────────────────

def test_create_and_remove_are_audited(_setup):
    audit = _setup
    c = _client(PARTNER)
    c.post("/api/assignments", json={"user_id": "e", "client_id": "C1"})
    c.delete("/api/assignments?user_id=e&client_id=C1")
    actions = [evt["args"][3] for evt in audit]  # positional: (firm, entity_type, entity_id, action)
    assert "create" in actions and "delete" in actions


# ── List views ────────────────────────────────────────────────────────────────

def test_list_views():
    c = _client(PARTNER)
    c.post("/api/assignments", json={"user_id": "e", "client_id": "C1"})
    assert c.get("/api/assignments/users/e").json()["data"]["client_ids"] == ["C1"]
    assert c.get("/api/assignments/clients/C1").json()["data"]["user_ids"] == ["e"]


def test_remove_missing_returns_false():
    r = _client(PARTNER).delete("/api/assignments?user_id=e&client_id=C1")
    assert r.json()["success"] is False


# ── Lifecycle → authorization (access granted/revoked; powers search/notif/AI) ──

def test_assignment_lifecycle_flips_authorization(monkeypatch):
    import core.authz as authz
    from repositories.assignment_repository import assignment_repo
    # Force enforced mode and back authz with the assignment repo's live data.
    monkeypatch.setattr(authz, "_USE_MOCK", False)
    monkeypatch.setattr(authz, "assigned_client_ids",
                        lambda user: set(assignment_repo.list_for_user(user["firm_id"], user["id"])))

    assert authz.can_access_client(EXEC, "C1") is False        # before
    assert authz.effective_client_ids(EXEC) == set()
    assignment_repo.create("F1", "e", "C1")
    assert authz.can_access_client(EXEC, "C1") is True          # access granted
    assert authz.effective_client_ids(EXEC) == {"C1"}
    assignment_repo.remove("F1", "e", "C1")
    assert authz.can_access_client(EXEC, "C1") is False         # access revoked
