from typing import Optional
from repositories.base import BaseRepository
from core import db_provider


_get_db = db_provider.request_db


def _write_db():
    """The client every INSERT, UPSERT and DELETE on `task_tags`, `task_dependencies` and `task_timeline_events` goes through:
    the privileged one (POST-A-018, migration 513).

    A signed-in session holds no write privilege on these tables, so nothing here may write as the caller. Reads stay on
    `_get_db` (the caller's own session). The price of writing privileged is that row security is no longer the second lock on
    a write: a tag and an event carry the firm they are written for, and `task_dependencies`, which has no firm of its own
    (migration 063 scopes it through `tasks`), is only written after both tasks are shown to be the firm's."""
    return db_provider.service_db()


class TaskExtrasRepository(BaseRepository[dict]):

    # ── Removing a task's satellites ─────────────────────────────────────────

    def purge_task(self, task_id: str, *, firm_id: str) -> None:
        """Remove what hangs off a task that has just been deleted: its tags, its dependencies in either direction and its
        timeline events. None of the three has a foreign key to `tasks` (migration 063), so the database leaves them
        behind. The task was shown to be the firm's by the caller; the tags and events are still filtered by the firm, and a
        dependency row (which has no firm of its own) is removed only where this task id is one end of it."""
        db = _write_db()
        db.table("task_tags").delete().eq("task_id", task_id).eq("firm_id", firm_id).execute()
        db.table("task_timeline_events").delete().eq("task_id", task_id).eq("firm_id", firm_id).execute()
        db.table("task_dependencies").delete().eq("task_id", task_id).execute()
        db.table("task_dependencies").delete().eq("depends_on_task_id", task_id).execute()

    # ── Tags ─────────────────────────────────────────────────────────────────

    def get_tags(self, task_id: str) -> list[dict]:
        result = _get_db().table("task_tags").select("*").eq("task_id", task_id).order("tag").execute()
        return result.data or []

    def add_tag(self, firm_id: str, task_id: str, tag: str) -> dict:
        result = _write_db().table("task_tags").upsert({
            "firm_id": firm_id,
            "task_id": task_id,
            "tag": tag.lower().strip(),
            "created_at": self.now_iso(),
        }, on_conflict="task_id,tag").execute()
        return result.data[0]

    def remove_tag(self, task_id: str, tag: str, *, firm_id: str) -> bool:
        """The firm is required, not optional: this deletes with the privileged client, so the firm filter is the only thing
        that keeps a task id from another firm out of reach."""
        result = (_write_db().table("task_tags").delete()
                  .eq("task_id", task_id).eq("tag", tag.lower().strip()).eq("firm_id", firm_id).execute())
        return len(result.data) > 0

    def get_firm_tags(self, firm_id: str,
                      allowed_client_ids: Optional[set] = None) -> list[str]:
        """The firm's tag vocabulary, optionally narrowed to a set of clients.

        `allowed_client_ids=None` means "every client in the firm" (a Partner or
        Manager), and takes the single-query path this always had.

        Otherwise the tags are resolved through their tasks. A tag is free text
        somebody typed on a client's task — "acme-gst-migration" names a client
        as surely as a client_id does — so an autocomplete list is not a reason
        to hand out labels from books the caller cannot open. Two queries, not
        one per tag: `task_tags` has no foreign key to `tasks` (migration 063),
        so PostgREST cannot embed the join.
        """
        q = _get_db().table("task_tags").select("tag, task_id").eq("firm_id", firm_id)
        rows = q.execute().data or []
        if allowed_client_ids is not None:
            task_ids = sorted({r["task_id"] for r in rows if r.get("task_id")})
            visible = set()
            if task_ids:
                owners = (_get_db().table("tasks").select("id, client_id")
                          .in_("id", task_ids).execute().data) or []
                visible = {t["id"] for t in owners
                           if t.get("client_id") in allowed_client_ids}
            rows = [r for r in rows if r.get("task_id") in visible]
        tags = list({row["tag"] for row in rows})
        tags.sort()
        return tags

    # ── Dependencies ──────────────────────────────────────────────────────────

    def _detect_cycle(self, task_id: str, depends_on_task_id: str) -> bool:
        """
        Detect if adding a dependency from task_id -> depends_on_task_id would create a cycle.
        Walks outward from depends_on_task_id to see if it can reach task_id.
        Returns True if a cycle would be created, False otherwise.

        Reads only the edges actually reachable from the starting task, one
        breadth-first level at a time. It used to `SELECT` the whole
        `task_dependencies` table — every firm's rows — to answer a question
        about two tasks in one firm. The table carries no `firm_id` of its own
        (migration 063: it is scoped through `tasks`), so there is no filter to
        add; bounding the traversal is the filter. Every edge it does read is
        one an ancestor of these two tasks already points at.
        """
        db = _get_db()
        visited = set()
        frontier = [depends_on_task_id]

        while frontier:
            if task_id in frontier:
                return True  # Cycle detected
            visited.update(frontier)
            rows = (
                db.table("task_dependencies")
                .select("task_id, depends_on_task_id")
                .in_("task_id", frontier)
                .execute()
            ).data or []
            frontier = sorted({
                r["depends_on_task_id"] for r in rows
                if r.get("depends_on_task_id") and r["depends_on_task_id"] not in visited
            })

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

    def _assert_tasks_in_firm(self, firm_id: str, *task_ids: str) -> None:
        """Every task named is the firm's, or ValueError. `task_dependencies` has no `firm_id`, so before migration 513 the
        row policy asked this question of the caller's session; the privileged writes below ask it themselves."""
        wanted = sorted({str(t) for t in task_ids})
        rows = (_write_db().table("tasks").select("id").in_("id", wanted).eq("firm_id", firm_id).execute().data) or []
        if len(rows) != len(wanted):
            raise ValueError("Task not found")

    def add_dependency(self, task_id: str, depends_on_task_id: str, *, firm_id: str) -> dict:
        if task_id == depends_on_task_id:
            raise ValueError("A task cannot depend on itself")
        self._assert_tasks_in_firm(firm_id, task_id, depends_on_task_id)
        if self._detect_cycle(task_id, depends_on_task_id):
            raise ValueError("Adding this dependency would create a circular chain")
        result = _write_db().table("task_dependencies").upsert({
            "task_id": task_id,
            "depends_on_task_id": depends_on_task_id,
            "created_at": self.now_iso(),
        }, on_conflict="task_id,depends_on_task_id").execute()
        return result.data[0]

    def remove_dependency(self, task_id: str, dependency_id: str, *, firm_id: str) -> bool:
        # Scoped to task_id (not just the dependency row's own id) so a dependency_id belonging to a different task can't be
        # deleted via this route, and task_id itself is shown to be the firm's before anything is deleted.
        self._assert_tasks_in_firm(firm_id, task_id)
        result = (
            _write_db().table("task_dependencies").delete()
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
        if not firm_id:
            # `firm_id` stayed Optional in the signature for the callers that pass it by keyword, but a row with no firm is
            # one the old row policy (`firm_id = get_my_firm_id()`) would have refused and the privileged client would not.
            raise ValueError("A task timeline event is written for a firm")
        result = _write_db().table("task_timeline_events").insert({
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
