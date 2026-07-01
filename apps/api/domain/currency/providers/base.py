"""
RateProvider interface (G5).

The accounting engine depends only on the ExchangeRateService, and the service
depends only on this interface — never on a concrete provider. Adding a feed is
"implement this interface + register", with zero kernel or report changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from domain.currency.rate_quote import RateQuote


class RateProvider(ABC):
    """A source of exchange rates (manual store, RBI feed, ECB feed, …)."""

    #: stable identifier persisted to fx_rates.source and RateQuote.source
    source: str = "abstract"

    @abstractmethod
    def get_rate(
        self, base: str, quote: str, rate_date: date, rate_type: str
    ) -> RateQuote | None:
        """Return the base→quote rate for `rate_date` of the given `rate_type`, or
        None if this provider has no such rate. Must never mutate posted data."""
        raise NotImplementedError
