"""One GST return-period type, for every place a period enters the API.

WHY THIS EXISTS
    A GST return period is written MMYYYY ('042026'). 27 route parameters and request-model fields took one as a plain string
    (four query parameters with `pattern=r"^\\d{6}$"`, which '139999' and '000000' satisfy), and what became of a malformed
    one depended on the door:

      * where the value reached `domain/gst/return_period.parse_month` (the computing and saving doors), '2026-04',
        '4/2026' and 'april' raised ValueError out of the domain layer and reached the CA as a 500 with a traceback in the
        log (found by filing a seeded year through the workspace doors, 19-10-2026);
      * '139999' (a month 13) passed the shape regex on the four routes that had one and then raised the same way;
      * '010000' was accepted as the first month of year zero and failed later, when a date was built from it
        (`iff/compute?period=010000` answered 500 on a real stack);
      * where the value was only used as a key it was not checked at all: `itc/register?period=2026-04` answered 200 with an
        empty register, and on the two ITC reversal bodies nothing looked at it until the register table's own CHECK
        (migration 285) refused the insert, after the journal and the amounts had been read.

    This is the same family as `FYLabel` / `AYLabel` (models/fy.py), for the same reason: the SHAPE is not the rule. The rule
    is the one `parse_month` has always applied (six digits, a month from 01 to 12), plus a year that is a year of this
    century, so a typo is a 422 naming the field and not a 500.

WHY A TYPE AND NOT THIRTY CHECKS
    The annotation is the rule, so a new endpoint gets it by writing `period: PeriodMMYYYY`, and
    tests/test_gst_return_periods_are_validated.py fails if a new one goes in as a bare `str`.

WHAT IT DOES NOT DO
    It does not decide whether the period is one a return can exist for, whether the registration files monthly or
    quarterly, or whether the period is in the future. `return_period.resolve` is told the frequency and answers the window;
    this only keeps a string that is not a month from reaching it. The year bounds are a sanity bound on a typo, not a
    statement of when GST began, which is a statutory fact this repository has not read from a primary source.
"""
from typing import Annotated, Optional

from pydantic import BeforeValidator

from domain.gst.return_period import parse_month

#: A year outside these is a typo for a year, not a period a return could be for. Not a statutory limit.
_FIRST_YEAR, _LAST_YEAR = 2000, 2099


def normalise_return_period(value) -> str:
    """'042026' -> '042026'; raises ValueError (rendered by FastAPI as a 422 naming the field) for anything else.

    Whitespace around the digits is trimmed, because a pasted value carries it; nothing else is repaired. A number is not
    accepted as a string of digits ('42026' as the integer 42026 has lost its leading zero, and which month it meant is
    exactly what the caller did not say)."""
    if not isinstance(value, str):
        raise ValueError("period must be MMYYYY, for example 042026")
    text = value.strip()
    # ASCII digits only. `str.isdigit` (and so `parse_month`) accepts Arabic-Indic and full-width digits, and the text is
    # STORED as the key a saved return is found under: a second spelling of April 2026 would open a second row.
    if not text.isascii():
        raise ValueError("period must be MMYYYY in ordinary digits, for example 042026")
    try:
        _month, year = parse_month(text)
    except ValueError:
        raise ValueError("period must be MMYYYY, for example 042026 for April 2026") from None
    if not _FIRST_YEAR <= year <= _LAST_YEAR:
        raise ValueError(f"period year {year:04d} is not a year a return can be for; write MMYYYY, for example 042026")
    return text


def _optional(value):
    # Absent is None and an empty string is the same statement with more typing: the caller named no period.
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return normalise_return_period(value)


#: A GST return period that must be present: '042026'.
PeriodMMYYYY = Annotated[str, BeforeValidator(normalise_return_period)]

#: The same, where the caller may say nothing at all.
OptionalPeriodMMYYYY = Annotated[Optional[str], BeforeValidator(_optional)]
