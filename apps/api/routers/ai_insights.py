from fastapi import APIRouter, Depends
from models.common import api_response
from core.permissions import rbac
from domain.ai_insight_service import (
    get_all_insights,
    get_insight_feed,
    generate_insights_for_client,
    acknowledge_insight,
    dismiss_insight,
)

router = APIRouter(prefix="/api/ai-insights", tags=["ai-insights"])


@router.get("")
def list_insights(
    client_id: str = None,
    status: str = None,
    category: str = None,
    current_user: dict = Depends(rbac("report", "read")),
):
    firm_id = current_user.get("firm_id")
    insights = get_all_insights(firm_id=firm_id, client_id=client_id, status=status, category=category)
    return api_response(True, insights)


@router.get("/feed")
def insight_feed(limit: int = 20, current_user: dict = Depends(rbac("report", "read"))):
    firm_id = current_user.get("firm_id")
    feed = get_insight_feed(firm_id=firm_id, limit=limit)
    return api_response(True, feed)


@router.post("/generate/{client_id}")
def generate_insights(client_id: str, current_user: dict = Depends(rbac("report", "write"))):
    firm_id = current_user.get("firm_id")
    insights = generate_insights_for_client(client_id, firm_id=firm_id)
    return api_response(True, {"generated": len(insights), "insights": insights})


@router.patch("/{insight_id}/acknowledge")
def ack_insight(insight_id: str, current_user: dict = Depends(rbac("report", "write"))):
    firm_id = current_user.get("firm_id")
    insight = acknowledge_insight(insight_id, firm_id=firm_id)
    if insight is None:
        return api_response(False, None, "Insight not found")
    return api_response(True, insight)


@router.patch("/{insight_id}/dismiss")
def dis_insight(insight_id: str, current_user: dict = Depends(rbac("report", "write"))):
    firm_id = current_user.get("firm_id")
    insight = dismiss_insight(insight_id, firm_id=firm_id)
    if insight is None:
        return api_response(False, None, "Insight not found")
    return api_response(True, insight)
