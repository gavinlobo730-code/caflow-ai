"""How a rupee figure is rendered on a document that leaves the building.

── WHY THIS EXISTS ──────────────────────────────────────────────────────────
Three PDF services formatted money and no two agreed.

**The sales invoice and the payslip grouped the WESTERN way.** Both carried

    rupees = paise // 100
    fraction = paise % 100
    return f"{rupees:,}.{fraction:02d}"

and `f"{1234567:,}"` is `1,234,567`. Decision D6 says Indian grouping
everywhere: **12,34,567**, never 1,234,567. These are the two documents that
leave the building most often — a tax invoice goes to the client's own
customer and a payslip to an employee — and both stated the amount in a
grouping an Indian reader does not use.

**AND THE SAME TWO LINES ARE SIMPLY WRONG FOR A NEGATIVE.** Python's `//`
floors and `%` follows it, so the sign-and-magnitude split silently inverts:

        -1 paise  ->  "-1.99"     (true: -0.01)
       -99 paise  ->  "-1.01"     (true: -0.99)
      -150 paise  ->  "-2.50"     (true: -1.50)

Every negative that is not an exact rupee came out wrong by one rupee minus
its own fraction. A payslip whose recoveries exceed the pay, a credit note, an
adjustment line — each of them.

`year_end_pdf_service._format_indian` had the grouping right and took `abs()`
first, so it was the one correct implementation of three. It is the one that
moved here.

── THE RULES ────────────────────────────────────────────────────────────────
**INDIAN GROUPING, ALWAYS** (D6): the last three digits, then twos.

**THE SIGN IS TAKEN OFF FIRST.** Everything below works on the magnitude and
the sign is put back at the end, which is what makes a negative right. A test
pins every case from -1 paise upward.

**NO RUPEE SIGN.** ReportLab's core fonts are WinAnsiEncoding and have no
glyph for U+20B9 — it renders as a black box, which shipped twice and is why
`tests/test_no_pdf_renders_the_rupee_sign.py` exists. This module emits
digits; a caller that wants a unit writes "Rs." itself.

**NOTHING IS ROUNDED.** `whole_rupees` TRUNCATES, which is what the year-end
statements have always done and is deliberate: a statement presented in whole
rupees is a presentation choice, and a browser- or renderer-side ROUND would be
a second implementation of a rounding rule — `domain/gst/money.py` is the
authority where one is statutory (CGST §170). The truncation is toward ZERO,
not toward minus infinity, so -150 paise is -1 rupee and not -2.
"""
from __future__ import annotations

__all__ = ["group_indian", "rupees_paise", "whole_rupees"]


def group_indian(digits: str) -> str:
    """`"1234567"` -> `"12,34,567"`. Digits only, no sign — the caller keeps it."""
    if len(digits) <= 3:
        return digits
    last3, rest = digits[-3:], digits[:-3]
    groups: list[str] = []
    while len(rest) > 2:
        groups.append(rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.append(rest)
    groups.reverse()
    return ",".join(groups) + "," + last3


def rupees_paise(paise: int | None) -> str:
    """Integer paise -> `"12,34,567.50"`, and `"-1.50"` for -150.

    `None` reads as nil rather than raising: a PDF is built from rows a query
    returned, and a column that is NULL on one row of a hundred must not fail
    the whole document.
    """
    p = int(paise or 0)
    sign = "-" if p < 0 else ""
    mag = abs(p)
    return f"{sign}{group_indian(str(mag // 100))}.{mag % 100:02d}"


def whole_rupees(paise: int | None) -> str:
    """Integer paise -> `"12,34,567"`, truncated TOWARD ZERO.

    The year-end statements present in whole rupees. Truncating the magnitude
    is what `-150 -> -1` means, and it is what the previous implementation did
    for a positive; the sign split is what it got wrong.
    """
    p = int(paise or 0)
    whole = abs(p) // 100
    # "-0" is not a figure. A magnitude below one rupee truncates to nil, and a
    # minus sign on a nil reads as an amount somebody owes.
    sign = "-" if p < 0 and whole else ""
    return f"{sign}{group_indian(str(whole))}"
