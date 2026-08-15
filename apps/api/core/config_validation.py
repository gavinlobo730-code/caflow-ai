"""
Startup configuration validation (Beta hardening — Phase F).

Emits a clear boot-time report of required/optional configuration so operators see
missing config immediately, rather than discovering it at first request. Non-fatal:
it logs, it does not crash the app (a crash-loop is worse than a clear error line).
"""
import os
import logging

_logger = logging.getLogger("caflow.config")

# (env var, required?, note)
_CONFIG = [
    ("SUPABASE_URL",              True,  "Postgres/PostgREST endpoint"),
    ("SUPABASE_SERVICE_ROLE_KEY", True,  "service-role key (RLS bypass — keep secret, server-only)"),
    ("SUPABASE_ANON_KEY",         False, "anon key (client)"),
    ("GROQ_API_KEY",              False, "AI chat/text features + PDF invoice extraction — disabled if unset"),
    ("GEMINI_API_KEY",            False, "AI image-based invoice extraction — disabled if unset"),
    ("SENTRY_DSN",                False, "error monitoring — disabled if unset"),
    # Every outbound email goes through this one key: portal invites (client and
    # employee), team invites, scheduled reports. services/email_service.py
    # returns False and logs rather than raising when it is missing, which is
    # right — a failed send must not break the action that triggered it — but it
    # also means nothing surfaces until somebody notices an email that never
    # arrived. Listing it here is what makes that visible at boot instead.
    #
    # EMAIL_FROM is deliberately NOT listed: it defaults to a real address in
    # email_service, so its absence degrades the From header rather than
    # stopping delivery.
    ("RESEND_API_KEY",            False, "outbound email (invites, reports) — nothing is sent if unset"),
]


def validate_config() -> dict:
    """Check configuration presence at startup; log a single clear report. Returns a
    summary dict {missing_required, missing_optional} for tests/health checks."""
    missing_required, missing_optional = [], []
    for name, required, _note in _CONFIG:
        if not os.environ.get(name):
            (missing_required if required else missing_optional).append(name)

    if missing_required:
        _logger.error(
            "CONFIG: missing REQUIRED environment variables: %s — the application "
            "cannot operate correctly until these are set.", ", ".join(missing_required))
    if missing_optional:
        _logger.warning(
            "CONFIG: optional environment variables not set: %s — the related features "
            "are disabled.", ", ".join(missing_optional))
    if not missing_required and not missing_optional:
        _logger.info("CONFIG: all expected configuration present.")
    return {"missing_required": missing_required, "missing_optional": missing_optional}
