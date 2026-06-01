from typing import Optional
from repositories.base import BaseRepository
from mock_data import MOCK_CLIENTS, CLIENT_INDEX
from core.exceptions import NotFoundError


class ClientRepository(BaseRepository[dict]):

    def find_by_id(self, id: str) -> Optional[dict]:
        return CLIENT_INDEX.get(id)

    def find_all(self, firm_id: Optional[str] = None, status: Optional[str] = None, **filters) -> list[dict]:
        clients = list(MOCK_CLIENTS)
        if status:
            clients = [c for c in clients if c.get("status") == status]
        return clients

    def find_by_pan(self, pan: str) -> Optional[dict]:
        return next((c for c in MOCK_CLIENTS if c["pan"] == pan), None)

    def find_by_gstin(self, gstin: str) -> Optional[dict]:
        return next((c for c in MOCK_CLIENTS if c.get("gstin") == gstin), None)

    def get_or_raise(self, id: str) -> dict:
        client = self.find_by_id(id)
        if not client:
            raise NotFoundError("Client", id)
        return client

    def create(self, data: dict) -> dict:
        import uuid
        record = {"id": str(uuid.uuid4()), **data, "created_at": self.now_iso(), "updated_at": self.now_iso()}
        MOCK_CLIENTS.append(record)
        CLIENT_INDEX[record["id"]] = record
        return record

    def update(self, id: str, data: dict) -> Optional[dict]:
        client = CLIENT_INDEX.get(id)
        if not client:
            return None
        client.update({**data, "updated_at": self.now_iso()})
        return client

    def count(self, firm_id: Optional[str] = None) -> int:
        return len(self.find_all(firm_id=firm_id))


# Singleton instance
client_repo = ClientRepository()
