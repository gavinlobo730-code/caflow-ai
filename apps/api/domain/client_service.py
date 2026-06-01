"""Client business logic. All DB access goes through repositories."""
from typing import Optional
from repositories.client_repository import client_repo
from repositories.task_repository import task_repo
from repositories.compliance_repository import compliance_repo
from repositories.document_repository import document_repo
from core.permissions import require_permission
from services.activity_service import log_activity
from models.client import validate_pan, validate_gstin


class ClientService:

    def get_workspace(self, client_id: str, actor_role: str = "Partner") -> dict:
        """Assemble full client workspace from all data sources."""
        require_permission(actor_role, "client", "read")
        client = client_repo.get_or_raise(client_id)
        tasks = task_repo.find_all(client_id=client_id)
        compliance = compliance_repo.find_all(client_id=client_id)
        documents = document_repo.find_all(client_id=client_id)

        open_tasks = [t for t in tasks if t["status"] != "completed"]
        overdue_compliance = [c for c in compliance if c["status"] == "overdue"]
        upcoming = sorted(
            [c for c in compliance if c["status"] in ("pending", "overdue")],
            key=lambda c: c["due_date"]
        )[:5]

        return {
            "profile": client,
            "compliance_tasks": compliance,
            "upcoming_deadlines": upcoming,
            "documents": documents,
            "open_tasks": open_tasks,
            "completed_tasks": [t for t in tasks if t["status"] == "completed"][:5],
            "summary": {
                "total_compliance": len(compliance),
                "overdue_count": len(overdue_compliance),
                "pending_count": len([c for c in compliance if c["status"] == "pending"]),
                "filed_count": len([c for c in compliance if c["status"] == "filed"]),
                "document_count": len(documents),
                "open_tasks": len(open_tasks),
                "pending_review_docs": len([d for d in documents if d["review_status"] == "pending_review"]),
            },
        }

    def create(self, data: dict, actor_role: str = "Partner") -> dict:
        require_permission(actor_role, "client", "write")
        validate_pan(data.get("pan", ""))
        if data.get("gstin"):
            validate_gstin(data["gstin"])
        client = client_repo.create(data)
        log_activity(
            action="client_created",
            description=f"Client created: {client['client_name']}",
            entity_type="client",
            entity_id=client["id"],
        )
        return client

    def update(self, client_id: str, data: dict, actor_role: str = "Partner") -> dict:
        require_permission(actor_role, "client", "write")
        client = client_repo.update(client_id, data)
        if not client:
            from core.exceptions import NotFoundError
            raise NotFoundError("Client", client_id)
        log_activity(
            action="client_updated",
            description=f"Client updated: {client['client_name']}",
            client_id=client_id,
            entity_type="client",
            entity_id=client_id,
        )
        return client

    def get_health_summary(self, firm_id: Optional[str] = None) -> dict:
        """Aggregate compliance health across all clients."""
        clients = client_repo.find_all(firm_id=firm_id)
        overdue = compliance_repo.find_overdue(firm_id=firm_id)
        overdue_client_ids = {t["client_id"] for t in overdue}
        return {
            "total_clients": len(clients),
            "active_clients": len([c for c in clients if c.get("status") == "active"]),
            "clients_with_overdue": len(overdue_client_ids),
            "total_overdue_items": len(overdue),
        }


client_service = ClientService()
