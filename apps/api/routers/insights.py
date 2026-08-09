"""
Legacy /api/insights route — delegates to ai_insights_repository.
Frontend lib/api/index.ts calls this endpoint; the newer /api/ai-insights
prefix is also wired for the same repository.
"""
from fastapi import APIRouter, Depends
from models.common import api_response
from core.permissions import rbac
from core.authz import can_access_client, filter_by_client
from repositories.ai_insights_repository import ai_insights_repo

router = APIRouter(prefix="/api/insights", tags=["insights"])


def _assert_insight_scope(current_user: dict, insight_id: str) -> dict | None:
    """Resolve insight_id to its row and verify the caller's client-assignment
    scope. Returns None for both a missing row and an out-of-scope one — the
    caller renders one fixed "Insight not found" either way, so a wrong-client
    guess cannot be distinguished from a real 404. Same shape as the resolver
    of the same name in ai_insights.py, which serves the same table under the
    newer /api/ai-insights prefix."""
    row = ai_insights_repo.find_by_id(insight_id, firm_id=current_user.get("firm_id"))
    if row is None or not can_access_client(current_user, row.get("client_id")):
        return None
    return row


@router.get("")
def list_insights(
    client_id: str | None = None,
    status: str | None = None,
    current_user: dict = Depends(rbac("report", "read")),
):
    firm_id = current_user.get("firm_id")
    insights = ai_insights_repo.find_all(firm_id=firm_id, client_id=client_id, status=status)
    insights = filter_by_client(current_user, insights)  # M2/M5: assignment scope
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
    # M2: update_status scopes by firm_id only — an unassigned caller could
    # acknowledge/resolve/dismiss another staff member's client's insight by
    # guessing an id. Resolve the row's owner first.
    if _assert_insight_scope(current_user, insight_id) is None:
        return api_response(False, None, "Insight not found")
    updated = ai_insights_repo.update_status(insight_id, new_status, firm_id=firm_id)
    if not updated:
        return api_response(False, None, "Insight not found")
    return api_response(True, {"id": insight_id, "status": new_status})
