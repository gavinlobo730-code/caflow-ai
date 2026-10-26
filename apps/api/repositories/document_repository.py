import os
from typing import Optional
from repositories.base import BaseRepository
from core.exceptions import NotFoundError
from core import db_provider
from core.db_paging import fetch_all
from core.authz import scope_query_to_clients
from core.db_provider import privileged_for

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from mock_data import MOCK_DOCUMENTS


_get_db = db_provider.request_db

#: A firm id that no firm has. The queries below are made with the privileged client (POST-A-339), which carries no row security,
#: so a call that names no firm must read and change nothing; it used to be narrowed to the caller's firm by the policy.
_NO_FIRM = "00000000-0000-0000-0000-000000000000"


class DocumentRepository(BaseRepository[dict]):

    def find_by_id(self, id: str, firm_id: Optional[str] = None) -> Optional[dict]:
        if _USE_MOCK:
            return next((d for d in MOCK_DOCUMENTS if d["id"] == id and not d.get("deleted_at")), None)
        result = (privileged_for(_get_db()).table("documents").select("*").eq("id", id).eq("firm_id", firm_id or _NO_FIRM)
                  .is_("deleted_at", None).maybe_single().execute())
        return result.data

    def find_all(
        self,
        firm_id: Optional[str] = None,
        client_id: Optional[str] = None,
        document_type: Optional[str] = None,
        review_status: Optional[str] = None,
        columns: str = "*",
        allowed_client_ids: Optional[set] = None,
    ) -> list[dict]:
        """Every matching document, newest first.

        `allowed_client_ids` (the caller's own clients when no single client is named; None is every client) narrows the statement
        itself, so a scoped caller does not read the whole firm's documents, extracted text included, to keep a few.

        `columns` narrows the projection for a caller that needs a few (the global search reads three), because `*` carries
        the extracted text of every document and this read now returns ALL of them, not the first thousand. It must name
        `id`: the pager's cursor is read off the last row."""
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

        # EVERY matching row, in keyset pages: PostgREST cuts a response at about a thousand rows and says nothing,
        # so a firm with more documents than that was shown the first thousand as though they were all of them
        # (core/db_paging.py). The newest-first order is applied after the read, because the pager's key is the id.
        def _query():
            query = (privileged_for(_get_db()).table("documents").select(columns).is_("deleted_at", None)
                     .eq("firm_id", firm_id or _NO_FIRM))
            if client_id:
                query = query.eq("client_id", client_id)
            else:
                query = scope_query_to_clients(query, allowed_client_ids)
            if document_type:
                query = query.eq("document_type", document_type)
            if review_status:
                query = query.eq("review_status", review_status)
            return query

        rows = fetch_all(_query, "id", label="documents")
        rows.sort(key=lambda d: str(d.get("id") or ""))
        rows.sort(key=lambda d: str(d.get("created_at") or ""), reverse=True)
        return rows

    def get_or_raise(self, id: str, firm_id: Optional[str] = None) -> dict:
        doc = self.find_by_id(id, firm_id=firm_id)
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
        result = privileged_for(_get_db()).table("documents").insert({**data, "created_at": self.now_iso()}).execute()
        return result.data[0]

    def update_review_status(self, id: str, status: str, reviewer_id: Optional[str] = None,
                             firm_id: Optional[str] = None) -> Optional[dict]:
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
        result = (privileged_for(_get_db()).table("documents").update(update_data).eq("id", id)
                  .eq("firm_id", firm_id or _NO_FIRM).execute())
        return result.data[0] if result.data else None

    def soft_delete(self, id: str, deleted_by: Optional[str] = None, firm_id: Optional[str] = None) -> bool:
        if _USE_MOCK:
            doc = self.find_by_id(id)
            if not doc:
                return False
            doc["deleted_at"] = self.now_iso()
            doc["deleted_by"] = deleted_by
            return True
        result = privileged_for(_get_db()).table("documents").update({
            "deleted_at": self.now_iso(),
            "deleted_by": deleted_by,
        }).eq("id", id).eq("firm_id", firm_id or _NO_FIRM).execute()
        return bool(result.data)

    def update_storage_path(self, id: str, storage_path: str, firm_id: Optional[str] = None) -> Optional[dict]:
        """Persist Supabase Storage path after a successful upload."""
        if _USE_MOCK:
            doc = self.find_by_id(id)
            if doc:
                doc["storage_path"] = storage_path
            return doc
        result = (privileged_for(_get_db()).table("documents").update({"storage_path": storage_path, "updated_at": self.now_iso()})
                  .eq("id", id).eq("firm_id", firm_id or _NO_FIRM).execute())
        return result.data[0] if result.data else None


document_repo = DocumentRepository()
