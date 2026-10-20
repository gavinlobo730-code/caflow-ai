"""TDS deducted and not yet deposited, as one number (the hub's TDS tile).

THE QUESTION. How much of the tax a firm's clients have withheld has no recorded challan behind it? The hub's tile used to read
`tds_deductions.challan_no IS NULL`. A deduction a purchase bill writes never carries that column (`POST /challans` records the
challan and never touches the deductions it paid), so the tile counted every such deduction as undeposited: on the seeded demo firm,
with every deduction deposited by a recorded challan, the dashboard said ₹1,94,614.98.

THE ANSWER IS THE CHALLAN REGISTER'S. A challan pays the deductions of its own financial year and quarter under its own section,
first in first out (`challan_mapping`), so what a group (client, financial year, quarter, section) has left undeposited is
`max(0, deducted - paid)` whatever the order of the fill, and the total is the sum of those. Migration 523's
`public.tds_deposit_position` (522's `tds_undeposited_paise` is now a wrapper over its first figure) computes it where the rows are,
because a firm-wide tile may not fetch rows proportional to the ledger. THIS MODULE IS ITS TWIN, a literal Python port of the SQL, and
its users are the in-memory database double the suites use (`tests/e2e_harness.py`: mock mode has no SQL functions) and the TDS
screen's deposit-state route in mock mode (`routers/tds_workspace.deposit_state`); production runs the SQL.
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

A QUARTER WITH NO CHALLAN RECORDED IS NOT A DEPOSIT DEFAULT (migration 523). The shortfall above is counted only in a (client,
financial year, quarter) for which the register holds at least one non-salary challan, whatever its section or amount; the tax
deducted in a quarter for which it holds none is reported apart as NOT RECORDED. For a firm that keeps its deposits in another system
the first reading says "₹X not yet deposited" about a deposit the books cannot see, which is an unknown shown as a value. Form 3CD
clause 34 uses the same rule. `position` returns both figures from one pass; `undeposited_paise` is its first, kept for callers that
want one.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Iterable, NamedTuple, Optional

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


class Position(NamedTuple):
    """The two figures one pass gives: `undeposited_paise` is the shortfall in quarters for which a challan is recorded, and
    `not_recorded_paise` the tax deducted in quarters for which none is."""
    undeposited_paise: int
    not_recorded_paise: int


def position(deductions: Iterable[dict], challans: Iterable[dict], *,
             client_ids: Optional[Iterable[str]] = None) -> Position:
    """The deposit position across these deductions, in paise.

    `client_ids` None is every client in the rows given; an empty collection is no client and answers nil on both. A challan meets
    only the deductions of the financial year and quarter it was recorded for, and a quarter in which no non-salary challan is
    recorded contributes its deductions' tax to `not_recorded_paise` and nothing to `undeposited_paise`."""
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
    recorded = {key[:3] for key in paid}
    undeposited = not_recorded = 0
    for key, tax in owed.items():
        if key[:3] in recorded:
            undeposited += max(0, tax - paid.get(key, 0))
        else:
            not_recorded += tax
    return Position(undeposited, not_recorded)


def undeposited_paise(deductions: Iterable[dict], challans: Iterable[dict], *,
                      client_ids: Optional[Iterable[str]] = None) -> int:
    """The tax deducted and not yet deposited, in quarters for which a challan is recorded: `position`'s first figure."""
    return position(deductions, challans, client_ids=client_ids).undeposited_paise
