"""The firm runs its own staff's payroll on the practice client, and only a Partner may (POST-A-532, second part).

WHAT CHANGED
    Guardrail G4 was a module cap: `assert_not_internal_for_payroll` refused payroll for the firm's own practice client to everybody,
    the Partner included, with a 403. On 20 November 2026 the owner decided the firm's own staff payroll runs in My practice, with
    everything else a client's workspace has. The cap is lifted; G1 (the practice is the Partner's alone) is what stands at the doors.

WHY THIS IS TESTED AND NOT JUST DELETED
    Payroll's own permission is Manager and above, and the rows behind these doors say what each colleague is paid. Before this
    change nothing of the practice was ever stored there, so no test had tried the payroll doors against it. Three layers refuse a
    non-Partner: the router guard (`require_client_access` asks G1 of any request that names a client), the assignment scope
    (`assert_client_access`: the practice cannot be assigned, and `core/authz` drops an assignment row that names it, held by
    `tests/test_an_assignment_to_the_practice_grants_a_non_partner_nothing.py`), and the door's own check asserted here.

WHAT IS ASSERTED
    * the rule over the router: every payroll route that asks the per-client switch, and the route that sets it, asks the practice
      check, and asks it BEFORE the switch, so a non-Partner is never told whether payroll is switched on for the practice;
    * through a real door (`POST /employees`), with the two other layers taken away so that only the door's own check is left:
      a Manager is told 404 in the words used for a client that does not exist, and a Partner goes through to the next step.

WHAT IS NOT ASSERTED HERE: the scope layer on the id-keyed routes (a run, a payslip, an employee by id). That an assignment row
naming the practice opens nothing to a non-Partner is the other test's, and that every id-keyed payroll route goes through the
scope guard is `tests/test_payroll_client_scope.py`'s. Nothing here was run against a real database or the live site.
"""
from __future__ import annotations

import ast
import inspect

import pytest
from fastapi import HTTPException

import routers.payroll as pr
import services.internal_client_service as ics
from models.payroll import EmployeeIn

FIRM, PRACTICE, CLIENT = "firm-pp-1", "client-practice", "client-ordinary"
PARTNER = {"id": "u-p", "firm_id": FIRM, "role": "Partner", "auth_user_id": "a-p"}
MANAGER = {"id": "u-m", "firm_id": FIRM, "role": "Manager", "auth_user_id": "a-m"}


def _route_handlers():
    tree = ast.parse(inspect.getsource(pr))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any("router." in ast.unparse(d) for d in node.decorator_list):
            yield node


def _first_call(node, name):
    lines = [s.lineno for s in ast.walk(node) if isinstance(s, ast.Call) and getattr(s.func, "id", None) == name]
    return min(lines) if lines else None


def test_every_payroll_door_that_asks_the_per_client_switch_asks_the_practice_check_first():
    judged = 0
    for node in _route_handlers():
        switch = _first_call(node, "assert_payroll_enabled")
        if switch is None and node.name != "put_payroll_enablement":
            continue
        judged += 1
        practice = _first_call(node, "assert_practice_payroll_is_the_partners")
        assert practice is not None, f"{node.name} asks whether payroll is switched on and never asks whose the practice's payroll is"
        if switch is not None:
            assert practice < switch, (
                f"{node.name} asks the per-client switch (line {switch}) before the practice check (line {practice}): a non-Partner "
                "would be told whether payroll is switched on for the practice")
    assert judged >= 18, f"the scan judged only {judged} doors"


@pytest.fixture()
def door(monkeypatch):
    """`POST /employees` with a database present and the two outer layers removed, so the door's own check is what answers."""
    monkeypatch.setattr(pr, "_db", lambda: object())
    monkeypatch.setattr(pr, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(ics, "get_internal_client_id", lambda firm_id: PRACTICE if firm_id == FIRM else None)
    reached = []

    def next_step(db, firm_id, client_id):
        reached.append(client_id)
        raise RuntimeError("past the practice check")

    monkeypatch.setattr(pr, "assert_payroll_enabled", next_step)
    return reached


def _employee(client_id):
    return EmployeeIn(client_id=client_id, name="A Colleague", employee_code="E-1", date_of_joining="2026-04-01")


def test_a_manager_is_told_the_practice_does_not_exist_at_a_payroll_door(door):
    with pytest.raises(HTTPException) as refused:
        pr.create_employee(_employee(PRACTICE), current_user=MANAGER)
    assert refused.value.status_code == 404 and refused.value.detail == "Client not found"
    assert door == [], "the door went on to the per-client switch for a non-Partner"


def test_a_partner_goes_through_and_so_does_anybody_for_an_ordinary_client(door):
    with pytest.raises(RuntimeError, match="past the practice check"):
        pr.create_employee(_employee(PRACTICE), current_user=PARTNER)
    with pytest.raises(RuntimeError, match="past the practice check"):
        pr.create_employee(_employee(CLIENT), current_user=MANAGER)
    assert door == [PRACTICE, CLIENT]


# ── the practice is not one of the firm's clients in a payroll list across clients (guardrail G2) ─────────────────────────────

from tests._capped_postgrest import CappedDB  # noqa: E402

A_CLIENT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
THE_PRACTICE = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _emp(i, client):
    return {"id": f"e{i:06d}", "firm_id": FIRM, "client_id": client, "name": f"Employee {i:05d}", "designation": "Clerk", "status": "active"}


def _att(i, employee):
    return {"id": f"a{i:06d}", "firm_id": FIRM, "employee_id": employee, "month": 8, "year": 2026,
            "working_days": 26, "days_present": 26, "casual_leaves": 0, "sick_leaves": 0, "earned_leaves": 0}


@pytest.fixture()
def firm(monkeypatch):
    """A client with two employees and the practice with one, with attendance entered for all three."""
    db = CappedDB({
        "payroll_employees": [_emp(1, A_CLIENT), _emp(2, A_CLIENT), _emp(3, THE_PRACTICE)],
        "attendance": [_att(1, "e000001"), _att(2, "e000002"), _att(3, "e000003")],
    })
    monkeypatch.setattr(pr, "_db", lambda: db)
    monkeypatch.setattr(pr, "get_internal_client_id", lambda firm_id: THE_PRACTICE if firm_id == FIRM else None)
    monkeypatch.setattr(ics, "get_internal_client_id", lambda firm_id: THE_PRACTICE if firm_id == FIRM else None)
    monkeypatch.setattr(pr, "assert_client_access", lambda *a, **k: None)
    return db


def test_a_list_across_clients_leaves_the_practices_own_staff_out_even_for_a_partner(firm):
    rows = [{"client_id": A_CLIENT, "n": 1}, {"client_id": THE_PRACTICE, "n": 2}, {"client_id": None, "n": 3}, {"n": 4}]
    kept = pr._the_firms_clients_only(PARTNER, rows)
    assert [r["n"] for r in kept] == [1, 3, 4], "a row of the practice is among the clients', or a firm-level row was dropped"
    roster = pr.list_employees(client_id=None, include_inactive=False, current_user=PARTNER)["data"]
    assert sorted(r["id"] for r in roster) == ["e000001", "e000002"]


def test_naming_the_practice_is_how_a_partner_reaches_its_roster(firm):
    roster = pr.list_employees(client_id=THE_PRACTICE, include_inactive=False, current_user=PARTNER)["data"]
    assert [r["id"] for r in roster] == ["e000003"]


#: A payroll route that names no client, run or employee and is NOT a list across clients, with why. Read on 21-11-2026.
NOT_A_LIST_ACROSS_CLIENTS: dict[str, str] = {
    "employee_import_template": "a blank CSV template: the column headings and no row of anybody's",
    "get_statutory_values": "the firm's own recorded statutory values (rates and slabs), which belong to no client",
    "delete_pt_slabs": "the firm's own recorded professional-tax slabs, which belong to no client",
    "one_time_earning_defaults": "the product's default kinds of one-time earning, no row of anybody's",
    "practice_staff": "ONE client's roster and not a list across clients: the practice's own, whose id the server reads off the firm "
                      "(POST-A-540). A Partner's alone (404 to anybody else), and the route asks the practice's two doors itself",
}

_NAMES_ITS_SUBJECT = ("data", "payload", "body")


def _names_a_subject(node) -> bool:
    """True when the handler cannot be called without an id (or a body that carries one): it answers for ONE thing, and the
    scope sweep (`tests/test_router_client_scope.py`) holds that it asks whose that thing is."""
    a = node.args
    params = a.args + a.kwonlyargs
    defaults = [None] * (len(a.args) - len(a.defaults)) + list(a.defaults) + list(a.kw_defaults)
    for p, d in zip(params, defaults, strict=True):
        if not (p.arg.endswith("_id") or p.arg in _NAMES_ITS_SUBJECT):
            continue
        if d is None or (isinstance(d, ast.Call) and ast.unparse(d).startswith(("Query(...", "Body(...", "Path("))):
            return True
    return False


def test_every_payroll_route_that_names_no_subject_narrows_across_clients_or_says_why_not():
    """The rule over the router, in both directions.

    The first version of this test failed only a call SPELLED `filter_by_client`, so a list with no narrowing at all passed it,
    and one existed: the year-end report with no client named read every run of the firm and returned every employee's pay to
    anybody with payroll read (found by the review of this change). The rule is now about the ROUTE: a handler that can be
    called without naming a client, a run or an employee answers across clients, and must go through the helper that narrows to
    the caller's clients and leaves the practice out, or be named above with the reason it lists nobody."""
    bare, unnarrowed, lists = [], [], 0
    for node in _route_handlers():
        calls = {getattr(c.func, "id", None) for c in ast.walk(node) if isinstance(c, ast.Call)}
        if "filter_by_client" in calls:
            bare.append(node.name)
        if _names_a_subject(node):
            continue
        if node.name in NOT_A_LIST_ACROSS_CLIENTS:
            assert "_the_firms_clients_only" not in calls, f"{node.name} narrows across clients now: take it off the list"
            continue
        lists += 1
        if "_the_firms_clients_only" not in calls:
            unnarrowed.append(node.name)
    assert not bare, f"a payroll list narrows by assignment and does not leave the practice out: {bare}"
    assert not unnarrowed, (
        f"a payroll route that names no client, run or employee does not narrow its answer to the caller's clients: {unnarrowed}")
    assert lists >= 9, f"the scan judged only {lists} lists across clients"
    live = {n.name for n in _route_handlers()}
    assert set(NOT_A_LIST_ACROSS_CLIENTS) <= live, f"named and no longer a route: {sorted(set(NOT_A_LIST_ACROSS_CLIENTS) - live)}"


def test_the_route_scan_tells_a_list_from_a_door():
    """The negative control for `_names_a_subject`: a required id is a door, an optional one is a list."""
    def handler(src):
        return ast.parse(src).body[0]
    assert _names_a_subject(handler("def f(client_id: str, current_user=None): ..."))
    assert _names_a_subject(handler("def f(run_id: str = Path(...)): ..."))
    assert _names_a_subject(handler("def f(data: EmployeeIn, current_user=None): ..."))
    assert not _names_a_subject(handler("def f(client_id: Optional[str] = None): ..."))
    assert not _names_a_subject(handler("def f(client_id: Optional[str] = Query(None)): ..."))
    assert not _names_a_subject(handler("def f(month: str, *, client_id: Annotated[Optional[str], Query()] = None): ..."))


# ── the year-end report with no client named (the hole the review found) ─────────────────────────────────────────────────────

import services.payroll_report_service as prs  # noqa: E402

B_CLIENT = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _run(i, client, month="2026-04"):
    return {"id": f"r{i}", "firm_id": FIRM, "client_id": client, "month": month}


def _slip(i, run, employee, name):
    return {"id": f"s{i}", "run_id": run, "employee_id": employee, "gross_paise": 5000000, "net_paise": 4500000,
            "tds_paise": 100000, "pt_paise": 20000, "pf_employee_paise": 180000, "esi_employee_paise": 0,
            "payroll_employees": {"name": name, "pan": "ABCPK1234F", "designation": "Clerk", "department": None}}


@pytest.fixture()
def year(monkeypatch):
    """Three clients' runs for one month: a client the Manager is assigned to, one they are not, and the practice."""
    db = CappedDB({
        "payroll_runs": [_run(1, A_CLIENT), _run(2, B_CLIENT), _run(3, THE_PRACTICE)],
        "payroll_slips": [_slip(1, "r1", "e1", "Asha"), _slip(2, "r2", "e2", "Bhaskar"), _slip(3, "r3", "e3", "A Colleague")],
    })
    monkeypatch.setattr(pr, "_db", lambda: db)
    monkeypatch.setattr(prs, "privileged_for", lambda d: d)
    monkeypatch.setattr(pr, "get_internal_client_id", lambda firm_id: THE_PRACTICE if firm_id == FIRM else None)
    monkeypatch.setattr(ics, "get_internal_client_id", lambda firm_id: THE_PRACTICE if firm_id == FIRM else None)
    # The assignment narrowing, stated: a Partner is firm-wide, the Manager is assigned to A_CLIENT alone.
    monkeypatch.setattr(pr, "filter_by_client", lambda user, rows: rows if user["role"] == "Partner"
                        else [r for r in rows if r.get("client_id") == A_CLIENT])
    return db


def test_the_year_end_report_with_no_client_named_is_the_callers_clients_and_never_the_practice(year):
    manager = pr.get_year_end_summary(financial_year="2026-27", client_id=None, current_user=MANAGER)["data"]
    assert [r["employee"]["name"] for r in manager["rows"]] == ["Asha"], (
        "a Manager read the pay of an employee of a client they are not assigned to, or of the firm's own staff")
    partner = pr.get_year_end_summary(financial_year="2026-27", client_id=None, current_user=PARTNER)["data"]
    assert [r["employee"]["name"] for r in partner["rows"]] == ["Asha", "Bhaskar"], (
        "the firm's own staff are in a list across the firm's clients (G2), or a client's are missing")


def test_the_years_on_file_are_of_the_callers_clients(monkeypatch, year):
    seen = {}

    def narrow_spy(user, rows):
        seen["called_with"] = [r.get("client_id") for r in rows]
        return [r for r in rows if r.get("client_id") == A_CLIENT]

    monkeypatch.setattr(pr, "filter_by_client", narrow_spy)
    data = pr.get_year_end_summary(financial_year="2026-27", client_id=None, current_user=MANAGER)["data"]
    assert data["financial_years"] == ["2026-27"]
    assert seen["called_with"], "the list of years was not narrowed: the runs it is read from carry no client"


def test_the_year_end_service_cannot_be_called_without_saying_whose_runs_may_be_answered_for():
    """`narrow` has no default. The service reads with the privileged client, so a caller that forgets it must fail and not
    answer for the whole firm."""
    for fn in (prs.employee_year_totals, prs.financial_years):
        param = inspect.signature(fn).parameters["narrow"]
        assert param.default is inspect.Parameter.empty and param.kind is inspect.Parameter.KEYWORD_ONLY


# ── the three lists a Partner opens FOR the practice ─────────────────────────────────────────────────────────────────────────

def test_a_stale_client_on_a_firm_wide_list_is_ignored_and_not_refused(firm, monkeypatch):
    """On these lists the id only says which screen is asking. An id that is not the practice changes nothing, and the scope
    check is not even asked, so a bookmarked address naming a client the caller has lost does not 404 the whole sheet."""
    def refuse(*a, **k):
        raise AssertionError("the scope check was asked about an id that is not the practice")
    monkeypatch.setattr(pr, "assert_client_access", refuse)
    board = pr.attendance_board(month="2026-08", client_id="not-a-client-of-anyone", current_user=MANAGER)["data"]
    assert sorted(e["id"] for e in board["employees"]) == ["e000001", "e000002"] and board["practice_client_id"] is None


def test_the_leave_ledger_lists_the_practices_staff_only_when_a_partner_names_the_practice(firm):
    plain = pr.leave_ledger(year=2026, current_user=PARTNER)["data"]["rows"]
    assert sorted(r["employee_id"] for r in plain) == ["e000001", "e000002"]
    named = pr.leave_ledger(year=2026, client_id=THE_PRACTICE, current_user=PARTNER)["data"]["rows"]
    assert sorted(r["employee_id"] for r in named) == ["e000001", "e000002", "e000003"]
    with pytest.raises(HTTPException) as refused:
        pr.leave_ledger(year=2026, client_id=THE_PRACTICE, current_user=MANAGER)
    assert refused.value.status_code == 404


def test_the_practices_own_payroll_page_reads_its_own_line(monkeypatch):
    """`GET /client-states` is what a client's Payroll page reads to say whether payroll is switched on. The firm-wide answer
    leaves the practice out, so the practice's own page said "Payroll is off" while payroll was on (found by the review)."""
    db = CappedDB({
        "client_payroll_settings": [
            {"id": "s1", "firm_id": FIRM, "client_id": A_CLIENT, "payroll_enabled": True, "inputs_due_day": 25},
            {"id": "s2", "firm_id": FIRM, "client_id": THE_PRACTICE, "payroll_enabled": True, "inputs_due_day": 25}],
        "payroll_runs": [],
        "clients": [{"id": A_CLIENT, "firm_id": FIRM, "client_name": "A Client"},
                    {"id": THE_PRACTICE, "firm_id": FIRM, "client_name": "The Practice"}],
    })
    monkeypatch.setattr(pr, "_db", lambda: db)
    monkeypatch.setattr(pr, "get_internal_client_id", lambda firm_id: THE_PRACTICE if firm_id == FIRM else None)
    monkeypatch.setattr(ics, "get_internal_client_id", lambda firm_id: THE_PRACTICE if firm_id == FIRM else None)
    monkeypatch.setattr(pr, "assert_client_access", lambda *a, **k: None)
    queue = pr.payroll_client_states(month="2026-08", current_user=PARTNER)["data"]["clients"]
    assert [c["client_id"] for c in queue] == [A_CLIENT], "the firm's queue lists the practice among its clients"
    own = pr.payroll_client_states(month="2026-08", client_id=THE_PRACTICE, current_user=PARTNER)["data"]["clients"]
    line = [c for c in own if c["client_id"] == THE_PRACTICE]
    assert len(line) == 1 and line[0]["payroll_enabled"] is True
    with pytest.raises(HTTPException) as refused:
        pr.payroll_client_states(month="2026-08", client_id=THE_PRACTICE, current_user=MANAGER)
    assert refused.value.status_code == 404


def test_the_attendance_sheet_leaves_the_practice_out_until_a_partner_names_it(firm):
    plain = pr.attendance_board(month="2026-08", current_user=PARTNER)["data"]
    assert sorted(e["id"] for e in plain["employees"]) == ["e000001", "e000002"]
    assert sorted(a["employee_id"] for a in plain["attendance"]) == ["e000001", "e000002"]
    assert plain["practice_client_id"] is None

    named = pr.attendance_board(month="2026-08", client_id=THE_PRACTICE, current_user=PARTNER)["data"]
    assert sorted(e["id"] for e in named["employees"]) == ["e000001", "e000002", "e000003"]
    assert sorted(a["employee_id"] for a in named["attendance"]) == ["e000001", "e000002", "e000003"]
    assert named["practice_client_id"] == THE_PRACTICE

    # Naming an ordinary client adds nothing and names no practice: that client's roster is on the firm-wide sheet already.
    other = pr.attendance_board(month="2026-08", client_id=A_CLIENT, current_user=PARTNER)["data"]
    assert sorted(e["id"] for e in other["employees"]) == ["e000001", "e000002"] and other["practice_client_id"] is None


def test_a_manager_who_names_the_practice_on_the_attendance_sheet_is_told_it_does_not_exist(firm):
    with pytest.raises(HTTPException) as refused:
        pr.attendance_board(month="2026-08", client_id=THE_PRACTICE, current_user=MANAGER)
    assert refused.value.status_code == 404
