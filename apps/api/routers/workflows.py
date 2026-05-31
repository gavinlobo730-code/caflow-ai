from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from models.common import api_response
from services.workflow_service import (
    get_all_templates, get_template_by_id, instantiate_workflow_tasks
)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.get("")
def list_workflows():
    templates = get_all_templates()
    return api_response(True, {"workflows": templates, "total": len(templates)})


@router.get("/{workflow_id}")
def get_workflow(workflow_id: str):
    template = get_template_by_id(workflow_id)
    if not template:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return api_response(True, {"workflow": template})


class InstantiateRequest(BaseModel):
    client_id: str
    assigned_to: str
    base_due_date: str


@router.post("/{workflow_id}/instantiate")
def instantiate_workflow(workflow_id: str, body: InstantiateRequest):
    tasks = instantiate_workflow_tasks(
        workflow_id, body.client_id, body.assigned_to, body.base_due_date
    )
    if not tasks:
        raise HTTPException(status_code=404, detail="Workflow template not found")
    return api_response(True, {"tasks": tasks, "count": len(tasks)})
