"""A payroll act that releases, pays, reverses or settles also asks for `payroll:read` (POST-A-219, part 2).

THE GAP
    `finalize`, `disburse`, `reverse`, the loan write-down and a leaver's settlement ask `payroll:finalize`, a Partner's act. A Partner
    whom the Team screen had blocked from READING payroll, and not from finalising it, passed that guard and then failed later, on a
    message about something else (the run could not be read, or the identity of what it needed could not be established). A person who
    is not allowed to see payroll should be told that at the door, in the words every other refusal uses.

WHAT IS HELD
    * every route that asks `payroll:finalize` also asks `payroll:read`, and asks it FIRST (a route-level dependency, so the refusal
      names the block and not whatever the handler would have tripped on), with a floor on how many such routes there are;
    * driven for real: with read refused and finalize allowed, each of the five answers 403 naming `read` on `payroll`; with both
      allowed, the same request is not refused (the negative control).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.permissions as permissions
from core.auth import get_current_user
from routers.payroll import router as payroll_router

PARTNER = {"id": "p", "auth_user_id": "a", "firm_id": "F1", "role": "Partner", "email": "p@f.in"}

FINALISE_TIER = [
    ("POST", "/api/payroll/runs/r1/finalize", {}),
    ("POST", "/api/payroll/runs/r1/loan-writedown", {}),
    ("POST", "/api/payroll/runs/r1/disburse", {"disbursement_date": "2026-05-31", "bank_account_id": "b1"}),
    ("POST", "/api/payroll/runs/r1/reverse", {}),
    ("POST", "/api/payroll/employees/e1/settlement/record", {}),
]


def _names(route) -> list[str]:
    return [d.call.__name__ for d in route.dependant.dependencies]


def test_every_route_that_asks_to_finalise_also_asks_to_read_and_asks_first():
    seen = 0
    for route in payroll_router.routes:
        names = _names(route)
        if "rbac_payroll_finalize" not in names:
            continue
        seen += 1
        assert "rbac_payroll_read" in names, f"{route.path} asks payroll:finalize and never payroll:read"
        assert names.index("rbac_payroll_read") < names.index("rbac_payroll_finalize"), (
            f"{route.path} asks payroll:finalize before payroll:read, so a blocked Partner meets the wrong refusal")
    assert seen >= 5, f"expected the five finalise-tier payroll routes, found {seen}: the scan has gone vacuous"


def _client(monkeypatch, allowed):
    monkeypatch.setattr(permissions, "can_user", lambda user, resource, action: (resource, action) in allowed)
    app = FastAPI()
    app.include_router(payroll_router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("method, path, body", FINALISE_TIER, ids=[p.rsplit("/", 1)[-1] for _, p, _ in FINALISE_TIER])
def test_a_partner_blocked_from_reading_payroll_is_told_so_at_the_door(monkeypatch, method, path, body):
    client = _client(monkeypatch, allowed={("payroll", "finalize")})
    r = client.request(method, path, json=body)
    assert r.status_code == 403, r.text
    assert "'read' on 'payroll'" in r.json()["detail"], r.json()


@pytest.mark.parametrize("method, path, body", FINALISE_TIER, ids=[p.rsplit("/", 1)[-1] for _, p, _ in FINALISE_TIER])
def test_negative_control_with_both_allowed_the_request_is_not_refused_at_the_door(monkeypatch, method, path, body):
    client = _client(monkeypatch, allowed={("payroll", "finalize"), ("payroll", "read")})
    r = client.request(method, path, json=body)
    detail = r.json().get("detail", "") if r.headers.get("content-type", "").startswith("application/json") else ""
    assert "'read' on 'payroll'" not in str(detail) and "'finalize' on 'payroll'" not in str(detail), r.text
