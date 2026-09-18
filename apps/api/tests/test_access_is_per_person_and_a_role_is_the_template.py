"""
Access is decided PER PERSON; a role is the template it falls back to.

WHAT WAS WRONG
    `rbac(resource, action)` decided every one of its 1037 call sites from the
    caller's ROLE alone, and a role is five buckets. A practice is not staffed in
    five buckets: one Executive runs GST and TDS and never touches payroll,
    another runs payroll and nothing else. The firm's only options were to
    promote somebody to reach one screen — handing them every other screen that
    tier opens — or to do the work outside the product.

    The Team screen already showed a per-member grid headed "Changes are saved
    instantly. Overrides the role default for that individual", and every clause
    was false: the toggles went into localStorage and nothing in
    `core/permissions.py` could have honoured them.

WHAT THIS FILE HOLDS
    The RULE, not a spelling of it. In particular the first test does not assert
    that `rbac` contains the token `can_user` — it asserts that an override
    CHANGES WHAT A GUARDED ENDPOINT DOES, which is the only thing that matters
    and the only form that survives the function being renamed.
"""
import pytest

from core import permissions as perms
from core.permissions import (
    PERMISSIONS,
    PRIVILEGE_CHANGING,
    UNREVOKABLE_FOR_PARTNER,
    Role,
    can,
    can_user,
    get_accessible_resources,
    is_known_permission,
    resolve_permission,
)

ALL_ROLES = [r.value for r in Role]
ALL_PAIRS = [(res, act) for res, actions in PERMISSIONS.items() for act in actions]


def _user(role, overrides=None):
    return {"role": role, "id": "u1", "firm_id": "f1", "permission_overrides": overrides or {}}


# ── The seam ─────────────────────────────────────────────────────────────────

def test_a_guarded_endpoint_honours_a_per_person_override():
    """The property the whole feature rests on, asserted THROUGH rbac().

    Deliberately not `assert "can_user" in inspect.getsource(rbac)`: that is a
    spelling, and this codebase has had five guards break on a move that did not
    break their rule. This one breaks only if the behaviour breaks.
    """
    from fastapi import HTTPException

    dependency = perms.rbac("payroll", "write")
    inner = dependency.__wrapped__ if hasattr(dependency, "__wrapped__") else dependency

    # An Executive cannot write payroll by role (PERMISSIONS says Manager+)...
    assert can("Executive", "payroll", "write") is False
    with pytest.raises(HTTPException) as refused:
        inner(_user("Executive"))
    assert refused.value.status_code == 403

    # ...and a grant lets them, with no change to the 1037 call sites.
    granted = inner(_user("Executive", {"payroll:write": True}))
    assert granted["role"] == "Executive"

    # A Manager can by role, and a deny takes it away.
    assert can("Manager", "payroll", "write") is True
    with pytest.raises(HTTPException):
        inner(_user("Manager", {"payroll:write": False}))


def test_the_refusal_does_not_blame_the_role_alone():
    """A per-person refusal that says "Role 'Manager' cannot…" sends the reader
    to change the role, which is not what refused them."""
    from fastapi import HTTPException

    dependency = perms.rbac("payroll", "write")
    inner = dependency.__wrapped__ if hasattr(dependency, "__wrapped__") else dependency
    with pytest.raises(HTTPException) as refused:
        inner(_user("Manager", {"payroll:write": False}))
    assert not refused.value.detail.startswith("Role ")


# ── Three states, and the third is the absence of a row ──────────────────────

@pytest.mark.parametrize("role", ALL_ROLES)
def test_no_override_is_exactly_the_role(role):
    """Nobody's access changes on the day migration 403 lands.

    The table is empty and there is no backfill, so this is the whole product's
    behaviour before and after — asserted over EVERY pair, not a sample.
    """
    for resource, action in ALL_PAIRS:
        assert can_user(_user(role), resource, action) == can(role, resource, action), (
            f"{role} {resource}:{action} moved with no override recorded"
        )


@pytest.mark.parametrize("role", ALL_ROLES)
def test_an_absent_overrides_key_reads_the_same_as_an_empty_one(role):
    """A principal built without the key (the dev/mock path, a test double, a
    portal principal) must resolve to the role rather than to nothing."""
    bare = {"role": role}
    for resource, action in ALL_PAIRS:
        assert can_user(bare, resource, action) == can(role, resource, action)


def test_a_grant_reaches_the_most_junior_role():
    assert can("Reviewer", "accounting", "write") is False
    assert can_user(_user("Reviewer", {"accounting:write": True}), "accounting", "write") is True


def test_a_deny_reaches_the_most_senior_role():
    assert can("Partner", "payroll", "finalize") is True
    assert can_user(_user("Partner", {"payroll:finalize": False}), "payroll", "finalize") is False


def test_null_is_not_false_it_is_the_absence_of_a_row():
    """The service deletes on None; nothing stores a null `granted` (NOT NULL).
    If one ever reaches the resolver it must read as NO OPINION, not as a deny:
    inventing a refusal out of a malformed value is how a permission disappears
    with nobody having removed it."""
    assert can_user(_user("Manager", {"payroll:write": None}), "payroll", "write") is True
    assert can_user(_user("Manager", {"payroll:write": "false"}), "payroll", "write") is True
    assert can_user(_user("Manager", {"payroll:write": 0}), "payroll", "write") is True


def test_both_key_shapes_resolve_identically():
    """The tuple key is what a Python caller reaches for; the string key is what
    survives JSON. A resolver that knew only one would silently read nothing
    from the other — and the wire shape is the one that carries real data."""
    for over in ({("payroll", "write"): True}, {"payroll:write": True}):
        assert resolve_permission("Executive", over, "payroll", "write") is True


# ── The Partner floor ────────────────────────────────────────────────────────

@pytest.mark.parametrize("resource,action", sorted(UNREVOKABLE_FOR_PARTNER))
def test_a_partner_keeps_the_pairs_that_reach_this_screen(resource, action):
    """Without this the grid is unrepairable: the only person who could restore
    access is the person whose access was removed, and `team:write` is the only
    thing that can write the table."""
    assert can_user(_user("Partner", {f"{resource}:{action}": False}), resource, action) is True


@pytest.mark.parametrize("resource,action", sorted(UNREVOKABLE_FOR_PARTNER))
def test_the_floor_is_the_partners_alone(resource, action):
    """A Manager granted team:write can still have it taken away. The floor
    exists to keep the door open, not to make anybody permanent."""
    granted = _user("Manager", {f"{resource}:{action}": True})
    assert can_user(granted, resource, action) is True
    denied = _user("Manager", {f"{resource}:{action}": False})
    assert can_user(denied, resource, action) is False


def test_the_floor_names_only_pairs_that_exist():
    for resource, action in UNREVOKABLE_FOR_PARTNER | PRIVILEGE_CHANGING:
        assert is_known_permission(resource, action), (
            f"{resource}:{action} is named in a constant and is not a real permission"
        )


def test_the_floor_is_reachable_by_the_role_it_protects():
    """A pair a Partner does not have by role could not be restored by the floor
    either, so listing it would be decorative."""
    for resource, action in UNREVOKABLE_FOR_PARTNER:
        assert can("Partner", resource, action) is True


def test_team_write_is_named_as_privilege_changing():
    """It IS "may become a Partner": its holder can grant themselves firm:admin
    and everything else. Allowed — a Partner appointing somebody to run access
    is a real decision — but it must not look like the other thirty ticks."""
    assert ("team", "write") in PRIVILEGE_CHANGING


# ── Unknown pairs are inert ──────────────────────────────────────────────────

def test_an_unknown_pair_falls_through_to_the_role_and_fails_closed():
    """The column is free TEXT with no CHECK — the vocabulary is a Python dict
    and SQL cannot read one — so a row from an older vocabulary can exist. It
    must do nothing, and a resource PERMISSIONS does not define must refuse."""
    assert can_user(_user("Partner", {"tarot:read": True}), "tarot", "read") is False
    assert can_user(_user("Partner", {"tarot:read": False}), "tarot", "read") is False
    assert is_known_permission("tarot", "read") is False


def test_a_grant_on_one_pair_does_not_leak_to_its_neighbours():
    person = _user("Reviewer", {"payroll:read": True})
    assert can_user(person, "payroll", "read") is True
    assert can_user(person, "payroll", "write") is False
    assert can_user(person, "payroll", "finalize") is False
    assert can_user(person, "billing", "read") is False


# ── The screen and the engine cannot disagree ────────────────────────────────

@pytest.mark.parametrize("role", ALL_ROLES)
def test_what_a_screen_is_told_is_what_rbac_will_do(role):
    """`/api/identity/permissions` renders from `get_accessible_resources`, and
    `rbac()` decides from `can_user`. Two derivations of one answer is how the
    Schedule III caption list came to offer five captions the engine had never
    heard of. Asserted over every pair under a non-trivial override set."""
    overrides = {
        "payroll:write": True, "payroll:read": True,
        "billing:read": False, "accounting:write": True,
        "team:write": False, "gst:approve": True,
    }
    served = get_accessible_resources(role, overrides)
    for resource, action in ALL_PAIRS:
        assert (action in served.get(resource, [])) == can_user(_user(role, overrides), resource, action), (
            f"{role} {resource}:{action}: the screen and the guard disagree"
        )


@pytest.mark.parametrize("role", ALL_ROLES)
def test_the_template_is_still_the_template(role):
    """`get_accessible_resources(role)` with no overrides must keep answering
    for the ROLE — /role-matrix shows a Partner what each role grants before
    they start overriding it, and a new member's grid is pre-filled from it."""
    served = get_accessible_resources(role)
    for resource, action in ALL_PAIRS:
        assert (action in served.get(resource, [])) == can(role, resource, action)
