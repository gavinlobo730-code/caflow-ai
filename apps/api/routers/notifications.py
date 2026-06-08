from fastapi import APIRouter, Depends
from models.common import api_response
from core.permissions import rbac
from repositories.notifications_repository import notifications_repo

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    unread_only: bool = False,
    current_user: dict = Depends(rbac("notification", "read")),
):
    firm_id = current_user.get("firm_id")
    notifications = notifications_repo.find_all(firm_id=firm_id, unread_only=unread_only)
    return api_response(True, notifications)


@router.get("/count")
def unread_count(current_user: dict = Depends(rbac("notification", "read"))):
    firm_id = current_user.get("firm_id")
    count = notifications_repo.count_unread(firm_id=firm_id)
    return api_response(True, {"unread": count})


@router.patch("/read-all")
def read_all(current_user: dict = Depends(rbac("notification", "write"))):
    firm_id = current_user.get("firm_id")
    count = notifications_repo.mark_all_read(firm_id=firm_id)
    return api_response(True, {"marked_read": count})


@router.patch("/{notification_id}/read")
def read_one(notification_id: str, current_user: dict = Depends(rbac("notification", "write"))):
    firm_id = current_user.get("firm_id")
    notif = notifications_repo.mark_read(notification_id, firm_id=firm_id)
    if notif is None:
        return api_response(False, None, "Notification not found")
    return api_response(True, notif)


@router.get("/stats")
def notification_stats(current_user: dict = Depends(rbac("notification", "read"))):
    firm_id = current_user.get("firm_id")
    stats = notifications_repo.get_stats(firm_id=firm_id)
    return api_response(True, stats)
