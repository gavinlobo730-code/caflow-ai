"""One financial-year label type, for every place a label enters the API.

WHY THIS EXISTS
    An Indian financial year is written '2026-27'. Fifty-six route parameters
    and request-model fields took one as a bare `str`, and every one of them
    passed it to code that reads the FIRST FOUR CHARACTERS and ignores the
    rest (core.ist_clock.fy_bounds, and the several private _parse_fy helpers
    that predate it). So:

      * '2026-28' and '2026-99' were accepted and silently meant 2026-27 —
        a label naming a year that does not exist, stored on the row and
        shown back to the CA as confirmation;
      * '2026' was accepted and meant 2026-27 too;
      * 'garbage' raised ValueError out of the domain layer and reached the
        CA as a 500.

    One endpoint had a shape regex (^\\d{4}-\\d{2}$), which '2026-28' passes.
    The walkthrough that found this asked for 2025-26 four times and generated
    2026-27 without a word.

WHY A TYPE AND NOT FIFTY-SIX CHECKS
    Fifty-six hand-written checks are fifty-six chances to miss one, and they
    drift. This is the annotation, so a new endpoint gets the rule by writing
    `fy: FYLabel` — and tests/test_fy_labels_are_validated.py fails if a new
    one goes in as a bare `str`.

WHY IT CANONICALISES
    '2026-2027' unambiguously means the same year, and a CA writes both. But
    two spellings of one year read as two years once they are STORED and then
    filtered on: a write of '2026-2027' followed by a read of '2026-27' finds
    nothing, and an empty list looks like an answer. So the label is
    normalised on the way in, at both ends.

    Verified before this was written: all 38 financial-year columns on
    production hold canonical YYYY-YY values already, so normalising a read
    cannot fail to match an existing row.
"""
from typing import Annotated, Optional

from pydantic import BeforeValidator

from core.ist_clock import normalise_fy_label


def _required_fy(value):
    """Raises ValueError, which FastAPI renders as a 422 naming the field."""
    return normalise_fy_label(value)


def _optional_fy(value):
    # An absent optional parameter is None, and `?fy=` is the same statement
    # with more typing — the caller named no year. A REQUIRED label gets no
    # such latitude: there, '' is a missing answer, not an unasked question.
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return normalise_fy_label(value)


#: A financial-year label that must be present: '2026-27'.
FYLabel = Annotated[str, BeforeValidator(_required_fy)]

#: The same, where the caller may say nothing at all.
OptionalFYLabel = Annotated[Optional[str], BeforeValidator(_optional_fy)]
