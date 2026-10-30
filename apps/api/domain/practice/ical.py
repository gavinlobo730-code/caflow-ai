"""The compliance calendar as an iCalendar (RFC 5545) file a CA can put in Outlook, Google Calendar or a phone (POST-A-142).

WHAT THIS IS, AND WHAT IT IS NOT

    A FILE OF DUE DATES, one all-day event per obligation, built from the rows the obligation calendar already serves. It holds no
    rule of its own: the due date is the one `compliance_records` holds (`services/compliance_engine` computed it), the status is the
    stored workflow state, and nothing here decides whether anything is late. It files nothing, transmits nothing and is not a
    reminder service: a calendar application pulls the file and does what it does with it.

    # CA REVIEW REQUIRED, DO NOT AUTO-SUBMIT. The description of every event says so in words, because the event is read in an
    # application that does not know where it came from.

THE FORMAT, AND THE THREE THINGS A HAND-WRITTEN FILE GETS WRONG

    * LINES END IN CRLF, and a content line is at most 75 OCTETS, folded by a CRLF and one space. Octets and not characters: a
      client's name in Devanagari is three bytes a character, and a fold in the middle of one is a corrupt file that some
      applications drop without a word. The fold never splits a UTF-8 sequence.
    * TEXT IS ESCAPED: a backslash, a semicolon and a comma are each preceded by a backslash and a line break is written as the two
      characters `\\n`. A client called "Rao, Rao & Sons; Traders" otherwise becomes three properties.
    * AN ALL-DAY EVENT IS A DATE, NOT AN INSTANT: `DTSTART;VALUE=DATE:20261020` with `DTEND` the NEXT day (the end of a date range is
      exclusive). No time zone is written, so an obligation due on the 20th is on the 20th in every zone; a time of "midnight UTC"
      would put it on the 19th or the 21st for a phone in another country.

WHAT MAKES AN EVENT THE SAME EVENT ON THE NEXT DOWNLOAD

    `UID` is derived from the obligation's id and nothing else, so importing the file twice updates the events rather than doubling
    them, and a due date that moved (a notification extended it) moves the event. `DTSTAMP` is handed in by the caller: this module
    reads no clock.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

#: Written into every calendar so a person who finds the file knows where it came from.
PRODID = "-//PracticeSync//Compliance calendar//EN"
#: The most octets on a content line before it is folded (RFC 5545 section 3.1).
FOLD_AT = 75
CRLF = "\r\n"
#: A UID is `<id>@<this>`: the right-hand side only has to be stable and unlikely to collide with another program's.
UID_DOMAIN = "obligation.practicesync"
NOT_A_FILING = "Due date as held on the compliance calendar. This is not a filing and nothing has been submitted."


@dataclass(frozen=True)
class Obligation:
    """One obligation as the file needs it. `day` is the due date; `status` is the stored workflow word, printed and not judged."""

    id: str
    day: date
    title: str
    client_name: Optional[str] = None
    status: Optional[str] = None
    period: Optional[str] = None
    kind: Optional[str] = None


def escape_text(value: str) -> str:
    """A TEXT value (RFC 5545 section 3.3.11): backslash, semicolon and comma are escaped and a line break is `\\n`."""
    out = str(value).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return out.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def fold(line: str) -> str:
    """The content line folded at 75 octets, each continuation starting with one space, never inside a UTF-8 sequence."""
    if len(line.encode("utf-8")) <= FOLD_AT:
        return line
    parts: list[str] = []
    current = ""
    budget = FOLD_AT
    for ch in line:
        size = len(ch.encode("utf-8"))
        if len(current.encode("utf-8")) + size > budget:
            parts.append(current)
            current = ""
            budget = FOLD_AT - 1                    # the leading space of a continuation line counts
        current += ch
    parts.append(current)
    return (CRLF + " ").join(parts)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _summary(o: Obligation) -> str:
    return f"{o.title} \u2013 {o.client_name}" if o.client_name else o.title


def _description(o: Obligation) -> str:
    bits = []
    if o.client_name:
        bits.append(f"Client: {o.client_name}")
    if o.period:
        bits.append(f"Period: {o.period}")
    if o.status:
        bits.append(f"Status: {o.status}")
    bits.append(NOT_A_FILING)
    return "\n".join(bits)


def _event(o: Obligation, stamp: str) -> list[str]:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{o.id}@{UID_DOMAIN}",
        f"DTSTAMP:{stamp}",
        f"DTSTART;VALUE=DATE:{o.day.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{(o.day + timedelta(days=1)).strftime('%Y%m%d')}",
        f"SUMMARY:{escape_text(_summary(o))}",
        f"DESCRIPTION:{escape_text(_description(o))}",
    ]
    if o.kind:
        lines.append(f"CATEGORIES:{escape_text(o.kind)}")
    # An all-day obligation does not make a person busy. STATUS is always CONFIRMED: the calendar's STATUS vocabulary (tentative,
    # confirmed, cancelled) is about whether the EVENT happens, and a filed obligation has not been cancelled; the workflow word is in
    # the description, where it is read as what it is.
    lines.append("TRANSP:TRANSPARENT")
    lines.append("STATUS:CONFIRMED")
    lines.append("END:VEVENT")
    return lines


def build_calendar(obligations: Iterable[Obligation], *, now: datetime, name: str = "Compliance calendar",
                   description: Optional[str] = None) -> str:
    """The whole file. `now` is the instant of the download (every event's DTSTAMP); the caller supplies it."""
    stamp = _stamp(now)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_text(name)}",
    ]
    if description:
        lines.append(f"X-WR-CALDESC:{escape_text(description)}")
    for o in obligations:
        lines.extend(_event(o, stamp))
    lines.append("END:VCALENDAR")
    return CRLF.join(fold(line) for line in lines) + CRLF


def _day_of(value) -> Optional[date]:
    """The due date a row holds, or None when it holds none a calendar can use."""
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def from_rows(rows: Iterable[dict], client_names: dict, *, now: datetime) -> str:
    """The file for the obligation rows the calendar serves. A row with no usable due date cannot be placed on a calendar: it is
    left out and the file's description says how many were, so a missing event is never read as nothing being due."""
    obligations: list[Obligation] = []
    skipped = 0
    for r in rows:
        day = _day_of(r.get("due_date"))
        if day is None or not r.get("id"):
            skipped += 1
            continue
        obligations.append(Obligation(
            id=str(r["id"]), day=day,
            title=str(r.get("period_label") or r.get("obligation_type") or r.get("compliance_type") or "Compliance obligation"),
            client_name=client_names.get(str(r.get("client_id") or "")),
            status=r.get("status") or None, period=None,
            kind=r.get("compliance_type") or None))
    obligations.sort(key=lambda o: (o.day, o.title, o.id))
    note = (f"{skipped} obligation{'s' if skipped != 1 else ''} with no due date {'are' if skipped != 1 else 'is'} not in this file."
            if skipped else None)
    return build_calendar(obligations, now=now, description=note)
