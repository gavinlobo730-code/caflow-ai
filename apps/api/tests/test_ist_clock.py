"""
core.ist_clock — single source of truth for "today" in India.

The backend has no server-level timezone pinning (python:3.11-slim defaults
to UTC — see Dockerfile), so a bare `datetime.now(timezone.utc)` / `date.today()`
silently disagrees with the true IST calendar date for the ~5.5 hours daily
where IST has already crossed into a new day but UTC has not (IST 00:00-05:29
== UTC 18:30-23:59 the previous day). These tests freeze the module's notion
of "now" to prove ist_now()/ist_today() resolve the correct IST calendar date
across that boundary, without depending on the real wall clock (no freezegun
in this project's dependencies).
"""
import datetime as _datetime_module
from datetime import date, datetime, timedelta, timezone

import core.ist_clock as ist_clock


def _freeze_utc(monkeypatch, utc_iso: str) -> datetime:
    """Freeze ist_clock's `datetime.now(tz)` to the given naive-UTC instant."""
    fixed = datetime.fromisoformat(utc_iso).replace(tzinfo=timezone.utc)

    class _FrozenDateTime(_datetime_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz is not None else fixed

    monkeypatch.setattr(ist_clock, "datetime", _FrozenDateTime)
    return fixed


def test_ist_today_crosses_into_next_day_before_utc_does(monkeypatch):
    # 31 Mar 23:59 UTC == 1 Apr 05:29 IST. A bare UTC "today" still reads
    # 31 March (the previous FY) here — the exact bug this helper closes.
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    assert ist_clock.ist_today() == date(2026, 4, 1)


def test_ist_today_at_the_exact_boundary_instant(monkeypatch):
    # 1 Apr 00:00 UTC == 1 Apr 05:30 IST — the first instant both calendars
    # agree it is 1 April.
    _freeze_utc(monkeypatch, "2026-04-01T00:00:00")
    assert ist_clock.ist_today() == date(2026, 4, 1)


def test_ist_today_agrees_with_utc_well_after_the_boundary(monkeypatch):
    _freeze_utc(monkeypatch, "2026-04-01T12:00:00")
    assert ist_clock.ist_today() == date(2026, 4, 1)


def test_ist_today_well_before_the_boundary_is_still_previous_day(monkeypatch):
    # 31 Mar 10:00 UTC == 31 Mar 15:30 IST — both calendars already agree.
    _freeze_utc(monkeypatch, "2026-03-31T10:00:00")
    assert ist_clock.ist_today() == date(2026, 3, 31)


def test_ist_now_carries_the_ist_offset_not_utc(monkeypatch):
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    now = ist_clock.ist_now()
    assert now.utcoffset() == timedelta(hours=5, minutes=30)
    assert (now.hour, now.minute) == (5, 29)
