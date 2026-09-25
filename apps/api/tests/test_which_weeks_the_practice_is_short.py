"""
`domain/practice/capacity_risk` — the forward-looking half of the workload engine.

THE TESTS ARE MOSTLY ABOUT WHAT IT REFUSES TO INVENT. Two numbers would be easy
to produce and wrong: an hours total imputed across tasks that carry no
estimate, and a percentage-of-capacity derived from `max_concurrent_tasks`,
which is a limit on what somebody may have OPEN rather than what they can
finish in a week. Both would look authoritative on a chart, and a partner would
staff against them.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from domain.practice import capacity_risk as cr

MONDAY = date(2026, 9, 28)   # a Monday


def due(offset_days: int, *, source: str = "task", hours=None) -> cr.DueItem:
    return cr.DueItem(
        due_date=(MONDAY + timedelta(days=offset_days)).isoformat(),
        source=source, effort_hours=hours,
    )


def run(items, *, today=MONDAY, people=5, hours=200, weeks=13, folded=0):
    return cr.forecast(items, today=today, people=people,
                       configured_weekly_hours=hours,
                       obligations_folded_into_tasks=folded,
                       weeks_ahead=weeks)


# ── The week grid ────────────────────────────────────────────────────────────

def test_the_window_is_every_week_including_the_empty_ones():
    """A forecast that lists only the busy weeks cannot show a partner the
    quiet one they could move work into, and hides the far end going empty —
    which is the calendar not being rolled forward, not a free quarter."""
    out = run([due(0)])
    assert len(out.weeks) == 13
    assert out.weeks[0].items_due == 1
    assert all(w.items_due == 0 for w in out.weeks[1:])


@pytest.mark.parametrize("day,expected_week", [
    (0, 0), (1, 0), (6, 0),     # Mon-Sun of week 0
    (7, 1), (13, 1),
    (70, 10),
])
def test_an_item_lands_in_the_week_containing_its_due_date(day, expected_week):
    out = run([due(day)])
    assert out.weeks[expected_week].items_due == 1
    assert sum(w.items_due for w in out.weeks) == 1


def test_a_week_starts_on_a_monday_whatever_day_today_is():
    """Every statutory due date falls on a calendar day — the 7th, the 11th,
    the 20th — so the week boundary has to come from somewhere, and the working
    week is the one a partner staffs against."""
    wednesday = MONDAY + timedelta(days=2)
    out = run([due(0)], today=wednesday)
    assert out.weeks[0].week_start == MONDAY.isoformat()
    # Monday's item is BEFORE Wednesday, so it is overdue rather than in week 0.
    assert out.overdue_items == 1
    assert out.weeks[0].items_due == 0


def test_an_item_past_the_end_of_the_window_is_simply_out_of_it():
    out = run([due(7 * 13)], weeks=13)
    assert sum(w.items_due for w in out.weeks) == 0
    assert out.overdue_items == 0


# ── Overdue and undated are counted apart, never piled onto week one ─────────

def test_overdue_work_is_stated_once_and_not_added_to_the_first_week():
    """It is not in any week — it is in all of them, since it still has to be
    done on top of whatever arrives. Piling it onto the first bar would make
    that week look like a peak it is not, every single week."""
    out = run([due(-1), due(-30), due(0)])
    assert out.overdue_items == 2
    assert out.weeks[0].items_due == 1


def test_an_item_with_no_due_date_is_counted_and_never_placed():
    """Putting it in this week would make the first bar wrong every time
    somebody forgets a date."""
    out = run([cr.DueItem(due_date="", source="task"), due(0)])
    assert out.undated_items == 1
    assert sum(w.items_due for w in out.weeks) == 1


# ── Effort: recorded only, never imputed ─────────────────────────────────────

def test_hours_come_only_from_what_was_recorded():
    out = run([due(0, hours=3.5), due(1, hours=1.5), due(2)])
    assert out.weeks[0].estimated_hours == 5.0
    assert out.weeks[0].items_without_an_estimate == 1
    assert out.weeks[0].items_due == 3


def test_nothing_is_averaged_over_the_tasks_with_no_estimate():
    """`tasks` has no effort column — only `workflow_steps` and
    `task_templates` do — so most tasks carry none. Imputing an average would
    produce a confident hours figure whose accuracy is a property of how many
    tasks happen to come from workflows, which the CA cannot see."""
    out = run([due(0, hours=10.0)] + [due(0) for _ in range(9)])
    assert out.weeks[0].estimated_hours == 10.0, "not 100.0"
    assert out.weeks[0].items_without_an_estimate == 9


def test_a_week_with_no_estimate_at_all_reports_nil_hours_and_says_how_many():
    out = run([due(0), due(1), due(2)])
    assert out.weeks[0].estimated_hours == 0.0
    assert out.weeks[0].items_without_an_estimate == 3


# ── Peaks, measured against the practice's own week ──────────────────────────

def test_a_week_far_above_the_practice_own_median_is_a_peak():
    items = []
    for w in range(13):
        n = 30 if w == 5 else 8
        items += [due(7 * w) for _ in range(n)]
    out = run(items)
    assert out.median_week_items == 8
    assert out.peak_weeks == (out.weeks[5].week_start,)
    assert out.weeks[5].is_peak is True
    assert out.weeks[5].vs_median_pct == 375
    assert out.weeks[0].vs_median_pct == 100


def test_an_even_quarter_has_no_peak():
    items = [due(7 * w) for w in range(13) for _ in range(8)]
    out = run(items)
    assert out.peak_weeks == ()
    assert all(w.vs_median_pct == 100 for w in out.weeks)


def test_the_median_is_taken_over_the_weeks_that_have_work():
    """Including the empty ones would drag the median toward zero and make
    every ordinary week a peak — and the far end of the window is usually
    empty because the calendar has not been rolled that far, not because the
    practice is free."""
    items = [due(7 * w) for w in range(5) for _ in range(8)]  # 5 weeks, 8 rest empty
    out = run(items)
    assert out.median_week_items == 8
    assert out.peak_weeks == ()

    all_weeks = [len([i for i in items
                      if cr.monday_of(date.fromisoformat(i.due_date))
                      == MONDAY + timedelta(weeks=w)])
                 for w in range(13)]
    assert sorted(all_weeks)[6] == 0, "premise: a median over all 13 would be 0"


def test_too_few_weeks_with_work_means_no_median_and_no_peak_called():
    """A practice whose calendar is barely populated is told that rather than
    shown three arbitrary peaks."""
    items = [due(7 * w) for w in range(cr.MIN_WEEKS_FOR_A_MEDIAN - 1) for _ in range(8)]
    out = run(items)
    assert out.median_week_items is None
    assert out.peak_weeks == ()
    assert all(w.vs_median_pct is None for w in out.weeks)
    assert all(w.is_peak is False for w in out.weeks)


def test_the_peak_threshold_is_lower_than_the_ledger_checks_and_that_is_deliberate():
    """A week wrongly flagged costs a partner a glance at a calendar; a week
    missed costs a filing deadline with a s. 47 late fee per client per day
    behind it. The two errors are not symmetric, so the multiple is not the
    six `domain/accounting/ledger_anomalies` uses."""
    from domain.accounting import ledger_anomalies
    assert cr.PEAK_MULTIPLE < ledger_anomalies.OUTLIER_MULTIPLE


# ── Capacity is reported beside the load, never multiplied into it ───────────

def test_the_team_is_a_headcount_and_a_configured_week_and_nothing_derived():
    """`max_concurrent_tasks` is a limit on what somebody may have OPEN, not on
    what they finish in a week. Treating it as a weekly throughput would give
    every week a confident percentage of an invented capacity."""
    out = run([due(0)], people=6, hours=240)
    assert out.people == 6
    assert out.configured_weekly_hours == 240
    week_fields = set(vars(out.weeks[0]))
    assert not {f for f in week_fields if "capacity" in f or "utilis" in f}, (
        "a week must carry no percentage-of-capacity figure")


def test_the_module_never_mentions_a_concurrency_limit():
    """Asserted on the source so a later reader cannot quietly reach for
    `max_concurrent_tasks` as a throughput."""
    import pathlib
    src = pathlib.Path(cr.__file__).read_text()
    body = src.split('"""', 2)[-1]   # past the module docstring, which names it
    assert "max_concurrent_tasks" not in body


# ── The fold ─────────────────────────────────────────────────────────────────

def test_the_fold_is_reported_rather_than_silent():
    """`compliance_calendar.task_id` means an obligation is already a task in
    the same list, so counting both would double every GSTR-1. A partner
    comparing this with the deadline list would otherwise read the difference
    as the forecast being short."""
    out = run([due(0)], folded=17)
    assert out.obligations_folded_into_tasks == 17


def test_the_two_sources_are_counted_apart_as_well_as_together():
    out = run([due(0), due(0, source="compliance"), due(0, source="compliance")])
    assert out.weeks[0].items_due == 3
    assert out.weeks[0].tasks_due == 1
    assert out.weeks[0].compliance_due == 2


# ── Shape ────────────────────────────────────────────────────────────────────

def test_the_forecast_says_what_it_cannot_see():
    out = run([])
    assert len(out.not_forecast) >= 4
    assert all(len(s) >= 60 for s in out.not_forecast)


def test_an_empty_practice_answers_rather_than_raising():
    out = run([])
    assert len(out.weeks) == 13
    assert out.median_week_items is None
    assert out.overdue_items == 0


@pytest.mark.parametrize("d,expected", [
    ("2026-09-28", "2026-09-28"),   # Monday
    ("2026-09-29", "2026-09-28"),
    ("2026-10-04", "2026-09-28"),   # Sunday
    ("2026-10-05", "2026-10-05"),
])
def test_monday_of(d, expected):
    assert cr.monday_of(date.fromisoformat(d)).isoformat() == expected
