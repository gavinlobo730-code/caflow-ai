"""POST-A-272 (the Partner view) — the challans tied to no ledger entry are listed across the caller's clients, oldest payment first.

WHAT WAS MISSING
    The Challans tab shows ONE client's challans, with a Ledger column that says tied or not. A practice with fifty clients had no way to ask
    "which recorded challans have nobody tied to the entry that paid them?" without opening fifty tabs, and a recorded challan with no entry behind
    it is exactly the liability the ledger may still show as owing (the register says the tax was deposited; TDS Payable still holds it).

WHAT THIS PINS
    SCOPE     a Partner sees the whole firm, anyone else the clients assigned to them; a client outside that scope answers as an empty list and
              an EMPTY scope is nothing, never "no filter"; another firm's challan is never in the answer;
    SHAPE     oldest payment first (the one that has waited longest), the id as the tiebreak, a window with the server's `has_more`, the
              figures over ALL unlinked challans and not over the window, each row's client name and days since the payment (Indian days);
    MEANING   a challan tied to an entry that no longer records the payment is NOT listed: it is tied, and the Challans tab says in words what
              became of the entry; nothing is changed by reading the list.
"""
import uuid
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.tds_workspace as tw
from core.auth import get_current_user
from services import tds_register_lists_service as lists
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "11111111-1111-1111-1111-111111111111"
OTHER_FIRM = "22222222-2222-2222-2222-222222222222"
A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
C = "cccccccc-cccc-cccc-cccc-cccccccccccc"
PARTNER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}
EXECUTIVE = {"id": "u2", "firm_id": FIRM, "auth_user_id": "au2", "role": "Executive", "email": "e@example.test"}
TODAY = date(2026, 11, 2)


def _id(n: int) -> str:
    return str(uuid.UUID(int=n))


def _challan(db, n, *, client=A, firm=FIRM, link=None, paid="2026-07-07", paise=100_000_00, no=None):
    return db.seed("tds_challans", {"id": _id(n), "firm_id": firm, "client_id": client, "section": "194C", "total_paise": paise,
                                    "payment_date": paid, "challan_no": no or f"CH-{n}", "journal_entry_id": link,
                                    "financial_year": "2026-27", "quarter": "Q2"})


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    for cid, name in ((A, "Acme Traders"), (B, "Bharat Foods"), (C, "Chandra Mills")):
        db.seed("clients", {"id": cid, "firm_id": FIRM, "client_name": name})
    _challan(db, 1, client=A, paid="2026-07-07")
    _challan(db, 2, client=B, paid="2026-05-07", paise=50_000_00)
    _challan(db, 3, client=C, paid="2026-09-07", paise=25_000_00)
    _challan(db, 4, client=A, paid="2026-08-07", link=_id(900))             # tied: not listed
    _challan(db, 5, client=A, firm=OTHER_FIRM, paid="2026-01-01")           # another firm's: never listed
    monkeypatch.setattr(lists, "ist_today", lambda: TODAY)
    wire_e2e(monkeypatch, db, [tw])
    return db


def listed(db, **kw):
    kw = {"client_ids": None, "client_id": None, "limit": 50, "offset": 0, **kw}
    return lists.unlinked_challans(db, FIRM, **kw)


# ── the list ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_untied_challans_are_listed_oldest_payment_first_with_the_client_and_the_wait(world):
    out = listed(world)
    assert [c["challan_no"] for c in out["challans"]] == ["CH-2", "CH-1", "CH-3"]
    first = out["challans"][0]
    assert first["client_name"] == "Bharat Foods" and first["client_id"] == B
    assert first["days_since_payment"] == (TODAY - date(2026, 5, 7)).days
    assert out["has_more"] is False and out["limit"] == 50


def test_a_tied_challan_and_another_firms_challan_are_not_listed(world):
    nos = {c["challan_no"] for c in listed(world)["challans"]}
    assert "CH-4" not in nos and "CH-5" not in nos


def test_the_figures_are_over_every_untied_challan_and_not_over_the_window(world):
    out = listed(world, limit=1)
    assert [c["challan_no"] for c in out["challans"]] == ["CH-2"] and out["has_more"] is True
    assert out["total_unlinked"] == 3 and out["total_unlinked_paise"] == 100_000_00 + 50_000_00 + 25_000_00
    second = listed(world, limit=1, offset=1)
    assert [c["challan_no"] for c in second["challans"]] == ["CH-1"] and second["total_unlinked"] == 3


def test_two_challans_paid_on_one_day_come_back_in_one_order_whichever_window_asks(world):
    _challan(world, 6, client=A, paid="2026-05-07", no="CH-6")
    _challan(world, 7, client=B, paid="2026-05-07", no="CH-7")
    whole = [c["challan_no"] for c in listed(world)["challans"]]
    pieces = [c["challan_no"] for off in range(0, 6) for c in listed(world, limit=1, offset=off)["challans"]]
    assert pieces == whole and len(set(whole)) == len(whole) == 5


def test_a_payment_with_no_date_waits_last_and_has_no_count_of_days(world):
    _challan(world, 8, client=A, paid=None, no="CH-8")
    rows = listed(world)["challans"]
    assert rows[-1]["challan_no"] == "CH-8" and rows[-1]["days_since_payment"] is None


def test_a_challan_that_has_waited_more_than_thirty_indian_days_is_flagged_and_counted_over_all_of_them(world):
    # CH-2 (7 May) and CH-1 (7 July) and CH-3 (7 Sept) have waited 179, 118 and 56 days at TODAY; a fresh one has not.
    _challan(world, 9, client=A, paid="2026-10-20", no="CH-9")          # 13 days
    _challan(world, 10, client=A, paid="2026-10-03", no="CH-10")        # exactly 30 days: not over
    _challan(world, 11, client=A, paid="2026-10-02", no="CH-11")        # 31 days: over
    out = listed(world, limit=3)
    assert out["long_wait_days"] == 30
    assert [(c["challan_no"], c["waiting_long"]) for c in out["challans"]] == [("CH-2", True), ("CH-1", True), ("CH-3", True)]
    assert out["total_waiting_long"] == 4, "counted over every untied challan, not over the window"
    rows = {c["challan_no"]: c for c in listed(world)["challans"]}
    assert (rows["CH-9"]["waiting_long"], rows["CH-10"]["waiting_long"], rows["CH-11"]["waiting_long"]) == (False, False, True)


def test_a_payment_with_no_date_is_not_called_long_waiting(world):
    _challan(world, 8, client=A, paid=None, no="CH-8")
    out = listed(world)
    assert next(c for c in out["challans"] if c["challan_no"] == "CH-8")["waiting_long"] is False
    assert out["total_waiting_long"] == 3


def test_a_client_can_be_asked_for_on_its_own(world):
    assert [c["challan_no"] for c in listed(world, client_id=A)["challans"]] == ["CH-1"]


# ── the scope ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_scoped_caller_sees_only_the_clients_assigned_to_them(world):
    assert [c["challan_no"] for c in listed(world, client_ids={A, C})["challans"]] == ["CH-1", "CH-3"]
    assert listed(world, client_ids={A, C})["total_unlinked"] == 2


def test_an_empty_scope_is_nothing_and_never_no_filter(world):
    out = listed(world, client_ids=set())
    assert out["challans"] == [] and out["total_unlinked"] == 0 and out["total_unlinked_paise"] == 0


def test_a_client_outside_the_scope_answers_as_an_empty_list(world):
    assert listed(world, client_ids={A}, client_id=B)["challans"] == []


# ── the route ───────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def http(world, monkeypatch):
    state = {"user": dict(PARTNER)}
    app = FastAPI()
    app.include_router(tw.router)
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    monkeypatch.setattr(tw, "can_access_client", lambda user, client_id: True)
    client = TestClient(app, raise_server_exceptions=False)
    client.state = state
    return client


def test_the_route_answers_a_partner_with_the_whole_firms_worklist(http, monkeypatch):
    monkeypatch.setattr(tw, "effective_client_ids", lambda user: None)
    res = http.get("/api/tds-workspace/challans/unlinked")
    assert res.status_code == 200 and res.json()["success"] is True
    data = res.json()["data"]
    assert [c["challan_no"] for c in data["challans"]] == ["CH-2", "CH-1", "CH-3"] and data["total_unlinked"] == 3


def test_the_route_narrows_a_scoped_caller_to_their_clients(http, monkeypatch):
    http.state["user"] = dict(EXECUTIVE)
    monkeypatch.setattr(tw, "effective_client_ids", lambda user: {B})
    data = http.get("/api/tds-workspace/challans/unlinked").json()["data"]
    assert [c["challan_no"] for c in data["challans"]] == ["CH-2"] and data["total_unlinked"] == 1


def test_the_route_refuses_a_client_the_caller_may_not_see_in_the_same_words_as_a_missing_one(http, monkeypatch):
    http.state["user"] = dict(EXECUTIVE)
    monkeypatch.setattr(tw, "effective_client_ids", lambda user: {B})
    monkeypatch.setattr(tw, "can_access_client", lambda user, client_id: client_id == B)
    monkeypatch.setattr("core.authz.can_access_client", lambda user, client_id: client_id == B)
    res = http.get(f"/api/tds-workspace/challans/unlinked?client_id={A}")
    assert res.status_code == 404


def test_the_route_is_a_read_and_asks_the_tds_read_tier(http):
    route = next(r for r in tw.router.routes if getattr(r, "path", "") == "/api/tds-workspace/challans/unlinked")
    assert route.methods == {"GET"}
    names = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
    assert "rbac_tds_read" in names


def test_reading_the_list_changes_nothing(http, world, monkeypatch):
    monkeypatch.setattr(tw, "effective_client_ids", lambda user: None)
    before = (list(world.rows("tds_challans")), list(world.rows("journal_entries")), list(world.rows("audit_log")))
    http.get("/api/tds-workspace/challans/unlinked")
    assert (list(world.rows("tds_challans")), list(world.rows("journal_entries")), list(world.rows("audit_log"))) == before
