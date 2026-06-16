"""
Platform Admin authorization tests — the security-critical surface.

Verifies that platform endpoints are gated by the platform_admins allowlist
(separate from firm RBAC): non-admins get 404 (cannot even discover the surface),
admins pass, and destructive actions additionally require MFA (aal2). No DB needed
— the allowlist lookup is stubbed; the happy-path data behaviour is verified
separately against the live database.
"""
import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

import core.platform_auth as pa
from core.auth import get_jwt_user


def _client(monkeypatch, *, is_admin: bool, aal: str = "aal1"):
    monkeypatch.setattr(pa, "_is_platform_admin", lambda uid: is_admin)
    app = FastAPI()

    @app.get("/guarded")
    def guarded(_a: dict = Depends(pa.require_platform_admin)):
        return {"ok": True}

    @app.post("/destructive")
    def destructive(_a: dict = Depends(pa.require_platform_admin_mfa)):
        return {"ok": True}

    @app.get("/me")
    def me(ctx: dict = Depends(pa.is_platform_admin)):
        return {"is_platform_admin": ctx["is_platform_admin"]}

    app.dependency_overrides[get_jwt_user] = lambda: {"auth_user_id": "u1", "email": "x@y.z", "aal": aal}
    return TestClient(app, raise_server_exceptions=False)


# ── Deny-by-default for non-platform-admins (firm Partner/Manager/etc.) ───────
def test_non_admin_gets_404_not_403(monkeypatch):
    c = _client(monkeypatch, is_admin=False)
    assert c.get("/guarded").status_code == 404          # cannot even discover the surface
    assert c.post("/destructive").status_code == 404


def test_admin_passes_read_guard(monkeypatch):
    c = _client(monkeypatch, is_admin=True, aal="aal1")
    assert c.get("/guarded").status_code == 200


# ── MFA step-up on destructive actions ───────────────────────────────────────
def test_destructive_requires_aal2(monkeypatch):
    c = _client(monkeypatch, is_admin=True, aal="aal1")
    r = c.post("/destructive")
    assert r.status_code == 403
    assert "Multi-factor" in r.json()["detail"]


def test_destructive_allowed_with_aal2(monkeypatch):
    c = _client(monkeypatch, is_admin=True, aal="aal2")
    assert c.post("/destructive").status_code == 200


# ── /me gating boolean ────────────────────────────────────────────────────────
def test_me_reports_admin_status(monkeypatch):
    assert _client(monkeypatch, is_admin=True).get("/me").json()["is_platform_admin"] is True
    assert _client(monkeypatch, is_admin=False).get("/me").json()["is_platform_admin"] is False


# ── Router imports cleanly + no firm-RBAC coupling ───────────────────────────
def test_platform_router_imports_and_is_rbac_independent():
    import importlib
    mod = importlib.import_module("routers.platform")
    assert mod.router.prefix == "/api/platform"
    src = open(mod.__file__).read()
    # Platform authz must not reach into the firm RBAC engine.
    assert "core.permissions" not in src and "from core.authz" not in src
