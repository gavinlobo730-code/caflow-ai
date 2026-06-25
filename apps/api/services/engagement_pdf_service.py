"""
Engagement letter PDF rendering.

Converts the rendered HTML content of an engagement letter into a PDF document
suitable for emailing to the prospective client as an attachment.

CGST Act Section 31 requires written engagement documentation before service
commencement — this PDF is that written record.

All monetary values in the letter are rendered upstream (integer paise →
display string by routers.engagement_letters._format_fee); this module performs
NO arithmetic on amounts — it only typesets the already-rendered HTML.
"""
import io
import logging

logger = logging.getLogger("caflow.services")


def _pdf_safe(html: str) -> str:
    """
    The Indian Rupee sign (₹, U+20B9) is absent from the PDF core fonts
    (Helvetica/Times), so it renders as a missing-glyph box. Substitute the
    universally supported "Rs." prefix for the PDF copy only — the email body
    keeps the ₹ glyph, which every modern email client renders correctly.
    """
    return (html or "").replace("₹", "Rs. ")


# A minimal, print-friendly wrapper. xhtml2pdf supports a CSS subset; these
# rules are all within it. The letter content itself is a trusted HTML fragment
# produced from our own templates (h2/h3/p/ul/li/strong/br).
_WRAPPER = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
  @page {{ size: a4; margin: 2cm; }}
  body {{ font-family: Helvetica, Arial, sans-serif; font-size: 11pt;
          color: #1a1a1a; line-height: 1.5; }}
  h2 {{ font-size: 16pt; margin: 0 0 12pt 0; }}
  h3 {{ font-size: 12pt; margin: 14pt 0 4pt 0; }}
  ul {{ margin: 4pt 0 8pt 18pt; }}
  li {{ margin: 2pt 0; }}
  p  {{ margin: 6pt 0; }}
</style>
</head>
<body>{body}</body>
</html>"""


def render_engagement_pdf(content_html: str, engagement_number: str) -> tuple[bytes, str]:
    """
    Render the engagement letter HTML to PDF bytes.

    Returns (pdf_bytes, suggested_filename).
    Raises RuntimeError on failure so the caller can decide how to degrade
    (e.g. fall back to a body-only email).
    """
    from xhtml2pdf import pisa  # lazy import — keeps app start-up light

    document = _WRAPPER.format(body=_pdf_safe(content_html))
    buf = io.BytesIO()
    result = pisa.CreatePDF(src=document, dest=buf, encoding="utf-8")
    if result.err:
        raise RuntimeError(f"engagement PDF generation failed ({result.err} errors)")
    filename = f"engagement-letter-{engagement_number or 'draft'}.pdf"
    return buf.getvalue(), filename
