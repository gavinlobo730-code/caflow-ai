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
import calendar
import re
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


_FY_LABEL = re.compile(r"^\s*(\d{4})\s*[-/]\s*(\d{2}|\d{4})\s*$")


def normalise_fy_label(fy_label, *, field: str = "financial year") -> str:
    """'2026-27' from anything that unambiguously means that financial year.

    WHY THIS IS STRICTER THAN fy_bounds
        fy_bounds reads the FIRST part and ignores the rest, because the
        second half of the label carries no information the first does not.
        That is right for a domain function whose caller already knows the
        label is a label. It is wrong at an API boundary, where the string
        came off the wire: '2026', '2026-2027', '2026-28' and '2026-99' all
        parse to FY 2026-27 there, and the last two mean the caller and the
        system disagree about which year is being generated. Obligations are
        due dates a CA plans around; generating the wrong year's silently is
        worse than refusing.

    Accepts YYYY-YY and YYYY-YYYY (a CA writes both), canonicalises to
    YYYY-YY, and REFUSES anything else — including a second half that does
    not follow the first, which is the near-miss a bare prefix parse cannot
    see. Raises ValueError; the API layer turns that into a 422.
    """
    match = _FY_LABEL.match(str(fy_label or ""))
    if not match:
        raise ValueError(f"{field} must look like '2026-27', got {fy_label!r}")
    start = int(match.group(1))
    if not (1900 <= start <= 2999):
        raise ValueError(f"{field} must look like '2026-27', got {fy_label!r}")
    tail = match.group(2)
    expected = str(start + 1) if len(tail) == 4 else str(start + 1)[2:]
    if tail != expected:
        raise ValueError(
            f"{field} {fy_label!r} is not a financial year: the Indian FY runs "
            f"1 April to 31 March, so {start} pairs with "
            f"{str(start + 1)[2:]}, not {tail}.")
    return f"{start}-{str(start + 1)[2:]}"

def preceding_fy(fy_label: str) -> str:
    """'2025-26' for '2026-27'."""
    start_year = int(str(fy_label).split("-")[0]) - 1
    return f"{start_year}-{str(start_year + 1)[2:]}"


def _as_ist_date(d=None) -> date:
    """A date, a datetime, an ISO date string, or None for today in IST.

    Accepting the string is deliberate: every document date in this codebase
    arrives from PostgREST or a request body as `'2026-03-31'`, and a caller
    that has to convert first is a caller that can forget to — which is how the
    financial year came to be read off the clock instead of the document
    (SALES-24)."""
    if d is None:
        return ist_today()
    if isinstance(d, str):
        return date.fromisoformat(d[:10])
    if isinstance(d, datetime):
        return d.astimezone(IST).date() if d.tzinfo else d.date()
    return d


def ist_fy_label(d=None) -> str:
    """Indian FY label ('YYYY-YY') for the given date, defaulting to the
    current IST calendar date. FY runs 1 April - 31 March. Consolidates what
    were previously independent, identical implementations in
    services/compliance_obligation_service.py and
    domain/income_tax/statutory_rates.py."""
    d = _as_ist_date(d)
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def fy_code(d=None) -> str:
    """The FOUR-DIGIT financial-year code a document number carries: '2627' for
    FY 2026-27. Accepts a date, a datetime, an ISO date string, or None for
    today in IST.

    WHY IT TAKES A DATE (SALES-24). Six modules had a private `_current_fy()`
    reading `datetime.now(timezone.utc)`, and every one of them was used to
    build a document NUMBER — `RCPT-{fy}-0001`, `CN-{fy}-…`, `SDN-{fy}-…`,
    `PCN-{fy}-…`, `DN-{fy}-…`, `PP-{fy}-…` — while the document's own date sat
    on the line above. Year-end is when a CA keys the most documents: every
    March-dated receipt entered in April was numbered into NEXT year's series
    and sat out of order in the year it belongs to, discovered when the year's
    register was printed and the numbers did not run. The FY-lock and period
    checks used the document date correctly all along; only the number was
    wrong.

    And `timezone.utc` was the second defect in the same line. Between 00:00
    and 05:30 IST on 1 April the server is still on 31 March, so a document
    dated into the new year was numbered into the old one — the exact case
    core.ist_clock exists for.

    DERIVED FROM `ist_fy_label` rather than computed again, so the two
    spellings of one financial year cannot disagree.
    """
    label = ist_fy_label(d)          # '2026-27'
    return f"{label[2:4]}{label[5:7]}"


def month_end_date(period: str) -> str:
    """The last calendar day of a 'YYYY-MM' period, as an ISO date string.

    THE ACCOUNTING DATE OF A MONTHLY POSTING IS A PROPERTY OF THE PERIOD, NOT
    OF THE CLOCK. A payroll accrual for August belongs in August whether it is
    finalised on the 31st or a fortnight later, and `datetime.now(...).date()`
    puts it wherever the button was pressed — which for a UTC server between
    00:00 and 05:30 IST is the day before, and on 1 April is the wrong
    FINANCIAL YEAR.

    Lives here rather than in each caller because there were THREE hand-rolled
    copies of these two lines (fixed assets' depreciation date, the same
    service's own depreciation branch, and the 24Q's representative payment
    date) and payroll would have been a fourth. CLAUDE.md's rule is move it,
    do not copy it.

    Raises ValueError on anything that is not YYYY-MM. A caller that cannot
    name its period has no business choosing an accounting date for it, and
    the alternative — falling back to today — is the bug this replaces.
    """
    m = re.fullmatch(r"(\d{4})-(0[1-9]|1[0-2])", (period or "").strip())
    if not m:
        raise ValueError(f"period must look like '2026-08', got {period!r}")
    year, month = int(m.group(1)), int(m.group(2))
    return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
