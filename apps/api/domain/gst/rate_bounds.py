"""A GST rate a CA typed is BOUNDED, and the bound is not a list of slabs.

SALES-35. Four line models carry `gst_rate_percent: float = 18.0` and not one
of them validated it, so on a ₹1,000 line:

    -5     accepted  -> CGST -2,500 + SGST -2,500      negative output tax
    1800   accepted  ->      9,000  +      9,000       a hundred times the tax
    999999 accepted  ->  4,99,99,500 each              on a thousand-rupee line

The middle one is the case this exists for and it is not exotic: `1800` is how
this codebase spells 18% everywhere it uses BASIS POINTS, so a CA or an importer
moving a figure between the two units produces a plausible-looking number that
charges a hundredfold. It reaches the ledger, the customer's invoice, GSTR-1 and
GSTR-3B without anything objecting.

BOUNDED, NOT ENUMERATED — and that argument is already written down in this
repository, at `models/invoices.AdvanceIn._rate_in_range`: CLAUDE.md is explicit
that GST rate slabs are per-line on the document and deliberately NOT a central
table here, so a list of allowed rates would be the very thing that file says
not to build, and would refuse a rate a Council notification adds. 0 to 100 per
cent is the range a rate can occupy at all; outside it is a typo or a unit
mix-up.

100 IS ALLOWED AND THAT IS DELIBERATE. No notified GST rate is anywhere near
it, but the bound exists to catch a unit mix-up rather than to police the
Council, and refusing a rate because nobody has notified it yet is the failure
mode the enumerated version has. Compensation cess takes the same shape for a
sharper reason — `SalesInvoiceLineIn.cess_rate_bps` is guarded as non-negative
with NO upper bound at all, because Schedule entries above 100% exist.

THE MESSAGE NAMES BOTH UNITS, because the reader who hits this is by
construction confused about which one they are in.
"""
from __future__ import annotations

from typing import Optional

#: The widest a percentage rate can be and still be a rate.
MAX_GST_RATE_PERCENT = 100.0


def rate_percent_violation(v: Optional[float]) -> Optional[str]:
    """Why this is not a GST rate, or None.

    Shaped like `domain/quantity.quantity_violation` and
    `domain/gst/gstin.problem_with`: one shape for "what is wrong with this
    value", returning the sentence rather than raising, so a model door, a bulk
    importer reporting per row, and a screen can all use the same rule.
    """
    if v is None:
        return None
    try:
        rate = float(v)
    except (TypeError, ValueError):
        return "A GST rate must be a number."
    if rate != rate:  # NaN, which every comparison below would pass
        return "A GST rate must be a number."
    if rate < 0:
        return (
            f"A GST rate cannot be negative, and {rate:g} is. A negative rate "
            f"posts negative output tax to the ledger and files a negative "
            f"figure on the return."
        )
    if rate > MAX_GST_RATE_PERCENT:
        return (
            f"{rate:g} is not a GST rate. This field is a PERCENTAGE — 18 is "
            f"18% — and basis points are a different field, where 1800 is 18%. "
            f"A rate above {MAX_GST_RATE_PERCENT:g}% is a typo or a unit "
            f"mix-up; check which of the two you meant."
        )
    return None
