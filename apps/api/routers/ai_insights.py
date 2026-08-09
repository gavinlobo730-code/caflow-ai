from fastapi import APIRouter, Depends
from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access, can_access_client, effective_client_ids, filter_by_client
from domain.ai_insight_service import (
    get_all_insights,
    get_insight_feed,
    generate_insights_for_client,
    acknowledge_insight,
    dismiss_insight,
    get_cross_client_patterns,
)

router = APIRouter(prefix="/api/ai-insights", tags=["ai-insights"])


def _assert_insight_scope(current_user: dict, insight_id: str) -> dict | None:
    """Resolve insight_id to its row and verify the caller's client-assignment
    scope (ai_insights.client_id is set on every real row). Returns None for
    both a missing row and an out-of-scope one — the caller renders one fixed
    "Insight not found" either way, so a wrong-client guess cannot be
    distinguished from a real 404."""
    from repositories.ai_insights_repository import ai_insights_repo
    row = ai_insights_repo.find_by_id(insight_id, firm_id=current_user.get("firm_id"))
    if row is None or not can_access_client(current_user, row.get("client_id")):
        return None
    return row


@router.get("")
def list_insights(
    client_id: str = None,
    status: str = None,
    category: str = None,
    current_user: dict = Depends(rbac("report", "read")),
):
    firm_id = current_user.get("firm_id")
    if client_id:
        assert_client_access(current_user, client_id)
    insights = get_all_insights(firm_id=firm_id, client_id=client_id, status=status, category=category)
    if not client_id:
        # No client named — narrow the firm-wide list to the caller's own
        # assigned book instead of handing every client's insights to an
        # Executive/Reviewer/Manager who only asked for "my" insights.
        insights = filter_by_client(current_user, insights)
    return api_response(True, insights)


@router.get("/cross-client")
def cross_client_patterns(
    current_user: dict = Depends(rbac("report", "read")),
):
    """
    GET /api/ai-insights/cross-client
    Returns cross-client intelligence patterns: shared directors with compliance risk,
    same issue appearing across multiple clients, group-wide cash flow signals, etc.
    Chapter 17 Product Bible — cross-client AI intelligence.

    TENANT ISOLATION. This used to accept `?firm_id=` and prefer it over the
    caller's own, so any authenticated user could read another **firm's**
    cross-client intelligence by supplying its id — an endpoint whose whole
    purpose is to aggregate across a firm's client base. That is a tenant
    boundary, not a client-assignment one: different firms are different
    customers. The parameter is gone rather than validated; cross-firm access
    belongs to the platform-admin surface (routers/platform.py), not here.

    NOT CLIENT-SCOPED (see EXEMPT in test_router_client_scope.py):
    get_cross_client_patterns is a hardcoded stub — the same fixed sample
    patterns for every firm regardless of real data (its own docstring:
    "In production this would query the DB... For now return realistic mock
    patterns."). There is no real client-scoped row here for an assignment
    check to gate; the response names no real client at all.
    """
    patterns = get_cross_client_patterns(firm_id=current_user.get("firm_id"))
    return api_response(True, {"patterns": patterns})


@router.get("/feed")
def insight_feed(limit: int = 20, current_user: dict = Depends(rbac("report", "read"))):
    """Firm-wide feed of open insights, confined to the caller's own
    assigned book — the same F2 convention compliance_record_service.
    get_firm_summary uses (allowed_client_ids=effective_client_ids(...))."""
    firm_id = current_user.get("firm_id")
    feed = get_insight_feed(
        firm_id=firm_id, limit=limit, allowed_client_ids=effective_client_ids(current_user),
    )
    return api_response(True, feed)


@router.post("/generate/{client_id}")
def generate_insights(client_id: str, current_user: dict = Depends(rbac("report", "write"))):
    assert_client_access(current_user, client_id)
    firm_id = current_user.get("firm_id")
    insights = generate_insights_for_client(client_id, firm_id=firm_id)
    return api_response(True, {"generated": len(insights), "insights": insights})


@router.patch("/{insight_id}/acknowledge")
def ack_insight(insight_id: str, current_user: dict = Depends(rbac("report", "write"))):
    firm_id = current_user.get("firm_id")
    if _assert_insight_scope(current_user, insight_id) is None:
        return api_response(False, None, "Insight not found")
    insight = acknowledge_insight(insight_id, firm_id=firm_id)
    if insight is None:
        return api_response(False, None, "Insight not found")
    return api_response(True, insight)


@router.patch("/{insight_id}/dismiss")
def dis_insight(insight_id: str, current_user: dict = Depends(rbac("report", "write"))):
    firm_id = current_user.get("firm_id")
    if _assert_insight_scope(current_user, insight_id) is None:
        return api_response(False, None, "Insight not found")
    insight = dismiss_insight(insight_id, firm_id=firm_id)
    if insight is None:
        return api_response(False, None, "Insight not found")
    return api_response(True, insight)
