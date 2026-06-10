import os
from typing import Optional
from repositories.base import BaseRepository
from core.exceptions import NotFoundError

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from mock_data import MOCK_ENGAGEMENTS, ENGAGEMENT_INDEX


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class EngagementRepository(BaseRepository[dict]):

    def find_by_id(self, id: str) -> Optional[dict]:
        if _USE_MOCK:
            e = ENGAGEMENT_INDEX.get(id)
            return e if e else None
        result = _get_db().table("fee_engagements").select("*").eq("id", id).maybe_single().execute()
        return result.data

    def find_all(
        self,
        firm_id: Optional[str] = None,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        **filters,
    ) -> list[dict]:
        if _USE_MOCK:
            engagements = list(MOCK_ENGAGEMENTS)
            if firm_id:
                engagements = [e for e in engagements if e.get("firm_id") == firm_id]
            if client_id:
                engagements = [e for e in engagements if e.get("client_id") == client_id]
            if status:
                engagements = [e for e in engagements if e.get("status") == status]
            return engagements

        query = _get_db().table("fee_engagements").select("*")
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if client_id:
            query = query.eq("client_id", client_id)
        if status:
            query = query.eq("status", status)
        result = query.order("created_at", desc=True).execute()
        return result.data or []

    def list_by_status(self, firm_id: str, status: str) -> list[dict]:
        return self.find_all(firm_id=firm_id, status=status)

    def get_or_raise(self, id: str) -> dict:
        engagement = self.find_by_id(id)
        if not engagement:
            raise NotFoundError("Engagement", id)
        return engagement

    def create(self, data: dict) -> dict:
        if _USE_MOCK:
            import uuid
            record = {
                "id": str(uuid.uuid4()),
                **data,
                "created_at": self.now_iso(),
                "updated_at": self.now_iso(),
            }
            MOCK_ENGAGEMENTS.append(record)
            ENGAGEMENT_INDEX[record["id"]] = record
            return record
        result = _get_db().table("fee_engagements").insert({**data, "created_at": self.now_iso(), "updated_at": self.now_iso()}).execute()
        return result.data[0]

    def update(self, id: str, data: dict) -> Optional[dict]:
        if _USE_MOCK:
            engagement = ENGAGEMENT_INDEX.get(id)
            if not engagement:
                return None
            engagement.update({**data, "updated_at": self.now_iso()})
            return engagement
        result = _get_db().table("fee_engagements").update({**data, "updated_at": self.now_iso()}).eq("id", id).execute()
        return result.data[0] if result.data else None

    def soft_delete(self, id: str) -> bool:
        if _USE_MOCK:
            engagement = ENGAGEMENT_INDEX.get(id)
            if not engagement:
                return False
            engagement["updated_at"] = self.now_iso()
            return True
        result = _get_db().table("fee_engagements").update({"updated_at": self.now_iso()}).eq("id", id).execute()
        return bool(result.data)


engagement_repo = EngagementRepository()
