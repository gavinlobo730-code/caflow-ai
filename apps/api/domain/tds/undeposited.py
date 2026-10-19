"""TDS deducted and not yet deposited, as one number (the hub's TDS tile).

THE QUESTION. How much of the tax a firm's clients have withheld has no recorded challan behind it? The hub's tile used to read
`tds_deductions.challan_no IS NULL`. A deduction a purchase bill writes never carries that column (`POST /challans` records the
challan and never touches the deductions it paid), so the tile counted every such deduction as undeposited: on the seeded demo firm,
with every deduction deposited by a recorded challan, the dashboard said ₹1,94,614.98.

THE ANSWER IS THE CHALLAN REGISTER'S. A challan pays the deductions of its own financial year and quarter under its own section,
first in first out (`challan_mapping`), so what a group (client, financial year, quarter, section) has left undeposited is
`max(0, deducted - paid)` whatever the order of the fill, and the total is the sum of those. Migration 522's
`public.tds_undeposited_paise` computes it where the rows are, because a firm-wide tile may not fetch rows proportional to the
ledger. THIS MODULE IS ITS TWIN, a literal Python port of the SQL, and its only user is the in-memory database double the suites
use (`tests/e2e_harness.py`: mock mode has no SQL functions); production runs the SQL.
`tests/test_the_undeposited_tds_asks_the_challan_register_pg.py` holds the two identical over a real Postgres, and
`tests/test_the_undeposited_tds_asks_the_challan_register.py` holds this port to the register's own match
(`deposit_due.mapping_from_register`) for every section the registry holds.

A SECTION IS GROUPED AS TYPED, WITH A TRAILING BRACKETED LIMB DROPPED ("194J(B)" -> "194J"). For every section the registry holds
that is `section_rates.parent_of`, which is what the statement and the worksheet group by. For a section the registry does not hold
the statement groups by the text itself and this answer by the bracket-stripped text, so "194Z(A)" is paid by a challan typed
"194Z" here and is not on the statement (the SQL does the same; a challan's section is free text). Whitespace is ASCII whitespace
only, and case-folding is `str.upper`, which is `upper()` for ASCII sections.

Salary (section 192, three spellings) is in neither side: payroll deposits it and neither half of this register carries it. A negative
row neither pays nor owes. A deduction with no usable date is left out, as the worksheet leaves it (there is no quarter to place it
in). Integer paise throughout.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Iterable, Optional

from domain.tds import challan_mapping

_ASCII_SPACE = " \t\n\r\f\v"
_BRACKETED_LIMB = re.compile(r"([^(])\(.*\)\Z", re.S)
_SALARY_SPELLINGS = ("192", "SEC192", "S192")
NO_SECTION = "(NO SECTION)"


def fy_label_of(on: date) -> str:
    """The financial year a date falls in, as a label: 2026-01-10 is "2025-26"."""
    start = on.year if on.month >= 4 else on.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def quarter_of(on: date) -> str:
    """Rule 31A's quarters of a financial year: April to June is Q1."""
    if 4 <= on.month <= 6:
        return "Q1"
    if 7 <= on.month <= 9:
        return "Q2"
    if 10 <= on.month <= 12:
        return "Q3"
    return "Q4"


def is_salary(section) -> bool:
    return str(section or "").replace(" ", "").upper() in _SALARY_SPELLINGS


def section_group(section, *, blank: str = "") -> str:
    """The group a typed section belongs to: trimmed, upper-cased, a trailing bracketed limb dropped. `blank` is what an empty one
    reads as: "(NO SECTION)" for a deduction, nothing for a challan, as the SQL spells them."""
    typed = str(section or "").strip(_ASCII_SPACE).upper() or blank
    return _BRACKETED_LIMB.sub(r"\1", typed, count=1)


def _at_least_nil(*parts) -> int:
    return max(0, sum(int(p or 0) for p in parts))


def undeposited_paise(deductions: Iterable[dict], challans: Iterable[dict], *,
                      client_ids: Optional[Iterable[str]] = None) -> int:
    """The tax deducted and not yet deposited across these deductions, in paise.

    `client_ids` None is every client in the rows given; an empty collection is no client and answers 0. A challan meets only the
    deductions of the financial year and quarter it was recorded for."""
    wanted = None if client_ids is None else {str(c) for c in client_ids}
    owed: dict[tuple, int] = {}
    for row in deductions:
        client = str(row.get("client_id"))
        on = challan_mapping.as_date(row.get("transaction_date"))
        if on is None or (wanted is not None and client not in wanted) or is_salary(row.get("section")):
            continue
        key = (client, fy_label_of(on), quarter_of(on), section_group(row.get("section"), blank=NO_SECTION))
        owed[key] = owed.get(key, 0) + _at_least_nil(row.get("tds_paise"), row.get("surcharge_paise"), row.get("cess_paise"))
    paid: dict[tuple, int] = {}
    for row in challans:
        client = str(row.get("client_id"))
        if (wanted is not None and client not in wanted) or is_salary(row.get("section")):
            continue
        key = (client, str(row.get("financial_year") or ""), str(row.get("quarter") or ""), section_group(row.get("section")))
        paid[key] = paid.get(key, 0) + _at_least_nil(row.get("tds_paise"), row.get("surcharge_paise"))
    return sum(max(0, tax - paid.get(key, 0)) for key, tax in owed.items())
