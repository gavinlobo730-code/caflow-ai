"""
Senior-citizen status for §192, and the one thing it is easy to get wrong.

WHY THIS EXISTS

Part III of the First Schedule to the Finance Act sets three basic exemptions
under the OLD regime, by age:

    under 60      Rs 2,50,000
    60 to 79      Rs 3,00,000     "senior citizen"
    80 and over   Rs 5,00,000     "very senior citizen"

`domain/income_tax/itr_engine.py::_slabs_for` has implemented all three ladders
for as long as the engine has existed, reading `is_senior_citizen` and
`is_very_senior_citizen` off the request. `domain/payroll/declarations` never set
either, because payroll held no date of birth — so an employee of 62 who
intimated the old regime was withheld on the general ladder, over-deducted every
month and refunded a year later on assessment. §192(1) makes the employer
answerable for a correct deduction.

THE TEST IS "AT ANY TIME DURING THE PREVIOUS YEAR"

Not "on 1 April", and not "on the last day". The Schedule's words are "of the
age of sixty years or more **at any time during the previous year**", so an
employee whose sixtieth birthday falls on 15 March 2027 is a senior citizen for
the WHOLE of FY 2026-27 — including the April payslip, computed eleven months
before the birthday.

Reading it as an age on a fixed date is the mistake, and it is a mistake in the
direction that costs the employee: the birthday-in-March case is exactly the one
a naive `age_on(1 April)` gets wrong, and it under-states the exemption for
someone the statute has already made senior.

CBDT has read it the same way for decades — the proviso to §139(1) and the
Explanation to §80D use the same "at any time during the previous year"
formulation, and it is why a person turning 60 in March files that year's return
as a senior citizen.

NO REGIME LOGIC HERE

Age changes nothing under the new regime — §115BAC(1A) has ONE ladder for every
individual, and Finance Act 2023 onwards it does not distinguish age at all.
This module answers only "how old were they during this year"; whether that
matters is the engine's question, and it already knows.

UNKNOWN IS NOT YOUNG

A missing date of birth returns False for both, which reproduces exactly what
payroll did before this module existed. It is NOT a claim that the employee is
under 60 — `senior_status_unknown` is what says so, and the run reports it as a
gap beside the others rather than letting a zero speak for itself.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from core.ist_clock import fy_bounds

SENIOR_AGE = 60
VERY_SENIOR_AGE = 80


def parse_dob(value) -> Optional[date]:
    """A date of birth from whatever the caller holds, or None.

    Accepts a `date`, or an ISO `YYYY-MM-DD` string (which is what PostgREST
    returns and what the import validates to). Anything else is None rather than
    an exception: this is read on the payslip path, and a malformed stored value
    must not stop a month's payroll — it becomes an unknown, which is reported.
    """
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def age_reached_during_fy(dob, fy: Optional[str]) -> Optional[int]:
    """The greatest age attained AT ANY TIME during the financial year.

    That is the age on 31 March, the last day of the previous year — because
    age only increases, the maximum over the year is the age at its end. Which
    is the whole point: it makes a March birthday count for the April payslip.
    """
    born = parse_dob(dob)
    if born is None or not fy:
        return None
    try:
        # fy_bounds returns ISO STRINGS, not dates.
        end = date.fromisoformat(fy_bounds(fy)[1])
    except (ValueError, TypeError, KeyError):
        return None
    years = end.year - born.year
    if (end.month, end.day) < (born.month, born.day):
        years -= 1
    return years if years >= 0 else None


def senior_status(dob, fy: Optional[str]) -> tuple[bool, bool]:
    """(is_senior_citizen, is_very_senior_citizen) for the First Schedule.

    Both False where the date of birth is unknown — see the module docstring:
    that is the pre-existing behaviour, not an assertion about the employee.
    Callers that need to tell the two apart use `senior_status_unknown`.
    """
    age = age_reached_during_fy(dob, fy)
    if age is None:
        return (False, False)
    # Very senior is ALSO senior in ordinary language, but the engine's
    # _slabs_for tests very_senior FIRST and falls through, so passing both is
    # correct and passing only `senior` for an 80-year-old would silently give
    # them the 60-79 ladder.
    return (age >= SENIOR_AGE, age >= VERY_SENIOR_AGE)


def senior_status_unknown(dob, fy: Optional[str]) -> bool:
    """True when the age could not be established, so the caller can report it.

    A zero for "not a senior citizen" and a zero for "we do not know" are the
    same number meaning opposite things — the mistake migration 327 fixed for
    professional tax and the LWF, in the same module.
    """
    return age_reached_during_fy(dob, fy) is None
