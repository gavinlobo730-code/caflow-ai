"""
resolve_currency_policy — the SINGLE currency decision point (G2).

Three gates (docs/architecture/06-multi-currency-phase0.md):
  L1 platform  env MULTI_CURRENCY_ENABLED     (kill switch, no DB dependency)
  L2 firm      firms.multi_currency_entitled
  L3 client    clients.multi_currency_enabled + clients.functional_currency

active = L1 AND L2 AND L3 AND functional == INR (Capability A only — a non-INR
functional currency is Capability B, which is not implemented, so it fails safe).

Fail-safe: anything off / ambiguous / missing ⇒ inactive, INR-only. This is
Phase-1 infrastructure — it is NOT yet wired into the posting kernel (this phase
makes no posting or journal changes); it becomes the kernel's authoritative guard
when foreign transactions arrive in Phase 2.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.feature_flags import multi_currency_platform_enabled

BASE_CURRENCY = "INR"


@dataclass(frozen=True)
class CurrencyPolicy:
    """The effective, resolved policy for a (firm, client). Matches the frozen
    signature `{ active, functional_currency }`."""
    active: bool
    functional_currency: str


def resolve_currency_policy(firm: dict | None, client: dict | None) -> CurrencyPolicy:
    """Resolve the effective currency policy for a (firm, client).

    Pure and total: never raises, never returns None — on any missing/ambiguous
    input it returns the inert INR-only policy, so behaviour is today's whenever
    the feature is off.
    """
    functional = BASE_CURRENCY
    if client is not None:
        raw = client.get("functional_currency")
        if isinstance(raw, str) and raw.strip():
            functional = raw.strip().upper()

    l1 = multi_currency_platform_enabled()
    l2 = bool(firm.get("multi_currency_entitled")) if firm else False
    l3 = bool(client.get("multi_currency_enabled")) if client else False

    # Capability A only: INR-functional books that transact in foreign currency.
    # A non-INR functional currency requires Capability B (presentation/translation),
    # which is not built — so it can never be active in Phase 1.
    capability_a = functional == BASE_CURRENCY
    active = l1 and l2 and l3 and capability_a

    # Fail-safe: when inactive, present INR so no caller can act on an unsupported
    # (non-INR) functional currency.
    return CurrencyPolicy(
        active=active,
        functional_currency=functional if active else BASE_CURRENCY,
    )
