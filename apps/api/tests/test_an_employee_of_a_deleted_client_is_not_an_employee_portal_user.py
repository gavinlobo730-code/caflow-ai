"""POST-A-504: an employee of a client the practice has DELETED is refused at the employee portal's door.

WHAT WAS WRONG
    Deleting a client sets `clients.deleted_at` and closes it to every staff screen, and the client portal already refuses a contact
    of one (POST-A-447). `get_current_portal_employee` resolved the employee from `payroll_employees` alone and never asked the
    client, so an employee of a deleted client kept signing in, reading their payslips and leave, and could make their one write,
    the tax declaration, into a payroll the practice no longer serves. The commit that closed the client half said only that the
    employee portal is "self-scoped"; whether it should be left open was written nowhere.

THE DECISION (20-11-2026, taken under the three tests: lawful, safe for the data, best for the product)
    The employee is refused at the door, in the same words as every other refusal here ("Not an employee portal user."), because a
    different sentence would say this identity is an employee of a client that exists. The reasons: the practice deleted the client,
    and every other door treats a deleted client as closed; the employer, not the practice's portal, owes the employee a payslip and
    keeps the records; and a door left open on a closed client is the one a later change forgets. An ARCHIVED client is untouched, as
    for the client portal. The cost is real and is said: an employee of a deleted client cannot read a payslip here and asks the
    employer. Reversing it is one condition.

WHAT THIS HOLDS (no database: the client row and the employee row are a fake of the two tables)
    * an employee of a live client resolves, and the same employee is refused once the client is deleted;
    * the refusal is the one every other refusal at this door is, word for word;
    * a client row of ANOTHER firm that carries the id does not make the client live;
    * an archived client is not refused (the recorded decision);
    * an employee the CA has withdrawn is still refused, and one with no client is refused;
    * a read of the client that fails is not a pass.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from core import portal_auth, supabase_client
from tests.e2e_harness import FakeDB

FIRM, OTHER_FIRM = "F-504", "F-OTHER"
CLIENT = "CL-504"
AUTH = "auth-emp-1"
JWT = {"auth_user_id": AUTH, "email": "asha@example.test"}


@pytest.fixture()
def world(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    db = FakeDB()
    db.seed("payroll_employees", {"id": "E1", "firm_id": FIRM, "client_id": CLIENT, "name": "Asha", "employee_code": "E-001",
                                  "portal_enabled": True, "auth_user_id": AUTH})
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM, "client_name": "Mehta Traders", "deleted_at": None})
    monkeypatch.setattr(supabase_client, "get_service_supabase", lambda: db)
    return db


def _refusal():
    with pytest.raises(HTTPException) as err:
        portal_auth.get_current_portal_employee(JWT)
    return err.value


def test_an_employee_of_a_live_client_resolves(world):
    ctx = portal_auth.get_current_portal_employee(JWT)
    assert ctx["employee_id"] == "E1" and ctx["client_id"] == CLIENT and ctx["role"] == "PortalEmployee"


def test_the_same_employee_is_refused_once_the_client_is_deleted(world):
    portal_auth.get_current_portal_employee(JWT)
    next(r for r in world.rows("clients") if r["id"] == CLIENT)["deleted_at"] = "2026-11-18T05:00:00+00:00"
    assert _refusal().status_code == 403


def test_the_refusal_is_the_one_every_other_refusal_at_this_door_is(world):
    next(r for r in world.rows("clients") if r["id"] == CLIENT)["deleted_at"] = "2026-11-18T05:00:00+00:00"
    deleted = _refusal().detail
    next(r for r in world.rows("payroll_employees") if r["id"] == "E1")["portal_enabled"] = False
    withdrawn = _refusal().detail
    assert deleted == withdrawn == "Not an employee portal user."


def test_a_client_row_of_another_firm_carrying_the_id_does_not_make_the_client_live(world):
    world.rows("clients")[0]["firm_id"] = OTHER_FIRM
    assert _refusal().status_code == 403


def test_no_client_row_at_all_is_a_refusal(world):
    world.rows("clients").clear()
    assert _refusal().status_code == 403


def test_an_archived_client_is_not_refused(world):
    # The recorded decision: archiving is not deleting, as for the client portal. A `status`/`archived` column is not even read.
    next(r for r in world.rows("clients") if r["id"] == CLIENT)["status"] = "archived"
    assert portal_auth.get_current_portal_employee(JWT)["employee_id"] == "E1"


def test_an_employee_the_ca_has_withdrawn_is_still_refused(world):
    next(r for r in world.rows("payroll_employees") if r["id"] == "E1")["portal_enabled"] = False
    assert _refusal().status_code == 403


def test_an_employee_with_no_client_is_refused(world):
    next(r for r in world.rows("payroll_employees") if r["id"] == "E1")["client_id"] = None
    assert _refusal().status_code == 403


def test_a_read_of_the_client_that_fails_is_not_a_pass(world, monkeypatch):
    real = world.table

    def table(name):
        if name == "clients":
            raise RuntimeError("the clients read failed")
        return real(name)

    monkeypatch.setattr(world, "table", table)
    with pytest.raises(RuntimeError):
        portal_auth.get_current_portal_employee(JWT)


def test_a_mock_mode_request_is_still_refused_before_any_of_this(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert _refusal().status_code == 403
