#!/usr/bin/env python3
"""Render this repo's compliance and audit markdown to a readable PDF.

    python3 scripts/docs/md_to_pdf.py <input.md> <output.pdf>

Handles the subset of markdown these documents actually use: ATX headings,
paragraphs with bold/italic/code spans, pipe tables, bullet and numbered lists,
blockquotes, fenced code and horizontal rules. It is deliberately not a general
markdown engine — it is the one that renders OUR documents correctly, and a
missing feature should be added when a document needs it rather than in advance.

BEYOND PLAIN MARKDOWN, because a thirty-page document nobody can skim is a
document nobody reads:

  * YAML-ish front matter between leading `---` fences becomes a COVER PAGE.
    `title`, `subtitle`, `meta` (one `|`-separated line per entry) and
    `classification` are recognised; anything else is ignored.
  * Fenced CALLOUTS, `:::key Heading` ... `:::`, in five weights — key, verdict,
    warn, stop, note. Each is a tinted panel with a coloured left rule, used for
    the handful of facts a reader must not miss.
  * `==text==` HIGHLIGHTS inline, for a threshold or a figure inside a sentence.
  * EVIDENCE CHIPS. `[P]`, `[S-gov]`, `[S]`, `[O]` and `[U]` are this document
    set's confidence grades, and they carry the whole argument about how much
    weight a line can take. Rendered as tinted chips they survive skimming; as
    bare brackets in body text they do not.
  * Page "N of M", which needs the total before any page is drawn, so the
    canvas buffers pages and stamps them on save.

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
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (BaseDocTemplate, Frame, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

F = "/usr/share/fonts/truetype/dejavu/"
pdfmetrics.registerFont(TTFont("DJ", F + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DJ-B", F + "DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DJM", F + "DejaVuSansMono.ttf"))

# ITALIC MAPS TO THE REGULAR FACE, DELIBERATELY. This DejaVu install ships no
# DejaVuSans-Oblique, so an <i> run fell back to DejaVuSerif — a serif word in
# the middle of a sans sentence, which reads as a font bug rather than as
# emphasis. In these documents italic is almost always a quotation from a
# portal or a vendor, and the quotation marks already carry that. Emphasis is
# carried by bold and by ==highlight==.
pdfmetrics.registerFontFamily("DJ", normal="DJ", bold="DJ-B",
                              italic="DJ", boldItalic="DJ-B")

INK = colors.HexColor("#0F172A")
MUTED = colors.HexColor("#475569")
RULE = colors.HexColor("#CBD5E1")
BAND = colors.HexColor("#F1F5F9")
ZEBRA = colors.HexColor("#F8FAFC")
ACCENT = colors.HexColor("#1D4ED8")
WIDTH = 165 * mm

#: Callout weights: (background, left rule, heading colour).
CALLOUT = {
    "key":     ("#EFF6FF", "#1D4ED8", "#1E40AF"),
    "verdict": ("#F0FDF4", "#15803D", "#166534"),
    "warn":    ("#FFFBEB", "#D97706", "#B45309"),
    "stop":    ("#FEF2F2", "#B91C1C", "#991B1B"),
    "note":    ("#F8FAFC", "#64748B", "#334155"),
}

#: Confidence grades, rendered as chips. See §0 of the document for what each means.
CHIP = {
    "P":     ("#DCFCE7", "#14532D"),
    "S-gov": ("#DBEAFE", "#1E3A8A"),
    "S":     ("#E2E8F0", "#334155"),
    "O":     ("#FAE8FF", "#701A75"),
    "U":     ("#FEE2E2", "#7F1D1D"),
}

ss = getSampleStyleSheet()


def style(name, **kw):
    base = dict(fontName="DJ", fontSize=9, leading=13.2, textColor=INK,
                alignment=TA_LEFT, spaceAfter=5)
    base.update(kw)
    return ParagraphStyle(name, **base)


S = {
    "covertitle": style("ct", fontName="DJ-B", fontSize=27, leading=33, spaceAfter=10),
    "coversub":   style("cs", fontSize=12, leading=18, textColor=MUTED, spaceAfter=22),
    "covermeta":  style("cm", fontSize=8.6, leading=15, textColor=MUTED, spaceAfter=0),
    "coverclass": style("cc", fontName="DJ-B", fontSize=8, leading=12,
                        textColor=colors.HexColor("#B45309"), spaceAfter=0),
    "h1":     style("h1", fontName="DJ-B", fontSize=15.5, leading=20,
                    spaceBefore=2, spaceAfter=8, textColor=INK, keepWithNext=1),
    "h2":     style("h2", fontName="DJ-B", fontSize=11.8, leading=16,
                    spaceBefore=14, spaceAfter=5, textColor=INK, keepWithNext=1),
    "h3":     style("h3", fontName="DJ-B", fontSize=10, leading=14,
                    spaceBefore=11, spaceAfter=4, textColor=ACCENT, keepWithNext=1),
    "body":   style("b"),
    "li":     style("li", leftIndent=11, bulletIndent=2, spaceAfter=3),
    "quote":  style("q", leftIndent=9, fontSize=8.8, leading=13,
                    textColor=colors.HexColor("#334155"), spaceAfter=5),
    "code":   style("c", fontName="DJM", fontSize=7.6, leading=10.4,
                    textColor=colors.HexColor("#1E293B")),
    "cell":   style("cell", fontSize=7.7, leading=10.4, spaceAfter=0),
    "cellh":  style("cellh", fontName="DJ-B", fontSize=7.7, leading=10.4,
                    spaceAfter=0, textColor=colors.white),
    "callout":  style("co", fontSize=8.9, leading=13, spaceAfter=4),
    "calloutH": style("coh", fontName="DJ-B", fontSize=8.4, leading=12, spaceAfter=4),
}


def _chip(grade: str) -> str:
    bg, fg = CHIP[grade]
    return (f'<font face="DJ-B" size="6.6" color="{fg}" backColor="{bg}">'
            f'&nbsp;{html.escape(grade)}&nbsp;</font>')


def inline(t: str) -> str:
    """Markdown inline -> reportlab mini-HTML. Escape FIRST, then add markup."""
    t = html.escape(t, quote=False)
    # HIGHLIGHT BEFORE CODE SPANS, and the order is load-bearing. The code
    # replacement emits attributes — size="8" — so a `backtick span` inside a
    # ==highlight== put an "=" in the middle of it and the [^=]+ body stopped
    # matching. The highlight then rendered as literal "==" in the text.
    t = re.sub(r"==(.+?)==", r'<font backColor="#FEF08A">\1</font>', t, flags=re.S)
    t = re.sub(r"`([^`]+)`",
               r'<font face="DJM" size="8" color="#B91C1C">\1</font>', t)
    # Chips before bold, so a grade inside **…** still becomes a chip.
    t = re.sub(r"\[(P|S-gov|S|O|U)\]", lambda m: _chip(m.group(1)), t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<i>\1</i>", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<font color="#1D4ED8">\1</font>', t)
    return t


def split_row(line: str):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def panel(inner, bg, rule, pad=9):
    t = Table([[inner]], colWidths=[WIDTH])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
        ("LINEBEFORE", (0, 0), (0, -1), 2.6, colors.HexColor(rule)),
        ("LEFTPADDING", (0, 0), (-1, -1), pad + 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), pad),
        ("TOPPADDING", (0, 0), (-1, -1), pad - 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), pad - 1)]))
    return t


def front_matter(lines):
    """Leading `---` fenced key: value block -> dict, plus the remaining lines."""
    if not lines or lines[0].strip() != "---":
        return {}, lines
    out, i = {}, 1
    while i < len(lines) and lines[i].strip() != "---":
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", lines[i])
        if m:
            out.setdefault(m.group(1), []).append(m.group(2).strip())
        i += 1
    return out, lines[i + 1:]


def cover(fm):
    if not fm:
        return []
    flow = [Spacer(1, 52 * mm)]
    for c in fm.get("classification", []):
        flow += [Paragraph(inline(c.upper()), S["coverclass"]), Spacer(1, 7)]
    for t in fm.get("title", []):
        flow.append(Paragraph(inline(t), S["covertitle"]))
    for s in fm.get("subtitle", []):
        flow.append(Paragraph(inline(s), S["coversub"]))
    rows = [m for entry in fm.get("meta", []) for m in [entry.split("|")]]
    if rows:
        t = Table([[Paragraph(inline(c.strip()), S["covermeta"]) for c in r]
                   for r in rows], colWidths=[40 * mm, WIDTH - 40 * mm])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LINEABOVE", (0, 0), (-1, 0), 0.8, RULE),
            ("TEXTCOLOR", (0, 0), (0, -1), INK),
            ("FONTNAME", (0, 0), (0, -1), "DJ-B")]))
        flow += [Spacer(1, 4), t]
    return flow + [PageBreak()]


def build(md_path, pdf_path, title, subtitle):
    raw = open(md_path).read().split("\n")
    fm, lines = front_matter(raw)
    if fm:
        title = (fm.get("title") or [title])[0]
        subtitle = (fm.get("subtitle") or [subtitle])[0]
        flow = cover(fm)
    else:
        flow = [Paragraph(inline(title), S["h1"]),
                Paragraph(inline(subtitle), S["quote"])]

    i = 0
    in_code = False
    code_buf = []
    while i < len(lines):
        ln = lines[i]

        if ln.strip().startswith("```"):
            if in_code:
                txt = "\n".join(code_buf) or " "
                flow += [panel(Paragraph(html.escape(txt).replace("\n", "<br/>"),
                                         S["code"]), "#F1F5F9", "#94A3B8", 7),
                         Spacer(1, 7)]
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

        # callout:  :::key Optional heading  ...  :::
        m = re.match(r"^:::(\w+)\s*(.*)$", st)
        if m:
            kind, heading = m.group(1).lower(), m.group(2).strip()
            bg, rule, hcol = CALLOUT.get(kind, CALLOUT["note"])
            i += 1
            buf = []
            while i < len(lines) and lines[i].strip() != ":::":
                buf.append(lines[i])
                i += 1
            i += 1
            inner = []
            if heading:
                hs = ParagraphStyle("coh_" + kind, parent=S["calloutH"],
                                    textColor=colors.HexColor(hcol))
                inner.append(Paragraph(inline(heading.upper()), hs))
            for para in re.split(r"\n\s*\n", "\n".join(buf)):
                para = para.strip()
                if not para:
                    continue
                # No `$` in this test: it anchors to end-of-string, so a block
                # of several bullets would fail it and collapse into one run-on
                # paragraph — which is exactly what it did.
                if re.match(r"^\s*(?:[-*]\s|\d+\.\s)", para):
                    # Rejoin wrapped items first: an indented unmarked line
                    # continues the item above it, and splitting it would also
                    # split any ==highlight== that spans the wrap.
                    items = []
                    for b in para.split("\n"):
                        if re.match(r"^\s*(?:[-*]\s|\d+\.\s)", b) or not items:
                            items.append(b.strip())
                        else:
                            items[-1] += " " + b.strip()
                    for b in items:
                        nm = re.match(r"^(\d+)\.\s+(.*)$", b)
                        if nm:
                            inner.append(Paragraph(inline(nm.group(2)), S["li"],
                                                   bulletText=nm.group(1) + "."))
                        else:
                            inner.append(Paragraph(
                                inline(re.sub(r"^[-*]\s+", "", b)), S["li"],
                                bulletText="•"))
                else:
                    inner.append(Paragraph(inline(" ".join(para.split())), S["callout"]))
            flow += [panel(inner, bg, rule), Spacer(1, 9)]
            continue

        if not st:
            i += 1
            continue

        if st in ("---", "***", "___"):
            flow.append(Spacer(1, 3))
            t = Table([[""]], colWidths=[WIDTH], rowHeights=[0.5])
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
            if n == 2:
                w = [WIDTH * 0.30, WIDTH * 0.70]
            elif n == 3:
                w = [WIDTH * 0.20, WIDTH * 0.44, WIDTH * 0.36]
            elif n >= 5:
                # A wide table is almost always "label + several narrow marks".
                w = [WIDTH * 0.22] + [WIDTH * 0.78 / (n - 1)] * (n - 1)
            else:
                w = [WIDTH / n] * n
            t = Table(data, colWidths=w, repeatRows=1)
            sty = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
                   ("GRID", (0, 0), (-1, -1), 0.35, RULE),
                   ("VALIGN", (0, 0), (-1, -1), "TOP"),
                   ("LEFTPADDING", (0, 0), (-1, -1), 5),
                   ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                   ("TOPPADDING", (0, 0), (-1, -1), 4.5),
                   ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5)]
            for r in range(2, len(data), 2):
                sty.append(("BACKGROUND", (0, r), (-1, r), ZEBRA))
            t.setStyle(TableStyle(sty))
            flow += [Spacer(1, 3), t, Spacer(1, 10)]
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
            flow += [panel(inner, "#F8FAFC", "#1D4ED8"), Spacer(1, 8)]
            continue

        m = re.match(r"^\s*([-*])\s+(.*)$", ln)
        n = re.match(r"^\s*(\d+)\.\s+(.*)$", ln)
        if m or n:
            text = (m or n).group(2)
            bullet = "•" if m else n.group(1) + "."
            i += 1
            # Absorb the wrap. An indented, unmarked, non-blank line continues
            # this item; anything else starts a new block.
            while (i < len(lines) and lines[i].strip()
                   and re.match(r"^\s+\S", lines[i])
                   and not re.match(r"^\s*(?:[-*]\s|\d+\.\s|#|>|\||:::|```)",
                                    lines[i])):
                text += " " + lines[i].strip()
                i += 1
            flow.append(Paragraph(inline(text), S["li"], bulletText=bullet))
            continue

        # paragraph: join continuation lines
        buf = [st]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
                r"^\s*(?:[-*]\s|#|>|\||:::|\d+\.\s|```)", lines[i]) \
                and lines[i].strip() not in ("---",):
            buf.append(lines[i].strip())
            i += 1
        flow.append(Paragraph(inline(" ".join(buf)), S["body"]))

    footer = (fm.get("footer") or ["PracticeSync"])[0]

    class Numbered(pdfcanvas.Canvas):
        """Page 'N of M' needs the total before page 1 is drawn, so buffer."""

        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for n, state in enumerate(self._pages, start=1):
                self.__dict__.update(state)
                if n > 1:                       # the cover carries no furniture
                    self._stamp(n, total)
                super().showPage()
            super().save()

        def _stamp(self, n, total):
            self.saveState()
            self.setFont("DJ", 7)
            self.setFillColor(MUTED)
            self.drawString(22 * mm, 11 * mm, footer)
            self.drawRightString(A4[0] - 23 * mm, 11 * mm, f"Page {n} of {total}")
            self.setStrokeColor(RULE)
            self.setLineWidth(0.4)
            self.line(22 * mm, 14 * mm, A4[0] - 23 * mm, 14 * mm)
            self.restoreState()

    doc = BaseDocTemplate(pdf_path, pagesize=A4,
                          leftMargin=22 * mm, rightMargin=23 * mm,
                          topMargin=18 * mm, bottomMargin=18 * mm,
                          title=title, author="PracticeSync")
    frame = Frame(doc.leftMargin, doc.bottomMargin, WIDTH,
                  A4[1] - doc.topMargin - doc.bottomMargin, id="f")
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame])])
    doc.build(flow, canvasmaker=Numbered)
    print("wrote", pdf_path)


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2],
          "Government API access — the verified position",
          "PracticeSync · 11 September 2026")
