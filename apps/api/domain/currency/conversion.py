"""
Foreign → base amount conversion at a frozen rate (Multi-Currency Phase 3).

Capability A: books are INR-functional; a document is entered in a transaction
currency and posted to the base (INR) ledger at the booking rate. This module does
the ONE arithmetic that requires it — convert an integer minor-unit amount in the
transaction currency to integer base paise — exactly (Decimal, HALF_UP), never
float. It performs no rate lookup, no posting, and no reporting.

Balancing rule used by the document services: convert each component (taxable,
each GST head) independently, then define the base TOTAL as the SUM of those
converted components. That guarantees the base journal balances exactly with no
FX-rounding account (which belongs to a later phase).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

BASE_MINOR_UNIT = 2  # INR (paise)


def to_base_minor(
    txn_minor: int,
    rate,
    txn_minor_unit: int,
    base_minor_unit: int = BASE_MINOR_UNIT,
) -> int:
    """Convert `txn_minor` (integer minor units of the transaction currency) to
    integer base minor units (paise) at `rate` (base MAJOR units per 1 txn MAJOR
    unit, e.g. 83.5 INR per 1 USD), using exact Decimal HALF_UP rounding.

        base_minor = round( txn_minor × rate × 10^(base_minor_unit − txn_minor_unit) )

    The 10^(…) factor reconciles differing minor-unit conventions (JPY has 0,
    INR/USD have 2), so a ¥1000 amount converts correctly to paise.
    """
    if not isinstance(rate, Decimal):
        rate = Decimal(str(rate))
    if rate <= 0:
        raise ValueError("exchange rate must be positive")
    scale = Decimal(10) ** (base_minor_unit - txn_minor_unit)
    value = Decimal(int(txn_minor)) * rate * scale
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def to_txn_minor(
    base_minor: int,
    rate,
    txn_minor_unit: int,
    base_minor_unit: int = BASE_MINOR_UNIT,
) -> int:
    """Inverse of to_base_minor: express an integer base-paise amount back in the
    transaction currency's minor units at `rate`, exact Decimal HALF_UP. Used only
    to stamp the per-line foreign (memo) amount on journal lines (G4 dual storage);
    the authoritative value is always the base amount. Never used to re-derive a
    document's foreign total — that is stored exactly from the user's input."""
    if not isinstance(rate, Decimal):
        rate = Decimal(str(rate))
    if rate <= 0:
        raise ValueError("exchange rate must be positive")
    scale = Decimal(10) ** (txn_minor_unit - base_minor_unit)
    value = (Decimal(int(base_minor)) / rate) * scale
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))
