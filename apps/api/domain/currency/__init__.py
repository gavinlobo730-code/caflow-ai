"""
Multi-Currency — Phase 1 (Foundation).

Additive infrastructure only (docs/architecture/06-multi-currency-phase0.md):
the currency master reader, the three-level currency-policy resolver, the rate
provider abstraction, and the ExchangeRateService. NONE of this changes accounting
behaviour: with the feature off (the default) resolve_currency_policy() is inert
(INR-only) and nothing here touches the posting kernel, journals, or reports.
"""
from domain.currency.policy import (
    BASE_CURRENCY,
    CurrencyPolicy,
    resolve_currency_policy,
)
from domain.currency.rate_quote import RateQuote
from domain.currency.rate_types import (
    DEFAULT_RATE_TYPE,
    RATE_TYPES,
    is_valid_rate_type,
)
from domain.currency.exchange_rate_service import ExchangeRateService, RateNotFound
from domain.currency.providers.base import RateProvider
from domain.currency.providers.manual import ManualRateProvider
from domain.currency.providers.rbi import RBIRateProvider
from domain.currency.providers.ecb import ECBRateProvider

__all__ = [
    "BASE_CURRENCY",
    "CurrencyPolicy",
    "resolve_currency_policy",
    "RateQuote",
    "RATE_TYPES",
    "DEFAULT_RATE_TYPE",
    "is_valid_rate_type",
    "ExchangeRateService",
    "RateNotFound",
    "RateProvider",
    "ManualRateProvider",
    "RBIRateProvider",
    "ECBRateProvider",
]
