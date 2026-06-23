import os
from typing import Optional
from repositories.base import BaseRepository
from core.exceptions import NotFoundError

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from mock_data import MOCK_DOCUMENTS


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class DocumentRepository(BaseRepository[dict]):

    def find_by_id(self, id: str) -> Optional[dict]:
        if _USE_MOCK:
            return next((d for d in MOCK_DOCUMENTS if d["id"] == id), None)
        result = _get_db().table("documents").select("*").eq("id", id).maybe_single().execute()
        return result.data

    def find_all(
        self,
        firm_id: Optional[str] = None,
        client_id: Optional[str] = None,
        document_type: Optional[str] = None,
        review_status: Optional[str] = None,
    ) -> list[dict]:
        if _USE_MOCK:
            docs = list(MOCK_DOCUMENTS)
            docs = [d for d in docs if not d.get("deleted_at")]
            if client_id:
                docs = [d for d in docs if d["client_id"] == client_id]
            if document_type:
                docs = [d for d in docs if d["document_type"] == document_type]
            if review_status:
                docs = [d for d in docs if d["review_status"] == review_status]
            return docs

        query = _get_db().table("documents").select("*").is_("deleted_at", None)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if client_id:
            query = query.eq("client_id", client_id)
        if document_type:
            query = query.eq("document_type", document_type)
        if review_status:
            query = query.eq("review_status", review_status)
        result = query.order("created_at", desc=True).execute()
        return result.data or []

    def get_or_raise(self, id: str) -> dict:
        doc = self.find_by_id(id)
        if not doc:
            raise NotFoundError("Document", id)
        return doc

    def find_pending_review(self, firm_id: Optional[str] = None) -> list[dict]:
        return self.find_all(review_status="pending_review", firm_id=firm_id)

    def create(self, data: dict) -> dict:
        if _USE_MOCK:
            import uuid
            record = {"id": str(uuid.uuid4()), **data, "created_at": self.now_iso()}
            MOCK_DOCUMENTS.append(record)
            return record
        result = _get_db().table("documents").insert({**data, "created_at": self.now_iso()}).execute()
        return result.data[0]

    def update_review_status(self, id: str, status: str, reviewer_id: Optional[str] = None) -> Optional[dict]:
        if _USE_MOCK:
            doc = self.find_by_id(id)
            if not doc:
                return None
            doc.update({"review_status": status, "reviewed_at": self.now_iso()})
            if reviewer_id:
                doc["reviewed_by"] = reviewer_id
            return doc
        update_data: dict = {"review_status": status, "reviewed_at": self.now_iso()}
        if reviewer_id:
            update_data["reviewed_by"] = reviewer_id
        result = _get_db().table("documents").update(update_data).eq("id", id).execute()
        return result.data[0] if result.data else None

    def soft_delete(self, id: str, deleted_by: Optional[str] = None) -> bool:
        if _USE_MOCK:
            doc = self.find_by_id(id)
            if not doc:
                return False
            doc["deleted_at"] = self.now_iso()
            doc["deleted_by"] = deleted_by
            return True
        result = _get_db().table("documents").update({
            "deleted_at": self.now_iso(),
            "deleted_by": deleted_by,
        }).eq("id", id).execute()
        return bool(result.data)

    def update_storage_path(self, id: str, storage_path: str) -> Optional[dict]:
        """Persist Supabase Storage path after a successful upload."""
        if _USE_MOCK:
            doc = self.find_by_id(id)
            if doc:
                doc["storage_path"] = storage_path
            return doc
        result = _get_db().table("documents").update({"storage_path": storage_path, "updated_at": self.now_iso()}).eq("id", id).execute()
        return result.data[0] if result.data else None


document_repo = DocumentRepository()
