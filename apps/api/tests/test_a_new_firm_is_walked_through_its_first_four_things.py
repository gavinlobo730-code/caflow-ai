"""market_and_trust-16 — a new firm sees a checklist that ticks itself.

WHAT WAS WRONG
    After sign-up a new owner landed on a welcome card of five links that was shown
    ONCE (`?welcome=1`) and then never again. Nothing tracked progress, so a firm that
    closed the tab after adding a client could not see that an invoice and a statement
    were still ahead of it, and nothing could say how long the first sitting took.
    `GET /api/onboarding/status` existed and no screen called it.

WHAT IS ASSERTED
    * the rule (`domain/onboarding/first_run`): the four steps in the order a firm
      meets the product; a step's `done` is True / False / NONE, and None (unreadable)
      is never counted as done and never reads as not done; `visible` is the server's
      answer — shown while there is something to do and something could be read;
    * each step ticks off the firm's OWN data and nothing else: the practice's own
      client record is not a client, a draft is not an invoice, a carried-over
      opening document is not an invoice somebody raised here (and does not hide a real
      one sorting after it — LIMIT 1 is why the filter is in the query), a deactivated
      or deleted colleague is not a colleague, and another firm's rows tick nothing;
    * it ticks itself — rows arriving change the answer with nothing stored — and so it
      PERSISTS across logins: a second Partner, or the same one next week, sees the
      same ticks;
    * a table that cannot be read leaves that one step unknown and the others intact;
    * `GET /api/onboarding/status` serves it to Partner and Manager and refuses the
      rest, and its older `checks` are derived from the same facts, so a deactivated
      colleague cannot count in one and not the other;
    * the time to first value is derived from two timestamps that already exist.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.onboarding as onboarding
import services.first_run_service as svc
from core.auth import get_current_user
from core.permissions import PERMISSIONS, Role
from domain.onboarding import first_run as rule
from tests.e2e_harness import FakeDB

FIRM, OTHER = "firm-fr-1", "firm-fr-2"
BORN = "2026-09-01T04:00:00+00:00"
PARTNER = {"id": "u-p1", "firm_id": FIRM, "role": "Partner", "email": "p1@f.in", "auth_user_id": "a-p1"}
PARTNER_2 = {"id": "u-p2", "firm_id": FIRM, "role": "Partner", "email": "p2@f.in", "auth_user_id": "a-p2"}
MANAGER = {"id": "u-m1", "firm_id": FIRM, "role": "Manager", "email": "m@f.in", "auth_user_id": "a-m1"}
EXECUTIVE = {"id": "u-e1", "firm_id": FIRM, "role": "Executive", "email": "e@f.in", "auth_user_id": "a-e1"}
REVIEWER = {"id": "u-r1", "firm_id": FIRM, "role": "Reviewer", "email": "r@f.in", "auth_user_id": "a-r1"}


# ══════════════════════════════════════════════════════════════════════════════
# the rule
# ══════════════════════════════════════════════════════════════════════════════

def test_the_steps_are_the_four_the_finding_names_in_the_order_a_firm_meets_them():
    assert rule.STEP_IDS == ("first_client", "first_invoice", "first_statement", "invite_colleague")
    assert all(s.title and s.why for s in rule.STEPS)


def _facts(**done):
    return {k: done.get(k, rule.Fact(False)) for k in rule.STEP_IDS}


def test_a_fresh_firm_has_four_things_to_do_and_a_first_one():
    out = rule.build(_facts(), firm_created_at=BORN)
    assert out["done_count"] == 0 and out["total"] == 4
    assert out["complete"] is False and out["visible"] is True
    assert out["next_step"] == "first_client"
    assert [s["done"] for s in out["steps"]] == [False] * 4
    assert out["unreadable"] == [] and out["minutes_to_first_invoice"] is None


def test_the_next_step_is_the_first_one_not_yet_done():
    out = rule.build(_facts(first_client=rule.Fact(True, BORN)), firm_created_at=BORN)
    assert out["next_step"] == "first_invoice" and out["done_count"] == 1
    out = rule.build(_facts(first_client=rule.Fact(True, BORN), first_invoice=rule.Fact(True, BORN)))
    assert out["next_step"] == "first_statement"


def test_a_firm_that_has_done_all_four_sees_nothing():
    out = rule.build({k: rule.Fact(True, BORN) for k in rule.STEP_IDS}, firm_created_at=BORN)
    assert out["complete"] is True and out["visible"] is False and out["next_step"] is None
    assert out["done_count"] == 4


def test_an_unreadable_step_is_neither_done_nor_not_done():
    facts = _facts(first_client=rule.Fact(True, BORN), first_statement=rule.Fact(None))
    out = rule.build(facts)
    by_id = {s["id"]: s for s in out["steps"]}
    assert by_id["first_statement"]["done"] is None
    assert out["unreadable"] == ["first_statement"]
    assert out["done_count"] == 1, "an unreadable step is not counted as done"
    assert out["complete"] is False and out["visible"] is True
    # and it is not offered as the next thing to do: nobody knows it is not done
    assert out["next_step"] == "first_invoice"


def test_four_unreadable_steps_show_nothing_rather_than_four_question_marks():
    out = rule.build({})
    assert out["unreadable"] == list(rule.STEP_IDS)
    assert out["visible"] is False and out["complete"] is False and out["next_step"] is None


def test_a_step_missing_from_the_facts_reads_as_unreadable_not_as_not_done():
    out = rule.build({"first_client": rule.Fact(True, BORN)})
    assert out["unreadable"] == ["first_invoice", "first_statement", "invite_colleague"]


def test_done_at_is_reported_only_for_a_step_that_is_done():
    out = rule.build(_facts(first_client=rule.Fact(True, BORN),
                            first_invoice=rule.Fact(False, "2026-09-02T00:00:00+00:00")))
    by_id = {s["id"]: s for s in out["steps"]}
    assert by_id["first_client"]["done_at"] == BORN
    assert by_id["first_invoice"]["done_at"] is None


@pytest.mark.parametrize("born,invoiced,expected", [
    ("2026-09-01T04:00:00+00:00", "2026-09-01T06:30:00+00:00", 150),
    ("2026-09-01T04:00:00Z", "2026-09-01T04:00:59Z", 0),
    ("2026-09-01T04:00:00+00:00", "2026-09-03T04:00:00+00:00", 2880),
    ("2026-09-01T04:00:00", "2026-09-01T05:00:00+00:00", 60),          # a bare stamp was written as UTC
    ("2026-09-01T04:00:00+00:00", "2026-08-31T00:00:00+00:00", None),   # carried over from before the firm
    (None, "2026-09-01T06:30:00+00:00", None),
    ("2026-09-01T04:00:00+00:00", None, None),
    ("not a time", "2026-09-01T06:30:00+00:00", None),
])
def test_the_time_to_first_invoice_is_two_timestamps_that_already_exist(born, invoiced, expected):
    facts = _facts(first_invoice=rule.Fact(True, invoiced))
    assert rule.build(facts, firm_created_at=born)["minutes_to_first_invoice"] == expected


def test_the_time_to_first_invoice_is_not_reported_for_an_invoice_nobody_has_raised():
    facts = _facts(first_invoice=rule.Fact(False, "2026-09-01T06:30:00+00:00"))
    assert rule.build(facts, firm_created_at=BORN)["minutes_to_first_invoice"] is None


# ══════════════════════════════════════════════════════════════════════════════
# the firm's own data
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def world(monkeypatch):
    db = FakeDB()
    db.seed("firms", {"id": FIRM, "name": "Sharma & Co", "created_at": BORN})
    db.seed("firms", {"id": OTHER, "name": "Rival & Co", "created_at": BORN})
    db.seed("users", {"id": "u-p1", "firm_id": FIRM, "email": "p1@f.in", "is_active": True,
                      "status": "active", "created_at": BORN, "deleted_at": None})
    db.seed("users", {"id": "u-x1", "firm_id": OTHER, "email": "x1@r.in", "is_active": True,
                      "status": "active", "created_at": BORN, "deleted_at": None})
    monkeypatch.setattr(svc, "_USE_MOCK", False)
    monkeypatch.setattr(svc, "_db", lambda: db)
    return db


def _steps(firm=FIRM):
    return {s["id"]: s for s in svc.first_run(firm)["steps"]}


def _client(db, firm=FIRM, *, internal=False, deleted=None, at="2026-09-01T05:00:00+00:00", id=None):
    return db.seed("clients", {"id": id or f"c-{len(db.rows('clients'))}", "firm_id": firm,
                               "client_name": "Acme", "is_internal": internal,
                               "deleted_at": deleted, "created_at": at})


def _invoice(db, firm=FIRM, *, status="issued", opening=False, deleted=None,
             at="2026-09-01T06:30:00+00:00"):
    return db.seed("client_sales_invoices", {
        "id": f"i-{len(db.rows('client_sales_invoices'))}", "firm_id": firm, "client_id": "c-0",
        "status": status, "is_opening": opening, "deleted_at": deleted, "created_at": at})


def test_a_fresh_firm_has_none_of_the_four_done(world):
    out = svc.first_run(FIRM)
    assert [s["done"] for s in out["steps"]] == [False] * 4
    assert out["visible"] is True and out["next_step"] == "first_client"
    assert out["minutes_to_first_invoice"] is None


def test_the_practices_own_record_is_not_a_client_and_a_deleted_one_is_not_either(world):
    _client(world, internal=True)
    _client(world, deleted="2026-09-02T00:00:00+00:00")
    assert _steps()["first_client"]["done"] is False


def test_a_real_client_ticks_the_first_step_and_stamps_when(world):
    _client(world, at="2026-09-01T05:00:00+00:00")
    step = _steps()["first_client"]
    assert step["done"] is True and step["done_at"] == "2026-09-01T05:00:00+00:00"


def test_the_earliest_client_is_the_one_that_dates_the_step(world):
    _client(world, at="2026-09-05T05:00:00+00:00")
    _client(world, at="2026-09-02T05:00:00+00:00")
    assert _steps()["first_client"]["done_at"] == "2026-09-02T05:00:00+00:00"


@pytest.mark.parametrize("kwargs", [
    {"status": "draft"},
    {"opening": True},
    {"deleted": "2026-09-02T00:00:00+00:00"},
], ids=["a draft", "an opening-balance document", "a deleted invoice"])
def test_what_is_not_an_invoice_somebody_raised_here_does_not_tick_the_step(world, kwargs):
    _invoice(world, **kwargs)
    assert _steps()["first_invoice"]["done"] is False


def test_an_issued_invoice_ticks_the_step_and_dates_the_time_to_first_value(world):
    _invoice(world, status="issued", at="2026-09-01T06:30:00+00:00")
    out = svc.first_run(FIRM)
    assert {s["id"]: s["done"] for s in out["steps"]}["first_invoice"] is True
    assert out["minutes_to_first_invoice"] == 150


def test_a_cancelled_invoice_was_still_raised(world):
    """It was issued and then cancelled; the firm has raised an invoice here."""
    _invoice(world, status="cancelled")
    assert _steps()["first_invoice"]["done"] is True


def test_a_carried_over_document_sorting_first_does_not_hide_a_real_invoice(world):
    """LIMIT 1 is why the opening filter is in the QUERY: filtered in Python afterwards,
    the opening document that sorts first would be the whole answer and a real invoice
    behind it would never be seen."""
    _invoice(world, opening=True, at="2026-08-01T00:00:00+00:00")
    _invoice(world, status="issued", at="2026-09-03T00:00:00+00:00")
    step = _steps()["first_invoice"]
    assert step["done"] is True and step["done_at"] == "2026-09-03T00:00:00+00:00"


def test_an_imported_statement_ticks_the_third_step(world):
    world.seed("bank_statements", {"id": "bs-1", "firm_id": FIRM, "client_id": "c-0",
                                   "created_at": "2026-09-02T09:00:00+00:00"})
    step = _steps()["first_statement"]
    assert step["done"] is True and step["done_at"] == "2026-09-02T09:00:00+00:00"


def test_a_colleague_who_is_only_invited_counts_because_the_invite_is_the_row(world):
    world.seed("users", {"id": "u-new", "firm_id": FIRM, "email": "new@f.in", "is_active": True,
                         "status": "invited", "created_at": "2026-09-02T08:00:00+00:00",
                         "deleted_at": None})
    step = _steps()["invite_colleague"]
    assert step["done"] is True and step["done_at"] == "2026-09-02T08:00:00+00:00"


def test_a_deactivated_or_deleted_colleague_is_not_a_colleague(world):
    world.seed("users", {"id": "u-off", "firm_id": FIRM, "email": "off@f.in", "is_active": False,
                         "status": "active", "created_at": "2026-09-02T08:00:00+00:00", "deleted_at": None})
    world.seed("users", {"id": "u-gone", "firm_id": FIRM, "email": "gone@f.in", "is_active": True,
                         "status": "active", "created_at": "2026-09-02T09:00:00+00:00",
                         "deleted_at": "2026-09-03T00:00:00+00:00"})
    assert _steps()["invite_colleague"]["done"] is False


def test_a_deactivated_person_in_front_does_not_hide_the_colleague_behind_them(world):
    world.seed("users", {"id": "u-off", "firm_id": FIRM, "email": "off@f.in", "is_active": False,
                         "status": "active", "created_at": "2026-09-01T05:00:00+00:00", "deleted_at": None})
    world.seed("users", {"id": "u-real", "firm_id": FIRM, "email": "real@f.in", "is_active": True,
                         "status": "active", "created_at": "2026-09-04T05:00:00+00:00", "deleted_at": None})
    step = _steps()["invite_colleague"]
    assert step["done"] is True and step["done_at"] == "2026-09-04T05:00:00+00:00"


def test_another_firms_rows_tick_nothing(world):
    """The service role bypasses RLS, so the firm filter on every read is the isolation."""
    _client(world, OTHER)
    _invoice(world, OTHER)
    world.seed("bank_statements", {"id": "bs-x", "firm_id": OTHER, "client_id": "c-x",
                                   "created_at": "2026-09-02T09:00:00+00:00"})
    world.seed("users", {"id": "u-x2", "firm_id": OTHER, "email": "x2@r.in", "is_active": True,
                         "status": "active", "created_at": "2026-09-02T08:00:00+00:00", "deleted_at": None})
    assert [s["done"] for s in svc.first_run(FIRM)["steps"]] == [False] * 4
    assert [s["done"] for s in svc.first_run(OTHER)["steps"]] == [True] * 4


def test_the_checklist_ticks_itself_as_each_step_is_done(world):
    seen = [[s["done"] for s in svc.first_run(FIRM)["steps"]]]
    _client(world)
    seen.append([s["done"] for s in svc.first_run(FIRM)["steps"]])
    _invoice(world)
    seen.append([s["done"] for s in svc.first_run(FIRM)["steps"]])
    world.seed("bank_statements", {"id": "bs-1", "firm_id": FIRM, "client_id": "c-0",
                                   "created_at": "2026-09-02T09:00:00+00:00"})
    seen.append([s["done"] for s in svc.first_run(FIRM)["steps"]])
    world.seed("users", {"id": "u-new", "firm_id": FIRM, "email": "n@f.in", "is_active": True,
                         "status": "invited", "created_at": "2026-09-03T00:00:00+00:00", "deleted_at": None})
    last = svc.first_run(FIRM)
    seen.append([s["done"] for s in last["steps"]])
    assert seen == [[False] * 4,
                    [True, False, False, False],
                    [True, True, False, False],
                    [True, True, True, False],
                    [True, True, True, True]]
    assert last["complete"] is True and last["visible"] is False


def test_deleting_the_row_unticks_the_step_because_nothing_was_stored(world):
    c = _client(world)
    assert _steps()["first_client"]["done"] is True
    world.rows("clients").remove(c)
    assert _steps()["first_client"]["done"] is False


class _Breaks:
    """A database double whose one table raises, like a table a migration has not
    reached or a read that timed out."""

    def __init__(self, db, table):
        self._db, self._table = db, table

    def table(self, name):
        if name == self._table:
            raise RuntimeError(f"relation {name} does not exist")
        return self._db.table(name)


def test_a_table_that_cannot_be_read_leaves_one_step_unknown_and_the_rest_intact(world, monkeypatch):
    _client(world)
    monkeypatch.setattr(svc, "_db", lambda: _Breaks(world, "bank_statements"))
    out = svc.first_run(FIRM)
    by_id = {s["id"]: s["done"] for s in out["steps"]}
    assert by_id == {"first_client": True, "first_invoice": False,
                     "first_statement": None, "invite_colleague": False}
    assert out["unreadable"] == ["first_statement"] and out["visible"] is True


def test_without_a_database_every_step_is_unknown_and_the_card_is_hidden(monkeypatch):
    monkeypatch.setattr(svc, "_USE_MOCK", True)
    out = svc.first_run(FIRM)
    assert out["unreadable"] == list(rule.STEP_IDS) and out["visible"] is False


# ══════════════════════════════════════════════════════════════════════════════
# the endpoint
# ══════════════════════════════════════════════════════════════════════════════

def _app(user):
    app = FastAPI()
    app.include_router(onboarding.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def served(world, monkeypatch):
    monkeypatch.setattr(onboarding, "get_service_supabase", lambda: world)
    return world


def test_a_partner_is_served_the_first_run_checklist(served):
    res = _app(PARTNER).get("/api/onboarding/status")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["success"] is True
    first_run = body["data"]["first_run"]
    assert [s["id"] for s in first_run["steps"]] == list(rule.STEP_IDS)
    assert first_run["visible"] is True and first_run["next_step"] == "first_client"


def test_it_persists_across_logins_because_a_second_partner_sees_what_the_first_did(served):
    _client(served)
    first = _app(PARTNER).get("/api/onboarding/status").json()["data"]["first_run"]
    second = _app(PARTNER_2).get("/api/onboarding/status").json()["data"]["first_run"]
    again = _app(PARTNER).get("/api/onboarding/status").json()["data"]["first_run"]
    assert first == second == again
    assert first["steps"][0]["done"] is True


def test_a_manager_sees_the_same_checklist_as_a_partner(served):
    _client(served)
    p = _app(PARTNER).get("/api/onboarding/status").json()["data"]["first_run"]
    m = _app(MANAGER).get("/api/onboarding/status").json()["data"]["first_run"]
    assert p == m


@pytest.mark.parametrize("user", [EXECUTIVE, REVIEWER], ids=["Executive", "Reviewer"])
def test_the_rest_of_the_firm_is_not_shown_a_setup_card_it_cannot_act_on(served, user):
    assert _app(user).get("/api/onboarding/status").status_code == 403


def test_only_partner_and_manager_hold_firm_read():
    assert PERMISSIONS["firm"]["read"] == {Role.PARTNER, Role.MANAGER}


def test_the_older_checks_are_derived_from_the_same_facts_as_the_checklist(served):
    """`checks.team_members_added` used to be `len(users) > 1`, which counts a person who has
    been deactivated; the checklist does not. One definition, so they cannot disagree."""
    served.seed("users", {"id": "u-off", "firm_id": FIRM, "email": "off@f.in", "is_active": False,
                          "status": "active", "created_at": "2026-09-02T08:00:00+00:00", "deleted_at": None})
    data = _app(PARTNER).get("/api/onboarding/status").json()["data"]
    assert data["checks"]["team_members_added"] is False
    assert data["first_run"]["steps"][3]["done"] is False

    _client(served)
    data = _app(PARTNER).get("/api/onboarding/status").json()["data"]
    assert data["checks"]["first_client_added"] is True
    assert data["score"] == sum(data["checks"].values()) and data["total"] == len(data["checks"])


def test_the_whole_walk_a_fresh_firm_takes_ends_with_the_card_gone_and_a_time_on_record(served):
    client = _app(PARTNER)
    start = client.get("/api/onboarding/status").json()["data"]["first_run"]
    assert start["visible"] and start["done_count"] == 0

    _client(served)
    _invoice(served, at="2026-09-01T07:15:00+00:00")
    served.seed("bank_statements", {"id": "bs-1", "firm_id": FIRM, "client_id": "c-0",
                                    "created_at": "2026-09-01T08:00:00+00:00"})
    served.seed("users", {"id": "u-new", "firm_id": FIRM, "email": "n@f.in", "is_active": True,
                          "status": "invited", "created_at": "2026-09-01T08:30:00+00:00", "deleted_at": None})
    done = client.get("/api/onboarding/status").json()["data"]["first_run"]
    assert done["complete"] is True and done["visible"] is False
    assert done["minutes_to_first_invoice"] == 195, "04:00 sign-up to the 07:15 invoice"


# ══════════════════════════════════════════════════════════════════════════════
# the two halves of the vocabulary: Python's steps, the browser's routes
# ══════════════════════════════════════════════════════════════════════════════

import re
from pathlib import Path

_WEB = Path(__file__).resolve().parents[2] / "web"


def _browser_routes() -> dict[str, str]:
    src = (_WEB / "lib" / "onboarding" / "firstRun.ts").read_text(encoding="utf-8")
    body = re.search(r"export const STEP_ROUTES[^=]*=\s*\{(.*?)\};", src, re.S)
    assert body, "STEP_ROUTES moved — this parity test reads it"
    return dict(re.findall(r'(\w+):\s*"(/[^"]*)"', body.group(1)))


def test_every_step_the_server_can_send_has_a_screen_in_the_browser_and_no_route_is_stale():
    """The vocabulary is Python's and the route map is the browser's (the shape of
    `lib/accounting/sourceDocument.ts`), pinned from the side that owns the vocabulary: a
    guard in `apps/web` would assert the map against a copy of itself."""
    routes = _browser_routes()
    assert set(routes) == set(rule.STEP_IDS), (
        f"steps without a route: {sorted(set(rule.STEP_IDS) - set(routes))}; "
        f"routes for no step: {sorted(set(routes) - set(rule.STEP_IDS))}")


def test_each_step_opens_a_screen_that_exists():
    for step_id, href in _browser_routes().items():
        page = _WEB / "app" / Path(*[p for p in href.split("/") if p]) / "page.tsx"
        assert page.is_file(), f"{step_id} opens {href}, which is not a screen"
