"""
/api/identity/permissions — the frontend's single source of truth for gating.

WHY THIS ENDPOINT EXISTS
    The UI decided what to render by hardcoding role lists next to each button
    (`hasRole(userRole, ["Partner", "Manager"])`). That is a second copy of the
    permission matrix, in another language, maintained by hand — and it had
    already drifted: `accounting:read` admits Executive but `accounting:write`
    does not, so an Executive was shown write actions the backend answers with
    403. Serving the matrix keeps exactly one copy of it, in core/permissions.py.

WHAT IT IS NOT
    Not a security boundary. rbac() on each endpoint remains the only thing that
    authorises anything; this endpoint only decides what is worth rendering. The
    tests below are therefore about FIDELITY (does it report the matrix
    accurately?), not about protection.
"""
import pytest

from core.permissions import (
    PERMISSIONS,
    Role,
    can,
    canonical_role,
    get_accessible_resources,
)
from routers.identity import my_permissions


def _call(role):
    return my_permissions(current_user={"id": "u1", "firm_id": "f1", "role": role})


@pytest.mark.parametrize("role", [r.value for r in Role])
def test_reported_permissions_match_the_matrix_exactly(role):
    """The whole point: no transformation, no filtering, no curated subset.
    If this endpoint ever starts editing what it reports, the UI is back to
    holding an opinion of its own."""
    body = _call(role)

    assert body["success"] is True
    assert body["data"]["permissions"] == get_accessible_resources(role)


@pytest.mark.parametrize("role", [r.value for r in Role])
def test_every_reported_pair_is_one_can_would_allow(role):
    """Cross-checked against can() rather than against the same function the
    endpoint calls — get_accessible_resources returning garbage would otherwise
    make the test above pass by agreeing with itself."""
    perms = _call(role)["data"]["permissions"]

    for resource, actions in perms.items():
        for action in actions:
            assert can(role, resource, action) is True, f"{role} {resource}:{action}"


@pytest.mark.parametrize("role", [r.value for r in Role])
def test_nothing_the_role_may_do_is_omitted(role):
    """The other direction. An endpoint that under-reports hides buttons from
    people entitled to them, which is how a permission feature gets ripped out."""
    perms = _call(role)["data"]["permissions"]

    for resource, actions in PERMISSIONS.items():
        for action in actions:
            if can(role, resource, action):
                assert action in perms.get(resource, []), f"{role} lost {resource}:{action}"


def test_the_known_drift_is_now_reportable():
    """The concrete mismatch that motivated this: Executive may read accounting
    but not write it. Named explicitly so a matrix change that erases the
    distinction has to come past this test."""
    executive = _call("Executive")["data"]["permissions"]
    manager = _call("Manager")["data"]["permissions"]

    assert "read" in executive["accounting"]
    assert "write" not in executive["accounting"]
    assert "approve" not in executive["accounting"]
    assert "write" in manager["accounting"]
    assert "approve" not in manager["accounting"]  # Partner-only


def test_legacy_role_strings_are_canonicalised():
    """Rows written under migrations 001/021/022 still carry owner/admin/staff.
    The frontend must receive the canonical name, or it will compare a role
    string it has never heard of and fail closed on a legitimate Partner."""
    body = _call("owner")

    assert body["data"]["role"] == "Partner"
    assert body["data"]["permissions"] == get_accessible_resources("Partner")


def test_an_unrecognised_role_yields_nothing_rather_than_an_error():
    """A junk role must not 500 the whole app shell — the frontend calls this on
    every sign-in. Empty map + null role is what the UI helpers fail closed on."""
    body = _call("Sorcerer")

    assert body["success"] is True
    assert body["data"]["role"] is None
    assert body["data"]["permissions"] == {}


def test_a_missing_role_key_is_treated_as_unrecognised():
    """current_user comes from a JWT/users row; role can be absent."""
    body = my_permissions(current_user={"id": "u1", "firm_id": "f1"})

    assert body["data"]["role"] is None
    assert body["data"]["permissions"] == {}


def test_canonical_role_does_not_raise_on_junk():
    """canonical_role is the public, non-raising wrapper the endpoint relies on —
    _to_role raises, and a raise here is a 500 on the app shell's first request."""
    assert canonical_role("owner") == "Partner"
    assert canonical_role("PARTNER") == "Partner"
    assert canonical_role("Sorcerer") is None
    assert canonical_role(None) is None
    assert canonical_role("") is None


def test_the_endpoint_is_not_itself_permission_gated():
    """Gating "which actions am I allowed?" behind an action is circular: every
    role would need it, so the guard would assert nothing. Pinned because the
    obvious "tidy-up" is to wrap it in rbac() like its neighbours, which would
    lock out whichever role got left out of the set."""
    import inspect

    params = inspect.signature(my_permissions).parameters
    dep = params["current_user"].default

    assert getattr(dep.dependency, "__name__", "") == "get_current_user"


def test_every_role_including_the_lowest_gets_an_answer():
    """Reviewer and Client are the roles a curated allowlist forgets."""
    for role in (r.value for r in Role):
        body = _call(role)
        assert body["data"]["role"] == role
        # Client is external and holds far less, but must still receive a map.
        assert isinstance(body["data"]["permissions"], dict)
