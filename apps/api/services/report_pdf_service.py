"""A live report as a PDF a CA can hand to a bank or an auditor (accounting-16).

ONE RENDERER FOR EVERY REPORT. The ledger, the trial balance, the cash flow
statement and the two ageing reports are all a title, some lines saying whose
books and which period, one or more tables of figures, and a few caveats — so
they are one `ReportDocument` (`domain/reporting/export_document`) drawn here,
rather than five services that each pick their own header colour. That is the
defect `services/pdf_style` was written to end, and a sixth document that
reached for its own palette would have been the seventh member of it.

WHOSE LETTERHEAD

    The page is headed by the PRACTICE that prepared it — its name and its own
    GSTIN, read through `domain/firm/identity.gstin_of` because `public.firms`
    carries the GSTIN in two columns and only one is ever written — and then
    names the CLIENT whose books these are, which is the subject of the
    document and the title under the rule.

    That is the opposite of the customer statement and the sales invoice, which
    are headed by the CLIENT: those are documents the client issues to a
    STRANGER (its own customer) and a practice's name on them misstates who is
    owed. A ledger is not issued to anybody. It is a report the practice hands
    to a banker or an auditor about the client, and the practice is the one
    vouching for it. The footer carries nothing but the page number
    (`pdf_page_furniture`) for the same reason it does everywhere: the margin
    is where branding has leaked into a client's document before.

WHAT IT DOES NOT DO

    It computes no figure and decides no colour. Money is grouped by
    `domain/money_text` and carries no rupee sign — ReportLab's core fonts have
    no glyph for U+20B9 and it prints as a black box, which shipped twice
    (`tests/test_no_pdf_renders_the_rupee_sign.py`) — so the unit is stated in
    the subtitle as "Amounts in INR" and nowhere beside a number.
"""
from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from core.ist_clock import ist_today
from domain.firm.identity import gstin_of
from domain.reporting.export_document import (
    BALANCE, EMPHASIS, INT, MONEY, SECTION, ReportDocument, cell_text,
)
from services import pdf_style
from services.pdf_page_furniture import numbered

_FONT_SIZE = 8
_PADDING = 3
_NUMERIC = (MONEY, BALANCE, INT)


def _holder_name(holder: dict) -> str:
    # The registered name first, as every statement of account does.
    return (holder.get("legal_name") or holder.get("trade_name")
            or holder.get("client_name") or "Books of account")


def _meta_rows(doc: ReportDocument, holder: dict) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if holder.get("gstin"):
        rows.append(("GSTIN", str(holder["gstin"])))
    if holder.get("pan"):
        rows.append(("PAN", str(holder["pan"])))
    rows.extend(doc.meta)
    return rows


def build_report_pdf(doc: ReportDocument, *, holder: dict, firm: dict,
                     generated_on: str | None = None) -> bytes:
    """`doc` on a page, headed by `firm` and naming `holder` as the client."""
    page = landscape(A4) if doc.landscape else A4
    margin_lr = 16 * mm
    avail = page[0] - 2 * margin_lr

    buf = io.BytesIO()
    pdf = SimpleDocTemplate(
        buf, pagesize=page, topMargin=18 * mm, bottomMargin=18 * mm,
        leftMargin=margin_lr, rightMargin=margin_lr,
        title=f"{doc.title} - {_holder_name(holder)}",
        author=firm.get("name") or "",
    )
    styles = pdf_style.paragraph_styles()
    cell = ParagraphStyle("report_cell", parent=styles["body"], fontSize=_FONT_SIZE,
                          leading=_FONT_SIZE + 2)
    story: list = []

    # ── The practice's own heading ───────────────────────────────────────────
    firm_name = firm.get("name") or "Chartered Accountant"
    firm_gstin = gstin_of(firm)
    story.append(Paragraph(escape(firm_name), styles["section"]))
    if firm_gstin:
        story.append(Paragraph(f"GSTIN {escape(firm_gstin)}", styles["note"]))
    story.append(Spacer(1, 3))
    story.append(HRFlowable(width="100%", thickness=0.5, color=pdf_style.C_BORDER_STRONG,
                            spaceBefore=0, spaceAfter=6))

    # ── Whose books, which report, which period ──────────────────────────────
    # `Title` is centred by default and the practice's heading above it is not;
    # one page reads from one left edge.
    title_style = ParagraphStyle("report_title", parent=styles["doc_title"], alignment=0)
    story.append(Paragraph(escape(_holder_name(holder)), title_style))
    heading = doc.title + (f" - {doc.subject}" if doc.subject else "")
    story.append(Paragraph(escape(heading), styles["doc_subtitle"]))
    if doc.period:
        story.append(Paragraph(escape(doc.period) + " &nbsp;|&nbsp; Amounts in INR",
                               styles["doc_subtitle"]))
    else:
        story.append(Paragraph("Amounts in INR", styles["doc_subtitle"]))
    story.append(Spacer(1, 6))

    meta = _meta_rows(doc, holder)
    if meta:
        # Two to a line, laid out as a headerless block (no header row, so no
        # repeatRows — a line of data must not reappear at the top of page 2).
        cells = [Paragraph(f"<b>{escape(k)}:</b> {escape(v)}", styles["body"])
                 for k, v in meta]
        if len(cells) % 2:
            cells.append(Paragraph("", styles["body"]))
        grid = [cells[i:i + 2] for i in range(0, len(cells), 2)]
        mt = Table(grid, colWidths=[avail / 2, avail / 2])
        mt.setStyle(TableStyle([("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                                ("TOPPADDING", (0, 0), (-1, -1), 1),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        story.append(mt)
        story.append(Spacer(1, 6))

    # ── The tables ───────────────────────────────────────────────────────────
    for tbl in doc.tables:
        if tbl.heading:
            story.append(Paragraph(escape(tbl.heading), styles["section"]))
        total_weight = sum(c.weight for c in tbl.columns) or 1.0
        widths = [avail * c.weight / total_weight for c in tbl.columns]

        # Room for a string inside a cell: the column less Table's default 6pt
        # of padding either side.
        room = [w - 12 for w in widths]
        data: list[list] = [[c.label for c in tbl.columns]]
        extra: list[tuple] = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            # Body text is the palette's body ink whether a cell is a plain
            # string or a Paragraph, so a row that happens to wrap does not
            # read in a different black from the one beside it.
            ("TEXTCOLOR", (0, 1), (-1, -1), pdf_style.C_BODY),
        ]
        for i, col in enumerate(tbl.columns):
            if col.kind in _NUMERIC:
                extra.append(("ALIGN", (i, 0), (i, -1), "RIGHT"))
        for r, row in enumerate(tbl.rows, start=1):
            plain = row.style in (EMPHASIS, SECTION)
            out = []
            for i, (col, value) in enumerate(zip(tbl.columns, row.cells)):
                text = cell_text(col.kind, value)
                # An ordinary text cell WRAPS when it has to (a narration can
                # run to several lines) and is otherwise a plain string, which
                # is an order of magnitude cheaper to lay out — a ten-thousand
                # line ledger is mostly lines that fit. A total, opening or
                # section row is a short label that TableStyle can set bold,
                # which a Paragraph would ignore.
                if (plain or col.kind in _NUMERIC
                        or ("\n" not in text and stringWidth(
                            text, pdf_style.FONT, _FONT_SIZE) <= room[i])):
                    out.append(text)
                else:
                    out.append(Paragraph(escape(text), cell))
            data.append(out)
            if row.style in (EMPHASIS, SECTION):
                extra.extend(pdf_style.emphasis_row(r))
                extra.append(("TEXTCOLOR", (0, r), (-1, r), pdf_style.C_INK))

        table = Table(data, colWidths=widths, repeatRows=1)
        table.setStyle(TableStyle(
            pdf_style.data_table_style(font_size=_FONT_SIZE, padding=_PADDING)
            + [("LINEBELOW", (0, 0), (-1, 0), 0.5, pdf_style.C_INK)]
            + extra))
        story.append(table)
        story.append(Spacer(1, 8))

    # ── What the reader needs to know before relying on it ───────────────────
    if doc.notes:
        story.append(Paragraph("Notes", styles["section"]))
        for note in doc.notes:
            story.append(Paragraph(escape(note), styles["note"]))
            story.append(Spacer(1, 2))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Generated on {escape(generated_on or ist_today().isoformat())} (IST). "
        "A report from the books as they stand; it is not a tax invoice or a "
        "statutory return.", styles["note"]))

    numbered(pdf, story)
    return buf.getvalue()
