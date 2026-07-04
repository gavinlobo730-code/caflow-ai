"""M6 — session revocation (forced logout) + MFA enforcement (flag-gated)."""
import pytest
from fastapi import HTTPException

import core.auth as auth
import core.security_config as cfg


# ── helpers to drive the real get_current_user JWT path ──────────────────────

class _Res:
    def __init__(self, data): self.data = data
class _Q:
    def __init__(self, d): self._d = d
    def select(self,*a,**k): return self
    def eq(self,*a,**k): return self
    def single(self): return self
    def execute(self): return _Res(self._d)
class _Supa:
    def __init__(self, d): self._d = d
    def table(self,_n): return _Q(self._d)


def _patch(monkeypatch, row, payload):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    class _K: key="k"
    class _J:
        def get_signing_key_from_jwt(self,_t): return _K()
    monkeypatch.setattr(auth, "_get_jwks_client", lambda: _J())
    monkeypatch.setattr(auth.jwt, "decode", lambda *a, **k: payload)
    monkeypatch.setattr(auth, "get_service_supabase", lambda: _Supa(row))
    # R3.5e: get_current_user() now caches the users/firms lookup by
    # auth_user_id. These tests all use the same sub ("a") with different
    # mocked rows to test different revocation states, so each test needs a
    # clean cache — otherwise test order would leak a stale row across tests.
    monkeypatch.setattr(auth, "_user_lookup_cache", {})


# ── Session revocation ────────────────────────────────────────────────────────

def test_token_issued_before_revocation_is_rejected(monkeypatch):
    # sessions_revoked_at is AFTER the token iat → reject.
    _patch(monkeypatch,
           {"id": "u", "firm_id": "F1", "role": "Partner", "is_active": True,
            "sessions_revoked_at": "2030-01-01T00:00:00+00:00"},
           {"sub": "a", "iat": 100, "email": "e@f"})
    with pytest.raises(HTTPException) as ei:
        auth.get_current_user(authorization="Bearer x")
    assert ei.value.status_code == 401
    assert "revoked" in ei.value.detail.lower()


def test_token_issued_after_revocation_is_accepted(monkeypatch):
    import time
    _patch(monkeypatch,
           {"id": "u", "firm_id": "F1", "role": "Partner", "is_active": True,
            "sessions_revoked_at": "2020-01-01T00:00:00+00:00"},
           {"sub": "a", "iat": int(time.time()), "email": "e@f"})
    assert auth.get_current_user(authorization="Bearer x")["role"] == "Partner"


def test_no_revocation_timestamp_is_accepted(monkeypatch):
    _patch(monkeypatch,
           {"id": "u", "firm_id": "F1", "role": "Partner", "is_active": True},
           {"sub": "a", "iat": 100, "email": "e@f"})
    assert auth.get_current_user(authorization="Bearer x")["aal"] == "aal1"


# ── MFA enforcement (flag-gated) ────────────────────────────────────────────────

def test_mfa_off_is_passthrough(monkeypatch):
    monkeypatch.delenv("REQUIRE_MFA", raising=False)
    assert cfg.require_mfa() is False
    user = {"role": "Partner", "aal": "aal1"}
    assert auth.mfa_guard(user) is user  # no raise


def test_mfa_on_blocks_aal1_for_required_role(monkeypatch):
    monkeypatch.setenv("REQUIRE_MFA", "true")
    monkeypatch.setenv("MFA_REQUIRED_ROLES", "Partner")
    with pytest.raises(HTTPException) as ei:
        auth.mfa_guard({"role": "Partner", "aal": "aal1"})
    assert ei.value.status_code == 403


def test_mfa_on_allows_aal2(monkeypatch):
    monkeypatch.setenv("REQUIRE_MFA", "true")
    monkeypatch.setenv("MFA_REQUIRED_ROLES", "Partner")
    assert auth.mfa_guard({"role": "Partner", "aal": "aal2"})["role"] == "Partner"


def test_mfa_on_ignores_non_required_role(monkeypatch):
    monkeypatch.setenv("REQUIRE_MFA", "true")
    monkeypatch.setenv("MFA_REQUIRED_ROLES", "Partner")
    # Executive not in required roles → aal1 allowed.
    assert auth.mfa_guard({"role": "Executive", "aal": "aal1"})["role"] == "Executive"
