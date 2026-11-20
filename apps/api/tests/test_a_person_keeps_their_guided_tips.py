"""A person keeps their guided tips: whether they want them, and which they have closed (POST-A-531, migration 774).

WHAT WAS MISSING
    The owner, on the live Test Firm on 20-11-2026, could not find where a firm keeps its own books and asked for the product to show a
    new CA round, with a switch to turn that off. Nothing kept a person-level preference of that kind except the first-run card's
    dismissal. A browser's own storage would show every tip again on the next device.

WHAT IS ASSERTED
    * the rule: never chosen answers the default (on) and says it is not the person's choice; a tip's id is a slug; closing a tip twice is
      closing it once; the list is bounded and drops its oldest; a stored value that is not a tip's id never reaches a screen;
    * the routes act on the CALLER'S OWN row only: a colleague's row, and a row of another firm, are never read or written;
    * the switch is a strict boolean, a tip id that is not a slug is a 422 with a sentence, and a caller with no row is refused and
      nothing is written;
    * "show them all again" empties the list and leaves the switch where the person put it;
    * every staff role may use them (a tip is for whoever is looking at the screen).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.guided_tips as guided_tips
import services.guided_tips_service as svc
from core.auth import get_current_user
from domain.guidance import tips as rule
from tests.e2e_harness import FakeDB

FIRM, OTHER = "firm-gt-1", "firm-gt-2"
PARTNER = {"id": "u-p1", "firm_id": FIRM, "role": "Partner", "email": "p1@f.in", "auth_user_id": "a-p1"}
MANAGER = {"id": "u-m1", "firm_id": FIRM, "role": "Manager", "email": "m@f.in", "auth_user_id": "a-m1"}
EXECUTIVE = {"id": "u-e1", "firm_id": FIRM, "role": "Executive", "email": "e@f.in", "auth_user_id": "a-e1"}
REVIEWER = {"id": "u-r1", "firm_id": FIRM, "role": "Reviewer", "email": "r@f.in", "auth_user_id": "a-r1"}
STRANGER = {"id": "u-ghost", "firm_id": FIRM, "role": "Partner", "email": "g@f.in", "auth_user_id": "a-g"}
RIVAL = {"id": "u-x1", "firm_id": OTHER, "role": "Partner", "email": "x1@r.in", "auth_user_id": "a-x1"}
# A person whose id is real, presented under another firm: the id alone must not find the row.
IMPOSTOR = {"id": "u-p1", "firm_id": OTHER, "role": "Partner", "email": "p1@f.in", "auth_user_id": "a-p1"}


# ── the rule ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_never_chosen_is_the_default_and_says_it_is_not_a_choice():
    assert rule.state({"guided_tips_on": None, "guided_tips_seen": []}) == {"on": True, "chosen": False, "seen": []}
    assert rule.state({}) == {"on": True, "chosen": False, "seen": []}, "a row read before the columns existed is 'never chosen'"


@pytest.mark.parametrize("stored, on", [(True, True), (False, False)])
def test_a_choice_is_kept_as_chosen(stored, on):
    assert rule.state({"guided_tips_on": stored, "guided_tips_seen": []}) == {"on": on, "chosen": True, "seen": []}


@pytest.mark.parametrize("tip_id", ["own-books", "a1", "add-client-2", "x" * rule.MAX_TIP_ID])
def test_a_slug_is_a_tip_id(tip_id):
    assert rule.tip_id_problem(tip_id) is None


@pytest.mark.parametrize("tip_id", ["", None, 7, "Own-Books", "own books", "own--books", "-own", "own-", "own_books",
                                    "<script>", "x" * (rule.MAX_TIP_ID + 1)])
def test_anything_else_is_refused_in_a_sentence(tip_id):
    problem = rule.tip_id_problem(tip_id)
    assert problem and problem.endswith(".")


def test_closing_a_tip_twice_is_closing_it_once_and_order_is_kept():
    assert rule.with_seen(["a", "b"], "c") == ["a", "b", "c"]
    assert rule.with_seen(["a", "b"], "a") == ["a", "b"]


def test_the_list_is_bounded_and_drops_its_oldest():
    full = [f"t{i}" for i in range(rule.MAX_SEEN)]
    out = rule.with_seen(full, "newest")
    assert len(out) == rule.MAX_SEEN and out[-1] == "newest" and out[0] == "t1"


def test_a_stored_value_that_is_not_a_tip_id_never_reaches_a_screen():
    assert rule.clean_seen(["ok", "Not OK", 3, None, "ok", "also-ok"]) == ["ok", "also-ok"]
    assert rule.clean_seen(None) == [] and rule.clean_seen("own-books") == []


# ── the routes ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def world(monkeypatch):
    db = FakeDB()
    for uid, firm in (("u-p1", FIRM), ("u-m1", FIRM), ("u-e1", FIRM), ("u-r1", FIRM), ("u-x1", OTHER)):
        db.seed("users", {"id": uid, "firm_id": firm, "email": f"{uid}@f.in", "is_active": True, "status": "active",
                          "deleted_at": None, "guided_tips_on": None, "guided_tips_seen": []})
    monkeypatch.setattr(svc, "_db", lambda: db)
    # No acting client in a unit test: the privileged client is the same double, as it is in mock mode.
    monkeypatch.setattr(svc, "privileged_for", lambda client: client)
    return db


def _app(user):
    app = FastAPI()
    app.include_router(guided_tips.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


def _row(db, user_id):
    return next(r for r in db.rows("users") if r["id"] == user_id)


def _untouched(db, *user_ids):
    return all(_row(db, u)["guided_tips_on"] is None and _row(db, u)["guided_tips_seen"] == [] for u in user_ids)


def test_a_person_who_never_chose_is_shown_tips(world):
    res = _app(PARTNER).get("/api/guided-tips")
    assert res.status_code == 200, res.text
    assert res.json() == {"success": True, "data": {"on": True, "chosen": False, "seen": []}, "error": None}


def test_turning_the_switch_off_writes_the_callers_own_row_only(world):
    res = _app(PARTNER).put("/api/guided-tips", json={"on": False})
    assert res.status_code == 200, res.text
    assert res.json()["data"] == {"on": False, "chosen": True, "seen": []}
    assert _row(world, "u-p1")["guided_tips_on"] is False
    assert _untouched(world, "u-m1", "u-e1", "u-r1", "u-x1")
    assert _app(MANAGER).get("/api/guided-tips").json()["data"]["on"] is True, "a colleague's switch is their own"


def test_turning_it_back_on_is_a_choice_too(world):
    _app(PARTNER).put("/api/guided-tips", json={"on": False})
    assert _app(PARTNER).put("/api/guided-tips", json={"on": True}).json()["data"] == {"on": True, "chosen": True, "seen": []}


@pytest.mark.parametrize("body", [{"on": "false"}, {"on": 0}, {"on": None}, {}, {"off": True}])
def test_the_switch_takes_a_real_boolean_and_nothing_else(world, body):
    res = _app(PARTNER).put("/api/guided-tips", json=body)
    assert res.status_code == 422
    assert _untouched(world, "u-p1")


def test_closing_a_tip_keeps_it_closed_and_touches_nobody_else(world):
    assert _app(PARTNER).post("/api/guided-tips/seen", json={"tip_id": "own-books"}).json()["data"]["seen"] == ["own-books"]
    again = _app(PARTNER).post("/api/guided-tips/seen", json={"tip_id": "own-books"})
    assert again.status_code == 200 and again.json()["data"]["seen"] == ["own-books"]
    assert _app(PARTNER).post("/api/guided-tips/seen", json={"tip_id": "add-client"}).json()["data"]["seen"] == ["own-books", "add-client"]
    assert _row(world, "u-p1")["guided_tips_seen"] == ["own-books", "add-client"]
    assert _row(world, "u-p1")["guided_tips_on"] is None, "closing a tip is not a decision about the switch"
    assert _untouched(world, "u-m1", "u-e1", "u-r1", "u-x1")
    assert _app(PARTNER).get("/api/guided-tips").json()["data"] == {"on": True, "chosen": False, "seen": ["own-books", "add-client"]}


@pytest.mark.parametrize("tip_id", ["Own Books", "own--books", "", "x" * 65, "../etc"])
def test_a_tip_id_that_is_not_a_slug_is_a_422_with_a_sentence_and_nothing_is_written(world, tip_id):
    res = _app(PARTNER).post("/api/guided-tips/seen", json={"tip_id": tip_id})
    assert res.status_code == 422 and "tip" in res.json()["detail"].lower()
    assert _untouched(world, "u-p1")


def test_show_them_all_again_empties_the_list_and_leaves_the_switch(world):
    app = _app(PARTNER)
    app.put("/api/guided-tips", json={"on": False})
    app.post("/api/guided-tips/seen", json={"tip_id": "own-books"})
    res = app.post("/api/guided-tips/show-again")
    assert res.status_code == 200 and res.json()["data"] == {"on": False, "chosen": True, "seen": []}
    assert _row(world, "u-p1")["guided_tips_seen"] == [] and _row(world, "u-p1")["guided_tips_on"] is False


@pytest.mark.parametrize("user", [PARTNER, MANAGER, EXECUTIVE, REVIEWER])
def test_every_staff_role_keeps_its_own_tips(world, user):
    app = _app(user)
    assert app.get("/api/guided-tips").status_code == 200
    assert app.post("/api/guided-tips/seen", json={"tip_id": "deadlines"}).status_code == 200
    assert _row(world, user["id"])["guided_tips_seen"] == ["deadlines"]


@pytest.mark.parametrize("call", [
    lambda app: app.get("/api/guided-tips"),
    lambda app: app.put("/api/guided-tips", json={"on": False}),
    lambda app: app.post("/api/guided-tips/seen", json={"tip_id": "own-books"}),
    lambda app: app.post("/api/guided-tips/show-again"),
])
@pytest.mark.parametrize("user", [STRANGER, IMPOSTOR])
def test_a_caller_with_no_row_in_their_firm_is_refused_and_nothing_is_written(world, user, call):
    """STRANGER has no row at all; IMPOSTOR carries a real person's id under another firm. Neither finds a row: the id alone is not enough."""
    res = call(_app(user))
    assert res.status_code == 403 and "team member" in res.json()["detail"]
    assert _untouched(world, "u-p1", "u-m1", "u-e1", "u-r1", "u-x1")


def test_a_caller_of_another_firm_reaches_only_their_own_row(world):
    assert _app(RIVAL).put("/api/guided-tips", json={"on": False}).status_code == 200
    assert _row(world, "u-x1")["guided_tips_on"] is False
    assert _untouched(world, "u-p1", "u-m1", "u-e1", "u-r1")


def test_every_query_names_the_person_and_the_firm():
    """The service role bypasses row security, so the two filters are the isolation. Read off the source so a query added later is held."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(svc))
    chains = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
            text = ast.unparse(node)
            chains += 1
            assert ".eq('id', user_id)" in text and ".eq('firm_id', firm_id)" in text, text
    assert chains >= 2, "the scan found no query to judge"
