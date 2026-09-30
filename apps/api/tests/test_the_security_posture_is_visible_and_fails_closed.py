"""The two safety switches fail CLOSED in production, and the deployment can say so.

SECURITY-PRIVACY-16 / OPS-06

WHAT WAS WRONG
    `USE_USER_JWT` (row-level security on the API path) and `REQUIRE_MFA` both
    defaulted to false in code and are `sync: false` in render.yaml, so their
    production values lived only in the Render dashboard. An UNSET pair caused the
    outage of 2026-08-15, and the quiet half of that failure — unset
    USE_USER_JWT means `service_role`, which bypasses RLS on every request —
    could come back with nothing to show for it.

WHAT THESE PIN
    * with APP_ENV=production an unset, blank or unrecognisable value means ON;
      an explicit false is still honoured (it is the operator's rollback) and is
      logged at ERROR;
    * outside production nothing moved — the suite and every local run leave
      APP_ENV unset, and they must keep exercising what they always did;
    * the boot validator logs an ERROR and reports a false flag where production
      has a switch explicitly off, and names the gap the defaults cannot close
      (a deployment that never declared APP_ENV);
    * the posture a probe can see is booleans only and carries no secret;
    * the Partner-only endpoint is mounted on the real app, refuses every other
      role, and sits behind the MFA guard.
"""
from __future__ import annotations

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.config_validation as cv
import core.security_config as sc
from core import security_posture as sp
from core.auth import get_current_user
from routers.security_policy import router as security_router

_ENV = (
    "APP_ENV", "USE_USER_JWT", "REQUIRE_MFA", "MFA_REQUIRED_ROLES", "SUPABASE_URL",
    "SUPABASE_ANON_KEY", "NEXT_PUBLIC_SUPABASE_ANON_KEY", "ENABLE_SCHEDULER",
    "ALLOWED_ORIGINS", "FRONTEND_URL", "SUPABASE_SERVICE_ROLE_KEY",
)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)


def _production(monkeypatch, **env):
    monkeypatch.setenv("APP_ENV", "production")
    for k, v in env.items():
        monkeypatch.setenv(k, v)


# ── the defaults ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [None, "", "   ", "ture", "disabled", "maybe"])
def test_in_production_an_unset_or_unreadable_switch_means_on(monkeypatch, value):
    _production(monkeypatch)
    for name in ("USE_USER_JWT", "REQUIRE_MFA"):
        if value is not None:
            monkeypatch.setenv(name, value)
    assert sc.use_user_jwt() is True
    assert sc.require_mfa() is True


@pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "off", " false "])
def test_in_production_an_explicit_false_is_still_honoured(monkeypatch, value):
    """The operator's own rollback. Overriding it would make a broken user-JWT
    path (grants, anon key) unrecoverable without a deploy."""
    _production(monkeypatch, USE_USER_JWT=value, REQUIRE_MFA=value)
    assert sc.use_user_jwt() is False
    assert sc.require_mfa() is False


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
def test_an_explicit_true_is_on_everywhere(monkeypatch, value):
    monkeypatch.setenv("USE_USER_JWT", value)
    monkeypatch.setenv("REQUIRE_MFA", value)
    assert sc.use_user_jwt() is True and sc.require_mfa() is True


@pytest.mark.parametrize("env", [None, "development", "test", "staging", "Prod", "production "])
def test_outside_production_nothing_moved(monkeypatch, env):
    """`production` is the LITERAL word. The unit-test suite and every local run
    leave APP_ENV unset, and turning MFA and the per-user client on for them
    would change what they exercise — test_session_mfa asserts the default is
    off. ("production " with a trailing space IS production: the read strips.)"""
    if env is not None:
        monkeypatch.setenv("APP_ENV", env)
    expect_on = env is not None and env.strip().lower() == "production"
    assert sc.use_user_jwt() is expect_on
    assert sc.require_mfa() is expect_on


def test_the_guard_asks_the_same_switch(monkeypatch):
    """mfa_guard must read the resolved value, not a second copy of the default."""
    from fastapi import HTTPException
    import core.auth as auth

    _production(monkeypatch)
    with pytest.raises(HTTPException) as ei:
        auth.mfa_guard({"role": "Partner", "aal": "aal1"})
    assert ei.value.status_code == 403
    assert auth.mfa_guard({"role": "Partner", "aal": "aal2"})["role"] == "Partner"


# ── the boot validator ───────────────────────────────────────────────────────

def _security_records(caplog, level):
    return [r for r in caplog.records
            if r.name == "caflow.config" and r.levelno == level
            and "CONFIG SECURITY" in r.getMessage()]


def test_the_validator_logs_an_error_and_reports_a_false_flag(monkeypatch, caplog):
    _production(monkeypatch, USE_USER_JWT="false", REQUIRE_MFA="true",
                SUPABASE_ANON_KEY="anon-key", ENABLE_SCHEDULER="true",
                ALLOWED_ORIGINS="https://app.example", FRONTEND_URL="https://app.example")
    caplog.set_level(logging.INFO, logger="caflow.config")

    result = cv.validate_config()["security"]

    assert result["use_user_jwt"] is False
    assert result["ok"] is False
    errors = _security_records(caplog, logging.ERROR)
    assert any("use_user_jwt_off" in r.getMessage() for r in errors), [r.getMessage() for r in errors]
    assert [p["code"] for p in result["problems"] if p["level"] == "error"] == ["use_user_jwt_off"]


def test_the_validator_is_quiet_about_errors_when_production_is_right(monkeypatch, caplog):
    _production(monkeypatch, USE_USER_JWT="true", REQUIRE_MFA="true",
                SUPABASE_ANON_KEY="anon-key", ENABLE_SCHEDULER="true",
                ALLOWED_ORIGINS="https://app.example", FRONTEND_URL="https://app.example")
    caplog.set_level(logging.INFO, logger="caflow.config")

    result = cv.validate_config()["security"]

    assert result["ok"] is True and result["problems"] == []
    assert _security_records(caplog, logging.ERROR) == []
    assert _security_records(caplog, logging.WARNING) == []


def test_an_unset_pair_is_defaulted_on_and_says_so_without_shouting(monkeypatch, caplog):
    """The OPS-06 scenario, after SECURITY-PRIVACY-16: unset no longer leaves the
    flag false, so there is no ERROR — but the decision is undocumented, which a
    Partner is told."""
    _production(monkeypatch, SUPABASE_ANON_KEY="anon-key", ENABLE_SCHEDULER="true",
                ALLOWED_ORIGINS="https://app.example", FRONTEND_URL="https://app.example")
    caplog.set_level(logging.INFO, logger="caflow.config")

    result = cv.validate_config()["security"]

    assert result["use_user_jwt"] is True and result["require_mfa"] is True
    assert result["use_user_jwt_explicit"] is False
    assert result["ok"] is True
    assert _security_records(caplog, logging.ERROR) == []
    codes = {p["code"] for p in result["problems"]}
    assert {"use_user_jwt_not_set", "require_mfa_not_set"} <= codes


def test_the_gap_the_defaults_cannot_close_is_an_error(monkeypatch, caplog):
    """A real deployment that never declared APP_ENV: the defaults key on the
    literal "production", so both would silently fall back to off."""
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    caplog.set_level(logging.INFO, logger="caflow.config")

    result = cv.validate_config()["security"]

    assert result["use_user_jwt"] is False and result["require_mfa"] is False
    assert result["ok"] is False
    assert any("app_env_not_declared" in r.getMessage()
               for r in _security_records(caplog, logging.ERROR))


def test_nothing_is_judged_outside_production(monkeypatch, caplog):
    monkeypatch.setenv("APP_ENV", "development")
    caplog.set_level(logging.INFO, logger="caflow.config")
    result = cv.validate_config()["security"]
    assert result["ok"] is True and result["problems"] == []
    assert _security_records(caplog, logging.ERROR) == []


def test_user_jwt_without_an_anon_key_is_an_error(monkeypatch):
    _production(monkeypatch, USE_USER_JWT="true", REQUIRE_MFA="true")
    result = sp.security_posture()
    assert result["ok"] is False
    assert "anon_key_missing" in {p["code"] for p in result["problems"]}
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    assert "anon_key_missing" not in {p["code"] for p in sp.security_posture()["problems"]}


def test_the_other_names_the_finding_lists_are_reported(monkeypatch):
    _production(monkeypatch, USE_USER_JWT="true", REQUIRE_MFA="true", SUPABASE_ANON_KEY="a")
    codes = {p["code"] for p in sp.security_posture()["problems"]}
    assert {"scheduler_disabled", "allowed_origins_not_set", "frontend_url_not_set"} <= codes
    # ...but a forgotten scheduler is operational: it must not report the
    # SECURITY posture as broken.
    assert sp.security_posture()["ok"] is True


def test_validation_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("env exploded")
    monkeypatch.setattr(sp, "security_posture", boom)
    out = sp.validate_security_posture()
    assert out["ok"] is False and out["assessed"] is False


# ── what a probe can see ─────────────────────────────────────────────────────

def test_the_readiness_view_is_booleans_only_and_carries_no_secret(monkeypatch):
    _production(monkeypatch, USE_USER_JWT="true", REQUIRE_MFA="true",
                SUPABASE_URL="https://secret-project.supabase.co",
                SUPABASE_ANON_KEY="anon-key-SECRET",
                SUPABASE_SERVICE_ROLE_KEY="service-key-SECRET",
                ALLOWED_ORIGINS="https://private-origin.example",
                FRONTEND_URL="https://private-frontend.example")
    flags = sp.readiness_flags()
    assert flags and all(isinstance(v, bool) for v in flags.values()), flags
    full = json.dumps(sp.security_posture())
    for secret in ("SECRET", "secret-project", "private-origin", "private-frontend"):
        assert secret not in full, f"{secret!r} leaked into the posture"


# ── the endpoint ─────────────────────────────────────────────────────────────

def _client(role: str, aal: str = "aal2") -> TestClient:
    app = FastAPI()
    app.include_router(security_router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u1", "auth_user_id": "a1", "firm_id": "F1", "role": role, "aal": aal,
        "permission_overrides": {},
    }
    return TestClient(app)


def test_a_partner_reads_the_posture(monkeypatch):
    _production(monkeypatch)
    res = _client("Partner").get("/api/security/posture")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True and body["error"] is None
    assert body["data"]["use_user_jwt"] is True
    assert body["data"]["require_mfa"] is True
    assert body["data"]["app_env_is_production"] is True
    # SECURITY-PRIVACY-26's half, so the one place that answers "what is exposed"
    # says the schema is not.
    assert body["data"]["api_docs_public"] is False


@pytest.mark.parametrize("role", ["Manager", "Executive", "Reviewer"])
def test_nobody_else_reads_it(monkeypatch, role):
    _production(monkeypatch)
    res = _client(role).get("/api/security/posture")
    assert res.status_code == 403, (role, res.status_code)


def test_it_sits_behind_the_mfa_guard(monkeypatch):
    """Firm administration, unlike /mfa-policy whose caller is by construction at
    aal1. A Partner who has not stepped up does not get the deployment's config."""
    _production(monkeypatch)
    assert _client("Partner", aal="aal1").get("/api/security/posture").status_code == 403
    assert _client("Partner", aal="aal2").get("/api/security/posture").status_code == 200


def test_the_posture_is_mounted_on_the_real_app():
    import main
    paths = {getattr(r, "path", None) for r in main.app.routes}
    assert "/api/security/posture" in paths
    assert "/api/security/mfa-policy" in paths
