"""Every platform sign-in and every platform action is told by mail to the people on the platform list (POST-B-351, lock 6).

The platform pages can suspend, delete or permanently remove a whole firm. The owner asked on 25-11-2026 to hear of every
visit and every action, so that a session he did not start is noticed the same day. Two kinds of notice:

* A SIGN-IN is the first platform request of a sign-in session (the token's `session_id`, or its `iat` where a token has
  none). It is recorded once in `platform_audit` as `platform_sign_in`, and the mail goes out once per session. Which
  sessions have been told is also remembered in this process, so a page that reads five lists does not read the audit
  table five times; a restart forgets that, and the audit table answers instead.
* An ACTION (suspend, unsuspend, soft delete, permanent delete) is told after it has been done, with the firm's name.

WHO IS TOLD: every address on the platform list (`platform_admins.email`). There is no second setting to keep in step:
the people who can act are the people who are told. A row with no address is skipped and logged.

A MAIL THAT FAILS DOES NOT STOP THE ACTION, and that is a decision. The mail is an alarm, not a lock: the locks are the
platform list, the second factor and the fresh code. Refusing every platform page while the mail provider is down would
leave the owner unable to suspend a firm in exactly the moment he might need to. A failure is logged at ERROR and the
audit row says the mail did not go.

Everything here runs on a thread of its own (`later`), so a slow mail provider does not slow the page, and a request
that is REFUSED or FAILS still mails: FastAPI runs a response's background tasks only when the route returns normally,
so a refused first request, or a purge whose own audit row failed, would have told nobody (the independent review of
27-11-2026).
"""
from __future__ import annotations

import html
import logging
import threading
from typing import Optional

from core.ist_clock import ist_now

_logger = logging.getLogger("caflow.platform")

_told_sessions: set[str] = set()
_told_lock = threading.Lock()

# The words of the four actions as a person reads them. A key not here is a programming error, not a new action.
ACTION_WORDS = {
    "platform_suspend": "suspended",
    "platform_unsuspend": "reopened (unsuspended)",
    "platform_delete": "deleted (soft delete: its records are kept)",
    "platform_purge": "PERMANENTLY deleted, with all of its data",
}


def later(fn, *args, **kwargs) -> None:
    """Run one notice on a daemon thread. The notices never raise, so the thread needs nothing around it."""
    threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True, name="platform-notice").start()


def session_key(jwt_user: dict) -> Optional[str]:
    """What names this sign-in session: the token's `session_id`, or its `iat` where it carries none; None if neither."""
    claims = jwt_user.get("session_claims") or {}
    if claims.get("session_id"):
        return f"session:{claims['session_id']}"
    if claims.get("iat") is not None:
        return f"iat:{jwt_user.get('auth_user_id', '')}:{claims['iat']}"
    return None


def _recipients(db) -> list[str]:
    rows = db.table("platform_admins").select("email").execute().data or []
    out = sorted({(r.get("email") or "").strip() for r in rows} - {""})
    if len(out) < len(rows):
        _logger.error("a platform administrator has no email address on the platform list; they are not told of platform activity")
    return out


def _when() -> str:
    return ist_now().strftime("%d %b %Y, %H:%M IST")


def _send_to_all(db, subject: str, body_html: str) -> bool:
    from services import email_service
    recipients = _recipients(db)
    if not recipients:
        _logger.error("no platform administrator has an email address; platform notice not sent: %s", subject)
        return False
    sent = True
    for to in recipients:
        if not email_service._send(to, subject, body_html):
            sent = False
            _logger.error("platform notice could not be mailed to a platform administrator: %s", subject)
    return sent


def _transitional_line(admin: dict) -> str:
    if not admin.get("platform_transitional"):
        return ""
    return ("<p><strong>This account is also a member of a firm.</strong> That is allowed only until an account that "
            "belongs to no firm is on the platform list; from then on, an account that belongs to a firm is refused.</p>")


def note_visit(admin: dict, address: Optional[str]) -> None:
    """Record and mail the first platform request of a sign-in session. Never raises."""
    key = session_key(admin)
    with _told_lock:
        # CLAIMED before any read (the independent review of 27-11-2026): the page reads three lists at once, so three
        # first requests arrive together, and a check-then-add let all three mail.
        if key and key in _told_sessions:
            return
        if key:
            _told_sessions.add(key)
    try:
        from core.supabase_client import get_service_supabase
        db = get_service_supabase()
        if key:
            seen = (db.table("platform_audit").select("id").eq("action", "platform_sign_in")
                    .contains("metadata", {"session": key}).limit(1).execute().data) or []
            if seen:
                return
        when = _when()
        who = html.escape(admin.get("email") or "an account with no email address")
        where = html.escape(address or "an address the server could not read")
        body = (f"<p>The platform administration pages were opened by <strong>{who}</strong> at {when}, "
                f"from {where}.</p>"
                f"{_transitional_line(admin)}"
                "<p>If this was not you, change that account's password and its authenticator straight away, and "
                "remove it from the platform list.</p>")
        mailed = _send_to_all(db, "PracticeSync platform: a sign-in to the administration pages", body)
        db.table("platform_audit").insert({
            "action": "platform_sign_in",
            "actor_auth_user_id": admin.get("auth_user_id") or None,
            "actor_email": admin.get("email"),
            "metadata": {"session": key, "address": address, "mailed": mailed,
                         "belongs_to_a_firm": bool(admin.get("platform_transitional"))},
        }).execute()
    except Exception:                                    # noqa: BLE001 — an alarm that failed is logged, never raised into a page
        _logger.error("could not record or mail a platform sign-in", exc_info=True)


def note_action(admin: dict, action: str, firm_id: str, firm_name: Optional[str], detail: Optional[str] = None,
                record: bool = True) -> None:
    """Mail one platform action and, unless the caller has written its own row, record it in `platform_audit`. Never raises."""
    words = ACTION_WORDS[action]
    try:
        from core.supabase_client import get_service_supabase
        db = get_service_supabase()
        name = html.escape(firm_name or "a firm whose name could not be read")
        who = html.escape(admin.get("email") or "an account with no email address")
        extra = f"<p>{html.escape(detail)}</p>" if detail else ""
        body = (f"<p>The firm <strong>{name}</strong> was {words} by <strong>{who}</strong> at {_when()}.</p>"
                f"{extra}{_transitional_line(admin)}"
                "<p>If this was not you, sign in to the platform pages, reverse what can be reversed, and change that "
                "account's password and authenticator.</p>")
        mailed = _send_to_all(db, f"PracticeSync platform: a firm was {words.split(' ')[0]}", body)
        if record:
            db.table("platform_audit").insert({
                "action": action, "target_firm_id": firm_id, "firm_name": firm_name,
                "actor_auth_user_id": admin.get("auth_user_id") or None, "actor_email": admin.get("email"),
                "metadata": {"mailed": mailed, **({"detail": detail} if detail else {})},
            }).execute()
    except Exception:                                    # noqa: BLE001 — as above
        _logger.error("could not mail or record platform action %s on firm %s", action, firm_id, exc_info=True)
