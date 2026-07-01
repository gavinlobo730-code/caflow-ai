"""
ExchangeRateService (G5) — the ONE seam the rest of the app uses to obtain a rate.

Depends only on RateProvider implementations (never the reverse). Phase 1:
  - identity (X→X = 1) always works with no data and never fails, guaranteeing the
    INR-only path is zero-overhead;
  - cross-currency delegates to a registered provider and returns its immutable
    RateQuote.

NO posting or journal interaction — this only produces RateQuotes.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from domain.currency.providers.base import RateProvider
from domain.currency.rate_quote import RateQuote
from domain.currency.rate_types import DEFAULT_RATE_TYPE, is_valid_rate_type


class RateNotFound(LookupError):
    """No provider could supply the requested rate."""


class ExchangeRateService:
    def __init__(
        self,
        providers: list[RateProvider] | None = None,
        default_source: str | None = None,
    ):
        self._providers: dict[str, RateProvider] = {p.source: p for p in (providers or [])}
        self._default_source = default_source or (providers[0].source if providers else None)

    def get_quote(
        self,
        base: str,
        quote: str,
        rate_date: date,
        rate_type: str = DEFAULT_RATE_TYPE,
        source: str | None = None,
    ) -> RateQuote:
        """Return an immutable RateQuote for base→quote. Raises ValueError on an
        unknown rate_type and RateNotFound when no provider can supply the rate."""
        if not is_valid_rate_type(rate_type):
            raise ValueError(f"unknown rate_type {rate_type!r}")
        base_u, quote_u = base.upper(), quote.upper()

        # Identity: same currency is always rate 1 — no data or provider needed.
        # This is what keeps the INR-only path zero-overhead and infallible.
        if base_u == quote_u:
            return RateQuote(
                base=base_u, quote=quote_u, rate=Decimal(1),
                rate_date=rate_date, rate_type=rate_type, source="identity",
            )

        src = source or self._default_source
        provider = self._providers.get(src) if src else None
        if provider is None:
            raise RateNotFound(f"no rate provider registered for source {src!r}")
        q = provider.get_rate(base_u, quote_u, rate_date, rate_type)
        if q is None:
            raise RateNotFound(
                f"no {rate_type} rate for {base_u}->{quote_u} on {rate_date} from {src}"
            )
        return q
