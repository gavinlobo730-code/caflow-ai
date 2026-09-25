"""The capacity forecast is CALLED with a database, and the fold actually folds.

`test_which_weeks_the_practice_is_short.py` exercises the RULE thoroughly with
hand-built `DueItem`s. This exercises the FETCH, which is where the two things
that can only go wrong in the service live:

  * the `compliance_calendar.task_id` fold, which is the difference between a
    forecast and one that counts every GSTR-1 twice;
  * `core.db_paging.fetch_all`'s first argument being a CALLABLE, which two
    call sites in this codebase have already got wrong — and neither failure
    was visible from that service's own tests, because a source scan cannot see
    an arity error and a `db is None` mock branch is not the code that runs.
    `tests/test_fetch_all_is_given_something_it_can_call.py` states the general
    rule; this states the specific claim, that the forecast answers.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from tests.e2e_harness import FakeDB

from services import capacity_risk_service as svc

FIRM = "66666666-6666-4666-8666-666666666666"
CLIENT = "77777777-7777-4777-8777-777777777777"
MONDAY = date(2026, 9, 28)

#: A Partner — `core.authz._FIRMWIDE_ROLES` — so `filter_by_client` does not
#: narrow these firm-wide reads to an empty assignment book and make every
#: assertion below vacuous.
PARTNER = {"firm_id": FIRM, "id": "u1", "role": "Partner"}


def _task(db, *, days, status="todo", step=None):
    return db.seed("tasks", {
        "firm_id": FIRM, "client_id": CLIENT, "status": status,
        "due_date": (MONDAY + timedelta(days=days)).isoformat(),
        "workflow_step_id": step, "title": "Prepare GSTR-1",
    })


def _obligation(db, *, days, status="pending", task_id=None):
    return db.seed("compliance_calendar", {
        "firm_id": FIRM, "client_id": CLIENT, "filing_status": status,
        "due_date": (MONDAY + timedelta(days=days)).isoformat(),
        "compliance_type": "GSTR3B", "task_id": task_id,
    })


@pytest.fixture()
def db():
    d = FakeDB()
    d.seed("users", {"id": "u1", "firm_id": FIRM, "is_active": True})
    d.seed("users", {"id": "u2", "firm_id": FIRM, "is_active": True})
    d.seed("users", {"id": "u3", "firm_id": FIRM, "is_active": False})
    d.seed("user_capacity", {"firm_id": FIRM, "user_id": "u1",
                             "weekly_capacity_hours": 45})
    return d


def test_the_forecast_answers_at_all(db):
    """The headline. A builder handed to `fetch_all` raises TypeError here."""
    out = svc.capacity_risk(db, PARTNER, today=MONDAY)
    assert isinstance(out, dict)
    assert len(out["weeks"]) == 13
    assert out["weeks"][0]["week_start"] == MONDAY.isoformat()


def test_an_obligation_that_names_a_task_is_counted_once(db):
    """The load-bearing one. Without the fold every GSTR-1 appears twice, and
    the calendar's own `task_id` column (migration 006) exists precisely
    because a filing obligation is usually worked as a task."""
    t = _task(db, days=1)
    _obligation(db, days=1, task_id=t["id"])

    out = svc.capacity_risk(db, PARTNER, today=MONDAY)
    assert out["weeks"][0]["items_due"] == 1
    assert out["weeks"][0]["tasks_due"] == 1
    assert out["weeks"][0]["compliance_due"] == 0
    assert out["obligations_folded_into_tasks"] == 1


def test_an_obligation_with_no_task_is_its_own_piece_of_work(db):
    _obligation(db, days=1)
    out = svc.capacity_risk(db, PARTNER, today=MONDAY)
    assert out["weeks"][0]["items_due"] == 1
    assert out["weeks"][0]["compliance_due"] == 1
    assert out["obligations_folded_into_tasks"] == 0


def test_an_obligation_naming_a_task_that_is_not_in_the_window_is_not_folded(db):
    """The fold is keyed on the task being IN the list — a completed or
    out-of-window task is not work anybody still has to do, so its obligation
    (which is still pending) has to stand on its own."""
    done = _task(db, days=1, status="completed")
    _obligation(db, days=1, task_id=done["id"])

    out = svc.capacity_risk(db, PARTNER, today=MONDAY)
    assert out["weeks"][0]["items_due"] == 1
    assert out["weeks"][0]["compliance_due"] == 1
    assert out["obligations_folded_into_tasks"] == 0


def test_finished_work_is_out_of_the_forecast(db):
    _task(db, days=1, status="completed")
    _task(db, days=1, status="cancelled")
    _task(db, days=1, status="in_progress")
    _obligation(db, days=1, status="filed")
    _obligation(db, days=1, status="na")
    _obligation(db, days=1, status="in_progress")

    out = svc.capacity_risk(db, PARTNER, today=MONDAY)
    assert out["weeks"][0]["items_due"] == 2


def test_an_unrecognised_task_status_is_still_to_do(db):
    """Written as "not done" rather than as a list of live statuses: migration
    002's CHECK carries five and a sixth added later must default to being IN
    the forecast rather than silently vanishing from it."""
    _task(db, days=1, status="escalated")
    out = svc.capacity_risk(db, PARTNER, today=MONDAY)
    assert out["weeks"][0]["items_due"] == 1


def test_the_one_effort_estimate_this_product_records_is_read(db):
    """`tasks` has no estimate column; `workflow_steps` does (migration 002).
    A task generated from a step carries one and everything else does not."""
    step = db.seed("workflow_steps", {"id": "step-1", "estimated_hours": 2.5,
                                      "workflow_id": "w1", "step_name": "File",
                                      "step_order": 1})
    _task(db, days=1, step=step["id"])
    _task(db, days=1)

    out = svc.capacity_risk(db, PARTNER, today=MONDAY)
    assert out["weeks"][0]["estimated_hours"] == 2.5
    assert out["weeks"][0]["items_without_an_estimate"] == 1


def test_a_step_with_no_recorded_estimate_leaves_the_task_unestimated(db):
    """Nullable with no default — a workflow step nobody sized is not a
    zero-hour task."""
    db.seed("workflow_steps", {"id": "step-2", "estimated_hours": None,
                               "workflow_id": "w1", "step_name": "Review",
                               "step_order": 2})
    _task(db, days=1, step="step-2")

    out = svc.capacity_risk(db, PARTNER, today=MONDAY)
    assert out["weeks"][0]["estimated_hours"] == 0.0
    assert out["weeks"][0]["items_without_an_estimate"] == 1


def test_the_team_figure_counts_active_members_and_their_configured_week(db):
    """A member with no capacity row takes the same default the workload screen
    already applies to them, so the two figures agree. u3 is inactive."""
    from repositories.capacity_repository import DEFAULT_WEEKLY_HOURS

    out = svc.capacity_risk(db, PARTNER, today=MONDAY)
    assert out["people"] == 2
    assert out["configured_weekly_hours"] == 45 + DEFAULT_WEEKLY_HOURS


def test_overdue_work_is_read_and_kept_out_of_the_weeks(db):
    _task(db, days=-3)
    _task(db, days=2)
    out = svc.capacity_risk(db, PARTNER, today=MONDAY)
    assert out["overdue_items"] == 1
    assert sum(w["items_due"] for w in out["weeks"]) == 1


def test_the_payload_carries_the_threshold_it_used(db):
    """A screen must not keep its own copy of the multiple, and a reader has to
    be able to tell what "peak" meant."""
    out = svc.capacity_risk(db, PARTNER, today=MONDAY)
    assert out["peak_multiple"] == svc.rule.PEAK_MULTIPLE
    assert len(out["not_forecast"]) >= 4


def test_a_task_with_no_due_date_is_read_by_its_own_query(db):
    """`.lt("due_date", ...)` excludes NULLs, so the window read cannot see an
    undated task at all — `undated_items` would have been a structural zero
    reading as "everything is dated", which is the `capital_wip` shape. Its own
    bounded `is null` read, rather than dropping the window filter and
    narrowing in Python, which would make the main read proportional to the
    whole task history."""
    db.seed("tasks", {"firm_id": FIRM, "client_id": CLIENT, "status": "todo",
                      "due_date": None, "workflow_step_id": None,
                      "title": "Chase the bank statements"})
    db.seed("tasks", {"firm_id": FIRM, "client_id": CLIENT, "status": "completed",
                      "due_date": None, "workflow_step_id": None,
                      "title": "Done, and undated"})
    _task(db, days=1)

    out = svc.capacity_risk(db, PARTNER, today=MONDAY)
    assert out["undated_items"] == 1, "the completed one is not outstanding work"
    assert sum(w["items_due"] for w in out["weeks"]) == 1
