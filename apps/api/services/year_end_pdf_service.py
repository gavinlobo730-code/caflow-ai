"""
Year End PDF Service — Phase 6.
Generates professional CA-presentation PDFs using ReportLab.

Schedule III formatting: Companies Act 2013, Schedule III.
All monetary values: integer paise (BIGINT) internally.
Display conversion: paise // 100 → rupees (integer division, never float).
Indian number format: 1,23,456 (lakh/crore grouping).
"""
from io import BytesIO
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle,
    Paragraph, Spacer, PageBreak, HRFlowable,
)

# ── Indian number formatting ──────────────────────────────────────────────────

def _paise_to_rupees(paise: int) -> int:
    """
    Convert integer paise to integer rupees.
    Integer division only — never float.
    """
    return int(paise) // 100


def _format_indian(amount_rupees: int) -> str:
    """
    Format integer rupees in Indian number system.
    Examples: 1234567 → '12,34,567'; 100000 → '1,00,000'; -500 → '-500'
    """
    negative = amount_rupees < 0
    n = abs(amount_rupees)
    s = str(n)

    if len(s) <= 3:
        result = s
    else:
        # Last 3 digits, then groups of 2
        last3 = s[-3:]
        rest  = s[:-3]
        groups = []
        while len(rest) > 2:
            groups.append(rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.append(rest)
        groups.reverse()
        result = ','.join(groups) + ',' + last3

    return f"-{result}" if negative else result


def _rs(paise: int) -> str:
    """Convert paise to formatted Indian rupee string for display in PDF."""
    return _format_indian(_paise_to_rupees(paise))


# ── Colour palette ────────────────────────────────────────────────────────────

_HEADER_BG   = colors.HexColor("#1a3c5e")   # Navy blue — CA firm theme
_SUBHEAD_BG  = colors.HexColor("#2e6da4")
_ALT_ROW_BG  = colors.HexColor("#f0f4f8")
_TOTAL_BG    = colors.HexColor("#dce8f5")
_WHITE       = colors.white
_BLACK       = colors.black
_GREY        = colors.HexColor("#666666")
_DRAFT_RED   = colors.HexColor("#cc0000")

PAGE_W, PAGE_H = A4


# ── Style helpers ─────────────────────────────────────────────────────────────

def _styles():
    s = getSampleStyleSheet()
    base = s["Normal"]

    title_style = ParagraphStyle(
        "CATitle", parent=base,
        fontSize=16, fontName="Helvetica-Bold",
        textColor=_HEADER_BG, alignment=1, spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "CASubtitle", parent=base,
        fontSize=11, fontName="Helvetica",
        textColor=_GREY, alignment=1, spaceAfter=8,
    )
    section_style = ParagraphStyle(
        "CASection", parent=base,
        fontSize=11, fontName="Helvetica-Bold",
        textColor=_HEADER_BG, spaceBefore=12, spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "CABody", parent=base,
        fontSize=9, fontName="Helvetica",
        spaceAfter=4,
    )
    note_style = ParagraphStyle(
        "CANote", parent=base,
        fontSize=8, fontName="Helvetica-Oblique",
        textColor=_GREY, spaceAfter=2,
    )
    watermark_style = ParagraphStyle(
        "CAWatermark", parent=base,
        fontSize=28, fontName="Helvetica-Bold",
        textColor=colors.Color(0.8, 0.1, 0.1, alpha=0.35),
        alignment=1,
    )
    return {
        "title":     title_style,
        "subtitle":  subtitle_style,
        "section":   section_style,
        "body":      body_style,
        "note":      note_style,
        "watermark": watermark_style,
    }


def _table_style(has_total_row: bool = False) -> TableStyle:
    cmds = [
        ("BACKGROUND",   (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR",    (0, 0), (-1, 0), _WHITE),
        ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, 0), 9),
        ("ALIGN",        (0, 0), (-1, 0), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2 if has_total_row else -1), [_WHITE, _ALT_ROW_BG]),
        ("FONTSIZE",     (0, 1), (-1, -1), 9),
        ("ALIGN",        (1, 1), (-1, -1), "RIGHT"),
        ("ALIGN",        (0, 1), (0, -1), "LEFT"),
        ("GRID",         (0, 0), (-1, -1), 0.4, _GREY),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    if has_total_row:
        cmds += [
            ("BACKGROUND", (0, -1), (-1, -1), _TOTAL_BG),
            ("FONTNAME",   (0, -1), (-1, -1), "Helvetica-Bold"),
        ]
    return TableStyle(cmds)


def _cover_page(elements, st, eng: dict, doc_title: str, is_draft: bool):
    """Build cover page elements."""
    elements.append(Spacer(1, 40 * mm))

    if is_draft:
        elements.append(Paragraph("DRAFT — NOT FOR DISTRIBUTION", st["watermark"]))
        elements.append(Spacer(1, 8 * mm))

    elements.append(Paragraph(doc_title, st["title"]))
    elements.append(Spacer(1, 6 * mm))
    elements.append(HRFlowable(width="80%", thickness=2, color=_HEADER_BG, hAlign="CENTER"))
    elements.append(Spacer(1, 6 * mm))

    client_name = eng.get("client_name") or eng.get("client_id", "—")
    fy = eng.get("financial_year", "—")
    status = eng.get("status", "—").upper()
    generated_at = datetime.now().strftime("%d %b %Y, %H:%M")

    info_rows = [
        ["Client:",        client_name],
        ["Financial Year:",f"FY {fy} (April 1 – March 31)"],
        ["Status:",        status],
        ["Generated:",     generated_at],
        ["Prepared by:",   "CAflow AI — Practice Management Platform"],
    ]
    for row in info_rows:
        elements.append(
            Paragraph(f"<b>{row[0]}</b>  {row[1]}", st["body"])
        )

    elements.append(Spacer(1, 20 * mm))
    elements.append(
        Paragraph(
            "This document is prepared for the internal use of the CA firm. "
            "All financial data is sourced from the verified General Ledger.",
            st["note"],
        )
    )


# ── Balance Sheet section ─────────────────────────────────────────────────────

def _bs_section(elements, st, bs_data: dict):
    elements.append(Paragraph("BALANCE SHEET", st["section"]))
    elements.append(
        Paragraph(
            "As per Schedule III, Companies Act 2013. "
            "All figures in Indian Rupees (₹). Amounts in paise are converted to rupees for display.",
            st["note"],
        )
    )
    elements.append(Spacer(1, 3 * mm))

    eq_lib = bs_data.get("equity_and_liabilities", {})
    assets = bs_data.get("assets", {})

    _EQUITY_LABELS = {
        "share_capital":              "Share Capital",
        "reserves_and_surplus":       "Reserves and Surplus",
        "long_term_borrowings":       "Long-term Borrowings",
        "deferred_tax_liabilities":   "Deferred Tax Liabilities",
        "other_long_term_liabilities":"Other Long-term Liabilities",
        "long_term_provisions":       "Long-term Provisions",
        "short_term_borrowings":      "Short-term Borrowings",
        "trade_payables":             "Trade Payables",
        "other_current_liabilities":  "Other Current Liabilities",
        "short_term_provisions":      "Short-term Provisions",
    }
    _ASSET_LABELS = {
        "tangible_assets":              "Tangible Assets",
        "intangible_assets":            "Intangible Assets",
        "capital_wip":                  "Capital Work-in-Progress",
        "long_term_investments":        "Long-term Investments",
        "deferred_tax_assets":          "Deferred Tax Assets",
        "long_term_loans_and_advances": "Long-term Loans and Advances",
        "other_non_current_assets":     "Other Non-current Assets",
        "current_investments":          "Current Investments",
        "inventories":                  "Inventories",
        "trade_receivables":            "Trade Receivables",
        "cash_and_bank":                "Cash and Bank Balances",
        "short_term_loans_and_advances":"Short-term Loans and Advances",
        "other_current_assets":         "Other Current Assets",
    }

    # Equity & Liabilities table
    eq_rows = [["Equity & Liabilities", "₹"]]
    for k, label in _EQUITY_LABELS.items():
        v = eq_lib.get(k, 0)
        eq_rows.append([label, _rs(v)])
    total_el = bs_data.get("total_equity_and_liabilities_paise", sum(eq_lib.values()))
    eq_rows.append(["TOTAL EQUITY AND LIABILITIES", _rs(total_el)])

    # Assets table
    asset_rows = [["Assets", "₹"]]
    for k, label in _ASSET_LABELS.items():
        v = assets.get(k, 0)
        asset_rows.append([label, _rs(v)])
    total_a = bs_data.get("total_assets_paise", sum(assets.values()))
    asset_rows.append(["TOTAL ASSETS", _rs(total_a)])

    col_w = [(PAGE_W - 60 * mm) * 0.70, (PAGE_W - 60 * mm) * 0.30]

    for rows in [eq_rows, asset_rows]:
        t = Table(rows, colWidths=col_w)
        t.setStyle(_table_style(has_total_row=True))
        elements.append(t)
        elements.append(Spacer(1, 4 * mm))


# ── P&L section ───────────────────────────────────────────────────────────────

def _pl_section(elements, st, pl_data: dict):
    elements.append(Paragraph("STATEMENT OF PROFIT AND LOSS", st["section"]))
    elements.append(
        Paragraph(
            "As per Schedule III, Companies Act 2013. "
            "All figures in Indian Rupees (₹).",
            st["note"],
        )
    )
    elements.append(Spacer(1, 3 * mm))

    _INCOME_LABELS = {
        "revenue_from_operations": "Revenue from Operations",
        "other_income":            "Other Income",
    }
    _EXPENSE_LABELS = {
        "cost_of_materials_consumed":   "Cost of Materials Consumed",
        "purchases_of_stock_in_trade":  "Purchases of Stock-in-Trade",
        "changes_in_inventories":       "Changes in Inventories",
        "employee_benefit_expense":     "Employee Benefit Expense",
        "finance_costs":                "Finance Costs",
        "depreciation_and_amortisation":"Depreciation and Amortisation",
        "other_expenses":               "Other Expenses",
    }

    income  = pl_data.get("income", {})
    expense = pl_data.get("expenses", {})

    rows = [["Particulars", "₹"]]
    rows.append(["I. INCOME", ""])
    for k, label in _INCOME_LABELS.items():
        rows.append([f"   {label}", _rs(income.get(k, 0))])
    total_income = pl_data.get("total_income_paise", sum(income.values()))
    rows.append(["   Total Income", _rs(total_income)])

    rows.append(["II. EXPENSES", ""])
    for k, label in _EXPENSE_LABELS.items():
        rows.append([f"   {label}", _rs(expense.get(k, 0))])
    total_expense = pl_data.get("total_expense_paise", sum(expense.values()))
    rows.append(["   Total Expenses", _rs(total_expense)])

    pbt = pl_data.get("profit_before_tax_paise", total_income - total_expense)
    tax = pl_data.get("tax_expense_paise", 0)
    pat = pl_data.get("profit_after_tax_paise", pbt - tax)

    rows.append(["III. Profit Before Tax (I - II)",  _rs(pbt)])
    rows.append(["IV.  Tax Expense",                  _rs(tax)])
    rows.append(["V.   Profit After Tax (III - IV)",  _rs(pat)])

    col_w = [(PAGE_W - 60 * mm) * 0.70, (PAGE_W - 60 * mm) * 0.30]
    t = Table(rows, colWidths=col_w)
    t.setStyle(_table_style(has_total_row=False))
    elements.append(t)


# ── Public API ────────────────────────────────────────────────────────────────

def generate_financial_statements_pdf(engagement_data: dict, statements_data: dict) -> bytes:
    """
    Generate Schedule III formatted Balance Sheet + P&L PDF.
    All paise values converted to rupees (integer division) for display only.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=25 * mm, rightMargin=25 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    )
    st = _styles()
    is_draft = engagement_data.get("status") not in ("approved", "locked")
    elements = []

    _cover_page(elements, st, engagement_data, "Financial Statements", is_draft)
    elements.append(PageBreak())

    _bs_section(elements, st, statements_data.get("balance_sheet", {}))
    elements.append(PageBreak())
    _pl_section(elements, st, statements_data.get("profit_loss", {}))

    doc.build(elements)
    return buf.getvalue()


def generate_notes_pdf(engagement_data: dict, notes_data: list) -> bytes:
    """
    Generate Notes to Accounts PDF.
    Each note rendered as a section with title, content, and data table.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=25 * mm, rightMargin=25 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    )
    st = _styles()
    is_draft = engagement_data.get("status") not in ("approved", "locked")
    elements = []

    _cover_page(elements, st, engagement_data, "Notes to Accounts", is_draft)
    elements.append(PageBreak())

    elements.append(Paragraph("NOTES TO FINANCIAL STATEMENTS", st["section"]))
    elements.append(
        Paragraph(
            "As required by Schedule III, Companies Act 2013. "
            "All figures in Indian Rupees (₹).",
            st["note"],
        )
    )
    elements.append(Spacer(1, 4 * mm))

    for note in sorted(notes_data, key=lambda n: n.get("sequence_no", 99)):
        elements.append(Paragraph(note.get("title", ""), st["section"]))
        elements.append(Paragraph(note.get("content", ""), st["body"]))

        note_data = note.get("note_data", {})
        # Render monetary fields in note_data as a small table
        monetary_rows = [
            (k.replace("_paise", "").replace("_", " ").title(), _rs(v))
            for k, v in note_data.items()
            if k.endswith("_paise") and isinstance(v, int)
        ]
        if monetary_rows:
            tbl = Table(
                [["Particulars", "₹ (Rupees)"]] + [[r[0], r[1]] for r in monetary_rows],
                colWidths=[(PAGE_W - 70 * mm) * 0.65, (PAGE_W - 70 * mm) * 0.35],
            )
            tbl.setStyle(_table_style(has_total_row=False))
            elements.append(tbl)

        elements.append(Spacer(1, 6 * mm))

    doc.build(elements)
    return buf.getvalue()


def generate_complete_pack_pdf(
    engagement_data: dict,
    statements_data: dict,
    notes_data: list,
    adjustments: list,
) -> bytes:
    """
    Complete year-end pack:
    Cover → Balance Sheet → P&L → Notes → Adjustment Register → Approval History.

    Watermarks 'DRAFT — NOT FOR DISTRIBUTION' if status is not 'approved' or 'locked'.
    All paise values converted to rupees (// 100, integer division) for display only.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=25 * mm, rightMargin=25 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    )
    st = _styles()
    status   = engagement_data.get("status", "draft")
    is_draft = status not in ("approved", "locked")
    elements = []

    # ── Cover ────────────────────────────────────────────────────────────────
    _cover_page(elements, st, engagement_data, "Year-End Audit Pack", is_draft)
    elements.append(PageBreak())

    # ── Balance Sheet ────────────────────────────────────────────────────────
    if is_draft:
        elements.append(Paragraph("DRAFT — NOT FOR DISTRIBUTION", st["watermark"]))
    _bs_section(elements, st, statements_data.get("balance_sheet", {}))
    elements.append(PageBreak())

    # ── P&L ─────────────────────────────────────────────────────────────────
    if is_draft:
        elements.append(Paragraph("DRAFT — NOT FOR DISTRIBUTION", st["watermark"]))
    _pl_section(elements, st, statements_data.get("profit_loss", {}))
    elements.append(PageBreak())

    # ── Notes to Accounts ────────────────────────────────────────────────────
    elements.append(Paragraph("NOTES TO FINANCIAL STATEMENTS", st["section"]))
    for note in sorted(notes_data, key=lambda n: n.get("sequence_no", 99)):
        elements.append(Paragraph(note.get("title", ""), st["section"]))
        elements.append(Paragraph(note.get("content", ""), st["body"]))
        elements.append(Spacer(1, 4 * mm))
    elements.append(PageBreak())

    # ── Adjustment Register ──────────────────────────────────────────────────
    elements.append(Paragraph("YEAR-END ADJUSTMENT REGISTER", st["section"]))
    elements.append(
        Paragraph("All amounts in Indian Rupees (₹). Paise converted to rupees for display.", st["note"])
    )
    elements.append(Spacer(1, 3 * mm))

    adj_rows = [["#", "Type", "Description", "Date", "Amount (₹)", "Status"]]
    for i, adj in enumerate(adjustments, start=1):
        adj_rows.append([
            str(i),
            adj.get("adjustment_type", "—"),
            (adj.get("description", "") or "")[:40],
            adj.get("adjustment_date", "—"),
            _rs(adj.get("amount_paise", 0)),   # integer paise → rupees display
            adj.get("status", "—").upper(),
        ])
    if len(adj_rows) == 1:
        adj_rows.append(["—", "—", "No adjustments recorded", "—", "—", "—"])

    avail_w = PAGE_W - 50 * mm
    adj_col_w = [
        avail_w * 0.05, avail_w * 0.13, avail_w * 0.35,
        avail_w * 0.12, avail_w * 0.15, avail_w * 0.20,
    ]
    t = Table(adj_rows, colWidths=adj_col_w)
    t.setStyle(_table_style(has_total_row=False))
    elements.append(t)
    elements.append(PageBreak())

    # ── Approval History ─────────────────────────────────────────────────────
    elements.append(Paragraph("APPROVAL HISTORY", st["section"]))
    elements.append(Spacer(1, 3 * mm))

    hist_rows = [["Event", "Actor", "Date", "Status"]]
    if engagement_data.get("submitted_at"):
        hist_rows.append(["Submitted for Review",
                           engagement_data.get("submitted_by", "—"),
                           engagement_data.get("submitted_at", "—")[:10], "SUBMITTED"])
    if engagement_data.get("approved_at"):
        hist_rows.append(["Manager Approved",
                           engagement_data.get("approved_by", "—"),
                           engagement_data.get("approved_at", "—")[:10], "APPROVED"])
    if engagement_data.get("final_approved_at"):
        hist_rows.append(["Partner Final Approval",
                           engagement_data.get("final_approved_by", "—"),
                           engagement_data.get("final_approved_at", "—")[:10], "LOCKED"])
    if len(hist_rows) == 1:
        hist_rows.append(["No approval history", "—", "—", "—"])

    hist_col_w = [avail_w * 0.35, avail_w * 0.25, avail_w * 0.20, avail_w * 0.20]
    th = Table(hist_rows, colWidths=hist_col_w)
    th.setStyle(_table_style(has_total_row=False))
    elements.append(th)
    elements.append(Spacer(1, 8 * mm))

    elements.append(
        Paragraph(
            f"Generated by CAflow AI on {datetime.now().strftime('%d %b %Y %H:%M')}. "
            "For CA firm internal use only.",
            st["note"],
        )
    )

    doc.build(elements)
    return buf.getvalue()
