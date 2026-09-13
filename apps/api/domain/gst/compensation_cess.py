"""
GST compensation cess — the one place that computes it.

WHAT IT IS

GST (Compensation to States) Act 2017 s.8(1) levies a cess "on such
intra-State supplies of goods or services or both ... and such inter-State
supplies of goods or services or both ... as are specified in column (2) of
the Schedule". s.8(2) says how much: "The cess shall be levied on such
supplies of goods and services as are specified in column (2) of the
Schedule, on the basis of VALUE, QUANTITY or on such basis at such rate not
exceeding the rate set forth in the corresponding entry in column (4)".

That "value, QUANTITY or on such basis" is the whole reason this module takes
two rates rather than one. Real Schedule entries use each:

    aerated waters, pan masala, motor vehicles   ad valorem, a percentage
    coal                                         specific, so much per tonne
    cigarettes                                   BOTH, a percentage PLUS a
                                                 figure per thousand sticks

A single `cess_rate_bps` column could express the first and not the other
two, and a product that can only charge a percentage silently under-charges
every coal and tobacco client. So a line carries an ad-valorem rate AND a
per-unit figure, and the charge is their SUM.

WHY THE AMOUNT IS DERIVED AND NOT TYPED

The same reason CGST/SGST/IGST are derived from `gst_rate_percent`: a stored
amount that no rate produces cannot be checked, and the two would drift the
first time a line was edited. A supplier whose own cess differs from ours by
a paise of rounding surfaces in the GSTR-2B reconciliation exactly the way a
GST difference already does — as a difference, which is the point.

ROUNDING FLOORS, because the sibling heads floor. s.11(2) applies the CGST
Act to this cess "mutatis mutandis", and `_compute_line_gst` floors with
`// 10000`; a cess that rounded the other way would disagree with the GST on
the same line for no statutory reason, and a sub-paise divergence between two
heads of one invoice is a reconciliation puzzle worth more than the paise.

THE PER-UNIT FIGURE IS PER THE LINE'S OWN UNIT OF MEASURE. The line has one
quantity and one UQC; nothing here converts tonnes to kilograms. A Schedule
entry of "Rs. 400 per tonne" on a line kept in KGS is 40 paise per unit, and
that is the CA's conversion to make, because only they know what the line
counts.

WHAT THIS MODULE DELIBERATELY DOES NOT DO

  * It holds NO RATE TABLE. Which cess reaches which HSN is Schedule data
    that changes by Council notification — the same shape as the state
    professional-tax slabs and the ITR schemas: a human reads the current
    notification and records it. `firm_hsn_rate_history` has carried
    `cess_rate_pct` and `cess_specific_paise_per_unit` since migration 181
    for exactly this, and nothing reads them yet.
  * It does not model a "whichever is HIGHER" entry. Where the Schedule
    charges the greater of a percentage and a per-unit figure rather than
    their sum, the CA records the limb that applies and leaves the other at
    zero. Modelling `max()` on top of `+` needs to know which entries are
    which, which is the rate table this module does not hold.

`apps/web/lib/money/cessLine.ts` is the keystroke mirror and the two are
pinned by `shared/gst-parity-vectors.json`.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# The statute, quoted where a caller needs to cite it.
CESS_ACT = "GST (Compensation to States) Act 2017"
CESS_CHARGE = f"{CESS_ACT} s.8"
# s.11(2) proviso: credit of this cess "shall be utilised only towards payment
# of cess". That is why GSTR-3B Table 6 never lets cess credit pay IGST, CGST
# or SGST, and why `gstr3b_computer` keeps the cess head out of the s.49(5)
# ladder entirely.
CESS_CREDIT_RING_FENCE = f"{CESS_ACT} s.11(2), proviso"

# What a caller is told when a Schedule entry charges the HIGHER of the two
# limbs rather than their sum. Stated once so every answer says the same thing.
HIGHER_OF_NOT_MODELLED = (
    "Where the Schedule charges the greater of a percentage and a per-unit "
    "figure rather than both, record the limb that applies and leave the other "
    "at zero — this engine adds the two limbs and holds no table saying which "
    "entries are which."
)


@dataclass(frozen=True)
class LineCess:
    """One line's compensation cess, and the two limbs it came from.

    Both limbs are reported, not just the total, because a CA checking a
    cigarette line against the Schedule needs to see the 5% and the per-
    thousand separately — a single number cannot be reconciled to an entry
    that has two parts.
    """
    cess_paise: int
    ad_valorem_paise: int
    specific_paise: int


def line_cess(
    *,
    taxable_paise: int,
    quantity,
    cess_rate_bps: int = 0,
    cess_specific_paise_per_unit: int = 0,
) -> LineCess:
    """Compensation cess on one line, in integer paise.

    `taxable_paise` is the VALUE OF SUPPLY — s.15 of the CGST Act, applied to
    this cess by s.11(1) of the Compensation Act — so it is the figure AFTER a
    s.15(3)(a) discount, which is the same base the GST heads are charged on.
    Passing the gross would charge cess on money the customer was never asked
    for.

    `quantity` is the line's own quantity in its own unit; it is read through
    `Decimal(str(...))` and truncated, matching `int(Decimal(str(qty)) *
    rate_paise)` in the routers so a fractional quantity behaves identically
    for both the value and the cess.

    Raises ValueError on a negative input. There is deliberately NO upper
    bound on the rate: Schedule column (4) carries entries well above 100%
    (unmanufactured tobacco, and the pan-masala entries), so any general
    ceiling would be invented and would refuse a lawful charge.
    """
    rate_bps = int(cess_rate_bps or 0)
    per_unit = int(cess_specific_paise_per_unit or 0)
    taxable = int(taxable_paise or 0)

    if rate_bps < 0:
        raise ValueError("cess_rate_bps must be non-negative.")
    if per_unit < 0:
        raise ValueError("cess_specific_paise_per_unit must be non-negative.")
    if taxable < 0:
        raise ValueError("taxable_paise must be non-negative.")

    qty = Decimal(str(quantity if quantity is not None else 0))
    if qty < 0:
        raise ValueError("quantity must be non-negative.")

    # Floor, exactly as _compute_line_gst floors the tax heads.
    ad_valorem = (taxable * rate_bps) // 10000
    # Truncate, exactly as the routers truncate qty x rate into the taxable.
    specific = int(qty * per_unit) if per_unit else 0
    return LineCess(
        cess_paise=ad_valorem + specific,
        ad_valorem_paise=ad_valorem,
        specific_paise=specific,
    )


def carries_cess(line: dict) -> bool:
    """True where a line declares either limb. Used to decide whether a
    document needs a cess ledger at all — a client with no cess goods must
    never be asked to hold an account it will never post to."""
    return bool(int(line.get("cess_rate_bps") or 0)
                or int(line.get("cess_specific_paise_per_unit") or 0))
