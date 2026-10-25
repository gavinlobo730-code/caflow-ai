"""POST-A-010, the staff payroll screens: the attendance sheet, the leave ledger, the roster and the run list.

WHAT MOVED. The Attendance screen (its month sheet and its Leave tab), the payroll Reports page and a client's Payroll tab read
`payroll_employees`, `payroll_runs`, `attendance` and `leave_balances` straight from PostgREST with the signed-in person's token.
Payroll is the most sensitive table family the browser reached, and the one control on that path was the database's row
security: the payroll tier a Partner sets on the Team screen is asked by `rbac("payroll", ...)` on the server and by nothing
in the browser. Each read is a route now.

WHAT THE SERVER HAD TO GET RIGHT, each pinned here:

  * EVERY ROW. PostgREST cuts a response at about a thousand rows without a word. The roster, the run list, a month's
    attendance and a year's leave were read once each; they are read in the server's own pages now.
  * THE SUM IS THE SERVER'S. The leave ledger added the days taken up in the browser over an unpaged read, so past the cut the
    total came out SHORT and the balance left came out too high for everybody after it. The total is taken over every row.
  * AN ENTITLEMENT NOBODY RECORDED IS UNKNOWN. It is `null`, never a default, and a day taken is still counted against it.
  * THE CALLER'S CLIENTS ONLY, for the people and for the rows that hang from them.
  * NO MORE OF A PERSON THAN THE SCREEN SHOWS. The two new reads name four columns of an employee; the roster keeps its
    existing shape.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import routers.payroll as pr
from tests._capped_postgrest import DB_MAX_ROWS, CappedDB

FIRM, OTHER_FIRM = "firm-001", "firm-002"
CLIENT_A, CLIENT_B = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}


def _emp(i, *, client=CLIENT_A, firm=FIRM, name=None, status="active"):
    return {"id": f"e{i:06d}", "firm_id": firm, "client_id": client, "name": name or f"Employee {i:05d}",
            "designation": "Clerk", "status": status}


def _att(i, employee, *, month=8, year=2026, casual=0, sick=0, earned=0, firm=FIRM):
    return {"id": f"a{i:06d}", "firm_id": firm, "employee_id": employee, "month": month, "year": year,
            "working_days": 26, "days_present": 26, "casual_leaves": casual, "sick_leaves": sick, "earned_leaves": earned}


@pytest.fixture
def wire(monkeypatch):
    def use(**tables):
        db = CappedDB(tables)
        monkeypatch.setattr(pr, "_db", lambda: db)
        return db
    return use


@pytest.fixture
def scoped(monkeypatch):
    """The caller is assigned to client A alone (the real narrowing, with only the assignment lookup replaced)."""
    import core.authz as authz
    monkeypatch.setattr(authz, "effective_client_ids", lambda user: {CLIENT_A})
    return {**USER, "role": "Executive"}


# ── the roster and the run list read every row ───────────────────────────────────────────────────────────────────────

def test_a_roster_longer_than_the_row_cap_lists_every_employee(wire):
    rows = [_emp(i) for i in range(2300)]
    db = wire(payroll_employees=rows)
    got = pr.list_employees(client_id=None, include_inactive=False, current_user=USER)["data"]
    assert len(got) == 2300 and len({e["id"] for e in got}) == 2300
    assert 2300 > DB_MAX_ROWS and len(db.requests["payroll_employees"]) == 3, "three pages of at most a thousand"


def test_the_roster_is_in_name_order_ignoring_case_with_ties_on_the_id(wire):
    rows = [_emp(1, name="bala"), _emp(2, name="Asha"), _emp(3, name="Chitra"), _emp(4, name="asha"), _emp(5, name="Bala")]
    wire(payroll_employees=rows)
    got = pr.list_employees(client_id=None, include_inactive=False, current_user=USER)["data"]
    assert [(e["name"], e["id"]) for e in got] == [
        ("Asha", "e000002"), ("asha", "e000004"), ("bala", "e000001"), ("Bala", "e000005"), ("Chitra", "e000003")]


def test_leavers_are_left_out_unless_asked_for_and_another_firms_people_never_appear(wire):
    rows = [_emp(1), _emp(2, status="resigned"), _emp(3, firm=OTHER_FIRM)]
    wire(payroll_employees=rows)
    assert [e["id"] for e in pr.list_employees(client_id=None, include_inactive=False, current_user=USER)["data"]] == ["e000001"]
    assert [e["id"] for e in pr.list_employees(client_id=None, include_inactive=True, current_user=USER)["data"]] == [
        "e000001", "e000002"]


def test_a_member_assigned_to_one_client_sees_only_that_clients_people_and_runs(wire, scoped):
    wire(payroll_employees=[_emp(1), _emp(2, client=CLIENT_B)],
         payroll_runs=[{"id": "r1", "firm_id": FIRM, "client_id": CLIENT_A, "month": "2026-08"},
                       {"id": "r2", "firm_id": FIRM, "client_id": CLIENT_B, "month": "2026-08"}])
    assert [e["id"] for e in pr.list_employees(client_id=None, include_inactive=False, current_user=scoped)["data"]] == ["e000001"]
    assert [r["id"] for r in pr.list_runs(client_id=None, current_user=scoped)["data"]] == ["r1"]


def test_more_runs_than_the_row_cap_are_listed_newest_month_first_with_ties_on_the_id(wire):
    rows = [{"id": f"r{i:06d}", "firm_id": FIRM, "client_id": CLIENT_A, "month": f"20{20 + i % 7}-{i % 12 + 1:02d}"}
            for i in range(2300)]
    db = wire(payroll_runs=rows)
    got = pr.list_runs(client_id=None, current_user=USER)["data"]
    assert len(got) == 2300 and len(db.requests["payroll_runs"]) == 3
    for earlier, later in zip(got, got[1:], strict=False):
        assert (earlier["month"] > later["month"]
                or (earlier["month"] == later["month"] and earlier["id"] < later["id"])), (earlier, later)


# ── the attendance sheet ─────────────────────────────────────────────────────────────────────────────────────────────

def test_the_board_holds_every_employee_leavers_included_and_the_months_rows_only(wire):
    rows = [_emp(1), _emp(2, status="resigned"), _emp(3, firm=OTHER_FIRM)]
    attendance = [_att(1, "e000001"), _att(2, "e000001", month=7), _att(3, "e000001", year=2025), _att(4, "e000002", casual=2),
                  _att(5, "e000003", firm=OTHER_FIRM)]
    wire(payroll_employees=rows, attendance=attendance)
    body = pr.attendance_board(month="2026-08", current_user=USER)["data"]
    assert body["month"] == "2026-08"
    assert [e["id"] for e in body["employees"]] == ["e000001", "e000002"]
    assert sorted(a["id"] for a in body["attendance"]) == ["a000001", "a000004"]


def test_the_board_names_four_columns_of_a_person_and_no_pan_salary_or_bank_detail(wire):
    """The double does not project columns, so the proof is the column list the query ASKS for: PostgREST returns exactly it."""
    db = wire(payroll_employees=[_emp(1)], attendance=[])
    pr.attendance_board(month="2026-08", current_user=USER)
    assert db.selects["payroll_employees"] == ["id, name, designation, client_id"]
    assert db.selects["attendance"] == ["id, employee_id, working_days, days_present, casual_leaves, sick_leaves, earned_leaves"]


def test_the_board_narrows_people_and_their_rows_to_the_callers_clients(wire, scoped):
    wire(payroll_employees=[_emp(1), _emp(2, client=CLIENT_B)],
         attendance=[_att(1, "e000001"), _att(2, "e000002")])
    body = pr.attendance_board(month="2026-08", current_user=scoped)["data"]
    assert [e["id"] for e in body["employees"]] == ["e000001"]
    assert [a["id"] for a in body["attendance"]] == ["a000001"], "a row of another client's employee is not served"


def test_a_month_with_more_rows_than_the_row_cap_is_served_whole(wire):
    employees = [_emp(i) for i in range(2300)]
    attendance = [_att(i, f"e{i:06d}") for i in range(2300)]
    db = wire(payroll_employees=employees, attendance=attendance)
    body = pr.attendance_board(month="2026-08", current_user=USER)["data"]
    assert len(body["employees"]) == 2300 and len(body["attendance"]) == 2300
    assert len(db.requests["attendance"]) == 3


@pytest.mark.parametrize("bad", ["2026-13", "2026", "August", "2026-8-1", ""])
def test_a_month_that_is_not_one_is_a_422_and_reads_nothing(wire, bad):
    db = wire()
    with pytest.raises(HTTPException) as caught:
        pr.attendance_board(month=bad, current_user=USER)
    assert caught.value.status_code == 422 and db.requests == {}


# ── the leave ledger ─────────────────────────────────────────────────────────────────────────────────────────────────

def _balance(employee, *, casual=12, sick=8, earned=15, year=2026, firm=FIRM):
    return {"id": f"b-{employee}", "firm_id": firm, "employee_id": employee, "year": year,
            "casual_leave_balance": casual, "sick_leave_balance": sick, "earned_leave_balance": earned}


def test_the_days_taken_are_summed_by_the_server_over_every_row_of_the_year(wire):
    """2,300 rows is more than the row cap. An unpaged read stops at a thousand and the total comes out short."""
    employees = [_emp(1)]
    attendance = [_att(i, "e000001", month=i % 12 + 1, casual=1, sick=0, earned=0) for i in range(2300)]
    db = wire(payroll_employees=employees, leave_balances=[_balance("e000001")], attendance=attendance)
    [row] = pr.leave_ledger(year=2026, current_user=USER)["data"]["rows"]
    assert row["casual_used"] == 2300 > DB_MAX_ROWS
    assert len(db.requests["attendance"]) == 3


def test_the_three_kinds_of_leave_are_summed_apart_and_only_for_the_year_asked(wire):
    wire(payroll_employees=[_emp(1)],
         leave_balances=[_balance("e000001")],
         attendance=[_att(1, "e000001", month=1, casual=1, sick=2, earned=3), _att(2, "e000001", month=2, casual=1, sick=0, earned=1),
                     _att(3, "e000001", year=2025, month=12, casual=9, sick=9, earned=9)])
    [row] = pr.leave_ledger(year=2026, current_user=USER)["data"]["rows"]
    assert (row["casual_used"], row["sick_used"], row["earned_used"]) == (2, 2, 4)
    assert (row["casual_leave_balance"], row["sick_leave_balance"], row["earned_leave_balance"]) == (12, 8, 15)
    assert row["year"] == 2026 and row["employee_id"] == "e000001" and row["id"] == "b-e000001"


def test_an_entitlement_nobody_recorded_is_null_and_not_a_default_while_the_days_taken_still_count(wire):
    wire(payroll_employees=[_emp(1), _emp(2)], leave_balances=[_balance("e000002")],
         attendance=[_att(1, "e000001", casual=3)])
    rows = {r["employee_id"]: r for r in pr.leave_ledger(year=2026, current_user=USER)["data"]["rows"]}
    unrecorded = rows["e000001"]
    assert unrecorded["id"] is None
    assert unrecorded["casual_leave_balance"] is None and unrecorded["sick_leave_balance"] is None
    assert unrecorded["earned_leave_balance"] is None and unrecorded["casual_used"] == 3
    assert rows["e000002"]["casual_leave_balance"] == 12 and rows["e000002"]["casual_used"] == 0


def test_a_recorded_zero_is_a_reading_and_not_an_absence(wire):
    wire(payroll_employees=[_emp(1)], leave_balances=[_balance("e000001", casual=0, sick=0, earned=0)], attendance=[])
    [row] = pr.leave_ledger(year=2026, current_user=USER)["data"]["rows"]
    assert row["casual_leave_balance"] == 0 and row["sick_leave_balance"] == 0 and row["earned_leave_balance"] == 0


def test_the_ledger_has_one_line_per_employee_in_reach_and_nothing_of_another_firm_or_client(wire, scoped):
    wire(payroll_employees=[_emp(1), _emp(2, client=CLIENT_B), _emp(3, firm=OTHER_FIRM)],
         leave_balances=[_balance("e000001"), _balance("e000002"), _balance("e000003", firm=OTHER_FIRM)],
         attendance=[_att(1, "e000001", casual=1), _att(2, "e000002", casual=5), _att(3, "e000003", casual=7, firm=OTHER_FIRM)])
    rows = pr.leave_ledger(year=2026, current_user=scoped)["data"]["rows"]
    assert [r["employee_id"] for r in rows] == ["e000001"] and rows[0]["casual_used"] == 1


def test_the_ledger_asks_only_the_columns_it_needs(wire):
    db = wire(payroll_employees=[_emp(1)], leave_balances=[], attendance=[])
    pr.leave_ledger(year=2026, current_user=USER)
    assert db.selects["payroll_employees"] == ["id, name, designation, client_id"]
    assert db.selects["attendance"] == ["id, employee_id, casual_leaves, sick_leaves, earned_leaves"]


@pytest.mark.parametrize("year", [1999, 2101])
def test_a_year_outside_the_calendar_the_rows_are_kept_under_is_a_422(dev_header_auth, wire, year):
    from main import app
    wire()
    r = TestClient(app, raise_server_exceptions=False).get(
        "/api/payroll/leave-ledger", params={"year": year}, headers={"X-User-Role": "Partner", "X-Firm-Id": FIRM, "X-User-Id": "u"})
    assert r.status_code == 422, r.text


# ── in front of the app: who may ask ─────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def app_world(monkeypatch, dev_header_auth, wire):
    from main import app
    wire(payroll_employees=[_emp(1)], leave_balances=[_balance("e000001")], attendance=[_att(1, "e000001", casual=1)])
    return TestClient(app, raise_server_exceptions=False)


def _h(role):
    return {"X-User-Role": role, "X-Firm-Id": FIRM, "X-User-Id": f"{role}-1"}


@pytest.mark.parametrize("path, params", [("/api/payroll/attendance-board", {"month": "2026-08"}),
                                          ("/api/payroll/leave-ledger", {"year": 2026})])
def test_the_two_new_reads_ask_the_payroll_read_permission_the_roles_have(app_world, path, params):
    """Payroll read is a Manager-and-above permission, asked by the route and not by the browser."""
    from core.permissions import PERMISSIONS
    readers = {str(getattr(r, "value", r)) for r in PERMISSIONS["payroll"]["read"]}
    assert readers == {"Partner", "Manager"}, "the test's premise: who reads payroll today"
    for role in ("Partner", "Manager", "Executive", "Reviewer", "Client"):
        r = app_world.get(path, params=params, headers=_h(role))
        assert (r.status_code == 200) is (role in readers), (role, r.status_code, r.text)
        if role not in readers:
            assert r.status_code == 403
