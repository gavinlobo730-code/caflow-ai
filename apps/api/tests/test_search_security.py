"""
Module 9.0 / M2 — search authorization.

Verifies the server-side /api/search only returns clients within the caller's
effective client set — an unassigned client is not discoverable.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.search as search_mod
from routers.search import router as search_router
from core.auth import get_current_user

CLIENTS = [
    {"id": "C1", "client_name": "Mehta Textiles", "pan": "AAAAA1111A", "gstin": "27AAAAA1111A1Z5", "entity_type": "Pvt Ltd"},
    {"id": "C2", "client_name": "Mehta Logistics", "pan": "BBBBB2222B", "gstin": "27BBBBB2222B1Z5", "entity_type": "LLP"},
]


def _client(user, monkeypatch, effective):
    monkeypatch.setattr(search_mod.client_repo, "find_all", lambda **kw: list(CLIENTS))
    monkeypatch.setattr(search_mod, "effective_client_ids", lambda u: effective)
    app = FastAPI()
    app.include_router(search_router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


PARTNER = {"id": "p", "firm_id": "F1", "role": "Partner"}
EXEC = {"id": "e", "firm_id": "F1", "role": "Executive"}


def test_partner_sees_all_matches(monkeypatch):
    c = _client(PARTNER, monkeypatch, None)  # None ⇒ firm-wide
    r = c.get("/api/search?q=Mehta").json()
    ids = {x["id"] for x in r["data"]["results"]}
    assert ids == {"C1", "C2"}


def test_executive_only_sees_assigned(monkeypatch):
    c = _client(EXEC, monkeypatch, {"C1"})  # assigned to C1 only
    r = c.get("/api/search?q=Mehta").json()
    ids = {x["id"] for x in r["data"]["results"]}
    assert ids == {"C1"}                      # C2 not discoverable


def test_unassigned_client_not_discoverable_by_identifier(monkeypatch):
    # Searching C2's PAN must return nothing for an executive not assigned to it.
    c = _client(EXEC, monkeypatch, {"C1"})
    r = c.get("/api/search?q=BBBBB2222B").json()
    assert r["data"]["results"] == []


def test_short_query_returns_empty(monkeypatch):
    c = _client(PARTNER, monkeypatch, None)
    assert c.get("/api/search?q=a").json()["data"]["results"] == []
