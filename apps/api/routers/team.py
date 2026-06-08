from fastapi import APIRouter, Depends
from models.common import api_response
from core.permissions import rbac
from repositories.user_repository import user_repo
from repositories.task_repository import task_repo
from services.task_service import compute_team_workload

router = APIRouter(prefix="/api/team", tags=["team"])


@router.get("")
def list_team(current_user: dict = Depends(rbac("team", "read"))):
    firm_id = current_user.get("firm_id")
    members = user_repo.find_all(firm_id=firm_id)
    tasks = task_repo.find_all(firm_id=firm_id)
    workload = compute_team_workload(tasks, members)
    return api_response(True, {"team": workload, "total": len(workload)})
