"""The security posture, as facts the running process can see about itself.

WHY THIS EXISTS (SECURITY-PRIVACY-16, OPS-06)
    Two switches decide whether row-level security and MFA are really in force,
    and `render.yaml` declares both `sync: false` — the value lives in the
    Render dashboard, where no test and no reader of this repository can see it.
    The only record that production's answer is "true" was a comment. When the
    service was recreated in Singapore on 2026-08-15 both were left unset, and
    the two halves of that failure were very different: the loud half was an
    outage (57 tables granted to `authenticated` only), and the QUIET half —
    USE_USER_JWT unset means `service_role`, which bypasses RLS on every
    request — is the one that can come back without anybody noticing.

    `core/security_config.py` now defaults both ON when `APP_ENV=production`.
    This module is the other half: it says what the process actually resolved,
    logs the ways that resolution is wrong, and is what the Partner-only
    `GET /api/security/posture` serves, so "are the safety switches really on in
    the live system" is a request rather than a trust exercise.

WHAT IT REPORTS AND WHAT IT NEVER DOES
    * **Booleans and counts only.** No key, no URL, no origin string. The
      `problems` list carries a code, a level and a fixed sentence — never a
      value read from the environment.
    * **It never raises and never stops the boot.** `core/config_validation`'s
      contract is "a crash-loop is worse than a clear error line", and a
      deploy must not fail its health check over a setting (which is also why
      none of this is on /health).
    * **Nothing is judged outside production.** A developer running with both
      flags off is not a problem; the same state in production is.

TWO LEVELS, AND THE SPLIT IS NOT COSMETIC
    `error` is a setting that removes a security control or makes the API path
    fail outright. `warning` is a setting that degrades an operational feature
    or leaves a decision undocumented. `ok` is "no error", so a forgotten
    ENABLE_SCHEDULER does not report the security posture as broken.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from core import security_config as sc

_logger = logging.getLogger("caflow.config")

ERROR = "error"
WARNING = "warning"


def _blank(name: str) -> bool:
    return not (os.environ.get(name) or "").strip()


def _scheduler_enabled() -> bool:
    # The same reading jobs/scheduler._scheduler_enabled makes. Restated rather
    # than imported because that module pulls in the whole job stack at import.
    return os.environ.get("ENABLE_SCHEDULER", "").lower() in ("1", "true", "yes")


def _problem(code: str, level: str, message: str) -> dict[str, str]:
    # `tone` is the word the browser's Callout takes ("problem" | "attention"),
    # served so the screen holds no mapping from a level to a colour — the
    # Schedule III caption lesson applied to a severity.
    return {
        "code": code,
        "level": level,
        "tone": "problem" if level == ERROR else "attention",
        "message": message,
    }


def security_posture() -> dict[str, Any]:
    """What this process resolved, and what is wrong with it.

    Safe to call at any time and from any thread: it reads the environment and
    nothing else, and it never raises.
    """
    from core.supabase_client import anon_key
    from core.urls import allowed_origins

    production = sc.is_production()
    jwt_on = sc.use_user_jwt()
    mfa_on = sc.require_mfa()
    jwt_setting = sc.flag_setting("USE_USER_JWT")
    mfa_setting = sc.flag_setting("REQUIRE_MFA")
    anon_present = bool(anon_key())
    scheduler = _scheduler_enabled()
    origins_count = len(allowed_origins())

    problems: list[dict[str, str]] = []

    # APP_ENV being absent is the one gap the production defaults cannot close
    # on their own: they key on the literal "production", because the unit-test
    # suite and every local run leave it unset. core/auth.py reads an unset
    # APP_ENV as production, so the two would disagree exactly here.
    if sc.app_env() == "" and not _blank("SUPABASE_URL"):
        problems.append(_problem(
            "app_env_not_declared", ERROR,
            "APP_ENV is not set on a deployment that talks to Supabase, so the "
            "production defaults for USE_USER_JWT and REQUIRE_MFA do not apply "
            "and both fall back to off. Set APP_ENV=production."))

    if production:
        if jwt_setting is False:
            problems.append(_problem(
                "use_user_jwt_off", ERROR,
                "USE_USER_JWT is explicitly off: the API queries as service_role, "
                "which bypasses row-level security on every request."))
        elif jwt_setting is None:
            if sc.flag_value_unrecognised("USE_USER_JWT"):
                problems.append(_problem(
                    "use_user_jwt_unrecognised", WARNING,
                    "USE_USER_JWT is set to a value that is neither true nor "
                    "false; production treats it as ON. Set it to true."))
            else:
                problems.append(_problem(
                    "use_user_jwt_not_set", WARNING,
                    "USE_USER_JWT is not set; production defaults it to ON. "
                    "Set it to true in the dashboard so the decision is recorded."))

        if mfa_setting is False:
            problems.append(_problem(
                "require_mfa_off", ERROR,
                "REQUIRE_MFA is explicitly off: no role is asked for a second "
                "factor on the administration and payroll routers."))
        elif mfa_setting is None:
            if sc.flag_value_unrecognised("REQUIRE_MFA"):
                problems.append(_problem(
                    "require_mfa_unrecognised", WARNING,
                    "REQUIRE_MFA is set to a value that is neither true nor "
                    "false; production treats it as ON. Set it to true."))
            else:
                problems.append(_problem(
                    "require_mfa_not_set", WARNING,
                    "REQUIRE_MFA is not set; production defaults it to ON. "
                    "Set it to true in the dashboard so the decision is recorded."))

        if jwt_on and not anon_present:
            problems.append(_problem(
                "anon_key_missing", ERROR,
                "USE_USER_JWT is on and no SUPABASE_ANON_KEY is set: the "
                "per-user client cannot be built, so every database access on "
                "the API path fails."))

        if not scheduler:
            problems.append(_problem(
                "scheduler_disabled", WARNING,
                "ENABLE_SCHEDULER is not true in this process: compliance "
                "reminders, recurring documents and escalations will not run "
                "on their own."))
        if _blank("ALLOWED_ORIGINS"):
            problems.append(_problem(
                "allowed_origins_not_set", WARNING,
                "ALLOWED_ORIGINS is not set; CORS is using the built-in default "
                "list of origins."))
        if _blank("FRONTEND_URL"):
            problems.append(_problem(
                "frontend_url_not_set", WARNING,
                "FRONTEND_URL is not set; invitation and portal links use the "
                "built-in default origin."))

    return {
        "app_env_is_production": production,
        "app_env_declared": sc.app_env() != "",
        "use_user_jwt": jwt_on,
        "use_user_jwt_explicit": jwt_setting is not None,
        "require_mfa": mfa_on,
        "require_mfa_explicit": mfa_setting is not None,
        "mfa_required_roles": sorted(sc.mfa_required_roles()),
        "supabase_anon_key_present": anon_present,
        "scheduler_enabled": scheduler,
        "cors_origin_count": origins_count,
        "allowed_origins_set": not _blank("ALLOWED_ORIGINS"),
        "frontend_url_set": not _blank("FRONTEND_URL"),
        "problems": problems,
        "ok": not any(p["level"] == ERROR for p in problems),
    }


def readiness_flags() -> dict[str, bool]:
    """The booleans-only view, for a readiness endpoint that is not Partner-only.

    OPS-06 asks for the posture to be shown in a readiness probe rather than in
    /health, so that a deploy is never failed by a setting. Every value is a
    bool — no role list, no origin count — because a probe is reachable by whoever
    can reach the service.
    """
    posture = security_posture()
    return {
        "posture_ok": bool(posture["ok"]),
        "app_env_is_production": bool(posture["app_env_is_production"]),
        "use_user_jwt": bool(posture["use_user_jwt"]),
        "require_mfa": bool(posture["require_mfa"]),
        "supabase_anon_key_present": bool(posture["supabase_anon_key_present"]),
        "scheduler_enabled": bool(posture["scheduler_enabled"]),
        "allowed_origins_set": bool(posture["allowed_origins_set"]),
        "frontend_url_set": bool(posture["frontend_url_set"]),
    }


def validate_security_posture() -> dict[str, Any]:
    """Log what `security_posture` found, once, at boot. Never raises."""
    try:
        posture = security_posture()
    except Exception:                                        # noqa: BLE001
        _logger.exception("CONFIG SECURITY: could not assess the security posture")
        return {"ok": False, "problems": [], "assessed": False}

    for problem in posture["problems"]:
        log = _logger.error if problem["level"] == ERROR else _logger.warning
        log("CONFIG SECURITY [%s]: %s", problem["code"], problem["message"])
    if posture["app_env_is_production"] and not posture["problems"]:
        _logger.info(
            "CONFIG SECURITY: production posture confirmed — user-JWT and MFA "
            "explicitly on, scheduler running.")
    posture["assessed"] = True
    return posture
