"""How a rupee figure is written for a person to read.

── THE TWO RULES, AND WHY THEY ARE IN DIFFERENT PLACES ──────────────────────
**The GROUPING is universal**: Indian grouping everywhere (decision D6) — the
last three digits, then twos, so 12,34,567 and never 1,234,567. That rule is
the same on a PDF, in an email, in a 422 a CA reads and in a spreadsheet cell's
text, so it lives here and has exactly one implementation.

**The UNIT is medium-specific and stays the CALLER'S**, which is why nothing
here emits one. ReportLab's core fonts are WinAnsiEncoding and carry no glyph
for U+20B9, so a PDF that prints ₹ prints a black box — that shipped twice, and
`tests/test_no_pdf_renders_the_rupee_sign.py` exists because of it. A PDF writes
"Rs."; an email, a screen and an API message write ₹. A function here that chose
one would be wrong for half its callers, and one that took the unit as an
argument would be a worse way of writing an f-string.

── WHERE THIS CAME FROM, AND WHY IT IS NOT JUST TIDYING ─────────────────────
`domain/reporting/pdf_money` was written when three PDF services turned out to
format money three ways. It fixed the three PDFs and **nothing else**, and the
same two defects survived in 73 more places — every email, every 422, every
timeline sentence, the XLSX export and a dozen domain modules.

**SIX of them carried the sign bug that module's own docstring documents.**
Python's `//` floors and `%` follows it, so the sign-and-magnitude split
silently inverts:

        -1 paise  ->  "-1.99"     (true: -0.01)
       -99 paise  ->  "-1.01"     (true: -0.99)
      -150 paise  ->  "-2.50"     (true: -1.50)

Every negative that is not an exact rupee came out wrong by one rupee minus its
own fraction. `services/email_service` is one of the six and it sends to a
CLIENT'S OWN CUSTOMER; `services/time_export_service` is another and it writes
a spreadsheet cell. `domain/banking/matcher` had taken `abs()` on the fraction
and not on the rupees, which fixes nothing: -1 paise still reads "-1.01".

**And roughly twenty-five divided by 100 in FLOAT.** CLAUDE.md's first money
rule is integer paise arithmetic, never floating point. Below 2^53 paise a
float is exact so no figure shipped wrong from this alone, but a `/ 100` on a
paise value is the shape the rule exists to keep out of the codebase, and it
sat in the middle of sentences a CA reads about money they are about to pay.

── THE RULES ────────────────────────────────────────────────────────────────
**THE SIGN IS TAKEN OFF FIRST.** Everything works on the magnitude and the
sign is restored at the end, which is what makes a negative right.

**NOTHING IS ROUNDED.** `whole_rupees` TRUNCATES, toward ZERO rather than
toward minus infinity, so -150 paise is -1 rupee and not -2. Where a rounding
rule is STATUTORY it belongs in `domain/gst/money.py` (CGST §170), not in a
formatter.

**`None` READS AS NIL rather than raising.** These render rows a query
returned, and a column that is NULL on one row of a hundred must not fail the
whole document, email or response.
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
    """Integer paise -> `"12,34,567.50"`, and `"-1.50"` for -150. No unit."""
    p = int(paise or 0)
    sign = "-" if p < 0 else ""
    mag = abs(p)
    return f"{sign}{group_indian(str(mag // 100))}.{mag % 100:02d}"


def whole_rupees(paise: int | None) -> str:
    """Integer paise -> `"12,34,567"`, truncated TOWARD ZERO. No unit."""
    p = int(paise or 0)
    whole = abs(p) // 100
    # "-0" is not a figure. A magnitude below one rupee truncates to nil, and a
    # minus sign on a nil reads as an amount somebody owes.
    sign = "-" if p < 0 and whole else ""
    return f"{sign}{group_indian(str(whole))}"
