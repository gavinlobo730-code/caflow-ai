"""Reading the audit log — Rule 3(1) of the Companies (Accounts) Rules 2014.

SEPARATE FROM services/audit_service.py ON PURPOSE. That module is the WRITE
path — `log_event`, which appends and never raises, and whose docstring carries
the DPDP retention and redaction reasoning. This is the READ path, and it has
none of those concerns and all of the paging ones. One file doing both would
put a query cursor next to an erasure rule.

WHY THIS EXISTS

    The proviso to Rule 3(1) requires books kept in electronic mode to carry an
    EDIT LOG: every change, who made it, and when. This product writes one —
    migration 266's triggers capture journal-entry and journal-line changes,
    and services all over the backend append to `audit_log` — and until now
    almost none of it could be READ.

    `GET /api/audit` capped at 200 rows firm-wide with no date range and no
    paging, and the only screen calling it fetched those 200 and filtered them
    IN THE BROWSER. So on any firm with activity, "show me what happened in
    April" showed whatever fell inside the most recent 200 events, and there
    was no way to ask a different question. A log that cannot be queried is
    not an edit log; it is a table.

TWO THINGS THAT LOOK LIKE DETAILS AND ARE NOT

    1. A DATE IS AN IST DATE. `created_at` is `timestamptz`, stored in UTC. A
       CA asking for 10 September means 00:00–24:00 IST, which is 18:30 on the
       9th to 18:30 on the 10th in UTC. Filtering on the UTC date instead
       silently moves the window five and a half hours and drops every event
       between midnight and 05:30 IST — the quiet hours a scheduled job runs
       in. The bounds are converted here, once.

    2. PAGING MUST BREAK TIES ON THE ID. `created_at` defaults to now(), and
       now() is the TRANSACTION's timestamp — so the four line-changes of one
       journal edit all carry the SAME instant. A cursor of "created_at <
       last_seen" would drop every row sharing the last one's timestamp, which
       is exactly the multi-line edit this feature exists to show. The cursor
       is (created_at, id) and the filter is the row comparison spelled out as
       PostgREST understands it.
"""
from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime, time, timedelta
from typing import Optional

from core.ist_clock import IST

#: What a caller may ask for in one page. The screen shows far fewer; the cap
#: is here so a client cannot ask for the whole table in one request.
MAX_PAGE = 200
DEFAULT_PAGE = 50

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                   r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class AuditQueryRefused(Exception):
    """A refusal the caller reads, not a 500."""


def ist_day_bounds(date_from: Optional[str],
                   date_to: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """IST calendar dates -> the UTC instants that bracket them.

    `date_to` is INCLUSIVE of its whole day, so it becomes the start of the
    NEXT IST day: a CA asking 1–10 September expects the 10th's events, and an
    exclusive bound would silently drop a day's work.
    """
    def _parse(text: str, field: str):
        try:
            return datetime.strptime(text.strip(), "%Y-%m-%d").date()
        except (ValueError, AttributeError):
            raise AuditQueryRefused(
                f"{field} must be a date like 2026-09-10.")

    lo = hi = None
    if date_from:
        lo = datetime.combine(_parse(date_from, "date_from"), time.min, tzinfo=IST)
    if date_to:
        d = _parse(date_to, "date_to")
        hi = datetime.combine(d + timedelta(days=1), time.min, tzinfo=IST)
    if lo and hi and lo >= hi:
        raise AuditQueryRefused("The start date must not follow the end date.")
    return (lo.isoformat() if lo else None, hi.isoformat() if hi else None)


def encode_cursor(row: dict) -> str:
    """The (created_at, id) of the last row on a page.

    Opaque on purpose: a client that takes it apart starts depending on the
    ordering, and the ordering is this module's to change.
    """
    raw = f"{row.get('created_at')}|{row.get('id')}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: Optional[str]) -> Optional[tuple[str, str]]:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        created_at, _, row_id = raw.partition("|")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise AuditQueryRefused("That page cursor is not one this log issued.")
    if not created_at or not _UUID.fullmatch(row_id):
        # The id half goes into a PostgREST filter that casts to uuid. A
        # malformed one would come back as the database's error rather than
        # this module's sentence, and it is not the caller's fault that the
        # cursor is opaque.
        raise AuditQueryRefused("That page cursor is not one this log issued.")
    return created_at, row_id


def cursor_clause(cursor: tuple[str, str]) -> str:
    """The row comparison (created_at, id) < (c_at, c_id), as PostgREST reads it.

    Postgres would write this as a tuple comparison and PostgREST has no
    syntax for one, so it is spelled out: strictly earlier, OR the same instant
    and a smaller id. Dropping the second limb is what loses the other lines of
    a multi-line journal edit, which all share one transaction timestamp.
    """
    created_at, row_id = cursor
    return f"created_at.lt.{created_at},and(created_at.eq.{created_at},id.lt.{row_id})"


def entity_types(raw: Optional[str]) -> list[str]:
    """A comma list, because one question spans two types.

    "What happened to this journal entry" means both the entry's own changes
    (`journal_entry`) and its lines' (`journal_line`) — migration 266 keys the
    line rows to the PARENT entry id precisely so the two can be asked for
    together.
    """
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def clamp_limit(limit: Optional[int]) -> int:
    if limit is None:
        return DEFAULT_PAGE
    return max(1, min(int(limit), MAX_PAGE))


def query(db, firm_id: str, *, entity_type: Optional[str] = None,
          entity_id: Optional[str] = None, actor_id: Optional[str] = None,
          action: Optional[str] = None, date_from: Optional[str] = None,
          date_to: Optional[str] = None, cursor: Optional[str] = None,
          limit: Optional[int] = None) -> dict:
    """One page of the log, newest first, with the cursor for the next.

    Every filter is applied IN THE DATABASE. The screen this replaced pulled
    200 rows and filtered them in the browser, so a date range could only ever
    narrow the most recent 200 events rather than search the log.
    """
    size = clamp_limit(limit)
    lo, hi = ist_day_bounds(date_from, date_to)
    after = decode_cursor(cursor)
    types = entity_types(entity_type)

    q = (db.table("audit_log")
         .select("id, firm_id, actor_id, actor_email, entity_type, entity_id, "
                 "action, old_data, new_data, metadata, created_at")
         .eq("firm_id", firm_id))
    if len(types) == 1:
        q = q.eq("entity_type", types[0])
    elif types:
        q = q.in_("entity_type", types)
    if entity_id:
        q = q.eq("entity_id", entity_id)
    if actor_id:
        q = q.eq("actor_id", actor_id)
    if action:
        q = q.eq("action", action)
    if lo:
        q = q.gte("created_at", lo)
    if hi:
        q = q.lt("created_at", hi)
    if after:
        q = q.or_(cursor_clause(after))

    # One more than asked for, so "is there another page" is answered without
    # a second query and without a count over the whole table.
    rows = (q.order("created_at", desc=True).order("id", desc=True)
             .limit(size + 1).execute().data) or []
    has_more = len(rows) > size
    page = rows[:size]
    return {
        "entries": page,
        "next_cursor": encode_cursor(page[-1]) if (has_more and page) else None,
        "has_more": has_more,
        "limit": size,
        # NOT a total. Counting the whole log to render a page is the thing
        # this replaced; `has_more` is what a "Load more" button needs.
        "window": {"from": lo, "to": hi},
    }
