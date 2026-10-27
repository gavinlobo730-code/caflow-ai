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

THE PDF SERVICES NEVER CONSTRUCT A ₹ STRING, AND THAT WAS NOT ENOUGH

They write "Rs." into their own format strings, and
`tests/test_no_pdf_renders_the_rupee_sign.py` holds that by failing on any U+20B9
a PDF service could put on a page. What that cannot see is text WRITTEN
ELSEWHERE that a service prints: a sentence a domain module words for a screen
(a gap, a caveat, a stored note) and text a person typed (a narration, an
adjustment's reason, a name). On 27-10-2026 a sweep that put "₹" into the
sentences a CA reads sent it into the year-end pack's notes (a stored tie-out
sentence) and into the receivables and payables ageing report's notes (the
advances' gaps), where it printed as a black box in a set a CA signs, and the
review of that change found the other half: a plain string in a table CELL never
passes through a paragraph, so a typed narration printed a box when it was short
and "Rs." when it was long enough to wrap.

So the boundary is the two flowables that carry text, and not the producer: every
PDF service builds its paragraphs through `services/pdf_style.Paragraph` (which
passes the text through `pdf_safe(..., prose=True)` and writes "Rs. ") and its
tables through `services/pdf_style.Table` (which writes "Rs." in a plain-string
cell, the table-cell form below), and
`tests/test_text_written_elsewhere_that_reaches_a_pdf_page_has_no_rupee_sign.py`
holds that no service imports reportlab's own. What is NOT covered because it cannot
carry such text: the page furniture draws only "Page N of M", and the document's
title and author metadata are never drawn.

The CA-authored HTML of an engagement letter keeps `engagement_pdf_service._pdf_safe`,
which is the same substitution on HTML.

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


#: The same word for running prose, where "Rs. 1,000.00" reads better than "Rs.1,000.00".
RUPEE_PDF_PROSE = "Rs. "


def pdf_safe(text: str | None, *, prose: bool = False) -> str:
    """Replace ₹ with "Rs." for text destined for a core-font PDF.

    `prose=True` writes "Rs. " (a space), for a sentence; the default is the table-cell form.

    Returns "" for None so a caller can use it on an optional field without a
    guard — a missing value must print as nothing, never as the word "None".
    """
    return (text or "").replace(RUPEE_SIGN, RUPEE_PDF_PROSE if prose else RUPEE_PDF)
