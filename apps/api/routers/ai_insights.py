from fastapi import APIRouter
from models.common import api_response
from domain.ai_insight_service import (
    get_all_insights,
    get_insight_feed,
    generate_insights_for_client,
    acknowledge_insight,
    dismiss_insight,
)

router = APIRouter(prefix="/api/ai-insights", tags=["ai-insights"])


@router.get("")
def list_insights(client_id: str = None, status: str = None, category: str = None):
    insights = get_all_insights(client_id=client_id, status=status, category=category)
    return api_response(True, insights)


@router.get("/feed")
def insight_feed(limit: int = 20):
    feed = get_insight_feed(limit=limit)
    return api_response(True, feed)


@router.post("/generate/{client_id}")
def generate_insights(client_id: str):
    insights = generate_insights_for_client(client_id)
    return api_response(True, {"generated": len(insights), "insights": insights})


@router.patch("/{insight_id}/acknowledge")
def ack_insight(insight_id: str):
    insight = acknowledge_insight(insight_id)
    if insight is None:
        return api_response(False, None, "Insight not found")
    return api_response(True, insight)


@router.patch("/{insight_id}/dismiss")
def dis_insight(insight_id: str):
    insight = dismiss_insight(insight_id)
    if insight is None:
        return api_response(False, None, "Insight not found")
    return api_response(True, insight)
