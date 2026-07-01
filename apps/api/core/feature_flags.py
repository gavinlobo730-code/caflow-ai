"""
Application feature flags (env-driven, default OFF) — the L1 platform layer.

Distinct from core/security_config.py (security cutovers); these are product
capability kill switches. Read at call time (never cached) so they can be toggled
per-process and are trivially testable via monkeypatch.setenv.
"""
import os


def _flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def multi_currency_platform_enabled() -> bool:
    """L1 Multi-Currency kill switch (docs/architecture/06-multi-currency-phase0.md).

    OFF (the default) ⇒ the whole platform is INR-only regardless of firm/client
    flags; resolve_currency_policy() can never return active=True. No DB dependency.
    """
    return _flag("MULTI_CURRENCY_ENABLED")
