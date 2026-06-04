"""
TDS domain — 24Q/26Q computation engine.
IT Act Section 192 (salary), Section 194 (non-salary), Section 206C (TCS).
All monetary values in integer paise — IT Act Section 145A.
"""
from .tds_computer import TDSComputer, TDS24QPayload, TDS26QPayload, TDSDeducteeRecord
from .tds_validator import TDSValidator

__all__ = [
    "TDSComputer",
    "TDS24QPayload",
    "TDS26QPayload",
    "TDSDeducteeRecord",
    "TDSValidator",
]
