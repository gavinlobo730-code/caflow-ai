from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from models.common import api_response
from mock_data import MOCK_TASKS, MOCK_CLIENTS, CLIENT_INDEX, TASK_INDEX
from services.task_service import (
    is_valid_transition, compute_task_urgency, group_tasks_by_status, compute_team_workload
)
from services.activity_service import log_activity
from datetime import datetime, timezone, date
import uuid

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

TASK_STORE = list(MOCK_TASKS)  # in-memory store for mock mutations


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
def dashboard_summary():
    today_str = date.today().isoformat()
    tasks = TASK_STORE
    due_today = [t for t in tasks if t.get("due_date") == today_str and t["status"] != "completed"]
    overdue = [t for t in tasks if t.get("due_date") and t.get("due_date") < today_str and t["status"] not in ("completed", "not_applicable")]
    waiting = [t for t in tasks if t["status"] == "waiting_client"]
    review = [t for t in tasks if t["status"] == "review_required"]
    return api_response(True, {
        "active_clients": len(MOCK_CLIENTS),
        "tasks_due_today": len(due_today),
        "overdue_tasks": len(overdue),
        "waiting_client": len(waiting),
        "review_required": len(review),
        "total_open_tasks": len([t for t in tasks if t["status"] != "completed"]),
    })


@router.get("")
def list_tasks(
    client_id: Optional[str] = None,
    status: Optional[str] = None,
    assigned_to: Optional[str] = None,
    priority: Optional[str] = None,
    kanban: bool = False,
):
    tasks = list(TASK_STORE)
    if client_id:
        tasks = [t for t in tasks if t["client_id"] == client_id]
    if status:
        tasks = [t for t in tasks if t["status"] == status]
    if assigned_to:
        tasks = [t for t in tasks if t.get("assigned_to") == assigned_to]
    if priority:
        tasks = [t for t in tasks if t["priority"] == priority]

    client_map = {c["id"]: c["client_name"] for c in MOCK_CLIENTS}
    enriched = [
        {**t, "client_name": client_map.get(t["client_id"], "Unknown"),
         "urgency": compute_task_urgency(t.get("due_date"), t["status"])}
        for t in tasks
    ]

    if kanban:
        return api_response(True, {"kanban": group_tasks_by_status(enriched), "total": len(enriched)})

    return api_response(True, {"tasks": enriched, "total": len(enriched)})


@router.post("")
def create_task(body: TaskCreate):
    if body.client_id not in CLIENT_INDEX:
        raise HTTPException(status_code=404, detail="Client not found")
    now = datetime.now(timezone.utc).isoformat()
    task = {
        "id": str(uuid.uuid4()),
        **body.model_dump(),
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    TASK_STORE.append(task)
    activity = log_activity(
        action="compliance_task_created",
        description=f"Task created: {task['title']}",
        client_id=body.client_id,
        entity_type="task",
        entity_id=task["id"],
    )
    return api_response(True, {"task": task, "activity": activity})


@router.patch("/{task_id}")
def update_task(task_id: str, body: TaskUpdate):
    task = next((t for t in TASK_STORE if t["id"] == task_id), None)
    if not task:
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
    task.update(updates)
    return api_response(True, {"task": task})
