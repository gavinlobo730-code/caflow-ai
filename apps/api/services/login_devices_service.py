"""Which devices a login is signed in on, who is told when a second appears, and "sign out my other sessions" (POST-A-486).

The rule for "live" and the words are `domain/identity/devices.py`; storage is `repositories/login_sessions_repository.py`. This
is the part that acts: it opens and refreshes a session, tells the Partners in the app (never by mail: the practice's own mail is off
unless the firm switches it on) when a login that already has a live session signs in somewhere else, and ends the other sessions.

Nothing here blocks a sign-in. A recording that fails is logged and the person carries on; the screens that READ the devices say
when they could not read them, they do not show none.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from core import db_provider
from domain.identity import devices
from repositories.login_sessions_repository import login_sessions_repo
from repositories.notifications_repository import notifications_repo
from repositories.user_repository import user_repo

_log = logging.getLogger("caflow.identity.devices")

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_service_db = db_provider.service_db


class MarkNotWritten(Exception):
    """The person's row could not be marked, so no other session was stopped."""


class NoSessionId(Exception):
    """The caller's token carries no sign-in-service session id, so the session cannot be told from the person's others."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _since(now: datetime) -> str:
    return (now - devices.LIVE_WINDOW).isoformat()


def _live_others(firm_id: str, user_id: str, session_id: Optional[str], now: datetime) -> list[dict]:
    rows = login_sessions_repo.open_for_user(firm_id, user_id, _since(now))
    return [r for r in rows if r.get("session_id") != session_id and devices.is_live(r, now)]


def register(current_user: Mapping[str, Any], ip: Optional[str], user_agent: Optional[str],
             now: Optional[datetime] = None) -> dict:
    """Say this session exists and is in use. The first time a session is heard of while the same login has another live one, the
    Partners are told. Idempotent: every later call only refreshes the sighting. Never raises."""
    session_id = current_user.get("session_id")
    firm_id, user_id = current_user.get("firm_id"), current_user.get("id")
    if not (session_id and firm_id and user_id):
        return {"registered": False, "second_device": False}
    moment = now or _now()
    agent = devices.clean_user_agent(user_agent)
    try:
        created = login_sessions_repo.register(firm_id, user_id, session_id, ip, agent, moment.isoformat())
    except Exception:                                                   # noqa: BLE001
        _log.warning("could not record the session of user %s", user_id, exc_info=True)
        return {"registered": False, "second_device": False}
    if not created:
        return {"registered": True, "second_device": False}
    try:
        others = _live_others(firm_id, user_id, session_id, moment)
    except Exception:                                                   # noqa: BLE001
        _log.warning("could not read the other sessions of user %s", user_id, exc_info=True)
        return {"registered": True, "second_device": False}
    if not others:
        return {"registered": True, "second_device": False}
    told = tell_partners(current_user, ip, agent, len(others))
    return {"registered": True, "second_device": True, "others_live": len(others), "partners_told": told}


def tell_partners(member: Mapping[str, Any], ip: Optional[str], user_agent: Optional[str], others_live: int) -> int:
    """One in-app notice to each active Partner of the firm OTHER THAN the member whose login it is (a Partner's own second device is
    on their own Security page; the notice points at Team, where they could not end their own sessions). Returns how many were
    written. Never raises.

    The row is written with the API's privileged client. The notice is addressed to somebody else, and the table's recipient policy
    (migration 084) lets only a Partner, or the recipient, write a row: under the signed-in member's own client an Executive's or a
    Manager's second device would have told nobody, with the failure swallowed below (found by the independent review)."""
    firm_id = member.get("firm_id")
    title, body = devices.second_device_notice(
        member.get("full_name") or member.get("email") or "", devices.browser_label(user_agent), ip, others_live)
    written = 0
    try:
        people = user_repo.find_all(firm_id=firm_id)
    except Exception:                                                   # noqa: BLE001
        _log.warning("could not list the Partners of firm %s to tell them of a second device", firm_id, exc_info=True)
        return 0
    for person in people:
        if person.get("role") != "Partner" or person.get("is_active") is False or not person.get("auth_user_id"):
            continue
        if person.get("id") == member.get("id"):
            continue
        if _already_told(firm_id, person.get("id"), member.get("id")):
            continue
        try:
            notifications_repo.create({
                "firm_id": firm_id,
                "user_id": person.get("id"),
                "type": devices.SECOND_DEVICE_NOTIFICATION_TYPE,
                "title": title,
                "body": body,
                "severity": "medium",
                "metadata": {"member_id": member.get("id")},
                "is_read": False,
                "is_archived": False,
            }, db=None if _USE_MOCK else _service_db())
            written += 1
        except Exception:                                               # noqa: BLE001
            _log.warning("could not write the second-device notice for Partner %s", person.get("id"), exc_info=True)
    return written


def _already_told(firm_id: Optional[str], partner_id: Optional[str], member_id: Optional[str]) -> bool:
    """Whether this Partner already has an UNREAD second-device notice about this member. A member who signs in again and again
    (a phone that signs itself out when idle, a second computer) is told once until the notice is read, so the bell is not trained to
    be ignored. Read with the privileged client, for the reason `tell_partners` writes with it. A failed read answers False: better a
    second notice than none."""
    try:
        rows = notifications_repo.find_all(firm_id=firm_id, user_id=partner_id, unread_only=True,
                                           notification_type=devices.SECOND_DEVICE_NOTIFICATION_TYPE, limit=50,
                                           db=None if _USE_MOCK else _service_db())
    except Exception:                                                   # noqa: BLE001
        return False
    for row in rows or []:
        if (row.get("type") == devices.SECOND_DEVICE_NOTIFICATION_TYPE and row.get("user_id") == partner_id
                and (row.get("metadata") or {}).get("member_id") == member_id and not row.get("is_read")):
            return True
    return False


def end_here(current_user: Mapping[str, Any]) -> None:
    """The person signed out of this session: it is no longer live. Never raises."""
    session_id = current_user.get("session_id")
    firm_id, user_id = current_user.get("firm_id"), current_user.get("id")
    if not (session_id and firm_id and user_id):
        return
    try:
        login_sessions_repo.end(firm_id, user_id, session_id, "signed_out")
    except Exception:                                                   # noqa: BLE001
        _log.warning("could not mark the session of user %s ended", user_id, exc_info=True)


def end_all(firm_id: str, user_id: str, how: str) -> None:
    """Every session of a person was ended on purpose (suspension, forced sign-out). Never raises."""
    try:
        login_sessions_repo.end_all(firm_id, user_id, how)
    except Exception:                                                   # noqa: BLE001
        _log.warning("could not mark the sessions of user %s ended", user_id, exc_info=True)


def devices_of(firm_id: str, user_id: str, *, current_session_id: Optional[str] = None,
               now: Optional[datetime] = None) -> dict:
    """The live devices of one login, in the shape a screen is served. Raises when the read fails: a failed read is not "none"."""
    moment = now or _now()
    rows = login_sessions_repo.open_for_user(firm_id, user_id, _since(moment))
    return devices.summarise(rows, moment, current_session_id=current_session_id)


def devices_of_firm(firm_id: str, members: list[Mapping[str, Any]], *, now: Optional[datetime] = None) -> list[dict]:
    """For each member who is signed in anywhere right now, their live devices. Members with none are left out. Raises on a failed read."""
    moment = now or _now()
    rows = login_sessions_repo.open_for_firm(firm_id, _since(moment))
    by_user: dict[str, list[dict]] = {}
    for row in rows:
        by_user.setdefault(row.get("user_id"), []).append(row)
    out = []
    for member in members:
        summary = devices.summarise(by_user.get(member.get("id"), []), moment)
        if summary["count"]:
            out.append({"user_id": member.get("id"), "name": member.get("full_name") or member.get("email") or "", **summary})
    out.sort(key=lambda m: (-m["count"], (m["name"] or "").lower()))
    return out


def sign_out_other_sessions(current_user: Mapping[str, Any], now: Optional[datetime] = None) -> dict:
    """End every session of the caller's login except the one asking. Raises `NoSessionId` when the token names none (then nothing
    could be kept, and ending "the others" would end this one too).

    The mark on the person's row is written FIRST and is what stops the other sessions' tokens at the API; the session rows are
    closed after, so the screens stop listing them. The sign-in service's own refresh tokens for those sessions are ended by the
    browser (`signOut({scope: "others"})`), which is the only party holding the person's own token for it.
    """
    session_id = current_user.get("session_id")
    if not session_id:
        raise NoSessionId()
    firm_id, user_id = current_user["firm_id"], current_user["id"]
    moment = now or _now()
    before = len(_live_others(firm_id, user_id, session_id, moment))
    written = user_repo.update(user_id, {"other_sessions_revoked_at": moment.isoformat(), "other_sessions_kept_session_id": session_id},
                               firm_id=firm_id)
    if not written:
        # A mark that was not written ends nothing: say so rather than answer success and let the browser go on to end the others.
        raise MarkNotWritten()
    # The lookup the API reads the mark from is cached for 30 seconds in this process: drop the caller's entry so their own
    # next request sees it (the other workers' caches age out on their own).
    try:
        from core.auth import _user_lookup_cache
        _user_lookup_cache.pop(current_user.get("auth_user_id"), None)
    except Exception:                                                   # noqa: BLE001
        _log.warning("could not drop the cached row of user %s; the mark is seen within 30 seconds", user_id, exc_info=True)
    try:
        login_sessions_repo.end_others(firm_id, user_id, session_id, "other_sessions", moment.isoformat())
    except Exception:                                                   # noqa: BLE001
        _log.warning("the mark was written but the session rows of user %s could not be closed", user_id, exc_info=True)
    return {"ended": before}
