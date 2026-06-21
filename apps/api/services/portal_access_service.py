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
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.portal_access")

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

def _find_active_by_auth(auth_user_id: str, db) -> Optional[dict]:
    if not auth_user_id:
        return None
    if _USE_MOCK:
        return next((c for c in MOCK_PORTAL_CONTACTS
                     if c.get("auth_user_id") == auth_user_id and c.get("status") == "active"), None)
    rows = (db.table("client_portal_users").select("*")
            .eq("auth_user_id", auth_user_id).eq("status", "active").limit(1).execute().data or [])
    return rows[0] if rows else None


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


def _find_invited_by_email(email: str, db) -> Optional[dict]:
    if not email:
        return None
    e = email.strip().lower()
    if _USE_MOCK:
        return next((c for c in MOCK_PORTAL_CONTACTS
                     if (c.get("email") or "").strip().lower() == e
                     and c.get("status") == "invited" and not c.get("auth_user_id")), None)
    rows = (db.table("client_portal_users").select("*")
            .ilike("email", e).eq("status", "invited").is_("auth_user_id", "null")
            .limit(1).execute().data or [])
    return rows[0] if rows else None


def _bind(contact: dict, auth_user_id: str, db) -> None:
    """Activation: bind the Supabase uid to an invited contact on first login."""
    fields = {"auth_user_id": auth_user_id, "status": "active", "activated_at": _now(), "updated_at": _now()}
    if _USE_MOCK:
        contact.update(fields)
        return
    db.table("client_portal_users").update(fields).eq("id", contact["id"]).execute()


def resolve_portal_client(auth_user_id: Optional[str], email: Optional[str], db=None) -> Optional[dict]:
    """Resolve a Supabase-authenticated identity to a single portal-client context,
    or None if they are not a portal user. Order: active contact → legacy
    portal_user_id → invited-by-email (binds + activates). Pure of HTTP concerns."""
    db = db or (None if _USE_MOCK else _db())
    active = _find_active_by_auth(auth_user_id, db)
    if active:
        return _ctx(active)
    legacy = _legacy_client(auth_user_id, db)
    if legacy:
        return {"client_id": legacy["client_id"], "firm_id": legacy.get("firm_id"),
                "contact_id": None, "email": email, "name": None, "status": "active", "legacy": True}
    invited = _find_invited_by_email(email, db) if email else None
    if invited:
        _bind(invited, auth_user_id, db)
        return _ctx({**invited, "auth_user_id": auth_user_id})
    return None


# ── CA-side invite lifecycle ─────────────────────────────────────────────────

def _audit(firm_id, client_id, contact_id, action, actor, extra=None):
    try:
        from services.audit_service import log_event
        log_event(firm_id, "client_portal_user", contact_id or client_id, action,
                  actor_id=(actor or {}).get("auth_user_id"), actor_email=(actor or {}).get("email"),
                  new_data={"client_id": client_id, **(extra or {})}, metadata={"source": "portal_access"})
    except Exception:  # pragma: no cover - audit is best-effort
        pass


def _send_invite_email(email: str, client_id: str, firm_id: str) -> None:
    try:
        from services.email_service import _send
        base = os.environ.get("PORTAL_BASE_URL", "https://caflow-ai.pages.dev/portal")
        link = f"{base}?client={client_id}"
        _send(email, "You've been invited to your accountant's client portal",
              f'<p>You have been granted access to your secure client portal.</p>'
              f'<p><a href="{link}">Open the portal</a> and sign in with this email to continue.</p>')
    except Exception:  # pragma: no cover - email is best-effort
        pass


def list_contacts(firm_id: str, client_id: str, db=None) -> list[dict]:
    if _USE_MOCK:
        return [dict(c) for c in MOCK_PORTAL_CONTACTS
                if c.get("firm_id") == firm_id and c.get("client_id") == client_id]
    db = db or _db()
    return (db.table("client_portal_users").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .order("created_at", desc=True).execute().data or [])


def get_contact(firm_id: str, contact_id: str, db=None) -> Optional[dict]:
    if _USE_MOCK:
        return next((dict(c) for c in MOCK_PORTAL_CONTACTS
                     if c.get("id") == contact_id and c.get("firm_id") == firm_id), None)
    db = db or _db()
    rows = (db.table("client_portal_users").select("*")
            .eq("id", contact_id).eq("firm_id", firm_id).limit(1).execute().data or [])
    return rows[0] if rows else None


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

    if existing:
        fields = {"status": "invited", "invited_at": _now(), "deactivated_at": None,
                  "name": name or existing.get("name"), "invited_by": (actor or {}).get("auth_user_id"),
                  "updated_at": _now()}
        if _USE_MOCK:
            existing.update(fields)
            contact = dict(existing)
        else:
            contact = (db.table("client_portal_users").update(fields)
                       .eq("id", existing["id"]).execute().data or [existing])[0]
    else:
        payload = {"firm_id": firm_id, "client_id": client_id, "email": email.strip(), "name": name,
                   "status": "invited", "invited_by": (actor or {}).get("auth_user_id"), "invited_at": _now()}
        if _USE_MOCK:
            payload["id"] = str(uuid.uuid4())
            payload["created_at"] = _now()
            MOCK_PORTAL_CONTACTS.append(payload)
            contact = dict(payload)
        else:
            contact = db.table("client_portal_users").insert(payload).execute().data[0]

    _audit(firm_id, client_id, contact.get("id"), "portal_invite", actor, {"email": email})
    _send_invite_email(email, client_id, firm_id)
    return contact


def resend_invite(firm_id: str, contact_id: str, actor: Optional[dict] = None, db=None) -> dict:
    contact = get_contact(firm_id, contact_id, db=db)
    if not contact:
        raise HTTPException(status_code=404, detail="Portal contact not found.")
    if contact.get("status") == "deactivated":
        raise HTTPException(status_code=422, detail="Reactivate the contact (re-invite) instead of resending.")
    fields = {"invited_at": _now(), "updated_at": _now()}
    if _USE_MOCK:
        for c in MOCK_PORTAL_CONTACTS:
            if c.get("id") == contact_id:
                c.update(fields)
    else:
        (db or _db()).table("client_portal_users").update(fields).eq("id", contact_id).eq("firm_id", firm_id).execute()
    _audit(firm_id, contact["client_id"], contact_id, "portal_invite_resend", actor)
    _send_invite_email(contact["email"], contact["client_id"], firm_id)
    return {**contact, **fields}


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
    return {**contact, **fields}
