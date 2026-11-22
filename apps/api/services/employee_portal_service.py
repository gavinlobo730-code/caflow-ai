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
    This one stores only a hash of it — see migration 264's header for why the
    obvious column-level REVOKE does not work.

THE TOKEN EXISTS ONLY IN THE MAIL THE SERVER SENDS (POST-A-552, 22-11-2026)
    `invite_employee` used to hand the token and the activation link BACK to the
    member of staff who pressed Invite, "so the caller can deliver the link if
    the email does not arrive", and the dialog showed it for copying. Since
    POST-A-445 that link is more than an invitation: `mint_activation_session`
    turns the bare token into a Supabase sign-in for the invitation's address,
    and for an address that ALREADY has a sign-in it asks for a magic link. So
    anybody allowed to invite an employee could type the address of an existing
    account (a Partner of their own practice, a member of another practice, a
    client's portal contact), copy the link from the dialog and be signed in AS
    THAT PERSON, in whatever practice or portal the account belongs to. The
    staff invitation had exactly this hole and closed it on 16-11-2026
    (`services/staff_invite_service`); the note written then said of this flow
    that its token "is never returned to anybody", which was not true.

    Now it is. The server issues the token, keeps only its hash in the STORED
    FORM below, mails the link itself and tells the screen whether the mail
    went, in one sentence. Nothing returns the token: not the invite, not the
    status. A mail that did not go is said, and the invitation can be sent
    again (a fresh token replaces the old one).

    AN INVITATION ISSUED BEFORE THIS (its hash stored bare, its link shown to
    the inviter) can still be ACCEPTED by somebody already signed in as its
    address, and nothing else: the server opens a sign-in only for an
    invitation in the stored form (`opens_a_sign_in`), the rule
    `domain/firm/invite_token` keeps for staff.
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
from core import db_provider
from core.db_provider import privileged_for
from services import sign_in_link
from core.observability import capture_soft_failure

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


# SERVICE ROLE, as in portal_access_service. There is no `core.database`
# module, so the import this replaced raised on every production call and
# no employee could ever be invited, activated or revoked. Service role is
# also what acceptance NEEDS: the accepting employee has no `users` row, so
# the RLS-enforced client would see nothing. Every staff path through here
# has already run rbac() and assert_client_access, and acceptance is scoped
# by the sha256 of a single-use token.
_db = db_provider.service_db


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


#: What marks an invitation the SERVER mailed and returned to nobody (POST-A-552). The column held the bare sha256 hex
#: before; hex never contains a colon, so the prefix tells the two apart with no migration.
STORED_PREFIX = "mailed:"


def stored_form(token: str) -> str:
    """What `portal_invite_token_hash` holds for an invitation issued now."""
    return STORED_PREFIX + token_hash(token)


def opens_a_sign_in(invite: dict) -> bool:
    """Whether the server may open a sign-in from this invitation's bare token: only one it mailed itself and
    returned to nobody. One issued before POST-A-552 was shown to the member of staff who sent it."""
    value = invite.get("portal_invite_token_hash")
    return isinstance(value, str) and value.startswith(STORED_PREFIX)


def _lookup_values(token: str) -> list[str]:
    """The column values a presented token matches: its stored form, and its bare hash for an invitation issued
    before POST-A-552. Nothing for an empty value."""
    if not token or not isinstance(token, str):
        return []
    return [stored_form(token), token_hash(token)]


#: What the payroll screen is told when the invitation's mail did not go. The invitation exists either way.
MAIL_NOT_SENT = ("The invitation was created, but the email could not be sent: the mail service did not accept it. "
                 "Send the invitation again; if it fails again, this deployment's mail is not reaching the mail service.")


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
        rows = (privileged_for(db).table("payroll_employees").select("*")
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
    rows = (privileged_for(db).table("payroll_employees").update(fields)
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
    except Exception as swallowed:
        capture_soft_failure(swallowed, operation="employee_portal.audit", firm_id=firm_id, employee_id=employee_id)


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

    THE TOKEN IS RETURNED TO NOBODY (POST-A-552; the module's header says why).
    It goes into the one mail the server sends, and the answer says whether
    that mail went (`mail`: `sent`, and one sentence when it did not).
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
        "portal_invite_token_hash": stored_form(token),
        "portal_invite_expires_at": (datetime.now(timezone.utc) + _INVITE_TTL).isoformat(),
        "portal_invited_at": _now(),
        "portal_invited_by": (actor or {}).get("auth_user_id"),
        # Access stays OFF until the invite is accepted. Setting it here would
        # hand out access to anyone who later guessed the auth link.
        "portal_enabled": False,
    }, db)

    _audit(firm_id, employee_id, "employee_portal_invite", actor, {"email": email.strip()})
    # `is True`: only the mail service's own yes is a yes.
    sent = _send_invite_email(email.strip(), employee.get("name") or "", token) is True
    return {"employee_id": employee_id, "email": email.strip(),
            "mail": {"sent": sent, "problem": None if sent else MAIL_NOT_SENT}}


def _send_invite_email(email: str, name: str, token: str) -> bool:
    """Mail the invitation, and say whether the mail service took it. A failed send does not lose the invitation
    (it is saved before this runs and can be sent again), but it is SAID: this mail is now the only place the link
    exists, so a send that failed silently would leave an employee who cannot get in and a screen that says sent."""
    try:
        from html import escape
        from services.email_service import _send
        url = activation_url(token)
        return bool(_send(to=email,
                          subject="Your payslip portal access",
                          html=(f"<p>Hello {escape(name) if name else 'there'},</p>"
                                f"<p>Your employer has given you access to view your payslips "
                                f"and leave balance online.</p>"
                                f'<p><a href="{escape(url, quote=True)}">Activate your portal access</a></p>'
                                f"<p>This link works once and expires in 14 days. It signs you in, so do not "
                                f"forward this email.</p>")))
    except Exception as swallowed:
        capture_soft_failure(swallowed, operation="employee_portal.invite_email")
        return False


def _find_pending_by_token(token: str, db):
    """A pending invite, looked up by the token's HASH.

    `auth_user_id IS NULL` is part of the query, not a check afterwards: it is
    what stops an already-accepted invite being replayed onto a second identity.
    """
    values = _lookup_values(token)
    if not values:
        return None
    if _USE_MOCK:
        return next((e for e in MOCK_EMPLOYEES
                     if e.get("portal_invite_token_hash") in values and not e.get("auth_user_id")), None)
    rows = (privileged_for(db).table("payroll_employees").select("*")
            .in_("portal_invite_token_hash", values).is_("auth_user_id", "null")
            .limit(1).execute().data or [])
    return rows[0] if rows else None


_INVALID_INVITE = HTTPException(status_code=404, detail="Invalid or expired invite.")


def _pending_unexpired_invite(token: str, db) -> Optional[dict]:
    """The invite `token` names, if it is still pending AND not past its
    expiry — the two checks `accept_employee_invite` and
    `mint_activation_session` both need before doing anything else with a
    token. Split out so the expiry arithmetic exists once; the two callers
    still raise their own generic error rather than sharing an exception
    instance across requests."""
    invite = _find_pending_by_token(token, db)
    if not invite:
        return None
    expires_at = invite.get("portal_invite_expires_at")
    if not expires_at:
        return None
    exp = (expires_at if isinstance(expires_at, datetime)
           else datetime.fromisoformat(str(expires_at).replace("Z", "+00:00")))
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < datetime.now(timezone.utc):
        return None
    return invite


def mint_activation_session(token: str, db=None) -> dict:
    """Turn a bare, unauthenticated invite token into a real Supabase session
    the FRONTEND can establish for itself — no email round trip, no prior
    session required.

    WHY THIS EXISTS
        The activation page's documented flow was "wait for the magic-link
        session that a Supabase-sent email already established, then present
        the token" — but nothing ever made Supabase send that email: neither
        this endpoint's own emailed link nor the activation URL returned
        alongside it (the "share this link another way" fallback the CA sees
        in PortalAccessModal) carries a Supabase auth hash fragment, because
        neither was ever produced by Supabase's Auth API. Both are bare
        `?token=...` URLs, so `detectSessionInUrl` has nothing to detect and
        the page's own polling times out into "This invitation cannot be
        used" — every time, for both links, regardless of which one is used.

        `PortalAccessModal.tsx`'s `invite()` now ALSO calls
        `supabase.auth.signInWithOtp(...)` from the browser, the same way the
        client portal's `handleSendInvite` does, so the REAL emailed link
        works going forward. This function is what makes the bare token work
        too — the fallback link, and anyone who lands here before that email
        arrives or after it is lost.

    WHAT IT DOES
        Validates the token exactly as `accept_employee_invite` does (pending,
        not expired) — but does NOT consume it or bind anything; only
        `accept_employee_invite` does that, once a real session exists. Then
        asks Supabase's ADMIN API (service role only; there is no client-side
        equivalent) to mint a sign-in link for the invite's OWN email address
        — never a caller-supplied one, for the same reason `sender_type` is
        never taken from a request body elsewhere in this codebase — and
        returns the raw ingredients (`token_hash` + `verification_type`) for
        the browser to redeem with `supabase.auth.verifyOtp({token_hash,
        type})`. That call is the SAME operation `detectSessionInUrl` performs
        automatically when a real magic-link URL is opened; this just supplies
        its inputs directly instead of via a URL hash fragment, using the anon
        key like any other client-side auth call — nothing here bypasses RLS
        on the browser's own eventual session.

        `type="invite"` is tried first because it creates the underlying
        Supabase Auth user on demand, which covers the common case of an
        employee who has never signed in before. It is retried as
        `type="magiclink"` on any failure, which is what a SECOND invite to an
        employee who already has a Supabase identity looks like (activated
        once, revoked, and re-invited — `revoke_employee_portal` clears
        `auth_user_id` and `portal_enabled` but does not delete the
        underlying Supabase user, so `generate_link` would otherwise refuse
        with an "already registered" error type this SDK version does not
        expose a stable code for).

    Every rejection before the Admin API call raises the SAME generic 404
    `accept_employee_invite` does, for the same probing-resistance reason. A
    failure IN the Admin API call is reported separately and honestly — the
    caller already holds a token proven valid, so there is no oracle risk in
    saying the problem is transient rather than folding it into "invalid".
    """
    db = db or (None if _USE_MOCK else _db())
    invite = _pending_unexpired_invite(token, db)
    if not invite:
        raise _INVALID_INVITE
    # Only an invitation the server mailed and returned to nobody opens a sign-in (POST-A-552). One issued before was
    # shown to the member of staff who sent it, and a sign-in opened from that link would make its holder whoever the
    # invitation's address belongs to. The same generic refusal: a different one would say the token is a real one.
    if not opens_a_sign_in(invite):
        raise _INVALID_INVITE

    email = (invite.get("email") or "").strip()
    if not email:
        raise _INVALID_INVITE

    if _USE_MOCK:
        # No Supabase Auth to call in mock/dev mode. The mock auth_user_id
        # mirrors what accept_employee_invite's own mock caller supplies
        # elsewhere in this test suite, so a test exercising the full
        # mint -> verify -> accept sequence has something real to bind.
        return {"token_hash": f"mock-token-hash-{token_hash(token)[:16]}",
                "verification_type": "magiclink", "email": email}

    return sign_in_link.mint(
        db.auth.admin, email,
        refusal="Could not start your sign-in session. Please try again "
                "in a moment, or ask your employer to resend the invitation.")


def accept_employee_invite(token: str, auth_user_id: str, email: str, db=None) -> dict:
    """Bind a Supabase identity to the invited employee.

    Every rejection raises the same 404 with the same message. Distinguishing
    "no such token" from "expired" from "wrong email" would let someone probe
    which tokens exist.
    """
    db = db or (None if _USE_MOCK else _db())
    generic = _INVALID_INVITE
    invite = _pending_unexpired_invite(token, db)
    if not invite:
        raise generic
    if not auth_user_id:
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
