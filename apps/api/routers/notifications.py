from fastapi import APIRouter, Depends
from models.common import api_response
from core.auth import get_current_user
from domain.notification_service import (
    get_notifications,
    get_unread_count,
    mark_read,
    mark_all_read,
    get_notification_stats,
)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def list_notifications(unread_only: bool = False, user_id: str = None, current_user: dict = Depends(get_current_user)):
    notifications = get_notifications(user_id=user_id, unread_only=unread_only)
    return api_response(True, notifications)


@router.get("/count")
def unread_count(current_user: dict = Depends(get_current_user)):
    count = get_unread_count()
    return api_response(True, {"unread": count})


@router.patch("/read-all")
def read_all(user_id: str = None, current_user: dict = Depends(get_current_user)):
    count = mark_all_read(user_id=user_id)
    return api_response(True, {"marked_read": count})


@router.patch("/{notification_id}/read")
def read_one(notification_id: str, current_user: dict = Depends(get_current_user)):
    notif = mark_read(notification_id)
    if notif is None:
        return api_response(False, None, "Notification not found")
    return api_response(True, notif)


@router.get("/stats")
def notification_stats(current_user: dict = Depends(get_current_user)):
    stats = get_notification_stats()
    return api_response(True, stats)
