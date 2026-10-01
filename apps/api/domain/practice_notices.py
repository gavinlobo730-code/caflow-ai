"""Which of the practice's own mail a person gets, and when a sweep may send it
again — the rule, and nothing else (practice_management-02 and -03).

WHAT WAS WRONG

    `services/email_service.py` held four notices for the practice's own staff —
    task assigned, task overdue, compliance due soon, escalation — and NOTHING
    CALLED ANY OF THEM. A client's portal message and a new document request
    recorded a row and told nobody. The escalation sweeps wrote in-app
    notifications only, so a preparer who was away from the screen never heard
    that a GSTR-3B was due in three days.

    Sending them is the easy half. Mail nobody can switch off is the mail a
    practice learns to filter away, and a sweep that re-sends every morning for
    forty-one days (apex-overview-practice-06 found exactly that for the in-app
    notification) turns a deadline reminder into noise.

WHAT THIS MODULE DECIDES

  * the VOCABULARY of events a person can switch email on or off for, and each
    event's DEFAULT. The vocabulary lives here and not in a CHECK, for the
    reason `core.permissions` holds the permission vocabulary: SQL cannot read a
    Python dict, and a hand-copied list in a migration is a second authority.
  * whether a person wants a mail, given the rows they have written. NO ROW MEANS
    THE EVENT'S OWN DEFAULT (migration 403's three states, for the same reason:
    a two-state control could never hand a choice back).
  * the DEDUPE KEY of a sweep mail, so "an immediate re-run of the sweep sends
    none" is a property of a key and not of whoever remembered to check.
  * the CADENCE of an overdue reminder — weekly, the same rhythm
    `compliance_obligation_service.escalate` already uses for an overdue
    obligation, and for the same reason.

WHAT IT DELIBERATELY DOES NOT DO

  * It never decides who a mail is FROM. A mail to staff goes from the product's
    own sender exactly as before; a mail to a client's portal contact about the
    practice's own work names the practice (`email_service` and
    `practice_mail_service`), and nothing here mixes the two.
  * It is not consulted for a mail to a CLIENT CONTACT. A client has no
    preference screen, and a document request somebody asked for is not
    something to default off.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Mapping, Optional

#: Events a STAFF member can switch email on or off for, with the sentence the
#: preferences screen shows and the default. Order is display order.
EVENTS: dict[str, dict] = {
    "task_assigned": {
        "label": "A task is assigned to me",
        "description": "One mail when somebody else assigns or reassigns a task to you.",
        "default_email": True,
    },
    "task_overdue": {
        "label": "A task assigned to me is overdue",
        "description": "One mail listing your overdue tasks, then a reminder each week while they stay open.",
        "default_email": True,
    },
    "compliance_deadline": {
        "label": "A deadline I prepare or review is 7, 3 or 1 day away, or overdue",
        "description": "One mail per sweep listing every obligation that reached one of those points.",
        "default_email": True,
    },
    "escalation": {
        "label": "A task escalates to me as a manager",
        "description": "One mail per sweep listing the tasks your firm's escalation rules sent you.",
        "default_email": True,
    },
    "portal_message": {
        "label": "A client writes to me on the portal",
        "description": "At most one mail per client per day, however many messages they send.",
        "default_email": True,
    },
}

EVENT_TYPES: tuple[str, ...] = tuple(EVENTS)

#: Events whose recipient is a CLIENT's portal contact. They take no preference
#: and are logged beside the staff ones; named here so the log's vocabulary is
#: one list rather than two string literals in two services.
CLIENT_NOTICE_EVENTS: tuple[str, ...] = (
    "document_request_notice",
    "portal_message_notice",
)

#: An overdue reminder repeats at most this often. Seven, because the
#: obligation escalator already waits seven days between overdue
#: notifications (apex-overview-practice-06) and two cadences for one fact is
#: how a task and its obligation come to disagree about when the nagging stops.
OVERDUE_RENOTIFY_DAYS = 7

#: The notification TYPE (public.notifications.type) a client's portal message
#: raises. Migration 450 added it to the CHECK; a test asserts the two agree.
PORTAL_MESSAGE_NOTIFICATION_TYPE = "portal_message"


def is_known_event(event_type: object) -> bool:
    return isinstance(event_type, str) and event_type in EVENTS


def default_email(event_type: str) -> bool:
    """The event's own answer when the person has recorded none. An UNKNOWN
    event answers False: a mail nobody has defined is not one to send."""
    return bool(EVENTS.get(event_type, {}).get("default_email", False))


def wants_email(event_type: str, chosen: Optional[Mapping[str, bool]]) -> bool:
    """Whether this person should be mailed about this event.

    `chosen` is the person's explicit rows only — `{event_type: email_enabled}`.
    A row they wrote wins; an absent one falls to the default; and an event
    outside the vocabulary is never mailed, whatever a row says, so a row
    written under an older vocabulary cannot switch on a mail somebody adds
    later (`user_permissions`' rule for an unrecognised pair).
    """
    if not is_known_event(event_type):
        return False
    if chosen and event_type in chosen and isinstance(chosen[event_type], bool):
        return chosen[event_type]
    return default_email(event_type)


def effective_preferences(chosen: Optional[Mapping[str, bool]]) -> list[dict]:
    """Every event with what the person gets and WHETHER THEY CHOSE IT, because
    showing only the effect makes an inherited default and a deliberate choice
    look identical (migration 403's own argument for three maps)."""
    out = []
    for event_type, meta in EVENTS.items():
        explicit = bool(chosen) and event_type in chosen and isinstance(chosen[event_type], bool)
        out.append({
            "event_type": event_type,
            "label": meta["label"],
            "description": meta["description"],
            "email_enabled": wants_email(event_type, chosen),
            "is_default": not explicit,
            "default_email": bool(meta["default_email"]),
        })
    return out


def dedupe_key(event_type: str, recipient_email: str, ref_id: str,
               tier: Optional[str], day: date) -> str:
    """The identity of one sweep mail: this event, to this address, about this
    thing, at this tier, FOR this day.

    The ADDRESS and not the user id, so a mail to a client's contact and one to
    a staff member who happens to share an address are two different mails and a
    changed address is not mistaken for an old one. Lower-cased and stripped,
    because `Ca@Firm.in` and `ca@firm.in` are one inbox.
    """
    return "|".join([
        event_type,
        (recipient_email or "").strip().lower(),
        str(ref_id),
        tier or "",
        day.isoformat(),
    ])


def _as_date(value: object) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def overdue_reminder_is_due(last_sent_for: object, today: date) -> bool:
    """Whether an overdue item may be mailed about again today.

    Never mailed -> yes. Mailed on day D -> not again until D + 7. A last-sent
    value that cannot be read is treated as NEVER mailed, which errs toward one
    extra reminder and never toward silence about an overdue deadline.
    """
    last = _as_date(last_sent_for)
    if last is None:
        return True
    return (today - last).days >= OVERDUE_RENOTIFY_DAYS


def latest(dates: Iterable[object]) -> Optional[date]:
    """The most recent readable date among `dates`, or None."""
    best: Optional[date] = None
    for raw in dates:
        d = _as_date(raw)
        if d is not None and (best is None or d > best):
            best = d
    return best
