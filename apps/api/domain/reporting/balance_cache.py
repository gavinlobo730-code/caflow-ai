"""
Monthly balance cache — the "passbook" (Reporting perf, Phase 1).

WHY
    The accrual reports (Trial Balance, P&L, Balance Sheet) are, mathematically,
    nothing more than the per-account sum of (debit_paise, credit_paise) over a
    date window — see domain/reporting/builders.py, which groups the flat line
    stream by account and sums it. Today that stream is rebuilt by fetching and
    re-summing a client's ENTIRE posted history on every report load, so cost
    grows without bound as the ledger grows (a 12k-entry client is slow, and
    gets slower every year).

    A running per-account, per-MONTH bucket ("account_period_balances") lets a
    report read a small, time-bounded table instead of replaying all history —
    exactly how Tally / QuickBooks / any serious ERP answer "what's the balance"
    without recounting from inception.

WHAT THIS MODULE IS
    The pure, database-free core: it DEFINES a bucket (build_buckets) from the
    same JournalEntry stream the reporting engine already uses, and PROJECTS
    buckets back into the ProjectedLine stream the existing builders consume
    (project_lines) — so the numbers are byte-identical, only faster to obtain.

    It is deliberately side-effect-free and knows nothing about Supabase; the
    storage/backfill/audit wiring lives in services/balance_cache_service.py, and
    NOTHING reads it into a live report yet (Phase 1 is store + proof only).

EXACTNESS
    Buckets are whole calendar months. For a window whose edges land on month
    boundaries (a financial year, a calendar month, a quarter — which is what the
    reports actually request), summing buckets is EXACT. For a window with a
    partial edge month (e.g. "as of the 18th"), the partial month's buckets are
    NOT used; instead the caller supplies that month's raw lines and we replay
    them with the exact per-day date filter. Either way the result equals the
    old full-replay path to the paise, while only ever touching at most two
    months of raw data regardless of how deep the history is.

    Scope: accrual basis only (the default + statutory view, and the one that was
    slow), and only for a report scoped to ONE client — the rows are keyed by
    client_id NOT NULL, so a firm-wide report cannot be answered from them at all
    (ReportingService._passbook_applicable enforces that). Cash basis stays on the
    existing engine: it needs entry-level detail a per-account monthly sum cannot
    reconstruct. Integer paise throughout — never float.

    The Cash Flow statement is a PARTIAL user, and the distinction matters. Its
    body genuinely needs entry-level detail, so it still replays raw posted
    entries — but bounded to the reporting window rather than all history. What it
    takes from here is opening and closing cash, which are cumulative per-account
    sums as of a date: precisely what a bucket is, and the same quantity Trial
    Balance is already served from.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from typing import Iterable, Optional

from .model import JournalEntry, ProjectedLine

# A bucket key: (account_id, period_month) where period_month is the first day of
# the calendar month as an ISO 'YYYY-MM-01' string (matches the DB DATE column).
BucketKey = tuple[str, str]
Buckets = dict[BucketKey, tuple[int, int]]   # -> (debit_paise, credit_paise)


def month_of(iso_date: str) -> str:
    """First-of-month ISO string for an entry date. 'YYYY-MM-DD' -> 'YYYY-MM-01'."""
    return iso_date[:7] + "-01"


def _is_month_first(iso_date: str) -> bool:
    return iso_date[8:10] == "01"


def _is_month_last(iso_date: str) -> bool:
    y, m, d = int(iso_date[:4]), int(iso_date[5:7]), int(iso_date[8:10])
    return d == calendar.monthrange(y, m)[1]


def build_buckets(entries: Iterable[JournalEntry]) -> Buckets:
    """Definitive bucket definition: for every posted line, add its base
    debit/credit into the (account, month-of-entry-date) bucket.

    `entries` MUST be the posted, non-deleted history (the reporting snapshot's
    entries_by_id already is exactly that set). This mirrors the accrual line
    stream one-to-one — a reversal is an ordinary posted entry here, contributing
    its own flipped lines in its own month, so a reversed pair nets to zero
    exactly as the full-replay path produces.
    """
    out: dict[BucketKey, list[int]] = defaultdict(lambda: [0, 0])
    for e in entries:
        mk = month_of(e.entry_date)
        for ln in e.lines:
            b = out[(ln.account_id, mk)]
            b[0] += int(ln.debit_paise or 0)
            b[1] += int(ln.credit_paise or 0)
    return {k: (v[0], v[1]) for k, v in out.items()}


def _months_in_window(months: Iterable[str], start_m: Optional[str],
                      end_m: Optional[str], exclude: set[str]) -> set[str]:
    keep = set()
    for m in months:
        if start_m is not None and m < start_m:
            continue
        if end_m is not None and m > end_m:
            continue
        if m in exclude:
            continue
        keep.add(m)
    return keep


def project_lines(buckets: Buckets, start: Optional[str], end: Optional[str],
                  edge_entries: Iterable[JournalEntry] = ()) -> list[ProjectedLine]:
    """Reconstruct the accrual ProjectedLine stream for the window [start, end]
    from the monthly buckets, exact to the paise.

    One synthetic line per account carries that account's summed (debit, credit)
    over the window — which the builders group-and-sum anyway, so feeding them
    one pre-summed line per account yields identical output to feeding them the
    raw lines.

    Partial edge months: a bucket's whole month is used only when the window
    fully covers that month. If `start` is not the 1st of its month, or `end` is
    not the last day of its month, that edge month is instead replayed from
    `edge_entries` (the raw posted entries the caller fetched for those one or two
    months) with the exact date filter. For month-aligned windows `edge_entries`
    is unused and may be empty.

    start=None means "from the beginning" (cumulative, for a Balance Sheet /
    Trial Balance as-of-date); end=None means "to the latest".
    """
    start_m = month_of(start) if start else None
    end_m = month_of(end) if end else None

    # Which edge months must be replayed raw rather than taken from buckets.
    replay_months: set[str] = set()
    if start is not None and not _is_month_first(start):
        replay_months.add(start_m)  # type: ignore[arg-type]
    if end is not None and not _is_month_last(end):
        replay_months.add(end_m)    # type: ignore[arg-type]

    all_months = {m for (_aid, m) in buckets.keys()}
    use_months = _months_in_window(all_months, start_m, end_m, replay_months)

    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for (aid, m), (dr, cr) in buckets.items():
        if m in use_months:
            t = totals[aid]
            t[0] += dr
            t[1] += cr

    # Replay only the partial edge months from raw entries, exact per-day filter.
    if replay_months:
        for e in edge_entries:
            em = month_of(e.entry_date)
            if em not in replay_months:
                continue
            if start is not None and e.entry_date < start:
                continue
            if end is not None and e.entry_date > end:
                continue
            for ln in e.lines:
                t = totals[ln.account_id]
                t[0] += int(ln.debit_paise or 0)
                t[1] += int(ln.credit_paise or 0)

    return [ProjectedLine(aid, t[0], t[1]) for aid, t in totals.items()]
