"""
User capacity repository — weekly capacity hours and concurrent task limits
per user, used by the workload engine for utilisation and overload detection.
"""
import os
from typing import Optional
from repositories.base import BaseRepository

_USE_MOCK = not os.environ.get("SUPABASE_URL")

# In-memory store for mock mode (tests / local dev without Supabase)
_MOCK_CAPACITY: list[dict] = []

DEFAULT_WEEKLY_HOURS = 40
DEFAULT_MAX_TASKS = 15


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class CapacityRepository(BaseRepository[dict]):

    def find_all(self, firm_id: Optional[str] = None, **filters) -> list[dict]:
        if _USE_MOCK:
            rows = list(_MOCK_CAPACITY)
            if firm_id:
                rows = [r for r in rows if r.get("firm_id") == firm_id]
            return rows
        query = _get_db().table("user_capacity").select("*")
        if firm_id:
            query = query.eq("firm_id", firm_id)
        result = query.execute()
        return result.data or []

    def find_for_user(self, firm_id: str, user_id: str) -> Optional[dict]:
        if _USE_MOCK:
            for r in _MOCK_CAPACITY:
                if r.get("firm_id") == firm_id and r.get("user_id") == user_id:
                    return r
            return None
        result = (
            _get_db().table("user_capacity").select("*")
            .eq("firm_id", firm_id).eq("user_id", user_id)
            .maybe_single().execute()
        )
        return result.data

    def upsert(self, firm_id: str, user_id: str, data: dict) -> dict:
        """Create or update a user's capacity row (one per firm/user pair)."""
        payload = {
            "weekly_capacity_hours": data.get("weekly_capacity_hours", DEFAULT_WEEKLY_HOURS),
            "max_concurrent_tasks": data.get("max_concurrent_tasks", DEFAULT_MAX_TASKS),
            "updated_by": data.get("updated_by"),
            "updated_at": self.now_iso(),
        }
        if _USE_MOCK:
            existing = self.find_for_user(firm_id, user_id)
            if existing:
                existing.update(payload)
                return existing
            import uuid
            record = {
                "id": str(uuid.uuid4()),
                "firm_id": firm_id,
                "user_id": user_id,
                "created_at": self.now_iso(),
                **payload,
            }
            _MOCK_CAPACITY.append(record)
            return record
        result = (
            _get_db().table("user_capacity")
            .upsert({"firm_id": firm_id, "user_id": user_id, **payload}, on_conflict="firm_id,user_id")
            .execute()
        )
        return result.data[0] if result.data else {}

    def capacity_map(self, firm_id: str) -> dict[str, dict]:
        """Map of user_id -> capacity row for a firm (defaults applied by caller)."""
        return {r["user_id"]: r for r in self.find_all(firm_id=firm_id)}


capacity_repo = CapacityRepository()
