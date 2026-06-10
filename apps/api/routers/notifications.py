from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from models.common import api_response
from core.permissions import rbac
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
    notif = notifications_repo.mark_read(notification_id, firm_id=firm_id)
    if notif is None:
        return api_response(False, None, "Notification not found")
    return api_response(True, notif)


@router.patch("/{notification_id}/archive")
def archive_one(notification_id: str, current_user: dict = Depends(rbac("notification", "write"))):
    firm_id = current_user.get("firm_id")
    notif = notifications_repo.archive(notification_id, firm_id=firm_id)
    if notif is None:
        return api_response(False, None, "Notification not found")
    return api_response(True, notif)


@router.post("")
def create_notification(body: NotificationCreate, current_user: dict = Depends(rbac("notification", "write"))):
    firm_id = current_user.get("firm_id")
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
