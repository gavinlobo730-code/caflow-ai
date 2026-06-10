from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from models.common import api_response
from core.permissions import rbac
from repositories.task_template_repository import task_template_repo

router = APIRouter(prefix="/api/task-templates", tags=["task-templates"])


class TemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    default_priority: str = "medium"
    estimated_hours: Optional[int] = None
    tags: list[str] = []
    default_assignee_role: Optional[str] = None


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    default_priority: Optional[str] = None
    estimated_hours: Optional[int] = None
    tags: Optional[list[str]] = None
    default_assignee_role: Optional[str] = None


class InstantiateRequest(BaseModel):
    client_id: str
    assignee_id: Optional[str] = None
    due_date: Optional[str] = None
    title_override: Optional[str] = None


@router.get("")
def list_templates(current_user: dict = Depends(rbac("task", "read"))):
    firm_id = current_user.get("firm_id")
    templates = task_template_repo.find_all(firm_id=firm_id)
    return api_response(True, {"templates": templates, "total": len(templates)})


@router.get("/{template_id}")
def get_template(template_id: str, current_user: dict = Depends(rbac("task", "read"))):
    tpl = task_template_repo.find_by_id(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return api_response(True, {"template": tpl})


@router.post("")
def create_template(body: TemplateCreate, current_user: dict = Depends(rbac("task", "write"))):
    firm_id = current_user.get("firm_id")
    tpl = task_template_repo.create({
        "firm_id": firm_id,
        "name": body.name,
        "description": body.description,
        "default_priority": body.default_priority,
        "estimated_hours": body.estimated_hours,
        "tags": body.tags,
        "default_assignee_role": body.default_assignee_role,
    })
    return api_response(True, {"template": tpl})


@router.put("/{template_id}")
def update_template(template_id: str, body: TemplateUpdate, current_user: dict = Depends(rbac("task", "write"))):
    tpl = task_template_repo.find_by_id(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = task_template_repo.update(template_id, updates)
    return api_response(True, {"template": updated})


@router.delete("/{template_id}")
def delete_template(template_id: str, current_user: dict = Depends(rbac("task", "write"))):
    tpl = task_template_repo.find_by_id(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    if not tpl.get("firm_id"):
        raise HTTPException(status_code=403, detail="Cannot delete system templates")
    task_template_repo.delete(template_id)
    return api_response(True, {"deleted": True})


@router.post("/{template_id}/instantiate")
def instantiate_template(
    template_id: str,
    body: InstantiateRequest,
    current_user: dict = Depends(rbac("task", "write")),
):
    from datetime import datetime, timezone
    from repositories.task_extras_repository import task_extras_repo
    from core.supabase_client import get_supabase

    tpl = task_template_repo.find_by_id(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")

    firm_id = current_user.get("firm_id")
    now = datetime.now(timezone.utc).isoformat()

    db = get_supabase()
    task_data = {
        "firm_id": firm_id,
        "client_id": body.client_id,
        "title": body.title_override or tpl["name"],
        "description": tpl.get("description"),
        "status": "todo",
        "priority": tpl.get("default_priority", "medium"),
        "assigned_to": body.assignee_id,
        "assignee_id": body.assignee_id,
        "due_date": body.due_date,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    result = db.table("tasks").insert(task_data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create task")

    task = result.data[0]

    if tpl.get("tags"):
        for tag in tpl["tags"]:
            try:
                task_extras_repo.add_tag(firm_id=firm_id, task_id=task["id"], tag=tag)
            except Exception:
                pass

    try:
        task_extras_repo.log_event(
            task_id=task["id"],
            event_type="created",
            firm_id=firm_id,
            actor_id=current_user.get("id"),
            actor_name=current_user.get("full_name") or current_user.get("email"),
            new_value={"source": "template", "template_id": template_id, "template_name": tpl["name"]},
        )
    except Exception:
        pass

    return api_response(True, {"task": task})
