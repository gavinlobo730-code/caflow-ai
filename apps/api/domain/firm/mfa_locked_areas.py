"""What the authenticator guard locks for a particular person, in the words the banner says (PRE-A-021).

`main.py` mounts seven routers behind `mfa_guard` (`_MFA_GUARD`): until a Partner or Manager the policy covers
has a verified authenticator, every route on them answers 403. The staff banner and the security settings page
used to say one fixed sentence to everyone: "Team, Payroll, Billing and firm settings stay locked until you set
up an authenticator app". Billing (and the firm's own practice books) is Partner-only by role, so a Manager read
that they would reach Billing once they set up an authenticator, which is false (the owner, signed in as a
Manager, 15-11-2026); and the sentence left out client assignments, the data export and the member's own profile,
which the same guard locks.

This module names each locked area once, with the permission a person needs to reach it at all, and
`locked_areas_for` keeps the areas the person's own permissions reach: what the authenticator would open for
THEM. `/api/security/mfa-policy` serves the list and the sentence built from it, so the browser words nothing.
`tests/test_the_mfa_banner_names_only_what_the_caller_reaches.py` holds the list to the routers `main.py`
actually guards, so an eighth guarded router cannot go unnamed.
"""
from __future__ import annotations

from typing import Mapping, Optional

from core.permissions import resolve_permission

#: (words in the sentence, the router module `main.py` guards, the permission needed to reach it at all).
#: Order is the sentence's order. `identity` carries two areas: the team screens (team:read, Manager and above)
#: and the member's own profile (identity:write, every member).
MFA_LOCKED_AREAS: tuple[tuple[str, str, str, str], ...] = (
    ("Team", "identity", "team", "read"),
    ("client assignments", "assignments", "assignment", "read"),
    ("Payroll", "payroll", "payroll", "read"),
    ("firm settings", "firms", "firm", "read"),
    ("Billing", "billing", "billing", "read"),
    ("the practice's own books", "practice", "practice", "read"),
    ("the data export", "data_export", "firm", "admin"),
    ("your own profile", "identity", "identity", "write"),
)


def locked_areas_for(role: Optional[str], overrides: Optional[Mapping] = None) -> list[str]:
    """The areas, in the sentence's order, that this person's own permissions reach. An unknown role reaches
    nothing, so the list is empty rather than a guess."""
    if not role:
        return []
    return [label for label, _module, resource, action in MFA_LOCKED_AREAS
            if resolve_permission(role, dict(overrides or {}), resource, action)]


def locked_sentence(areas: list[str]) -> Optional[str]:
    """The banner's sentence for these areas, or None when there are none (then nothing is said)."""
    if not areas:
        return None
    if len(areas) == 1:
        listed = areas[0]
    else:
        listed = ", ".join(areas[:-1]) + " and " + areas[-1]
    listed = listed[0].upper() + listed[1:]
    verb = "stays" if len(areas) == 1 else "stay"
    return f"{listed} {verb} locked until you set up an authenticator app."
