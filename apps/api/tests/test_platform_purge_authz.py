"""
P0 security hotfix regression — platform_purge_firm authorization (audit C7).

Defense has three layers; this suite covers the two that run without a database
(the application layer). The SQL-grant layer and the in-body SECURITY DEFINER
guard are verified against the live database (see the hotfix deliverable) and by
migrations/141_hotfix_platform_purge_firm_authz.sql.

Layer under test here — the API gate on DELETE /api/platform/firms/{id}/permanent:
  * anonymous / non-platform-admin  → 404 (surface not even discoverable)
  * platform admin WITHOUT MFA      → 403 (aal2 required)
  * platform admin WITH MFA         → reaches platform_purge_firm exactly once
An unauthorized caller can therefore never reach the purge RPC at all.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.platform_auth as pa
import routers.platform as plat
from core.auth import get_jwt_user


class _FakeQuery:
    def __init__(self, firm):
        self._firm = firm
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def maybe_single(self): return self
    def insert(self, *a, **k): return self
    def execute(self):
        class R:  # firms lookup returns the firm; platform_audit insert returns nothing
            data = self._firm
        return R()


class _FakeDB:
    """Minimal service-role client double: firm lookup + rpc recorder + audit insert."""
    def __init__(self, firm):
        self._firm = firm
        self.rpc_calls = []
    def table(self, name):
        return _FakeQuery(self._firm if name == "firms" else None)
    def rpc(self, fn, params):
        self.rpc_calls.append((fn, params))
        class _R:
            def execute(self_inner):
                class R: data = {"firm_id": params.get("p_firm_id"), "clients_deleted": 0, "users_deleted": 0}
                return R()
        return _R()


def _client(monkeypatch, *, is_admin: bool, aal: str = "aal2", fake_db: "_FakeDB | None" = None):
    monkeypatch.setattr(pa, "_is_platform_admin", lambda uid: is_admin)
    if fake_db is not None:
        monkeypatch.setattr(plat, "get_service_supabase", lambda: fake_db)
        monkeypatch.setattr(plat, "log_event", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(plat.router)
    app.dependency_overrides[get_jwt_user] = lambda: {"auth_user_id": "u1", "email": "x@y.z", "aal": aal}
    return TestClient(app, raise_server_exceptions=False)


_PURGE = "/api/platform/firms/FIRM-1/permanent"


def test_anonymous_or_non_admin_cannot_reach_purge(monkeypatch):
    c = _client(monkeypatch, is_admin=False)
    assert c.delete(_PURGE).status_code == 404       # cannot even discover the endpoint


def test_platform_admin_without_mfa_cannot_purge(monkeypatch):
    c = _client(monkeypatch, is_admin=True, aal="aal1")
    r = c.delete(_PURGE)
    assert r.status_code == 403
    assert "Multi-factor" in r.json()["detail"]


def test_platform_admin_with_mfa_reaches_purge_rpc_once(monkeypatch):
    db = _FakeDB(firm={"id": "FIRM-1", "name": "Acme & Co"})
    c = _client(monkeypatch, is_admin=True, aal="aal2", fake_db=db)
    r = c.delete(_PURGE)
    assert r.status_code == 200 and r.json()["success"] is True
    # The purge is delegated to the guarded RPC exactly once, with the firm id.
    assert db.rpc_calls == [("platform_purge_firm", {"p_firm_id": "FIRM-1"})]


def test_missing_firm_is_404_even_for_admin(monkeypatch):
    db = _FakeDB(firm=None)                            # firm lookup returns nothing
    c = _client(monkeypatch, is_admin=True, aal="aal2", fake_db=db)
    assert c.delete(_PURGE).status_code == 404
    assert db.rpc_calls == []                          # never reaches the purge RPC
