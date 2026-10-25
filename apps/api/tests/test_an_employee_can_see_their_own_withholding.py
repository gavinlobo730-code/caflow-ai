"""The employee-facing API, and what makes it safe (PAY-26).

WHAT WAS MISSING
    An employee has held a real Supabase identity since migration 262 —
    `payroll_employees.auth_user_id` with `portal_enabled` — and the API had no
    way to resolve one. So the employee portal could read only what RLS let it
    read straight over PostgREST, and anything COMPUTED was unreachable to an
    employee however well it worked for the CA. The §192 projection is the case
    that forced it: `_compute_slip` is the payroll run's own engine, there is no
    second one, and it is exactly the working an employee asks their employer
    for in January.

THE PROPERTY THAT MATTERS IS NOT "IT RETURNS A NUMBER"
    It is that the number is the SAME one the staff door returns, and that the
    endpoint cannot be asked about anybody else. The second is structural
    rather than checked: there is no employee_id parameter, so there is nothing
    to tamper with — and that is asserted on the SIGNATURE, so an id added
    later fails here rather than becoming a way in.

WHAT IS DELIBERATELY ABSENT
    A write path. An employee submitting a declaration or a reimbursement claim
    is a separate decision with its own consequences; a test asserts no route in
    this module accepts one, so adding it is deliberate rather than incidental.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.payroll as payroll_mod
import routers.portal_employee as portal_mod
from core.auth import get_current_user
from core.portal_auth import get_current_portal_employee
from tests.e2e_harness import FakeDB

FY = "2026-27"
FIRM = "F1"
CLIENT = "C1"
EMP = "E1"
PARTNER = {"id": "u1", "firm_id": FIRM, "role": "Partner", "email": "p@f1.test"}
EMPLOYEE_CTX = {
    "portal": True, "employee": True, "employee_id": EMP,
    "client_id": CLIENT, "firm_id": FIRM, "name": "A Salaried Person",
    "employee_code": "EMP-001", "email": "e@f1.test", "role": "PortalEmployee",
}


@pytest.fixture
def app_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(payroll_mod, "_db", lambda: db)
    app = FastAPI()
    app.include_router(portal_mod.router)
    app.include_router(payroll_mod.router)
    app.dependency_overrides[get_current_portal_employee] = lambda: dict(EMPLOYEE_CTX)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False), db


def _employee(db, **over):
    row = {
        "id": EMP, "firm_id": FIRM, "client_id": CLIENT, "status": "active",
        "name": "A Salaried Person",
        "basic_paise": 2_00_000_00, "hra_percent": 0, "da_percent": 0,
        "lta_paise": 0, "medical_paise": 0, "special_allowance_paise": 0,
        "other_allowances_paise": 0,
        "pf_applicable": False, "esi_applicable": False, "pt_applicable": False,
        "joining_date": "2020-04-01",
    }
    row.update(over)
    db.seed("payroll_employees", row)
    return row


# ── one engine, two doors ───────────────────────────────────────────────────

def test_the_employee_sees_exactly_what_the_CA_sees(app_db):
    """Not "a similar number" — the same object, field for field.

    PAY-10's whole finding was a second withholding engine in the browser; a
    second one for the employee's side of the screen would be the same defect
    with a different audience.
    """
    client, db = app_db
    _employee(db)
    mine = client.get(f"/api/portal/employee/tds-projection?financial_year={FY}")
    theirs = client.get(
        f"/api/payroll/tds-projection?client_id={CLIENT}&employee_id={EMP}"
        f"&financial_year={FY}")
    assert mine.status_code == 200 and theirs.status_code == 200
    assert mine.json()["data"] == theirs.json()["data"]


def test_the_caveats_travel_with_the_figures(app_db):
    """An employee reading a projection without them takes an estimate for a
    decision. §192(1) estimates on salary and a projected month assumes a full
    month's attendance — both sentences are the payroll module's and both must
    reach the person the money comes out of."""
    client, db = app_db
    _employee(db)
    data = client.get(
        f"/api/portal/employee/tds-projection?financial_year={FY}").json()["data"]
    assert data["gaps"], "a projection with no caveat reads as a settled figure"
    assert any("attendance" in g for g in data["gaps"])


# ── the endpoint cannot be asked about anybody else ─────────────────────────

_IDENTIFYING = ("employee_id", "client_id", "firm_id", "employee_code",
                "auth_user_id", "user_id")


@pytest.mark.parametrize("route", [r for r in portal_mod.router.routes
                                   if hasattr(r, "endpoint")],
                         ids=lambda r: getattr(r, "path", "?"))
def test_no_employee_route_takes_an_identifying_parameter(route):
    """THE SAFETY IS STRUCTURAL, so it is asserted on the signature.

    A check inside a handler can be forgotten on the next endpoint; a parameter
    that does not exist cannot be tampered with. Every id comes from the
    resolved principal.
    """
    params = set(inspect.signature(route.endpoint).parameters)
    offending = params & set(_IDENTIFYING)
    assert not offending, (
        f"{route.path} accepts {sorted(offending)} — an employee could then ask "
        f"for a colleague's salary by editing a query string. Take it from the "
        f"principal.")


#: The ONE write the employee API has: the employee's own Form 12BB declaration. It is not a new capability: migration 297 let the
#: employee file it from the browser, with their own token, and POST-A-010 moved every browser write of a payroll table behind the
#: API. What the route may and may not do (it carries no verified amount, resets what the CA had checked, refuses a verified
#: declaration, and refuses what payroll cannot give effect to) is held by
#: `test_an_employee_files_their_own_declaration_through_the_server.py`. A reimbursement claim, or any other write, is still a
#: separate decision and still fails here.
_THE_ONE_WRITE = {("PUT", "/api/portal/employee/tax-declaration")}


@pytest.mark.parametrize("route", [r for r in portal_mod.router.routes
                                   if hasattr(r, "methods")],
                         ids=lambda r: f"{sorted(r.methods)}{getattr(r, 'path', '?')}")
def test_the_employee_api_is_read_only_but_for_the_one_declaration(route):
    """Owner decision of 14-09-2026: read-only, self-scoped, narrow. The exception is named, singular and held elsewhere."""
    writes = {(m, route.path) for m in route.methods if m not in {"GET", "HEAD", "OPTIONS"}}
    assert writes <= _THE_ONE_WRITE, (
        f"{route.path} accepts {sorted(route.methods)}. An employee write path "
        f"is a separate decision — declarations and reimbursement claims have "
        f"their own consequences.")


#: The one GET that answers a person who is not an employee instead of refusing them (POST-A-010): "is this identity an
#: activated employee?" is asked of every signed-in person by the activation page and the client portal's dashboard, so
#: "no" is its ordinary answer and a 403 there would put a refusal in the log for every client login.
_ANSWERS_NO = {"/api/portal/employee/access"}


def test_every_employee_route_resolves_the_principal(app_db):
    """A route on this router with no principal is an open door.

    Asserted by REMOVING the override: with the real dependency in place and no
    Supabase URL configured, every route must refuse.
    """
    client, db = app_db
    client.app.dependency_overrides.pop(get_current_portal_employee)
    for route in portal_mod.router.routes:
        if "GET" not in getattr(route, "methods", set()):
            continue
        res = client.get(route.path + "?financial_year=" + FY)
        if route.path in _ANSWERS_NO:
            # Allowed to answer 200, and only with "no". Which of the refusals or the "no" this environment gives depends
            # on APP_ENV (CI runs as development, where the sign-in layer lets a dev identity through and the answer is
            # the "no"; elsewhere it is a 503), so both are accepted and a "yes" never is.
            if res.status_code == 200:
                assert res.json()["data"] == {"enabled": False}, (
                    f"{route.path} said an identity with no employee behind it is an employee")
                continue
        # 401 the JWT is missing or bad, 403 the identity is not an employee,
        # 503 the auth layer itself could not answer (core/auth raises that
        # deliberately rather than a 403, so a transient lookup failure is not
        # reported as a permanent refusal). All three are refusals; a 200 is
        # an open door.
        assert res.status_code in (401, 403, 503), (
            f"{route.path} answered {res.status_code} with no employee "
            f"principal resolved")


def test_a_principal_whose_employee_row_is_gone_is_refused_not_answered(app_db):
    """The ids came from the principal, so a miss means the principal is wrong.

    403 rather than the staff door's 200/success=false: there is no request to
    correct, and answering 200 with an empty projection would show a live
    employee a year of zeros.
    """
    client, db = app_db          # no employee seeded
    res = client.get(f"/api/portal/employee/tds-projection?financial_year={FY}")
    assert res.status_code == 403


def test_an_employee_of_another_firm_is_not_reachable(app_db):
    """The firm and the client are BOTH matched, so a principal carrying the
    right employee id under the wrong firm reads nothing."""
    client, db = app_db
    _employee(db, firm_id="F2")
    res = client.get(f"/api/portal/employee/tds-projection?financial_year={FY}")
    assert res.status_code == 403


def test_a_malformed_financial_year_is_refused_by_the_type(app_db):
    """The year is the ONLY thing the caller chooses, so it is the only thing
    that can be malformed. `2026-28` passes a shape regex and then means
    2026-27 — CLAUDE.md records why FYLabel exists and why it must sit in the
    Annotated position."""
    client, db = app_db
    _employee(db)
    assert client.get(
        "/api/portal/employee/tds-projection?financial_year=2026-28"
    ).status_code == 422
    assert client.get(
        "/api/portal/employee/tds-projection?financial_year=nonsense"
    ).status_code == 422


def test_the_employee_api_is_exactly_these_doors(app_db):
    """The doors the employee has, listed, so a new one is a decision somebody writes down here.

    This used to say there was no /me, deliberately: the portal read its own row over PostgREST under migration 262's policy, and
    a second door onto the same fact was the pattern this repository keeps undoing. POST-A-010 closed the browser's reach into the
    payroll tables, so the portal's own record, payslip list, leave balance and declaration are routes, each on THIS principal and
    none taking a person (the signature test above): `/access` is the one question two pages ask to decide where to send somebody,
    and `/me` is the record. The payslip PDF names a DOCUMENT, never a person: `slip_id` is resolved only within the principal's
    own released slips (see test_an_employee_can_download_their_own_payslip)."""
    assert sorted((sorted(m for m in r.methods if m != "HEAD")[0], r.path) for r in portal_mod.router.routes
                  if hasattr(r, "methods")) == [
        ("GET", "/api/portal/employee/access"),
        ("GET", "/api/portal/employee/leave-balances"),
        ("GET", "/api/portal/employee/me"),
        ("GET", "/api/portal/employee/payslips"),
        ("GET", "/api/portal/employee/payslips/{slip_id}/pdf"),
        ("GET", "/api/portal/employee/tax-declaration"),
        ("GET", "/api/portal/employee/tds-projection"),
        ("PUT", "/api/portal/employee/tax-declaration"),
    ]


# ── the principal itself ────────────────────────────────────────────────────

def test_a_revoked_employee_is_refused_even_though_the_binding_remains(monkeypatch):
    """`revoke_employee_portal` clears portal_enabled and may leave
    auth_user_id, so a check on the binding alone keeps a revoked employee
    signed in. The two facts are asked separately."""
    from fastapi import HTTPException
    import core.portal_auth as auth_mod

    db = FakeDB()
    db.seed("payroll_employees", {
        "id": EMP, "firm_id": FIRM, "client_id": CLIENT, "name": "Someone",
        "auth_user_id": "uid-1", "portal_enabled": False})
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setattr("core.supabase_client.get_service_supabase", lambda: db)
    with pytest.raises(HTTPException) as e:
        auth_mod.get_current_portal_employee(
            jwt_user={"auth_user_id": "uid-1", "email": "e@f1.test"})
    assert e.value.status_code == 403


def test_an_enabled_employee_resolves_to_their_own_ids(monkeypatch):
    import core.portal_auth as auth_mod

    db = FakeDB()
    db.seed("payroll_employees", {
        "id": EMP, "firm_id": FIRM, "client_id": CLIENT, "name": "Someone",
        "employee_code": "EMP-001",
        "auth_user_id": "uid-1", "portal_enabled": True})
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setattr("core.supabase_client.get_service_supabase", lambda: db)
    ctx = auth_mod.get_current_portal_employee(
        jwt_user={"auth_user_id": "uid-1", "email": "e@f1.test"})
    assert ctx["employee_id"] == EMP
    assert ctx["client_id"] == CLIENT
    assert ctx["firm_id"] == FIRM
    # NOT an RBAC role: PERMISSIONS has no entry for it, so rbac() denies this
    # principal everywhere — which is why no endpoint may carry both.
    assert ctx["role"] == "PortalEmployee"
    from core.permissions import PERMISSIONS
    assert not any("PortalEmployee" in roles
                   for res in PERMISSIONS.values() for roles in res.values())


def test_the_principal_is_the_identity_it_is_BOUND_to_and_not_the_first_row(monkeypatch):
    """The single most consequential line in the module, asserted with two rows.

    A one-employee fixture cannot tell "matched on auth_user_id" from "took
    whatever came back", because both answers are the same row. Migration 262's
    unique index makes one identity at most one employee; this is the Python
    half of the same statement, and without it a valid login would resolve to
    somebody else's salary.
    """
    import core.portal_auth as auth_mod

    db = FakeDB()
    db.seed("payroll_employees", {
        "id": "E-other", "firm_id": FIRM, "client_id": CLIENT,
        "name": "Somebody Else", "employee_code": "EMP-999",
        "auth_user_id": "uid-somebody-else", "portal_enabled": True})
    db.seed("payroll_employees", {
        "id": EMP, "firm_id": FIRM, "client_id": CLIENT, "name": "The Caller",
        "employee_code": "EMP-001",
        "auth_user_id": "uid-1", "portal_enabled": True})
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setattr("core.supabase_client.get_service_supabase", lambda: db)

    ctx = auth_mod.get_current_portal_employee(
        jwt_user={"auth_user_id": "uid-1", "email": "e@f1.test"})
    assert ctx["employee_id"] == EMP
    assert ctx["name"] == "The Caller"


def test_an_identity_bound_to_nobody_is_refused(monkeypatch):
    from fastapi import HTTPException
    import core.portal_auth as auth_mod

    db = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setattr("core.supabase_client.get_service_supabase", lambda: db)
    with pytest.raises(HTTPException) as e:
        auth_mod.get_current_portal_employee(
            jwt_user={"auth_user_id": "uid-nobody", "email": "x@f1.test"})
    assert e.value.status_code == 403
    # The SAME message as a revoked employee and as no JWT at all: a distinct
    # one would tell an outsider whether an identity is an employee of this
    # firm, the oracle employee_portal_service raises one generic 404 to avoid.
    assert e.value.detail == "Not an employee portal user."


def test_mock_mode_refuses_rather_than_inventing_an_employee(monkeypatch):
    """With no database there is nothing to resolve against, and a stub
    principal here would make every guard above vacuous."""
    from fastapi import HTTPException
    import core.portal_auth as auth_mod

    monkeypatch.delenv("SUPABASE_URL", raising=False)
    with pytest.raises(HTTPException) as e:
        auth_mod.get_current_portal_employee(
            jwt_user={"auth_user_id": "uid-1", "email": "e@f1.test"})
    assert e.value.status_code == 403
