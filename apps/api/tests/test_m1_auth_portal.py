"""
Module 9.0 / M1 — active-user enforcement + portal authentication.

- get_current_user must reject a disabled (is_active=False) account even with a
  valid, unexpired JWT, and must default a missing role to least privilege.
- The /api/portal/* endpoints (previously unauthenticated) must now enforce RBAC.
"""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import core.auth as auth
from core.auth import get_current_user
from routers.portal import router as portal_router


# ── Active-user enforcement (get_current_user) ───────────────────────────────

class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, data):
        self._data = data
    def select(self, *_a, **_k):  return self
    def eq(self, *_a, **_k):      return self
    def single(self):            return self
    def maybe_single(self):      return self
    def execute(self):           return _FakeResult(self._data)


class _FakeSupabase:
    def __init__(self, data):
        self._data = data
    def table(self, _name):
        return _FakeQuery(self._data)


def _patch_auth(monkeypatch, user_row):
    """Make get_current_user take the real (non-dev) JWT path with mocked deps."""
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")

    class _Key:  key = "k"
    class _JWKS:
        def get_signing_key_from_jwt(self, _t):  return _Key()
    monkeypatch.setattr(auth, "_get_jwks_client", lambda: _JWKS())
    monkeypatch.setattr(auth.jwt, "decode",
                        lambda *a, **k: {"sub": "auth-1", "email": "u@firm.com"})
    monkeypatch.setattr(auth, "get_service_supabase", lambda: _FakeSupabase(user_row))
    # R3.5e: get_current_user() now caches the users/firms lookup by
    # auth_user_id. These tests all reuse the same sub ("auth-1") with
    # different mocked rows, so each test needs a clean cache.
    monkeypatch.setattr(auth, "_user_lookup_cache", {})


def test_disabled_user_is_rejected(monkeypatch):
    _patch_auth(monkeypatch, {"firm_id": "F1", "role": "Partner", "is_active": False})
    with pytest.raises(HTTPException) as ei:
        get_current_user(authorization="Bearer x")
    assert ei.value.status_code == 403
    assert "disabled" in ei.value.detail.lower()


def test_active_user_is_allowed(monkeypatch):
    _patch_auth(monkeypatch, {"firm_id": "F1", "role": "Partner", "is_active": True})
    user = get_current_user(authorization="Bearer x")
    assert user["role"] == "Partner"
    assert user["firm_id"] == "F1"


def test_missing_is_active_defaults_to_allowed(monkeypatch):
    # Rows predating the is_active column (no key) must not be blocked.
    _patch_auth(monkeypatch, {"firm_id": "F1", "role": "Manager"})
    assert get_current_user(authorization="Bearer x")["role"] == "Manager"


def test_missing_role_defaults_to_least_privilege(monkeypatch):
    _patch_auth(monkeypatch, {"firm_id": "F1", "is_active": True})
    assert get_current_user(authorization="Bearer x")["role"] == "Reviewer"


# ── Portal authentication / authorization ────────────────────────────────────

def _portal_client(user):
    app = FastAPI()
    app.include_router(portal_router)
    if user is None:
        def _raise():
            raise HTTPException(status_code=401, detail="no auth")
        app.dependency_overrides[get_current_user] = _raise
    else:
        app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


PARTNER = {"firm_id": "F1", "role": "Partner", "auth_user_id": "p"}
REVIEWER = {"firm_id": "F1", "role": "Reviewer", "auth_user_id": "r"}
CLIENT = {"firm_id": "F1", "role": "Client", "auth_user_id": "c"}

DOC_REQ_URL = "/api/portal/document-requests?firm_id=F1&client_id=C1"


def test_portal_requires_authentication():
    # No valid auth → 401 (previously these endpoints were wide open).
    assert _portal_client(None).get(DOC_REQ_URL).status_code == 401


def test_portal_read_allowed_for_staff():
    assert _portal_client(PARTNER).get(DOC_REQ_URL).status_code == 200
    assert _portal_client(REVIEWER).get(DOC_REQ_URL).status_code == 200


def test_portal_denied_for_client_role():
    # The Client role is NOT firm staff and must not reach the CA-facing portal API.
    assert _portal_client(CLIENT).get(DOC_REQ_URL).status_code == 403


def test_portal_write_denied_for_reviewer():
    # Reviewer is read-only on the portal (portal:write = Executive+).
    body = {"firm_id": "F1", "client_id": "C1", "title": "Upload PAN"}
    assert _portal_client(REVIEWER).post("/api/portal/document-requests", json=body).status_code == 403
    assert _portal_client(PARTNER).post("/api/portal/document-requests", json=body).status_code == 200
