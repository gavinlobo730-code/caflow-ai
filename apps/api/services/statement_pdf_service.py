"""
Customer statement PDF (Phase 4.1) — a read-only account statement.

Reuses the invoice PDF stack (reportlab, _load_firm, _paise_to_rupee_str). This
is NOT a tax document and carries NO accounting entries — it renders the opening
balance, the period's invoices/receipts/credit notes with a running balance, and
the closing outstanding. All amounts arrive as integer paise (display only).
"""
from __future__ import annotations

import io
import logging

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from services.invoice_pdf_service import _load_firm, _paise_to_rupee_str
from services.customer_statement_service import customer_statement_service

logger = logging.getLogger("caflow.services")


def _bal(paise: int) -> str:
    """Signed balance as 'x,xxx.xx Dr|Cr' (Dr = customer owes)."""
    side = "Dr" if paise >= 0 else "Cr"
    return f"{_paise_to_rupee_str(abs(paise))} {side}"


def build_statement_pdf(statement: dict, firm: dict, customer: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            title="Customer Statement")
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Title"], fontSize=16, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#64748B"))
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9)
    elems = []

    firm_name = firm.get("name") or "Chartered Accountant"
    period = statement["period"]
    elems.append(Paragraph(firm_name, h))
    elems.append(Paragraph("Customer Statement of Account", sub))
    elems.append(Spacer(1, 8))

    cust = statement["customer"]
    meta = [
        [Paragraph(f"<b>Customer:</b> {cust.get('name') or ''}", small),
         Paragraph(f"<b>Period:</b> {period['start_date']} to {period['end_date']}", small)],
        [Paragraph(f"<b>GSTIN:</b> {cust.get('gstin') or '—'}", small),
         Paragraph(f"<b>Email:</b> {cust.get('email') or '—'}", small)],
    ]
    mt = Table(meta, colWidths=[95 * mm, 83 * mm])
    mt.setStyle(TableStyle([("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 1)]))
    elems.append(mt)
    elems.append(Spacer(1, 10))

    rows = [["Date", "Particulars", "Ref", "Debit", "Credit", "Balance"]]
    rows.append(["", "Opening Balance", "", "", "", _bal(statement["opening_balance_paise"])])
    for t in statement["transactions"]:
        rows.append([
            t["date"], t["particulars"], t.get("reference") or "",
            _paise_to_rupee_str(t["debit_paise"]) if t["debit_paise"] else "",
            _paise_to_rupee_str(t["credit_paise"]) if t["credit_paise"] else "",
            _bal(t["running_balance_paise"]),
        ])
    rows.append(["", "Closing Outstanding", "", "", "", _bal(statement["closing_balance_paise"])])

    table = Table(rows, colWidths=[20 * mm, 70 * mm, 24 * mm, 22 * mm, 22 * mm, 20 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F1F5F9")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F1F5F9")),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#0F172A")),
        ("ROWBACKGROUNDS", (0, 2), (-1, -2), [colors.white, colors.HexColor("#FAFAFA")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elems.append(table)
    elems.append(Spacer(1, 8))

    tot = statement["totals"]
    elems.append(Paragraph(
        f"Invoiced: ₹{_paise_to_rupee_str(tot['invoiced_paise'])} &nbsp;|&nbsp; "
        f"Received: ₹{_paise_to_rupee_str(tot['received_paise'])} &nbsp;|&nbsp; "
        f"Credits: ₹{_paise_to_rupee_str(tot['credited_paise'])}", sub))
    elems.append(Spacer(1, 6))
    elems.append(Paragraph("This is a statement of account, not a tax invoice. Amounts in INR.", sub))

    doc.build(elems)
    return buf.getvalue()


def get_customer_statement_pdf(db, firm_id, client_id, customer_id, start, end) -> tuple[bytes, str]:
    statement = customer_statement_service.generate(db, firm_id, client_id, customer_id, start, end)
    firm = _load_firm(firm_id)
    pdf = build_statement_pdf(statement, firm, statement["customer"])
    name = (statement["customer"].get("name") or "customer").replace(" ", "-").lower()
    filename = f"statement-{name}-{start}-{end}.pdf"
    return pdf, filename
