"""Whether an engagement letter is past its expiry date, and the status a screen shows because of it (POST-A-106).

THE RULE THIS HOLDS: A LETTER THAT HAS GONE PAST ITS DATE IS SHOWN AS EXPIRED, BECAUSE NOTHING WRITES THE WORD.
The status vocabulary of an engagement letter has always included "Expired", and no code has ever written it: a letter past its
`expiry_date` kept the stored status "Sent" in the staff list for as long as nobody touched it, while the public signing page (which
asks the date, not the status) already refused it. Two screens described one letter in two ways. The answer is the one the overdue
obligation took (`docs/design-record/filing-and-compliance.md`): the stored status is a record of what a PERSON did (generated, sent,
viewed, signed, rejected), and "expired" is a fact about the calendar, so it is derived on every read from the date and not stored. A
sweep that wrote it would need a second claim on the row, would race a signature, and would be wrong for the hours between a letter's
last day and the sweep.

WHAT IS EXPIRED. Only a letter still waiting on the client: `Sent` or `Viewed`. A signed letter, a rejected one, a draft and a
generated-but-unsent one are not "expired" by their date: the first two are finished, and a draft has not been offered to anybody
whose time could run out. The day itself is the last day it may be signed (the date is inclusive), and today is the Indian day.

Statutory note: none. A letter of engagement is a contract, and nothing here decides the date.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from core.ist_clock import ist_today

EXPIRED = "Expired"
#: The stored statuses of a letter that is waiting for the client, and so the only ones a date can expire.
WAITING_ON_THE_CLIENT = ("Sent", "Viewed")


def is_past_expiry(expiry_date: object, today: Optional[date] = None) -> bool:
    """True when the letter's last day is before `today` (the Indian day). A letter with no date, or a date that cannot be read, never
    expires: guessing a date out of text that is not one would expire a letter nobody meant to expire."""
    if not expiry_date:
        return False
    try:
        last_day = date.fromisoformat(str(expiry_date)[:10])
    except ValueError:
        return False
    return (today or ist_today()) > last_day


def displayed_status(status: object, expiry_date: object, today: Optional[date] = None) -> str:
    """The status a screen shows: "Expired" for a letter still waiting on the client whose last day has passed, otherwise the stored
    status exactly as it is. An unknown stored status is passed through, never replaced."""
    stored = status if isinstance(status, str) else ""
    if stored in WAITING_ON_THE_CLIENT and is_past_expiry(expiry_date, today):
        return EXPIRED
    return stored


def present(engagement: dict, today: Optional[date] = None) -> dict:
    """The letter as a screen is served it: the stored row plus `displayed_status`. The stored `status` is untouched, because the actions
    (resend, copy the link, mark signed) are about what was stored and not about the calendar."""
    return {**engagement, "displayed_status": displayed_status(engagement.get("status"), engagement.get("expiry_date"), today)}


__all__ = ["EXPIRED", "WAITING_ON_THE_CLIENT", "displayed_status", "is_past_expiry", "present"]
