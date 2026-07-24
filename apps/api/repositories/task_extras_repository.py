from typing import Optional
from repositories.base import BaseRepository


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class TaskExtrasRepository(BaseRepository[dict]):

    # ── Tags ─────────────────────────────────────────────────────────────────

    def get_tags(self, task_id: str) -> list[dict]:
        result = _get_db().table("task_tags").select("*").eq("task_id", task_id).order("tag").execute()
        return result.data or []

    def add_tag(self, firm_id: str, task_id: str, tag: str) -> dict:
        result = _get_db().table("task_tags").upsert({
            "firm_id": firm_id,
            "task_id": task_id,
            "tag": tag.lower().strip(),
            "created_at": self.now_iso(),
        }, on_conflict="task_id,tag").execute()
        return result.data[0]

    def remove_tag(self, task_id: str, tag: str, firm_id: Optional[str] = None) -> bool:
        query = _get_db().table("task_tags").delete().eq("task_id", task_id).eq("tag", tag.lower().strip())
        if firm_id:
            query = query.eq("firm_id", firm_id)
        result = query.execute()
        return len(result.data) > 0

    def get_firm_tags(self, firm_id: str) -> list[str]:
        result = _get_db().table("task_tags").select("tag").eq("firm_id", firm_id).execute()
        tags = list({row["tag"] for row in (result.data or [])})
        tags.sort()
        return tags

    # ── Dependencies ──────────────────────────────────────────────────────────

    def _detect_cycle(self, task_id: str, depends_on_task_id: str) -> bool:
        """
        Detect if adding a dependency from task_id -> depends_on_task_id would create a cycle.
        Uses depth-first search starting from depends_on_task_id to see if it can reach task_id.
        Returns True if a cycle would be created, False otherwise.
        """
        # Get all dependencies from the database
        result = _get_db().table("task_dependencies").select("task_id, depends_on_task_id").execute()
        all_deps = result.data or []

        # Build adjacency list: task_id -> [tasks that task_id depends on]
        adjacency = {}
        for dep in all_deps:
            t_id = dep["task_id"]
            dep_id = dep["depends_on_task_id"]
            if t_id not in adjacency:
                adjacency[t_id] = []
            adjacency[t_id].append(dep_id)

        # DFS from depends_on_task_id to see if we can reach task_id
        visited = set()
        stack = [depends_on_task_id]

        while stack:
            current = stack.pop()
            if current == task_id:
                return True  # Cycle detected
            if current in visited:
                continue
            visited.add(current)

            # Add all tasks that depend on current to the stack
            if current in adjacency:
                for next_task in adjacency[current]:
                    if next_task not in visited:
                        stack.append(next_task)

        return False  # No cycle detected

    def get_dependencies(self, task_id: str) -> list[dict]:
        db = _get_db()
        result = db.table("task_dependencies").select("*").eq("task_id", task_id).execute()
        rows = result.data or []
        if not rows:
            return []
        dep_ids = [r["depends_on_task_id"] for r in rows]
        tasks_result = db.table("tasks").select("id, title, status").in_("id", dep_ids).execute()
        task_map = {t["id"]: t for t in (tasks_result.data or [])}
        out = []
        for r in rows:
            dep_task = task_map.get(r["depends_on_task_id"]) or {}
            out.append({
                "id": r["id"],
                "task_id": r["task_id"],
                "depends_on_task_id": r["depends_on_task_id"],
                "depends_on_task_title": dep_task.get("title"),
                "depends_on_task_status": dep_task.get("status"),
                "created_at": r["created_at"],
            })
        return out

    def add_dependency(self, task_id: str, depends_on_task_id: str) -> dict:
        if task_id == depends_on_task_id:
            raise ValueError("A task cannot depend on itself")
        if self._detect_cycle(task_id, depends_on_task_id):
            raise ValueError("Adding this dependency would create a circular chain")
        result = _get_db().table("task_dependencies").upsert({
            "task_id": task_id,
            "depends_on_task_id": depends_on_task_id,
            "created_at": self.now_iso(),
        }, on_conflict="task_id,depends_on_task_id").execute()
        return result.data[0]

    def remove_dependency(self, task_id: str, dependency_id: str) -> bool:
        # Scoped to task_id (not just the dependency row's own id) so a
        # dependency_id belonging to a different task can't be deleted via
        # this route -- the caller has already verified task_id's firm.
        result = (
            _get_db().table("task_dependencies").delete()
            .eq("id", dependency_id).eq("task_id", task_id).execute()
        )
        return len(result.data) > 0

    # ── Timeline Events ───────────────────────────────────────────────────────

    def get_timeline(self, task_id: str) -> list[dict]:
        result = (
            _get_db().table("task_timeline_events")
            .select("*")
            .eq("task_id", task_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []

    def log_event(
        self,
        task_id: str,
        event_type: str,
        firm_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
        old_value: Optional[dict] = None,
        new_value: Optional[dict] = None,
    ) -> dict:
        result = _get_db().table("task_timeline_events").insert({
            "task_id": task_id,
            "firm_id": firm_id,
            "event_type": event_type,
            "actor_id": actor_id,
            "actor_name": actor_name,
            "old_value": old_value,
            "new_value": new_value,
            "created_at": self.now_iso(),
        }).execute()
        return result.data[0]

    def find_events_by_type(self, task_id: str, event_type: str) -> list[dict]:
        """Find all timeline events of a specific type for a task."""
        result = (
            _get_db().table("task_timeline_events")
            .select("*")
            .eq("task_id", task_id)
            .eq("event_type", event_type)
            .execute()
        )
        return result.data or []


task_extras_repo = TaskExtrasRepository()
