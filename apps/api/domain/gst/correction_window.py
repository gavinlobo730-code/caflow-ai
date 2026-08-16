"""
How long a filed period can still be corrected, and when that stops being true.

THE RULE, AND WHY IT IS ONE RULE AND NOT THREE
    Three separate provisions close on the same date:

      CGST §37(3) proviso  rectifying an error in GSTR-1
      CGST §39(9) proviso  rectifying an error in GSTR-3B
      CGST §16(4)          taking input tax credit on an invoice or debit note

    All three were amended by the Finance Act 2022 from the old "return for
    September following the financial year" formulation to:

        30 November following the end of the financial year, OR the furnishing
        of the relevant annual return, WHICHEVER IS EARLIER.

    So one window governs amendments (#152) and unclaimed credit alike, and one
    date decides both.

THE "WHICHEVER IS EARLIER" IS THE PART THAT BITES
    A client who files GSTR-9 in August has lost the ability to amend that year
    from August — three months before the date everyone quotes. Reporting 30
    November regardless would tell a CA a correction is available when it has
    already gone.

WHAT CLOSING MEANS
    Not "late". Gone. After the window there is no mechanism to declare the
    correction or to take the credit: the output tax stays understated or the
    input credit is simply lost. That is why this warns ahead rather than
    reporting afterwards, and why a closed window is still reported rather than
    hidden — a CA needs to know what can no longer be fixed at least as much as
    what can.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from services.compliance_engine import correction_window_closes, november_30_cutoff

# How far ahead a window starts being called out. A month is roughly the time
# needed to find the drift, decide the treatment, and get it into a return that
# is itself only filed monthly — warning later than this leaves no room to act.
CLOSING_SOON_DAYS = 30

OPEN = "open"
CLOSING_SOON = "closing_soon"
CLOSED = "closed"


def financial_year_end(period: str) -> Optional[int]:
    """Calendar year in which the FY containing MMYYYY ends on 31 March.

    India's financial year runs 1 April to 31 March (CLAUDE.md), so June 2025 is
    in FY 2025-26, which ends in 2026 — and its correction window therefore runs
    to 30 November 2026, not 2025. Getting this wrong by a year is the whole
    difference between "you have months" and "it closed last year".
    """
    s = str(period or "")
    if len(s) != 6 or not s.isdigit():
        return None
    month, year = int(s[:2]), int(s[2:])
    if not 1 <= month <= 12:
        return None
    return year + 1 if month >= 4 else year


def fy_label(period: str) -> str:
    """'062025' -> '2025-26'. What a CA calls the year."""
    end = financial_year_end(period)
    if end is None:
        return ""
    return f"{end - 1}-{str(end)[2:]}"


def window_for(
    period: str, *, as_of: date, annual_return_filed_on: Optional[date] = None
) -> Optional[dict]:
    """When the correction window for `period` closes, and where it stands.

    `as_of` rather than today() so a CA can ask the question as at a period end,
    and so the tests are not a function of the day they run.
    """
    end = financial_year_end(period)
    if end is None:
        return None

    statutory = november_30_cutoff(end)
    closes = correction_window_closes(end, annual_return_filed_on)
    days_left = (closes - as_of).days

    if days_left < 0:
        status = CLOSED
    elif days_left <= CLOSING_SOON_DAYS:
        status = CLOSING_SOON
    else:
        status = OPEN

    return {
        "period": period,
        "financial_year": fy_label(period),
        "closes_on": closes.isoformat(),
        "days_left": days_left,
        "status": status,
        "statutory_cutoff": statutory.isoformat(),
        # True when filing GSTR-9 pulled the date in ahead of 30 November.
        # Worth saying out loud: the CA will otherwise be working from the date
        # everyone quotes, and be wrong by however early the annual return went.
        "shortened_by_annual_return": closes < statutory,
        "rule": "CGST Act §37(3) / §39(9) / §16(4) — 30 November following the "
                "financial year end, or the annual return, whichever is earlier "
                "(Finance Act 2022).",
    }


def is_actionable(window: Optional[dict]) -> bool:
    """Can a correction for this period still be declared at all?"""
    return bool(window) and window.get("status") != CLOSED
