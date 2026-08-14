"""
Employee-portal provisioning — the link between a payroll_employees row and a
Supabase identity.

Migration 262 made the employee portal readable; it deliberately did not create
the link, because granting an employee access to salary data is a decision, not
a rename. This is that link: a CA invites an employee, the employee signs in
with their own Supabase identity and presents the invite token, and only then
are auth_user_id and portal_enabled set.

MODELLED ON services/portal_access_service.py, INCLUDING ITS SCARS
    Client-portal invites had a real vulnerability (migration 153): binding
    happened whenever a session's email matched a row, on every page load — no
    token, no expiry, no explicit action — so a recycled or typo'd address
    inherited someone else's data on first login. Every property below exists
    because of that:

      * a 256-bit token from secrets.token_urlsafe, not a guessable id
      * an explicit expiry, checked on every acceptance
      * single use: the token is cleared the moment it binds
      * the row must still be unbound, so an accepted invite cannot be replayed
        onto a different identity
      * the email is checked too, as defence in depth
      * every failure raises the SAME generic 404, so the error cannot be used
        as an oracle to distinguish "no such token" from "expired" from "wrong
        email"

ONE DELIBERATE DIVERGENCE
    The client flow stores the live token in client_portal_users.invite_token.
    This one stores only sha256(token) — see migration 264's header for why the
    obvious column-level REVOKE does not work. The plaintext token is returned
    exactly once, by invite_employee(), to the caller that will deliver it.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from core.authz import assert_client_access
from core.urls import frontend_base

# Same window the client-portal invites use. Long enough for someone on leave to
# act on it, short enough that a forgotten invite does not stay live for months.
_INVITE_TTL = timedelta(days=14)

# Same test portal_access_service uses — mock mode is "no Supabase configured",
# not a flag of its own. Inventing USE_MOCK_DB here would have added an
# undeclared environment variable, which is exactly what
# tests/test_render_manifest_matches_code.py exists to catch, and it did.
_USE_MOCK = not os.environ.get("SUPABASE_URL")

# Mock store (mock/dev mode only) — mirrors portal_access_service's shape.
MOCK_EMPLOYEES: list[dict] = []


def reset_mock_stores() -> None:  # test helper
    MOCK_EMPLOYEES.clear()


def _db():
    from core.database import get_db
    return get_db()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def token_hash(token: str) -> str:
    """sha256 hex of an invite token.

    Plain sha256, not a password KDF: the input is 32 bytes of CSPRNG output, so
    there is no dictionary to search and stretching would buy nothing. A salt
    would only prevent cross-row comparison of identical tokens, and tokens are
    never identical.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _employee(firm_id: str, employee_id: str, db, actor: Optional[dict] = None) -> dict:
    """One employee of THIS firm, and of a client the caller may act for.

    Firm scoping is applied in the query rather than checked afterwards, so a
    wrong-firm id is indistinguishable from a missing one.

    The client-assignment check is NOT optional and cannot be left to RLS: these
    calls run through the backend's service-role client, which bypasses
    payroll_employees_assignment_scope entirely. Without it an Executive
    assigned only to Client A could issue portal access to Client B's employee.
    Caught by tests/test_router_client_scope.py, which is exactly what that
    ratchet is for."""
    if _USE_MOCK:
        row = next((e for e in MOCK_EMPLOYEES
                    if e.get("id") == employee_id and e.get("firm_id") == firm_id), None)
    else:
        rows = (db.table("payroll_employees").select("*")
                .eq("id", employee_id).eq("firm_id", firm_id).limit(1).execute().data or [])
        row = rows[0] if rows else None
    if not row:
        raise HTTPException(status_code=404, detail="Employee not found.")
    if actor is not None:
        # Raises 404, not 403 — the existence of another client's employee is
        # itself not disclosed.
        assert_client_access(actor, row.get("client_id"))
    return row


def _update(employee_id: str, fields: dict, db) -> dict:
    if _USE_MOCK:
        for e in MOCK_EMPLOYEES:
            if e.get("id") == employee_id:
                e.update(fields)
                return dict(e)
        raise HTTPException(status_code=404, detail="Employee not found.")
    rows = (db.table("payroll_employees").update(fields)
            .eq("id", employee_id).execute().data or [])
    if not rows:
        raise HTTPException(status_code=404, detail="Employee not found.")
    return rows[0]


def _audit(firm_id, employee_id, action, actor, extra=None) -> None:
    try:
        from services import audit_service
        audit_service.log_event(
            firm_id=firm_id, entity_type="payroll_employee", entity_id=employee_id,
            action=action, actor_id=(actor or {}).get("auth_user_id"),
            actor_email=(actor or {}).get("email"), metadata=extra or {})
    except Exception:  # audit must never block provisioning
        pass


def activation_url(token: str) -> str:
    """Where the invited employee goes. Built from core.urls so it follows
    FRONTEND_URL rather than hardcoding a host that may not resolve."""
    return f"{frontend_base()}/portal/employee/activate?token={token}"


def invite_employee(firm_id: str, employee_id: str, email: str,
                    actor: Optional[dict] = None, db=None) -> dict:
    """Mint a fresh single-use invite for one employee.

    Re-inviting is allowed and always mints a NEW token, which invalidates the
    previous one — the same "re-invite supersedes" behaviour as
    portal_access_service.invite_contact. An already-activated employee is
    refused rather than silently re-invited, because that would look like it
    worked while their existing access continued unchanged.

    Returns the plaintext token; it is not stored and cannot be retrieved again.
    """
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="A valid email is required.")
    db = db or (None if _USE_MOCK else _db())
    employee = _employee(firm_id, employee_id, db, actor)

    if employee.get("auth_user_id"):
        raise HTTPException(
            status_code=409,
            detail="This employee already has portal access. Revoke it first to re-issue.")

    token = secrets.token_urlsafe(32)
    _update(employee_id, {
        "email": email.strip(),
        "portal_invite_token_hash": token_hash(token),
        "portal_invite_expires_at": (datetime.now(timezone.utc) + _INVITE_TTL).isoformat(),
        "portal_invited_at": _now(),
        "portal_invited_by": (actor or {}).get("auth_user_id"),
        # Access stays OFF until the invite is accepted. Setting it here would
        # hand out access to anyone who later guessed the auth link.
        "portal_enabled": False,
    }, db)

    _audit(firm_id, employee_id, "employee_portal_invite", actor, {"email": email.strip()})
    _send_invite_email(email.strip(), employee.get("name") or "", token)
    return {"employee_id": employee_id, "email": email.strip(), "token": token,
            "activation_url": activation_url(token)}


def _send_invite_email(email: str, name: str, token: str) -> None:
    """Best-effort. A failed send must not lose the invite — the endpoint also
    returns the activation URL so the CA can deliver it another way."""
    try:
        from services.email_service import _send
        url = activation_url(token)
        _send(to=email,
              subject="Your payslip portal access",
              html=(f"<p>Hello {name or 'there'},</p>"
                    f"<p>Your employer has given you access to view your payslips "
                    f"and leave balance online.</p>"
                    f'<p><a href="{url}">Activate your portal access</a></p>'
                    f"<p>This link works once and expires in 14 days.</p>"))
    except Exception:
        pass


def _find_pending_by_token(token: str, db):
    """A pending invite, looked up by the token's HASH.

    `auth_user_id IS NULL` is part of the query, not a check afterwards: it is
    what stops an already-accepted invite being replayed onto a second identity.
    """
    if not token:
        return None
    h = token_hash(token)
    if _USE_MOCK:
        return next((e for e in MOCK_EMPLOYEES
                     if e.get("portal_invite_token_hash") == h and not e.get("auth_user_id")), None)
    rows = (db.table("payroll_employees").select("*")
            .eq("portal_invite_token_hash", h).is_("auth_user_id", "null")
            .limit(1).execute().data or [])
    return rows[0] if rows else None


def accept_employee_invite(token: str, auth_user_id: str, email: str, db=None) -> dict:
    """Bind a Supabase identity to the invited employee.

    Every rejection raises the same 404 with the same message. Distinguishing
    "no such token" from "expired" from "wrong email" would let someone probe
    which tokens exist.
    """
    db = db or (None if _USE_MOCK else _db())
    invite = _find_pending_by_token(token, db)
    generic = HTTPException(status_code=404, detail="Invalid or expired invite.")
    if not invite:
        raise generic
    if not auth_user_id:
        raise generic

    expires_at = invite.get("portal_invite_expires_at")
    if not expires_at:
        raise generic
    exp = (expires_at if isinstance(expires_at, datetime)
           else datetime.fromisoformat(str(expires_at).replace("Z", "+00:00")))
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < datetime.now(timezone.utc):
        raise generic
    if (invite.get("email") or "").strip().lower() != (email or "").strip().lower():
        raise generic

    row = _update(invite["id"], {
        "auth_user_id": auth_user_id,
        "portal_enabled": True,
        "portal_activated_at": _now(),
        # Single use — the hash goes too, so the same link cannot bind twice.
        "portal_invite_token_hash": None,
        "portal_invite_expires_at": None,
    }, db)

    _audit(invite.get("firm_id"), invite["id"], "employee_portal_activated",
           {"auth_user_id": auth_user_id, "email": email}, {"email": email})
    return {"employee_id": row["id"], "name": row.get("name"),
            "client_id": row.get("client_id")}


def revoke_employee_portal(firm_id: str, employee_id: str,
                           actor: Optional[dict] = None, db=None) -> dict:
    """Withdraw access.

    Clears auth_user_id as well as portal_enabled. Leaving the binding in place
    would mean re-enabling the flag silently restored the OLD identity's access
    — including an ex-employee's. Revoke then re-invite is the only way back,
    and that mints a fresh token for whoever is meant to have it now.
    """
    db = db or (None if _USE_MOCK else _db())
    employee = _employee(firm_id, employee_id, db, actor)
    _update(employee_id, {
        "portal_enabled": False,
        "auth_user_id": None,
        "portal_invite_token_hash": None,
        "portal_invite_expires_at": None,
    }, db)
    _audit(firm_id, employee_id, "employee_portal_revoked", actor)
    return {"employee_id": employee_id, "portal_enabled": False}


def portal_status(firm_id: str, employee_id: str, db=None, actor: Optional[dict] = None) -> dict:
    """What the payroll screen shows next to an employee. Never returns the
    hash — there is no caller that needs it, and it would be one more place a
    secret could leak from."""
    db = db or (None if _USE_MOCK else _db())
    e = _employee(firm_id, employee_id, db, actor)
    pending = bool(e.get("portal_invite_token_hash"))
    return {
        "employee_id": employee_id,
        "email": e.get("email"),
        "portal_enabled": bool(e.get("portal_enabled")),
        "activated": bool(e.get("auth_user_id")),
        "invite_pending": pending and not e.get("auth_user_id"),
        "invited_at": e.get("portal_invited_at"),
        "invite_expires_at": e.get("portal_invite_expires_at") if pending else None,
        "activated_at": e.get("portal_activated_at"),
    }
