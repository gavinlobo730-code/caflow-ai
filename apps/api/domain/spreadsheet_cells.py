"""Reading what a person typed into a spreadsheet cell — the one place (ACC-05/17/18).

Three bulk imports (opening documents, vouchers, the fixed-asset register) take a
CSV or workbook a CA or a bookkeeper filled in by hand, and every one of them has
to read a DATE and match a NAME. They are written here once, because each of the
three would otherwise have grown its own, and "the same date reads two ways
depending on which screen you uploaded it to" is how a ledger acquires entries
dated in the wrong month.

THE DATE RULE, AND WHAT IT REFUSES
    An Indian spreadsheet writes the DAY FIRST: 01-04-2026, 1/4/2026, 01.04.2026,
    01-Apr-2026, or the ISO 2026-04-01 a machine writes. All of those are read.

    What is REFUSED, deliberately, is a two-digit year. `4/1/26` is 4 January 2026
    to a spreadsheet library that defaults to the American order and 1 April 2026
    to the person who typed it, and when an Excel workbook is turned into text the
    cell a CA formatted as a date can come out in exactly that form. There is no
    way to tell which was meant from the cell, so the cell is not read: the row is
    returned to the person with a sentence saying how to write it, which costs a
    minute, instead of being dated in the wrong month, which costs a return.

    Nor is a day-first reading attempted on an ISO date, or the reverse: the shape
    decides, so two readers cannot disagree about one string.

    A real calendar date or nothing: 31-02-2026 is None, not 3 March.

WHY A NAME IS FOLDED AND NOT MATCHED FUZZILY
    A party named "Acme Traders" in the file is "ACME  TRADERS" in the master and
    the same party; case and runs of spaces are noise. Two parties whose names are
    DIFFERENT words are different parties however alike they look — a fuzzy match
    that joins "Sharma Traders" to "Sharma Trading Co" books one customer's
    receivable against another's, which is invisible until they are asked to pay.
    So the fold removes only what is certainly not a difference, and a name that
    still matches more than one party is reported as ambiguous and never picked.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?$")
_DAY_FIRST = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$")
_DAY_MONTH_NAME = re.compile(r"^(\d{1,2})[ \-/.]([A-Za-z]{3,9})[ \-/.,]+(\d{4})$")

#: What to say when a date cell cannot be read. One sentence, so the three
#: imports tell a person the same thing.
DATE_FORMAT_SENTENCE = (
    "write it as dd-mm-yyyy or yyyy-mm-dd — a two-digit year is not read, "
    "because 4/1/26 could be 4 January or 1 April")


def parse_cell_date(value: Any) -> Optional[date]:
    """A date a person typed, or None where it cannot be read with certainty."""
    if isinstance(value, date):
        return value
    s = str(value if value is not None else "").strip()
    if not s:
        return None
    try:
        m = _ISO.match(s)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = _DAY_FIRST.match(s)
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        m = _DAY_MONTH_NAME.match(s)
        if m:
            month = _MONTHS.get(m.group(2).lower())
            if month:
                return date(int(m.group(3)), month, int(m.group(1)))
    except ValueError:
        return None          # 31-02-2026: a shape that is not a day
    return None


def fold_name(value: Any) -> str:
    """A name with only the certainly-meaningless differences removed.

    Case, runs of whitespace and trailing punctuation. NOT "&" against "and",
    "Pvt." against "Private" or "M/s" — each of those is a judgement about two
    different strings, and this module does not make it.
    """
    s = " ".join(str(value if value is not None else "").casefold().split())
    return s.rstrip(" .,;:")
