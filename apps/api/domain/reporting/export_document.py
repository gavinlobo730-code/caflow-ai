"""A live report, made ready to be printed or opened in a spreadsheet.

WHAT THIS IS FOR (accounting-16)

    A CA hands the ledger, the trial balance, the cash flow statement and the
    ageing to a bank or an auditor, and until now the only server-made PDFs
    were the year-end pack, the bank reconciliation, a customer statement, an
    invoice and a payslip: everything else was the browser's print dialog or a
    CSV of the screen. A banker wants a clean document with the client's name
    on it, not a screenshot.

THE SHAPE, AND WHY THERE IS ONE

    A report is a `ReportDocument`: a title, a few lines saying whose books and
    which period, one or more tables of already-computed figures, and the
    caveats the screen shows beside them. `services/report_pdf_service.py` and
    `services/report_xlsx_service.py` are two RENDERERS of that one object, so
    the PDF and the spreadsheet cannot disagree with each other, and
    `export_builders` builds it from the dict the screen's own endpoint already
    returns, so neither can disagree with the screen.

    NOTHING IN HERE COMPUTES A FIGURE. Every cell is a value the report
    function returned, copied across; the one thing the builders do beyond
    copying is CHECK that a document foots (a ledger's lines must carry its
    opening balance to its closing one) and REFUSE to produce one that does
    not. A printed statement that does not add up is worse than none, because
    it is the copy that leaves the building.

THE THREE CELL KINDS

    TEXT     a string, or None for an empty cell.
    MONEY    integer PAISE, or None for an empty cell. A zero debit on a ledger
             line is None, not 0 — the screen shows a blank there and a column
             of printed zeros is noise — while a figure that IS nil and is
             worth saying so (a nil closing balance) is 0.
    BALANCE  signed integer paise, DEBIT-POSITIVE. A ledger balance has a
             side, which the PDF prints as `Dr`/`Cr` and the spreadsheet keeps
             as the sign so the column can be added up. `is_debit` is
             `balance >= 0` in both ledger implementations (builders.ledger and
             public.account_ledger_page), so the sign carries the side.
    INT      a whole number that is not money (days overdue).

    Money is never a float anywhere in this module. The spreadsheet renderer
    divides by a Decimal at the last moment, and the PDF renderer groups with
    `domain/money_text`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from domain.money_text import rupees_paise

TEXT = "text"
MONEY = "money"
BALANCE = "balance"
INT = "int"
KINDS = (TEXT, MONEY, BALANCE, INT)

#: A row is an ordinary one, a total/opening/closing line (set bold on a muted
#: band) or a section heading (a label with no figures).
BODY = "body"
EMPHASIS = "emphasis"
SECTION = "section"
ROW_STYLES = (BODY, EMPHASIS, SECTION)


class ExportRefused(Exception):
    """A report that cannot be produced as a document, and why, in words.

    The router turns it into a 422 carrying the message, so the CA reads the
    reason rather than "Internal server error". Raised for a ledger that does
    not foot and for a report too large to print, and for nothing a retry
    could fix.
    """


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: str = TEXT
    #: Relative width on a printed page. Only the ratios matter.
    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown column kind {self.kind!r}")


@dataclass(frozen=True)
class Row:
    cells: tuple
    style: str = BODY

    def __post_init__(self) -> None:
        if self.style not in ROW_STYLES:
            raise ValueError(f"unknown row style {self.style!r}")


@dataclass(frozen=True)
class Table:
    columns: tuple[Column, ...]
    rows: tuple[Row, ...]
    heading: Optional[str] = None

    def __post_init__(self) -> None:
        # A row shorter than its header would shift every figure one column
        # left in a spreadsheet and print under the wrong heading on a page —
        # silently, which is the one way a table can be wrong and look right.
        width = len(self.columns)
        for i, row in enumerate(self.rows):
            if len(row.cells) != width:
                raise ValueError(
                    f"row {i} has {len(row.cells)} cells for {width} columns")
            for cell, col in zip(row.cells, self.columns):
                if cell is None:
                    continue
                if col.kind in (MONEY, BALANCE, INT):
                    if isinstance(cell, bool) or not isinstance(cell, int):
                        raise ValueError(
                            f"row {i}, column {col.key!r}: {col.kind} cells hold "
                            f"integers, got {type(cell).__name__}")
                elif not isinstance(cell, str):
                    raise ValueError(
                        f"row {i}, column {col.key!r}: text cells hold strings, "
                        f"got {type(cell).__name__}")


@dataclass(frozen=True)
class ReportDocument:
    report_id: str
    #: The report's own name — "General Ledger", "Trial Balance".
    title: str
    #: What it is a report OF — an account, or the books as at a date. May be
    #: empty.
    subject: str
    #: The period or as-at date, already worded ("2026-04-01 to 2027-03-31").
    period: str
    tables: tuple[Table, ...]
    #: Label/value lines under the title ("Basis", "Account type").
    meta: tuple[tuple[str, str], ...] = ()
    #: Caveats and tie-out statements, shown after the tables on a page and on
    #: a sheet of their own in a spreadsheet.
    notes: tuple[str, ...] = ()
    #: A table with many money columns wants the width.
    landscape: bool = False
    #: The file's own name, without extension, and its first sheet's name.
    file_stem: str = "report"
    sheet_name: str = "Report"


def cell_text(kind: str, value) -> str:
    """The text a cell prints as. `None` is an empty cell, never a zero.

    Here rather than in a renderer because the PDF prints it and the
    spreadsheet SIZES its columns from it, and two spellings of "how wide is
    this figure" is one reformat from a clipped column. No rupee sign: a PDF
    cannot draw one (ReportLab's core fonts have no U+20B9) and a spreadsheet
    cell holds a number whose FORMAT is the display.
    """
    if value is None:
        return ""
    if kind == BALANCE:
        return f"{rupees_paise(abs(value))} {'Dr' if value >= 0 else 'Cr'}"
    if kind == MONEY:
        return rupees_paise(value)
    return str(value)
