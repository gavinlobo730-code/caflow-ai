"""A member of staff asks a Partner for a permission they do not hold, and an approval writes it (POST-A-543).

WHAT IT IS FOR
    The owner's rule of 21-11-2026 is that the permissions a Partner ticks decide what a person sees on the menu and can
    open, and the page that says "this is not part of your access" used to end there: the person had to find a Partner
    and say which screen. The owner asked for a Request access button. Pressing it raises a request of this type; a
    Partner sees it in Approvals; approving it writes that one permission for that one person, exactly as the Team
    screen's Permissions tab would have.

IT CALLS THE FUNCTION THE TEAM SCREEN CALLS
    The approved act is `user_permission_service.set_permissions`, the function `PUT /api/identity/users/{id}/permissions`
    calls, with the approving Partner as the person who granted it, and it writes the same audit entry that route writes.
    The approval engine once carried handlers that wrote the repository directly and skipped what the direct route asked
    first (`approval_service`'s header); this one cannot skip a check the route makes, because it has no write of its own.

WHO MAY ASK, AND FOR WHAT
    Any member of staff, a Reviewer included: the request has its own door (`POST /api/approvals/access-requests`), because
    the engine's general door asks a permission a Reviewer does not hold. A Partner is not asked to raise one: a Partner
    changes access on the Team screen. What may be asked for is any permission the server knows EXCEPT the ones a request
    must never grant: the firm's own practice and its fee billing (My practice is a Partner's alone, the owner's
    decision), and the permissions that change what OTHER people may do (`PRIVILEGE_CHANGING`). A person who already
    holds it is told so. One request per person per permission may be waiting at a time.

WHO MAY DECIDE
    A Partner, and never the person who asked. `approval:approve` can be ticked for somebody who is not a Partner, so the
    route's guard alone does not make the decider a Partner; this module asks the role. The second factor is the route's.

THE ASKER LEARNS THE OUTCOME
    The asker cannot read the approvals inbox. `mine()` answers their own requests of this type (the page that refused
    them shows "waiting" or what was decided), and a notification is written to them when a Partner decides. Partners are
    notified when a request is made. A notification that cannot be written never undoes the request or the decision.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from core.permissions import PRIVILEGE_CHANGING, can_user, canonical_role, is_known_permission
from repositories.approval_repository import approval_repo
from repositories.user_repository import user_repo
from services.audit_service import log_event

logger = logging.getLogger(__name__)

REQUEST_TYPE = "access_request"

#: Never grantable through a request: My practice is a Partner's alone (the owner's decision of 21-11-2026), and the
#: server decides it by the role, so a tick would open nothing and promise something.
NOT_REQUESTABLE_RESOURCES = frozenset({"practice", "billing"})

NOTE_MAX = 300
SCREEN_MAX = 80


def _is_partner(user: dict) -> bool:
    return canonical_role(user.get("role")) == "Partner"


def _name(member: dict) -> str:
    return (member.get("full_name") or member.get("email") or "this person").strip() or "this person"


def _member(firm_id: str, user_id) -> Optional[dict]:
    if not isinstance(user_id, str) or not user_id.strip():
        return None
    return user_repo.find_by_id(user_id, firm_id=firm_id)


def _plain(raw, limit: int) -> str:
    """Somebody's own words, kept as one line of plain text and bounded: they are shown to a Partner, never acted on."""
    return " ".join(str(raw or "").split())[:limit]


def requestable(resource: str, action: str) -> bool:
    """Whether a request may ask for this permission at all."""
    return (is_known_permission(resource, action)
            and resource not in NOT_REQUESTABLE_RESOURCES
            and (resource, action) not in PRIVILEGE_CHANGING)


def _waiting(firm_id: str, user_id: str, resource: str, action: str) -> list[dict]:
    return [r for r in approval_repo.pending_with_payload(firm_id, REQUEST_TYPE, "user_id", user_id)
            if (r.get("payload") or {}).get("resource") == resource and (r.get("payload") or {}).get("action") == action]


def prepare(firm_id: str, payload: dict, asker: dict) -> dict:
    """Validate a request when it is made and return the payload that is STORED: the server's facts about who is asking
    for what, with the asker's own note beside them."""
    resource, action = payload.get("resource"), payload.get("action")
    if not isinstance(resource, str) or not isinstance(action, str) or not is_known_permission(resource, action):
        raise HTTPException(422, "Say which permission you are asking for.")
    if canonical_role(asker.get("role")) not in ("Partner", "Manager", "Executive", "Reviewer"):
        raise HTTPException(403, "Only a member of the firm's staff can ask for access.")
    if _is_partner(asker):
        raise HTTPException(409, "You are a Partner, so nobody needs to approve this: switch it on for yourself from "
                                 "Team, under Permissions.")
    if resource in NOT_REQUESTABLE_RESOURCES:
        raise HTTPException(403, "My practice holds the firm's own books, fees and revenue and is open to Partners only. "
                                 "It cannot be asked for.")
    if (resource, action) in PRIVILEGE_CHANGING:
        raise HTTPException(403, "This permission changes what other people in the firm may do, so it is not given through "
                                 "a request. Speak to a Partner, who can set it from Team, under Permissions.")
    if can_user(asker, resource, action):
        raise HTTPException(409, "You already have this access. If the screen still refuses you, reload the page.")
    if not asker.get("id") or _member(firm_id, asker.get("id")) is None:
        raise HTTPException(403, "Only a member of the firm's staff can ask for access.")
    if _waiting(firm_id, asker["id"], resource, action):
        raise HTTPException(409, "You have already asked for this, and a Partner has not decided yet.")
    partners = [m for m in user_repo.find_all(firm_id=firm_id)
                if canonical_role(m.get("role")) == "Partner" and m.get("is_active") is not False and m.get("auth_user_id")]
    if not partners:
        raise HTTPException(409, "There is no active Partner to decide this request.")
    return {
        "user_id": asker["id"], "user_name": _name(asker), "user_email": asker.get("email"), "user_role": canonical_role(asker.get("role")),
        "resource": resource, "action": action,
        # The asker's own words, shown to the Partner as such: the screen they were on, and why they are asking.
        "asked_from": _plain(payload.get("asked_from"), SCREEN_MAX),
        "note": _plain(payload.get("note"), NOTE_MAX),
    }


def summary(payload: dict) -> str:
    who = f"{payload.get('user_name')} ({payload.get('user_email')})" if payload.get("user_email") else payload.get("user_name")
    where = f" (asked from {payload.get('asked_from')})" if payload.get("asked_from") else ""
    return f"{who} asks for access: {payload.get('resource')} {payload.get('action')}{where}"


def check_decider(firm_id: str, request: dict, decider: dict) -> None:
    """Refuse, before anything is claimed, a decision by somebody who is not a Partner or who made the request."""
    if not _is_partner(decider):
        raise HTTPException(403, "Only a Partner can decide a request for access.")
    if decider.get("id") and decider.get("id") in (request.get("requested_by"), (request.get("payload") or {}).get("user_id")):
        raise HTTPException(403, "You cannot approve a request for your own access. Another Partner has to.")


def execute(firm_id: str, payload: dict, decider: dict) -> dict:
    """The approved act: allow that one permission for that one person, through the function the Team screen calls."""
    from core.supabase_client import get_service_supabase
    from services.user_permission_service import PermissionWriteRefused, set_permissions

    resource, action = payload.get("resource"), payload.get("action")
    if not isinstance(resource, str) or not isinstance(action, str) or not requestable(resource, action):
        raise HTTPException(409, "This permission can no longer be given through a request. Reject it.")
    member = _member(firm_id, payload.get("user_id"))
    if member is None:
        raise HTTPException(409, "The person who asked is no longer a member of this firm, so nothing was changed. "
                                 "Reject this request.")
    if member.get("is_active") is False:
        raise HTTPException(409, f"{_name(member)} has been suspended since this was asked, so nothing was changed. "
                                 "Reject this request.")
    try:
        set_permissions(get_service_supabase(), firm_id, member, {f"{resource}:{action}": True}, decider.get("id"))
    except PermissionWriteRefused as exc:
        raise HTTPException(409, f"{exc} Reject this request.") from exc
    return {"user_id": member["id"], "granted": f"{resource}:{action}"}


def audit_extra(request: dict, result: dict, decider: dict) -> dict:
    payload = request.get("payload") or {}
    return {"target_user_id": payload.get("user_id"), "target_email": payload.get("user_email"), "granted": result.get("granted")}


def _notify(firm_id: str, user_id, title: str, body: str, request: dict) -> None:
    """One in-app notification. It never raises: a notice that could not be written does not undo what it is about."""
    if not user_id:
        return
    try:
        from repositories.notifications_repository import notifications_repo
        notifications_repo.create({
            "firm_id": firm_id, "user_id": user_id, "type": "status_changed", "severity": "info",
            "title": title, "body": body, "is_read": False, "is_archived": False,
            "metadata": {"approval_request_id": request.get("id"), "request_type": REQUEST_TYPE},
        })
    except Exception:  # noqa: BLE001 - reported, and the request or decision it describes stands
        logger.warning("access request %s: a notification could not be written", request.get("id"), exc_info=True)


def after_create(firm_id: str, request: dict, asker: dict) -> None:
    """Tell the firm's Partners there is something to decide."""
    payload = request.get("payload") or {}
    for partner in user_repo.find_all(firm_id=firm_id):
        if canonical_role(partner.get("role")) == "Partner" and partner.get("is_active") is not False:
            _notify(firm_id, partner.get("id"), f"{payload.get('user_name')} asks for access",
                    f"{request.get('summary')}. Decide it in Approvals.", request)


def after_approval(firm_id: str, request: dict, result: dict, decider: dict) -> None:
    """The same record the Team screen's save leaves against the person's permissions, and a word to the asker."""
    payload = request.get("payload") or {}
    log_event(firm_id, "user_permissions", str(result.get("user_id")), "update",
              actor_id=decider.get("auth_user_id"), actor_email=decider.get("email"),
              new_data={"changes": {result.get("granted"): True}, "by_access_request": request.get("id")})
    _notify(firm_id, payload.get("user_id"), "Your request for access was approved",
            f"{_name(decider)} allowed: {payload.get('resource')} {payload.get('action')}. Reload the page to see it.", request)


def after_rejection(firm_id: str, request: dict, decider: dict, reason: Optional[str]) -> None:
    payload = request.get("payload") or {}
    why = f" Reason given: {_plain(reason, NOTE_MAX)}" if _plain(reason, NOTE_MAX) else ""
    _notify(firm_id, payload.get("user_id"), "Your request for access was declined",
            f"{_name(decider)} declined: {payload.get('resource')} {payload.get('action')}.{why}", request)


def mine(firm_id: str, user: dict) -> list[dict]:
    """The caller's own requests for access, newest first: what is waiting, and what a Partner decided. Only what the
    asker may know about their own request is answered (never who else asked, or the inbox)."""
    out = []
    for r in approval_repo.by_requester(firm_id, REQUEST_TYPE, user.get("id")):
        payload = r.get("payload") or {}
        out.append({
            "id": r.get("id"), "resource": payload.get("resource"), "action": payload.get("action"),
            "status": r.get("status"), "asked_at": r.get("created_at"), "decided_at": r.get("decided_at"),
            "reason": r.get("reason") if r.get("status") == "rejected" else None,
        })
    return out
