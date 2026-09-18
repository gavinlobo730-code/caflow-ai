"""
Per-person access overrides — read and write the grid (migration 403).

WHAT THIS IS FOR
    `rbac(resource, action)` decided every request from the caller's ROLE, and a
    role is five buckets. A practice is not staffed in five buckets: one
    Executive runs GST and TDS and never touches payroll, another runs payroll
    and nothing else, and a senior Manager is trusted with the firm's own
    billing while their peer is not. Without a per-person answer the firm either
    promotes somebody to reach one screen — handing them every other screen that
    tier opens — or does the work outside the product.

THE RULE IS NOT HERE
    `core.permissions.resolve_permission` is the rule and `can_user` is what
    every request goes through. This module FETCHES and WRITES; it decides
    nothing about who may do what, exactly as `services/cwip_service.py` decides
    nothing `domain/fixed_assets/cwip.py` decides. Two answers to "may this
    person post a journal" is the failure this separation exists to prevent.

WHAT IT REFUSES, AND WHY EACH REFUSAL IS ITS OWN
    * An unknown (resource, action) pair. The column is free TEXT with no CHECK
      — the vocabulary is a Python dict and SQL cannot read one — so this door
      is where the vocabulary is enforced. A stale row is inert rather than
      dangerous, but a row that was never valid should not be written at all.
    * Denying a Partner one of `UNREVOKABLE_FOR_PARTNER`. Refused HERE with a
      sentence the screen can show, as well as ignored by the resolver: the
      resolver's floor is the backstop for a row that arrived another way (a
      restored backup, a hand-run UPDATE), and a door that silently accepted a
      write the resolver then ignored would be a control that does nothing —
      which is the exact fault the read-only Team grid was left as a monument to.
    * A member of another firm. `users.id` is a global key, so without this the
      caller could write a row against anybody's account in the database.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from core.permissions import (
    PERMISSIONS,
    PRIVILEGE_CHANGING,
    UNREVOKABLE_FOR_PARTNER,
    canonical_role,
    get_accessible_resources,
    is_known_permission,
)
from core.db_paging import fetch_all
from core.observability import capture_soft_failure


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PermissionWriteRefused(ValueError):
    """A grid change the firm may not make, with the reason a human reads."""


def vocabulary() -> list[dict]:
    """Every (resource, action) pair the product has, for the grid's columns.

    Served rather than spelled in the browser for the reason
    `/api/identity/role-matrix` already exists: a hardcoded copy of this list
    drifted in BOTH directions at once the last time one was kept — it offered
    five captions the engine had never heard of and spelled five others
    differently. The Schedule III caption lesson, applied to access.
    """
    return [
        {
            "resource": resource,
            "action": action,
            # The screen must say plainly what a tick means where the tick lets
            # its holder change what OTHER people may do. It otherwise looks
            # exactly like the other thirty.
            "privilege_changing": (resource, action) in PRIVILEGE_CHANGING,
            "unrevokable_for_partner": (resource, action) in UNREVOKABLE_FOR_PARTNER,
        }
        for resource in sorted(PERMISSIONS)
        for action in sorted(PERMISSIONS[resource])
    ]


def overrides_for(db, firm_id: str, user_id: str) -> dict[str, bool]:
    """The stored answers for one member, keyed ``"resource:action"``.

    Firm-scoped as well as user-scoped: `users.id` is a global key and the
    app-layer `.eq("firm_id", …)` filter is the primary isolation control,
    because the service-role key bypasses RLS.
    """
    rows = fetch_all(
        lambda: (
            db.table("user_permissions")
            .select("id, resource, action, granted")
            .eq("firm_id", firm_id)
            .eq("user_id", user_id)
        ),
        label="user_permissions.overrides_for",
    )
    return {
        f"{r['resource']}:{r['action']}": r["granted"]
        for r in rows
        if r.get("resource") and r.get("action") and isinstance(r.get("granted"), bool)
    }


def grid_for(db, firm_id: str, member: dict) -> dict:
    """What one member may reach, and why — the Team screen's per-person panel.

    Carries THREE things a screen needs and cannot derive: the role's own
    template (so the grid can show what a tick is departing from), the stored
    overrides, and the EFFECTIVE answer. Showing only the last would make an
    inherited permission and a deliberately granted one look identical, so a
    Partner could not tell which of their firm's access was a decision.
    """
    role = canonical_role(member.get("role"))
    overrides = overrides_for(db, firm_id, str(member["id"]))
    return {
        "user_id": str(member["id"]),
        "full_name": member.get("full_name"),
        "email": member.get("email"),
        "role": role,
        "role_defaults": get_accessible_resources(role) if role else {},
        "overrides": overrides,
        "effective": get_accessible_resources(role, overrides) if role else {},
    }


def _assert_writable(role: Optional[str], resource: str, action: str, granted: bool) -> None:
    if not is_known_permission(resource, action):
        raise PermissionWriteRefused(
            f"'{resource}:{action}' is not a permission this product has. "
            "The list of pairs is served by GET /api/identity/permission-vocabulary."
        )
    if granted is False and role == "Partner" and (resource, action) in UNREVOKABLE_FOR_PARTNER:
        raise PermissionWriteRefused(
            f"A Partner cannot be denied '{resource}:{action}'. It is what reaches "
            "this screen, so removing it would leave nobody able to put it back."
        )


def set_permissions(
    db,
    firm_id: str,
    member: dict,
    changes: dict[str, bool | None],
    actor_id: Optional[str],
) -> dict:
    """Apply a set of grid changes for one member and return their new grid.

    `changes` is ``{"resource:action": True | False | None}``. **None DELETES
    the row**, which is not the same as False: absence means "whatever the role
    says" and False means "refused however senior", and a screen that could only
    express the second could never hand a permission back to the role — it would
    freeze today's role map into the person's row and detach them from
    `PERMISSIONS` the moment it is edited. The three-state control is the whole
    design; two states would be a different, worse feature.

    Every change is validated BEFORE any write, so a request carrying one bad
    pair changes nothing rather than half of what was asked.
    """
    role = canonical_role(member.get("role"))
    user_id = str(member["id"])

    parsed: list[tuple[str, str, Optional[bool]]] = []
    for key, value in changes.items():
        resource, _, action = str(key).partition(":")
        if not resource or not action:
            raise PermissionWriteRefused(
                f"'{key}' is not a permission key. Expected 'resource:action'."
            )
        if value is not None and not isinstance(value, bool):
            raise PermissionWriteRefused(
                f"'{key}' must be true (allow), false (refuse) or null (use the role default)."
            )
        if value is not None:
            _assert_writable(role, resource, action, value)
        elif not is_known_permission(resource, action):
            # Clearing an unknown pair is allowed — that is how a row left by an
            # older vocabulary gets removed, and refusing it would make such a
            # row permanent.
            pass
        parsed.append((resource, action, value))

    existing = fetch_all(
        lambda: (
            db.table("user_permissions")
            .select("id, resource, action, granted")
            .eq("firm_id", firm_id)
            .eq("user_id", user_id)
        ),
        label="user_permissions.set_permissions.existing",
    )
    by_pair = {(r["resource"], r["action"]): r for r in existing}

    for resource, action, value in parsed:
        row = by_pair.get((resource, action))
        if value is None:
            if row:
                db.table("user_permissions").delete().eq("id", row["id"]).execute()
            continue
        if row:
            if row.get("granted") == value:
                continue
            db.table("user_permissions").update({
                "granted": value, "granted_by": actor_id, "updated_at": _now(),
            }).eq("id", row["id"]).execute()
        else:
            db.table("user_permissions").insert({
                "firm_id": firm_id, "user_id": user_id,
                "resource": resource, "action": action,
                "granted": value, "granted_by": actor_id,
            }).execute()

    _invalidate(member)
    return grid_for(db, firm_id, member)


def _invalidate(member: dict) -> None:
    """Drop this member's cached auth row so the change bites now, not in 30s.

    `core.auth._get_user_and_firm` caches the user row — overrides included —
    for 30 seconds, which is right for the read path and wrong here: a Partner
    who removes somebody's access expects it removed, and half a minute of
    continued access after an explicit revocation is the wrong thing to explain.

    Best-effort and keyed on `auth_user_id`, which an invited member who has
    never signed in does not have; there is nothing cached for them either, so
    the miss is harmless.

    IT ONLY REACHES THIS PROCESS. The cache is per-instance, so on a deployment
    running more than one API instance the other instances still serve the old
    answer until their own TTL expires. The 30-second TTL is therefore the
    guarantee and this is an optimisation on top of it — which is exactly how a
    ROLE change already behaves on the same cache, so this adds no new exposure
    window, it only shortens the common one. A revocation that must be immediate
    and firm-wide is `suspend_user`, which bumps `sessions_revoked_at` and is
    checked against the JWT rather than cached.
    """
    auth_user_id = member.get("auth_user_id")
    if not auth_user_id:
        return
    try:
        from core.auth import _user_lookup_cache
        _user_lookup_cache.pop(auth_user_id, None)
    except Exception as exc:  # never let a cache miss fail a write
        # Reported rather than swallowed: the write SUCCEEDED and this only
        # decides whether it bites now or in 30 seconds, so failing the request
        # would be wrong — but a cache that stopped being clearable is exactly
        # the kind of quiet breakage that is noticed months later, by somebody
        # wondering why a revocation did not take.
        capture_soft_failure(exc, operation="user_permissions.invalidate_cache",
                             auth_user_id=str(auth_user_id))
