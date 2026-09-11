#!/usr/bin/env python3
"""Render this repo's compliance and audit markdown to a readable PDF.

    python3 scripts/docs/md_to_pdf.py <input.md> <output.pdf>

Handles the subset of markdown these documents actually use: ATX headings,
paragraphs with bold/italic/code spans, pipe tables, bullet and numbered lists,
blockquotes, fenced code and horizontal rules. It is deliberately not a general
markdown engine — it is the one that renders OUR documents correctly, and a
missing feature should be added when a document needs it rather than in advance.

DejaVu, not Helvetica: the built-in fonts have no rupee glyph and reportlab maps
U+20B9 to the WinAnsi byte for "n" — the same trap invoice_pdf_service.py's
header comment describes. Every figure in this document is in rupees, so that
would have been a document full of "n1 crore".
"""
import html
import re
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

F = "/usr/share/fonts/truetype/dejavu/"
pdfmetrics.registerFont(TTFont("DJ", F + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DJ-B", F + "DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DJ-I", F + "DejaVuSerif.ttf"))
pdfmetrics.registerFont(TTFont("DJM", F + "DejaVuSansMono.ttf"))
pdfmetrics.registerFontFamily("DJ", normal="DJ", bold="DJ-B", italic="DJ-I")

INK = colors.HexColor("#0F172A")
MUTED = colors.HexColor("#475569")
RULE = colors.HexColor("#CBD5E1")
BAND = colors.HexColor("#F1F5F9")
ACCENT = colors.HexColor("#1D4ED8")

ss = getSampleStyleSheet()

def style(name, **kw):
    base = dict(fontName="DJ", fontSize=9, leading=13.2, textColor=INK,
                alignment=TA_LEFT, spaceAfter=5)
    base.update(kw)
    return ParagraphStyle(name, **base)

S = {
    "title":  style("t", fontName="DJ-B", fontSize=19, leading=24, spaceAfter=4),
    "sub":    style("s", fontSize=9.5, leading=14, textColor=MUTED, spaceAfter=14),
    "h1":     style("h1", fontName="DJ-B", fontSize=14.5, leading=19,
                    spaceBefore=17, spaceAfter=7, textColor=INK),
    "h2":     style("h2", fontName="DJ-B", fontSize=11.5, leading=15.5,
                    spaceBefore=13, spaceAfter=5, textColor=INK),
    "h3":     style("h3", fontName="DJ-B", fontSize=10, leading=14,
                    spaceBefore=10, spaceAfter=4, textColor=ACCENT),
    "body":   style("b"),
    "li":     style("li", leftIndent=11, bulletIndent=2, spaceAfter=3),
    "quote":  style("q", leftIndent=9, fontSize=8.8, leading=13,
                    textColor=colors.HexColor("#334155"), spaceAfter=5),
    "code":   style("c", fontName="DJM", fontSize=7.6, leading=10.4,
                    textColor=colors.HexColor("#1E293B")),
    "cell":   style("cell", fontSize=7.7, leading=10.4, spaceAfter=0),
    "cellh":  style("cellh", fontName="DJ-B", fontSize=7.7, leading=10.4, spaceAfter=0),
}


def inline(t: str) -> str:
    """Markdown inline -> reportlab mini-HTML. Escape FIRST, then add markup."""
    t = html.escape(t, quote=False)
    t = re.sub(r"`([^`]+)`",
               r'<font face="DJM" size="8" color="#B91C1C">\1</font>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<i>\1</i>", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<font color="#1D4ED8">\1</font>', t)
    return t


def split_row(line: str):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def build(md_path, pdf_path, title, subtitle):
    lines = open(md_path).read().split("\n")
    flow = [Paragraph(inline(title), S["title"]),
            Paragraph(inline(subtitle), S["sub"])]

    i = 0
    in_code = False
    code_buf = []
    while i < len(lines):
        ln = lines[i]

        if ln.strip().startswith("```"):
            if in_code:
                txt = "\n".join(code_buf) or " "
                t = Table([[Paragraph(html.escape(txt).replace("\n", "<br/>"), S["code"])]],
                          colWidths=[165 * mm])
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), BAND),
                    ("BOX", (0, 0), (-1, -1), 0.4, RULE),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
                flow += [t, Spacer(1, 6)]
                code_buf, in_code = [], False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(ln)
            i += 1
            continue

        st = ln.strip()

        if not st:
            i += 1
            continue

        if st in ("---", "***", "___"):
            flow.append(Spacer(1, 3))
            t = Table([[""]], colWidths=[165 * mm], rowHeights=[0.5])
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), RULE)]))
            flow += [t, Spacer(1, 8)]
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", st)
        if m:
            lvl, txt = len(m.group(1)), m.group(2)
            if lvl == 1:
                flow.append(PageBreak())
                flow.append(Paragraph(inline(txt), S["h1"]))
            else:
                flow.append(Paragraph(inline(txt), S[{2: "h1", 3: "h2"}.get(lvl, "h3")]))
            i += 1
            continue

        # table
        if st.startswith("|") and i + 1 < len(lines) and re.match(
                r"^\s*\|[\s:\-\|]+\|\s*$", lines[i + 1]):
            header = split_row(st)
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i].strip()))
                i += 1
            n = len(header)
            data = [[Paragraph(inline(c), S["cellh"]) for c in header]]
            for r in rows:
                r = (r + [""] * n)[:n]
                data.append([Paragraph(inline(c), S["cell"]) for c in r])
            avail = 165 * mm
            if n == 2:
                w = [avail * 0.30, avail * 0.70]
            elif n == 3:
                w = [avail * 0.20, avail * 0.44, avail * 0.36]
            else:
                w = [avail / n] * n
            t = Table(data, colWidths=w, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), BAND),
                ("GRID", (0, 0), (-1, -1), 0.35, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
            flow += [Spacer(1, 3), t, Spacer(1, 9)]
            continue

        if st.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            text = " ".join(x for x in buf if x).replace("  ", " ")
            parts = [p for p in "\n".join(buf).split("\n\n") if p.strip()]
            inner = [Paragraph(inline(" ".join(p.split())), S["quote"]) for p in parts] \
                or [Paragraph(inline(text), S["quote"])]
            t = Table([[inner]], colWidths=[165 * mm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ("LINEBEFORE", (0, 0), (0, -1), 2.2, ACCENT),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
            flow += [t, Spacer(1, 8)]
            continue

        m = re.match(r"^\s*([-*])\s+(.*)$", ln)
        if m:
            flow.append(Paragraph(inline(m.group(2)), S["li"], bulletText="•"))
            i += 1
            continue
        m = re.match(r"^\s*(\d+)\.\s+(.*)$", ln)
        if m:
            flow.append(Paragraph(inline(m.group(2)), S["li"],
                                  bulletText=m.group(1) + "."))
            i += 1
            continue

        # paragraph: join continuation lines
        buf = [st]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
                r"^\s*([-*#>|]|\d+\.|```)", lines[i]) and lines[i].strip() not in ("---",):
            buf.append(lines[i].strip())
            i += 1
        flow.append(Paragraph(inline(" ".join(buf)), S["body"]))

    doc = BaseDocTemplate(pdf_path, pagesize=A4,
                          leftMargin=22 * mm, rightMargin=23 * mm,
                          topMargin=18 * mm, bottomMargin=18 * mm,
                          title=title, author="PracticeSync")
    frame = Frame(doc.leftMargin, doc.bottomMargin, 165 * mm,
                  A4[1] - doc.topMargin - doc.bottomMargin, id="f")

    def furniture(canvas, d):
        canvas.saveState()
        canvas.setFont("DJ", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(doc.leftMargin, 11 * mm,
                          "PracticeSync — Government API access, 11 September 2026")
        canvas.drawRightString(A4[0] - doc.rightMargin, 11 * mm, str(d.page))
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.4)
        canvas.line(doc.leftMargin, 14 * mm, A4[0] - doc.rightMargin, 14 * mm)
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=furniture)])
    doc.build(flow)
    print("wrote", pdf_path)


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2],
          "Government API access — the verified position",
          "PracticeSync · 11 September 2026 · what to apply for, what it unblocks, "
          "where a human is legally unavoidable, and the six emails that close the gaps")
