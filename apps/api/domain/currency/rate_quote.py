"""Immutable exchange-rate quote (G3 immutability, G4/G6 provenance)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class RateQuote:
    """An immutable rate quote.

    `frozen=True` guarantees a booked rate can never be mutated in place (G3:
    rates are frozen at posting; historical documents are never recalculated).
    Conversion and rounding are LATER phases — this Phase-1 value object only
    *carries* the rate and its provenance; it performs no posting or arithmetic.

    `rate` is the price of one unit of `base` expressed in `quote` (base→quote),
    an exact Decimal (stored NUMERIC(18,8)) — never a float.
    """
    base: str
    quote: str
    rate: Decimal
    rate_date: date
    rate_type: str
    source: str
    as_of: datetime | None = None  # when the quote was produced/fetched (provenance)

    def __post_init__(self) -> None:
        # Enforce the exactness invariant without breaking immutability.
        if not isinstance(self.rate, Decimal):
            raise TypeError("RateQuote.rate must be a Decimal (exact), never float")
        if self.rate <= 0:
            raise ValueError("RateQuote.rate must be positive")
