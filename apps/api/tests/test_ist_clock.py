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


# ── ist_fy_label (Phase 3 consolidation) ────────────────────────────────────
# Single shared FY-label helper now backing both
# services/compliance_obligation_service.py::_current_fy() and
# domain/income_tax/statutory_rates.py::current_fy(). These tests pin its
# boundary/leap-year/explicit-date behaviour so both call sites keep the
# exact label they produced before the consolidation.

def _old_fy_formula(d: date) -> str:
    """The formula both call sites independently implemented before Phase 3 —
    kept here (not imported) so this test proves the shared helper still
    matches it, rather than trivially checking the helper against itself."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def test_ist_fy_label_matches_the_pre_consolidation_formula_across_every_month():
    for year in (2023, 2024, 2025, 2026):
        for month in range(1, 13):
            d = date(year, month, 15)
            assert ist_clock.ist_fy_label(d) == _old_fy_formula(d)


def test_ist_fy_label_fy_boundary_march_31_is_the_outgoing_fy():
    assert ist_clock.ist_fy_label(date(2026, 3, 31)) == "2025-26"


def test_ist_fy_label_fy_boundary_april_1_is_the_new_fy():
    assert ist_clock.ist_fy_label(date(2026, 4, 1)) == "2026-27"


def test_ist_fy_label_leap_day_falls_in_the_fy_that_started_the_prior_april():
    # 29 Feb 2024 is in FY 2023-24 (started 1 Apr 2023), not FY 2024-25.
    assert ist_clock.ist_fy_label(date(2024, 2, 29)) == "2023-24"


def test_ist_fy_label_defaults_to_ist_today_across_the_utc_boundary(monkeypatch):
    # 31 Mar 23:59 UTC == 1 Apr 05:29 IST — the default (no explicit date)
    # must resolve the new FY here, mirroring ist_today()'s own boundary test.
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    assert ist_clock.ist_fy_label() == "2026-27"


def test_ist_fy_label_explicit_date_overrides_the_clock(monkeypatch):
    _freeze_utc(monkeypatch, "2026-04-01T12:00:00")
    assert ist_clock.ist_fy_label(date(2020, 1, 1)) == "2019-20"
