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

── THE GROUPING MOVED, AND THE NO-GLYPH RULE DID NOT ────────────────────────
`domain/money_text` is now the one implementation of Indian grouping, because
the same two defects above survived in 73 more places outside the PDFs — every
email, every 422 a CA reads, the XLSX export — with SIX more copies of the sign
bug. This module re-exports the three unit-less functions and **deliberately
does not re-export `inr`**: that one prepends U+20B9, and a PDF that prints ₹
prints a black box. The grouping is universal; the unit is the medium's.
"""
from __future__ import annotations

from domain.money_text import group_indian, rupees_paise, whole_rupees

__all__ = ["group_indian", "rupees_paise", "whole_rupees"]
