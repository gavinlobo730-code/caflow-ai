from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from models.common import api_response
from core.authz import assert_client_access, effective_client_ids
from core.permissions import rbac
from repositories.task_extras_repository import task_extras_repo
from repositories.task_repository import task_repo

router = APIRouter(prefix="/api/tasks", tags=["task-extras"])


# ── Client-assignment scope (M2) ──────────────────────────────────────────────
# `core.authz` makes only the **Partner** firm-wide (`_FIRMWIDE_ROLES`); a
# Manager, Executive or Reviewer sees only the clients in
# `user_client_assignments`. This router did not import core.authz at all.
#
# `tasks.client_id` is NOT NULL, and every handler here ALREADY loads its task
# firm-scoped and 404s when it is missing — so the client is in hand and the
# guard costs no extra query. `task_tags`, `task_dependencies` and
# `task_timeline_events` carry no client of their own (task_dependencies has no
# firm_id either); they are all reached through that task.

def _assert_task_scope(current_user: dict, task: dict) -> None:
    """Check the client of a task the caller has already loaded.

    Takes the ROW, not an id, because every caller has one by this point.
    Re-fetching would be a second query for an answer already on the desk.
    """
    assert_client_access(current_user, task.get("client_id"))


# ── Tags ─────────────────────────────────────────────────────────────────────

class AddTagBody(BaseModel):
    tag: str


@router.get("/{task_id}/tags")
def get_tags(task_id: str, current_user: dict = Depends(rbac("task", "read"))):
    task = task_repo.find_by_id(task_id, firm_id=current_user.get("firm_id"))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    _assert_task_scope(current_user, task)
    tags = task_extras_repo.get_tags(task_id)
    return api_response(True, {"tags": tags})


@router.post("/{task_id}/tags")
def add_tag(task_id: str, body: AddTagBody, current_user: dict = Depends(rbac("task", "write"))):
    firm_id = current_user.get("firm_id")
    task = task_repo.find_by_id(task_id, firm_id=firm_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    _assert_task_scope(current_user, task)
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
    _assert_task_scope(current_user, task)
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
    _assert_task_scope(current_user, task)
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
    _assert_task_scope(current_user, task)
    dep_task = task_repo.find_by_id(body.depends_on_task_id, firm_id=firm_id)
    if not dep_task:
        raise HTTPException(status_code=404, detail="Dependency task not found")
    # The dependency's own client too: the response and the timeline event echo
    # dep_task["title"], so linking to another client's task discloses it.
    _assert_task_scope(current_user, dep_task)
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
    _assert_task_scope(current_user, task)
    task_extras_repo.remove_dependency(task_id, dependency_id)
    return api_response(True, {"removed": True})


# ── Timeline ──────────────────────────────────────────────────────────────────

@router.get("/{task_id}/timeline")
def get_timeline(task_id: str, current_user: dict = Depends(rbac("task", "read"))):
    task = task_repo.find_by_id(task_id, firm_id=current_user.get("firm_id"))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    _assert_task_scope(current_user, task)
    events = task_extras_repo.get_timeline(task_id)
    return api_response(True, {"events": events, "total": len(events)})


# ── Firm-wide tag list ────────────────────────────────────────────────────────

@router.get("/tags/all")
def list_firm_tags(current_user: dict = Depends(rbac("task", "read"))):
    firm_id = current_user.get("firm_id")
    # A tag is free text somebody typed on a client's task —
    # "acme-gst-migration" names a client as surely as a client_id does — so an
    # autocomplete list is not a reason to hand out labels from books the caller
    # cannot open. effective_client_ids returns None for a firm-wide role, which
    # takes the single-query path this always had.
    tags = task_extras_repo.get_firm_tags(
        firm_id, allowed_client_ids=effective_client_ids(current_user))
    return api_response(True, {"tags": tags})
