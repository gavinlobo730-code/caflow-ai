from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from models.common import api_response
from core.permissions import rbac
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

    clients = client_repo.find_all(firm_id=firm_id)
    client_map = {c["id"]: c["client_name"] for c in clients}
    enriched = [{**t, "client_name": client_map.get(t.get("client_id", ""), "Unknown")} for t in tasks]

    if kanban:
        return api_response(True, {"kanban": group_tasks_by_status(enriched), "total": len(enriched)})

    return api_response(True, {"tasks": enriched, "total": len(enriched)})


@router.post("")
def create_task(body: TaskCreate, current_user: dict = Depends(rbac("task", "write"))):
    client = client_repo.find_by_id(body.client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
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
    return api_response(True, {"task": updated})
