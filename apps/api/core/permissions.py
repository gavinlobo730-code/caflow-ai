"""
Role-Based Access Control for CAflow AI.
Roles: Partner > Manager > Executive > Reviewer > Client
"""
from enum import Enum
from typing import Optional
from core.exceptions import PermissionDeniedError


class Role(str, Enum):
    PARTNER   = "Partner"
    MANAGER   = "Manager"
    EXECUTIVE = "Executive"
    REVIEWER  = "Reviewer"
    CLIENT    = "Client"


# Permission matrix — what each role can do
# Format: resource -> set of roles that have access
PERMISSIONS: dict[str, dict[str, set[str]]] = {
    "firm": {
        "read":   {Role.PARTNER, Role.MANAGER},
        "write":  {Role.PARTNER},
        "admin":  {Role.PARTNER},
    },
    "client": {
        "read":   {Role.PARTNER, Role.MANAGER, Role.EXECUTIVE, Role.REVIEWER},
        "write":  {Role.PARTNER, Role.MANAGER},
        "delete": {Role.PARTNER},
    },
    "compliance_record": {
        "read":   {Role.PARTNER, Role.MANAGER, Role.EXECUTIVE, Role.REVIEWER},
        "write":  {Role.PARTNER, Role.MANAGER, Role.EXECUTIVE},
        "approve":{Role.PARTNER, Role.MANAGER},
        "delete": {Role.PARTNER},
    },
    "task": {
        "read":   {Role.PARTNER, Role.MANAGER, Role.EXECUTIVE, Role.REVIEWER},
        "write":  {Role.PARTNER, Role.MANAGER, Role.EXECUTIVE},
        "delete": {Role.PARTNER, Role.MANAGER},
    },
    "document": {
        "read":   {Role.PARTNER, Role.MANAGER, Role.EXECUTIVE, Role.REVIEWER},
        "write":  {Role.PARTNER, Role.MANAGER, Role.EXECUTIVE},
        "approve":{Role.PARTNER, Role.MANAGER, Role.REVIEWER},
        "delete": {Role.PARTNER},
    },
    "team": {
        "read":   {Role.PARTNER, Role.MANAGER},
        "write":  {Role.PARTNER},
        "delete": {Role.PARTNER},
    },
    "report": {
        "read":   {Role.PARTNER, Role.MANAGER, Role.REVIEWER},
        "export": {Role.PARTNER, Role.MANAGER},
    },
    "settings": {
        "read":   {Role.PARTNER, Role.MANAGER},
        "write":  {Role.PARTNER},
    },
    "accounting": {
        "read":   {Role.PARTNER, Role.MANAGER, Role.EXECUTIVE},
        "write":  {Role.PARTNER, Role.MANAGER},
        "approve":{Role.PARTNER},
    },
}


def can(role: str, resource: str, action: str) -> bool:
    """Check if a role has permission to perform action on resource."""
    resource_perms = PERMISSIONS.get(resource, {})
    allowed_roles = resource_perms.get(action, set())
    return Role(role) in allowed_roles


def require_permission(role: str, resource: str, action: str) -> None:
    """Raise PermissionDeniedError if role cannot perform action on resource."""
    if not can(role, resource, action):
        raise PermissionDeniedError(action, resource)


def get_accessible_resources(role: str) -> dict[str, list[str]]:
    """Return all resource:action pairs accessible to a role."""
    result: dict[str, list[str]] = {}
    for resource, actions in PERMISSIONS.items():
        accessible = [action for action, roles in actions.items() if Role(role) in roles]
        if accessible:
            result[resource] = accessible
    return result


# Role hierarchy — higher index = more privileged
ROLE_HIERARCHY = [Role.CLIENT, Role.REVIEWER, Role.EXECUTIVE, Role.MANAGER, Role.PARTNER]


def is_at_least(role: str, minimum: str) -> bool:
    """Check if role is at or above minimum in the hierarchy."""
    try:
        return ROLE_HIERARCHY.index(Role(role)) >= ROLE_HIERARCHY.index(Role(minimum))
    except ValueError:
        return False
