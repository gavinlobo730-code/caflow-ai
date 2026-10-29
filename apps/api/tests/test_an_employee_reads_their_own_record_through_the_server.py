"""POST-A-010, the employee portal: the employee's own record, payslips and leave are asked of the server.

WHAT MOVED. The employee portal read `payroll_employees`, `payroll_slips` (with its run) and `leave_balances` straight from
PostgREST with the employee's own token, and two pages asked the database whether an identity was an activated employee. Each
is a route now, on the employee principal alone, and nothing in any request names a person.

WHAT THE SERVER HAS TO GET RIGHT, each pinned here with a colleague's and another firm's rows seeded beside the caller's,
because these routes read with the SERVER's client (`routers.payroll._db`), so the principal's ids are the only scope:

  * ME is the caller's own row, the eight columns the page shows, and a principal whose row is gone is refused;
  * PAYSLIPS are the caller's own, in a RELEASED run of the caller's own firm and client, newest first: a colleague's slip,
    a draft's, another client's and another firm's are absent;
  * LEAVE is the entitlement recorded for the current calendar year in IST (the year the staff side keeps leave under; the
    portal used to ask for the April-to-March year's first year, which from January to March was LAST year's row), and an
    entitlement nobody recorded is an empty list, never a default;
  * ACCESS says `enabled` for an activated employee and `false`, with a 200, for everyone else.
"""
from __future__ import annotations

import inspect
from datetime import date

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import routers.payroll as payroll_mod
import routers.portal_employee as portal_mod
from core.auth import get_jwt_user
from core.portal_auth import get_current_portal_employee
from domain.payroll.run_status import PAYROLL_RELEASED
from tests.e2e_harness import FakeDB
from tests._fastapi_compat import body_annotation

FIRM, OTHER_FIRM = "F1", "F2"
CLIENT, OTHER_CLIENT = "C1", "C2"
ME, COLLEAGUE, STRANGER = "E-me", "E-colleague", "E-stranger"
ME_CTX = {
    "portal": True, "employee": True, "employee_id": ME, "client_id": CLIENT,
    "firm_id": FIRM, "name": "Me", "employee_code": "EMP-001",
    "email": "me@f1.test", "role": "PortalEmployee",
}


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(payroll_mod, "_db", lambda: db)
    monkeypatch.setattr(portal_mod, "ist_today", lambda: date(2026, 10, 25))
    for emp, firm, client, name in ((ME, FIRM, CLIENT, "Me"), (COLLEAGUE, FIRM, CLIENT, "Colleague"),
                                    (STRANGER, OTHER_FIRM, OTHER_CLIENT, "Stranger")):
        db.seed("payroll_employees", {
            "id": emp, "firm_id": firm, "client_id": client, "name": name, "designation": "Clerk", "department": "Accounts",
            "pan": "ABCDE1234F", "bank_account_no": "1234567890", "bank_name": "HDFC", "bank_ifsc": "HDFC0001234",
            "basic_paise": 5_000_000, "auth_user_id": f"auth-{emp}", "portal_enabled": True})
    app = FastAPI()
    app.include_router(portal_mod.router)
    app.dependency_overrides[get_current_portal_employee] = lambda: dict(ME_CTX)
    return TestClient(app, raise_server_exceptions=False), db


def _run(db, run_id, *, status="finalized", month="2026-06", firm=FIRM, client=CLIENT):
    return db.seed("payroll_runs", {"id": run_id, "firm_id": firm, "client_id": client, "status": status, "month": month})


def _slip(db, slip_id, run_id, employee=ME, *, created="2026-06-30T10:00:00+00:00", gross=5_000_000, net=4_500_000):
    return db.seed("payroll_slips", {"id": slip_id, "run_id": run_id, "employee_id": employee, "created_at": created,
                                     "gross_paise": gross, "net_paise": net})


# ── me ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_me_is_the_callers_own_row_and_the_eight_columns_the_page_shows(world):
    client, _ = world
    got = client.get("/api/portal/employee/me").json()["data"]["employee"]
    assert got == {"id": ME, "name": "Me", "designation": "Clerk", "department": "Accounts", "pan": "ABCDE1234F",
                   "bank_account_no": "1234567890", "bank_name": "HDFC", "bank_ifsc": "HDFC0001234"}
    assert "basic_paise" not in got and "auth_user_id" not in got and "firm_id" not in got


def test_a_principal_whose_row_is_gone_is_refused_in_the_principals_own_words(world):
    client, db = world
    db.rows("payroll_employees")[:] = [r for r in db.rows("payroll_employees") if r["id"] != ME]
    r = client.get("/api/portal/employee/me")
    assert r.status_code == 403 and r.json()["detail"] == "Not an employee portal user."


def test_a_row_of_the_same_id_in_another_firm_is_not_served(world):
    client, db = world
    db.rows("payroll_employees")[:] = [r for r in db.rows("payroll_employees") if r["id"] != ME]
    db.seed("payroll_employees", {"id": ME, "firm_id": OTHER_FIRM, "client_id": OTHER_CLIENT, "name": "Imposter"})
    assert client.get("/api/portal/employee/me").status_code == 403


# ── payslips ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_list_holds_the_callers_released_slips_newest_first(world):
    client, db = world
    _run(db, "R1", month="2026-04"); _run(db, "R2", month="2026-05", status="paid"); _run(db, "R3", month="2026-06")
    _slip(db, "S1", "R1", created="2026-04-30T10:00:00+00:00")
    _slip(db, "S2", "R2", created="2026-05-31T10:00:00+00:00")
    _slip(db, "S3", "R3", created="2026-06-30T10:00:00+00:00")
    got = client.get("/api/portal/employee/payslips").json()["data"]["payslips"]
    assert [s["id"] for s in got] == ["S3", "S2", "S1"]
    assert got[0] == {"id": "S3", "month": "2026-06", "gross_paise": 5_000_000, "net_paise": 4_500_000,
                      "created_at": "2026-06-30T10:00:00+00:00"}


def test_a_colleagues_a_drafts_another_clients_and_another_firms_slips_are_absent(world):
    client, db = world
    _run(db, "R1")
    _run(db, "RD", status="draft"); _run(db, "RR", status="review")
    _run(db, "RC", client=OTHER_CLIENT); _run(db, "RF", firm=OTHER_FIRM, client=OTHER_CLIENT)
    _run(db, "RX", firm=OTHER_FIRM, client=CLIENT)   # the caller's client id under another firm: a run of nobody's of theirs
    _slip(db, "mine", "R1")
    _slip(db, "other-firm-same-client", "RX")
    _slip(db, "colleague", "R1", employee=COLLEAGUE)
    _slip(db, "draft", "RD"); _slip(db, "review", "RR")
    _slip(db, "other-client", "RC"); _slip(db, "other-firm", "RF")
    assert [s["id"] for s in client.get("/api/portal/employee/payslips").json()["data"]["payslips"]] == ["mine"]


def test_both_released_statuses_are_listed_and_only_they(world):
    client, db = world
    for i, status in enumerate(sorted(PAYROLL_RELEASED) + ["draft", "review", "cancelled"]):
        _run(db, f"R{i}", status=status)
        _slip(db, f"S{i}", f"R{i}")
    got = {s["id"] for s in client.get("/api/portal/employee/payslips").json()["data"]["payslips"]}
    assert got == {f"S{i}" for i in range(len(PAYROLL_RELEASED))}


def test_a_long_history_is_listed_whole_across_the_batches_of_runs_asked_for(world):
    client, db = world
    for i in range(130):
        _run(db, f"R{i:03d}", month=f"20{10 + i // 12}-{i % 12 + 1:02d}")
        _slip(db, f"S{i:03d}", f"R{i:03d}", created=f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}+00:00")
    got = client.get("/api/portal/employee/payslips").json()["data"]["payslips"]
    assert len(got) == 130 and len({s["id"] for s in got}) == 130
    assert [s["id"] for s in got[:2]] == ["S129", "S128"]


def test_slips_of_one_moment_are_in_one_order(world):
    client, db = world
    _run(db, "R1")
    for sid in ("S-b", "S-c", "S-a"):
        _slip(db, sid, "R1", created="2026-06-30T10:00:00+00:00")
    assert [s["id"] for s in client.get("/api/portal/employee/payslips").json()["data"]["payslips"]] == ["S-a", "S-b", "S-c"]


def test_no_slips_is_an_empty_list_and_not_an_error(world):
    client, _ = world
    r = client.get("/api/portal/employee/payslips")
    assert r.status_code == 200 and r.json()["data"] == {"payslips": []}


# ── leave ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _leave(db, employee, year, casual=12, firm=FIRM):
    return db.seed("leave_balances", {"id": f"L-{employee}-{year}", "firm_id": firm, "employee_id": employee, "year": year,
                                      "casual_leave_balance": casual, "sick_leave_balance": 8, "earned_leave_balance": None})


def test_the_current_calendar_year_in_ist_is_asked_for(world, monkeypatch):
    client, db = world
    _leave(db, ME, 2026, casual=11); _leave(db, ME, 2027, casual=9); _leave(db, ME, 2025, casual=1)
    body = client.get("/api/portal/employee/leave-balances").json()["data"]
    assert body["year"] == 2026 and [b["casual_leave_balance"] for b in body["balances"]] == [11]
    # From January to March the April-to-March year's first calendar year is LAST year: the server asks for this one.
    monkeypatch.setattr(portal_mod, "ist_today", lambda: date(2027, 2, 10))
    body = client.get("/api/portal/employee/leave-balances").json()["data"]
    assert body["year"] == 2027 and [b["casual_leave_balance"] for b in body["balances"]] == [9]


def test_an_unrecorded_entitlement_is_null_and_a_year_with_none_recorded_is_an_empty_list(world):
    client, db = world
    _leave(db, ME, 2026)
    [row] = client.get("/api/portal/employee/leave-balances").json()["data"]["balances"]
    assert row["earned_leave_balance"] is None and row["sick_leave_balance"] == 8
    db.rows("leave_balances").clear()
    assert client.get("/api/portal/employee/leave-balances").json()["data"] == {"year": 2026, "balances": []}


def test_a_colleagues_and_another_firms_leave_is_not_served(world):
    client, db = world
    _leave(db, ME, 2026, casual=11); _leave(db, COLLEAGUE, 2026, casual=3); _leave(db, ME, 2026, casual=7, firm=OTHER_FIRM)
    got = client.get("/api/portal/employee/leave-balances").json()["data"]["balances"]
    assert [b["casual_leave_balance"] for b in got] == [11]


# ── access ───────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def access_world(monkeypatch):
    app = FastAPI()
    app.include_router(portal_mod.router)
    app.dependency_overrides[get_jwt_user] = lambda: {"auth_user_id": "auth-1", "email": "x@y.test"}
    return TestClient(app, raise_server_exceptions=False), monkeypatch


def test_an_activated_employee_is_enabled(access_world):
    client, mp = access_world
    mp.setattr(portal_mod, "get_current_portal_employee", lambda jwt_user: dict(ME_CTX))
    r = client.get("/api/portal/employee/access")
    assert r.status_code == 200 and r.json()["data"] == {"enabled": True}


def test_anyone_else_is_a_200_that_says_false_and_not_a_refusal(access_world):
    client, mp = access_world

    def refuse(jwt_user):
        raise HTTPException(status_code=403, detail="Not an employee portal user.")

    mp.setattr(portal_mod, "get_current_portal_employee", refuse)
    r = client.get("/api/portal/employee/access")
    assert r.status_code == 200 and r.json() == {"success": True, "data": {"enabled": False}, "error": None}


def test_a_failure_that_is_not_a_refusal_is_not_hidden_as_false(access_world):
    client, mp = access_world

    def broken(jwt_user):
        raise HTTPException(status_code=503, detail="database unavailable")

    mp.setattr(portal_mod, "get_current_portal_employee", broken)
    assert client.get("/api/portal/employee/access").status_code == 503


def test_access_asks_the_one_resolver_the_other_routes_ask(access_world):
    """It must not grow a second definition of 'an activated employee'."""
    src = inspect.getsource(portal_mod.employee_portal_access)
    assert "get_current_portal_employee(" in src and "payroll_employees" not in src


# ── the shape of the door ────────────────────────────────────────────────────────────────────────────────────────────

def test_no_new_route_takes_a_person_a_client_or_a_firm_from_the_request():
    """Who is asking comes from the principal; the only things a caller chooses are a financial year and, on the pdf route,
    which of their own payslips."""
    forbidden = {"employee_id", "client_id", "firm_id", "user_id", "auth_user_id"}
    for route in portal_mod.router.routes:
        params = {p for p in inspect.signature(route.endpoint).parameters}
        assert not (params & forbidden), (route.path, params & forbidden)
        body = getattr(route, "body_field", None)
        if body is not None:
            model = body_annotation(body)
            fields = set(model.model_fields) if hasattr(model, "model_fields") else set()
            assert not (fields & forbidden), (route.path, fields & forbidden)
