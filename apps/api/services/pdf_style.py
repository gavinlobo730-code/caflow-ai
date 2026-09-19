"""One palette and one set of table styles for every PDF this product renders.

WHAT WAS WRONG

    Six reportlab services rendered the documents a practice hands out, and
    each had picked its own colours. FOUR different header fills:

        #0F172A   bank reconciliation, customer statement
        #1f2937   sales invoice, payslip
        #1a3c5e   the year-end pack — navy, and it is the set a CA SIGNS
        #1a1a1a   the engagement letter

    and three different body greys (#64748B, #737373, #666666), 31 hardcoded
    hex values, 16 TableStyle blocks and 24 ParagraphStyle blocks across ~3,200
    lines with nothing shared. A CA who prints an invoice, a payslip, a
    year-end pack and an engagement letter in one morning gets four documents
    that look like they came from four different products — and the one with
    the most authority, the signed pack, was the furthest off.

    None of the six used the product's OWN palette, which is in
    `apps/web/tailwind.config.ts` and is the only one in this repository that
    has been reasoned about: its `ps.*` ink scale carries a recorded contrast
    audit (`hint` was moved off #94A3B8 at 2.56:1 on white) and its `state.*`
    scale is deliberately not the accent.

THE PALETTE IS THE PRODUCT'S, AND IT IS PINNED FROM PYTHON

    `_TOKEN_SOURCE` below names every value's token, and
    `tests/test_one_pdf_style_and_every_document_shares_it.py` asserts each
    against `tailwind.config.ts` itself. The guard lives on the PYTHON side
    deliberately: one written in `apps/web` would assert the browser against a
    copy of itself and pass whenever both drifted together — the Schedule III
    caption lesson, which this repository has already paid for twice.

    Mapping is by ROLE, never by nearest hex. A "this reconciles" fill is a
    READY SURFACE, so it becomes `state.ready-surface`; it is not matched to
    whichever token happens to sit closest to #DCFCE7.

WHAT THIS MODULE DELIBERATELY DOES NOT DO

    IT CHANGES NO FONT SIZE AND NO COLUMN WIDTH. `_DETAIL_WIDTHS` and the
    three sizing constants in the invoice service were measured against real
    worst-case content (T5a-4b: seven columns were too narrow, and the room
    came out of the padding), and a shared module that quietly renormalised
    them would re-break exactly what that measurement fixed. Every builder
    here takes its size and padding from the caller, with each caller passing
    the value it already had.

    IT SETS NO FONT FAMILY BEYOND Helvetica. Embedding a face that carries
    U+20B9 is a licence decision the owner has not taken (T5a-5), and this
    module must not pre-empt it by reaching for a font.

    NOTHING HERE READS THE DATABASE, renders, or knows what a document means.
    It is a style sheet.
"""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet


# ── The palette ───────────────────────────────────────────────────────────────
#
# Each value's token is recorded in `_TOKEN_SOURCE` and asserted against
# apps/web/tailwind.config.ts. Add a colour here only with its token; a value
# with no token is a colour nobody reasoned about, which is what this replaced.

INK             = "#0D1635"   # headings, figures, anything load-bearing
BODY            = "#334155"   # body copy
LABEL           = "#475569"   # labels, secondary copy
HINT            = "#64748B"   # hints, captions, the quietest readable text
DISABLED        = "#CBD5E1"

PAGE_BG         = "#F8FAFC"   # also the zebra stripe — see `data_table_style`
SURFACE         = "#FFFFFF"
MUTED           = "#F1F5F9"   # a table's header band, a subtotal row
BORDER          = "#E2E8F0"
BORDER_STRONG   = "#CBD5E1"

READY           = "#047857"
READY_SURFACE   = "#ECFDF5"
ATTENTION       = "#B45309"
ATTENTION_SURFACE = "#FFFBEB"
PROBLEM         = "#B91C1C"
PROBLEM_SURFACE = "#FEF2F2"

#: Which `tailwind.config.ts` token each value above is. The guard reads this.
_TOKEN_SOURCE = {
    "INK": "ps.ink",
    "BODY": "ps.body",
    "LABEL": "ps.label",
    "HINT": "ps.hint",
    "DISABLED": "ps.disabled",
    "PAGE_BG": "ps.bg",
    "SURFACE": "ps.surface",
    "MUTED": "ps.muted",
    "BORDER": "ps.border",
    "BORDER_STRONG": "ps.border-strong",
    "READY": "state.ready",
    "READY_SURFACE": "state.ready-surface",
    "ATTENTION": "state.attention",
    "ATTENTION_SURFACE": "state.attention-surface",
    "PROBLEM": "state.problem",
    "PROBLEM_SURFACE": "state.problem-surface",
}


def c(hex_value: str) -> colors.Color:
    """A reportlab colour from one of the constants above."""
    return colors.HexColor(hex_value)


# Pre-built, because a TableStyle command list is written far more often than
# it is read and `c(INK)` at every site is noise.
C_INK, C_BODY, C_LABEL, C_HINT = c(INK), c(BODY), c(LABEL), c(HINT)
C_PAGE_BG, C_SURFACE, C_MUTED = c(PAGE_BG), c(SURFACE), c(MUTED)
C_BORDER, C_BORDER_STRONG = c(BORDER), c(BORDER_STRONG)
C_READY, C_READY_SURFACE = c(READY), c(READY_SURFACE)
C_ATTENTION, C_ATTENTION_SURFACE = c(ATTENTION), c(ATTENTION_SURFACE)
C_PROBLEM, C_PROBLEM_SURFACE = c(PROBLEM), c(PROBLEM_SURFACE)
C_WHITE = colors.white


# ── Type ──────────────────────────────────────────────────────────────────────
#
# Helvetica only, and see the module docstring: which face carries the rupee
# sign is an unresolved licence decision, so nothing here embeds one.

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_ITALIC = "Helvetica-Oblique"


def paragraph_styles() -> dict[str, ParagraphStyle]:
    """The styles every document shares, by ROLE.

    A caller that needs a size this does not offer builds its own from
    `getSampleStyleSheet()` as before — the point of this function is that the
    COLOURS agree, not that every document is laid out identically. A statement
    and an engagement letter are different documents.
    """
    base = getSampleStyleSheet()
    normal, title = base["Normal"], base["Title"]
    return {
        # A document's own name: "Tax Invoice", "Payslip", "Statement of Account".
        "doc_title": ParagraphStyle(
            "ps_doc_title", parent=title, fontSize=16, spaceAfter=2,
            textColor=C_INK),
        # The line under it — a period, an address, a registration number.
        "doc_subtitle": ParagraphStyle(
            "ps_doc_subtitle", parent=normal, fontSize=9, textColor=C_HINT),
        "section": ParagraphStyle(
            "ps_section", parent=normal, fontSize=11, fontName=FONT_BOLD,
            spaceBefore=8, spaceAfter=4, textColor=C_INK),
        "body": ParagraphStyle(
            "ps_body", parent=normal, fontSize=9, textColor=C_BODY),
        "small": ParagraphStyle(
            "ps_small", parent=normal, fontSize=8, textColor=C_LABEL),
        # A caveat, a gap, a "this is not a filing" notice.
        "note": ParagraphStyle(
            "ps_note", parent=normal, fontSize=8, textColor=C_HINT),
    }


# ── Tables ────────────────────────────────────────────────────────────────────

def data_table_style(
    *,
    font_size: float,
    padding: float,
    grid: float = 0.25,
    zebra: bool = True,
    first_body_row: int = 1,
    last_body_row: int = -1,
    right_align_from: int | None = None,
) -> list[tuple]:
    """The command list for a table of records: dark header, zebra, hairline grid.

    `font_size` and `padding` are REQUIRED and have no default. Every caller
    passes what it already used, so converting a service moves its colours and
    nothing else — see the module docstring on why sizes must not be
    renormalised here.

    THE ZEBRA STRIPE IS `ps.bg`, the application background, which is the
    product's own quiet alternate fill. Four services had reached for #FAFAFA,
    a neutral grey that is not in the palette and reads slightly warm beside
    the navy-cast ink.

    `first_body_row` / `last_body_row` exist because the customer statement
    puts an opening-balance row directly under the header and a closing-balance
    row at the foot, and neither should be striped.
    """
    cmds: list[tuple] = [
        ("BACKGROUND", (0, 0), (-1, 0), C_INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), C_WHITE),
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("TOPPADDING", (0, 0), (-1, -1), padding),
        ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
    ]
    if right_align_from is not None:
        cmds.append(("ALIGN", (right_align_from, 0), (-1, -1), "RIGHT"))
    if zebra:
        cmds.append(("ROWBACKGROUNDS", (0, first_body_row), (-1, last_body_row),
                     [C_SURFACE, C_PAGE_BG]))
    if grid:
        cmds.append(("GRID", (0, 0), (-1, -1), grid, C_BORDER))
    return cmds


def emphasis_row(row: int) -> list[tuple]:
    """A total, a subtotal or an opening balance: the muted band, set bold."""
    return [
        ("BACKGROUND", (0, row), (-1, row), C_MUTED),
        ("FONTNAME", (0, row), (-1, row), FONT_BOLD),
    ]


def verdict_fill(row: int, ok: bool) -> tuple:
    """The fill for a row that states an outcome — reconciles, or does not.

    Mapped by ROLE to `state.ready-surface` / `state.problem-surface` rather
    than to whichever token sits nearest the #DCFCE7 and #FEE2E2 that were
    there: `state.ready-hover` happens to be #DCFCE7 and means a ready ROW
    UNDER THE CURSOR, which a printed page does not have.
    """
    return ("BACKGROUND", (0, row), (-1, row),
            C_READY_SURFACE if ok else C_PROBLEM_SURFACE)


def subtotal_rule(row: int, weight: float = 0.5) -> tuple:
    """The "add these up" line above a subtotal or a tie-out figure.

    `ps.hint` rather than either border token, and DARKER than what it
    replaced. The bank reconciliation drew this in #94A3B8 — which is the
    value `tailwind.config.ts` records moving the hint step OFF, at 2.56:1 on
    white, below even WCAG 1.4.11's 3:1 for a non-text component. A grid
    hairline may be quiet because the cells around it do the work; the rule
    under a reconciliation's tie-out is the one mark saying which figures are
    being added, and on a laser printer it has to survive.
    """
    return ("LINEABOVE", (0, row), (-1, row), weight, C_HINT)
