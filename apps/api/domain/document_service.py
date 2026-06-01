"""Document business logic."""
from typing import Optional
from repositories.document_repository import document_repo
from core.permissions import require_permission
from services.activity_service import log_activity


class DocumentService:

    def get_for_client(self, client_id: str, actor_role: str = "Partner") -> list[dict]:
        require_permission(actor_role, "document", "read")
        return document_repo.find_all(client_id=client_id)

    def approve(self, document_id: str, reviewer_id: str, actor_role: str = "Partner") -> dict:
        require_permission(actor_role, "document", "approve")
        doc = document_repo.update_review_status(document_id, "approved", reviewer_id)
        if not doc:
            from core.exceptions import NotFoundError
            raise NotFoundError("Document", document_id)
        log_activity(
            action="document_approved",
            description=f"Document approved: {doc.get('file_name')}",
            client_id=doc.get("client_id"),
            entity_type="document",
            entity_id=document_id,
        )
        return doc

    def reject(self, document_id: str, reviewer_id: str, actor_role: str = "Partner") -> dict:
        require_permission(actor_role, "document", "approve")
        doc = document_repo.update_review_status(document_id, "rejected", reviewer_id)
        if not doc:
            from core.exceptions import NotFoundError
            raise NotFoundError("Document", document_id)
        log_activity(
            action="document_rejected",
            description=f"Document rejected: {doc.get('file_name')}",
            client_id=doc.get("client_id"),
            entity_type="document",
            entity_id=document_id,
        )
        return doc

    def get_pending_review(self, firm_id: Optional[str] = None, actor_role: str = "Partner") -> list[dict]:
        require_permission(actor_role, "document", "read")
        return document_repo.find_pending_review(firm_id=firm_id)


document_service = DocumentService()
