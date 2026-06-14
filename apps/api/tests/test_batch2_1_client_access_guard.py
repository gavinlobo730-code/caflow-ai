"""
Batch 2.1 — G1 by-id router guard (require_client_access).

Verifies the shared guard that main.py attaches to client-scoped routers via
include_router(dependencies=[...]): a non-Partner who supplies the internal
client's id (in path OR query) gets 404, while Partners and all external-client
access pass through. Uses the real require_client_access with dependency
overrides (no DB needed).
"""
import pytest
from fastapi import FastAPI, APIRouter, Depends, Query
from fastapi.testclient import TestClient

import services.internal_client_service as ics
from core.auth import get_current_user

PARTNER = {"firm_id": "F1", "role": "Partner", "auth_user_id": "p"}
STAFF = {"firm_id": "F1", "role": "Executive", "auth_user_id": "s"}


def _make_client(user, monkeypatch):
    # The firm's internal client id is "INT".
    monkeypatch.setattr(ics, "get_internal_client_id", lambda firm_id: "INT")

    app = FastAPI()
    r = APIRouter()

    @r.get("/api/timeline")
    def timeline(client_id: str = Query(...)):
        return {"ok": True}

    @r.get("/api/clients/{client_id}")
    def workspace(client_id: str):
        return {"ok": True}

    @r.get("/api/firmwide")
    def firmwide():
        return {"ok": True}

    # Applied exactly as main.py does it.
    app.include_router(r, dependencies=[Depends(ics.require_client_access)])
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


def test_staff_blocked_from_internal_via_query(monkeypatch):
    c = _make_client(STAFF, monkeypatch)
    assert c.get("/api/timeline?client_id=INT").status_code == 404
    assert c.get("/api/timeline?client_id=EXT").status_code == 200


def test_staff_blocked_from_internal_via_path(monkeypatch):
    c = _make_client(STAFF, monkeypatch)
    assert c.get("/api/clients/INT").status_code == 404
    assert c.get("/api/clients/EXT").status_code == 200


def test_partner_allowed_internal(monkeypatch):
    c = _make_client(PARTNER, monkeypatch)
    assert c.get("/api/timeline?client_id=INT").status_code == 200
    assert c.get("/api/clients/INT").status_code == 200


def test_firmwide_endpoints_unaffected(monkeypatch):
    # No client_id param -> guard is a no-op for everyone.
    assert _make_client(STAFF, monkeypatch).get("/api/firmwide").status_code == 200
    assert _make_client(PARTNER, monkeypatch).get("/api/firmwide").status_code == 200


def test_app_imports_cleanly():
    # Catches wiring/import errors introduced in main.py.
    import importlib
    import main
    importlib.reload(main)
    assert main.app is not None
