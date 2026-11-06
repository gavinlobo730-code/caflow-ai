"""One rule for "this text is a calendar date written YYYY-MM-DD", for a request model that still takes a date as text (POST-A-380).

WHAT WAS WRONG
    A request model that types a date as a bare `str` hands whatever a caller sent to a DATE column or to a date parser, and a caller that is not
    the screen (an import, a script, a hand-made request) gets a 500 with no sentence. The browser drive of the date boxes (PRE-A-015) met it model
    by model and each was fixed with its own private copy of the same four lines. This is the one copy: a model's `field_validator` calls it, and
    the sentence names the field the caller sent.

WHAT IT IS NOT
    `a_real_date` judges only that the text is a real day. Whether a day may be in the future, before a period, or outside a year is the door's own rule
    (`domain.compliance_record_service.clean_filed_date` for a filing, the period lock for a posting), and it is asked after this.
    `date.fromisoformat` also reads the compact forms (`20261101`, `2026-W44-1`); the value returned is the canonical `YYYY-MM-DD`, so what is
    stored is not the compact text.

    `a_day_that_has_happened` is the one further question several doors share and nothing more: a day a bank, a portal, a customs office or a counterparty printed is a real day and is not after
    today in India, because it is a thing that has happened by the time it is recorded (the Form 15CA date, the shipping bill date, the no-PE declaration date). How far back such a day may
    go is still the door's own rule, and no statutory reading is assumed here.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from core.ist_clock import ist_today


def a_real_date(value: object, name: str) -> str:
    """The canonical YYYY-MM-DD of `value`, or a ValueError whose message is the sentence a person is shown (a Pydantic validator turns it into a 422)."""
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError:
        raise ValueError(f"{name} must be a date written YYYY-MM-DD.") from None


def a_day_that_has_happened(value: Optional[str], name: str, sentence: str, *, a_blank_is_no_date: bool) -> Optional[str]:
    """A day a portal, a bank or a counterparty printed, or None when it is not stated (PRE-A-015, sixteenth and eighteenth slices): a real day, kept as the canonical YYYY-MM-DD, and not
    after today in India, because it is a thing that has happened by the time it is recorded. `sentence` is what a person is shown for a later day. A blank is no date where
    `a_blank_is_no_date` (a new document) and is REFUSED where it is not (a PATCH, which the route reads without what was not sent: a blank read as absent would be dropped and a success
    reported for a date that was not cleared). How far back it may go is the door's own rule, not this one's."""
    if value is None or (a_blank_is_no_date and str(value).strip() == ""):
        return None
    day = a_real_date(value, name)
    if day > ist_today().isoformat():
        raise ValueError(sentence)
    return day
