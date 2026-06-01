from typing import Optional
from repositories.base import BaseRepository
from mock_data import MOCK_DOCUMENTS
from core.exceptions import NotFoundError


class DocumentRepository(BaseRepository[dict]):

    def find_by_id(self, id: str) -> Optional[dict]:
        return next((d for d in MOCK_DOCUMENTS if d["id"] == id), None)

    def find_all(
        self,
        firm_id: Optional[str] = None,
        client_id: Optional[str] = None,
        document_type: Optional[str] = None,
        review_status: Optional[str] = None,
    ) -> list[dict]:
        docs = list(MOCK_DOCUMENTS)
        if client_id:
            docs = [d for d in docs if d["client_id"] == client_id]
        if document_type:
            docs = [d for d in docs if d["document_type"] == document_type]
        if review_status:
            docs = [d for d in docs if d["review_status"] == review_status]
        return docs

    def get_or_raise(self, id: str) -> dict:
        doc = self.find_by_id(id)
        if not doc:
            raise NotFoundError("Document", id)
        return doc

    def find_pending_review(self, firm_id: Optional[str] = None) -> list[dict]:
        return self.find_all(review_status="pending_review", firm_id=firm_id)

    def create(self, data: dict) -> dict:
        import uuid
        record = {"id": str(uuid.uuid4()), **data, "created_at": self.now_iso()}
        MOCK_DOCUMENTS.append(record)
        return record

    def update_review_status(self, id: str, status: str, reviewer_id: Optional[str] = None) -> Optional[dict]:
        doc = self.find_by_id(id)
        if not doc:
            return None
        doc.update({"review_status": status, "reviewed_at": self.now_iso()})
        if reviewer_id:
            doc["reviewed_by"] = reviewer_id
        return doc


document_repo = DocumentRepository()
