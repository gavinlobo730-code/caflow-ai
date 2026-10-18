import os
from typing import Optional
from repositories.base import BaseRepository
from core.exceptions import NotFoundError
from services.task_service import compute_task_urgency
from core import db_provider
from core.db_paging import fetch_all
from core.ist_clock import ist_today

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from mock_data import MOCK_TASKS, TASK_INDEX


_get_db = db_provider.request_db


class TaskRepository(BaseRepository[dict]):

    def find_by_id(self, id: str, firm_id: Optional[str] = None) -> Optional[dict]:
        # firm_id is an optional defense-in-depth scope (same pattern as
        # client_repository.find_by_id) -- pass it whenever the caller has one,
        # so a forgotten post-check can't leak another firm's task.
        if _USE_MOCK:
            task = TASK_INDEX.get(id)
            if not task:
                return None
            if firm_id and task.get("firm_id") != firm_id:
                return None
            return task
        query = _get_db().table("tasks").select("*").eq("id", id).is_("deleted_at", None)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        result = query.maybe_single().execute()
        return result.data

    def find_all(
        self,
        firm_id: Optional[str] = None,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        assigned_to: Optional[str] = None,
        priority: Optional[str] = None,
        exclude_statuses: Optional[list[str]] = None,
    ) -> list[dict]:
        if _USE_MOCK:
            tasks = list(MOCK_TASKS)
            # Mock branch was missing this filter entirely (only the real
            # Supabase branch below scoped by firm) -- the same cross-tenant
            # mock-mode gap already fixed for client_repository.py (R3.13b).
            if firm_id:
                tasks = [t for t in tasks if t.get("firm_id") == firm_id]
            if client_id:
                tasks = [t for t in tasks if t["client_id"] == client_id]
            if status:
                tasks = [t for t in tasks if t["status"] == status]
            if assigned_to:
                tasks = [t for t in tasks if t.get("assigned_to") == assigned_to]
            if priority:
                tasks = [t for t in tasks if t["priority"] == priority]
            if exclude_statuses:
                tasks = [t for t in tasks if t["status"] not in exclude_statuses]
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
        if exclude_statuses:
            query = query.not_.in_("status", exclude_statuses)
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

    def find_open(self, firm_id: Optional[str] = None) -> list[dict]:
        """Every task that is not completed or deleted, with the columns a COUNT needs, every page.

        The dashboard's open-task counts used `find_all`, which is unpaged and stops at PostgREST's row cap, while
        `find_overdue` beside it reads every page: a firm with 1,500 open tasks, all overdue, was told 1,500 overdue and
        1,000 open on one payload. Both halves read every page now, so the figures on one screen agree. (`find_all`
        keeps its newest-first order for the screens that list tasks; a count has no use for an order.)"""
        if _USE_MOCK:
            tasks = [t for t in MOCK_TASKS if t.get("status") != "completed" and not t.get("deleted_at")]
            if firm_id:
                tasks = [t for t in tasks if t.get("firm_id") == firm_id]
            return tasks
        from core.db_paging import fetch_all

        def open_query():
            query = (_get_db().table("tasks").select("id, status, due_date, client_id")
                     .neq("status", "completed").is_("deleted_at", None))
            if firm_id:
                query = query.eq("firm_id", firm_id)
            return query

        return fetch_all(open_query, label="tasks.find_open")

    def find_overdue(self, firm_id: Optional[str] = None) -> list[dict]:
        """Overdue (past-due, not completed) tasks. firm_id is optional and
        defaults to None (every firm) only for backward compatibility with
        existing callers still doing their own post-filter — new callers
        should always pass firm_id so the scope is pushed to the query."""
        today = ist_today().isoformat()
        if _USE_MOCK:
            tasks = [
                t for t in MOCK_TASKS
                if t.get("due_date") and t["due_date"] < today and t["status"] not in ("completed",)
            ]
            if firm_id:
                tasks = [t for t in tasks if t.get("firm_id") == firm_id]
            return tasks
        # Every page: PostgREST stops at ~1000 rows and says nothing, and this count feeds the executive dashboard
        # and the morning digest (POST-A-048). The Indian day, not the UTC one: between 00:00 and 05:30 IST the
        # server clock still names yesterday and a task that fell due this morning would not be overdue yet.
        # Only what the callers read (the count, the client for narrowing, the two owner columns; `id` is the paging
        # key): what crosses the wire is the size of the ANSWER, and a firm with thousands of overdue tasks would
        # otherwise pull every description. The select is a literal so the columns-exist guard can read it.
        def _overdue_query():
            query = (
                _get_db().table("tasks").select("id, firm_id, client_id, assignee_id, assigned_to, due_date, status")
                .lt("due_date", today)
                .neq("status", "completed")
                .is_("deleted_at", None)
            )
            return query.eq("firm_id", firm_id) if firm_id else query

        return fetch_all(_overdue_query, label="tasks overdue")

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

    def delete(self, id: str, *, firm_id: str) -> bool:
        """Remove a task. The firm is required: the router has already shown the row is the caller's, and this is the one
        statement that cannot be taken back."""
        if not firm_id:
            raise ValueError("delete needs the firm")
        if _USE_MOCK:
            task = TASK_INDEX.get(id)
            if not task or task.get("firm_id") != firm_id:
                return False
            TASK_INDEX.pop(id, None)
            if task in MOCK_TASKS:
                MOCK_TASKS.remove(task)
            return True
        result = _get_db().table("tasks").delete().eq("id", id).eq("firm_id", firm_id).execute()
        return bool(result.data)

    def group_by_status(self, firm_id: str) -> dict[str, list[dict]]:
        # The firm is required, and an empty one is refused: find_all() with no
        # firm returns EVERY firm's tasks, and a board built from that would carry
        # everybody else's cards. This had no firm parameter at all until
        # engineering-28 and its only caller is get_kanban.
        if not firm_id:
            raise ValueError("group_by_status needs the firm: without one every firm's tasks are read")
        from services.task_service import group_tasks_by_status
        return group_tasks_by_status(self.find_all(firm_id=firm_id))


task_repo = TaskRepository()
