"""Task business logic — wraps repository with domain rules."""
from typing import Optional
from repositories.task_repository import task_repo
from repositories.client_repository import client_repo
from core.permissions import require_permission
from core.exceptions import NotFoundError, ValidationError
from services.task_service import is_valid_transition
from services.activity_service import log_activity


class TaskDomainService:

    def get_kanban(self, firm_id: Optional[str] = None, client_id: Optional[str] = None) -> dict:
        tasks = task_repo.find_all(firm_id=firm_id, client_id=client_id)
        clients = client_repo.find_all(firm_id=firm_id)
        client_map = {c["id"]: c["client_name"] for c in clients}
        enriched = [{**t, "client_name": client_map.get(t.get("client_id", ""), "Unknown")} for t in tasks]
        return task_repo.group_by_status() if not client_id else _group(enriched)

    def get_dashboard_summary(self, firm_id: Optional[str] = None) -> dict:
        from datetime import date, timedelta
        from domain.compliance_record_service import compliance_record_service
        today = date.today()
        today_str = today.isoformat()
        week_end = (today + timedelta(days=7)).isoformat()

        all_clients = client_repo.find_all(firm_id=firm_id)
        active_clients = [c for c in all_clients if c.get("status") == "active"]

        tasks = task_repo.find_all(firm_id=firm_id)
        open_tasks = [t for t in tasks if t.get("status") != "completed"]

        # R3.13d: compliance_records (System A) is the sole source now —
        # compliance_tasks (System B) is being retired.
        all_records = compliance_record_service.list_records(firm_id=firm_id)
        compliance_overdue = len([r for r in all_records if r.get("status") == "Overdue"])
        compliance_due_week = len([
            r for r in all_records
            if r.get("status") not in ("Filed",) and today_str <= r.get("due_date", "") <= week_end
        ])

        high_risk_clients = 0
        for client in active_clients:
            hs = compliance_record_service.get_client_health_score(client["id"])
            if hs["health_score"] < 50:
                high_risk_clients += 1

        # task_repo.find_overdue() has no firm_id parameter (it scans every
        # firm's tasks) — filter the result in Python to the caller's firm,
        # the same post-hoc scoping pattern used for this exact repo method
        # in domain/ai_copilot_service.py's _build_context. Tenancy fix, R2.8/F19.
        overdue_tasks = [
            t for t in task_repo.find_overdue()
            if not firm_id or t.get("firm_id") == firm_id
        ]

        return {
            "active_clients": len(active_clients),
            "tasks_due_today": len([t for t in open_tasks if t.get("due_date") == today_str]),
            "overdue_tasks": len(overdue_tasks),
            "waiting_client": len([t for t in open_tasks if t.get("status") == "waiting_client"]),
            "review_required": len([t for t in open_tasks if t.get("status") == "review_required"]),
            "total_open_tasks": len(open_tasks),
            "documents_pending_review": 2,
            "compliance_due_week": compliance_due_week,
            "compliance_overdue": compliance_overdue,
            "high_risk_clients": high_risk_clients,
            "returns_due_week": compliance_due_week,
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
