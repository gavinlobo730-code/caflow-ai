"""practice_management-24 — ONE capacity model, and a task carries its own estimate.

WHAT WAS WRONG
    Two screens answered "how loaded is this person" differently, and one of them
    was a guess by job title: `/team/work-allocation` divided a count of open
    tasks by a per-role constant in the browser, while `/team/workload` is a real
    model (a thirteen-week forecast off `weekly_capacity_hours` and logged time).
    That model could see effort for almost nothing — `tasks` had no estimate, the
    task template's `estimated_hours` was never copied when a task was made from
    it, and the only effort the forecast found sat on `workflow_steps` behind a
    `workflow_step_id` that nothing writes.

WHAT IS ASSERTED
    * the rule (`domain/practice/task_estimate`): whole minutes > 0 or None, never
      0; hours become minutes with one rounding; recorded estimates are totalled
      and the tasks with none are COUNTED, never averaged over;
    * every door that makes a task from something that knows how long it takes
      copies the figure — a 3-hour template makes a 180-minute task — and a source
      with no figure adds NO KEY, never a 0 (the six starter workflows included);
    * a task made by hand takes an estimate, refuses a bad one, and a request
      with none never names the column (the window between a deploy and the
      migration);
    * the forecast reads the task's own estimate first, falls back to the old
      workflow-step join only for a task with none, and counts the rest;
    * `GET /api/workload` carries each person's open estimate and the tasks with
      none, their open work, and the unassigned backlog — the one model the
      retired screen is merged into;
    * a reassignment moves BOTH assignee columns, because the workload figures
      read `assignee_id` first.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.task_templates as tt
import routers.tasks as tr
import routers.workload as wl
from core.auth import get_current_user
from domain.practice import task_estimate as est
from services import capacity_risk_service as risk
from services import recurring_task_service as rec
from services import workflow_service as starters
from tests.e2e_harness import FakeDB

FIRM, CLIENT = "firm-cap-1", "client-cap-1"
PARTNER = {"id": "u-ptr", "firm_id": FIRM, "role": "Partner", "email": "p@f.in", "auth_user_id": "a-ptr"}
MONDAY = date(2026, 9, 28)


# ══════════════════════════════════════════════════════════════════════════════
# the rule
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("value,expected", [
    (180, 180), (1, 1), (180.0, 180), ("180", 180), (" 90 ", 90),
    (0, None), (-5, None), (12.5, None), ("12.5", None), ("1e3", None), ("abc", None),
    (True, None), (False, None), (None, None), ([], None), ({}, None),
    (float("nan"), None), (float("inf"), None),
])
def test_an_estimate_is_whole_minutes_more_than_zero_or_nothing(value, expected):
    assert est.clean_minutes(value) == expected


@pytest.mark.parametrize("bad", [0, -1, 12.5, "x", True])
def test_a_door_that_sets_an_estimate_refuses_one_that_is_not(bad):
    with pytest.raises(ValueError, match="whole number of minutes"):
        est.check_minutes(bad)
    assert est.check_minutes(None) is None, "not given is not refused"
    assert est.check_minutes(180) == 180


@pytest.mark.parametrize("hours,minutes", [
    (3, 180), (1, 60), (1.5, 90), (0.25, 15), ("0.5", 30), (0.1, 6), (4.0, 240),
    (0.33, 20),            # 19.8 minutes, rounded half up: an estimate, not a money figure
    (0.008, None),         # under half a minute is no estimate rather than a 0
])
def test_hours_become_minutes_with_one_rounding(hours, minutes):
    assert est.minutes_from_hours(hours) == minutes


@pytest.mark.parametrize("junk", [0, -2, None, True, "", "x", float("nan")])
def test_no_figure_is_no_estimate_and_never_zero(junk):
    assert est.minutes_from_hours(junk) is None


def test_an_absent_estimate_stays_absent_in_the_forecasts_unit():
    assert est.hours_from_minutes(None) is None
    assert est.hours_from_minutes(0) is None, "there is no estimate of nothing"
    assert est.hours_from_minutes(90) == 1.5


def test_recorded_estimates_are_totalled_and_the_rest_are_counted_never_averaged():
    s = est.summarise([180, None, 60, 0, "x"])
    assert (s.minutes, s.with_estimate, s.without_estimate) == (240, 2, 3)


# ══════════════════════════════════════════════════════════════════════════════
# a task made by hand
# ══════════════════════════════════════════════════════════════════════════════

class _Made(list):
    """The rows created, in order; `.stored` is the same rows by id."""
    stored: dict


@pytest.fixture
def made(monkeypatch):
    """The rows POST/PATCH /api/tasks write, captured."""
    rows = _Made()
    stored: dict[str, dict] = {}
    rows.stored = stored

    def create(data):
        row = {"id": f"t{len(rows) + 1}", **data}
        rows.append(row)
        stored[row["id"]] = row
        return row

    def update(task_id, data, *a, **k):
        stored[task_id].update(data)
        return stored[task_id]

    monkeypatch.setattr(tr.task_repo, "create", create)
    monkeypatch.setattr(tr.task_repo, "update", update)
    monkeypatch.setattr(tr.task_repo, "find_by_id", lambda tid, *a, **k: stored.get(tid))
    monkeypatch.setattr(tr.client_repo, "find_by_id", lambda *a, **k: {"id": CLIENT, "firm_id": FIRM})
    monkeypatch.setattr(tr, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(tr, "log_activity", lambda **k: {})
    monkeypatch.setattr(tr, "log_event", lambda *a, **k: None)
    monkeypatch.setattr("repositories.user_repository.user_repo.find_by_id",
                        lambda uid, firm_id=None, **k: {"id": uid, "firm_id": FIRM, "email": f"{uid}@f.in"})
    monkeypatch.setattr("repositories.task_extras_repository.task_extras_repo.log_event",
                        lambda *a, **k: {})
    monkeypatch.setattr("services.notification_service.notification_service.notify_task_assigned",
                        lambda *a, **k: None)
    monkeypatch.setattr("services.notification_service.notification_service.notify_task_reassigned",
                        lambda *a, **k: None)
    return rows


def _app(router):
    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


def test_a_task_made_by_hand_takes_an_estimate(made):
    res = _app(tr).post("/api/tasks", json={"client_id": CLIENT, "title": "GSTR-3B", "estimated_minutes": 180})
    assert res.status_code == 200, res.text
    assert made[0]["estimated_minutes"] == 180


def test_a_task_with_no_estimate_never_names_the_column(made):
    """The window between a deploy and migration 452: a request that carries no
    estimate must not mention a column the table may not have yet, or every task
    made by hand is refused until it lands."""
    res = _app(tr).post("/api/tasks", json={"client_id": CLIENT, "title": "GSTR-3B"})
    assert res.status_code == 200, res.text
    assert "estimated_minutes" not in made[0]


@pytest.mark.parametrize("bad", [0, -5, 12.5, "abc", True])
def test_a_bad_estimate_is_refused_and_nothing_is_created(made, bad):
    res = _app(tr).post("/api/tasks", json={"client_id": CLIENT, "title": "x", "estimated_minutes": bad})
    assert res.status_code == 422
    assert made == [], "a refused estimate must not become a task with a different one"


def test_an_estimate_can_be_corrected_on_an_existing_task(made):
    c = _app(tr)
    c.post("/api/tasks", json={"client_id": CLIENT, "title": "x", "estimated_minutes": 60})
    res = c.patch("/api/tasks/t1", json={"estimated_minutes": 120})
    assert res.status_code == 200, res.text
    assert made.stored["t1"]["estimated_minutes"] == 120
    assert c.patch("/api/tasks/t1", json={"estimated_minutes": 0}).status_code == 422
    assert made.stored["t1"]["estimated_minutes"] == 120


def test_a_reassignment_moves_both_assignee_columns(made):
    """`/api/workload` reads `assignee_id` FIRST, and a task made from a template
    or a recurring configuration carries both columns. A PATCH that wrote only
    `assigned_to` left the old person holding the task in the figures."""
    c = _app(tr)
    c.post("/api/tasks", json={"client_id": CLIENT, "title": "x", "assigned_to": "u-old"})
    made.stored["t1"]["assignee_id"] = "u-old"
    res = c.patch("/api/tasks/t1", json={"assigned_to": "u-new"})
    assert res.status_code == 200, res.text
    assert made.stored["t1"]["assigned_to"] == "u-new"
    assert made.stored["t1"]["assignee_id"] == "u-new"


# ══════════════════════════════════════════════════════════════════════════════
# a task made from something that knows how long it takes
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def instantiate(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    monkeypatch.setattr(tt, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr("repositories.task_extras_repository.task_extras_repo.log_event",
                        lambda *a, **k: {})

    def run(template: dict):
        monkeypatch.setattr(tt.task_template_repo, "find_by_id",
                            lambda tid, firm_id=None, **k: {"id": tid, "firm_id": FIRM, **template})
        res = _app(tt).post("/api/task-templates/tpl-1/instantiate", json={"client_id": CLIENT})
        assert res.status_code == 200, res.text
        return db.rows("tasks")[-1]

    return run


def test_a_task_made_from_a_three_hour_template_carries_180_minutes(instantiate):
    row = instantiate({"name": "Monthly GST", "estimated_hours": 3})
    assert row["estimated_minutes"] == 180


def test_a_template_with_no_estimate_adds_no_estimate(instantiate):
    row = instantiate({"name": "Ad hoc", "estimated_hours": None})
    assert "estimated_minutes" not in row


def test_a_template_estimate_of_zero_is_no_estimate(instantiate):
    assert "estimated_minutes" not in instantiate({"name": "Zero", "estimated_hours": 0})


def test_a_recurring_task_takes_its_templates_estimate(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(rec, "_get_db", lambda: db)
    monkeypatch.setattr(rec, "ist_today", lambda: MONDAY)
    db.seed("task_templates", {"id": "tpl-1", "firm_id": FIRM, "name": "Monthly GST",
                               "description": None, "default_priority": "medium",
                               "estimated_hours": 2})
    db.seed("task_recurring_configs", {
        "id": "cfg-1", "firm_id": FIRM, "client_id": CLIENT, "template_id": "tpl-1",
        "is_active": True, "frequency": "monthly", "next_due_date": MONDAY.isoformat(),
        "last_generated_at": None, "assignee_id": None})
    made = rec.generate_due_recurring_tasks(firm_id=FIRM)
    assert [t.get("estimated_minutes") for t in made] == [120]


def test_a_recurring_task_with_no_template_adds_no_estimate(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(rec, "_get_db", lambda: db)
    monkeypatch.setattr(rec, "ist_today", lambda: MONDAY)
    db.seed("task_recurring_configs", {
        "id": "cfg-2", "firm_id": FIRM, "client_id": CLIENT, "title": "Collect KYC",
        "is_active": True, "frequency": "monthly", "next_due_date": MONDAY.isoformat(),
        "last_generated_at": None, "assignee_id": None})
    made = rec.generate_due_recurring_tasks(firm_id=FIRM)
    assert len(made) == 1 and "estimated_minutes" not in made[0]


def test_a_workflow_create_task_action_hands_its_estimate_to_the_task(monkeypatch):
    from domain.workflow_engine_v2 import WorkflowEngineV2
    import repositories.task_repository as task_repository
    import repositories.client_repository as client_repository
    created: list[dict] = []
    monkeypatch.setattr(task_repository.task_repo, "create",
                        lambda data: created.append(data) or {"id": "t1", **data})
    monkeypatch.setattr(client_repository.client_repo, "find_by_id", lambda *a, **k: {"id": CLIENT})
    engine = WorkflowEngineV2.__new__(WorkflowEngineV2)
    instance = {"id": "i1", "client_id": CLIENT}
    for params in ({"title": "A", "estimated_minutes": 90},
                   {"title": "B", "estimated_hours": 1.5},
                   {"title": "C", "estimated_minutes": 0},
                   {"title": "D"}):
        engine._execute_action({"action_type": "create_task", "params": params}, instance, {}, FIRM)
    assert [c.get("estimated_minutes") for c in created] == [90, 90, None, None]
    assert all("estimated_minutes" not in c for c in created[2:]), "an unusable figure adds no key"


@pytest.mark.parametrize("template", starters.get_all_templates(), ids=lambda t: t["id"])
def test_every_step_of_the_six_starter_workflows_hands_its_estimate_to_its_task(template):
    assert len(starters.get_all_templates()) == 6
    tasks = starters.instantiate_workflow_tasks(template["id"], CLIENT, "u1", "2026-10-20")
    assert len(tasks) == len(template["steps"])
    for step, task in zip(template["steps"], tasks):
        assert step.get("estimated_hours"), "every starter step records how long it takes"
        assert task["estimated_minutes"] == est.minutes_from_hours(step["estimated_hours"])


# ══════════════════════════════════════════════════════════════════════════════
# the forecast reads the task's own estimate
# ══════════════════════════════════════════════════════════════════════════════

PARTNER_ROW = {"firm_id": FIRM, "id": "u1", "role": "Partner"}


def _task(db, *, days, minutes=None, step=None, status="todo", assignee=None, title="Prepare GSTR-1"):
    row = {"firm_id": FIRM, "client_id": CLIENT, "status": status, "title": title,
           "due_date": (MONDAY + timedelta(days=days)).isoformat(), "workflow_step_id": step,
           "assignee_id": assignee, "assigned_to": assignee, "priority": "medium"}
    if minutes is not None:
        row["estimated_minutes"] = minutes
    return db.seed("tasks", row)


@pytest.fixture
def db():
    d = FakeDB()
    d.seed("users", {"id": "u1", "firm_id": FIRM, "is_active": True, "full_name": "Asha", "role": "Manager"})
    d.seed("users", {"id": "u2", "firm_id": FIRM, "is_active": True, "full_name": "Ravi", "role": "Executive"})
    d.seed("user_capacity", {"firm_id": FIRM, "user_id": "u1", "weekly_capacity_hours": 45})
    return d


def _forecast(db):
    return risk.capacity_risk(db, PARTNER_ROW, weeks_ahead=13, today=MONDAY)


def test_a_task_made_from_a_three_hour_template_shows_three_hours_in_the_forecast(db):
    _task(db, days=1, minutes=180)
    week = _forecast(db)["weeks"][0]
    assert week["estimated_hours"] == 3.0
    assert week["items_without_an_estimate"] == 0


def test_tasks_with_no_estimate_are_counted_beside_the_hours_and_never_averaged(db):
    _task(db, days=1, minutes=180)
    for d in (1, 2, 3):
        _task(db, days=d)
    week = _forecast(db)["weeks"][0]
    assert week["estimated_hours"] == 3.0, "not 12.0: nothing is imputed for the tasks that carry none"
    assert week["items_without_an_estimate"] == 3


def test_the_tasks_own_estimate_beats_its_workflow_steps(db):
    db.seed("workflow_steps", {"id": "step-1", "estimated_hours": 5.0})
    _task(db, days=1, minutes=90, step="step-1")
    assert _forecast(db)["weeks"][0]["estimated_hours"] == 1.5


def test_a_task_with_only_a_workflow_step_still_resolves_through_it(db):
    """The join stays as a fallback: nothing the forecast could already see is lost."""
    db.seed("workflow_steps", {"id": "step-1", "estimated_hours": 2.0})
    _task(db, days=1, step="step-1")
    week = _forecast(db)["weeks"][0]
    assert week["estimated_hours"] == 2.0 and week["items_without_an_estimate"] == 0


def test_the_step_lookup_is_asked_only_for_tasks_that_need_it(db, monkeypatch):
    asked: list[list[str]] = []
    real = risk._effort_by_step
    monkeypatch.setattr(risk, "_effort_by_step", lambda d, ids: asked.append(list(ids)) or real(d, ids))
    db.seed("workflow_steps", {"id": "step-own", "estimated_hours": 9.0})
    db.seed("workflow_steps", {"id": "step-need", "estimated_hours": 1.0})
    _task(db, days=1, minutes=60, step="step-own")
    _task(db, days=1, step="step-need")
    _forecast(db)
    assert asked == [["step-need"]], "a task that carries its own estimate does not need the join"


def test_the_forecasts_own_caveat_no_longer_says_only_a_workflow_step_can_estimate():
    from domain.practice import capacity_risk as rule
    sentence = next(s for s in rule.NOT_FORECAST if "How long anything takes" in s)
    assert "the task itself carries an estimate" in sentence
    assert "workflow step recorded" not in sentence


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/workload — the one model the retired screen is merged into
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def workload(db, monkeypatch):
    monkeypatch.setattr(wl, "_get_db", lambda: db)
    _configured(monkeypatch)
    return _app(wl).get("/api/workload").json()["data"]


def _configured(monkeypatch, hours=45):
    """`capacity_repo` answers from its own in-memory store in mock mode, so the
    configured week is stated through it rather than seeded into FakeDB."""
    monkeypatch.setattr(wl.capacity_repo, "capacity_map",
                        lambda firm_id: {"u1": {"weekly_capacity_hours": hours,
                                                "max_concurrent_tasks": 15}})


def _member(payload, uid):
    return next(m for m in payload["members"] if m["user_id"] == uid)


def test_each_person_carries_what_their_open_work_is_expected_to_take(db, monkeypatch):
    _task(db, days=1, minutes=180, assignee="u1")
    _task(db, days=2, minutes=60, assignee="u1")
    _task(db, days=3, assignee="u1")
    _task(db, days=4, assignee="u1", status="completed", minutes=999)
    monkeypatch.setattr(wl, "_get_db", lambda: db)
    _configured(monkeypatch)
    asha = _member(_app(wl).get("/api/workload").json()["data"], "u1")
    assert asha["active_tasks"] == 3
    assert asha["estimated_open_minutes"] == 240, "recorded estimates, open tasks only"
    assert asha["open_tasks_without_estimate"] == 1, "counted, never averaged over"
    assert asha["weekly_capacity_hours"] == 45, "the capacity is the configured one, not a role constant"


def test_a_person_carries_their_open_tasks_earliest_due_first_and_bounded(db, monkeypatch):
    for d in range(12):
        _task(db, days=20 - d, assignee="u1", title=f"t{d}")
    _task(db, days=0, assignee="u1", title="undated-last").update({"due_date": None})
    monkeypatch.setattr(wl, "_get_db", lambda: db)
    asha = _member(_app(wl).get("/api/workload").json()["data"], "u1")
    shown = asha["open_tasks"]
    assert len(shown) == wl.OPEN_TASKS_SHOWN_PER_MEMBER
    assert [t["due_date"] for t in shown] == sorted(t["due_date"] for t in shown), "earliest first"
    assert asha["active_tasks"] == 13, "the count is the whole truth, the list is what fits on a card"
    assert all(t["title"] != "undated-last" for t in shown), "an undated task goes last"


def test_the_unassigned_backlog_is_served_with_its_own_estimate(db, monkeypatch):
    _task(db, days=1, minutes=120)
    _task(db, days=2)
    _task(db, days=3, assignee="u1", minutes=60)
    monkeypatch.setattr(wl, "_get_db", lambda: db)
    data = _app(wl).get("/api/workload").json()["data"]
    un = data["unassigned"]
    assert un["count"] == 2 and un["estimated_minutes"] == 120 and un["without_estimate"] == 1
    assert len(un["tasks"]) == 2 and all("estimated_minutes" in t for t in un["tasks"])


def test_a_reassigned_task_leaves_the_old_persons_count(db, monkeypatch, made):
    """Reassigning through PATCH moves both columns, so the workload figures —
    which read `assignee_id` first — follow it."""
    row = _task(db, days=1, assignee="u1", minutes=60)
    made.stored[row["id"]] = row
    monkeypatch.setattr(tr.task_repo, "update",
                        lambda tid, data, *a, **k: db.rows("tasks")[0].update(data) or db.rows("tasks")[0])
    monkeypatch.setattr(wl, "_get_db", lambda: db)
    assert _member(_app(wl).get("/api/workload").json()["data"], "u1")["active_tasks"] == 1
    assert _app(tr).patch(f"/api/tasks/{row['id']}", json={"assigned_to": "u2"}).status_code == 200
    data = _app(wl).get("/api/workload").json()["data"]
    assert _member(data, "u1")["active_tasks"] == 0
    assert _member(data, "u2")["active_tasks"] == 1
