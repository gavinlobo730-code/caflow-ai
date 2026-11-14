"""A member's own time over a period of Indian days, decided by the server and summed by the database (POST-A-156).

WHAT WAS WRONG
    `/time` showed "Total Hours" as the sum of the entries it listed (at most 500), so the tiles were the latest entries and no
    period at all, and `GET /api/time-entries/summary/me` summed every entry the member ever made in Python, ignored the `period`
    it accepted and was called by nothing.

WHAT THIS HOLDS
    * `domain.time_summary.window_for`: this week is Monday to Sunday of India's week, this month the calendar month, a chosen range
      both its days, and a range backwards or half-given is refused in words.
    * `summarise`: an entry belongs to the Indian day it started on (18:30 UTC is the next day in India), only a finished entry is
      counted, a running timer is counted apart, and the minutes per client are ordered with no client last.
    * the route decides the window, returns it with the totals and the non-billable remainder, and refuses a bad period or day.
    * with a database configured the repository asks `time_entry_summary` with the instants that bound the Indian days, and a
      reply that is not a summary is raised, never answered from the twin.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

import core.ist_clock as ist_clock
import repositories.time_tracking_repository as tt_repo_module
import routers.time_tracking as tt
from domain.time_summary import PeriodProblem, summarise, window_for
from tests.e2e_harness import FakeDB

FIRM, ME, SOMEONE = "F1", "u-me", "u-other"
MEMBER = {"id": ME, "firm_id": FIRM, "auth_user_id": "a-me", "role": "Executive", "email": "me@f.test"}


# ── The window a period names ────────────────────────────────────────────────

@pytest.mark.parametrize("today,first,last", [
    (date(2026, 11, 11), date(2026, 11, 9), date(2026, 11, 15)),   # a Wednesday
    (date(2026, 11, 9), date(2026, 11, 9), date(2026, 11, 15)),    # the Monday itself
    (date(2026, 11, 15), date(2026, 11, 9), date(2026, 11, 15)),   # the Sunday is the week's last day
    (date(2026, 12, 31), date(2026, 12, 28), date(2027, 1, 3)),    # a week across the year end
])
def test_this_week_is_monday_to_sunday_of_indias_week(today, first, last):
    assert window_for("week", today) == (first, last)


def test_this_month_is_the_calendar_month_and_february_knows_its_leap_years():
    assert window_for("month", date(2026, 11, 14)) == (date(2026, 11, 1), date(2026, 11, 30))
    assert window_for("month", date(2028, 2, 10)) == (date(2028, 2, 1), date(2028, 2, 29))
    assert window_for("month", date(2027, 2, 10)) == (date(2027, 2, 1), date(2027, 2, 28))


def test_a_range_to_the_calendars_last_day_is_refused_and_not_a_500():
    with pytest.raises(PeriodProblem, match="last day the calendar holds"):
        window_for("range", date(2026, 11, 14), date(2026, 1, 1), date.max)


def test_a_chosen_range_is_its_two_days_and_a_bad_one_is_refused_in_words():
    assert window_for("range", date(2026, 11, 14), date(2026, 4, 1), date(2026, 4, 1)) == (date(2026, 4, 1), date(2026, 4, 1))
    with pytest.raises(PeriodProblem, match="after its last day"):
        window_for("range", date(2026, 11, 14), date(2026, 4, 2), date(2026, 4, 1))
    with pytest.raises(PeriodProblem, match="both its first day and its last day"):
        window_for("range", date(2026, 11, 14), date(2026, 4, 2), None)
    with pytest.raises(PeriodProblem, match="period must be one of"):
        window_for("fortnight", date(2026, 11, 14))


# ── The totals ───────────────────────────────────────────────────────────────

def _e(started, minutes, *, billable=True, client="C1", ended=True, user=ME, firm=FIRM):
    return {"firm_id": firm, "user_id": user, "client_id": client, "started_at": started, "is_billable": billable,
            "ended_at": "2026-11-10T10:00:00+00:00" if ended else None, "duration_minutes": minutes if ended else None}


ENTRIES = [
    _e("2026-11-09T04:00:00+00:00", 60),                              # Monday, billable, C1
    _e("2026-11-09T05:00:00+00:00", 30, billable=False),              # Monday, not billable, C1
    _e("2026-11-10T06:00:00+00:00", 45, client=None),                 # Tuesday, no client
    _e("2026-11-08T18:30:00+00:00", 20, client="C2"),                 # 00:00 IST Monday 9th: in the week
    _e("2026-11-08T18:29:59+00:00", 999),                             # 23:59:59 IST Sunday 8th: the week before
    _e("2026-11-11T07:00:00+00:00", 0, ended=False),                  # a timer still running
    {**_e("2026-11-11T08:00:00+00:00", 15), "duration_minutes": None},  # ended but with no duration: not a finished entry
]


def test_the_totals_count_finished_entries_by_their_indian_day_and_keep_a_running_timer_apart():
    out = summarise(ENTRIES, date(2026, 11, 9), date(2026, 11, 15))
    assert (out["total_minutes"], out["billable_minutes"], out["entries_count"], out["running"]) == (155, 125, 4, 1)
    assert out["by_client"] == [
        {"client_id": "C1", "minutes": 90, "billable_minutes": 60},
        {"client_id": "C2", "minutes": 20, "billable_minutes": 20},
        {"client_id": None, "minutes": 45, "billable_minutes": 45},
    ], "per client, ordered, with no client last"


def test_nothing_in_the_window_is_zero_and_an_empty_list_not_a_missing_one():
    assert summarise(ENTRIES, date(2025, 1, 1), date(2025, 1, 31)) == {
        "total_minutes": 0, "billable_minutes": 0, "entries_count": 0, "running": 0, "by_client": []}


# ── The route ────────────────────────────────────────────────────────────────

def _in_india(stamp: str) -> str:
    from datetime import datetime
    return datetime.fromisoformat(stamp).astimezone(ist_clock.IST).isoformat()


@pytest.fixture
def at_my_time(monkeypatch):
    db = FakeDB()
    # The in-memory database compares stamps as TEXT, so the route's rows are seeded written in India's offset, the way the bounds
    # are: the real database compares instants, and the midnight rule itself is proved on `summarise` above and on Postgres in
    # test_time_entry_summary_parity_pg.py.
    for e in ENTRIES:
        db.seed("time_entries", {**e, "started_at": _in_india(e["started_at"])})
    db.seed("time_entries", _e("2026-11-10T04:00:00+00:00", 500, user=SOMEONE))     # somebody else's time
    db.seed("time_entries", _e("2026-11-10T04:00:00+00:00", 700, firm="F2"))        # another firm's
    monkeypatch.setattr(tt_repo_module, "_get_db", lambda: db)
    monkeypatch.setattr(tt_repo_module.db_provider, "service_db_or_none", lambda: None)
    monkeypatch.setattr(ist_clock, "ist_today", lambda: date(2026, 11, 11))
    return db


def test_the_route_answers_this_week_by_default_with_its_days_and_only_the_callers_time(at_my_time):
    out = tt.my_summary(period="week", date_from=None, date_to=None, current_user=MEMBER)
    assert out["success"] is True
    d = out["data"]
    assert (d["period"], d["date_from"], d["date_to"]) == ("week", "2026-11-09", "2026-11-15")
    assert (d["total_minutes"], d["billable_minutes"], d["non_billable_minutes"], d["entries_count"], d["running"]) == (155, 125, 30, 4, 1)


def test_the_route_reads_indias_today_from_the_clock_it_is_given(at_my_time, monkeypatch):
    """A today far from the real one, so a stub that missed the route (which imports the clock inside the function) is seen."""
    monkeypatch.setattr(ist_clock, "ist_today", lambda: date(2027, 3, 7))     # a Sunday
    d = tt.my_summary(period="week", date_from=None, date_to=None, current_user=MEMBER)["data"]
    assert (d["date_from"], d["date_to"], d["total_minutes"]) == ("2027-03-01", "2027-03-07", 0)


def test_the_route_answers_a_month_and_a_chosen_range(at_my_time):
    month = tt.my_summary(period="month", date_from=None, date_to=None, current_user=MEMBER)["data"]
    assert (month["date_from"], month["date_to"]) == ("2026-11-01", "2026-11-30")
    assert month["total_minutes"] == 155 + 999, "the 8th is in November"
    one_day = tt.my_summary(period="range", date_from="2026-11-09", date_to="2026-11-09", current_user=MEMBER)["data"]
    assert (one_day["date_from"], one_day["date_to"], one_day["total_minutes"]) == ("2026-11-09", "2026-11-09", 110)


@pytest.mark.parametrize("kwargs,words", [
    ({"period": "fortnight"}, "period must be one of"),
    ({"period": "range", "date_from": "2026-11-10", "date_to": "2026-11-09"}, "after its last day"),
    ({"period": "range", "date_from": "2026-11-10"}, "both its first day and its last day"),
    ({"period": "range", "date_from": "10/11/2026", "date_to": "2026-11-11"}, "date_from must be a date written YYYY-MM-DD"),
])
def test_the_route_refuses_what_is_not_a_period_in_words(at_my_time, kwargs, words):
    args = {"period": "week", "date_from": None, "date_to": None, **kwargs}
    with pytest.raises(HTTPException) as e:
        tt.my_summary(current_user=MEMBER, **args)
    assert e.value.status_code == 422 and words in str(e.value.detail)


# ── The database path ────────────────────────────────────────────────────────

class _Rpc:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def rpc(self, name, params):
        self.calls.append((name, params))
        answer = self.answer

        class _Exec:
            def execute(self_inner):
                return type("R", (), {"data": answer})()
        return _Exec()


def test_with_a_database_the_sum_is_asked_of_it_with_the_instants_that_bound_the_indian_days(monkeypatch):
    db = _Rpc({"total_minutes": 7, "billable_minutes": 5, "entries_count": 1, "running": 0, "by_client": []})
    monkeypatch.setattr(tt_repo_module.db_provider, "service_db_or_none", lambda: db)
    monkeypatch.setattr(tt_repo_module, "_get_db", lambda: (_ for _ in ()).throw(AssertionError("the rows were fetched")))
    out = tt_repo_module.time_tracking_repo.get_summary(FIRM, ME, date(2026, 11, 9), date(2026, 11, 15))
    assert out["total_minutes"] == 7
    assert db.calls == [("time_entry_summary", {"p_firm": FIRM, "p_user": ME,
                                                "p_from": "2026-11-09T00:00:00+05:30", "p_to": "2026-11-16T00:00:00+05:30"})]


def test_a_reply_that_is_not_a_summary_is_raised_not_answered_from_the_twin(monkeypatch):
    monkeypatch.setattr(tt_repo_module.db_provider, "service_db_or_none", lambda: _Rpc([]))
    with pytest.raises(ValueError, match="not a summary"):
        tt_repo_module.time_tracking_repo.get_summary(FIRM, ME, date(2026, 11, 9), date(2026, 11, 15))
