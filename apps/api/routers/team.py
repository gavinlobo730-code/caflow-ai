from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from models.common import api_response
from core.permissions import rbac
from repositories.user_repository import user_repo
from repositories.task_repository import task_repo
from services.task_service import compute_team_workload
from services.audit_service import log_event

router = APIRouter(prefix="/api/team", tags=["team"])

VALID_ROLES = {"Partner", "Manager", "Executive", "Reviewer", "Client"}


class RoleUpdate(BaseModel):
    role: str


@router.get("")
def list_team(current_user: dict = Depends(rbac("team", "read"))):
    firm_id = current_user.get("firm_id")
    members = user_repo.find_all(firm_id=firm_id)
    tasks = task_repo.find_all(firm_id=firm_id)
    workload = compute_team_workload(tasks, members)
    return api_response(True, {"team": workload, "total": len(workload)})


@router.patch("/{user_id}/role")
def update_user_role(
    user_id: str,
    body: RoleUpdate,
    current_user: dict = Depends(rbac("team", "write")),
):
    """Update a team member's role — Partners only."""
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}")

    firm_id = current_user.get("firm_id")
    member = user_repo.find_by_id(user_id)
    if not member or member.get("firm_id") != firm_id:
        raise HTTPException(status_code=404, detail="Team member not found")

    old_role = member.get("role")
    updated = user_repo.update(user_id, {"role": body.role})
    log_event(
        firm_id, "user_role", user_id, "update",
        actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
        old_data={"role": old_role}, new_data={"role": body.role},
    )
    return api_response(True, {"user": updated})
