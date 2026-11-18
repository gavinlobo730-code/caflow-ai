"""Reading a spreadsheet of payroll opening positions (POST-A-082, part 2): the file's cells into the rows `PUT /opening-positions` takes.

The same shape as the employee import (`domain/payroll/employee_import.py`): the browser reads the file's cells as text, and every
decision about them is made here, for the whole file at once, keyed to the row the CA sees in their spreadsheet. If one row is wrong,
nothing is written. A row names its employee by the employee code, because a name is not unique and an id is not something a CA holds.

WHAT A CELL MAY MEAN, AND WHAT IT MAY NOT
  * Every amount is REQUIRED, the way the form requires it: a blank cell is "not entered" and is refused, never read as nil (write 0 for
    nothing). Amounts are rupees, Indian grouping allowed, at most two decimals, read to integer paise by concatenation
    (`employee_import._paise`), never by multiplying a float.
  * The first month is YYYY-MM; a spreadsheet date on the first of a month (what a workbook's date cell becomes) is read as its month,
    and any other day is refused rather than guessed.
  * The ESI answer is yes, no, or blank for "not known", which is not read as no.

It holds no statutory figure. Whether the figures make sense together (the months against the joining date, tax against gross, the ESI
answer against the contribution period) is `opening_position.validate`, asked by the route for the file exactly as for the form.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from domain.payroll.employee_import import _paise, _text

#: (column, the field of `OpeningPositionIn` it fills). Every column but the ESI answer and the note is required.
COLUMNS: list[tuple[str, str, bool]] = [
    ("employee_code", "employee_id", True),
    ("first_month_here", "first_month_here", True),
    ("months_paid", "months_paid", True),
    ("gross", "gross_paise", True),
    ("tds", "tds_paise", True),
    ("pf_employee", "pf_employee_paise", True),
    ("pf_employer", "pf_employer_paise", True),
    ("esi_employee", "esi_employee_paise", True),
    ("esi_employer", "esi_employer_paise", True),
    ("pt", "pt_paise", True),
    ("esi_contributed_earlier_in_period", "esi_contributed_earlier_in_period", False),
    ("source_note", "source_note", False),
]

_AMOUNTS = [(c, f) for c, f, _req in COLUMNS if f.endswith("_paise")]
_YES = {"y", "yes", "true", "1", "t"}
_NO = {"n", "no", "false", "0", "f"}
_NOT_KNOWN = {"", "not known", "unknown", "nk"}


@dataclass
class OpeningImport:
    """Every problem in the file, and the rows `PUT /opening-positions` would take (with their spreadsheet row numbers)."""
    problems: list[str] = field(default_factory=list)
    rows: list[tuple[int, dict[str, Any]]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _month(raw: str) -> Optional[str]:
    m = re.fullmatch(r"(\d{4})-(\d{2})(?:-01)?", raw)
    if not m or not 1 <= int(m.group(2)) <= 12:
        return None
    return f"{m.group(1)}-{m.group(2)}"


def read(rows: list[dict], *, employee_by_code: dict[str, str]) -> OpeningImport:
    """Read the whole file. `employee_by_code` maps an employee code on this client's roster (lower case) to the employee's id."""
    out = OpeningImport()
    if not rows:
        out.problems.append("The file has no rows.")
        return out
    for index, raw_row in enumerate(rows):
        n = index + 1
        row = {str(k).strip().lower(): v for k, v in (raw_row or {}).items()}
        problems: list[str] = []
        body: dict[str, Any] = {}

        code = _text(row, "employee_code")
        if not code:
            problems.append("employee_code is required")
        elif code.lower() not in employee_by_code:
            problems.append(f'no employee with the code "{code}" is on this client\'s roster')
        else:
            body["employee_id"] = employee_by_code[code.lower()]

        month = _month(_text(row, "first_month_here"))
        if month is None:
            problems.append(f'first_month_here must be a month as YYYY-MM, got "{_text(row, "first_month_here")}"')
        else:
            body["first_month_here"] = month

        months = _text(row, "months_paid")
        if not re.fullmatch(r"\d{1,2}", months):
            problems.append(f'months_paid must be a whole number of months, got "{months}"')
        else:
            body["months_paid"] = int(months)

        for column, name in _AMOUNTS:
            if not _text(row, column):
                problems.append(f"{column} is required (write 0 for nothing): a blank is not entered, not nil")
                continue
            value, err = _paise(row, column)
            if err or value is None or value < 0:
                problems.append(err or f"{column} may not be negative")
            else:
                body[name] = value

        typed = _text(row, "esi_contributed_earlier_in_period")
        answer = typed.lower()
        if answer in _YES:
            body["esi_contributed_earlier_in_period"] = True
        elif answer in _NO:
            body["esi_contributed_earlier_in_period"] = False
        elif answer in _NOT_KNOWN:
            body["esi_contributed_earlier_in_period"] = None
        else:
            problems.append(f'esi_contributed_earlier_in_period must be yes, no or blank for not known, got "{typed}"')

        body["source_note"] = _text(row, "source_note") or None

        if problems:
            out.problems.extend(f"Row {n}: {p}" for p in problems)
        else:
            out.rows.append((n, body))
    return out


def template_csv() -> str:
    """The header row, and nothing else (a template with an example row gets uploaded with the example in it)."""
    return ",".join(c for c, _f, _r in COLUMNS) + "\n"
