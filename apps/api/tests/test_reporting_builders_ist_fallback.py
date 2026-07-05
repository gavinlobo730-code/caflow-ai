"""
domain/reporting/builders.py — as_of_date IST fallback (Phase 3 consolidation).

trial_balance() and balance_sheet() both defaulted a missing as_of_date via a
bare `date.today().isoformat()`. The only production caller,
domain/reporting/service.py, always resolves as_of to a concrete string before
calling in (verified by reading every builders.trial_balance/balance_sheet
call site in the backend), so this fallback is unreachable in practice — but
it is still public, directly callable, and worth pinning to the shared
core.ist_clock.ist_today() so it can never silently drift back onto a bare
UTC date.today() if a future caller omits as_of_date.
"""
import datetime as _datetime_module
from datetime import date, datetime, timezone

import core.ist_clock as ist_clock
from domain.reporting import builders


def _freeze_utc(monkeypatch, utc_iso: str) -> datetime:
    fixed = datetime.fromisoformat(utc_iso).replace(tzinfo=timezone.utc)

    class _FrozenDateTime(_datetime_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz is not None else fixed

    monkeypatch.setattr(ist_clock, "datetime", _FrozenDateTime)
    return fixed


def test_trial_balance_defaults_as_of_date_to_ist_today_across_the_utc_boundary(monkeypatch):
    # 31 Mar 23:59 UTC == 1 Apr 05:29 IST — a bare date.today() would still
    # read 31 March here; the shared ist_today() must read 1 April.
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    out = builders.trial_balance([], {}, None, "accrual")
    assert out["as_of_date"] == "2026-04-01"


def test_balance_sheet_defaults_as_of_date_to_ist_today_across_the_utc_boundary(monkeypatch):
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    out = builders.balance_sheet([], {}, None, "accrual")
    assert out["as_of_date"] == "2026-04-01"


def test_trial_balance_explicit_as_of_date_is_never_overridden_by_the_clock(monkeypatch):
    _freeze_utc(monkeypatch, "2026-04-01T12:00:00")
    out = builders.trial_balance([], {}, "2020-01-15", "accrual")
    assert out["as_of_date"] == "2020-01-15"


def test_balance_sheet_explicit_as_of_date_is_never_overridden_by_the_clock(monkeypatch):
    _freeze_utc(monkeypatch, "2026-04-01T12:00:00")
    out = builders.balance_sheet([], {}, "2020-01-15", "accrual")
    assert out["as_of_date"] == "2020-01-15"
