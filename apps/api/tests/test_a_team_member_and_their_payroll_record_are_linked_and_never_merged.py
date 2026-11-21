"""A TEAM MEMBER AND THEIR RECORD IN THE FIRM'S OWN PAYROLL ARE LINKED, AND NEVER MERGED (POST-A-540).

WHAT WAS MISSING
    A member of the firm's staff is two records: a sign-in on the Team screen (`users`) and, since the firm runs its own staff's
    payroll in My practice (POST-A-532), an employee there (`payroll_employees`). Nothing said they were one person.

WHAT IS ASSERTED
    * THE THREE RULES OF A LINK, each refused in a sentence before anything is written: the member is this firm's (a stranger, a
      deleted member and an invented id answer in the same words), the employee is in the firm's OWN payroll (a client's employee
      is nobody on the Team screen), and one member is at most one employee.
    * A LINK, NEVER A MERGE: writing or removing a link changes that one column and nothing else of either record.
    * WHOSE IT IS: the roster the Team screen reads is a Partner's alone and a Manager is told 404 (guardrail G1's answer), and it
      carries no pay, no identifier and no bank detail. The link door asks the practice check (G4) after the scope.
    * THE CREATE DOOR: an employee created with a member is asked the same three rules, and one created without never names the
      column (so a server that reaches production minutes before migration 776 cannot break an ordinary create).
    * THE EDIT DOOR takes no link: the link has a door of its own.

Nothing here was run against a real database (the database's half is `..._pg.py`) or on the live site.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.payroll as pr
import services.internal_client_service as ics
import services.practice_staff_link_service as link
from models.payroll import EmployeeIn, EmployeeUpdateIn
from tests.e2e_harness import FakeDB

FIRM, OTHER_FIRM = "firm-link-1", "firm-link-2"
PRACTICE, CLIENT = "client-practice", "client-ordinary"
PARTNER = {"id": "u-partner", "firm_id": FIRM, "role": "Partner", "auth_user_id": "a-partner", "email": "p@firm.test"}
MANAGER = {"id": "u-manager", "firm_id": FIRM, "role": "Manager", "auth_user_id": "a-manager", "email": "m@firm.test"}


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    for uid, firm, deleted in (("u-partner", FIRM, None), ("u-manager", FIRM, None), ("u-asha", FIRM, None),
                               ("u-gone", FIRM, "2026-10-01T00:00:00+00:00"), ("u-stranger", OTHER_FIRM, None)):
        d.seed("users", {"id": uid, "firm_id": firm, "full_name": uid, "email": f"{uid}@x.test", "deleted_at": deleted})
    d.seed("payroll_employees", {"id": "e-asha", "firm_id": FIRM, "client_id": PRACTICE, "name": "Asha Rao", "status": "active",
                                 "employee_code": "S001", "designation": "Article", "pan": "ABCPR1234F", "basic_paise": 4000000,
                                 "bank_account_no": "0011223344", "staff_user_id": None})
    d.seed("payroll_employees", {"id": "e-ravi", "firm_id": FIRM, "client_id": PRACTICE, "name": "Ravi K", "status": "active",
                                 "staff_user_id": None})
    d.seed("payroll_employees", {"id": "e-client", "firm_id": FIRM, "client_id": CLIENT, "name": "A Client's Clerk", "status": "active",
                                 "staff_user_id": None})
    d.seed("client_payroll_settings", {"firm_id": FIRM, "client_id": PRACTICE, "payroll_enabled": True})
    practice_of = lambda firm_id: PRACTICE if firm_id == FIRM else None      # noqa: E731
    monkeypatch.setattr(pr, "_db", lambda: d)
    monkeypatch.setattr(pr, "get_internal_client_id", practice_of)
    monkeypatch.setattr(ics, "get_internal_client_id", practice_of)
    monkeypatch.setattr(link, "get_internal_client_id", practice_of)
    monkeypatch.setattr(pr, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(pr, "assert_payroll_enabled", lambda *a, **k: None)
    monkeypatch.setattr(pr.timeline_service, "log", lambda *a, **k: None)
    audit = []
    import services.audit_service as audit_service
    monkeypatch.setattr(audit_service, "log_event", lambda *a, **k: audit.append((a, k)))
    d.audit = audit
    return d


def _employee(db, employee_id):
    return next(r for r in db.rows("payroll_employees") if r["id"] == employee_id)


def _put(employee_id, member, user=PARTNER):
    return pr.link_employee_to_team_member(employee_id, pr.StaffLinkIn(staff_user_id=member), current_user=user)


# ── the link door ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_link_is_written_on_the_employee_and_changes_nothing_else_of_either_record(db):
    before_employee = dict(_employee(db, "e-asha"))
    before_member = dict(next(r for r in db.rows("users") if r["id"] == "u-asha"))
    answer = _put("e-asha", "u-asha")
    assert answer["success"] and answer["data"]["staff_user_id"] == "u-asha"
    after = dict(_employee(db, "e-asha"))
    assert {k for k in after if after[k] != before_employee.get(k)} == {"staff_user_id"}, "the link changed something else of the employee"
    assert next(r for r in db.rows("users") if r["id"] == "u-asha") == before_member, "the link wrote to the member's own record"
    assert set(answer["data"]) == {"id", "name", "employee_code", "designation", "status", "staff_user_id"}, "the answer carries more than the roster shows"
    [(args, kw)] = db.audit
    assert kw["old_data"] == {"staff_user_id": None} and kw["new_data"] == {"staff_user_id": "u-asha"}
    assert kw["actor_id"] == "a-partner", "the audit log names the internal id, and it takes the sign-in's"


def test_a_link_is_removed_by_sending_none_and_the_employee_stays(db):
    _put("e-asha", "u-asha")
    assert _put("e-asha", None)["data"]["staff_user_id"] is None
    assert _employee(db, "e-asha")["name"] == "Asha Rao" and _employee(db, "e-asha")["staff_user_id"] is None


def test_writing_the_link_an_employee_already_carries_is_not_refused_as_a_duplicate_of_itself(db):
    _put("e-asha", "u-asha")
    assert _put("e-asha", "u-asha")["data"]["staff_user_id"] == "u-asha"


@pytest.mark.parametrize("member", ["u-stranger", "u-gone", "11111111-1111-1111-1111-111111111111"])
def test_a_member_who_is_not_this_firms_is_answered_in_one_sentence_and_nothing_is_written(db, member):
    with pytest.raises(HTTPException) as refused:
        _put("e-asha", member)
    assert refused.value.status_code == 404 and refused.value.detail == "That team member was not found."
    assert _employee(db, "e-asha")["staff_user_id"] is None and db.audit == []


def test_one_member_is_at_most_one_employee(db):
    _put("e-asha", "u-asha")
    with pytest.raises(HTTPException) as refused:
        _put("e-ravi", "u-asha")
    assert refused.value.status_code == 409
    assert "already linked to Asha Rao" in refused.value.detail and "Remove that link first" in refused.value.detail
    assert _employee(db, "e-ravi")["staff_user_id"] is None


@pytest.mark.parametrize("member", ["u-asha", None])
def test_a_clients_employee_is_nobody_on_the_team_screen(db, member):
    with pytest.raises(HTTPException) as refused:
        _put("e-client", member)
    assert refused.value.status_code == 422 and refused.value.detail == link.A_CLIENTS_EMPLOYEE
    assert _employee(db, "e-client")["staff_user_id"] is None and db.audit == []


def test_the_link_door_asks_the_scope_and_then_whose_the_practices_payroll_is(db, monkeypatch):
    """With the outer layers taken away, the door's own practice check is what answers a Manager: 404, in the words of a client
    that does not exist."""
    with pytest.raises(HTTPException) as refused:
        _put("e-asha", "u-asha", user=MANAGER)
    assert refused.value.status_code == 404 and refused.value.detail == "Client not found"
    assert _employee(db, "e-asha")["staff_user_id"] is None
    import ast
    import inspect
    body = ast.parse(inspect.getsource(pr.link_employee_to_team_member))
    order = [n.func.id for n in ast.walk(body) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id in ("_assert_employee_scope", "assert_practice_payroll_is_the_partners")]
    assert order == ["_assert_employee_scope", "assert_practice_payroll_is_the_partners"]


def test_an_employee_that_does_not_exist_is_not_found(db):
    with pytest.raises(HTTPException) as refused:
        _put("e-nobody", "u-asha")
    assert refused.value.status_code == 404 and refused.value.detail == "Employee not found"


# ── the roster the Team screen reads ────────────────────────────────────────────────────────────────────────────────────

def test_the_roster_is_the_practices_employees_with_their_links_and_nothing_of_pay(db):
    _put("e-asha", "u-asha")
    data = pr.practice_staff(current_user=PARTNER)["data"]
    assert data["practice_client_id"] == PRACTICE and data["payroll_enabled"] is True
    assert [(e["id"], e["staff_user_id"]) for e in data["employees"]] == [("e-asha", "u-asha"), ("e-ravi", None)], \
        "a client's employee is on the roster, or the practice's are missing or out of order"
    for e in data["employees"]:
        assert set(e) <= {"id", "name", "employee_code", "designation", "status", "staff_user_id"}, f"the roster carries {sorted(e)}"


def test_a_manager_is_told_the_roster_does_not_exist(db):
    with pytest.raises(HTTPException) as refused:
        pr.practice_staff(current_user=MANAGER)
    assert refused.value.status_code == 404


def test_a_firm_with_no_practice_has_an_empty_roster_and_that_is_a_fact(db, monkeypatch):
    monkeypatch.setattr(link, "get_internal_client_id", lambda firm_id: None)
    assert pr.practice_staff(current_user=PARTNER)["data"] == {"practice_client_id": None, "payroll_enabled": False, "employees": []}


def test_a_switch_that_could_not_be_read_is_unknown_and_never_off(db, monkeypatch):
    real = db.table

    def table(name):
        if name == "client_payroll_settings":
            raise RuntimeError("the settings could not be read")
        return real(name)
    monkeypatch.setattr(db, "table", table)
    monkeypatch.setattr(link, "capture_soft_failure", lambda *a, **k: None)
    data = pr.practice_staff(current_user=PARTNER)["data"]
    assert data["payroll_enabled"] is None and len(data["employees"]) == 2


def test_a_practice_with_no_settings_row_is_not_switched_on(db):
    db.rows("client_payroll_settings").clear()
    assert pr.practice_staff(current_user=PARTNER)["data"]["payroll_enabled"] is False


# ── the create door ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _new(client_id, **more):
    return EmployeeIn(client_id=client_id, name="New Person", basic_paise=3000000, **more)


def test_an_employee_of_the_firms_own_payroll_can_be_created_linked(db):
    made = pr.create_employee(_new(PRACTICE, staff_user_id="u-manager"), current_user=PARTNER)["data"]
    assert _employee(db, made["id"])["staff_user_id"] == "u-manager"
    assert any(k["metadata"] == {"what": "team_member_link"} and k["new_data"] == {"staff_user_id": "u-manager"} for _a, k in db.audit)


def test_an_employee_created_without_a_member_never_names_the_column(db):
    made = pr.create_employee(_new(PRACTICE), current_user=PARTNER)["data"]
    assert "staff_user_id" not in _employee(db, made["id"]), "an ordinary create names the link column, which a server ahead of migration 776 cannot write"


@pytest.mark.parametrize("client, member, status", [
    (CLIENT, "u-asha", 422),          # a client's employee
    (PRACTICE, "u-stranger", 404),    # a member of another firm
    (PRACTICE, "u-gone", 404),        # a deleted member
])
def test_the_create_door_asks_the_three_rules_before_it_writes(db, client, member, status):
    count = len(db.rows("payroll_employees"))
    with pytest.raises(HTTPException) as refused:
        pr.create_employee(_new(client, staff_user_id=member), current_user=PARTNER)
    assert refused.value.status_code == status
    assert len(db.rows("payroll_employees")) == count, "an employee was written before the link was asked"


def test_the_create_door_refuses_a_member_who_is_already_an_employee(db):
    _put("e-asha", "u-asha")
    count = len(db.rows("payroll_employees"))
    with pytest.raises(HTTPException) as refused:
        pr.create_employee(_new(PRACTICE, staff_user_id="u-asha"), current_user=PARTNER)
    assert refused.value.status_code == 409 and len(db.rows("payroll_employees")) == count


def test_the_edit_door_takes_no_link():
    assert "staff_user_id" not in EmployeeUpdateIn.model_fields, "the employee edit accepts the link: it has a door of its own, which asks the three rules"
