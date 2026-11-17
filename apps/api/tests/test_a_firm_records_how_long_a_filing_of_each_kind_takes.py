"""A firm states how long one filing of each obligation type takes, and Team Workload's one capacity model counts it (POST-A-212).

WHAT WAS WRONG
    A task carries its own whole-minute estimate (migration 452) and an obligation worked as a task is counted once, as that task. An
    obligation NOT worked as a task had no estimate and nothing could hold one, so the forecast saw the work as dated and weightless.

WHAT THIS HOLDS
    * the firm's figure for a type reaches the forecast as hours on every open obligation of that type, per obligation;
    * a type the firm has not stated stays an unknown, counted beside the hours and never averaged and never zero;
    * an obligation worked as a task is still counted once, by the task (the fold is untouched);
    * the figure is whole minutes above zero and the type a plain word, refused in a sentence otherwise;
    * the doors are `workload` read and write (Manager and above, the capacity doors' own tier), the firm's own, audited under the sign-in id;
    * the list names the calendar's types that have no figure yet, and clearing a figure makes the type an unknown again.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import repositories.compliance_effort_repository as repo_mod
from core.auth import get_current_user
from domain.practice import obligation_estimate as rule
from repositories.compliance_effort_repository import compliance_effort_repo
from services import capacity_risk_service as svc
from tests.e2e_harness import FakeDB

FIRM = "66666666-6666-4666-8666-666666666666"
CLIENT = "77777777-7777-4777-8777-777777777777"
MONDAY = date(2026, 9, 28)
PARTNER = {"firm_id": FIRM, "id": "u1", "role": "Partner", "email": "p@f.test", "auth_user_id": "auth-1"}


@pytest.fixture(autouse=True)
def _clean():
    repo_mod._MOCK_ROWS.clear()
    yield
    repo_mod._MOCK_ROWS.clear()


def _db():
    d = FakeDB()
    d.seed("users", {"id": "u1", "firm_id": FIRM, "is_active": True})
    return d


def _obligation(db, *, days=2, kind="GSTR3B", task_id=None):
    return db.seed("compliance_calendar", {
        "firm_id": FIRM, "client_id": CLIENT, "filing_status": "pending", "task_id": task_id, "compliance_type": kind,
        "due_date": (MONDAY + timedelta(days=days)).isoformat()})


def _week0(out):
    return out["weeks"][0]


def test_a_stated_figure_adds_its_hours_per_obligation():
    db = _db()
    for _ in range(3):
        _obligation(db)
    compliance_effort_repo.upsert(FIRM, "GSTR3B", 90, "u1")

    w = _week0(svc.capacity_risk(db, PARTNER, today=MONDAY))

    assert w["compliance_due"] == 3 and w["estimated_hours"] == 4.5 and w["items_without_an_estimate"] == 0


def test_a_kind_the_firm_has_not_stated_stays_an_unknown_and_is_never_averaged():
    db = _db()
    _obligation(db, kind="GSTR3B")
    _obligation(db, kind="TDS26Q")
    compliance_effort_repo.upsert(FIRM, "GSTR3B", 60, "u1")

    w = _week0(svc.capacity_risk(db, PARTNER, today=MONDAY))

    assert w["estimated_hours"] == 1.0 and w["items_without_an_estimate"] == 1


def test_another_firms_figure_is_not_read():
    db = _db()
    _obligation(db)
    compliance_effort_repo.upsert("some-other-firm", "GSTR3B", 600, "u9")
    w = _week0(svc.capacity_risk(db, PARTNER, today=MONDAY))
    assert w["estimated_hours"] in (0, 0.0, None) and w["items_without_an_estimate"] == 1


def test_an_obligation_worked_as_a_task_is_counted_once_by_the_task():
    db = _db()
    t = db.seed("tasks", {"firm_id": FIRM, "client_id": CLIENT, "status": "todo", "title": "GSTR-3B",
                          "due_date": (MONDAY + timedelta(days=2)).isoformat(), "estimated_minutes": 30})
    _obligation(db, task_id=t["id"])
    compliance_effort_repo.upsert(FIRM, "GSTR3B", 600, "u1")

    w = _week0(svc.capacity_risk(db, PARTNER, today=MONDAY))

    assert w["items_due"] == 1 and w["estimated_hours"] == 0.5


@pytest.mark.parametrize("bad", [0, -5, True, 1.5, "12.5", None, rule.MAX_MINUTES + 1])
def test_minutes_are_whole_and_above_zero(bad):
    with pytest.raises(ValueError):
        rule.check_minutes(bad)


@pytest.mark.parametrize("word,ok", [("GSTR-3B", True), ("  TDS 26Q ", True), ("", False), ("   ", False), ("x" * 61, False),
                                     ("a\nb", False), (None, False), (7, False)])
def test_the_type_is_a_plain_word(word, ok):
    assert (rule.clean_type(word) is not None) is ok


# ── the doors ────────────────────────────────────────────────────────────────

@pytest.fixture
def api(monkeypatch):
    import routers.workload as wl
    import services.audit_service as au
    db = _db()
    _obligation(db, kind="GSTR3B")
    _obligation(db, kind="TDS26Q")
    monkeypatch.setattr(wl, "_get_db", lambda: db)
    audited: list = []
    monkeypatch.setattr(au, "log_event", lambda *a, **k: audited.append((a, k)))
    app = FastAPI()
    app.include_router(wl.router)
    state = {"user": {**PARTNER}}
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    return TestClient(app, raise_server_exceptions=False), state, audited


def test_the_firm_states_a_figure_and_it_is_listed_and_audited(api):
    client, _state, audited = api
    r = client.put("/api/workload/obligation-estimates", json={"compliance_type": "GSTR3B", "estimated_minutes": 45})
    assert r.status_code == 200, r.text
    got = client.get("/api/workload/obligation-estimates").json()["data"]
    assert got["estimates"][0]["compliance_type"] == "GSTR3B" and got["estimates"][0]["estimated_minutes"] == 45
    assert got["types_without_an_estimate"] == ["TDS26Q"]                   # the calendar's other kind still has no figure
    (args, kwargs), = audited
    assert args[1:4] == ("compliance_effort_estimate", args[2], "obligation_estimate_set") and kwargs["actor_id"] == "auth-1"


def test_a_second_save_replaces_and_clearing_makes_it_an_unknown_again(api):
    client, _state, audited = api
    client.put("/api/workload/obligation-estimates", json={"compliance_type": "GSTR3B", "estimated_minutes": 45})
    client.put("/api/workload/obligation-estimates", json={"compliance_type": "GSTR3B", "estimated_minutes": 50})
    assert [e["estimated_minutes"] for e in client.get("/api/workload/obligation-estimates").json()["data"]["estimates"]] == [50]
    assert client.delete("/api/workload/obligation-estimates", params={"compliance_type": "GSTR3B"}).status_code == 200
    got = client.get("/api/workload/obligation-estimates").json()["data"]
    assert got["estimates"] == [] and "GSTR3B" in got["types_without_an_estimate"]
    assert client.delete("/api/workload/obligation-estimates", params={"compliance_type": "GSTR3B"}).status_code == 404


@pytest.mark.parametrize("body", [{"compliance_type": "GSTR3B", "estimated_minutes": 0},
                                  {"compliance_type": "GSTR3B", "estimated_minutes": -3},
                                  {"compliance_type": "", "estimated_minutes": 30}])
def test_a_bad_figure_or_type_is_refused_in_a_sentence(api, body):
    client, _state, _audited = api
    r = client.put("/api/workload/obligation-estimates", json=body)
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)
    assert client.get("/api/workload/obligation-estimates").json()["data"]["estimates"] == []


@pytest.mark.parametrize("role,reads,writes", [("Partner", True, True), ("Manager", True, True), ("Executive", False, False),
                                               ("Reviewer", False, False)])
def test_who_may_read_and_who_may_write(api, role, reads, writes):
    client, state, _audited = api
    state["user"] = {**PARTNER, "role": role}
    assert (client.get("/api/workload/obligation-estimates").status_code == 200) is reads
    r = client.put("/api/workload/obligation-estimates", json={"compliance_type": "GSTR3B", "estimated_minutes": 30})
    assert (r.status_code == 200) is writes, (role, r.status_code)
