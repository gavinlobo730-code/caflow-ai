"""
An item is STOCKED in one unit and may be TRANSACTED in another, and only the
first one ever reaches the ledger.

WHY THIS EXISTS (INV-03's third convenience, and INV-09's part 3 — each
finding deferred the alternate unit to the other, so neither built it)

    A wholesaler buys cement in tonnes and sells it in bags; a stationer buys
    pens in boxes of twelve and sells them singly. Today `service_catalogue`
    carries ONE `unit`, so the CA either keeps the master in the buying unit
    and re-types a converted quantity onto every sales line, or keeps two
    catalogue rows for one physical item — at which point the on-hand figure
    is split across two rows and ties to nothing.

THE PRIMARY UNIT IS THE ONE THE LEDGER KEEPS, AND THE ALTERNATE IS DERIVED

    `inventory_stock_ledger` holds `quantity_delta` and a running total, and
    `domain/reporting/stock_position` sums the deltas to answer a dated
    question. If a movement could be recorded in either unit the sum would add
    boxes to pieces, so the conversion happens at the DOOR — a quantity typed
    in the alternate unit is turned into primary units before anything is
    stored — and the ledger never learns that a second unit exists. A test
    asserts exactly that, the same discipline `record_stock_out` takes about a
    batch (INV-03a): a column that COULD change what is stored is the one that
    eventually does.

    So nothing stores a quantity in the alternate unit. `to_alternate` exists
    for DISPLAY — "42 PCS (3.5 BOX)" — and is recomputed on every read, which
    is migration 278's reasoning applied to a quantity: a stored pair drifts
    the first time somebody edits the factor, and the drift is invisible
    because both numbers look computed.

THE CONVERSION REFUSES WHERE THREE DECIMALS CANNOT HOLD IT

    Every quantity column is `NUMERIC(10,3)` (`domain/quantity`), so a
    conversion whose product needs a fourth decimal cannot be stored as
    computed. Truncating understates what moved and leaves stock on the books
    that has gone; rounding up overstates it and writes off stock that is
    there. Neither direction is safe, which is precisely `quantity_violation`'s
    argument, so the conversion REFUSES and names the figure. The case is rare
    — a factor is nearly always a whole number of the smaller unit — and a
    refusal costs one correction where a silent 0.001 costs a reconciliation
    nobody can close.

THE FACTOR IS PRIMARY UNITS PER ONE ALTERNATE UNIT, AND THE NAME SAYS SO

    `units_per_alternate` rather than `conversion_factor`, because the second
    name does not say which way it points and a factor applied upside down is
    a 144× error on a box of twelve that still looks like a plausible
    quantity. It must be strictly positive: zero would make every alternate
    quantity nil and a negative one would reverse the movement.

BOTH UNITS ARE UQC CODES AND THEY MAY NOT BE THE SAME

    The alternate goes through `domain/gst/uqc` like the primary — it is a
    candidate for Rule 46(h)'s unit on a document, so an unofficial word there
    is the same defect GST-29 closed on the primary. Equal units are refused
    rather than accepted with a factor of 1: an item whose two units are the
    same has one unit, and storing the pair invites a later factor edit that
    silently rescales the master.

NOTHING HERE IS A COST FORMULA. The conversion moves a QUANTITY. What a unit
costs is `domain/inventory/costing`'s business and is unchanged — the value of
a movement is whatever the document says, in paise, and dividing it by a
converted quantity is not done anywhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from domain.gst import uqc
from domain.quantity import QUANTITY_DECIMALS

#: The ledger's own exponent. Read from `domain/quantity` rather than restated,
#: because it is the same NUMERIC(10,3) both are about.
_STEP = Decimal(1).scaleb(-QUANTITY_DECIMALS)


@dataclass(frozen=True)
class AlternateUnit:
    """A second unit an item may be bought or sold in.

    `units_per_alternate` is how many PRIMARY units make one of these. A box of
    twelve pens whose primary unit is PCS is ``AlternateUnit("BOX", 12)``.
    """

    code: str
    units_per_alternate: Decimal


@dataclass(frozen=True)
class Conversion:
    """The answer, or the reason there is not one.

    `quantity` is in PRIMARY units and is None exactly when `refusal` is set.
    Never both, never neither — a caller that reads one without checking the
    other would store a None or ignore a refusal, and both are silent.
    """

    quantity: Optional[Decimal]
    refusal: Optional[str]


def _decimal(value) -> Optional[Decimal]:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return d if d.is_finite() else None


def problem_with_pair(primary: Optional[str], alternate: Optional[str],
                      units_per_alternate) -> Optional[str]:
    """Why this alternate unit cannot be recorded against this primary, or None.

    Asked at every door that writes the master. An item with no alternate unit
    at all is fine and returns None — the whole feature is optional, and an
    absent alternate is the state every existing row is in.
    """
    if alternate is None or str(alternate).strip() == "":
        if units_per_alternate not in (None, "") and _decimal(units_per_alternate) not in (None, Decimal(0)):
            return ("A conversion factor was given with no alternate unit. Name the "
                    "unit it converts to, or clear the factor.")
        return None

    bad = uqc.problem_with(alternate)
    if bad:
        return f"Alternate unit: {bad}"

    if not primary or str(primary).strip() == "":
        return ("An alternate unit needs a primary unit to convert to. Record the "
                "item's own unit first.")

    if uqc.normalise(primary) == uqc.normalise(alternate):
        return ("The alternate unit is the same as the primary unit. An item with "
                "one unit needs no conversion factor.")

    factor = _decimal(units_per_alternate)
    if factor is None:
        return "The conversion factor must be a number."
    if factor <= 0:
        return ("The conversion factor must be greater than zero — it is how many "
                f"{uqc.normalise(primary)} make one {uqc.normalise(alternate)}.")
    if -factor.as_tuple().exponent > QUANTITY_DECIMALS:
        return (f"The conversion factor is kept to {QUANTITY_DECIMALS} decimals "
                f"({units_per_alternate} has {-factor.as_tuple().exponent}).")
    return None


def to_primary(quantity_in_alternate, unit: AlternateUnit) -> Conversion:
    """Turn a quantity typed in the alternate unit into PRIMARY units.

    This is the only direction anything is stored in. It refuses rather than
    rounding — see the module docstring; the direction of a rounding error is
    unsafe both ways round on a stock position.
    """
    qty = _decimal(quantity_in_alternate)
    if qty is None:
        return Conversion(None, "Quantity must be a number.")
    factor = _decimal(unit.units_per_alternate)
    if factor is None or factor <= 0:
        return Conversion(None, "The conversion factor must be greater than zero.")

    product = qty * factor
    # Decimal keeps the exact product, so this tests REPRESENTABILITY and not a
    # float's idea of it: 0.001 BOX at 12 is 0.012 PCS and passes; 10 PCS at a
    # factor of 3 is 3.333... and never arises here, because the division is
    # the DISPLAY direction and does not store anything.
    if -product.normalize().as_tuple().exponent > QUANTITY_DECIMALS:
        return Conversion(None, (
            f"{quantity_in_alternate} {unit.code} is {product} "
            f"— more than {QUANTITY_DECIMALS} decimals, which is what the stock "
            f"ledger keeps. Enter the quantity in the item's own unit instead, or "
            f"record a factor that divides evenly."))
    return Conversion(product, None)


def to_alternate(quantity_in_primary, unit: AlternateUnit) -> Optional[Decimal]:
    """The same quantity expressed in the alternate unit, FOR DISPLAY ONLY.

    Quantised to the ledger's three decimals so it reads like every other
    quantity on the screen, and deliberately not refused when it does not
    divide evenly: 10 PCS of a 12-PCS box really is 0.833 of a box, and a
    screen that refused to say so would be less useful than one that rounds the
    label. Nothing stores this.
    """
    qty = _decimal(quantity_in_primary)
    factor = _decimal(unit.units_per_alternate)
    if qty is None or factor is None or factor <= 0:
        return None
    return (qty / factor).quantize(_STEP)


def describe(unit: AlternateUnit, primary: Optional[str]) -> str:
    """"1 BOX = 12 PCS" — the sentence a screen puts beside the factor box.

    Built here rather than in the browser because getting it backwards is the
    error this module is named for, and one authority for which side of the
    equals sign each unit goes on is cheaper than two.
    """
    factor = _decimal(unit.units_per_alternate)
    shown = format(factor.normalize(), "f") if factor is not None else "?"
    return f"1 {unit.code} = {shown} {uqc.normalise(primary) or '?'}"
