"""The compliance calendar as a spreadsheet a CA can sort, filter and send (POST-A-142, the second half of its export).

WHAT THIS IS, AND WHAT IT IS NOT

    A FILE OF DUE DATES, one row per obligation, built from the same rows the obligation calendar already serves and the iCalendar
    file already carries. It holds no rule of its own: the due date is the one `compliance_records` holds, the status is the stored
    workflow word printed as it is, and the "on the calendar" column is the BUCKET the calendar read put the row in (overdue,
    upcoming or settled): nothing here decides whether anything is late. The settled bucket holds two different things, a filing and
    an obligation the CA recorded as not owed by the client (POST-A-267), so its row is labelled by which of the two it is: "Filed"
    for the first and "Not required" for the second, never "Filed" for a payment nobody made. It files nothing and transmits nothing.

    # CA REVIEW REQUIRED, DO NOT AUTO-SUBMIT. The first column header says, in words, that the date is a due date and not a filing.

WHAT A SPREADSHEET FILE HAS TO GET RIGHT

    * UTF-8 WITH A BYTE-ORDER MARK, because Excel opens a CSV in the local code page unless the file says otherwise, and a client's
      name in Devanagari is otherwise rubbish.
    * A CELL THAT STARTS WITH `=`, `+`, `-`, `@`, a tab or a carriage return IS A FORMULA to a spreadsheet. A client's name is typed by
      a person, and `=HYPERLINK(...)` in one would run on the CA's machine when they open the file. Such a cell is written with a
      leading apostrophe, which a spreadsheet shows as text and does not evaluate.
    * A COMMA, A QUOTE OR A LINE BREAK in a cell is quoted by the writer (`csv`), not by hand.
    * A ROW WITH NO USABLE DUE DATE IS KEPT, with an empty date: a spreadsheet can hold a blank, and a row that quietly left the file
      would read as nothing being due. (The iCalendar file cannot place such a row, and says how many it left out.)
"""
from __future__ import annotations

import csv
import io
from datetime import date
from typing import Iterable

from domain.practice.compliance_overdue import NOT_REQUIRED

#: The header row. The first names what the date is, so a file passed on without its screen is not read as a filing record.
COLUMNS = ("Due date (not a filing date)", "Client", "Obligation", "Type", "Status", "On the calendar")

#: What each bucket of the calendar read is called in the file. The settled bucket ("completed") is "Filed" for a filing and
#: NOT_REQUIRED_LABEL for an obligation recorded as not owed (`bucket_label`).
BUCKET_LABEL = {"overdue": "Overdue", "upcoming": "Upcoming", "completed": "Filed"}
NOT_REQUIRED_LABEL = "Not required"

_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: object) -> str:
    """The text of a cell, with a leading apostrophe when a spreadsheet would take it for a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_STARTS) else text


def _day(value: object) -> str:
    """The due date as `YYYY-MM-DD`, or an empty cell when the row holds none a person could read as a date."""
    try:
        return date.fromisoformat(str(value or "")[:10]).isoformat()
    except ValueError:
        return ""


def bucket_label(bucket: str, row: dict) -> str:
    """The "on the calendar" cell: the bucket's name, except that a settled row the CA recorded as not required says so."""
    if bucket == "completed" and row.get("status") == NOT_REQUIRED:
        return NOT_REQUIRED_LABEL
    return BUCKET_LABEL.get(bucket, bucket)


def _title(row: dict) -> str:
    return str(row.get("period_label") or row.get("obligation_type") or row.get("compliance_type") or "Compliance obligation")


def from_rows(rows: Iterable[tuple[str, dict]], client_names: dict) -> bytes:
    """The file for `(bucket, row)` pairs, oldest due date first (a row with no date last), as UTF-8 with a byte-order mark."""
    lines = []
    for bucket, r in rows:
        lines.append((
            _day(r.get("due_date")),
            client_names.get(str(r.get("client_id") or ""), ""),
            _title(r),
            str(r.get("compliance_type") or ""),
            str(r.get("status") or ""),
            bucket_label(bucket, r),
            str(r.get("id") or ""),
        ))
    # Dated rows by date, then by client and obligation so the order is stable between two downloads; undated ones after them.
    lines.sort(key=lambda cells: (cells[0] == "", cells[0], cells[1], cells[2], cells[6]))
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    for cells in lines:
        writer.writerow([safe_cell(c) for c in cells[:6]])
    return buf.getvalue().encode("utf-8-sig")
