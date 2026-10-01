from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access, filter_by_client
from repositories.notifications_repository import notifications_repo

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationCreate(BaseModel):
    type: str
    title: str
    body: str
    severity: str = "info"
    user_id: Optional[str] = None
    client_id: Optional[str] = None
    action_url: Optional[str] = None
    metadata: Optional[dict] = None


class EmailPreferenceIn(BaseModel):
    event_type: str
    email_enabled: bool


def _me(current_user: dict) -> str:
    uid = current_user.get("id")
    if not uid:
        raise HTTPException(status_code=400, detail="Your account could not be resolved.")
    return str(uid)


@router.get("/email-preferences")
def get_email_preferences(current_user: dict = Depends(rbac("notification", "read"))):
    """Which of the practice's own mail THIS person gets, event by event, and
    whether they chose it or it is the event's default (practice_management-03).
    Always the caller's own: there is no user id to pass, so there is nothing to
    tamper with, and a Partner does not edit a colleague's mail."""
    from services import practice_mail_service
    return api_response(True, {"events": practice_mail_service.effective_preferences(
        current_user["firm_id"], _me(current_user))})


@router.put("/email-preferences")
def set_email_preference(body: EmailPreferenceIn,
                         current_user: dict = Depends(rbac("notification", "write"))):
    """Switch one kind of mail on or off for the caller. An event the product
    does not define is refused with a sentence, not stored."""
    from services import practice_mail_service
    me = _me(current_user)
    try:
        practice_mail_service.set_preference(
            current_user["firm_id"], me, body.event_type, body.email_enabled)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return api_response(True, {"events": practice_mail_service.effective_preferences(
        current_user["firm_id"], me)})


@router.get("/email-log")
def get_email_log(limit: int = 50,
                  current_user: dict = Depends(rbac("notification", "read"))):
    """The mails the product sent THIS person, newest first - the answer to
    "why did I not get it?" (a skipped mail is the absence of a row)."""
    from services import practice_mail_service
    return api_response(True, {"sent": practice_mail_service.recent_log(
        current_user["firm_id"], _me(current_user), limit)})


@router.get("")
def list_notifications(
    unread_only: bool = False,
    archived: bool = False,
    type: Optional[str] = None,
    limit: int = 50,
    current_user: dict = Depends(rbac("notification", "read")),
):
    firm_id = current_user.get("firm_id")
    user_id = current_user.get("id")
    notifications = notifications_repo.find_all(
        firm_id=firm_id,
        user_id=user_id,
        unread_only=unread_only,
        archived=archived,
        notification_type=type,
        limit=limit,
    )
    # M2: notifications.client_id is nullable (migration 004) — a notification
    # ABOUT a client the caller is no longer assigned to should stop being
    # readable, the same rule the underlying record obeys. filter_by_client
    # keeps client-less (firm-level) notifications. unread_count below is a
    # bare tally that names no client, so it is left as the recipient's own.
    notifications = filter_by_client(current_user, notifications)
    unread_count = notifications_repo.count_unread(firm_id=firm_id, user_id=user_id)
    return api_response(True, {
        "notifications": notifications,
        "total": len(notifications),
        "unread_count": unread_count,
    })


@router.get("/count")
def unread_count(current_user: dict = Depends(rbac("notification", "read"))):
    firm_id = current_user.get("firm_id")
    user_id = current_user.get("id")
    count = notifications_repo.count_unread(firm_id=firm_id, user_id=user_id)
    return api_response(True, {"unread": count})


@router.patch("/read-all")
def read_all(current_user: dict = Depends(rbac("notification", "write"))):
    firm_id = current_user.get("firm_id")
    user_id = current_user.get("id")
    count = notifications_repo.mark_all_read(firm_id=firm_id, user_id=user_id)
    return api_response(True, {"marked_read": count})


@router.patch("/{notification_id}/read")
def read_one(notification_id: str, current_user: dict = Depends(rbac("notification", "write"))):
    firm_id = current_user.get("firm_id")
    # M2: scope to the recipient so a user cannot mark another user's notification.
    notif = notifications_repo.mark_read(notification_id, firm_id=firm_id, user_id=current_user.get("id"))
    if notif is None:
        return api_response(False, None, "Notification not found")
    return api_response(True, notif)


@router.patch("/{notification_id}/archive")
def archive_one(notification_id: str, current_user: dict = Depends(rbac("notification", "write"))):
    firm_id = current_user.get("firm_id")
    notif = notifications_repo.archive(notification_id, firm_id=firm_id, user_id=current_user.get("id"))
    if notif is None:
        return api_response(False, None, "Notification not found")
    return api_response(True, notif)


@router.post("")
def create_notification(body: NotificationCreate, current_user: dict = Depends(rbac("notification", "write"))):
    firm_id = current_user.get("firm_id")
    # M2: body.client_id was written straight into the row with no check —
    # this router carries no mount-level client guard at all, so an unassigned
    # caller could plant a notification against another staff member's client.
    # A no-op when client_id is None (a firm-level notification).
    assert_client_access(current_user, body.client_id)
    notif = notifications_repo.create({
        "firm_id": firm_id,
        "type": body.type,
        "title": body.title,
        "body": body.body,
        "severity": body.severity,
        "user_id": body.user_id,
        "client_id": body.client_id,
        "action_url": body.action_url,
        "metadata": body.metadata,
        "is_read": False,
        "is_archived": False,
    })
    return api_response(True, {"notification": notif})


@router.get("/stats")
def notification_stats(current_user: dict = Depends(rbac("notification", "read"))):
    firm_id = current_user.get("firm_id")
    stats = notifications_repo.get_stats(firm_id=firm_id)
    return api_response(True, stats)
