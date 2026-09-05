"""
MFA covers payroll, and the role list covers the people who run it.

WHAT WAS WRONG

Two halves of one control, each individually reasonable and jointly a no-op.

  * The guard was attached to four routers — assignments, identity, practice,
    billing — every one of them firm ADMINISTRATION. None of them holds the
    personal data. Payroll, which the DPDP note calls the highest-exposure
    surface in the product by a distance (employee PAN, Aadhaar-linked UAN,
    ESIC number, date of birth, bank account, salary, Form 12BB family data),
    was not behind it.

  * MFA_REQUIRED_ROLES defaulted to "Partner" alone. The guard FILTERS BY ROLE,
    so adding payroll while that stood would have left every Manager — and
    payroll RBAC is Manager+ — completely unchallenged. Enforced-looking, not
    enforced.

Fixing either alone achieves nothing, which is why both are pinned here and why
the tests are written to fail if the pair drifts apart.

MEASURED ON PRODUCTION, 2026-09-05: the four guarded routers had seen NO
activity since MFA was enrolled on 2026-08-15 — no assignment, identity,
practice or billing event in audit_log — so whatever REQUIRE_MFA is set to, the
guard had never once met a real request. Payroll is used daily. This is the
first time the control touches traffic.

NEGATIVE CONTROLS — each applied, then reverted:

  | control                                        | tests that fail |
  |------------------------------------------------|-----------------|
  | put the role default back to "Partner"         | 3               |
  | drop payroll back to the client guard alone    | 1               |
  | add Executive/Reviewer to the role default     | 1               |
"""
from __future__ import annotations

import os
from unittest import mock

import pytest

from core.permissions import PERMISSIONS
from core.security_config import mfa_required_roles


def _guarded_routers() -> set[str]:
    """Which routers main.py attaches the MFA guard to, read from the app."""
    import main
    from core.auth import mfa_guard

    guarded = set()
    for route in main.app.routes:
        deps = getattr(getattr(route, "dependant", None), "dependencies", [])
        calls = {getattr(d, "call", None) for d in deps}
        if mfa_guard in calls:
            guarded.add(str(getattr(route, "path", "")))
    return guarded


def test_payroll_is_behind_the_mfa_guard():
    """The highest-exposure personal data in the product."""
    paths = _guarded_routers()
    assert any(p.startswith("/api/payroll") for p in paths), (
        "no payroll route carries mfa_guard — the guard covers firm "
        "administration only, which is where it started")


def test_the_firm_administration_routers_keep_the_guard():
    """Adding payroll must not have displaced what was already covered."""
    paths = _guarded_routers()
    for prefix in ("/api/assignments", "/api/identity"):
        assert any(p.startswith(prefix) for p in paths), f"{prefix} lost the guard"


def test_manager_is_in_the_required_roles_because_payroll_is_manager_plus():
    """The pair that has to move together. Payroll RBAC is Manager+, so a role
    list of Partner alone leaves the people who run payroll unchallenged."""
    roles = mfa_required_roles()
    assert "Manager" in roles, (
        "payroll is behind the guard but Manager is not in MFA_REQUIRED_ROLES — "
        "the guard filters by role, so this combination protects nobody")
    assert "Partner" in roles


def test_every_role_that_can_read_payroll_is_covered():
    """Derived from the permission matrix rather than restated, so a later
    widening of payroll RBAC fails here instead of silently escaping MFA."""
    payroll_readers = set(PERMISSIONS["payroll"]["read"])
    uncovered = payroll_readers - mfa_required_roles()
    assert not uncovered, (
        f"these roles can read payroll but never face an MFA challenge: "
        f"{sorted(uncovered)}")


def test_roles_that_cannot_reach_a_guarded_surface_are_left_out():
    """Not a tautology — a deliberate limit. Adding Executive or Reviewer would
    put a login step in front of people who cannot reach payroll or any of the
    four administration routers, protecting nothing. If a surface they CAN reach
    goes behind the guard, this test is the one that should be changed."""
    assert mfa_required_roles() == {"Partner", "Manager"}


def test_the_role_list_is_overridable_without_a_deploy():
    with mock.patch.dict(os.environ, {"MFA_REQUIRED_ROLES": "Partner"}):
        assert mfa_required_roles() == {"Partner"}
