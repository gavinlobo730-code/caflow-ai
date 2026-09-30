"""An employee can download their own payslip, and only theirs (payroll-01).

WHAT WAS WRONG
    The employee portal's Download payslip button called
    `GET /api/payroll/salary-slips/{id}/pdf`, which is `rbac("payroll", "read")`
    and needs a staff `users` row. An employee has none, so `core.auth` answered
    403 "User not found in firm" — every employee, every slip — while
    `routers/portal_employee.py` exposed only the §192 projection. The most
    basic thing an employee does with the portal was built, linked and
    unreachable, and the reachability guards passed because they matched URL
    strings (see `test_a_screen_calls_only_routes_its_principal_can_pass.py`).

WHAT IS ASSERTED, through the real route with the employee principal and no
`users` row anywhere
    * the caller's own slip in a released run is a 200 `application/pdf`, from
      the one payslip renderer, and is not cacheable;
    * a COLLEAGUE's slip — same firm, same client — is refused, and the renderer
      is never asked for it;
    * a slip in a draft or review run is refused; both released statuses pass;
    * a slip under another firm or another client is refused;
    * a made-up id, a colleague's id and a draft's id are the SAME answer — no
      oracle for whether somebody else's payslip id is real;
    * the old staff route still refuses an identity with no `users` row, and is
      still a staff-only route;
    * the route carries no person-naming parameter, and the lookup is scoped in
      the QUERY rather than checked after the fact.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.auth as auth
import routers.payroll as payroll_mod
import routers.portal_employee as portal_mod
import services.payslip_pdf_service as pdf_service
from core.auth import get_current_user
from core.portal_auth import get_current_portal_employee
from domain.payroll.run_status import PAYROLL_RELEASED
from services import employee_payslip_service as svc
from tests.e2e_harness import FakeDB

FIRM, CLIENT = "F1", "C1"
ME, COLLEAGUE = "E-me", "E-colleague"
PDF = b"%PDF-1.4 payslip for the caller"
ME_CTX = {
    "portal": True, "employee": True, "employee_id": ME, "client_id": CLIENT,
    "firm_id": FIRM, "name": "Me", "employee_code": "EMP-001",
    "email": "me@f1.test", "role": "PortalEmployee",
}


class _Renderer:
    """The one payslip renderer, recorded. The route must call it for the
    caller's own released slip and for nothing else."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def __call__(self, slip_id, firm_id):
        self.calls.append((slip_id, firm_id))
        return PDF, "payslip-2026-06.pdf"


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    renderer = _Renderer()
    monkeypatch.setattr(payroll_mod, "_db", lambda: db)
    monkeypatch.setattr(pdf_service, "get_payslip_pdf", renderer)
    app = FastAPI()
    app.include_router(portal_mod.router)
    app.include_router(payroll_mod.router)
    # The EMPLOYEE principal only. There is deliberately no override for
    # get_current_user: an employee has no users row, and this app has no staff
    # identity to fall back on.
    app.dependency_overrides[get_current_portal_employee] = lambda: dict(ME_CTX)
    return TestClient(app, raise_server_exceptions=False), db, renderer


def _run(db, run_id="R1", status="finalized", firm=FIRM, client=CLIENT):
    return db.seed("payroll_runs", {"id": run_id, "firm_id": firm,
                                    "client_id": client, "status": status,
                                    "month": "2026-06"})


def _slip(db, slip_id, employee=ME, run_id="R1"):
    return db.seed("payroll_slips", {"id": slip_id, "run_id": run_id,
                                     "employee_id": employee})


def _get(client, slip_id):
    return client.get(f"/api/portal/employee/payslips/{slip_id}/pdf")


def _premise(client, db, renderer):
    """The caller's OWN released slip works in this world — so a refusal below
    is a refusal of something, not the absence of a route. Without it every
    refusal test passes against a build with no such route at all (the 404 is
    the router's), which a negative control caught."""
    _run(db, run_id="R-own", status="finalized")
    _slip(db, "S-own", run_id="R-own")
    assert _get(client, "S-own").status_code == 200
    renderer.calls.clear()


# ── the caller's own slip ────────────────────────────────────────────────────

def test_an_employee_downloads_their_own_released_payslip(world):
    client, db, renderer = world
    _run(db); _slip(db, "S-mine")
    res = _get(client, "S-mine")
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.content == PDF
    assert 'attachment; filename="payslip-2026-06.pdf"' in res.headers["content-disposition"]
    assert "no-store" in res.headers["cache-control"]
    assert renderer.calls == [("S-mine", FIRM)]


@pytest.mark.parametrize("status", list(PAYROLL_RELEASED))
def test_every_released_status_passes(world, status):
    client, db, renderer = world
    _run(db, status=status); _slip(db, "S-mine")
    assert _get(client, "S-mine").status_code == 200


# ── nobody else's ────────────────────────────────────────────────────────────

def test_a_colleagues_payslip_is_refused_and_never_rendered(world):
    client, db, renderer = world
    _premise(client, db, renderer)
    _run(db); _slip(db, "S-colleague", employee=COLLEAGUE)
    res = _get(client, "S-colleague")
    assert res.status_code == 404
    assert renderer.calls == [], "the renderer was asked for a colleague's slip"
    assert PDF not in res.content


@pytest.mark.parametrize("status", ["draft", "review", "", "reversed", "anything"])
def test_a_slip_in_a_run_that_has_not_been_released_is_refused(world, status):
    """A draft has paid nobody, and migration 323 already keeps it out of the
    employee's own PostgREST read — this door must not be the way round."""
    client, db, renderer = world
    _premise(client, db, renderer)
    _run(db, status=status); _slip(db, "S-mine")
    assert _get(client, "S-mine").status_code == 404
    assert renderer.calls == []


def test_a_run_under_another_firm_is_refused(world):
    client, db, renderer = world
    _premise(client, db, renderer)
    _run(db, firm="F2"); _slip(db, "S-mine")
    assert _get(client, "S-mine").status_code == 404
    assert renderer.calls == []


def test_a_run_under_another_client_is_refused(world):
    client, db, renderer = world
    _premise(client, db, renderer)
    _run(db, client="C2"); _slip(db, "S-mine")
    assert _get(client, "S-mine").status_code == 404
    assert renderer.calls == []


def test_a_slip_whose_run_is_missing_is_refused(world):
    client, db, renderer = world
    _premise(client, db, renderer)
    _slip(db, "S-orphan", run_id="R-gone")
    assert _get(client, "S-orphan").status_code == 404
    assert renderer.calls == []


def test_every_refusal_is_the_same_answer(world):
    """A distinct message for "exists but is not yours" would tell an employee
    whether somebody else's payslip id is real."""
    client, db, renderer = world
    _premise(client, db, renderer)
    _run(db); _run(db, run_id="R-draft", status="draft")
    _slip(db, "S-colleague", employee=COLLEAGUE)
    _slip(db, "S-draft", run_id="R-draft")
    answers = {(r.status_code, r.text) for r in (
        _get(client, "S-colleague"), _get(client, "S-draft"),
        _get(client, "S-never-existed"))}
    assert len(answers) == 1, answers
    assert next(iter(answers))[0] == 404


# ── the principal must still be resolved ─────────────────────────────────────

def test_the_route_resolves_the_employee_principal(world):
    """Remove the override: with the real dependency and no Supabase URL it must
    refuse, not hand a PDF to an anonymous caller."""
    client, db, renderer = world
    _run(db); _slip(db, "S-mine")
    client.app.dependency_overrides.pop(get_current_portal_employee)
    res = _get(client, "S-mine")
    assert res.status_code in (401, 403, 503), res.status_code
    assert renderer.calls == []


# ── the staff door is unchanged ──────────────────────────────────────────────

def test_the_staff_route_still_refuses_an_identity_with_no_users_row(monkeypatch):
    """The employee's own JWT, through the REAL get_current_user, against the
    staff route this button used to call. It is the 403 that made the feature
    unreachable, and it must stay a 403: the fix is a door for the employee,
    not a loosened guard on the staff one."""
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")

    class _Key:
        key = "k"

    class _JWKS:
        def get_signing_key_from_jwt(self, _t):
            return _Key()

    class _Result:
        data = None

    class _Query:
        def select(self, *_a, **_k): return self
        def eq(self, *_a, **_k): return self
        def single(self): return self
        def maybe_single(self): return self
        def limit(self, *_a): return self
        def execute(self): return _Result()

    class _Sb:
        def table(self, _n): return _Query()

    monkeypatch.setattr(auth, "_get_jwks_client", lambda: _JWKS())
    monkeypatch.setattr(auth.jwt, "decode",
                        lambda *a, **k: {"sub": "employee-auth-id", "email": "me@f1.test"})
    monkeypatch.setattr(auth, "get_service_supabase", lambda: _Sb())
    monkeypatch.setattr(auth, "_user_lookup_cache", {})

    app = FastAPI()
    app.include_router(payroll_mod.router)
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/api/payroll/salary-slips/S-mine/pdf",
                     headers={"Authorization": "Bearer employee-jwt"})
    assert res.status_code == 403
    assert "not found in firm" in res.text.lower()


def test_the_staff_route_is_still_staff_only():
    from tests.test_a_screen_calls_only_routes_its_principal_can_pass import (
        STAFF, principal_required, routes_for)
    routes = routes_for("/api/payroll/salary-slips/{}/pdf")
    assert routes and {principal_required(r) for r in routes} == {STAFF}


# ── structure: nothing names a person, and scope is in the query ─────────────

def test_the_route_takes_no_person_naming_parameter():
    params = set(inspect.signature(portal_mod.employee_payslip_pdf).parameters)
    assert params == {"slip_id", "employee"}, params


def test_ownership_is_asked_in_the_query_not_checked_afterwards():
    """If the slip were fetched by id alone and compared in Python, a colleague's
    row would be READ and then discarded — and the next edit that forgot the
    comparison would hand it over. Asked in the query, it is never read."""
    src = inspect.getsource(svc.own_released_slip)
    assert '.eq("id", slip_id).eq("employee_id", employee_id)' in src
    assert '.eq("firm_id", firm_id)' in src and '.eq("client_id", client_id)' in src
    assert "PAYROLL_RELEASED" in src


@pytest.mark.parametrize("missing", ["employee_id", "firm_id", "client_id"])
def test_a_principal_missing_an_id_matches_nothing_rather_than_everything(missing):
    db = FakeDB()
    _run(db); _slip(db, "S-mine")
    who = dict(ME_CTX); who[missing] = None
    with pytest.raises(svc.PayslipNotFound):
        svc.own_released_slip(db, who, "S-mine")


def test_the_renderer_is_the_one_the_staff_route_calls():
    """Two payslip renderers would be two payslips that agree until one changes."""
    assert "get_payslip_pdf" in inspect.getsource(portal_mod.employee_payslip_pdf)
    assert "get_payslip_pdf" in inspect.getsource(payroll_mod.download_salary_slip_pdf)
