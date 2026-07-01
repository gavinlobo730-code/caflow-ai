"""
Manual rate provider — serves operator-entered rates from the fx_rates table.

This is NOT an automatic feed (no rates are fetched from any external source in
Phase 1); it only reads rates that were recorded manually. Returns the latest
rate on or before the requested date for the (base, quote, rate_type) triple.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from domain.currency.providers.base import RateProvider
from domain.currency.rate_quote import RateQuote


class ManualRateProvider(RateProvider):
    source = "manual"

    def __init__(self, db):
        self._db = db

    def get_rate(
        self, base: str, quote: str, rate_date: date, rate_type: str
    ) -> RateQuote | None:
        as_of = rate_date.isoformat() if isinstance(rate_date, date) else str(rate_date)
        res = (
            self._db.table("fx_rates")
            .select("base, quote, rate_date, rate_type, rate, source")
            .eq("base", base.upper())
            .eq("quote", quote.upper())
            .eq("rate_type", rate_type)
            .eq("source", self.source)
            .lte("rate_date", as_of)
            .order("rate_date", desc=True)
            .limit(1)
            .execute()
        )
        rows = getattr(res, "data", None) or []
        if not rows:
            return None
        row = rows[0]
        return RateQuote(
            base=row["base"],
            quote=row["quote"],
            rate=Decimal(str(row["rate"])),  # exact — parse via str, never float
            rate_date=date.fromisoformat(str(row["rate_date"])[:10]),
            rate_type=row["rate_type"],
            source=row["source"],
        )
