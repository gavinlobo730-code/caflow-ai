"""
A discount recorded in the invoice — CGST Act §15(3)(a).

THE SECTION, AND THE ONE THIS IS NOT
    §15(3): "The value of the supply shall not include any discount which is
    given — (a) before or at the time of the supply if such discount has been
    DULY RECORDED IN THE INVOICE issued in respect of such supply".

    So the tax is charged on the net, and the relief is conditional on the
    invoice showing the discount. That is why a discount is a field of its own
    rather than a smaller rate.

    §15(3)(b) — a discount given AFTER the supply — is excluded only where it
    was established in an agreement at or before the time of supply, is
    specifically linked to the invoices, AND the recipient has reversed the
    attributable input tax credit. That is the §34 credit-note path. Nothing in
    this module reaches it, and no discount field is added to the note models,
    because a post-supply discount that quietly reduced the value of a supply
    already made — with no credit note, no linkage and no reversal at the other
    end — is exactly what §15(3)(b) exists to prevent.

TWO LEVELS, AND WHY THE DOCUMENT ONE IS ALLOCATED
    GST is charged per line at the line's own rate. A document discount that
    stayed at document level could not be taxed at all on an invoice whose
    lines carry different rates — 5% off a bill of 18% goods and 5% services is
    not 5% off one number. So it is allocated pro-rata across the lines BEFORE
    tax, by their discounted value, and each line's share joins its own
    discount.

WHY EVERY ROUNDING HERE GOES DOWN
    A discount is money taken off the value of supply, so a LARGER discount is a
    SMALLER taxable value and less tax. Flooring the discount can only ever
    leave the taxable value a paise higher, which is the direction that cannot
    under-declare. It also matches `_compute_line_gst`, which floors the tax
    itself.

WHY THE ALLOCATION USES LARGEST REMAINDER
    A pro-rata split that loses a paise makes the invoice total differ from the
    figure the customer was quoted. The parts must sum to the whole exactly, so
    the residue is handed out one paise at a time to the lines with the largest
    fractional remainder — ties broken by position, so the same invoice always
    allocates the same way.
"""
from __future__ import annotations

from typing import Optional, Sequence

BPS = 10_000


def discount_for(gross_paise: int,
                 percent_bps: Optional[int] = None,
                 amount_paise: Optional[int] = None) -> int:
    """The discount on one line, in paise.

    A percentage is resolved against the line's gross; a flat amount is taken
    as given. When both arrive the PERCENTAGE wins, because it is the one the
    CA typed — the amount beside it is the figure a screen derived, and letting
    a derived number override a typed one is how a form's preview becomes the
    document.

    Refuses a discount larger than the line: a negative value of supply is not
    something the GL or GSTR-1 can represent, and silently capping it would
    charge tax on a figure nobody agreed.
    """
    if gross_paise < 0:
        raise ValueError("gross_paise must be non-negative")

    if percent_bps is not None:
        if percent_bps < 0 or percent_bps > BPS:
            raise ValueError("discount_percent_bps must be between 0 and 10000 "
                             "(0% to 100%)")
        # Floor, not round — see the module docstring. Plain integer
        # arithmetic, not Decimal: the browser mirrors this in BigInt and
        # integer floor division is the one operation both languages do
        # identically, with no precision setting to agree on.
        out = gross_paise * percent_bps // BPS
    elif amount_paise is not None:
        out = int(amount_paise)
    else:
        return 0

    if out < 0:
        raise ValueError("a discount cannot be negative")
    if out > gross_paise:
        raise ValueError(
            f"discount of {out} paise exceeds the line value of {gross_paise} "
            "paise — the value of a supply cannot be negative")
    return out


def allocate(total_paise: int, weights: Sequence[int]) -> list[int]:
    """Split a document-level discount across lines, pro-rata by `weights`
    (each line's value after its own discount), summing to EXACTLY total_paise.

    Largest remainder: every line gets the floor of its exact share, then the
    residue goes one paise at a time to the largest fractional remainders,
    ties broken by position so the same invoice always allocates the same way.

    A zero total weight — every line already fully discounted — allocates
    nothing rather than dividing by zero. There is no value left to reduce.
    """
    if total_paise < 0:
        raise ValueError("a discount cannot be negative")
    n = len(weights)
    if n == 0 or total_paise == 0:
        return [0] * n

    base = sum(weights)
    if base <= 0:
        return [0] * n
    if total_paise > base:
        raise ValueError(
            f"document discount of {total_paise} paise exceeds the invoice "
            f"value of {base} paise — the value of a supply cannot be negative")

    # Integer arithmetic throughout, so the browser's BigInt mirror is exact
    # rather than approximately equal: `n // base` is the floor of the share and
    # `n - q * base` is its numerator remainder, compared as integers rather
    # than as fractions.
    numerators = [total_paise * w for w in weights]
    out = [num // base for num in numerators]
    remainder = [num - q * base for num, q in zip(numerators, out)]

    # Each floor loses less than one whole paise, so the residue is strictly
    # less than the number of lines and every line gets at most one.
    residue = total_paise - sum(out)
    order = sorted(range(n), key=lambda i: (-remainder[i], i))
    for i in order[:residue]:
        out[i] += 1
    return out


def apply_to_lines(lines: Sequence[dict],
                   document_percent_bps: Optional[int] = None,
                   document_amount_paise: Optional[int] = None) -> list[dict]:
    """Resolve every discount on one invoice, in the order that makes
    "5% off this line, and 2% off the bill" mean what a CA expects.

    Each dict in `lines` carries `gross_paise` and optionally
    `discount_percent_bps` / `discount_paise`. Returns one dict per line with
    the resolved `discount_paise` (line + its share of the document discount),
    the `taxable_paise` that remains, and the `discount_percent_bps` the CA
    typed, carried through untouched for the customer's copy.

    LINE FIRST, THEN DOCUMENT. The document discount is a percentage OF THE
    BILL, and the bill is what is left after the line discounts — taking both
    off the gross would compound two reliefs the customer was quoted as one.
    """
    resolved = []
    for ln in lines:
        gross = int(ln.get("gross_paise") or 0)
        pct = ln.get("discount_percent_bps")
        amt = ln.get("discount_paise")
        d = discount_for(gross, pct, amt)
        resolved.append({"gross_paise": gross, "line_discount_paise": d,
                         "discount_percent_bps": pct,
                         "net_paise": gross - d})

    nets = [r["net_paise"] for r in resolved]
    doc_total = discount_for(sum(nets), document_percent_bps, document_amount_paise)
    shares = allocate(doc_total, nets)

    out = []
    for r, share in zip(resolved, shares):
        out.append({
            "discount_paise": r["line_discount_paise"] + share,
            "discount_percent_bps": r["discount_percent_bps"],
            "taxable_paise": r["net_paise"] - share,
        })
    return out
