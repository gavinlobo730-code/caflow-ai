"""One place that knows the PDF core fonts cannot print a rupee sign.

WHY THIS EXISTS AS A MODULE

The Indian Rupee sign (₹, U+20B9) is not in WinAnsiEncoding, which is what
reportlab's built-in Helvetica and Times use. A string containing it does not
raise, does not warn, and does not fall back to anything sensible — it lands in
the PDF as an unmapped glyph. Rendered and read back:

    'PAYSLIP  Net Pay: ■1,234.56'

Two services already knew this and handled it privately, with the reasoning
written out twice; three others did not, and shipped the box to a CA's customer,
to an employee, and into a signed year-end set.

⚠️ THIS MODULE HAS NO PRODUCTION IMPORTER, AND THAT IS NOT A BUG TO FIX BY
WIRING IT IN. An earlier version of this docstring said the fix was "one
function now", which was the intention and is not what happened. What the five
PDF services actually do is never CONSTRUCT a ₹ string at all — they write
"Rs." into their format strings directly — and
`tests/test_no_pdf_renders_the_rupee_sign.py` is what holds that, by failing on
any U+20B9 a PDF service could put on a page. A substitution helper has nothing
to substitute.

The one place the text is NOT under a service's control is CA-authored HTML in
an engagement letter, and `services/engagement_pdf_service._pdf_safe` handles
that. It is deliberately NOT this function: it replaces with **"Rs. "**, a
space, because that text is running prose, where this module uses **"Rs."**
without one, because its case is a table cell. Two answers to two questions.
Unifying them would change a document a client receives.

So this module is kept for the RULE it records rather than for a caller, and
`tests/test_a_domain_module_has_a_reader.py` names it with that reason so the
next sweep does not re-find it.

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
