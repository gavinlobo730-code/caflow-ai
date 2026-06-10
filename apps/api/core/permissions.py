"""
Role-Based Access Control for CAflow AI.
Roles: Partner > Manager > Executive > Reviewer > Client

Usage in routers:
    from core.permissions import rbac

    @router.get("/foo")
    def list_foo(current_user: dict = Depends(rbac("resource", "read"))):
        ...
"""
from enum import Enum
from typing import Callable
from fastapi import Depends, HTTPException, status
from core.exceptions import PermissionDeniedError


class Role(str, Enum):
    PARTNER   = "Partner"
    MANAGER   = "Manager"
    EXECUTIVE = "Executive"
    REVIEWER  = "Reviewer"
    CLIENT    = "Client"


# Role hierarchy — index 0 = least privileged
ROLE_HIERARCHY = [Role.CLIENT, Role.REVIEWER, Role.EXECUTIVE, Role.MANAGER, Role.PARTNER]

_ALL_STAFF = {Role.PARTNER, Role.MANAGER, Role.EXECUTIVE, Role.REVIEWER}
_AT_LEAST_EXECUTIVE = {Role.PARTNER, Role.MANAGER, Role.EXECUTIVE}
_AT_LEAST_MANAGER   = {Role.PARTNER, Role.MANAGER}
_PARTNER_ONLY       = {Role.PARTNER}


# Permission matrix — resource -> action -> set of roles allowed
PERMISSIONS: dict[str, dict[str, set[str]]] = {
    # ── Firm administration ──────────────────────────────────────────────────
    "firm": {
        "read":   _AT_LEAST_MANAGER,
        "write":  _PARTNER_ONLY,
        "admin":  _PARTNER_ONLY,
    },
    # ── Clients ──────────────────────────────────────────────────────────────
    "client": {
        "read":   _ALL_STAFF,
        "write":  _AT_LEAST_MANAGER,
        "delete": _PARTNER_ONLY,
    },
    # ── Compliance records ───────────────────────────────────────────────────
    "compliance_record": {
        "read":   _ALL_STAFF,
        "write":  _AT_LEAST_EXECUTIVE,
        "approve": _AT_LEAST_MANAGER,
        "delete": _PARTNER_ONLY,
    },
    # ── Tasks ────────────────────────────────────────────────────────────────
    "task": {
        "read":   _ALL_STAFF,
        "write":  _AT_LEAST_EXECUTIVE,
        "delete": _AT_LEAST_MANAGER,
    },
    # ── Documents ────────────────────────────────────────────────────────────
    "document": {
        "read":   _ALL_STAFF,
        "write":  _AT_LEAST_EXECUTIVE,
        "approve": {Role.PARTNER, Role.MANAGER, Role.REVIEWER},
        "delete": _PARTNER_ONLY,
    },
    # ── Team management ──────────────────────────────────────────────────────
    "team": {
        "read":   _AT_LEAST_MANAGER,
        "write":  _PARTNER_ONLY,
        "delete": _PARTNER_ONLY,
    },
    # ── Reports / dashboards / insights ─────────────────────────────────────
    "report": {
        "read":   _ALL_STAFF,
        "write":  _AT_LEAST_MANAGER,
        "export": _AT_LEAST_MANAGER,
    },
    # ── Settings / automation ────────────────────────────────────────────────
    "settings": {
        "read":   _AT_LEAST_MANAGER,
        "write":  _PARTNER_ONLY,
    },
    # ── Accounting ───────────────────────────────────────────────────────────
    "accounting": {
        "read":   _AT_LEAST_EXECUTIVE,
        "write":  _AT_LEAST_MANAGER,
        "approve": _PARTNER_ONLY,   # post/approve journal entry
    },
    # ── GST (compute, validate, approve for filing) ──────────────────────────
    "gst": {
        "read":    _ALL_STAFF,
        "compute": _AT_LEAST_EXECUTIVE,
        "approve": _AT_LEAST_MANAGER,
    },
    # ── TDS ──────────────────────────────────────────────────────────────────
    "tds": {
        "read":    _ALL_STAFF,
        "compute": _AT_LEAST_EXECUTIVE,
        "approve": _AT_LEAST_MANAGER,
    },
    # ── Income Tax ───────────────────────────────────────────────────────────
    "income_tax": {
        "read":    _ALL_STAFF,
        "compute": _AT_LEAST_EXECUTIVE,
        "approve": _AT_LEAST_MANAGER,
    },
    # ── Notifications (every authenticated staff member can read/mark own) ───
    "notification": {
        "read":  _ALL_STAFF,
        "write": _ALL_STAFF,
    },
    # ── Workflows ────────────────────────────────────────────────────────────
    "workflow": {
        "read":       _ALL_STAFF,
        "instantiate": _AT_LEAST_EXECUTIVE,
    },
    # ── Risks ────────────────────────────────────────────────────────────────
    "risk": {
        "read":  _AT_LEAST_MANAGER,
        "write": _AT_LEAST_MANAGER,
    },
    # ── AI assistant ─────────────────────────────────────────────────────────
    "ai": {
        "read":     _ALL_STAFF,       # general assistant (Reviewer can ask questions)
        "copilot":  _AT_LEAST_MANAGER,  # firm-context AI (sees client list, risks)
    },
    # ── Automation engine ────────────────────────────────────────────────────
    "automation": {
        "read":  _AT_LEAST_MANAGER,
        "write": _PARTNER_ONLY,
    },
    # ── Reminders ────────────────────────────────────────────────────────────
    "reminder": {
        "read":  _ALL_STAFF,
        "write": _AT_LEAST_EXECUTIVE,
    },
    # ── Time tracking ─────────────────────────────────────────────────────────
    "time_entry": {
        "read":   _ALL_STAFF,
        "write":  _ALL_STAFF,
        "delete": _AT_LEAST_MANAGER,
        "report": _AT_LEAST_MANAGER,
    },
    # ── Workload visibility ───────────────────────────────────────────────────
    "workload": {
        "read":  _AT_LEAST_MANAGER,
        "write": _AT_LEAST_MANAGER,
    },
    # ── Productivity analytics ────────────────────────────────────────────────
    "analytics": {
        "read":   _AT_LEAST_MANAGER,
        "export": _AT_LEAST_MANAGER,
    },
    # ── Fee engagements ────────────────────────────────────────────────────────
    "engagement": {
        "read":  _AT_LEAST_MANAGER,
        "write": _PARTNER_ONLY,
    },
    # ── Fee invoices ───────────────────────────────────────────────────────────
    "invoice": {
        "read":  _AT_LEAST_MANAGER,
        "write": _PARTNER_ONLY,
    },
}


# ── Core helpers ─────────────────────────────────────────────────────────────

def can(role: str, resource: str, action: str) -> bool:
    """Return True if role is allowed to perform action on resource."""
    try:
        r = Role(role)
    except ValueError:
        return False
    resource_perms = PERMISSIONS.get(resource, {})
    allowed_roles = resource_perms.get(action, set())
    return r in allowed_roles


def require_permission(role: str, resource: str, action: str) -> None:
    """Raise PermissionDeniedError if role cannot perform action on resource."""
    if not can(role, resource, action):
        raise PermissionDeniedError(action, resource)


def is_at_least(role: str, minimum: str) -> bool:
    """Return True if role is at or above minimum in the hierarchy."""
    try:
        return ROLE_HIERARCHY.index(Role(role)) >= ROLE_HIERARCHY.index(Role(minimum))
    except ValueError:
        return False


def get_accessible_resources(role: str) -> dict[str, list[str]]:
    """Return all resource:action pairs accessible to a role."""
    result: dict[str, list[str]] = {}
    for resource, actions in PERMISSIONS.items():
        accessible = [action for action, roles in actions.items() if can(role, resource, action)]
        if accessible:
            result[resource] = accessible
    return result


# ── FastAPI Dependency factory ────────────────────────────────────────────────

def rbac(resource: str, action: str) -> Callable:
    """
    FastAPI dependency factory — validates JWT *and* enforces RBAC in one shot.

    Usage:
        @router.get("/foo")
        def list_foo(current_user: dict = Depends(rbac("client", "read"))):
            ...

    Raises 401 if no/invalid JWT, 403 if role lacks permission.
    """
    from core.auth import get_current_user  # avoid circular import at module level

    def _dependency(current_user: dict = Depends(get_current_user)) -> dict:
        role = current_user.get("role", "")
        if not can(role, resource, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' cannot perform '{action}' on '{resource}'",
            )
        return current_user

    # Give the dependency a stable name so FastAPI's OpenAPI can reference it
    _dependency.__name__ = f"rbac_{resource}_{action}"
    return _dependency
