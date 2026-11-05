"""One rule for "this text is a calendar date written YYYY-MM-DD", for a request model that still takes a date as text (POST-A-380).

WHAT WAS WRONG
    A request model that types a date as a bare `str` hands whatever a caller sent to a DATE column or to a date parser, and a caller that is not
    the screen (an import, a script, a hand-made request) gets a 500 with no sentence. The browser drive of the date boxes (PRE-A-015) met it model
    by model and each was fixed with its own private copy of the same four lines. This is the one copy: a model's `field_validator` calls it, and
    the sentence names the field the caller sent.

WHAT IT IS NOT
    It judges only that the text is a real day. Whether a day may be in the future, before a period, or outside a year is the door's own rule
    (`domain.compliance_record_service.clean_filed_date` for a filing, the period lock for a posting), and it is asked after this.
    `date.fromisoformat` also reads the compact forms (`20261101`, `2026-W44-1`); the value returned is the canonical `YYYY-MM-DD`, so what is
    stored is not the compact text.
"""
from __future__ import annotations

from datetime import date


def a_real_date(value: object, name: str) -> str:
    """The canonical YYYY-MM-DD of `value`, or a ValueError whose message is the sentence a person is shown (a Pydantic validator turns it into a 422)."""
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError:
        raise ValueError(f"{name} must be a date written YYYY-MM-DD.") from None
