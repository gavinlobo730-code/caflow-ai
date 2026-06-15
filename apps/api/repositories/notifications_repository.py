import os
import uuid
from datetime import datetime
from typing import Optional
from repositories.base import BaseRepository

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from domain.notification_service import MOCK_NOTIFICATIONS, _notif_index


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class NotificationsRepository(BaseRepository[dict]):

    def find_all(
        self,
        firm_id: Optional[str] = None,
        user_id: Optional[str] = None,
        unread_only: bool = False,
        archived: bool = False,
        notification_type: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        if _USE_MOCK:
            results = list(MOCK_NOTIFICATIONS)
            if unread_only:
                results = [n for n in results if not n["is_read"]]
            return sorted(results, key=lambda n: n["created_at"], reverse=True)[:limit]

        query = _get_db().table("notifications").select("*")
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if user_id:
            # M2: deliver only this user's notifications. Previously OR'd in
            # `user_id IS NULL`, which broadcast NULL-recipient rows (carrying
            # client names) to every user in the firm.
            query = query.eq("user_id", user_id)
        if unread_only:
            query = query.eq("is_read", False)
        if not archived:
            query = query.eq("is_archived", False)
        else:
            query = query.eq("is_archived", True)
        if notification_type:
            query = query.eq("type", notification_type)
        result = query.order("created_at", desc=True).limit(limit).execute()
        return result.data or []

    def count_unread(self, firm_id: Optional[str] = None, user_id: Optional[str] = None) -> int:
        if _USE_MOCK:
            return len([n for n in MOCK_NOTIFICATIONS if not n["is_read"]])
        query = _get_db().table("notifications").select("id", count="exact").eq("is_read", False).eq("is_archived", False)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if user_id:
            query = query.eq("user_id", user_id)  # M2: own notifications only
        result = query.execute()
        return result.count or 0

    def create(self, data: dict) -> dict:
        if _USE_MOCK:
            nid = f"notif-{str(uuid.uuid4())[:8]}"
            notif = {
                "id": nid,
                "is_read": False,
                "created_at": self.now_iso(),
                **data,
            }
            MOCK_NOTIFICATIONS.append(notif)
            _notif_index[nid] = notif
            return notif

        payload = {k: v for k, v in data.items() if v is not None}
        payload["created_at"] = self.now_iso()
        result = _get_db().table("notifications").insert(payload).execute()
        return result.data[0]

    def mark_read(self, notification_id: str, firm_id: Optional[str] = None,
                  user_id: Optional[str] = None) -> Optional[dict]:
        if _USE_MOCK:
            notif = _notif_index.get(notification_id)
            if notif:
                notif["is_read"] = True
            return notif

        query = _get_db().table("notifications").update({"is_read": True}).eq("id", notification_id)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if user_id:
            query = query.eq("user_id", user_id)  # M2: only the recipient may mark their own
        result = query.execute()
        return result.data[0] if result.data else None

    def mark_all_read(self, firm_id: Optional[str] = None, user_id: Optional[str] = None) -> int:
        if _USE_MOCK:
            count = 0
            for n in MOCK_NOTIFICATIONS:
                if not n["is_read"]:
                    n["is_read"] = True
                    count += 1
            return count

        query = _get_db().table("notifications").update({"is_read": True}).eq("is_read", False)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if user_id:
            query = query.eq("user_id", user_id)
        result = query.execute()
        return len(result.data) if result.data else 0

    def archive(self, notification_id: str, firm_id: Optional[str] = None,
                user_id: Optional[str] = None) -> Optional[dict]:
        if _USE_MOCK:
            notif = _notif_index.get(notification_id)
            if notif:
                notif["is_archived"] = True
            return notif

        query = _get_db().table("notifications").update({"is_archived": True, "is_read": True}).eq("id", notification_id)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if user_id:
            query = query.eq("user_id", user_id)  # M2: only the recipient may archive their own
        result = query.execute()
        return result.data[0] if result.data else None

    def get_stats(self, firm_id: Optional[str] = None) -> dict:
        notifications = self.find_all(firm_id=firm_id)
        unread = sum(1 for n in notifications if not n["is_read"])
        by_type: dict[str, int] = {}
        for n in notifications:
            by_type[n["type"]] = by_type.get(n["type"], 0) + 1
        return {"total": len(notifications), "unread": unread, "by_type": by_type}


notifications_repo = NotificationsRepository()
