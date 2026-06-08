"""
Legacy /api/insights route — delegates to ai_insights_repository.
Frontend lib/api/index.ts calls this endpoint; the newer /api/ai-insights
prefix is also wired for the same repository.
"""
from fastapi import APIRouter, Depends
from models.common import api_response
from core.permissions import rbac
from repositories.ai_insights_repository import ai_insights_repo

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("")
def list_insights(
    client_id: str | None = None,
    status: str | None = None,
    current_user: dict = Depends(rbac("report", "read")),
):
    firm_id = current_user.get("firm_id")
    insights = ai_insights_repo.find_all(firm_id=firm_id, client_id=client_id, status=status)
    return api_response(True, {"insights": insights, "total": len(insights)})


@router.patch("/{insight_id}/status")
def update_insight_status(
    insight_id: str,
    new_status: str,
    current_user: dict = Depends(rbac("report", "write")),
):
    allowed = {"acknowledged", "resolved", "dismissed"}
    if new_status not in allowed:
        return api_response(False, None, f"status must be one of: {allowed}")
    firm_id = current_user.get("firm_id")
    updated = ai_insights_repo.update_status(insight_id, new_status, firm_id=firm_id)
    if not updated:
        return api_response(False, None, "Insight not found")
    return api_response(True, {"id": insight_id, "status": new_status})
