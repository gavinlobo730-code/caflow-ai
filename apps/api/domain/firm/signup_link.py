"""The rules of a sign-up link: who may ask for one and how often, how long it lives, and what a typed name may be (POST-A-485, 497).

A sign-up link used to be the sign-in library's own emailed one-time link. The first opener won and every other opener was refused: a mail
scanner that opens links before the person does, a second click, the link opened on a phone after the laptop. And what the link MEANT ("a
NEW practice, not the existing one this address belongs to") lived in a note in the browser that had sent the form, so the link opened in
another browser entered the practice silently. The server keeps the link now, the way it keeps a staff invitation
(`domain/firm/invite_token`, `services/staff_invite_service`): this module is the part of that which needs no database and no clock of its
own, so each rule is a function a test can call with a date.

THE NUMBERS ARE ENGINEERING CHOICES, NOT STATUTORY ONES. Nothing here is a rate, a threshold or a period an Act sets; each was chosen for
the person and is said on the screen and in the mail, so a change is one edit here and the words follow:

  * the link lives 24 hours. A person who fills in the form and is called away comes back the next morning; the library's own link lasted
    an hour. It is also removed the moment the practice is created, so it never outlives its purpose by a day;
  * one address may ask again after 30 seconds (the sign-up page's own wait), and at most 5 times in an hour. Each request REPLACES the
    previous link, so an address that is asked for over and over (by a stranger who typed it in the form) is mailed a handful of times
    an hour, and only the latest link works.

WHAT THE FIRM AND PERSON NAMES ARE. They are what a stranger typed into a public form and they are mailed to a third party, so they are
cleaned (control characters out, runs of space folded) and bounded; the mail escapes them (`services/email_service`), and says it was
asked for by whoever typed the address, so a link for a firm name nobody chose is ignorable.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

#: How long a link can be used, from the moment it was last mailed.
LINK_LIFETIME = timedelta(hours=24)

#: The least time between two mails to one address.
COOLDOWN_SECONDS = 30

#: The most mails to one address in one window, and the window.
HOURLY_CAP = 5
WINDOW = timedelta(hours=1)

#: How long a typed name may be. `firms.name` carries no limit of its own; a screen heading does.
NAME_MAX = 100

_SPACES = re.compile(r"\s+")
#: The two joiners some scripts need INSIDE a word. Every other format character (a bidirectional override, a zero-width space, a byte-order
#: mark) is removed, because it shows nothing and can only reorder or hide what is around it.
_JOINERS = frozenset("\u200c\u200d")
#: A web or email address typed where a name goes. A name is never one, and this is a public form that mails a stranger: the text it carries is
#: the one thing in that mail that is not ours.
_AN_ADDRESS = re.compile(r"(?i)(https?\s*:|://|\bwww\s*\.|@)")


def normalise_email(value: Any) -> str:
    """The address as it is kept and compared: trimmed and lower-cased. An address is not case-sensitive for this purpose, and the table
    holds one row per address."""
    return str(value or "").strip().lower()


def clean_name(value: Any, what: str) -> str:
    """A typed firm or person name, cleaned. Raises `ValueError` with a sentence naming `what` when nothing visible is left, it is too long or it is
    a web or email address.

    Control characters and line breaks become a space (they have no place in a name and can reshape a mail), invisible format characters go
    (except the two joiners a script may need), and runs of space become one. Nothing else is removed: a name is typed text and is escaped where
    it is shown, never stripped of the letters, digits and marks a real name has. A name made only of invisible characters is blank: the
    database would accept it as text, and the page would then read "Continue setting up " with nothing after it."""
    kept = []
    for ch in str(value or ""):
        category = unicodedata.category(ch)
        if category in ("Cc", "Zl", "Zp"):
            kept.append(" ")
        elif category == "Cf" and ch not in _JOINERS:
            continue
        else:
            kept.append(ch)
    text = _SPACES.sub(" ", "".join(kept)).strip()
    if not any(unicodedata.category(ch)[0] in ("L", "N", "P", "S", "M") for ch in text):
        raise ValueError(f"Please enter {what}.")
    if len(text) > NAME_MAX:
        raise ValueError(f"{what[0].upper()}{what[1:]} is too long: please keep it to {NAME_MAX} characters or fewer.")
    if _AN_ADDRESS.search(text):
        raise ValueError(f"That looks like a web or email address. Please enter {what}.")
    return text


def as_instant(value: Any) -> Optional[datetime]:
    """A stored timestamp as an aware instant (PostgREST answers ISO text, with a `Z` or an offset); None when it cannot be read."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        # Not a timestamp. A timestamptz column always reads back as ISO text, so a stored instant never lands here: this is an absent value or a
        # hand-built one, and None says there is no instant.
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def expires_at(now: datetime) -> datetime:
    """When a link mailed at `now` stops working."""
    return now + LINK_LIFETIME


def is_live(row: Optional[Mapping[str, Any]], now: datetime) -> bool:
    """Whether a stored link can still be used: it exists and its expiry is in the future. An expiry that cannot be read is NOT live: a
    link whose end nobody can say is not one to sign somebody in with."""
    if not row:
        return False
    end = as_instant(row.get("expires_at"))
    return end is not None and end > now


@dataclass(frozen=True)
class Allowance:
    """Whether an address may be mailed another link now, and the counters to store if so."""
    ok: bool
    #: When not ok, whole seconds until it would be (never below 1); 0 when ok.
    wait_seconds: int = 0
    #: When not ok, which rule said so: "cooldown" or "hourly".
    reason: str = ""
    #: When ok, what the row's counters become.
    send_count: int = 1
    window_started_at: Optional[datetime] = None


def allowance(existing: Optional[Mapping[str, Any]], now: datetime) -> Allowance:
    """May this address be mailed another link at `now`, given the row it already has (None when it has none)?

    The row is what survives a restart, which an in-process counter does not. A row whose stamps cannot be read is treated as a
    first request: damping is for the person's benefit, and refusing a person because of an unreadable stamp would lock them out of
    their own sign-up."""
    if not existing:
        return Allowance(True, send_count=1, window_started_at=now)
    sent = as_instant(existing.get("sent_at"))
    if sent is not None:
        waited = (now - sent).total_seconds()
        # A stamp in the FUTURE is a request another worker has just made (its clock was read a moment after ours): that is a request just made.
        if waited < COOLDOWN_SECONDS:
            return Allowance(False, max(1, math.ceil(COOLDOWN_SECONDS - max(waited, 0))), "cooldown")
    window_start = as_instant(existing.get("window_started_at"))
    if window_start is None or now - window_start >= WINDOW:
        return Allowance(True, send_count=1, window_started_at=now)
    count = int(existing.get("send_count") or 0)
    if count >= HOURLY_CAP:
        return Allowance(False, max(1, math.ceil((window_start + WINDOW - now).total_seconds())), "hourly")
    return Allowance(True, send_count=count + 1, window_started_at=window_start)


def refusal_sentence(a: Allowance) -> str:
    """What the sign-up page says when `allowance` refused, in a person's words and with the wait."""
    if a.reason == "cooldown":
        return (f"A link was sent to this address a moment ago. Please wait {a.wait_seconds} "
                f"second{'s' if a.wait_seconds != 1 else ''} before asking for another.")
    minutes = max(1, math.ceil(a.wait_seconds / 60))
    return (f"A link has already been sent to this address {HOURLY_CAP} times in the last hour, so no more will be sent for now. "
            f"Please use the latest one in the inbox (check the spam folder too), or try again in about "
            f"{minutes} minute{'s' if minutes != 1 else ''}.")
