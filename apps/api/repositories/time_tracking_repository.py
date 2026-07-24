from typing import Optional
from datetime import datetime, timezone
from repositories.base import BaseRepository


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class TimeTrackingRepository(BaseRepository[dict]):

    def find_all(
        self,
        firm_id: str,
        user_id: Optional[str] = None,
        client_id: Optional[str] = None,
        task_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list[dict]:
        query = _get_db().table("time_entries").select("*").eq("firm_id", firm_id)
        if user_id:
            query = query.eq("user_id", user_id)
        if client_id:
            query = query.eq("client_id", client_id)
        if task_id:
            query = query.eq("task_id", task_id)
        if date_from:
            query = query.gte("started_at", f"{date_from}T00:00:00Z")
        if date_to:
            query = query.lte("started_at", f"{date_to}T23:59:59Z")
        result = query.order("started_at", desc=True).execute()
        return result.data or []

    def find_running(self, firm_id: str, user_id: str) -> Optional[dict]:
        result = (
            _get_db().table("time_entries")
            .select("*")
            .eq("firm_id", firm_id)
            .eq("user_id", user_id)
            .is_("ended_at", None)
            .maybe_single()
            .execute()
        )
        return result.data

    def find_by_id(self, id: str, firm_id: Optional[str] = None) -> Optional[dict]:
        query = _get_db().table("time_entries").select("*").eq("id", id)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        result = query.maybe_single().execute()
        return result.data

    def create(self, data: dict) -> dict:
        result = _get_db().table("time_entries").insert({
            **data,
            "created_at": self.now_iso(),
            "updated_at": self.now_iso(),
        }).execute()
        return result.data[0]

    def update(self, id: str, data: dict, firm_id: Optional[str] = None) -> Optional[dict]:
        query = _get_db().table("time_entries").update({
            **data,
            "updated_at": self.now_iso(),
        }).eq("id", id)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        result = query.execute()
        return result.data[0] if result.data else None

    def delete(self, id: str, firm_id: Optional[str] = None) -> bool:
        query = _get_db().table("time_entries").delete().eq("id", id)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        result = query.execute()
        return len(result.data) > 0

    def get_summary(self, firm_id: str, user_id: Optional[str] = None, client_id: Optional[str] = None) -> dict:
        entries = self.find_all(firm_id=firm_id, user_id=user_id, client_id=client_id)
        completed = [e for e in entries if e.get("ended_at") and e.get("duration_minutes")]
        total_minutes = sum(e["duration_minutes"] for e in completed)
        billable_minutes = sum(e["duration_minutes"] for e in completed if e.get("is_billable"))

        by_client: dict[str, dict] = {}
        by_user: dict[str, dict] = {}
        for e in completed:
            cid = e.get("client_id") or "unknown"
            uid = e.get("user_id") or "unknown"
            if cid not in by_client:
                by_client[cid] = {"client_id": cid, "client_name": None, "minutes": 0}
            by_client[cid]["minutes"] += e["duration_minutes"]
            if uid not in by_user:
                by_user[uid] = {"user_id": uid, "user_name": None, "minutes": 0}
            by_user[uid]["minutes"] += e["duration_minutes"]

        return {
            "total_minutes": total_minutes,
            "billable_minutes": billable_minutes,
            "entries_count": len(completed),
            "by_client": list(by_client.values()),
            "by_user": list(by_user.values()),
        }


time_tracking_repo = TimeTrackingRepository()
