"""
Portal Access service (Phase 4.5.1) — multi-contact portal foundation.

Reuses Supabase auth (no parallel auth system). A client may have MANY portal
contacts (client_portal_users), while the legacy single-user link
(clients.portal_user_id) keeps working — both are resolved here.

Lifecycle: invite (status='invited') → first login binds auth_user_id and flips to
'active' (activation) → deactivate (status='deactivated', loses access). Every CA
mutation is audit-logged. NO staff privilege is ever granted to a portal contact.
"""
import os
import secrets
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.portal_access")

# F22 fix: a portal invite must be explicitly accepted (token presented) within
# this window. Clients check email less frequently than staff, so the window is
# longer than the staff-invite TTL (7 days, routers/identity.py).
_INVITE_TTL = timedelta(days=14)

# Mock stores (mock/dev mode only).
MOCK_PORTAL_CONTACTS: list[dict] = []
# Simulates the legacy clients.portal_user_id link: {auth_user_id: {"client_id","firm_id"}}.
MOCK_LEGACY_PORTAL: dict[str, dict] = {}


def _db():
    from core.supabase_client import get_service_supabase
    return get_service_supabase()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def reset_mock_stores() -> None:  # test helper
    MOCK_PORTAL_CONTACTS.clear()
    MOCK_LEGACY_PORTAL.clear()


def _ctx(contact: dict, legacy: bool = False) -> dict:
    return {
        "client_id": contact["client_id"],
        "firm_id": contact.get("firm_id"),
        "contact_id": None if legacy else contact.get("id"),
        "email": contact.get("email"),
        "name": contact.get("name"),
        "status": "active",
        "legacy": legacy,
    }


# ── Resolution (the heart of get_current_portal_client) ──────────────────────

def _find_all_active_by_auth(auth_user_id: str, db) -> list[dict]:
    """ALL active memberships for an identity (one identity → many clients)."""
    if not auth_user_id:
        return []
    if _USE_MOCK:
        return [c for c in MOCK_PORTAL_CONTACTS
                if c.get("auth_user_id") == auth_user_id and c.get("status") == "active"]
    return (db.table("client_portal_users").select("*")
            .eq("auth_user_id", auth_user_id).eq("status", "active").execute().data or [])


def _legacy_client(auth_user_id: str, db) -> Optional[dict]:
    """Backward-compat: the single legacy clients.portal_user_id link."""
    if not auth_user_id:
        return None
    if _USE_MOCK:
        leg = MOCK_LEGACY_PORTAL.get(auth_user_id)
        return dict(leg) if leg else None
    rows = (db.table("clients").select("id,firm_id")
            .eq("portal_user_id", auth_user_id).eq("portal_enabled", True).limit(1).execute().data or [])
    return {"client_id": rows[0]["id"], "firm_id": rows[0]["firm_id"]} if rows else None


def _find_by_invite_token(token: str, db) -> Optional[dict]:
    """A pending invite awaiting acceptance (F22 fix) — never matches an
    already-bound row, since auth_user_id must still be NULL."""
    if not token:
        return None
    if _USE_MOCK:
        return next((c for c in MOCK_PORTAL_CONTACTS
                     if c.get("invite_token") == token and c.get("status") == "invited"
                     and not c.get("auth_user_id")), None)
    rows = (db.table("client_portal_users").select("*")
            .eq("invite_token", token).eq("status", "invited").is_("auth_user_id", "null")
            .limit(1).execute().data or [])
    return rows[0] if rows else None


def _bind(contact: dict, auth_user_id: str, db) -> None:
    """Activation: bind the Supabase uid to an invited contact. Single-use — the
    invite token is cleared so it cannot be replayed."""
    fields = {
        "auth_user_id": auth_user_id, "status": "active", "activated_at": _now(), "updated_at": _now(),
        "invite_token": None, "invite_expires_at": None,
    }
    if _USE_MOCK:
        contact.update(fields)
        return
    db.table("client_portal_users").update(fields).eq("id", contact["id"]).execute()


def accept_portal_invite(token: str, auth_user_id: str, email: str, db=None) -> dict:
    """Explicitly accept ONE portal invite by its token (F22 fix).

    Previously list_portal_memberships auto-bound ANY client_portal_users row
    whose email matched the caller's Supabase session email, on every single
    portal page load — no token, no expiry, no explicit action by the invitee.
    A recycled or typo'd email address silently inherited that client's portal
    access (invoices, statements, compliance status) on first login. Binding now
    requires presenting the single-use, expiring token the invite email actually
    carries; email is checked too as defense in depth, but the token (a 256-bit
    random secret) is what makes this unforgeable.

    Raises HTTPException(404) for any invalid/expired/mismatched token — kept
    generic so the error can't be used as an oracle to distinguish why it failed.
    """
    db = db or (None if _USE_MOCK else _db())
    invite = _find_by_invite_token(token, db)
    if not invite:
        raise HTTPException(status_code=404, detail="Invalid or expired invite.")
    expires_at = invite.get("invite_expires_at")
    if not expires_at:
        raise HTTPException(status_code=404, detail="Invalid or expired invite.")
    exp = expires_at if isinstance(expires_at, datetime) else datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    if exp < datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="Invalid or expired invite.")
    if (invite.get("email") or "").strip().lower() != (email or "").strip().lower():
        raise HTTPException(status_code=404, detail="Invalid or expired invite.")

    _bind(invite, auth_user_id, db)
    _audit(invite.get("firm_id"), invite["client_id"], invite.get("id"), "portal_invite_accepted",
           {"auth_user_id": auth_user_id, "email": email})
    return _ctx(invite)


def list_portal_memberships(auth_user_id: Optional[str], email: Optional[str], db=None) -> list[dict]:
    """ALL ALREADY-ACTIVE client memberships for a Supabase identity (a person may
    be a portal contact for several clients — a multi-company owner / shared CFO
    sees all of them here). Includes the legacy portal_user_id link.

    Read-only (F22 fix): this used to ALSO auto-bind any pending invite matching
    the email on every call — see accept_portal_invite for the explicit,
    token-gated replacement. A NEW invite must be accepted once (via its token)
    before it appears here; already-active memberships are unaffected."""
    db = db or (None if _USE_MOCK else _db())
    memberships = [_ctx(c) for c in _find_all_active_by_auth(auth_user_id, db)]
    legacy = _legacy_client(auth_user_id, db)
    if legacy and not any(str(m["client_id"]) == str(legacy["client_id"]) for m in memberships):
        memberships.append({"client_id": legacy["client_id"], "firm_id": legacy.get("firm_id"),
                            "contact_id": None, "email": email, "name": None, "status": "active", "legacy": True})
    return memberships


def select_active_membership(memberships: list[dict], requested_client_id: Optional[str] = None):
    """Deterministic, explicit active-client selection (pure). Returns
    (active_context_or_None, needs_selection: bool):
      • no memberships              → (None, False)   — not a portal user
      • requested client_id given   → (matching membership or None, False)  — None = not a member (deny)
      • exactly one membership      → (that membership, False)              — single-client unchanged
      • multiple, none requested    → (None, True)    — caller MUST choose; never implicit."""
    if not memberships:
        return None, False
    if requested_client_id:
        return next((m for m in memberships if str(m["client_id"]) == str(requested_client_id)), None), False
    if len(memberships) == 1:
        return memberships[0], False
    return None, True


# ── CA-side invite lifecycle ─────────────────────────────────────────────────

def _audit(firm_id, client_id, contact_id, action, actor, extra=None):
    try:
        from services.audit_service import log_event
        log_event(firm_id, "client_portal_user", contact_id or client_id, action,
                  actor_id=(actor or {}).get("auth_user_id"), actor_email=(actor or {}).get("email"),
                  new_data={"client_id": client_id, **(extra or {})}, metadata={"source": "portal_access"})
    except Exception:  # pragma: no cover - audit is best-effort
        pass


def _send_invite_email(email: str, client_id: str, firm_id: str, invite_token: str) -> None:
    try:
        from services.email_service import _send
        # F22 fix: previously defaulted to https://.../portal — the legacy,
        # pre-Phase-4.5.1 page that never learned about invite tokens (it only
        # understood ?client=, and its own auto-bind was against the un-tokened
        # clients.portal_user_id link). The token-gated accept-invite flow now
        # lives on a dedicated activation route (POST /api/portal/accept-invite,
        # consumed by portal/activate/page.tsx, which also collects the client's
        # password) — that is the only page this link may point to. A client who
        # re-clicks an already-accepted link there is simply redirected on to
        # their dashboard instead of erroring.
        #
        # NOTE: if PORTAL_BASE_URL is set explicitly in the deployment environment
        # (e.g. Render), it must be updated there too — this default only applies
        # when the env var is unset.
        base = os.environ.get("PORTAL_BASE_URL", "https://caflow-ai.pages.dev/portal/activate")
        link = f"{base}?invite={invite_token}"
        _send(email, "You've been invited to your accountant's client portal",
              f'<p>You have been granted access to your secure client portal.</p>'
              f'<p><a href="{link}">Set up your account</a> — you\'ll choose a password so you can '
              f'sign in any time at practicesync.com/portal/login.</p>'
              f'<p>This link expires in 14 days.</p>')
    except Exception:  # pragma: no cover - email is best-effort
        pass


# client_portal_users carries a live, single-use invite secret (invite_token),
# its expiry, and the internal Supabase auth reference (auth_user_id). The
# frontend's own direct-Supabase read of this table already excludes these
# (apps/web/.../portal/page.tsx:loadContacts) with the same rationale: a
# repeatable read must never hand back a still-valid, replayable credential.
# invite_contact() below is the one deliberate exception — its POST response
# is the one-time channel that hands the freshly-minted token back to the
# inviting CA's own browser so it can immediately build the magic link (see
# that function for why). Every other contact-returning function funnels
# through here so that exception can't spread by accident.
_SENSITIVE_CONTACT_FIELDS = {"invite_token", "invite_expires_at", "auth_user_id"}


def _sanitize_contact(contact: dict) -> dict:
    return {k: v for k, v in contact.items() if k not in _SENSITIVE_CONTACT_FIELDS}


def list_contacts(firm_id: str, client_id: str, db=None) -> list[dict]:
    if _USE_MOCK:
        return [_sanitize_contact(c) for c in MOCK_PORTAL_CONTACTS
                if c.get("firm_id") == firm_id and c.get("client_id") == client_id]
    db = db or _db()
    rows = (db.table("client_portal_users").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .order("created_at", desc=True).execute().data or [])
    return [_sanitize_contact(r) for r in rows]


def get_contact(firm_id: str, contact_id: str, db=None) -> Optional[dict]:
    if _USE_MOCK:
        contact = next((c for c in MOCK_PORTAL_CONTACTS
                        if c.get("id") == contact_id and c.get("firm_id") == firm_id), None)
        return _sanitize_contact(contact) if contact else None
    db = db or _db()
    rows = (db.table("client_portal_users").select("*")
            .eq("id", contact_id).eq("firm_id", firm_id).limit(1).execute().data or [])
    return _sanitize_contact(rows[0]) if rows else None


def _enable_portal(firm_id: str, client_id: str, db) -> None:
    if _USE_MOCK:
        return
    try:
        db.table("clients").update({"portal_enabled": True, "portal_invited_at": _now()}) \
          .eq("id", client_id).eq("firm_id", firm_id).execute()
    except Exception:  # pragma: no cover
        pass


def invite_contact(firm_id: str, client_id: str, email: str, name: Optional[str],
                   actor: Optional[dict] = None, db=None) -> dict:
    """Enable the client's portal and invite a contact (idempotent per email —
    re-inviting a deactivated/existing contact reactivates the invitation)."""
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="A valid email is required.")
    db = db or (None if _USE_MOCK else _db())
    _enable_portal(firm_id, client_id, db)
    e = email.strip().lower()

    existing = None
    if _USE_MOCK:
        existing = next((c for c in MOCK_PORTAL_CONTACTS
                         if c.get("client_id") == client_id and (c.get("email") or "").lower() == e), None)
    else:
        rows = (db.table("client_portal_users").select("*")
                .eq("client_id", client_id).ilike("email", e).limit(1).execute().data or [])
        existing = rows[0] if rows else None

    # F22 fix: a fresh single-use token every time a (re-)invite is issued — also
    # backfills a token for any pre-migration invite that never had one.
    invite_token = secrets.token_urlsafe(32)
    invite_expires_at = (datetime.now(timezone.utc) + _INVITE_TTL).isoformat()

    if existing:
        fields = {"status": "invited", "invited_at": _now(), "deactivated_at": None,
                  "name": name or existing.get("name"), "invited_by": (actor or {}).get("auth_user_id"),
                  "updated_at": _now(), "invite_token": invite_token, "invite_expires_at": invite_expires_at}
        if _USE_MOCK:
            existing.update(fields)
            contact = dict(existing)
        else:
            contact = (db.table("client_portal_users").update(fields)
                       .eq("id", existing["id"]).execute().data or [existing])[0]
    else:
        payload = {"firm_id": firm_id, "client_id": client_id, "email": email.strip(), "name": name,
                   "status": "invited", "invited_by": (actor or {}).get("auth_user_id"), "invited_at": _now(),
                   "invite_token": invite_token, "invite_expires_at": invite_expires_at}
        if _USE_MOCK:
            payload["id"] = str(uuid.uuid4())
            payload["created_at"] = _now()
            MOCK_PORTAL_CONTACTS.append(payload)
            contact = dict(payload)
        else:
            contact = db.table("client_portal_users").insert(payload).execute().data[0]

    _audit(firm_id, client_id, contact.get("id"), "portal_invite", actor, {"email": email})
    _send_invite_email(email, client_id, firm_id, invite_token)
    # Deliberately NOT run through _sanitize_contact(): this response is the
    # one-time channel the inviting CA's own browser uses to build the magic
    # link right now (apps/web/.../portal/page.tsx:handleSendInvite reads
    # res.data.contact.invite_token immediately, never persists it). Every
    # other function in this file returns a sanitized contact so that
    # exception stays confined to this single call.
    return contact


def resend_invite(firm_id: str, contact_id: str, actor: Optional[dict] = None, db=None) -> dict:
    contact = get_contact(firm_id, contact_id, db=db)
    if not contact:
        raise HTTPException(status_code=404, detail="Portal contact not found.")
    if contact.get("status") == "deactivated":
        raise HTTPException(status_code=422, detail="Reactivate the contact (re-invite) instead of resending.")
    # F22 fix: rotate the token on every resend (a stale/leaked link stops working).
    invite_token = secrets.token_urlsafe(32)
    fields = {"invited_at": _now(), "updated_at": _now(), "invite_token": invite_token,
              "invite_expires_at": (datetime.now(timezone.utc) + _INVITE_TTL).isoformat()}
    if _USE_MOCK:
        for c in MOCK_PORTAL_CONTACTS:
            if c.get("id") == contact_id:
                c.update(fields)
    else:
        (db or _db()).table("client_portal_users").update(fields).eq("id", contact_id).eq("firm_id", firm_id).execute()
    _audit(firm_id, contact["client_id"], contact_id, "portal_invite_resend", actor)
    _send_invite_email(contact["email"], contact["client_id"], firm_id, invite_token)
    # Unlike invite_contact(), nothing in the frontend consumes this response's
    # token today — the new one is delivered by email only. Sanitize so it
    # can't leak if a future caller reads the response instead of the inbox.
    return _sanitize_contact({**contact, **fields})


def deactivate_contact(firm_id: str, contact_id: str, actor: Optional[dict] = None, db=None) -> dict:
    contact = get_contact(firm_id, contact_id, db=db)
    if not contact:
        raise HTTPException(status_code=404, detail="Portal contact not found.")
    fields = {"status": "deactivated", "deactivated_at": _now(), "updated_at": _now()}
    if _USE_MOCK:
        for c in MOCK_PORTAL_CONTACTS:
            if c.get("id") == contact_id:
                c.update(fields)
    else:
        (db or _db()).table("client_portal_users").update(fields).eq("id", contact_id).eq("firm_id", firm_id).execute()
    _audit(firm_id, contact["client_id"], contact_id, "portal_deactivate", actor)
    return _sanitize_contact({**contact, **fields})
