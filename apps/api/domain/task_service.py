"""Task business logic — wraps repository with domain rules."""
from typing import Optional
from repositories.task_repository import task_repo
from repositories.client_repository import client_repo
from core.permissions import require_permission
from core.exceptions import NotFoundError, ValidationError
from services.task_service import is_valid_transition
from services.activity_service import log_activity
from mock_data import MOCK_CLIENTS


class TaskDomainService:

    def get_kanban(self, firm_id: Optional[str] = None, client_id: Optional[str] = None) -> dict:
        tasks = task_repo.find_all(firm_id=firm_id, client_id=client_id)
        client_map = {c["id"]: c["client_name"] for c in MOCK_CLIENTS}
        enriched = [{**t, "client_name": client_map.get(t["client_id"], "Unknown")} for t in tasks]
        return task_repo.group_by_status() if not client_id else _group(enriched)

    def get_dashboard_summary(self, firm_id: Optional[str] = None) -> dict:
        from datetime import date
        today = date.today().isoformat()
        from mock_data import MOCK_TASKS, MOCK_CLIENTS, MOCK_COMPLIANCE_TASKS
        tasks = MOCK_TASKS
        return {
            "active_clients": len([c for c in MOCK_CLIENTS if c.get("status") == "active"]),
            "tasks_due_today": len([t for t in tasks if t.get("due_date") == today and t["status"] != "completed"]),
            "overdue_tasks": len(task_repo.find_overdue()),
            "waiting_client": len([t for t in tasks if t["status"] == "waiting_client"]),
            "review_required": len([t for t in tasks if t["status"] == "review_required"]),
            "total_open_tasks": len([t for t in tasks if t["status"] != "completed"]),
            "documents_pending_review": 2,
            "overdue_compliance": len([c for c in MOCK_COMPLIANCE_TASKS if c["status"] == "overdue"]),
        }

    def transition_status(self, task_id: str, new_status: str, actor_role: str = "Partner") -> dict:
        require_permission(actor_role, "task", "write")
        task = task_repo.get_or_raise(task_id)
        if not is_valid_transition(task["status"], new_status):
            raise ValidationError("status", f"Cannot transition {task['status']} → {new_status}")
        updates: dict = {"status": new_status}
        if new_status == "completed":
            from datetime import datetime, timezone
            updates["completed_at"] = datetime.now(timezone.utc).isoformat()
        return task_repo.update(task_id, updates)

    def create(self, data: dict, actor_role: str = "Partner") -> dict:
        require_permission(actor_role, "task", "write")
        client_repo.get_or_raise(data["client_id"])
        task = task_repo.create(data)
        log_activity(
            action="compliance_task_created",
            description=f"Task created: {task['title']}",
            client_id=data["client_id"],
            entity_type="task",
            entity_id=task["id"],
        )
        return task


def _group(tasks: list[dict]) -> dict:
    from services.task_service import group_tasks_by_status
    return group_tasks_by_status(tasks)


task_domain_service = TaskDomainService()
