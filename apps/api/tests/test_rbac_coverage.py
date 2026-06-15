"""
Module 9.0 / M1 — RBAC coverage guardrail + role-model unification tests.

The single most important test here scans every router for rbac("resource","action")
usage and asserts each pair is defined in the PERMISSIONS matrix. This permanently
prevents the "phantom resource" class of bug (a resource referenced by a router but
missing from PERMISSIONS → can() fail-closed → 403 for ALL roles, including Partner).
"""
import re
from pathlib import Path

import pytest

from core.permissions import (
    PERMISSIONS,
    Role,
    _to_role,
    can,
)

ROUTERS_DIR = Path(__file__).resolve().parent.parent / "routers"
RBAC_CALL = re.compile(r"""rbac\(\s*["']([a-z_]+)["']\s*,\s*["']([a-z_]+)["']\s*\)""")


def _all_rbac_pairs():
    pairs = set()
    for py in ROUTERS_DIR.glob("*.py"):
        for resource, action in RBAC_CALL.findall(py.read_text()):
            pairs.add((resource, action, py.name))
    return pairs


def test_every_rbac_resource_action_is_defined():
    """Guardrail: no phantom resources/actions. Every rbac() pair must exist."""
    missing = []
    for resource, action, fname in sorted(_all_rbac_pairs()):
        if action not in PERMISSIONS.get(resource, {}):
            missing.append(f"{fname}: rbac({resource!r}, {action!r})")
    assert not missing, "rbac() references not defined in PERMISSIONS:\n" + "\n".join(missing)


def test_previously_phantom_resources_now_defined():
    """The 7 resources that used to 403 for everyone are now real."""
    for resource in ("analytics", "copilot", "engagement", "invoice",
                     "payroll", "time_entry", "workload", "portal"):
        assert resource in PERMISSIONS, f"{resource} still missing from PERMISSIONS"
        assert PERMISSIONS[resource], f"{resource} has no actions"


def test_partner_can_use_previously_broken_endpoints():
    """Partner must be allowed on the formerly-phantom resources."""
    assert can("Partner", "analytics", "read")
    assert can("Partner", "payroll", "read")
    assert can("Partner", "invoice", "write")
    assert can("Partner", "workload", "read")
    assert can("Partner", "portal", "read")


def test_permission_matrix_only_uses_canonical_roles():
    """No legacy role strings (Article/Staff/Admin/Viewer) leak into PERMISSIONS."""
    canonical = set(Role)
    for resource, actions in PERMISSIONS.items():
        for action, roles in actions.items():
            for r in roles:
                assert r in canonical, f"{resource}.{action} references non-canonical role {r!r}"


# ── Role-model unification: legacy → canonical mapping ───────────────────────

@pytest.mark.parametrize("legacy,expected", [
    ("owner", Role.PARTNER),
    ("admin", Role.MANAGER),
    ("manager", Role.MANAGER),
    ("article", Role.EXECUTIVE),
    ("Article", Role.EXECUTIVE),
    ("staff", Role.EXECUTIVE),
    ("Staff", Role.EXECUTIVE),
    ("viewer", Role.REVIEWER),
    ("Viewer", Role.REVIEWER),
    ("partner", Role.PARTNER),
    ("PARTNER", Role.PARTNER),
])
def test_legacy_roles_map_to_canonical(legacy, expected):
    assert _to_role(legacy) == expected


def test_unknown_role_raises():
    with pytest.raises(ValueError):
        _to_role("wizard")


def test_legacy_role_authorizes_through_can():
    """A legacy 'Article' user must authorize like an Executive (not 403)."""
    assert can("Article", "task", "read") is True
    assert can("Staff", "client", "read") is True
    assert can("Viewer", "client", "read") is True   # Reviewer is in _ALL_STAFF
    assert can("Viewer", "client", "write") is False  # Reviewer cannot write
