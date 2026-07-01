"""Rate provider adapters behind the RateProvider interface (G5)."""
from domain.currency.providers.base import RateProvider
from domain.currency.providers.manual import ManualRateProvider
from domain.currency.providers.rbi import RBIRateProvider
from domain.currency.providers.ecb import ECBRateProvider

__all__ = ["RateProvider", "ManualRateProvider", "RBIRateProvider", "ECBRateProvider"]
