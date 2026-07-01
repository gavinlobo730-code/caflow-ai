"""
ECB reference-rate provider — abstraction only.

The class exists so the ExchangeRateService can depend on the RateProvider
interface today. Automatic fetching from the ECB feed is a LATER phase (see the
roadmap in docs/architecture/06-multi-currency-phase0.md); calling get_rate now
raises NotImplementedError rather than silently returning "no rate".
"""
from __future__ import annotations

from datetime import date

from domain.currency.providers.base import RateProvider
from domain.currency.rate_quote import RateQuote


class ECBRateProvider(RateProvider):
    source = "ecb"

    def get_rate(
        self, base: str, quote: str, rate_date: date, rate_type: str
    ) -> RateQuote | None:
        raise NotImplementedError(
            "Automatic ECB rate fetching is not implemented in Phase 1 (abstraction only)."
        )
