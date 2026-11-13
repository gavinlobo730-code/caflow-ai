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
from typing import Annotated, Optional

from pydantic import BeforeValidator, ValidationInfo

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


# ── The date as a TYPE (POST-A-380), in the shape of `models/fy.FYLabel` ────────────────────────────────────────────────────────────────────────────────
# A field annotated with one of these is judged by the rule above before anything else sees it, so the document's date cannot reach a period check,
# a financial-year number or a DATE column as text that is not a day. They are three because a date is asked three ways:
#
#   IsoDate          a date that must be there: the date of an invoice, a bill, a receipt, a payment. Blank and absent-as-blank are refused.
#   OptionalIsoDate  a date a NEW document may leave out (a due date the credit terms fill in): blank is no date, None is no date.
#   PatchIsoDate     a date an EDIT may leave out: None is "not sent, keep it". A blank is REFUSED, because the route reads an edit without what was not sent
#                    and would drop a blank as "nothing to change" and report a success for a date that was not cleared (the shape POST-A-399 closed on screens).
#
# Only a `str` is accepted: a before-validator runs AHEAD of Pydantic's own `str` check and `a_real_date` takes `str(value)`, so without this an integer such as
# 20261101 would be read as the compact date 2026-11-01. The value handed on is the canonical YYYY-MM-DD, so what is stored is not
# a compact `20261101` or a padded ` 2026-11-01 `. WHAT IS NOT JUDGED HERE is whether the day may be in the future, before a period or outside a year: that is the
# door's own rule (the period lock, `clean_filed_date`), asked after this. `tests/test_a_date_field_on_a_request_model_is_a_real_date_or_is_on_the_frozen_list.py`
# is the rule over the whole API: a new bare `str` date field fails it.

def _field(info: Optional[ValidationInfo]) -> str:
    return (getattr(info, "field_name", None) or "date")


def _as_text(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a date written YYYY-MM-DD.")
    return value


def _required_day(value: object, info: ValidationInfo) -> str:
    name = _field(info)
    return a_real_date(_as_text(value, name), name)


def _optional_day(value: object, info: ValidationInfo) -> Optional[str]:
    if value is None:
        return None
    name = _field(info)
    text = _as_text(value, name)
    if text.strip() == "":
        return None
    return a_real_date(text, name)


def _patch_day(value: object, info: ValidationInfo) -> Optional[str]:
    if value is None:
        return None
    name = _field(info)
    text = _as_text(value, name)
    if text.strip() == "":
        raise ValueError(f"{name} must be a date written YYYY-MM-DD. It cannot be cleared here: leave it out to keep it as it is.")
    return a_real_date(text, name)


def a_real_date_text(value: object, name: str) -> str:
    """For a date that arrives inside a body the request model does not type (a free `dict`, such as a document extraction): the same refusal the types give, called by hand.
    A non-text value is refused too, because `a_real_date` takes `str(value)` and would read the integer 20261101 as a compact date."""
    return a_real_date(_as_text(value, name), name)


#: A calendar date that must be present: '2026-07-01'.
IsoDate = Annotated[str, BeforeValidator(_required_day)]

#: A calendar date a new document may leave out (blank or absent is no date).
OptionalIsoDate = Annotated[Optional[str], BeforeValidator(_optional_day)]

#: A calendar date an edit may leave out (absent keeps the stored one; blank is refused).
PatchIsoDate = Annotated[Optional[str], BeforeValidator(_patch_day)]

#: The three, by name, for the guard that reads annotations.
DATE_TYPE_NAMES = ("IsoDate", "OptionalIsoDate", "PatchIsoDate")
