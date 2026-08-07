"""
Module 9.0 / M2 — Central Authorization Engine.

Single source of truth for "can this user act on this resource (optionally scoped
to a client)?". Composes, in order:

    tenant (firm) → RBAC role (core.permissions) → client assignment scope

Design notes
------------
* Deny by default — unknown role / unknown resource-action / unassigned client
  all resolve to "no".
* Role-aware: delegates the role↔action matrix to core.permissions.can().
* Assignment-aware: Partner/Manager are firm-wide; Executive/Reviewer/Client are
  restricted to clients in user_client_assignments. Returns 404 (not 403) on an
  unauthorized client so existence is not disclosed.
* Visibility-layer compatible: can_access_client / effective_client_ids are the
  seam a future data-classification tier plugs into.

ENFORCEMENT NOTE. The backend uses the Supabase SERVICE_ROLE key (bypasses RLS),
so these application-layer checks are the effective control. In mock/dev mode
(no SUPABASE_URL) there is no assignments table, so assignment checks are
permissive — real enforcement runs against the live DB; the enforcement *logic*
is unit-tested with explicit assignment fixtures (see tests/test_authz_engine.py).
"""
import os
from typing import Optional

from fastapi import Depends, HTTPException, Request

from core.auth import get_current_user
from core.permissions import Role, _to_role, can as _rbac_can

_USE_MOCK = not os.environ.get("SUPABASE_URL")

# Firm-wide roles see every client in their firm; everyone else is assignment-scoped.
# M3 decision — Manager scope = assigned-book (Option B): only the Partner/Owner is
# firm-wide. Managers (like Executives/Reviewers) see only the clients explicitly
# assigned to them, so one manager cannot see another manager's book — the core
# internal-confidentiality goal of Module 9. Flip this set to re-include MANAGER if
# a firm-wide manager model is ever desired.
_FIRMWIDE_ROLES = {Role.PARTNER}


def _db():
    from core.supabase_client import get_service_supabase
    return get_service_supabase()


def _role(user: dict) -> Optional[Role]:
    try:
        return _to_role(str(user.get("role", "")))
    except ValueError:
        return None


def is_firmwide(user: dict) -> bool:
    """True for roles that may see every client in the firm."""
    return _role(user) in _FIRMWIDE_ROLES


def firmwide_roles_label() -> str:
    """The firm-wide roles, named, for a refusal message a human has to read.

    Derived from `_FIRMWIDE_ROLES` rather than written out, because it had
    already drifted: two routers told a refused caller the endpoint was open to
    "Partners and Managers" when the M3 decision above left only the Partner
    firm-wide. A Manager was reading a 403 saying they should have got in.
    """
    names = sorted(role.value + "s" for role in _FIRMWIDE_ROLES)
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def assigned_client_ids(user: dict) -> set[str]:
    """The set of client ids explicitly assigned to this user.

    Empty when the user has no internal id resolved or in mock mode (callers
    should use effective_client_ids/can_access_client which apply the dev
    permissive rule)."""
    uid = user.get("id")
    if _USE_MOCK or not uid:
        return set()
    res = (
        _db().table("user_client_assignments")
        .select("client_id")
        .eq("user_id", uid)
        .execute()
    )
    return {str(r["client_id"]) for r in (res.data or []) if r.get("client_id")}


def is_client_assigned(user_id: Optional[str], client_id: Optional[str]) -> bool:
    """Low-level check: is this (internal) user id assigned to this client?
    Canonical assignment primitive — other modules (e.g. knowledge_service)
    delegate here rather than re-implementing the query. Mock/dev permissive."""
    if not user_id or not client_id:
        return False
    if _USE_MOCK:
        return True
    res = (
        _db().table("user_client_assignments")
        .select("id")
        .eq("user_id", user_id)
        .eq("client_id", client_id)
        .limit(1)
        .execute()
    )
    return bool(res.data)


def effective_client_ids(user: dict) -> Optional[set[str]]:
    """Client ids the user may access.

    Returns None to mean "ALL clients in the firm" (firm-wide roles, or mock/dev
    where enforcement is permissive). Otherwise a concrete set of assigned ids.
    Callers filter firm-scoped result sets against this (None ⇒ no extra filter).
    """
    if is_firmwide(user):
        return None
    if _USE_MOCK:
        return None  # dev/test permissive — real scoping requires the DB
    return assigned_client_ids(user)


def _client_belongs_to_firm(client_id: str, firm_id: Optional[str]) -> bool:
    """Real-DB check (F1 fix): does this client exist and belong to this firm?
    Only reached on the enforced (non-mock) path — see can_access_client."""
    from repositories.client_repository import client_repo
    return client_repo.find_by_id(client_id, firm_id=firm_id) is not None


def can_access_client(user: dict, client_id: Optional[str]) -> bool:
    """Whether the user may access a specific client's data."""
    if not client_id:
        return True  # firm-level resource, no client scope to check
    if _USE_MOCK:
        return True
    # F1 fix: is_firmwide() says a role sees every client IN ITS OWN FIRM — it
    # says nothing about which firm client_id actually belongs to. Without this
    # check, a Partner in Firm B who supplies (or guesses) Firm A's client_id
    # passed this gate unconditionally, because the old ordering returned True
    # for any firm-wide role before ever looking at the client at all.
    if not _client_belongs_to_firm(client_id, user.get("firm_id")):
        return False
    if is_firmwide(user):
        return True
    return str(client_id) in assigned_client_ids(user)


def assert_client_access(user: dict, client_id: Optional[str]) -> None:
    """Raise 404 (existence not disclosed) if the user may not access the client."""
    if not can_access_client(user, client_id):
        raise HTTPException(status_code=404, detail="Not found")


def authorize(user: dict, resource: str, action: str, *, client_id: Optional[str] = None) -> bool:
    """Single source of truth: RBAC role check AND (optional) client-assignment scope."""
    if not _rbac_can(str(user.get("role", "")), resource, action):
        return False
    if client_id is not None and not can_access_client(user, client_id):
        return False
    return True


def filter_by_client(user: dict, rows: list[dict], key: str = "client_id") -> list[dict]:
    """Drop rows whose client is outside the user's effective client set.
    Rows with no client id (firm-level) are kept."""
    eff = effective_client_ids(user)
    if eff is None:
        return rows
    return [r for r in rows if not r.get(key) or str(r.get(key)) in eff]


def require(resource: str, action: str):
    """FastAPI dependency: RBAC + per-request client-assignment scope.

    Reads client_id from the path or query string (body scope is enforced in the
    handler). Equivalent to permissions.rbac() but assignment-aware. 403 on role
    failure; 404 on an unauthorized client (existence not disclosed)."""
    def _dependency(request: Request, current_user: dict = Depends(get_current_user)) -> dict:
        role = str(current_user.get("role", ""))
        if not _rbac_can(role, resource, action):
            raise HTTPException(
                status_code=403,
                detail=f"Role '{role}' cannot perform '{action}' on '{resource}'",
            )
        client_id = request.path_params.get("client_id") or request.query_params.get("client_id")
        if client_id:
            assert_client_access(current_user, client_id)
        return current_user

    _dependency.__name__ = f"authz_{resource}_{action}"
    return _dependency
