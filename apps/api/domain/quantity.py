"""
A quantity is stored to THREE decimals, so three decimals is what may be typed.

WHY THIS EXISTS (INV-09)
    Every quantity column in this schema is `NUMERIC(10,3)` — invoice lines,
    bill lines, note lines, the inventory stock ledger and the catalogue's
    cached on-hand figure (migrations 050, 188, 210). Postgres rounds a fourth
    decimal away on the way in, silently.

    The models did not. `StockAdjustmentIn.quantity` was a bare `float` with a
    positive() check, and `apply_stock_adjustment` computes the MONEY from
    `Decimal(str(quantity))` — the unrounded value. So an adjustment of
    1.2345 units at ₹100 booked ₹123.45 of value against a stored quantity of
    1.234 or 1.235: sub-paise money against a quantity the ledger did not keep,
    and Σ `value_delta_paise` stops being Σ(qty × unit cost).

    That matters beyond tidiness because CLAUDE.md makes Σ `value_delta_paise`
    the figure that ties the stock ledger to the Inventory control account.

REFUSE, DO NOT ROUND. Rounding would silently change what the CA typed, and
the direction is not obviously safe in either sense — a rounded-down write-off
leaves stock that is gone, a rounded-up one writes off stock that is there. A
refusal costs one correction and says exactly what to correct.

    The browser already refuses it: `apps/web/lib/money/rupeeInput.parseQuantity`
    takes up to three decimals and returns null otherwise. This is the same rule
    on the side that actually decides, for the paths a browser does not use —
    the CSV importers, the bulk endpoints and anything calling the API directly.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional

#: What NUMERIC(10,3) keeps. Not configurable — it is the column, and a second
#: figure here would be a second answer to a question the schema has settled.
QUANTITY_DECIMALS = 3


def quantity_violation(value) -> Optional[str]:
    """Why this quantity cannot be stored as typed, or None.

    Rejects a fourth decimal and anything that is not a number at all. Says
    nothing about SIGN or ZERO: those differ by document — an adjustment must be
    positive, an invoice line must be positive, and a credit note's line is
    positive too — so each model keeps its own rule and this one stays about the
    column.
    """
    if value is None:
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return "Quantity must be a number."
    if not d.is_finite():
        return "Quantity must be a number."
    if -d.as_tuple().exponent > QUANTITY_DECIMALS:
        return (f"Quantity is kept to {QUANTITY_DECIMALS} decimals ({value} has "
                f"{-d.as_tuple().exponent}). Round it before saving — the database "
                f"would round it silently and the value would no longer match it.")
    return None
