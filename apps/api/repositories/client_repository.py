import os
from typing import Optional
from repositories.base import BaseRepository
from core.exceptions import NotFoundError

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from mock_data import MOCK_CLIENTS, CLIENT_INDEX


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class ClientRepository(BaseRepository[dict]):

    def find_by_id(self, id: str) -> Optional[dict]:
        if _USE_MOCK:
            return CLIENT_INDEX.get(id)
        result = _get_db().table("clients").select("*").eq("id", id).is_("deleted_at", None).maybe_single().execute()
        return result.data

    def find_all(self, firm_id: Optional[str] = None, status: Optional[str] = None, **filters) -> list[dict]:
        if _USE_MOCK:
            clients = list(MOCK_CLIENTS)
            if status:
                clients = [c for c in clients if c.get("status") == status]
            return clients
        query = _get_db().table("clients").select("*").is_("deleted_at", None)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if status:
            query = query.eq("status", status)
        result = query.order("client_name").execute()
        return result.data or []

    def find_by_pan(self, pan: str) -> Optional[dict]:
        if _USE_MOCK:
            return next((c for c in MOCK_CLIENTS if c["pan"] == pan), None)
        result = _get_db().table("clients").select("*").eq("pan", pan).is_("deleted_at", None).execute()
        return result.data[0] if result.data else None

    def find_by_gstin(self, gstin: str) -> Optional[dict]:
        if _USE_MOCK:
            return next((c for c in MOCK_CLIENTS if c.get("gstin") == gstin), None)
        result = _get_db().table("clients").select("*").eq("gstin", gstin).is_("deleted_at", None).execute()
        return result.data[0] if result.data else None

    def get_or_raise(self, id: str) -> dict:
        client = self.find_by_id(id)
        if not client:
            raise NotFoundError("Client", id)
        return client

    def create(self, data: dict) -> dict:
        if _USE_MOCK:
            import uuid
            record = {"id": str(uuid.uuid4()), **data, "created_at": self.now_iso(), "updated_at": self.now_iso()}
            MOCK_CLIENTS.append(record)
            CLIENT_INDEX[record["id"]] = record
            return record
        result = _get_db().table("clients").insert({**data, "created_at": self.now_iso(), "updated_at": self.now_iso()}).execute()
        return result.data[0]

    def update(self, id: str, data: dict) -> Optional[dict]:
        if _USE_MOCK:
            client = CLIENT_INDEX.get(id)
            if not client:
                return None
            client.update({**data, "updated_at": self.now_iso()})
            return client
        result = _get_db().table("clients").update({**data, "updated_at": self.now_iso()}).eq("id", id).execute()
        return result.data[0] if result.data else None

    def soft_delete(self, id: str) -> bool:
        if _USE_MOCK:
            return False
        result = _get_db().table("clients").update({"deleted_at": self.now_iso()}).eq("id", id).execute()
        return bool(result.data)

    def count(self, firm_id: Optional[str] = None) -> int:
        return len(self.find_all(firm_id=firm_id))


client_repo = ClientRepository()
