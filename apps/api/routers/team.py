from fastapi import APIRouter, Depends
from models.common import api_response
from core.auth import get_current_user
from mock_data import MOCK_TEAM_MEMBERS, MOCK_TASKS
from services.task_service import compute_team_workload

router = APIRouter(prefix="/api/team", tags=["team"])


@router.get("")
def list_team(current_user: dict = Depends(get_current_user)):
    workload = compute_team_workload(MOCK_TASKS, MOCK_TEAM_MEMBERS)
    return api_response(True, {"team": workload, "total": len(workload)})
