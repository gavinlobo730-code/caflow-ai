"""The Form 3CD register as a working paper a CA can print or hand over (POST-A-076).

WHAT THIS IS, AND WHAT IT IS NOT

    `GET /api/income-tax/form-3cd` serves the 44-clause register: ten clauses answered from the books, the rest named with the
    reason they are not, and the CA's own recorded answers where there are any. Until this module the register had no output at
    all, so a CA wanting it on paper took a screenshot. This turns the SAME dict the screen reads into a `ReportDocument`, which
    the report PDF and the report spreadsheet draw (`services/report_pdf_service`, `services/report_xlsx_service`), so the file
    cannot disagree with the screen.

    IT IS A WORKING PAPER, NOT THE FORM. It is not Form 3CD as the Income Tax portal takes it, PracticeSync does not produce that
    file, and nothing here was filed or submitted (the portal's own JSON waits on a schema nobody has fetched). The notes say so on
    the page.

THE ANSWERS ARE NOT KNOWN TO THIS MODULE, ON PURPOSE

    A clause's value is whatever the module behind it returned: a word, a list of losses, the §32 blocks with their own gaps, the
    §43B(h) workings. Writing a layout for each would be a second copy of those shapes that drifts the day one of them gains a
    field. So `describe` reads ANY value the way a person would write it down, and invents nothing:

      * a word or a sentence is itself; true and false are Yes and No; a missing value is "Not stated";
      * a figure under a key ending `_paise` is money, grouped the Indian way (a figure under any other key is printed as the
        number it is, never given a unit it was not stored with); one ending `_bps` is a percentage, done in whole-number
        arithmetic;
      * a key is written as a label (`remaining_amount_paise` -> "Remaining amount"), and the original key is not shown;
      * a list is one line per entry, a record inside it one line of "label: value" pairs, and anything nested below that goes
        on lines of its own, indented.

    NOTHING IS COMPUTED. No figure is added, rounded, translated or defaulted here; a value that cannot be rendered by those rules
    is printed with `str`, which is what the screen's own fallback does.

WHAT IS REFUSED, AND WHAT IS NOT

    A register of more than `MAX_LINES` lines is refused in words rather than cut: a page that silently drops the end of clause 34
    is worse than none, and no real register measured comes near it.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from domain.money_text import rupees_paise
from domain.reporting.export_document import (
    BODY, TEXT, Column, ExportRefused, ReportDocument, Row, Table,
)

FORM_3CD = "form-3cd"

#: Printed lines (rows of the first table) past which the document is refused. A real register is a few hundred at most.
MAX_LINES = 5_000

#: A level of nesting is shown by this many no-break spaces; ordinary spaces at the start of a PDF cell are collapsed by the
#: layout, and a spreadsheet keeps them as typed.
_INDENT = "    "

FROM_THE_BOOKS = "From the books"
RECORDED_BY_THE_CA = "Recorded by the CA"
NOT_ANSWERED = "Not answered here"

_STATUS_WORDS = {"draft": "Draft", "review": "In review", "finalised": "Recorded as finalised by someone who may approve"}

#: Words in a key that are abbreviations, so a label reads "TAN" and not "Tan". A word not listed is written as it is.
_ABBREVIATIONS = frozenset({"tan", "tds", "tcs", "pan", "gst", "gstin", "cgst", "sgst", "igst", "itc", "msme", "msmed", "wdv", "fy", "ay", "hsn"})

_MONEY_KEY = re.compile(r"_paise$")
_RATE_KEY = re.compile(r"_bps$")
_WHOLE_NUMBER = re.compile(r"^-?\d+$")


def _label(key: Any, *, unit_stripped: bool) -> str:
    text = str(key)
    if unit_stripped:
        text = _MONEY_KEY.sub("", _RATE_KEY.sub("", text))
    words = text.replace("_", " ").split()
    if not words:
        return str(key)
    # The letters of an abbreviation are capitals however the key spelled them (`total_tds_deducted` is "Total TDS deducted").
    words = [w.upper() if w.lower() in _ABBREVIATIONS else w for w in words]
    return words[0][:1].upper() + " ".join(words)[1:]


def percent_from_bps(bps: int) -> str:
    """Basis points as a percentage, in whole-number arithmetic: 675 -> `6.75%`, -50 -> `-0.50%`."""
    sign = "-" if bps < 0 else ""
    magnitude = abs(bps)
    return f"{sign}{magnitude // 100}.{magnitude % 100:02d}%"


def _whole_number(value: Any) -> Optional[int]:
    """The integer a stored figure is, whether it arrived as a number or as the digits of one (a bigint comes back as text)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _WHOLE_NUMBER.match(value.strip()):
        return int(value.strip())
    return None


def _scalar(value: Any, key: Optional[str]) -> tuple[str, bool]:
    """(the text, whether the key's unit was applied and may be dropped from the label)."""
    if value is None:
        return "Not stated", False
    if isinstance(value, bool):
        return ("Yes" if value else "No"), False
    key_text = str(key or "")
    whole = _whole_number(value)
    if whole is not None:
        if _MONEY_KEY.search(key_text):
            return rupees_paise(whole), True
        if _RATE_KEY.search(key_text):
            return percent_from_bps(whole), True
    return str(value), False


def _is_scalar(value: Any) -> bool:
    return not isinstance(value, (dict, list, tuple))


def _record_line(record: dict) -> str:
    parts = []
    for key, value in record.items():
        text, stripped = _scalar(value, key)
        parts.append(f"{_label(key, unit_stripped=stripped)}: {text}")
    return "; ".join(parts)


def describe(value: Any, key: Optional[str] = None, depth: int = 0) -> list[str]:
    """Any answer, as the lines a person would write it on a page. See the module note for the rules."""
    pad = _INDENT * depth
    if _is_scalar(value):
        text, _ = _scalar(value, key)
        return [pad + text]
    if isinstance(value, dict):
        if not value:
            return [pad + "No entries."]
        lines: list[str] = []
        for k, v in value.items():
            if _is_scalar(v):
                text, stripped = _scalar(v, k)
                lines.append(f"{pad}{_label(k, unit_stripped=stripped)}: {text}")
            elif not v:
                lines.append(f"{pad}{_label(k, unit_stripped=False)}: No entries.")
            else:
                lines.append(f"{pad}{_label(k, unit_stripped=False)}:")
                lines.extend(describe(v, k, depth + 1))
        return lines
    items = list(value)
    if not items:
        return [pad + "No entries."]
    lines = []
    for item in items:
        if _is_scalar(item):
            text, _ = _scalar(item, key)
            lines.append(f"{pad}- {text}")
        elif isinstance(item, dict) and item and all(_is_scalar(v) for v in item.values()):
            lines.append(f"{pad}- {_record_line(item)}")
        else:
            lines.append(f"{pad}-")
            lines.extend(describe(item, key, depth + 1))
    return lines


def _status_of(clause: dict) -> str:
    if clause.get("derived"):
        return FROM_THE_BOOKS
    if clause.get("value") is not None:
        return RECORDED_BY_THE_CA
    return NOT_ANSWERED


def form_3cd_document(register: dict) -> ReportDocument:
    """The register `services.form_3cd_service.build` returns, as a document. Raises `ExportRefused` for one too long to print."""
    clauses = list(register.get("clauses") or [])
    if not clauses:
        raise ExportRefused("This Form 3CD register has no clauses to print, so no working paper was made.")

    answer_rows: list[Row] = []
    basis_rows: list[Row] = []
    counts = {FROM_THE_BOOKS: 0, RECORDED_BY_THE_CA: 0, NOT_ANSWERED: 0}
    for clause in clauses:
        status = _status_of(clause)
        counts[status] += 1
        code = str(clause.get("code") or "")
        heading = str(clause.get("heading") or "")
        lines = describe(clause["value"]) if clause.get("value") is not None else ["Not answered here."]
        for i, line in enumerate(lines):
            answer_rows.append(Row(
                (code, heading, line, status) if i == 0 else ("", "", line, ""), BODY))
        basis_rows.append(Row((code, str(clause.get("note") or "")), BODY))
        if len(answer_rows) > MAX_LINES:
            raise ExportRefused(
                f"This Form 3CD register runs to more than {MAX_LINES:,} printed lines, which is more than a working paper takes, "
                "and it was not cut short. The register on the screen shows every clause.")

    fy = str(register.get("financial_year") or "")
    status_word = _STATUS_WORDS.get(str(register.get("checklist_status") or ""), str(register.get("checklist_status") or "Not stated"))
    answered = (f"{counts[FROM_THE_BOOKS]} from the books, {counts[RECORDED_BY_THE_CA]} recorded by the CA, "
                f"{counts[NOT_ANSWERED]} not answered, of {len(clauses)}")

    particulars = Table(
        heading="Statement of particulars",
        columns=(
            Column("clause", "Clause", TEXT, 0.6),
            Column("particulars", "Particulars", TEXT, 3.0),
            Column("answer", "Answer", TEXT, 4.6),
            Column("source", "Source", TEXT, 1.3),
        ),
        rows=tuple(answer_rows),
    )
    bases = Table(
        heading="Basis of each answer",
        columns=(Column("clause", "Clause", TEXT, 0.6), Column("basis", "Basis", TEXT, 9.0)),
        rows=tuple(basis_rows),
    )
    return ReportDocument(
        report_id=FORM_3CD,
        title="Form 3CD working paper",
        subject="",
        period=f"Previous year {fy}" if fy else "",
        tables=(particulars, bases),
        meta=(("Financial year", fy), ("Checklist", status_word), ("Clauses", answered)),
        notes=(
            "This is a working paper for the CA's review, built from the books as they stand and from the answers the CA has "
            "recorded on the register. It is not Form 3CD as the Income Tax portal takes it: PracticeSync does not produce that "
            "file, and nothing here has been filed or submitted.",
            "\"From the books\" means a figure PracticeSync computed from this client's records by the module named in its basis; "
            "\"Recorded by the CA\" means the CA typed it on the register and PracticeSync has not checked it; \"Not answered here\" "
            "means PracticeSync neither holds nor derives that fact, and the CA answers it in the report.",
            "Where a clause is answered from only part of what the form asks, its basis says which part and what is left to the CA, "
            "and a gap the module behind a figure named is printed with that figure.",
        ),
        landscape=True,
        file_stem=f"form-3cd-working-paper-{fy}" if fy else "form-3cd-working-paper",
        sheet_name="Form 3CD",
    )
