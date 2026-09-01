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


def fy_bounds(fy_label: str) -> tuple[str, str]:
    """('2026-04-01', '2027-03-31') for '2026-27'.

    Pure: raises ValueError for anything that is not a financial-year label. The
    API layer turns that into a 422 (services/ratio_analysis_service.fy_bounds);
    the domain layer needs the dates without knowing what HTTP is.

    The Indian financial year runs 1 April to 31 March, so both bounds are month
    boundaries — which is what lets a whole year be read from the monthly
    passbook buckets with no partial edge month.
    """
    try:
        start_year = int(str(fy_label).split("-")[0])
    except (ValueError, IndexError, AttributeError):
        raise ValueError(f"fy must look like '2026-27', got {fy_label!r}")
    if not (1900 <= start_year <= 2999):
        raise ValueError(f"fy must look like '2026-27', got {fy_label!r}")
    return f"{start_year}-04-01", f"{start_year + 1}-03-31"


def preceding_fy(fy_label: str) -> str:
    """'2025-26' for '2026-27'."""
    start_year = int(str(fy_label).split("-")[0]) - 1
    return f"{start_year}-{str(start_year + 1)[2:]}"


def ist_fy_label(d: date | None = None) -> str:
    """Indian FY label ('YYYY-YY') for the given date, defaulting to the
    current IST calendar date. FY runs 1 April - 31 March. Consolidates what
    were previously independent, identical implementations in
    services/compliance_obligation_service.py and
    domain/income_tax/statutory_rates.py."""
    d = d or ist_today()
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[2:]}"
