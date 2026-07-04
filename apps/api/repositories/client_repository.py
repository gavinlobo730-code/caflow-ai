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
    """
    Authoritative client lifecycle model.

    A client is LIVE when deleted_at IS NULL. It is ARCHIVED when
    status='archived'. The is_archived/is_deleted booleans are derived MIRRORS
    kept in sync by archive()/restore()/soft_delete() for index support;
    status + deleted_at are the read-canonical fields.

    All read paths (find_all/find_by_id/find_by_pan/find_by_gstin) filter on the
    canonical fields (deleted_at IS NULL, status != 'archived') — never on the
    mirror booleans. The mirrors exist only to back partial indexes.
    """

    def find_by_id(self, id: str, firm_id: Optional[str] = None) -> Optional[dict]:
        # firm_id is an optional defense-in-depth scope. Callers SHOULD pass it
        # so a single forgotten check cannot leak another firm's client. When
        # omitted, callers MUST themselves enforce firm membership (e.g. via
        # _assert_firm in the router) — see SECURITY.md for the isolation model.
        if _USE_MOCK:
            c = CLIENT_INDEX.get(id)
            if not c or c.get("deleted_at"):
                return None
            if firm_id and c.get("firm_id") != firm_id:
                return None
            return c
        query = _get_db().table("clients").select("*").eq("id", id).is_("deleted_at", None)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        result = query.maybe_single().execute()
        return result.data

    def find_all(
        self,
        firm_id: Optional[str] = None,
        status: Optional[str] = None,
        include_archived: bool = False,
        include_test: bool = True,
        include_internal: bool = False,
        **filters,
    ) -> list[dict]:
        # Guardrail G2 (Amendment v1.1): the firm-as-internal-client is excluded
        # from every client-population surface by default. Partner-scoped callers
        # that genuinely need it (e.g. the Practice workspace) pass
        # include_internal=True explicitly.
        if _USE_MOCK:
            clients = [c for c in MOCK_CLIENTS if not c.get("deleted_at")]
            if firm_id:
                clients = [c for c in clients if c.get("firm_id") == firm_id]
            if not include_internal:
                clients = [c for c in clients if not c.get("is_internal", False)]
            if not include_archived:
                clients = [c for c in clients if c.get("status") != "archived"]
            if not include_test:
                clients = [c for c in clients if not c.get("is_test", False)]
            if status:
                clients = [c for c in clients if c.get("status") == status]
            return clients

        query = _get_db().table("clients").select("*").is_("deleted_at", None)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if not include_internal:
            query = query.eq("is_internal", False)
        if not include_archived:
            query = query.neq("status", "archived")
        if not include_test:
            query = query.eq("is_test", False)
        if status:
            query = query.eq("status", status)
        result = query.order("client_name").execute()
        return result.data or []

    def find_by_pan(self, pan: str) -> Optional[dict]:
        if _USE_MOCK:
            return next((c for c in MOCK_CLIENTS if c["pan"] == pan and not c.get("deleted_at")), None)
        result = _get_db().table("clients").select("*").eq("pan", pan).is_("deleted_at", None).execute()
        return result.data[0] if result.data else None

    def find_by_gstin(self, gstin: str) -> Optional[dict]:
        if _USE_MOCK:
            return next((c for c in MOCK_CLIENTS if c.get("gstin") == gstin and not c.get("deleted_at")), None)
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
            record = {
                "id": str(uuid.uuid4()),
                "is_test": False,
                **data,
                "created_at": self.now_iso(),
                "updated_at": self.now_iso(),
                "deleted_at": None,
            }
            MOCK_CLIENTS.append(record)
            CLIENT_INDEX[record["id"]] = record
            return record
        result = _get_db().table("clients").insert({**data, "created_at": self.now_iso(), "updated_at": self.now_iso()}).execute()
        return result.data[0]

    def update(self, id: str, data: dict) -> Optional[dict]:
        if _USE_MOCK:
            client = CLIENT_INDEX.get(id)
            if not client or client.get("deleted_at"):
                return None
            client.update({**data, "updated_at": self.now_iso()})
            return client
        result = _get_db().table("clients").update({**data, "updated_at": self.now_iso()}).eq("id", id).execute()
        return result.data[0] if result.data else None

    def archive(self, id: str, actor_id: Optional[str] = None) -> Optional[dict]:
        from datetime import datetime, timezone
        return self.update(id, {
            "status": "archived",
            "is_archived": True,
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "archived_by": actor_id,
        })

    def restore(self, id: str, actor_id: Optional[str] = None) -> Optional[dict]:
        # actor_id is accepted for audit symmetry with archive()/soft_delete()
        # even though restore stores no actor column (it clears archived_by).
        return self.update(id, {
            "status": "active",
            "is_archived": False,
            "archived_at": None,
            "archived_by": None,
        })

    def soft_delete(self, id: str, actor_id: Optional[str] = None) -> bool:
        if _USE_MOCK:
            client = CLIENT_INDEX.get(id)
            if not client:
                return False
            client["deleted_at"] = self.now_iso()
            client["is_deleted"] = True
            client["deleted_by"] = actor_id
            client["updated_at"] = self.now_iso()
            return True
        result = _get_db().table("clients").update({
            "deleted_at": self.now_iso(),
            "is_deleted": True,
            "deleted_by": actor_id,
        }).eq("id", id).execute()
        return bool(result.data)

    def count(self, firm_id: Optional[str] = None, include_internal: bool = False) -> int:
        # Excludes the internal client by default (Guardrail G2).
        return len(self.find_all(firm_id=firm_id, include_internal=include_internal))


client_repo = ClientRepository()
