"""An amount of rupees inside a SENTENCE a person reads: the function every such sentence calls, so the sign and the word "minus" are written once.

`domain/money_text` is deliberately unit-free (digits only), because `domain/reporting/pdf_money` re-exports it and every PDF
service calls it, and a PDF cannot draw the sign (`tests/test_a_rupee_figure_is_grouped_the_indian_way.py` fails the day that module
emits one). A sentence on a screen, in an email or in a refusal wants the unit, so the function that adds it lives here, beside and
not inside the authority: it takes the grouping from `rupees_paise` and adds only the sign and the word "minus".
"""
from __future__ import annotations

from domain.money_text import group_indian, minor_units_text, rupees_paise

__all__ = ["amount_text", "rupee_text", "rupee_whole_text"]


def rupee_text(paise: int | None, unit: str = "₹") -> str:
    """Integer paise -> `"₹12,34,567.50"`, and `"minus ₹1.50"` for -150: an AMOUNT INSIDE A SENTENCE.

    For a sentence a person reads on a screen, in an email or in a refusal: the unit is the rupee sign, the grouping is
    `rupees_paise`'s and a negative amount is written in words, because `"₹" + "-1.50"` is "₹-1.50", which reads as a rupee
    sign with a minus sign inside it and is how three review passes found the same defect. NEVER for a PDF, whose core fonts have
    no glyph for the sign: text that was written elsewhere and ends on a PDF page goes through `domain.reporting.pdf_text.pdf_safe`
    at the PDF, which turns this into "Rs." and keeps the "minus".

    `unit` is the module's own word for the currency where it has one ("Rs " in a statutory note that is stored and printed, with
    its space): the sign, the grouping and the "minus" are the same whatever it is, which is what private copies of this function
    each got slightly differently.
    """
    p = int(paise or 0)
    sign = "minus " if p < 0 else ""
    return f"{sign}{unit}{rupees_paise(abs(p))}"


def rupee_whole_text(paise: int | None, unit: str = "₹") -> str:
    """Integer paise -> `"₹12,34,567"`: WHOLE rupees, truncated toward zero, for a sentence where the paise are noise (a threshold,
    a limit, a turnover in crores). `"minus ₹5"` for -500, and no minus for a magnitude under one rupee ("-0" is not a figure)."""
    p = int(paise or 0)
    whole = abs(p) // 100
    sign = "minus " if p < 0 and whole else ""
    return f"{sign}{unit}{group_indian(str(whole))}"


def amount_text(amount: int | None, currency: str | None = None, minor_unit: int | None = None) -> str:
    """An amount of money in a sentence where the document may be in a FOREIGN currency.

    Base currency (no code, or INR) is `rupee_text`. A foreign amount is integer MINOR units of that currency and is never written
    with the rupee sign, which would say a dollar amount is rupees: with the currency's own decimals when the caller has them
    (`currencies.minor_unit`, JPY 0, USD 2, KWD 3), and otherwise as the bare count of smallest units with the code beside it and
    the words saying so, because how many make one unit is not guessed here.
    """
    code = (currency or "").strip().upper()
    if code in ("", "INR"):
        return rupee_text(amount)
    if minor_unit is not None:
        return f"{minor_units_text(amount, minor_unit)} {code}"
    return f"{int(amount or 0)} {code} (smallest units)"
