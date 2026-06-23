from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from models.common import api_response
from core.permissions import rbac
from core.authz import filter_by_client, assert_client_access
from repositories.task_repository import task_repo
from repositories.client_repository import client_repo
from services.task_service import is_valid_transition, group_tasks_by_status
from services.activity_service import log_activity
from datetime import datetime, timezone

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


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


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[str] = None
    due_date: Optional[str] = None


@router.get("/summary/dashboard")
def dashboard_summary(current_user: dict = Depends(rbac("task", "read"))):
    from domain.task_service import task_domain_service
    firm_id = current_user.get("firm_id")
    return api_response(True, task_domain_service.get_dashboard_summary(firm_id=firm_id))


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
        assignee = user_repo.find_by_id(body.assigned_to)
        if not assignee or assignee.get("firm_id") != current_user.get("firm_id"):
            raise HTTPException(status_code=422, detail="Assignee not found in this firm")
    now = datetime.now(timezone.utc).isoformat()
    task = task_repo.create({
        **body.model_dump(),
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
            assignee = user_repo.find_by_id(body.assigned_to)
            if assignee:
                notification_service.notify_task_assigned(task, assignee, current_user)
        except Exception:
            pass

    return api_response(True, {"task": task, "activity": activity})


@router.patch("/{task_id}")
def update_task(task_id: str, body: TaskUpdate, current_user: dict = Depends(rbac("task", "write"))):
    firm_id = current_user.get("firm_id")
    task = task_repo.find_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("firm_id") and task["firm_id"] != firm_id:
        raise HTTPException(status_code=404, detail="Task not found")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}

    # C4: verify assignee belongs to the same firm before applying the update.
    if "assigned_to" in updates and updates["assigned_to"] is not None:
        from repositories.user_repository import user_repo
        assignee = user_repo.find_by_id(updates["assigned_to"])
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
            event_type = "assigned" if not task.get("assigned_to") else "reassigned"
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

    # Send notifications if task is reassigned (or newly assigned)
    if "assigned_to" in updates and updates["assigned_to"] != task.get("assigned_to"):
        try:
            from services.notification_service import notification_service
            from repositories.user_repository import user_repo

            new_assignee_id = updates["assigned_to"]
            old_assignee_id = task.get("assigned_to")

            if new_assignee_id:
                new_assignee = user_repo.find_by_id(new_assignee_id)
                if new_assignee:
                    if old_assignee_id:
                        # This is a reassignment
                        old_assignee = user_repo.find_by_id(old_assignee_id)
                        if old_assignee:
                            reason = "Task load rebalancing"
                            notification_service.notify_task_reassigned(updated, old_assignee, new_assignee, reason)
                    else:
                        # This is a new assignment
                        notification_service.notify_task_assigned(updated, new_assignee, current_user)
        except Exception:
            pass

    return api_response(True, {"task": updated})


@router.post("/trigger-escalations")
def trigger_escalations(current_user: dict = Depends(rbac("task", "write"))):
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
    """
    from jobs.scheduler import run_daily_jobs
    firm_id = current_user.get("firm_id")
    result = run_daily_jobs(firm_id=firm_id, force=force)
    return api_response(True, result)


@router.post("/trigger-recurring-generation")
def trigger_recurring_generation(current_user: dict = Depends(rbac("task", "write"))):
    from jobs.recurring_task_job import run_recurring_generation_job
    firm_id = current_user.get("firm_id")
    result = run_recurring_generation_job(firm_id=firm_id)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Unknown error"))
    return api_response(True, {"generated": result.get("count"), "tasks": result.get("tasks")})
