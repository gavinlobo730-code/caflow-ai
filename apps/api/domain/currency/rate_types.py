"""
FX rate types — controlled vocabulary shared by the application and the
fx_rates.rate_type CHECK constraint (no free-text rate types).

  booking      — transaction-date rate a document is posted at (Ind AS 21 initial recognition)
  gst_notified — CBIC / CGST Rule 34 notified rate for the INR-equivalent of a foreign supply
  customs      — customs exchange rate for imports
  closing      — period-end rate for monetary-item retranslation (revaluation)
"""
from __future__ import annotations

RATE_TYPES: frozenset[str] = frozenset({"booking", "gst_notified", "customs", "closing"})

DEFAULT_RATE_TYPE = "booking"


def is_valid_rate_type(rate_type: str) -> bool:
    return rate_type in RATE_TYPES
