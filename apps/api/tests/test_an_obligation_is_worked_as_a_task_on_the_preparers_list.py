"""An open compliance obligation can be worked as a task on the preparer's list, shown once, and completing the task takes the
obligation to review (POST-A-206, second slice).

WHAT WAS WRONG
    My Work showed a person's obligations beside their tasks and nothing joined them: an obligation could not be put on a task list,
    and `tasks.compliance_record_id` (migration 003) was written by nothing.

WHAT IS HELD
    * the door makes ONE task, linked to the obligation, titled from its label, due on its due date, for its client, assigned to its
      preparer when they can open the client and to nobody otherwise; a second press answers the same task; a settled obligation is
      refused in words; nothing on the obligation moves;
    * the door is `compliance` write behind the obligation's scope, and making a task needs task write too, asked per person;
    * completing the task moves the obligation to Ready For Review through the transition door from each status it can be worked
      from, leaves one already there or beyond, does nothing for a person without compliance write and says so, and never fails the
      task's own change; a task that works no obligation answers as before;
    * My Obligations shows an obligation worked as the person's own task once, as the task, and counts it; one worked as somebody
      else's task stays and names it;
    * My Work offers the button only to someone who may write compliance and tasks.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user
from mock_data import MOCK_COMPLIANCE_RECORDS, MOCK_TASKS, TASK_INDEX
from repositories.compliance_records_repository import compliance_records_repo
from services import compliance_obligation_service as obligations
from services import obligation_task

FIRM = "F-206T"
PREP = "user-prep"
WEB = Path(__file__).resolve().parents[2] / "web"


def _user(role="Partner", uid="u-actor", **extra):
    return {"id": uid, "firm_id": FIRM, "role": role, "email": f"{role.lower()}@f.test", "auth_user_id": f"auth-{uid}", **extra}


@pytest.fixture
def world(monkeypatch):
    import routers.compliance_ops as ops
    import routers.tasks as tasks_router
    import services.audit_service as au
    import services.timeline_service as ts
    audited: list = []
    monkeypatch.setattr(au, "log_event", lambda *a, **k: audited.append((a, k)))
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(tasks_router, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(obligation_task, "_preparer_who_can_open",
                        lambda firm_id, record: record.get("preparer_id") if record.get("preparer_id") == PREP else None)
    app = FastAPI()
    app.include_router(ops.router)
    app.include_router(tasks_router.router)
    state = {"user": _user()}
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    before = list(MOCK_TASKS)
    yield TestClient(app, raise_server_exceptions=False), state, audited
    for t in [t for t in MOCK_TASKS if t not in before]:
        MOCK_TASKS.remove(t)
        TASK_INDEX.pop(t["id"], None)
    for rid in [r for r, rec in list(_index().items()) if rec.get("firm_id") == FIRM]:
        _drop(rid)


def _index():
    return {r["id"]: r for r in MOCK_COMPLIANCE_RECORDS}


def _drop(rid):
    for r in list(MOCK_COMPLIANCE_RECORDS):
        if r["id"] == rid:
            MOCK_COMPLIANCE_RECORDS.remove(r)


def _obl(status="Not Started", **over):
    row = {"firm_id": FIRM, "client_id": "C-1", "compliance_type": "GST", "obligation_type": "GSTR3B",
           "period_label": "GSTR-3B October 2026", "due_date": "2026-11-20", "status": status, "preparer_id": PREP}
    row.update(over)
    return compliance_records_repo.create(row)


def _work(client, rec):
    return client.post(f"/api/compliance/obligations/{rec['id']}/task")


def _row(rec):
    return compliance_records_repo.find_by_id(rec["id"])


# ── the door ────────────────────────────────────────────────────────────────

def test_it_makes_one_linked_task_from_the_obligation_and_moves_nothing_on_it(world):
    client, _state, audited = world
    rec = _obl()
    r = _work(client, rec)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    task = data["task"]
    assert data["created"] is True
    assert task["compliance_record_id"] == rec["id"] and task["client_id"] == "C-1" and task["firm_id"] == FIRM
    assert task["title"] == "Prepare GSTR-3B October 2026" and task["due_date"] == "2026-11-20"
    assert task["assigned_to"] == PREP and task["assignee_id"] == PREP and task["status"] == "todo"
    assert "its preparer" in data["message"]
    assert _row(rec)["status"] == "Not Started", "making the task moves nothing on the obligation"
    assert any(a[1:4] == ("task", task["id"], "create") for a, _k in audited)


def test_a_second_press_answers_the_same_task(world):
    client, _state, _audited = world
    rec = _obl()
    first = _work(client, rec).json()["data"]["task"]
    again = _work(client, rec).json()["data"]
    assert again["created"] is False and again["task"]["id"] == first["id"]
    assert sum(1 for t in MOCK_TASKS if t.get("compliance_record_id") == rec["id"]) == 1


def test_a_preparer_who_cannot_open_the_client_is_not_given_it(world):
    client, _state, _audited = world
    rec = _obl(preparer_id="someone-else")
    data = _work(client, rec).json()["data"]
    assert not data["task"].get("assigned_to") and "nobody yet" in data["message"]


@pytest.mark.parametrize("status", ["Filed", "Completed", "Not Required"])
def test_a_settled_obligation_is_refused_in_words(world, status):
    client, _state, _audited = world
    rec = _obl(status=status)
    r = _work(client, rec)
    assert r.status_code == 422 and "no work left" in r.json()["detail"]
    assert not any(t.get("compliance_record_id") == rec["id"] for t in MOCK_TASKS)


def test_another_firms_obligation_is_a_404(world):
    client, _state, _audited = world
    rec = _obl(firm_id="F-OTHER")
    assert _work(client, rec).status_code == 404
    _drop(rec["id"])


def test_the_door_needs_compliance_write_and_task_write(world, monkeypatch):
    client, state, _audited = world
    rec = _obl()
    state["user"] = _user("Reviewer")
    assert _work(client, rec).status_code == 403
    state["user"] = _user()
    import core.permissions as perms
    real = perms.can_user
    monkeypatch.setattr(perms, "can_user", lambda u, r, a: False if (r, a) == ("task", "write") else real(u, r, a))
    r = _work(client, rec)
    assert r.status_code == 403 and "write tasks" in r.json()["detail"]


# ── completing the task ─────────────────────────────────────────────────────

def _complete(client, task_id):
    client.patch(f"/api/tasks/{task_id}", json={"status": "in_progress"})
    return client.patch(f"/api/tasks/{task_id}", json={"status": "completed"})


@pytest.mark.parametrize("start", ["Not Started", "Awaiting Documents", "Overdue", "In Progress"])
def test_completing_the_task_moves_the_obligation_to_ready_for_review(world, start):
    client, _state, _audited = world
    rec = _obl(status=start)
    task = _work(client, rec).json()["data"]["task"]
    r = _complete(client, task["id"])
    assert r.status_code == 200, r.text
    answer = r.json()["data"]["compliance_obligation"]
    assert answer["state"] == "moved_to_review" and answer["moved"] is True
    assert _row(rec)["status"] == "Ready For Review"


@pytest.mark.parametrize("past", ["Ready For Review", "Ready To File"])
def test_an_obligation_already_at_review_or_beyond_is_left_and_said(world, past):
    client, _state, _audited = world
    rec = _obl(status="In Progress")
    task = _work(client, rec).json()["data"]["task"]
    compliance_records_repo.update(rec["id"], {"status": past})
    answer = _complete(client, task["id"]).json()["data"]["compliance_obligation"]
    assert answer["state"] == "already_at_review_or_beyond" and _row(rec)["status"] == past


def test_a_person_without_compliance_write_completes_the_task_and_is_told(world, monkeypatch):
    client, state, _audited = world
    rec = _obl()
    task = _work(client, rec).json()["data"]["task"]
    import core.permissions as perms
    real = perms.can_user
    monkeypatch.setattr(perms, "can_user", lambda u, r, a: False if (r, a) == ("compliance", "write") else real(u, r, a))
    r = _complete(client, task["id"])
    assert r.json()["data"]["task"]["status"] == "completed"
    answer = r.json()["data"]["compliance_obligation"]
    assert answer["state"] == "not_allowed" and "Compliance access" in answer["message"]
    assert _row(rec)["status"] == "Not Started"


def test_a_failure_moving_it_never_fails_the_task(world, monkeypatch):
    client, _state, _audited = world
    rec = _obl()
    task = _work(client, rec).json()["data"]["task"]

    def boom(*_a, **_k):
        raise RuntimeError("database away")
    monkeypatch.setattr(obligations, "transition", boom)
    r = _complete(client, task["id"])
    assert r.status_code == 200 and r.json()["data"]["task"]["status"] == "completed"
    assert r.json()["data"]["compliance_obligation"]["moved"] is False


def test_a_task_that_works_no_obligation_answers_as_before(world):
    client, _state, _audited = world
    from repositories.task_repository import task_repo
    tid = task_repo.create({"firm_id": FIRM, "client_id": "C-1", "title": "Plain task", "status": "todo"})["id"]
    data = _complete(client, tid).json()["data"]
    assert data["task"]["status"] == "completed" and "compliance_obligation" not in data


# ── shown once on My Work ───────────────────────────────────────────────────

def test_my_own_task_hides_the_obligation_and_is_counted(world):
    client, _state, _audited = world
    rec = _obl()
    _work(client, rec)
    out = obligations.my_obligations(FIRM, PREP, today=date(2026, 11, 18))
    assert rec["id"] not in {o["id"] for o in out["obligations"]} and out["worked_as_your_task"] == 1


def test_somebody_elses_task_leaves_it_on_the_reviewers_list_and_names_the_task(world):
    client, _state, _audited = world
    rec = _obl(reviewer_id="user-rev")
    task = _work(client, rec).json()["data"]["task"]
    out = obligations.my_obligations(FIRM, "user-rev", today=date(2026, 11, 18))
    row = next(o for o in out["obligations"] if o["id"] == rec["id"])
    assert row["task_id"] == task["id"] and out["worked_as_your_task"] == 0


def test_a_completed_task_no_longer_hides_it(world):
    client, _state, _audited = world
    rec = _obl()
    task = _work(client, rec).json()["data"]["task"]
    compliance_records_repo.update(rec["id"], {"status": "Ready For Review"})
    client.patch(f"/api/tasks/{task['id']}", json={"status": "in_progress"})
    client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"})
    out = obligations.my_obligations(FIRM, PREP, today=date(2026, 11, 18))
    assert rec["id"] in {o["id"] for o in out["obligations"]} and out["worked_as_your_task"] == 0


# ── the screen ──────────────────────────────────────────────────────────────

def test_my_work_offers_the_button_to_who_the_door_admits_and_shows_the_count():
    page = (WEB / "app/work/page.tsx").read_text()
    assert 'can("compliance", "write")' in page and 'can("task", "write")' in page
    assert "workObligationAsTask" in page and "workedAsYourTask" in page
