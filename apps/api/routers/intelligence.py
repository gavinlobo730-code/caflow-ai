"""
Phase 1.3 Intelligence Layer endpoints.

Read endpoints use ai.read (all staff); journal suggestion approval requires
accounting.write since it creates a draft journal entry. Approved entries
still go through the normal Partner posting flow (accounting.approve).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from models.common import api_response
from core.permissions import rbac

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


@router.get("/compliance-risk")
def compliance_risk(current_user: dict = Depends(rbac("ai", "read"))):
    """Per-client predictive compliance risk scores and predicted misses."""
    from services.intelligence_service import compute_compliance_risk
    return api_response(True, compute_compliance_risk(current_user["firm_id"]))


@router.get("/relationship-health")
def relationship_health(current_user: dict = Depends(rbac("ai", "read"))):
    """Client relationship / engagement health scores."""
    from services.intelligence_service import compute_relationship_health
    return api_response(True, compute_relationship_health(current_user["firm_id"]))


@router.get("/recommendations")
def recommendations(current_user: dict = Depends(rbac("ai", "read"))):
    """Proactive compliance, client and operational recommendations."""
    from services.intelligence_service import compute_recommendations
    return api_response(True, compute_recommendations(current_user["firm_id"]))


@router.get("/workload-insights")
def workload_insights(current_user: dict = Depends(rbac("workload", "read"))):
    """Team workload insights: overload, idle members, unassigned backlog."""
    from services.intelligence_service import compute_workload_insights
    return api_response(True, compute_workload_insights(current_user["firm_id"]))


@router.get("/journal-suggestions")
def journal_suggestions(
    client_id: Optional[str] = None,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Suggested recurring journal entries detected from posted-entry patterns."""
    from services.intelligence_service import compute_journal_suggestions
    return api_response(True, compute_journal_suggestions(current_user["firm_id"], client_id))


class JournalSuggestionApproval(BaseModel):
    client_id: Optional[str] = None
    narration: str
    entry_type: str = "Journal"
    suggested_date: Optional[str] = None
    lines: list[dict]


@router.post("/journal-suggestions/approve")
def approve_journal_suggestion_endpoint(
    body: JournalSuggestionApproval,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """
    Approve a journal suggestion — creates a DRAFT journal entry.
    Posting to the ledger still requires Partner approval (accounting.approve).
    """
    from services.intelligence_service import approve_journal_suggestion
    try:
        entry = approve_journal_suggestion(
            firm_id=current_user["firm_id"],
            suggestion=body.model_dump(),
            user_id=current_user.get("id"),
        )
        return api_response(True, {"entry": entry})
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
