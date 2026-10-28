"""A person can dismiss the first-run checklist for good (POST-A-002, migration 555).

WHAT WAS MISSING
    The dashboard's "Getting started" card ticks itself from the firm's own rows and stays until the firm has done its first four things.
    The browser could COLLAPSE it, per device, and that was all: a Partner who did not want it had it on every screen, for good. The card's
    own module said so ("No dismiss for good. That needs a column") and no migration number had been left for it.

WHAT IS ASSERTED
    * the rule: a dismissal hides the card whatever the steps say, a dismissal that could not be READ is not one (the card stays and the
      answer says `dismissed: None`), and the answer always carries the key;
    * the service reads the CALLER's own row only, so a second Partner who has not dismissed it still sees it, and a table that cannot be
      read leaves the card to its steps;
    * `POST /api/onboarding/first-run/dismiss` writes the caller's own `users` row and nobody else's, in their own firm only, keeps the first
      stamp when asked twice, is refused for the roles that are not shown the card, and writes nothing when the caller has no row;
    * the next `GET /api/onboarding/status` for that person says `visible: false, dismissed: true`.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.onboarding as onboarding
import services.first_run_service as svc
from core.auth import get_current_user
from domain.onboarding import first_run as rule
from tests.e2e_harness import FakeDB

FIRM, OTHER = "firm-dm-1", "firm-dm-2"
BORN = "2026-09-01T04:00:00+00:00"
PARTNER = {"id": "u-p1", "firm_id": FIRM, "role": "Partner", "email": "p1@f.in", "auth_user_id": "a-p1"}
PARTNER_2 = {"id": "u-p2", "firm_id": FIRM, "role": "Partner", "email": "p2@f.in", "auth_user_id": "a-p2"}
MANAGER = {"id": "u-m1", "firm_id": FIRM, "role": "Manager", "email": "m@f.in", "auth_user_id": "a-m1"}
EXECUTIVE = {"id": "u-e1", "firm_id": FIRM, "role": "Executive", "email": "e@f.in", "auth_user_id": "a-e1"}
STRANGER = {"id": "u-ghost", "firm_id": FIRM, "role": "Partner", "email": "g@f.in", "auth_user_id": "a-g"}
RIVAL = {"id": "u-x1", "firm_id": OTHER, "role": "Partner", "email": "x1@r.in", "auth_user_id": "a-x1"}


def _facts(**done):
    return {k: done.get(k, rule.Fact(False)) for k in rule.STEP_IDS}


# ── the rule ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_dismissal_hides_a_card_the_steps_would_still_show():
    out = rule.build(_facts(), firm_created_at=BORN, dismissed=True)
    assert out["complete"] is False and out["done_count"] == 0
    assert out["dismissed"] is True and out["visible"] is False


@pytest.mark.parametrize("dismissed", [False, None])
def test_no_dismissal_and_an_unreadable_one_leave_the_card_to_its_steps(dismissed):
    out = rule.build(_facts(), firm_created_at=BORN, dismissed=dismissed)
    assert out["visible"] is True and out["dismissed"] is dismissed


def test_the_answer_always_carries_the_key_and_a_default_call_is_not_a_dismissal():
    out = rule.build(_facts())
    assert "dismissed" in out and out["dismissed"] is None and out["visible"] is True


def test_a_dismissal_does_not_change_what_the_steps_say():
    plain = rule.build(_facts(first_client=rule.Fact(True, BORN)), firm_created_at=BORN)
    gone = rule.build(_facts(first_client=rule.Fact(True, BORN)), firm_created_at=BORN, dismissed=True)
    for key in ("steps", "total", "done_count", "complete", "next_step", "unreadable", "minutes_to_first_invoice"):
        assert plain[key] == gone[key], key


# ── the service ────────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def world(monkeypatch):
    db = FakeDB()
    db.seed("firms", {"id": FIRM, "name": "Sharma & Co", "created_at": BORN})
    db.seed("firms", {"id": OTHER, "name": "Rival & Co", "created_at": BORN})
    for uid, firm in (("u-p1", FIRM), ("u-p2", FIRM), ("u-m1", FIRM), ("u-e1", FIRM), ("u-x1", OTHER)):
        db.seed("users", {"id": uid, "firm_id": firm, "email": f"{uid}@f.in", "is_active": True, "status": "active",
                          "created_at": BORN, "deleted_at": None, "first_run_dismissed_at": None})
    monkeypatch.setattr(svc, "_USE_MOCK", False)
    monkeypatch.setattr(svc, "_db", lambda: db)
    monkeypatch.setattr(onboarding, "get_service_supabase", lambda: db)
    return db


def _stamp(db, user_id):
    return next(r for r in db.rows("users") if r["id"] == user_id)["first_run_dismissed_at"]


def test_the_service_reads_the_callers_own_row_only(world):
    next(r for r in world.rows("users") if r["id"] == "u-p1")["first_run_dismissed_at"] = "2026-09-02T00:00:00+00:00"
    mine = svc.first_run(FIRM, "u-p1")
    assert mine["dismissed"] is True and mine["visible"] is False
    colleague = svc.first_run(FIRM, "u-p2")
    assert colleague["dismissed"] is False and colleague["visible"] is True, "a second Partner who has not dismissed it still sees it"


def test_a_caller_with_no_row_or_no_id_is_unknown_and_the_card_stays(world):
    assert svc.first_run(FIRM, "u-nobody")["dismissed"] is None and svc.first_run(FIRM, "u-nobody")["visible"] is True
    assert svc.first_run(FIRM)["dismissed"] is None and svc.first_run(FIRM)["visible"] is True


def test_a_row_of_another_firm_does_not_count_for_this_one(world):
    next(r for r in world.rows("users") if r["id"] == "u-x1")["first_run_dismissed_at"] = "2026-09-02T00:00:00+00:00"
    assert svc.first_run(FIRM, "u-x1")["dismissed"] is None, "the user id belongs to another firm: unknown here, never a dismissal"


def test_a_dismissal_that_cannot_be_read_leaves_the_card_to_its_steps(world, monkeypatch):
    def broken(db, firm_id, user_id):
        raise RuntimeError("permission denied for table users")
    monkeypatch.setattr(svc, "_dismissed", broken)
    out = svc.first_run(FIRM, "u-p1")
    assert out["dismissed"] is None and out["visible"] is True


# ── the endpoint ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def _app(user):
    app = FastAPI()
    app.include_router(onboarding.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


def test_a_partner_dismisses_the_card_and_only_their_own_row_is_written(world):
    res = _app(PARTNER).post("/api/onboarding/first-run/dismiss")
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["dismissed"] is True and data["dismissed_at"] == _stamp(world, "u-p1")
    for other in ("u-p2", "u-m1", "u-e1", "u-x1"):
        assert _stamp(world, other) is None, f"{other} was written"


def test_after_dismissing_the_status_says_so_for_that_person_and_not_for_a_colleague(world):
    _app(PARTNER).post("/api/onboarding/first-run/dismiss")
    mine = _app(PARTNER).get("/api/onboarding/status").json()["data"]["first_run"]
    theirs = _app(PARTNER_2).get("/api/onboarding/status").json()["data"]["first_run"]
    assert mine["dismissed"] is True and mine["visible"] is False
    assert theirs["dismissed"] is False and theirs["visible"] is True
    assert mine["steps"] == theirs["steps"], "a dismissal changes what is shown, not what is true"


def test_asking_twice_keeps_the_first_stamp(world):
    first = _app(PARTNER).post("/api/onboarding/first-run/dismiss").json()["data"]["dismissed_at"]
    row = next(r for r in world.rows("users") if r["id"] == "u-p1")
    row["first_run_dismissed_at"] = "2026-09-09T09:09:09+00:00"      # a stamp from an earlier time
    again = _app(PARTNER).post("/api/onboarding/first-run/dismiss").json()["data"]["dismissed_at"]
    assert first != again and again == "2026-09-09T09:09:09+00:00", "the second request must not overwrite the first stamp"


def test_a_manager_can_dismiss_it_too(world):
    assert _app(MANAGER).post("/api/onboarding/first-run/dismiss").status_code == 200
    assert _stamp(world, "u-m1") is not None


def test_a_role_that_is_not_shown_the_card_is_refused_and_nothing_is_written(world):
    res = _app(EXECUTIVE).post("/api/onboarding/first-run/dismiss")
    assert res.status_code == 403
    assert all(r["first_run_dismissed_at"] is None for r in world.rows("users"))


def test_a_caller_with_no_users_row_writes_nothing_and_is_told_so(world):
    res = _app(STRANGER).post("/api/onboarding/first-run/dismiss")
    assert res.status_code == 409 and "nothing was changed" in res.json()["detail"]
    assert all(r["first_run_dismissed_at"] is None for r in world.rows("users"))


def test_a_caller_of_another_firm_cannot_reach_this_firms_rows(world):
    res = _app(RIVAL).post("/api/onboarding/first-run/dismiss")
    assert res.status_code == 200
    assert _stamp(world, "u-x1") is not None
    assert all(_stamp(world, u) is None for u in ("u-p1", "u-p2", "u-m1", "u-e1"))
