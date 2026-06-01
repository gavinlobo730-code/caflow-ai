import os
from typing import Optional
from repositories.base import BaseRepository
from core.exceptions import NotFoundError
from services.task_service import compute_task_urgency

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from mock_data import MOCK_TASKS, TASK_INDEX


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class TaskRepository(BaseRepository[dict]):

    def find_by_id(self, id: str) -> Optional[dict]:
        if _USE_MOCK:
            return TASK_INDEX.get(id)
        result = _get_db().table("tasks").select("*").eq("id", id).is_("deleted_at", None).maybe_single().execute()
        return result.data

    def find_all(
        self,
        firm_id: Optional[str] = None,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        assigned_to: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> list[dict]:
        if _USE_MOCK:
            tasks = list(MOCK_TASKS)
            if client_id:
                tasks = [t for t in tasks if t["client_id"] == client_id]
            if status:
                tasks = [t for t in tasks if t["status"] == status]
            if assigned_to:
                tasks = [t for t in tasks if t.get("assigned_to") == assigned_to]
            if priority:
                tasks = [t for t in tasks if t["priority"] == priority]
            return [{**t, "urgency": compute_task_urgency(t.get("due_date"), t["status"])} for t in tasks]

        query = _get_db().table("tasks").select("*").is_("deleted_at", None)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if client_id:
            query = query.eq("client_id", client_id)
        if status:
            query = query.eq("status", status)
        if assigned_to:
            query = query.eq("assigned_to", assigned_to)
        if priority:
            query = query.eq("priority", priority)
        result = query.order("created_at", desc=True).execute()
        tasks = result.data or []
        return [{**t, "urgency": compute_task_urgency(t.get("due_date"), t.get("status", ""))} for t in tasks]

    def get_or_raise(self, id: str) -> dict:
        task = self.find_by_id(id)
        if not task:
            raise NotFoundError("Task", id)
        return task

    def find_by_status(self, status: str, firm_id: Optional[str] = None) -> list[dict]:
        return self.find_all(status=status, firm_id=firm_id)

    def find_overdue(self) -> list[dict]:
        from datetime import date
        today = date.today().isoformat()
        if _USE_MOCK:
            return [
                t for t in MOCK_TASKS
                if t.get("due_date") and t["due_date"] < today and t["status"] not in ("completed",)
            ]
        result = (
            _get_db().table("tasks").select("*")
            .lt("due_date", today)
            .neq("status", "completed")
            .is_("deleted_at", None)
            .execute()
        )
        return result.data or []

    def find_due_today(self) -> list[dict]:
        from datetime import date
        today = date.today().isoformat()
        if _USE_MOCK:
            return [t for t in MOCK_TASKS if t.get("due_date") == today and t["status"] != "completed"]
        result = (
            _get_db().table("tasks").select("*")
            .eq("due_date", today)
            .neq("status", "completed")
            .is_("deleted_at", None)
            .execute()
        )
        return result.data or []

    def create(self, data: dict) -> dict:
        if _USE_MOCK:
            import uuid
            record = {"id": str(uuid.uuid4()), **data, "created_at": self.now_iso(), "updated_at": self.now_iso()}
            MOCK_TASKS.append(record)
            TASK_INDEX[record["id"]] = record
            return record
        result = _get_db().table("tasks").insert({**data, "created_at": self.now_iso(), "updated_at": self.now_iso()}).execute()
        return result.data[0]

    def update(self, id: str, data: dict) -> Optional[dict]:
        if _USE_MOCK:
            task = TASK_INDEX.get(id)
            if not task:
                return None
            task.update({**data, "updated_at": self.now_iso()})
            return task
        result = _get_db().table("tasks").update({**data, "updated_at": self.now_iso()}).eq("id", id).execute()
        return result.data[0] if result.data else None

    def group_by_status(self) -> dict[str, list[dict]]:
        from services.task_service import group_tasks_by_status
        return group_tasks_by_status(self.find_all())


task_repo = TaskRepository()
