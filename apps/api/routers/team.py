"""The firm's staff list, with each member's live task workload.

ONE ROUTE, AND THE SECOND ONE WAS DELETED ON 24-09-2026.

`PATCH /api/team/{user_id}/role` lived here and was a SECOND WRITE PATH for a
member's role: `PATCH /api/identity/users/{user_id}/role` is the other, it is
what `app/team/page.tsx` calls through `api.identity.changeRole`, and it sits
beside the suspend, reactivate and force-logout routes that make up the rest of
that lifecycle. Nothing in either frontend ever called this one — the
reachability ratchet had it as the single unreachable route on this prefix —
so the two never had to agree, and they did not: this copy validated against a
local `VALID_ROLES` set while identity.py validates against `_CANONICAL`, and
only identity.py's route is part of the state machine the Team screen drives.

Two write paths for one fact is the shape this codebase refuses everywhere
else (one posting kernel, one supplier master, one filing demo). The one that
no screen could reach is the one that goes.
"""
from fastapi import APIRouter, Depends
from models.common import api_response
from core.permissions import rbac
from core.authz import filter_by_client
from repositories.user_repository import user_repo
from repositories.task_repository import task_repo
from services.task_service import compute_team_workload

router = APIRouter(prefix="/api/team", tags=["team"])


@router.get("")
def list_team(current_user: dict = Depends(rbac("team", "read"))):
    firm_id = current_user.get("firm_id")
    members = user_repo.find_all(firm_id=firm_id)
    # M2: the per-member counts are computed over every task in the firm.
    # Narrow to the caller's assigned book first — tasks.client_id is NOT NULL
    # (migration 002), so nothing legitimately client-less is dropped here.
    tasks = filter_by_client(current_user, task_repo.find_all(firm_id=firm_id))
    workload = compute_team_workload(tasks, members)
    return api_response(True, {"team": workload, "total": len(workload)})
