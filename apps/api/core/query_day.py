"""A day a caller names in a query string, judged at the door (POST-A-380, the manual-run `as_of`, the journal's `occurrence` and the late-interest preview's `as_of`).

WHAT WAS WRONG
    Four doors took their day as a bare query string and handed it to the date parser, so `?as_of=soon` was a 500 with no sentence for a script: the recurring purchase bills' manual
    runs and the recurring journals' (`run` and "generate one occurrence"). The fee billing's two (`preview-run` and `run`) never reached a parser: the service compared the raw text with each
    schedule's stored day, so any text that sorts after a digit made EVERY schedule due and `run` drafted invoices for schedules not due for months, with a 200. The late-interest preview carried a
    pattern of four digits, two and two, which admits `2026-02-30`, and answered 500. The screens send a real day, or nothing. The recurring invoices' pair had already been fixed with a private
    copy of these few lines; this is the one copy.

WHAT IT DOES
    Nothing or a blank is NO DAY (the service's own default for that door: today for the runs and previews; for the journal's one occurrence, the template's own next day). Anything else must be
    a real calendar day written YYYY-MM-DD, kept in its canonical form (a padded or compact date is stored as the day); text that is not one is a 422 naming the query parameter. That includes
    a day with a time after it (`2026-07-01T10:00:00`), which the recurrence reader and the billing comparison used to take by its first ten characters and which the recurring invoices' pair
    already refused. A route calls it AFTER the caller's access to what the route acts on has been asked (a template or a client that is not theirs is a 404 before any day is judged:
    `tests/test_recurring_client_scope.py` holds that order for the recurring invoices and `tests/test_a_manual_run_names_a_real_day_and_the_callers_access_is_asked_first.py` for the rest), so a
    refusal never tells a caller anything the access check would not. It judges only that the text is a day. Whether that day may be in the future is the service's own rule.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from models.iso_date import a_real_date


def query_day(value: Optional[str], name: str) -> Optional[str]:
    """The canonical day named by a query parameter, None when none was named, a 422 (naming `name`) when the text is not a day."""
    if value is None or not str(value).strip():
        return None
    try:
        return a_real_date(value, name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
