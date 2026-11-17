"""A payroll opening position: what an employee had been paid and had deducted in the financial year before this product ran
their client's payroll (POST-A-082).

A CA enters it per employee; it is validated here and read by the engine beside the released runs. It is NEVER a back-dated run:
no slip, no ledger entry, no remittance. It holds no statutory figure of its own: every figure is a fact the CA read off the
old system's records, and the checks are arithmetic on those facts and on the calendar.

WHAT IT DOES NOT CARRY (the screen says so beside the form):
  * a previous EMPLOYER's salary and tax (s.192(2), Form 12B). That is a different fact with its own proof and its own reading
    (POST-A-084) and will be a table of its own; this record's `months_paid` and `gross_paise` are THIS employer's, paid before
    the product, and must not be used for the previous employer's;
  * the lifetime exemptions already used (gratuity, leave encashment);
  * any month this product has run.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Optional

AMOUNT_FIELDS = ("gross_paise", "tds_paise", "pf_employee_paise", "pf_employer_paise",
                 "esi_employee_paise", "esi_employer_paise", "pt_paise")


def months_before(first_month: date, fy: str, joining_date: Optional[str]) -> Optional[int]:
    """How many months of `fy` the employee could have been paid for before `first_month`: from the later of 1 April and the
    joining month, up to but not including `first_month`. None when the joining date cannot be read (the bound is then the
    months from April, which is what `months_before_fy_start` returns)."""
    start_year = int(fy[:4])
    fy_start = date(start_year, 4, 1)
    begin = fy_start
    if joining_date:
        try:
            joined = date.fromisoformat(str(joining_date)[:10])
        except ValueError:
            return None
        if joined > fy_start:
            begin = date(joined.year, joined.month, 1)
    return max(0, (first_month.year - begin.year) * 12 + first_month.month - begin.month)


def esi_answer_can_be_yes(first_month: date) -> bool:
    """Whether "contributed to ESI earlier in this contribution period" can be true of a position whose first month is
    `first_month`. The periods are April to September and October to March (`esi_contribution_period`), so a first month of
    April or October opens its period and has no earlier month in it: a Yes there can only describe the PREVIOUS period, and the
    continuation the answer feeds does not cross a period boundary (`_members_contributing_earlier_this_period`)."""
    return first_month.month not in (4, 10)


def _esi_answer_problems(body: Mapping[str, Any], first: date) -> list[str]:
    if body.get("esi_contributed_earlier_in_period") is True and not esi_answer_can_be_yes(first):
        return [f"The first month {first:%Y-%m} opens an ESI contribution period (April or October), so no earlier month of "
                f"that period exists; a contribution in the previous period does not carry over. Answer No or Not known."]
    return []


def validate(body: Mapping[str, Any], *, fy: str, joining_date: Optional[str]) -> list[str]:
    """Every problem with a position, in a CA's words. Empty means acceptable. `fy` is the financial year the first month falls in."""
    problems: list[str] = []
    try:
        first = date.fromisoformat(f"{str(body.get('first_month_here'))[:7]}-01")
    except ValueError:
        return ["The first month this product runs payroll for this client is not a month (use YYYY-MM)."]
    start_year = int(fy[:4])
    if not (date(start_year, 4, 1) <= first <= date(start_year + 1, 3, 1)):
        problems.append(f"The first month {first:%Y-%m} is not in the financial year {fy}.")
        return problems
    months_paid = body.get("months_paid")
    if not isinstance(months_paid, int) or isinstance(months_paid, bool) or months_paid < 0:
        return problems + ["Months already paid must be a whole number, zero or more."]
    for f in AMOUNT_FIELDS:
        v = body.get(f)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            problems.append(f"{f} must be a whole number of paise, zero or more.")
    if problems:
        return problems
    possible = months_before(first, fy, joining_date)
    if possible is None:
        problems.append("The employee's joining date cannot be read, so the number of months they could have been paid for before "
                        "this product cannot be checked. Correct the joining date first.")
    elif months_paid > possible:
        if joining_date and date.fromisoformat(str(joining_date)[:10]) > date(start_year, 4, 1):
            problems.append(f"{months_paid} months were entered but the employee joined in {str(joining_date)[:7]}, so at most "
                            f"{possible} month(s) of {fy} fall before {first:%Y-%m}.")
        else:
            problems.append(f"{months_paid} months were entered but only {possible} month(s) of {fy} fall before {first:%Y-%m}.")
    if (months_paid == 0) != (body["gross_paise"] == 0):
        problems.append("Months already paid and the gross paid so far go together: both are nil, or both are more than nil.")
    if body["tds_paise"] > body["gross_paise"]:
        problems.append("The tax withheld so far is more than the gross paid so far.")
    if body["pf_employee_paise"] + body["esi_employee_paise"] + body["pt_paise"] + body["tds_paise"] > body["gross_paise"]:
        problems.append("The employee's own deductions (tax, PF, ESI and professional tax) add up to more than the gross paid so far.")
    if months_paid == 0 and any(body[f] for f in AMOUNT_FIELDS):
        problems.append("No month was paid, yet an amount was entered.")
    problems.extend(_esi_answer_problems(body, first))
    note = body.get("source_note")
    if note is not None and len(str(note)) > 500:
        problems.append("The note is longer than 500 characters.")
    return problems


@dataclass(frozen=True)
class Opening:
    tds_paise: int
    months_paid: int
    gross_paise: int
    first_month: str                 # YYYY-MM
    esi_contributed_earlier: Optional[bool]


def applies(position: Mapping[str, Any], month: str) -> bool:
    """A position describes the months BEFORE `first_month_here`, so it counts only for a run month on or after it: a run
    back-dated before the first month must not be credited with deductions made after it."""
    return str(position.get("first_month_here"))[:7] <= month[:7]


def as_opening(position: Mapping[str, Any]) -> Opening:
    return Opening(int(position.get("tds_paise") or 0), int(position.get("months_paid") or 0),
                   int(position.get("gross_paise") or 0), str(position.get("first_month_here"))[:7],
                   position.get("esi_contributed_earlier_in_period"))


def add_to_ytd(ytd: dict, openings: Mapping[str, Opening]) -> dict:
    """`_tds_already_deducted_this_fy`'s {employee: (tds, months, gross)} with each opening added on."""
    out = dict(ytd)
    for emp, o in openings.items():
        tds, months, gross = out.get(emp, (0, 0, 0))
        out[emp] = (tds + o.tds_paise, months + o.months_paid, gross + o.gross_paise)
    return out


def gap_sentence(name: str, month: str) -> str:
    return (f"{name}: no earlier payroll for this financial year is on file here and no opening position is recorded, so the "
            f"{month} run spreads the year's tax as if nothing had been paid or withheld before it. If {name} was paid earlier "
            f"in the year elsewhere, record what was paid and withheld (Payroll, Opening positions); a figure the old system "
            f"holds is a fact, an estimate is not. This product does not know it was not.")


def unread_sentence(name: str, month: str) -> str:
    return (f"{name}: this financial year's earlier payroll months or its opening positions could not be read, so the {month} "
            f"run spreads the year's tax as if nothing had been paid or withheld before it, and that may not be so. Recompute "
            f"the run once they can be read; this is a failed read, not a finding that nothing is on file.")
