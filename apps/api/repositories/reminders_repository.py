import os
from typing import Optional
from repositories.base import BaseRepository

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from mock_data import MOCK_REMINDERS
    _MOCK_STORE: list[dict] = list(MOCK_REMINDERS)


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class RemindersRepository(BaseRepository[dict]):

    def find_all(
        self,
        firm_id: Optional[str] = None,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[dict]:
        if _USE_MOCK:
            rows = list(_MOCK_STORE)
            if client_id:
                rows = [r for r in rows if r.get("client_id") == client_id]
            if status:
                rows = [r for r in rows if r.get("status") == status]
            return rows
        query = _get_db().table("reminders").select("*")
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if client_id:
            query = query.eq("client_id", client_id)
        if status:
            query = query.eq("status", status)
        result = query.order("scheduled_for").execute()
        return result.data or []

    def find_by_id(self, id: str) -> Optional[dict]:
        if _USE_MOCK:
            return next((r for r in _MOCK_STORE if r["id"] == id), None)
        result = _get_db().table("reminders").select("*").eq("id", id).maybe_single().execute()
        return result.data

    def create(self, data: dict) -> dict:
        if _USE_MOCK:
            import uuid
            record = {"id": str(uuid.uuid4()), **data, "created_at": self.now_iso(), "updated_at": self.now_iso()}
            _MOCK_STORE.append(record)
            return record
        result = _get_db().table("reminders").insert({**data, "created_at": self.now_iso(), "updated_at": self.now_iso()}).execute()
        return result.data[0]

    def update(self, id: str, data: dict) -> Optional[dict]:
        if _USE_MOCK:
            reminder = self.find_by_id(id)
            if not reminder:
                return None
            reminder.update({**data, "updated_at": self.now_iso()})
            return reminder
        result = _get_db().table("reminders").update({**data, "updated_at": self.now_iso()}).eq("id", id).execute()
        return result.data[0] if result.data else None


reminders_repo = RemindersRepository()
