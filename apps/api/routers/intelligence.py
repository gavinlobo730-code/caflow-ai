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
from core.authz import assert_client_access, effective_client_ids
from middleware.rate_limit import ai_limit

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


@router.get("/compliance-risk")
def compliance_risk(current_user: dict = Depends(rbac("ai", "read"))):
    """Per-client predictive compliance risk scores and predicted misses."""
    from services.intelligence_service import compute_compliance_risk
    # None for a firm-wide role; a set of assigned ids otherwise. Every row
    # this returns names its client, so it must be narrowed.
    return api_response(True, compute_compliance_risk(
        current_user["firm_id"], effective_client_ids(current_user)))


@router.get("/relationship-health")
def relationship_health(current_user: dict = Depends(rbac("ai", "read"))):
    """Client relationship / engagement health scores."""
    from services.intelligence_service import compute_relationship_health
    # None for a firm-wide role; a set of assigned ids otherwise. Every row
    # this returns names its client, so it must be narrowed.
    return api_response(True, compute_relationship_health(
        current_user["firm_id"], effective_client_ids(current_user)))


@router.get("/recommendations")
def recommendations(current_user: dict = Depends(rbac("ai", "read"))):
    """Proactive compliance, client and operational recommendations."""
    from services.intelligence_service import compute_recommendations
    # None for a firm-wide role; a set of assigned ids otherwise. Every row
    # this returns names its client, so it must be narrowed.
    return api_response(True, compute_recommendations(
        current_user["firm_id"], effective_client_ids(current_user)))


@router.get("/digest")
async def digest(current_user: dict = Depends(rbac("ai", "read")),
                 _limit: None = Depends(ai_limit("intelligence"))):
    """What needs attention today, across the caller's own clients (ai-25).

    Every count is read off an existing check — the compliance-risk engine, the
    overdue-task read, the nightly books check's stored findings — and equals what
    that check reports. A model words the lines when something needs attention and
    is discarded if it adds a figure; with no model the plain sentence is the
    answer. `domain/practice/digest` is the rule and `services/digest_service`
    fetches; this decides nothing.

    `ai_limit` is declared AFTER `rbac()` so a permission refusal spends nothing.
    Each section follows the access of the screen it summarises and a section the
    caller may not see, or that could not be read, is named in `gaps`.
    """
    from services import digest_service
    # None for a firm-wide role; a set of assigned ids otherwise. Every section
    # names or counts clients, so every read inside is narrowed by this one value.
    return api_response(True, await digest_service.todays_digest(
        current_user, effective_client_ids(current_user)))


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
    # An explicit client_id is mount-guard-covered; the default (None) reads
    # the whole firm, so narrow that case too.
    if client_id:
        assert_client_access(current_user, client_id)
    return api_response(True, compute_journal_suggestions(
        current_user["firm_id"], client_id, effective_client_ids(current_user)))


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
    # Creates a DRAFT journal entry against body.client_id — the mount guard
    # inspects JSON bodies, but this makes the check visible at the write.
    assert_client_access(current_user, body.client_id)
    try:
        entry = approve_journal_suggestion(
            firm_id=current_user["firm_id"],
            suggestion=body.model_dump(),
            user_id=current_user.get("id"),
        )
        return api_response(True, {"entry": entry})
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
