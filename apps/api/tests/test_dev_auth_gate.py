"""
The dev/test header-auth fallback must stay gated on APP_ENV=development.

core.auth.get_current_user lets X-User-Role / X-Firm-Id / X-User-Id stand in
for a Supabase JWT when SUPABASE_URL is unset. That is what makes the in-memory
test suite possible — and it is also, on its own, a total authentication bypass:
anyone who can set a header could name their own role and firm.

What keeps it safe is the SECOND condition, `APP_ENV == "development"`. A
production deployment has APP_ENV unset (the code defaults to "production"), so
the fallback refuses with 503 rather than trusting the header.

These tests exist because the 44 tests that used the header mode were fixed by
opting into it through a per-module fixture (`dev_header_auth` in conftest)
rather than by relaxing this gate. That decision is only sound while the gate
actually holds, so the gate gets its own test instead of being assumed.

NOTE: this module deliberately does NOT use the dev_header_auth fixture — it
asserts what happens in its ABSENCE.
"""
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)
HEADERS = {"X-User-Role": "partner", "X-Firm-Id": "firm-001", "X-User-Id": "user-001"}


@pytest.fixture
def no_supabase(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)


def test_header_auth_is_refused_when_app_env_is_unset(monkeypatch, no_supabase):
    """APP_ENV unset ⇒ the code's default of "production" ⇒ no header trust."""
    monkeypatch.delenv("APP_ENV", raising=False)

    resp = client.get("/api/clients", headers=HEADERS)

    assert resp.status_code == 503
    assert "SUPABASE_URL not set" in resp.json()["detail"]


@pytest.mark.parametrize("app_env", ["production", "staging", "Development", "dev", ""])
def test_header_auth_is_refused_for_every_non_development_app_env(
    monkeypatch, no_supabase, app_env
):
    """The comparison is exact and case-sensitive. "Development" and "dev" are
    NOT development — a near-miss must fail closed, not open."""
    monkeypatch.setenv("APP_ENV", app_env)

    resp = client.get("/api/clients", headers=HEADERS)

    assert resp.status_code == 503, f"APP_ENV={app_env!r} must not enable header auth"


def test_header_auth_is_allowed_only_in_development(monkeypatch, no_supabase):
    """The positive case — otherwise the tests above would pass against a build
    where the fallback had been removed entirely, and the suite that depends on
    it would be the only thing to notice."""
    monkeypatch.setenv("APP_ENV", "development")

    resp = client.get("/api/clients", headers=HEADERS)

    assert resp.status_code == 200


def test_dev_fallback_does_not_apply_when_supabase_is_configured(monkeypatch):
    """With SUPABASE_URL set, the header mode is off regardless of APP_ENV —
    a real deployment that also had APP_ENV=development must still demand a JWT
    rather than accept a header-named role."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")

    resp = client.get("/api/clients", headers=HEADERS)

    # Not 200: no Authorization header, so it is rejected rather than trusted.
    assert resp.status_code != 200
