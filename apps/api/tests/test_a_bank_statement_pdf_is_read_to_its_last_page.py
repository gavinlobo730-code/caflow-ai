"""
BANK-14 — a PDF statement is read to its LAST page, not to its first ruled one.

`domain/banking/normalizer._pdf_rows` has two strategies: pdfplumber's
`extract_tables`, which reads a table drawn with ruling lines, and a geometric
fallback that places every word in the column its midpoint falls in. The choice
between them used to be made ONCE for the whole document — `if rows: return
rows` sat outside the page loop — so a statement whose first page carries the
ruling and whose continuation pages do not imported page one and dropped the
rest.

It is silent, which is what makes it worth a test file of its own. The backstop
is `domain/banking/tie_out.py`, and it can only catch a short read on a
statement that PRINTS its totals — which it does on the last page, one of the
pages that vanished.

The second half is the part that is not a one-liner. `_rows_by_position` needs
a header line to place its columns, and a continuation page does not repeat
one, so deciding per page would on its own have returned nothing for exactly
the pages it was added to rescue. The columns are carried forward from the page
that printed the header.

WHY REAL PDFs. Everything here is built with reportlab and read back through
pdfplumber, the two libraries the product actually uses. A fake page object
would let the test agree with a wrong reading of what `extract_tables` returns,
which is the reading this bug was made of.
"""
import io

import pytest

from domain.banking.normalizer import (
    _columns_from,
    _geometric_rows,
    _merge_pages,
    _page_lines,
    _pdf_rows,
    parse_pdf,
)

reportlab = pytest.importorskip("reportlab")
pdfplumber = pytest.importorskip("pdfplumber")

from reportlab.lib.pagesizes import A4          # noqa: E402
from reportlab.pdfgen import canvas             # noqa: E402


# ── Drawing a statement ───────────────────────────────────────────────────────
# Cosmos-style six-column cheque layout: Date, Particulars, Cheque No,
# Withdrawal, Deposit, Balance — `normalizer._ADAPTERS["generic_cheque"]`.
# Amount columns are RIGHT-aligned, label and value alike, exactly as a bank
# prints them: it is what keeps a value under its own heading.
_COLUMNS = (
    ("Date",        40.0,  "left"),
    ("Particulars", 96.0,  "left"),
    ("Cheque No",   256.0, "left"),
    ("Withdrawal",  390.0, "right"),
    ("Deposit",     470.0, "right"),
    ("Balance",     556.0, "right"),
)
_GRID_X = (38.0, 92.0, 252.0, 312.0, 392.0, 472.0, 558.0)
_TOP = 780.0
_LEADING = 16.0


def _draw_row(c, cells, y):
    for (_label, x, align), text in zip(_COLUMNS, cells):
        if not text:
            continue
        if align == "right":
            c.drawRightString(x, y, text)
        else:
            c.drawString(x, y, text)


def _draw_page(c, rows, *, header: bool, ruled: bool, prose: str = ""):
    c.setFont("Helvetica", 8)
    if prose:
        c.drawString(40.0, _TOP, prose)
        return
    y = _TOP
    drawn = 0
    if header:
        _draw_row(c, [label for label, _x, _a in _COLUMNS], y)
        y -= _LEADING
        drawn += 1
    for row in rows:
        _draw_row(c, row, y)
        y -= _LEADING
        drawn += 1
    if ruled:
        # A grid pdfplumber's line strategy can see: one vertical per column
        # boundary, one horizontal per row boundary.
        top, bottom = _TOP + 10.0, _TOP - _LEADING * drawn + 6.0
        for x in _GRID_X:
            c.line(x, top, x, bottom)
        for i in range(drawn + 1):
            yy = top - i * _LEADING
            c.line(_GRID_X[0], yy, _GRID_X[-1], yy)


def _statement(pages) -> bytes:
    """pages: list of dicts with rows / header / ruled / prose."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for page in pages:
        _draw_page(c, page.get("rows", []),
                   header=page.get("header", False),
                   ruled=page.get("ruled", False),
                   prose=page.get("prose", ""))
        c.showPage()
    c.save()
    return buf.getvalue()


def _txn(date, narration, ref, withdrawal, deposit, balance):
    return (date, narration, ref, withdrawal, deposit, balance)


PAGE_ONE = [
    _txn("01/04/2025", "OPENING", "", "", "", "1,00,000.00"),
    _txn("02/04/2025", "NEFT ACME", "N001", "", "25,000.00", "1,25,000.00"),
]
PAGE_TWO = [
    _txn("03/04/2025", "RENT PAID", "C002", "40,000.00", "", "85,000.00"),
    _txn("04/04/2025", "UPI ZEN", "U003", "", "15,000.00", "1,00,000.00"),
]


def _dates(txns):
    return [t.transaction_date for t in txns]


# ── The finding ───────────────────────────────────────────────────────────────

def test_a_ruled_first_page_does_not_swallow_the_rest_of_the_statement():
    """The bug, in its own shape: page 1 carries the ruling, page 2 does not
    and does not repeat the header. Before the fix this returned page 1."""
    pdf = _statement([
        {"rows": PAGE_ONE, "header": True, "ruled": True},
        {"rows": PAGE_TWO, "header": False, "ruled": False},
    ])
    txns = parse_pdf(pdf)
    assert _dates(txns) == ["2025-04-01", "2025-04-02", "2025-04-03", "2025-04-04"]


def test_the_last_page_is_the_one_carrying_the_closing_balance():
    """Why it is silent. The statement's own totals sit on the last page, so a
    read that stops early loses the evidence that it stopped early."""
    pdf = _statement([
        {"rows": PAGE_ONE, "header": True, "ruled": True},
        {"rows": PAGE_TWO, "header": False, "ruled": False},
    ])
    txns = parse_pdf(pdf)
    assert txns[-1].balance_paise == 1_00_000_00


def test_a_continuation_page_that_does_not_repeat_the_header_is_still_read():
    """Neither page is ruled, so both go through geometry — and page 2 has no
    header of its own to derive columns from."""
    pdf = _statement([
        {"rows": PAGE_ONE, "header": True, "ruled": False},
        {"rows": PAGE_TWO, "header": False, "ruled": False},
    ])
    txns = parse_pdf(pdf)
    assert _dates(txns) == ["2025-04-01", "2025-04-02", "2025-04-03", "2025-04-04"]


def test_the_carried_columns_are_the_header_pages_own():
    """The unit underneath: `_geometric_rows` hands page 2 the geometry page 1
    established, rather than answering "no header, no rows"."""
    pdf = _statement([
        {"rows": PAGE_ONE, "header": True, "ruled": False},
        {"rows": PAGE_TWO, "header": False, "ruled": False},
    ])
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        pages = list(doc.pages)
        assert _columns_from(_page_lines(pages[1])) is None    # page 2 has no header
        per_page = _geometric_rows(pages)
    assert len(per_page) == 2
    assert per_page[1], "the continuation page produced no rows"
    assert per_page[1][0][0] == "03/04/2025"


def test_the_pages_come_back_in_document_order():
    """`_opening_closing_balance` takes the opening off the earliest row and
    `tie_out.balance_agreement` walks the running balance down the file, so a
    merge that reordered pages would fail arithmetic that is correct."""
    pdf = _statement([
        {"rows": PAGE_ONE, "header": True, "ruled": True},
        {"rows": PAGE_TWO, "header": False, "ruled": False},
    ])
    balances = [t.balance_paise for t in parse_pdf(pdf)]
    assert balances == [1_00_000_00, 1_25_000_00, 85_000_00, 1_00_000_00]


# ── What must not change ──────────────────────────────────────────────────────

def test_a_fully_ruled_statement_still_reads_through_the_ruled_path():
    pdf = _statement([
        {"rows": PAGE_ONE, "header": True, "ruled": True},
        {"rows": PAGE_TWO, "header": True, "ruled": True},
    ])
    txns = parse_pdf(pdf)
    assert _dates(txns) == ["2025-04-01", "2025-04-02", "2025-04-03", "2025-04-04"]


def test_a_trailing_page_of_terms_does_not_make_the_document_geometric():
    """A page the ruled pass misses is not necessarily a page it FAILED on.
    Most statements end with a computer-generated-statement notice, and the
    ruled read of the pages before it is complete."""
    pdf = _statement([
        {"rows": PAGE_ONE + PAGE_TWO, "header": True, "ruled": True},
        {"prose": "This is a computer generated statement and needs no signature."},
    ])
    txns = parse_pdf(pdf)
    assert _dates(txns) == ["2025-04-01", "2025-04-02", "2025-04-03", "2025-04-04"]


def test_a_single_unruled_page_still_reads():
    pdf = _statement([{"rows": PAGE_ONE + PAGE_TWO, "header": True, "ruled": False}])
    assert len(parse_pdf(pdf)) == 4


def test_a_pdf_with_no_text_layer_is_still_refused_rather_than_read_as_empty():
    pdf = _statement([{"prose": ""}])
    assert _pdf_rows(pdf) == []


# ── The one decision that is not per page ─────────────────────────────────────
# `_merge_pages` is a pure function over the two per-page reads, so the
# disagreement case can be stated directly rather than hoping a drawn PDF
# reproduces it. It is the case a real statement will eventually hit: a bank
# that omits one vertical rule merges two columns for `extract_tables` and not
# for the geometry, and the two reads then describe different tables.

_SIX = ["Date", "Particulars", "Cheque No", "Withdrawal", "Deposit", "Balance"]
_FIVE = ["Date", "Particulars", "Cheque No", "Withdrawal Deposit", "Balance"]


def test_a_page_the_ruled_pass_missed_comes_from_geometry():
    merged = _merge_pages(
        ruled=[[_SIX, ["01/04/2025", "A", "", "", "1.00", "1.00"]], []],
        geometric=[[_SIX, ["01/04/2025", "A", "", "", "1.00", "1.00"]],
                   [["02/04/2025", "B", "", "2.00", "", "0.00"]]],
    )
    assert merged[-1][0] == "02/04/2025"
    assert len(merged) == 3


def test_pages_keep_their_document_order_through_the_merge():
    merged = _merge_pages(
        ruled=[[["p1r1"], ["p1r2"]], []],
        geometric=[[], [["p2r1"], ["p2r2"]]],
    )
    assert merged == [["p1r1"], ["p1r2"], ["p2r1"], ["p2r2"]]


def test_two_reads_that_disagree_about_the_columns_are_not_interleaved():
    """Five ruled columns and six geometric ones cannot be read against one
    header row. The document goes through geometry rather than half and half."""
    merged = _merge_pages(
        ruled=[[_FIVE, ["01/04/2025", "A", "", "1.00", "1.00"]], []],
        geometric=[[_SIX, ["01/04/2025", "A", "", "", "1.00", "1.00"]],
                   [["02/04/2025", "B", "", "2.00", "", "0.00"]]],
    )
    assert all(len(row) == 6 for row in merged), merged
    assert merged[0] == _SIX


def test_a_page_geometry_cannot_place_keeps_its_ruled_rows():
    """Preferring geometry does not mean dropping a page geometry could not
    read — a page before the first header has no columns to be placed in."""
    merged = _merge_pages(
        ruled=[[_FIVE, ["01/04/2025", "A", "", "1.00", "1.00"]],
               [["02/04/2025", "B", "", "2.00", "0.00"]]],
        geometric=[[_SIX, ["01/04/2025", "A", "", "", "1.00", "1.00"]], []],
    )
    assert merged[-1] == ["02/04/2025", "B", "", "2.00", "0.00"]


def test_a_geometry_with_no_header_has_no_column_count_to_disagree_with():
    """An unknown count is not a disagreement. The ruled read found the header
    here, so it keeps its page."""
    merged = _merge_pages(
        ruled=[[_SIX, ["01/04/2025", "A", "", "", "1.00", "1.00"]]],
        geometric=[[["02/04/2025", "B", "", "2.00", "", "0.00"]]],
    )
    assert merged == [_SIX, ["01/04/2025", "A", "", "", "1.00", "1.00"]]


def test_a_ruled_read_that_found_no_header_does_not_outvote_one_that_did():
    """A summary box drawn with ruling lines is not the statement's table. It
    must not keep geometry — which found the actual header — off the page."""
    merged = _merge_pages(
        ruled=[[["Account Summary", "as at", "31/03/2025"]], []],
        geometric=[[_SIX, ["01/04/2025", "A", "", "", "1.00", "1.00"]],
                   [["02/04/2025", "B", "", "2.00", "", "0.00"]]],
    )
    assert merged[0] == _SIX
    assert ["Account Summary", "as at", "31/03/2025"] not in merged
