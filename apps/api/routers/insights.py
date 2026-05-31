from fastapi import APIRouter
from models.common import api_response
from mock_data import MOCK_AI_INSIGHTS

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("")
def list_insights(client_id: str | None = None, status: str | None = None):
    insights = MOCK_AI_INSIGHTS
    if client_id:
        insights = [i for i in insights if i["client_id"] == client_id]
    if status:
        insights = [i for i in insights if i["status"] == status]
    return api_response(True, {"insights": insights, "total": len(insights)})


@router.patch("/{insight_id}/status")
def update_insight_status(insight_id: str, new_status: str):
    allowed = {"acknowledged", "resolved", "dismissed"}
    if new_status not in allowed:
        return api_response(False, None, f"status must be one of: {allowed}")
    # In production: UPDATE ai_insights SET status=... WHERE id=...
    return api_response(True, {"id": insight_id, "status": new_status})
