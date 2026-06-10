"""
GST-compliant invoice PDF generation.

Mandatory tax invoice particulars per Rule 46, CGST Rules 2017 (under
Section 31, CGST Act 2017):
  - Supplier (firm) name, address, GSTIN
  - Consecutive invoice number and date
  - Recipient (client) name, address, GSTIN
  - SAC code (998211 — professional/CA services)
  - Description, taxable value, tax rate and tax amount
  - CGST + SGST split for intra-state supply, IGST for inter-state
    (place of supply determined by the first two GSTIN digits — state code)

All monetary values arrive as integer paise and are formatted for display
only — no float arithmetic is performed on amounts.
"""
import io
import logging
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

logger = logging.getLogger("caflow.services")

SAC_CODE = "998211"
GST_RATE_PCT = 18


def _paise_to_rupee_str(paise: int) -> str:
    """Format integer paise as rupees string, e.g. 123456 -> '1,234.56'."""
    rupees = paise // 100
    fraction = paise % 100
    return f"{rupees:,}.{fraction:02d}"


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
         "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
         "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two_digits(n: int) -> str:
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")).strip()


def _three_digits(n: int) -> str:
    s = ""
    if n >= 100:
        s = _ONES[n // 100] + " Hundred"
        if n % 100:
            s += " " + _two_digits(n % 100)
        return s
    return _two_digits(n)


def amount_in_words(paise: int) -> str:
    """Indian-system amount in words (Crore/Lakh/Thousand), required on tax invoices."""
    rupees = paise // 100
    p = paise % 100
    if rupees == 0:
        words = "Zero"
    else:
        crore = rupees // 10_000_000
        lakh = (rupees // 100_000) % 100
        thousand = (rupees // 1000) % 100
        rest = rupees % 1000
        parts = []
        if crore:
            parts.append(_three_digits(crore) + " Crore")
        if lakh:
            parts.append(_two_digits(lakh) + " Lakh")
        if thousand:
            parts.append(_two_digits(thousand) + " Thousand")
        if rest:
            parts.append(_three_digits(rest))
        words = " ".join(parts)
    result = f"Rupees {words}"
    if p:
        result += f" and {_two_digits(p)} Paise"
    return result + " Only"


def _state_code(gstin: Optional[str]) -> Optional[str]:
    if gstin and len(gstin) >= 2 and gstin[:2].isdigit():
        return gstin[:2]
    return None


def build_invoice_pdf(invoice: dict, firm: dict, client: dict, engagement: Optional[dict] = None) -> bytes:
    """Render a GST tax invoice PDF and return raw bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Tax Invoice {invoice.get('invoice_no', '')}",
    )
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
    bold = ParagraphStyle("bold", parent=styles["Normal"], fontName="Helvetica-Bold")

    story = []
    story.append(Paragraph("TAX INVOICE", ParagraphStyle(
        "title", parent=styles["Title"], fontSize=16, spaceAfter=2)))
    story.append(Paragraph("(Issued under Section 31, CGST Act 2017 read with Rule 46, CGST Rules 2017)", small))
    story.append(Spacer(1, 6 * mm))

    firm_name = firm.get("name") or firm.get("firm_name") or "Chartered Accountants"
    firm_lines = [f"<b>{firm_name}</b>"]
    if firm.get("address"):
        firm_lines.append(firm["address"])
    if firm.get("gstin"):
        firm_lines.append(f"GSTIN: {firm['gstin']}")
    if firm.get("pan"):
        firm_lines.append(f"PAN: {firm['pan']}")

    client_name = client.get("client_name") or client.get("name") or "Client"
    client_lines = [f"<b>{client_name}</b>"]
    if client.get("address"):
        client_lines.append(client["address"])
    if client.get("gstin"):
        client_lines.append(f"GSTIN: {client['gstin']}")
    if client.get("pan"):
        client_lines.append(f"PAN: {client['pan']}")

    meta_lines = [
        f"<b>Invoice No:</b> {invoice.get('invoice_no', '')}",
        f"<b>Invoice Date:</b> {str(invoice.get('invoice_date', ''))[:10]}",
    ]
    if invoice.get("due_date"):
        meta_lines.append(f"<b>Due Date:</b> {str(invoice['due_date'])[:10]}")
    meta_lines.append(f"<b>Status:</b> {invoice.get('status', '')}")

    header = Table(
        [[Paragraph("<br/>".join(firm_lines), styles["Normal"]),
          Paragraph("<br/>".join(meta_lines), styles["Normal"])],
         [Paragraph("<b>Bill To:</b><br/>" + "<br/>".join(client_lines), styles["Normal"]), ""]],
        colWidths=[100 * mm, 80 * mm],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
    ]))
    story.append(header)
    story.append(Spacer(1, 6 * mm))

    # Intra-state supply: CGST + SGST split equally; inter-state: IGST.
    # Place of supply per Section 12, IGST Act 2017 — state code from GSTINs.
    amount_paise = invoice.get("amount_paise", 0)
    gst_paise = invoice.get("gst_paise", 0)
    total_paise = invoice.get("total_paise", amount_paise + gst_paise)
    firm_state = _state_code(firm.get("gstin"))
    client_state = _state_code(client.get("gstin"))
    intra_state = firm_state is not None and firm_state == client_state

    description = "Professional Services — Chartered Accountancy"
    if engagement and engagement.get("service_type"):
        description = f"Professional Services — {engagement['service_type']}"

    rows = [
        ["#", "Description", "SAC", "Taxable Value (₹)"],
        ["1", Paragraph(description, styles["Normal"]), SAC_CODE, _paise_to_rupee_str(amount_paise)],
        ["", "Taxable Value", "", _paise_to_rupee_str(amount_paise)],
    ]
    if intra_state:
        # Integer split: CGST gets the floor half, SGST gets the remainder,
        # so CGST + SGST == gst_paise exactly with no paise lost.
        cgst = gst_paise // 2
        sgst = gst_paise - cgst
        rows.append(["", f"CGST @ {GST_RATE_PCT // 2}%", "", _paise_to_rupee_str(cgst)])
        rows.append(["", f"SGST @ {GST_RATE_PCT // 2}%", "", _paise_to_rupee_str(sgst)])
    else:
        rows.append(["", f"IGST @ {GST_RATE_PCT}%", "", _paise_to_rupee_str(gst_paise)])
    rows.append(["", "Total", "", _paise_to_rupee_str(total_paise)])

    table = Table(rows, colWidths=[10 * mm, 95 * mm, 25 * mm, 50 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (1, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"<b>Amount in words:</b> {amount_in_words(total_paise)}", styles["Normal"]))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(
        "Whether tax is payable on reverse charge basis: No", styles["Normal"]))
    story.append(Spacer(1, 14 * mm))
    story.append(Paragraph(f"For {firm_name}", bold))
    story.append(Spacer(1, 14 * mm))
    story.append(Paragraph("Authorised Signatory", styles["Normal"]))

    doc.build(story)
    return buf.getvalue()


def get_invoice_pdf(invoice_id: str) -> tuple[bytes, str]:
    """
    Load an invoice with its firm, client and engagement records and render the PDF.

    Returns:
        (pdf_bytes, suggested_filename)
    """
    from repositories.invoice_repository import invoice_repo
    from repositories.client_repository import client_repo

    invoice = invoice_repo.find_by_id_or_raise(invoice_id)

    client = {}
    try:
        client = client_repo.find_by_id(invoice.get("client_id")) or {}
    except Exception as e:
        logger.warning(f"Could not load client for invoice {invoice_id}: {e}")

    firm = _load_firm(invoice.get("firm_id"))

    engagement = None
    if invoice.get("engagement_id"):
        try:
            from repositories.engagement_repository import engagement_repo
            engagement = engagement_repo.find_by_id(invoice["engagement_id"])
        except Exception:
            engagement = None

    pdf = build_invoice_pdf(invoice, firm, client, engagement)
    filename = f"invoice-{invoice.get('invoice_no', invoice_id)}.pdf"
    return pdf, filename


def _load_firm(firm_id: Optional[str]) -> dict:
    if not firm_id:
        return {}
    try:
        from core.supabase_client import get_supabase
        result = get_supabase().table("firms").select("*").eq("id", firm_id).maybe_single().execute()
        return result.data or {}
    except Exception as e:
        logger.warning(f"Could not load firm {firm_id}: {e}")
        return {}
