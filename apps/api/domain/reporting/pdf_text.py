"""One place that knows the PDF core fonts cannot print a rupee sign.

WHY THIS EXISTS AS A MODULE

The Indian Rupee sign (₹, U+20B9) is not in WinAnsiEncoding, which is what
reportlab's built-in Helvetica and Times use. A string containing it does not
raise, does not warn, and does not fall back to anything sensible — it lands in
the PDF as an unmapped glyph. Rendered and read back:

    'PAYSLIP  Net Pay: ■1,234.56'

Two services already knew this and handled it privately, with the reasoning
written out twice; three others did not, and shipped the box to a CA's customer,
to an employee, and into a signed year-end set. Discovering the same fact
independently five times is how four of them got it wrong, so it is one function
now.

WHY "Rs." AND NOT AN EMBEDDED FONT

Embedding a Unicode TTF would let the real glyph print, and is the better answer
eventually. It needs a licensed font file in the repo, a registerFont call in
every service, and a decision about what happens when the file is missing at
runtime. "Rs." is what Indian statutory forms themselves use, needs nothing, and
cannot fail. The trade is recorded here so the next person does not re-derive it.

WHAT THIS IS NOT FOR

HTML that will be shown in a browser or an email body. Every modern client
renders ₹ correctly, and replacing it there makes the product look dated. This
is for text on its way into a PDF, and nowhere else.
"""
from __future__ import annotations

#: U+20B9. Named so a grep for the character finds this module too.
RUPEE_SIGN = "₹"

#: What the statutory forms themselves print.
RUPEE_PDF = "Rs."


def pdf_safe(text: str | None) -> str:
    """Replace ₹ with "Rs." for text destined for a core-font PDF.

    Returns "" for None so a caller can use it on an optional field without a
    guard — a missing value must print as nothing, never as the word "None".
    """
    return (text or "").replace(RUPEE_SIGN, RUPEE_PDF)
