"""
Single source of truth for "the current date/time in India" (IST, UTC+5:30).

This backend has no server-level timezone pinning — it deploys on a plain
python:3.11-slim container (see Dockerfile), which defaults to UTC. Any
business-relevant "today" resolved via a bare `date.today()` or
`datetime.now(timezone.utc)` silently disagrees with the true IST calendar
date for the ~5.5 hours daily where IST has already crossed into a new day
but UTC has not (IST 00:00-05:29 = UTC 18:30-23:59 the previous day). For
statutory dates (invoice/receipt/journal dates, financial-year boundaries),
that disagreement can misfile a real transaction into the wrong FY.

Use ist_today() / ist_now() anywhere "today" needs to reflect the CA's actual
calendar day, not the server's. Mirrors the IST-aware pattern already used
correctly in jobs/scheduler.py (BackgroundScheduler(timezone="Asia/Kolkata"),
_compute_next_run, _past_scheduled_hour).
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def ist_now() -> datetime:
    """The current instant, expressed in IST (timezone-aware)."""
    return datetime.now(IST)


def ist_today() -> date:
    """The current calendar date in IST — the safe replacement for a bare
    date.today() / datetime.now(timezone.utc).date() wherever the result
    represents a CA's "today", not a server log timestamp."""
    return ist_now().date()
