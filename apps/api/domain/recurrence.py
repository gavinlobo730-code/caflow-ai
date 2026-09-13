"""When a recurring thing next falls due. Pure, deterministic, no database.

WHY THIS IS ITS OWN MODULE (ACC-06)

    `services/recurring_invoice_service.py` has owned this arithmetic since
    Phase 4.3 and it is right. Recurring JOURNALS need the same answers, and
    CLAUDE.md's rule for that case is one line: **when a rule has to exist in
    two places, MOVE it — do not copy it.** Two implementations drift, and a
    cadence engine drifting means one feature posts in a month the other skips.

    So the invoice service imports these names rather than keeping its own, and
    re-exports them so its existing callers and tests are untouched — the same
    shape `routers/fixed_assets.py` took when Schedule II moved into
    `domain/fixed_assets/`.

THE ONE RULE WORTH KNOWING: month ends CLAMP, and they clamp against the
    ORIGINAL day rather than the previous occurrence. A monthly template
    starting 31 January runs 31 Jan, 28 Feb, 31 Mar — not 31 Jan, 28 Feb,
    28 Mar. `_add_months_clamped` always measures from `start_date`, so a
    short month borrows nothing from the months after it. Advancing one
    occurrence at a time and clamping each step would walk the whole series
    back to the 28th after one February, which is how a rent journal quietly
    starts posting three days early for ever.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

#: The five cadences. `recurring_invoice_templates.frequency` and
#: `recurring_journal_templates.frequency` both CHECK exactly these.
FREQUENCIES = ("weekly", "monthly", "quarterly", "half_yearly", "yearly")

#: How many months each non-weekly cadence advances.
MONTHS = {"monthly": 1, "quarterly": 3, "half_yearly": 6, "yearly": 12}

#: Safety bound on back-dated catch-up, per template per run. A template
#: dormant for years must not generate a thousand documents on the morning
#: somebody switches it on.
MAX_CATCHUP_PER_RUN = 120


def to_date(v) -> date:
    """A `date`, from a date or an ISO string. Truncates a timestamp."""
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def add_months_clamped(d: date, months: int) -> date:
    """Add `months` to d, clamping the day to the last valid day of the target
    month (Jan-31 + 1 month -> Feb-28/29). Anchored to the original day."""
    m = d.month - 1 + months
    y = d.year + m // 12
    month = m % 12 + 1
    last = monthrange(y, month)[1]
    return date(y, month, min(d.day, last))


def occurrence(frequency: str, start_date, n: int) -> date:
    """The n-th occurrence (n=0 is start_date). Strictly increasing in n."""
    start = to_date(start_date)
    if frequency == "weekly":
        return start + timedelta(days=7 * n)
    if frequency not in MONTHS:
        raise ValueError(f"Unsupported frequency: {frequency}")
    return add_months_clamped(start, MONTHS[frequency] * n)


def _index_floor(frequency: str, start: date, ref: date) -> int:
    """A lower-bound estimate of the occurrence index at/just before `ref`."""
    if frequency == "weekly":
        return max(0, (ref - start).days // 7)
    return max(0, ((ref.year - start.year) * 12 + (ref.month - start.month)) // MONTHS[frequency])


def occurrence_on_or_after(frequency: str, start_date, ref) -> date:
    """Smallest occurrence date >= ref (the first occurrence is start_date)."""
    start, ref = to_date(start_date), to_date(ref)
    if ref <= start:
        return start
    n = _index_floor(frequency, start, ref)
    while n > 0 and occurrence(frequency, start, n - 1) >= ref:
        n -= 1
    while occurrence(frequency, start, n) < ref:
        n += 1
    return occurrence(frequency, start, n)


def next_occurrence(frequency: str, start_date, after=None) -> date:
    """Smallest occurrence strictly AFTER `after` (or the first occurrence =
    start_date when `after` is None or precedes start_date)."""
    start = to_date(start_date)
    if after is None:
        return start
    after = to_date(after)
    if after < start:
        return start
    n = _index_floor(frequency, start, after)
    while n > 0 and occurrence(frequency, start, n - 1) > after:
        n -= 1
    while occurrence(frequency, start, n) <= after:
        n += 1
    return occurrence(frequency, start, n)


def preview_occurrences(template: dict, count: int = 5, from_date=None) -> list[str]:
    """The next `count` occurrence dates from the template's next_run_date,
    stopping at end_date. Read-only preview (no writes)."""
    freq = template["frequency"]
    start = template["start_date"]
    end = to_date(template["end_date"]) if template.get("end_date") else None
    cur = to_date(template.get("next_run_date") or start)
    if from_date:
        cur = occurrence_on_or_after(freq, start, max(to_date(from_date), to_date(start)))
    out: list[str] = []
    n = 0
    while len(out) < max(count, 0) and n < MAX_CATCHUP_PER_RUN:
        if end and cur > end:
            break
        out.append(cur.isoformat())
        nxt = next_occurrence(freq, start, cur)
        if nxt is None or nxt <= cur:
            break
        cur = nxt
        n += 1
    return out
