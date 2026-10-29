from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from typing import Optional
from models.common import api_response
from core.permissions import rbac
from core.authz import (
    filter_by_client, assert_client_access, assert_firmwide_job,
)
from repositories.task_repository import task_repo
from repositories.client_repository import client_repo
from services.task_service import is_valid_transition, group_tasks_by_status
from services.activity_service import log_activity
from services.audit_service import log_event
from domain.practice import task_estimate
import logging
from datetime import date, datetime, timezone

_logger = logging.getLogger("caflow.tasks")

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _blank_to_none(value):
    """A cleared box arrives as "" (an input's own value) and means "nothing": Postgres has no empty date and no empty user id."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _check_due_date(value):
    """A due date is a calendar date, YYYY-MM-DD, or nothing. Checked here so a bad one is a 422 that names the field and
    never a database error halfway through a write."""
    value = _blank_to_none(value)
    if value is None:
        return None
    try:
        date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("due_date must be a calendar date written YYYY-MM-DD") from exc
    return str(value)


class TaskCreate(BaseModel):
    client_id: str
    title: str
    description: Optional[str] = None
    status: str = "todo"
    priority: str = "medium"
    assigned_to: Optional[str] = None
    due_date: Optional[str] = None
    workflow_id: Optional[str] = None
    workflow_step_id: Optional[str] = None
    # How long this is expected to take, in whole minutes (> 0). Absent is "nobody
    # has estimated it" and is never stored as 0 (`domain/practice/task_estimate`).
    estimated_minutes: Optional[int] = None

    @field_validator("estimated_minutes", mode="before")
    @classmethod
    def _check_estimate(cls, v):
        return task_estimate.check_minutes(v)

    @field_validator("due_date", mode="before")
    @classmethod
    def _check_due(cls, v):
        return _check_due_date(v)

    @field_validator("assigned_to", mode="before")
    @classmethod
    def _unassigned_is_none(cls, v):
        return _blank_to_none(v)


class TaskUpdate(BaseModel):
    """A PATCH: a field that is ABSENT is left as it is. Two fields can also be cleared, by sending them as null (or, for
    a box a person emptied, as ""): `due_date` and `assigned_to`. A task with no due date and a task with no assignee are
    both real states, and a form that could not set them back would leave the only way to do it a write straight to the
    table. Nothing else is cleared by a null, so a caller that sends a whole form with some fields empty cannot wipe the
    title or the priority by accident."""
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[str] = None
    due_date: Optional[str] = None
    # Moving a task to another client. The caller must be able to act on the NEW client too.
    client_id: Optional[str] = None
    # Changed here, not cleared: like every field of this PATCH, an absent value
    # means "leave it", so an estimate can be corrected but not taken off again.
    estimated_minutes: Optional[int] = None

    @field_validator("due_date", mode="before")
    @classmethod
    def _check_due(cls, v):
        return _check_due_date(v)

    @field_validator("assigned_to", mode="before")
    @classmethod
    def _unassigned_is_none(cls, v):
        return _blank_to_none(v)

    @field_validator("estimated_minutes", mode="before")
    @classmethod
    def _check_estimate(cls, v):
        return task_estimate.check_minutes(v)


@router.get("")
def list_tasks(
    client_id: Optional[str] = None,
    status: Optional[str] = None,
    assigned_to: Optional[str] = None,
    priority: Optional[str] = None,
    kanban: bool = False,
    current_user: dict = Depends(rbac("task", "read")),
):
    firm_id = current_user.get("firm_id")
    tasks = task_repo.find_all(
        firm_id=firm_id,
        client_id=client_id,
        status=status,
        assigned_to=assigned_to,
        priority=priority,
    )
    tasks = filter_by_client(current_user, tasks)  # M2/M5: assignment scope

    clients = client_repo.find_all(firm_id=firm_id)
    client_map = {c["id"]: c["client_name"] for c in clients}
    enriched = [{**t, "client_name": client_map.get(t.get("client_id", ""), "Unknown")} for t in tasks]

    if kanban:
        return api_response(True, {"kanban": group_tasks_by_status(enriched), "total": len(enriched)})

    return api_response(True, {"tasks": enriched, "total": len(enriched)})


@router.post("")
def create_task(body: TaskCreate, current_user: dict = Depends(rbac("task", "write"))):
    # M5 Gap C: body client_id isn't seen by the path/query guard — enforce here.
    assert_client_access(current_user, body.client_id)
    client = client_repo.find_by_id(body.client_id, current_user.get("firm_id"))
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    # C4: verify assignee belongs to the same firm before creating the task.
    if body.assigned_to:
        from repositories.user_repository import user_repo
        assignee = user_repo.find_by_id(body.assigned_to, firm_id=current_user.get("firm_id"))
        if not assignee or assignee.get("firm_id") != current_user.get("firm_id"):
            raise HTTPException(status_code=422, detail="Assignee not found in this firm")
    now = datetime.now(timezone.utc).isoformat()
    fields = body.model_dump()
    if fields.get("assigned_to"):
        # `tasks` carries the assignee TWICE (`assigned_to` and `assignee_id`, both pointing at users) and `/api/workload`
        # reads `assignee_id` FIRST; a task made with only one is invisible to whichever reader looks at the other. Every
        # task made from a template or a recurring configuration, and every reassignment below, writes both.
        fields["assignee_id"] = fields["assigned_to"]
    if fields.get("estimated_minutes") is None:
        # An absent estimate is an absent KEY, not a NULL one: this is the hot path
        # for every task made by hand, and naming a column the table does not have
        # yet (the window between a deploy and migration 452) would refuse them all.
        fields.pop("estimated_minutes", None)
    task = task_repo.create({
        **fields,
        "firm_id": current_user.get("firm_id"),
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
    })
    activity = log_activity(
        action="compliance_task_created",
        description=f"Task created: {task['title']}",
        client_id=body.client_id,
        entity_type="task",
        entity_id=task["id"],
    )
    # H10: immutable audit_log records (log_activity above is a no-op stub).
    try:
        log_event(
            current_user.get("firm_id"), "task", task["id"], "create",
            actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            new_data={"title": task["title"], "status": task.get("status"),
                      "assigned_to": body.assigned_to},
        )
        if body.assigned_to:
            log_event(
                current_user.get("firm_id"), "task", task["id"], "assign",
                actor_id=current_user.get("auth_user_id"),
                actor_email=current_user.get("email"),
                new_data={"assigned_to": body.assigned_to},
            )
    except Exception:
        pass
    try:
        from repositories.task_extras_repository import task_extras_repo
        task_extras_repo.log_event(
            task_id=task["id"],
            event_type="created",
            firm_id=current_user.get("firm_id"),
            actor_id=current_user.get("id"),
            actor_name=current_user.get("full_name") or current_user.get("email"),
            new_value={"title": task["title"], "status": task.get("status"), "priority": task.get("priority")},
        )
        if body.assigned_to:
            task_extras_repo.log_event(
                task_id=task["id"],
                event_type="assigned",
                firm_id=current_user.get("firm_id"),
                actor_id=current_user.get("id"),
                actor_name=current_user.get("full_name") or current_user.get("email"),
                new_value={"assigned_to": body.assigned_to},
            )
    except Exception:
        pass

    # Send notification if task is assigned
    if body.assigned_to:
        try:
            from services.notification_service import notification_service
            from repositories.user_repository import user_repo
            assignee = user_repo.find_by_id(body.assigned_to, firm_id=current_user.get("firm_id"))
            if assignee:
                notification_service.notify_task_assigned(task, assignee, current_user)
        except Exception:
            pass

    return api_response(True, {"task": task, "activity": activity})


def _changes_in(body: "TaskUpdate", task: dict, current_user: dict, firm_id: str) -> dict:
    """What a PATCH actually changes: the fields sent, minus any that equal what is held, plus the two a null clears."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    # An explicit null clears these two and nothing else (see TaskUpdate).
    for cleared in ("due_date", "assigned_to"):
        if cleared in body.model_fields_set and getattr(body, cleared) is None:
            updates[cleared] = None
    # A form sends the whole task. A value equal to what is held is not a change: the same status is not a transition (the
    # machine would refuse it), and the same client is not a move.
    for unchanged in ("status", "client_id"):
        if unchanged in updates and updates[unchanged] == task.get(unchanged):
            updates.pop(unchanged)

    if "client_id" in updates:
        # The new client must be one this caller may act on, and one of this firm: the old client was checked by the caller,
        # and a task moved to a client nobody checked would be written into books the caller cannot open.
        assert_client_access(current_user, updates["client_id"], detail="Client not found")
        if not client_repo.find_by_id(updates["client_id"], firm_id):
            raise HTTPException(status_code=404, detail="Client not found")
    return updates


def _notify_reassignment(task: dict, updated: dict, updates: dict, firm_id: str, current_user: dict) -> None:
    """Tell the people concerned when a task's assignee changed. Best effort: a notification that fails never fails the PATCH."""
    if "assigned_to" not in updates or updates["assigned_to"] == task.get("assigned_to"):
        return
    try:
        from services.notification_service import notification_service
        from repositories.user_repository import user_repo

        new_assignee_id = updates["assigned_to"]
        old_assignee_id = task.get("assigned_to")

        if new_assignee_id:
            new_assignee = user_repo.find_by_id(new_assignee_id, firm_id=firm_id)
            if new_assignee:
                if old_assignee_id:
                    # This is a reassignment
                    old_assignee = user_repo.find_by_id(old_assignee_id, firm_id=firm_id)
                    if old_assignee:
                        reason = "Task load rebalancing"
                        notification_service.notify_task_reassigned(
                            updated, old_assignee, new_assignee, reason,
                            reassigned_by=current_user)
                else:
                    # This is a new assignment
                    notification_service.notify_task_assigned(updated, new_assignee, current_user)
    except Exception:
        pass


@router.patch("/{task_id}")
def update_task(task_id: str, body: TaskUpdate, current_user: dict = Depends(rbac("task", "write"))):
    firm_id = current_user.get("firm_id")
    task = task_repo.find_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("firm_id") and task["firm_id"] != firm_id:
        raise HTTPException(status_code=404, detail="Task not found")
    # tasks.client_id is NOT NULL and the row is already in hand, so this costs
    # no extra query. 404, not 403, matching the firm check just above — the
    # status code must not become an oracle for which task ids are real.
    assert_client_access(current_user, task.get("client_id"), detail="Task not found")

    updates = _changes_in(body, task, current_user, firm_id)

    # C4: verify assignee belongs to the same firm before applying the update.
    if "assigned_to" in updates and updates["assigned_to"] is not None:
        from repositories.user_repository import user_repo
        assignee = user_repo.find_by_id(updates["assigned_to"], firm_id=firm_id)
        if not assignee or assignee.get("firm_id") != firm_id:
            raise HTTPException(status_code=422, detail="Assignee not found in this firm")

    if "status" in updates:
        if not is_valid_transition(task["status"], updates["status"]):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status transition: {task['status']} → {updates['status']}"
            )
        if updates["status"] == "completed":
            updates["completed_at"] = datetime.now(timezone.utc).isoformat()

    if "assigned_to" in updates:
        # `tasks` carries the assignee TWICE (`assigned_to` and `assignee_id`,
        # migrations 063 / 113 / 232, both pointing at users since 424) and the two
        # readers pick differently: `/api/workload` reads `assignee_id` FIRST. A
        # reassignment that wrote only `assigned_to` left the old person holding the
        # task in the workload figures for any task that had been made with both —
        # which every task made from a template or a recurring configuration is.
        updates["assignee_id"] = updates["assigned_to"]

    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    updated = task_repo.update(task_id, updates)

    try:
        from repositories.task_extras_repository import task_extras_repo
        actor_id = current_user.get("id")
        actor_name = current_user.get("full_name") or current_user.get("email")
        if "status" in updates:
            task_extras_repo.log_event(
                task_id=task_id,
                event_type="status_changed",
                firm_id=firm_id,
                actor_id=actor_id,
                actor_name=actor_name,
                old_value={"status": task.get("status")},
                new_value={"status": updates["status"]},
            )
        if "assigned_to" in updates and updates["assigned_to"] != task.get("assigned_to"):
            event_type = ("unassigned" if updates["assigned_to"] is None
                          else "assigned" if not task.get("assigned_to") else "reassigned")
            task_extras_repo.log_event(
                task_id=task_id,
                event_type=event_type,
                firm_id=firm_id,
                actor_id=actor_id,
                actor_name=actor_name,
                old_value={"assigned_to": task.get("assigned_to")},
                new_value={"assigned_to": updates["assigned_to"]},
            )
        if "priority" in updates and updates["priority"] != task.get("priority"):
            task_extras_repo.log_event(
                task_id=task_id,
                event_type="priority_changed",
                firm_id=firm_id,
                actor_id=actor_id,
                actor_name=actor_name,
                old_value={"priority": task.get("priority")},
                new_value={"priority": updates["priority"]},
            )
    except Exception:
        pass

    # H10: immutable audit_log records for assignment + completion transitions
    # (the task_extras_repo events above write task_timeline_events, a different store).
    try:
        old_status = task.get("status")
        old_assignee = task.get("assigned_to")
        if "assigned_to" in updates and updates["assigned_to"] != old_assignee:
            action = ("unassign" if updates["assigned_to"] is None
                      else "reassign" if old_assignee else "assign")
            log_event(
                firm_id, "task", task_id, action,
                actor_id=current_user.get("auth_user_id"),
                actor_email=current_user.get("email"),
                old_data={"assigned_to": old_assignee},
                new_data={"assigned_to": updates["assigned_to"]},
            )
        if "client_id" in updates:
            log_event(
                firm_id, "task", task_id, "update",
                actor_id=current_user.get("auth_user_id"),
                actor_email=current_user.get("email"),
                old_data={"client_id": task.get("client_id")},
                new_data={"client_id": updates["client_id"]},
            )
        if "status" in updates and updates["status"] != old_status:
            if updates["status"] == "completed":
                log_event(
                    firm_id, "task", task_id, "complete",
                    actor_id=current_user.get("auth_user_id"),
                    actor_email=current_user.get("email"),
                    old_data={"status": old_status},
                    new_data={"status": updates["status"]},
                )
            elif old_status == "completed":
                log_event(
                    firm_id, "task", task_id, "reopen",
                    actor_id=current_user.get("auth_user_id"),
                    actor_email=current_user.get("email"),
                    old_data={"status": old_status},
                    new_data={"status": updates["status"]},
                )
    except Exception:
        pass

    _notify_reassignment(task, updated, updates, firm_id, current_user)

    return api_response(True, {"task": updated})



@router.get("/transitions")
def status_transitions(current_user: dict = Depends(rbac("task", "read"))):
    """Which status a task may move to from each status. Served so a screen offers only the moves the server will accept
    (the machine lives here, in `services/task_service`; a copy in the browser would drift)."""
    from services.task_service import VALID_TRANSITIONS
    return api_response(True, {"transitions": VALID_TRANSITIONS})


def _is_a_foreign_key_refusal(exc: Exception) -> bool:
    text = str(exc).lower()
    return "23503" in text or "foreign key" in text or "violates foreign key" in text


@router.delete("/{task_id}")
def delete_task(task_id: str, current_user: dict = Depends(rbac("task", "delete"))):
    """Delete a task, and say so in the audit log with the whole row.

    The browser used to delete straight from the table: no assignment check beyond row security, no record of what was
    removed, and a task still linked to a reminder or a compliance record was refused by the database with an error the
    screen never read, so it looked deleted until the next load. Here a refusal for that reason is a 409 that says so.

    A hard delete, as it always was: `tasks` has a `deleted_at` column, but half a dozen readers (workload, analytics,
    capacity, health) do not filter on it, so hiding a task by stamping it would leave it counted. Its tags, dependencies
    and timeline events, which have no foreign key to `tasks` (migration 063), are removed with it.
    """
    firm_id = current_user.get("firm_id")
    task = task_repo.find_by_id(task_id)
    if not task or (task.get("firm_id") and task["firm_id"] != firm_id):
        raise HTTPException(status_code=404, detail="Task not found")
    assert_client_access(current_user, task.get("client_id"), detail="Task not found")

    try:
        task_repo.delete(task_id, firm_id=firm_id)
    except Exception as exc:
        if _is_a_foreign_key_refusal(exc):
            raise HTTPException(
                status_code=409,
                detail=("This task is linked to a reminder or a compliance record, so it cannot be deleted. "
                        "Complete it instead, or remove what refers to it first.")) from exc
        raise

    try:
        from repositories.task_extras_repository import task_extras_repo
        task_extras_repo.purge_task(task_id, firm_id=firm_id)
    except Exception:
        _logger.warning("task %s was deleted but its tags, dependencies or events were not all removed", task_id, exc_info=True)
    log_event(
        firm_id, "task", task_id, "delete",
        actor_id=current_user.get("auth_user_id"),
        actor_email=current_user.get("email"),
        old_data={k: task.get(k) for k in ("title", "status", "priority", "client_id", "assigned_to", "assignee_id",
                                           "due_date", "description", "workflow_id", "created_at")},
    )
    return api_response(True, {"deleted": True, "id": task_id})


def _assert_firmwide_job(current_user: dict, what: str) -> None:
    """Refuse a firm-WIDE job to a caller who is not firm-wide (`core.authz.assert_firmwide_job`, the one guard)."""
    assert_firmwide_job(current_user, what)


@router.post("/trigger-escalations")
def trigger_escalations(current_user: dict = Depends(rbac("task", "write"))):
    _assert_firmwide_job(current_user, "Escalation processing")
    from services.escalation_service import escalation_service
    firm_id = current_user.get("firm_id")
    result = escalation_service.run_all_escalations(firm_id)
    return api_response(True, result)


@router.post("/trigger-scheduler-run")
def trigger_scheduler_run(force: bool = False, current_user: dict = Depends(rbac("task", "write"))):
    """
    Run all daily automation jobs for this firm now: recurring generation,
    escalations, and invoice overdue transitions. Idempotent per day unless
    force=true. Intended for external cron services and manual catch-up.

    Answers at once with whether the run started: the sweep is minutes, so it runs on a thread and `GET /api/scheduler/status`
    shows the outcome.
    """
    _assert_firmwide_job(current_user, "The daily automation batch")
    from jobs.scheduler import start_daily_jobs
    firm_id = current_user.get("firm_id")
    return api_response(True, start_daily_jobs(firm_id, force))


@router.post("/trigger-recurring-generation")
def trigger_recurring_generation(current_user: dict = Depends(rbac("task", "write"))):
    _assert_firmwide_job(current_user, "Recurring task generation")
    from jobs.recurring_task_job import run_recurring_generation_job
    firm_id = current_user.get("firm_id")
    result = run_recurring_generation_job(firm_id=firm_id)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Unknown error"))
    return api_response(True, {"generated": result.get("count"), "tasks": result.get("tasks")})
