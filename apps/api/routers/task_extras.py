from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from models.common import api_response
from core.permissions import rbac
from repositories.task_extras_repository import task_extras_repo
from repositories.task_repository import task_repo

router = APIRouter(prefix="/api/tasks", tags=["task-extras"])


# ── Tags ─────────────────────────────────────────────────────────────────────

class AddTagBody(BaseModel):
    tag: str


@router.get("/{task_id}/tags")
def get_tags(task_id: str, current_user: dict = Depends(rbac("task", "read"))):
    task = task_repo.find_by_id(task_id, firm_id=current_user.get("firm_id"))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    tags = task_extras_repo.get_tags(task_id)
    return api_response(True, {"tags": tags})


@router.post("/{task_id}/tags")
def add_tag(task_id: str, body: AddTagBody, current_user: dict = Depends(rbac("task", "write"))):
    firm_id = current_user.get("firm_id")
    task = task_repo.find_by_id(task_id, firm_id=firm_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    tag = task_extras_repo.add_tag(firm_id=firm_id, task_id=task_id, tag=body.tag)
    try:
        task_extras_repo.log_event(
            task_id=task_id,
            event_type="tagged",
            firm_id=firm_id,
            actor_id=current_user.get("id"),
            actor_name=current_user.get("full_name") or current_user.get("email"),
            new_value={"tag": body.tag},
        )
    except Exception:
        pass
    return api_response(True, {"tag": tag})


@router.delete("/{task_id}/tags/{tag}")
def remove_tag(task_id: str, tag: str, current_user: dict = Depends(rbac("task", "write"))):
    task = task_repo.find_by_id(task_id, firm_id=current_user.get("firm_id"))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task_extras_repo.remove_tag(task_id, tag)
    return api_response(True, {"removed": True})


# ── Dependencies ──────────────────────────────────────────────────────────────

class AddDependencyBody(BaseModel):
    depends_on_task_id: str


@router.get("/{task_id}/dependencies")
def get_dependencies(task_id: str, current_user: dict = Depends(rbac("task", "read"))):
    task = task_repo.find_by_id(task_id, firm_id=current_user.get("firm_id"))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    deps = task_extras_repo.get_dependencies(task_id)
    return api_response(True, {"dependencies": deps})


@router.post("/{task_id}/dependencies")
def add_dependency(task_id: str, body: AddDependencyBody, current_user: dict = Depends(rbac("task", "write"))):
    firm_id = current_user.get("firm_id")
    if task_id == body.depends_on_task_id:
        raise HTTPException(status_code=400, detail="A task cannot depend on itself")
    task = task_repo.find_by_id(task_id, firm_id=firm_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    dep_task = task_repo.find_by_id(body.depends_on_task_id, firm_id=firm_id)
    if not dep_task:
        raise HTTPException(status_code=404, detail="Dependency task not found")
    try:
        dep = task_extras_repo.add_dependency(task_id, body.depends_on_task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        task_extras_repo.log_event(
            task_id=task_id,
            event_type="dependency_added",
            firm_id=current_user.get("firm_id"),
            actor_id=current_user.get("id"),
            actor_name=current_user.get("full_name") or current_user.get("email"),
            new_value={"depends_on": body.depends_on_task_id, "depends_on_title": dep_task.get("title")},
        )
    except Exception:
        pass
    return api_response(True, {"dependency": dep})


@router.delete("/{task_id}/dependencies/{dependency_id}")
def remove_dependency(task_id: str, dependency_id: str, current_user: dict = Depends(rbac("task", "write"))):
    task = task_repo.find_by_id(task_id, firm_id=current_user.get("firm_id"))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task_extras_repo.remove_dependency(task_id, dependency_id)
    return api_response(True, {"removed": True})


# ── Timeline ──────────────────────────────────────────────────────────────────

@router.get("/{task_id}/timeline")
def get_timeline(task_id: str, current_user: dict = Depends(rbac("task", "read"))):
    task = task_repo.find_by_id(task_id, firm_id=current_user.get("firm_id"))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    events = task_extras_repo.get_timeline(task_id)
    return api_response(True, {"events": events, "total": len(events)})


# ── Firm-wide tag list ────────────────────────────────────────────────────────

@router.get("/tags/all")
def list_firm_tags(current_user: dict = Depends(rbac("task", "read"))):
    firm_id = current_user.get("firm_id")
    tags = task_extras_repo.get_firm_tags(firm_id)
    return api_response(True, {"tags": tags})
