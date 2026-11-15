"""The authenticator banner names only what the guard locks for THIS person (PRE-A-021).

WHAT WAS WRONG
    The staff banner and the security settings page said one fixed sentence to every Partner and Manager the
    policy covers: "Team, Payroll, Billing and firm settings stay locked until you set up an authenticator app".
    Billing is Partner-only by role, so a Manager read that it would open for them once they set up an
    authenticator, which is false (the owner, signed in as a Manager, 15-11-2026); and the sentence left out client
    assignments, the data export and the member's own profile, which the same guard locks.

WHAT THIS HOLDS
    * `domain/firm/mfa_locked_areas.MFA_LOCKED_AREAS` names every router `main.py` mounts behind `_MFA_GUARD`, and
      names nothing that is not behind it: the list is read off `main.py` itself, so an eighth guarded router
      cannot go unnamed and a router taken off the guard cannot stay in the sentence.
    * Each named area's permission is one its router actually asks, read off the router's own `rbac(...)` calls.
    * `locked_areas_for` keeps what the person's own permissions reach, overrides included, and
      `GET /api/security/mfa-policy` serves the list and the sentence: a Manager's has no Billing.
"""
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user
from domain.firm.mfa_locked_areas import MFA_LOCKED_AREAS, locked_areas_for, locked_sentence
from routers.security_policy import router as security_router

API = Path(__file__).resolve().parents[1]
MAIN = (API / "main.py").read_text(encoding="utf-8")


def _guarded_modules() -> set[str]:
    """The router modules main.py mounts with `_MFA_GUARD` among their dependencies."""
    aliases = dict(re.findall(r"from routers\.(\w+) import router as (\w+)", MAIN))
    by_alias = {alias: module for module, alias in aliases.items()}
    out = set()
    for target in re.findall(r"app\.include_router\(([\w.]+),\s*dependencies=[^)]*_MFA_GUARD", MAIN):
        if target.endswith(".router"):
            out.add(target[: -len(".router")])
        else:
            out.add(by_alias[target])
    return out


def test_every_router_behind_the_guard_is_named_and_nothing_else_is():
    guarded = _guarded_modules()
    assert len(guarded) >= 7, guarded  # the reader is not vacuous
    named = {module for _label, module, _r, _a in MFA_LOCKED_AREAS}
    assert named == guarded, f"named but not guarded: {named - guarded}; guarded but not named: {guarded - named}"


@pytest.mark.parametrize("label,module,resource,action", MFA_LOCKED_AREAS)
def test_each_area_names_a_permission_its_router_asks(label, module, resource, action):
    source = (API / "routers" / f"{module}.py").read_text(encoding="utf-8")
    asked = set(re.findall(r'rbac\("(\w+)",\s*"(\w+)"\)', source))
    assert (resource, action) in asked, f"{label}: routers/{module}.py never asks {resource}:{action}"


def test_a_manager_is_not_told_that_billing_or_the_practice_books_open_for_them():
    areas = locked_areas_for("Manager")
    assert areas == ["Team", "client assignments", "Payroll", "firm settings", "your own profile"]
    sentence = locked_sentence(areas)
    assert sentence == ("Team, client assignments, Payroll, firm settings and your own profile stay locked until "
                        "you set up an authenticator app.")
    assert "Billing" not in sentence and "practice" not in sentence


def test_a_partner_is_told_every_area():
    assert locked_areas_for("Partner") == [label for label, *_ in MFA_LOCKED_AREAS]


def test_the_person_decides_not_the_role_alone():
    # a Manager granted Billing reads it; a Manager whose Payroll was taken away does not
    granted = locked_areas_for("Manager", {"billing:read": True})
    assert "Billing" in granted
    revoked = locked_areas_for("Manager", {("payroll", "read"): False})
    assert "Payroll" not in revoked


def test_an_unknown_role_and_an_empty_list_say_nothing():
    assert locked_areas_for(None) == []
    assert locked_areas_for("Astrologer") == []
    assert locked_sentence([]) is None
    assert locked_sentence(["your own profile"]) == "Your own profile stays locked until you set up an authenticator app."


@pytest.mark.parametrize("role,billing", [("Manager", False), ("Partner", True)])
def test_the_policy_route_serves_the_callers_own_sentence(role, billing):
    app = FastAPI()
    app.include_router(security_router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "u", "firm_id": "F1", "role": role}
    body = TestClient(app).get("/api/security/mfa-policy").json()["data"]
    assert ("Billing" in body["locked_areas"]) is billing
    assert ("Billing" in body["locked_sentence"]) is billing
    assert body["locked_sentence"].endswith("stay locked until you set up an authenticator app.")
