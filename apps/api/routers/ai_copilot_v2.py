"""
Phase 11 — AI Copilot Platform API.
Endpoints: conversations, messages, summaries, recommendations, intelligence, executive dashboard.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from models.common import api_response
from models.ai_copilot import (
    ConversationCreateIn, MessageIn, FeedbackIn,
    RecommendationActionIn, AIActionIn,
    GLOBAL_SUGGESTED_QUESTIONS, CLIENT_SUGGESTED_QUESTIONS, COMPLIANCE_SUGGESTED_QUESTIONS,
)
from core.permissions import rbac
from core.authz import assert_client_access, can_access_client, effective_client_ids, filter_by_client

router = APIRouter(prefix="/api/copilot", tags=["AI Copilot Phase 11"])


def _repo():
    from repositories.ai_copilot_repository import ai_copilot_repo
    return ai_copilot_repo


def _service():
    from domain.ai_copilot_service import ai_copilot_service
    return ai_copilot_service


def _assert_conversation_scope(current_user: dict, conversation_id: str) -> dict:
    """Resolve an ai_conversations row and 404 unless it belongs to the
    caller's firm and (if client-scoped) the caller may access its client.

    Does NOT apply MessageIn.context_id's per-message override — send_message
    layers that check on top of this one, since a message may target a
    different (still caller-authorized) context than its conversation."""
    conv = _repo().get_conversation(current_user["firm_id"], conversation_id)
    if not conv or not can_access_client(current_user, conv.get("context_id")):
        raise HTTPException(404, "Conversation not found")
    return conv


def _assert_message_scope(current_user: dict, message_id: str) -> dict:
    """Resolve an ai_messages row via its conversation and 404 unless the
    caller may access the conversation's client context. ai_messages itself
    carries no context_id — only its parent conversation does."""
    msg = _repo().get_message(current_user["firm_id"], message_id)
    if not msg:
        raise HTTPException(404, "Message not found")
    conv = _repo().get_conversation(current_user["firm_id"], msg["conversation_id"])
    if not conv or not can_access_client(current_user, conv.get("context_id")):
        raise HTTPException(404, "Message not found")
    return msg


# ── Conversations ─────────────────────────────────────────────────────────────

@router.get("/conversations")
def list_conversations(
    is_archived: bool = False,
    limit: int = Query(30, le=100),
    current_user: dict = Depends(rbac("task", "read")),
):
    firm_id = current_user["firm_id"]
    user_id = current_user.get("auth_user_id", "user-dev")
    convs = _repo().list_conversations(firm_id, user_id, is_archived=is_archived, limit=limit)
    # M2: already scoped to the caller's own conversations (user_id), but a
    # conversation's context_id could name a client the caller was later
    # unassigned from — narrow the same way any other client-bearing list is.
    convs = filter_by_client(current_user, convs, key="context_id")
    return api_response(True, {"conversations": convs})


@router.post("/conversations")
def create_conversation(
    payload: ConversationCreateIn,
    current_user: dict = Depends(rbac("task", "read")),
):
    firm_id = current_user["firm_id"]
    user_id = current_user.get("auth_user_id", "user-dev")
    # M2 audit finding: context_id is caller-supplied ("e.g., client_id" per
    # ConversationCreateIn) and was never checked — every OTHER endpoint that
    # reads or acts on a context_id (send_message, quick_chat,
    # client_intelligence) already does.
    assert_client_access(current_user, payload.context_id)
    conv = _repo().create_conversation(firm_id, user_id, payload.model_dump())
    return api_response(True, conv)


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    current_user: dict = Depends(rbac("task", "read")),
):
    # M2 audit finding: row-addressed by conversation_id, firm-scoped only —
    # a conversation's context_id (client) was never checked, so any member
    # of the firm could read another's client-scoped AI chat history.
    conv = _assert_conversation_scope(current_user, conversation_id)
    messages = _repo().list_messages(conversation_id)
    return api_response(True, {**conv, "messages": messages})


@router.post("/conversations/{conversation_id}/archive")
def archive_conversation(
    conversation_id: str,
    current_user: dict = Depends(rbac("task", "read")),
):
    # M2 audit finding: same shape as get_conversation above.
    _assert_conversation_scope(current_user, conversation_id)
    updated = _repo().archive_conversation(current_user["firm_id"], conversation_id)
    if not updated:
        raise HTTPException(404, "Conversation not found")
    return api_response(True, updated)


# ── Messages / Chat ────────────────────────────────────────────────────────────

@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    payload: MessageIn,
    current_user: dict = Depends(rbac("task", "read")),
):
    firm_id = current_user["firm_id"]
    user_id = current_user.get("auth_user_id", "user-dev")
    conv = _repo().get_conversation(firm_id, conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    ctx_id = payload.context_id or conv.get("context_id")
    # M2: a client-scoped chat may only target an authorized client; scope the
    # injected firm context to the caller's effective client set.
    assert_client_access(current_user, ctx_id)
    result = await _service().chat(
        firm_id=firm_id,
        user_id=user_id,
        conversation_id=conversation_id,
        user_message=payload.content,
        context_type=payload.context_type or conv.get("context_type", "global"),
        context_id=ctx_id,
        allowed_client_ids=effective_client_ids(current_user),
    )
    return api_response(True, result)


@router.post("/messages/{message_id}/feedback")
def rate_message(
    message_id: str,
    payload: FeedbackIn,
    current_user: dict = Depends(rbac("task", "read")),
):
    # M2 audit finding: row-addressed by message_id, firm-scoped only — a
    # message's conversation (and that conversation's client context) was
    # never checked, so any member of the firm could rate/comment on
    # another's client-scoped chat message.
    _assert_message_scope(current_user, message_id)
    firm_id = current_user["firm_id"]
    user_id = current_user.get("auth_user_id", "user-dev")
    feedback = _repo().add_feedback(firm_id, message_id, user_id, payload.rating,
                                     payload.feedback_text, payload.tags)
    return api_response(True, feedback)


# ── Quick chat (no conversation required) ────────────────────────────────────

@router.post("/chat")
async def quick_chat(
    payload: MessageIn,
    current_user: dict = Depends(rbac("task", "read")),
):
    """Single-turn chat without persisting conversation history."""
    firm_id = current_user["firm_id"]
    user_id = current_user.get("auth_user_id", "user-dev")
    # M2: gate the requested client context before doing any work.
    assert_client_access(current_user, payload.context_id)
    # Auto-create a conversation for this quick chat
    conv = _repo().create_conversation(firm_id, user_id, {
        "context_type": payload.context_type or "global",
        "context_id": payload.context_id,
    })
    result = await _service().chat(
        firm_id=firm_id,
        user_id=user_id,
        conversation_id=conv["id"],
        user_message=payload.content,
        context_type=payload.context_type or "global",
        context_id=payload.context_id,
        allowed_client_ids=effective_client_ids(current_user),
    )
    return api_response(True, {**result, "conversation_id": conv["id"]})


# ── Suggested questions ────────────────────────────────────────────────────────

@router.get("/suggestions")
def get_suggestions(
    context_type: str = "global",
    current_user: dict = Depends(rbac("task", "read")),
):
    if context_type == "client":
        return api_response(True, {"suggestions": CLIENT_SUGGESTED_QUESTIONS})
    if context_type == "compliance":
        return api_response(True, {"suggestions": COMPLIANCE_SUGGESTED_QUESTIONS})
    return api_response(True, {"suggestions": GLOBAL_SUGGESTED_QUESTIONS})


# ── Intelligence endpoints ─────────────────────────────────────────────────────

@router.get("/intelligence/client/{client_id}")
async def client_intelligence(
    client_id: str,
    current_user: dict = Depends(rbac("client", "read")),
):
    """Generate AI-powered intelligence report for a specific client."""
    assert_client_access(current_user, client_id)
    firm_id = current_user["firm_id"]
    result = await _service().get_client_intelligence(firm_id, client_id)
    return api_response(True, result)


@router.get("/intelligence/compliance")
async def compliance_intelligence(
    current_user: dict = Depends(rbac("compliance", "read")),
):
    """Generate AI-powered compliance intelligence for all clients."""
    firm_id = current_user["firm_id"]
    result = await _service().get_compliance_intelligence(firm_id)
    return api_response(True, result)


@router.get("/intelligence/workflows")
async def workflow_intelligence(
    current_user: dict = Depends(rbac("task", "read")),
):
    """Generate AI-powered workflow performance intelligence."""
    firm_id = current_user["firm_id"]
    result = await _service().get_workflow_intelligence(firm_id)
    return api_response(True, result)


@router.get("/intelligence/relationships")
async def relationship_intelligence(
    current_user: dict = Depends(rbac("client", "read")),
):
    """Generate AI-powered relationship and ownership risk analysis."""
    firm_id = current_user["firm_id"]
    result = await _service().get_relationship_intelligence(firm_id)
    return api_response(True, result)


# ── Executive Dashboard ────────────────────────────────────────────────────────

@router.get("/executive-dashboard")
async def executive_dashboard(
    current_user: dict = Depends(rbac("firm", "read")),
):
    """AI-powered executive dashboard with firm-wide intelligence."""
    firm_id = current_user["firm_id"]
    result = await _service().get_executive_dashboard(firm_id)
    return api_response(True, result)


# ── Recommendations ───────────────────────────────────────────────────────────

@router.get("/recommendations")
def list_recommendations(
    client_id: Optional[str] = None,
    status: Optional[str] = "pending",
    rec_type: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = Query(50, le=200),
    current_user: dict = Depends(rbac("task", "read")),
):
    firm_id = current_user["firm_id"]
    # M2 audit finding: client_id is caller-supplied and was never checked;
    # without one, the firm's whole recommendation list was returned
    # unfiltered by assignment.
    if client_id:
        assert_client_access(current_user, client_id)
    recs = _repo().list_recommendations(firm_id, client_id=client_id, status=status,
                                          rec_type=rec_type, priority=priority, limit=limit)
    if not client_id:
        recs = filter_by_client(current_user, recs)
    return api_response(True, {"recommendations": recs, "total": len(recs)})


@router.post("/recommendations/{rec_id}/action")
def act_recommendation(
    rec_id: str,
    payload: RecommendationActionIn,
    current_user: dict = Depends(rbac("task", "write")),
):
    firm_id = current_user["firm_id"]
    user_id = current_user.get("auth_user_id", "user-dev")
    # M2 audit finding: row-addressed by rec_id, firm-scoped only —
    # ai_recommendations.client_id (nullable — firm-wide recs like
    # airec-003 exist) was never checked before acting on it.
    rec = _repo().get_recommendation(firm_id, rec_id)
    if not rec or not can_access_client(current_user, rec.get("client_id")):
        raise HTTPException(404, "Recommendation not found")
    updated = _service().act_on_recommendation(firm_id, rec_id, payload.action, user_id, payload.snooze_days)
    if not updated:
        raise HTTPException(404, "Recommendation not found")
    return api_response(True, updated)


# ── AI Actions (manual execution) ─────────────────────────────────────────────

@router.post("/actions")
def execute_ai_action(
    payload: AIActionIn,
    current_user: dict = Depends(rbac("task", "write")),
):
    """Execute an AI-recommended action after user confirmation."""
    firm_id = current_user["firm_id"]
    user_id = current_user.get("auth_user_id", "user-dev")
    # M2 audit finding: when linked to a recommendation, that recommendation's
    # client was never checked — same shape as act_recommendation above.
    if payload.recommendation_id:
        rec = _repo().get_recommendation(firm_id, payload.recommendation_id)
        if not rec or not can_access_client(current_user, rec.get("client_id")):
            raise HTTPException(404, "Recommendation not found")
    action = _repo().create_ai_action(firm_id, {
        "action_type": payload.action_type,
        "action_data": payload.action_data,
        "recommendation_id": payload.recommendation_id,
    })
    # Execute the action (simplified — in production this would call the respective service)
    result = {"action_id": action["id"], "action_type": payload.action_type, "status": "executed"}
    _repo().complete_ai_action(action["id"], result, user_id)
    return api_response(True, result)


# ── Summaries ─────────────────────────────────────────────────────────────────

@router.get("/summaries")
def list_summaries(
    summary_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    current_user: dict = Depends(rbac("task", "read")),
):
    firm_id = current_user["firm_id"]
    # M2 audit finding: entity_id can be a client_id (context_type "client"
    # summaries are stored keyed by client_id) and was never checked.
    if entity_id:
        assert_client_access(current_user, entity_id)
    from repositories.ai_copilot_repository import MOCK_SUMMARIES
    summaries = [s for s in MOCK_SUMMARIES if s["firm_id"] == firm_id and not s["is_stale"]]
    if summary_type:
        summaries = [s for s in summaries if s["summary_type"] == summary_type]
    if entity_id:
        summaries = [s for s in summaries if s.get("entity_id") == entity_id]
    return api_response(True, {"summaries": summaries})
