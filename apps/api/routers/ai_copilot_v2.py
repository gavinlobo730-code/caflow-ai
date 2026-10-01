"""
Phase 11 — AI Copilot Platform API.
Endpoints: conversations, messages, intelligence, executive dashboard.
(The recommendations, actions and summaries routes were deleted — see the note at
the foot of this file.)
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from models.common import api_response
from models.ai_copilot import (
    ConversationCreateIn, MessageIn, FeedbackIn,
    GLOBAL_SUGGESTED_QUESTIONS, CLIENT_SUGGESTED_QUESTIONS, COMPLIANCE_SUGGESTED_QUESTIONS,
)
from core.permissions import rbac
from middleware.rate_limit import ai_limit
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
    _limit: None = Depends(ai_limit("chat")),
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
    _limit: None = Depends(ai_limit("chat")),
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
    _limit: None = Depends(ai_limit("intelligence")),
):
    """Generate AI-powered intelligence report for a specific client."""
    assert_client_access(current_user, client_id)
    firm_id = current_user["firm_id"]
    result = await _service().get_client_intelligence(firm_id, client_id)
    return api_response(True, result)


@router.get("/intelligence/compliance")
async def compliance_intelligence(
    current_user: dict = Depends(rbac("compliance", "read")),
    _limit: None = Depends(ai_limit("intelligence")),
):
    """Generate AI-powered compliance intelligence for all clients."""
    firm_id = current_user["firm_id"]
    # "All clients" means the CALLER's clients. effective_client_ids returns
    # None for a Partner and a set for anyone assignment-scoped; this endpoint
    # answered across the whole firm for every role until 11-09-2026, and
    # firm:read reaches Manager while _FIRMWIDE_ROLES is Partner only.
    result = await _service().get_compliance_intelligence(
        firm_id, allowed_client_ids=effective_client_ids(current_user))
    return api_response(True, result)


@router.get("/intelligence/workflows")
async def workflow_intelligence(
    current_user: dict = Depends(rbac("task", "read")),
    _limit: None = Depends(ai_limit("intelligence")),
):
    """Generate AI-powered workflow performance intelligence."""
    firm_id = current_user["firm_id"]
    # "All clients" means the CALLER's clients. effective_client_ids returns
    # None for a Partner and a set for anyone assignment-scoped; this endpoint
    # answered across the whole firm for every role until 11-09-2026, and
    # firm:read reaches Manager while _FIRMWIDE_ROLES is Partner only.
    result = await _service().get_workflow_intelligence(
        firm_id, allowed_client_ids=effective_client_ids(current_user))
    return api_response(True, result)


@router.get("/intelligence/relationships")
async def relationship_intelligence(
    current_user: dict = Depends(rbac("client", "read")),
    _limit: None = Depends(ai_limit("intelligence")),
):
    """Generate AI-powered relationship and ownership risk analysis."""
    firm_id = current_user["firm_id"]
    # "All clients" means the CALLER's clients. effective_client_ids returns
    # None for a Partner and a set for anyone assignment-scoped; this endpoint
    # answered across the whole firm for every role until 11-09-2026, and
    # firm:read reaches Manager while _FIRMWIDE_ROLES is Partner only.
    result = await _service().get_relationship_intelligence(
        firm_id, allowed_client_ids=effective_client_ids(current_user))
    return api_response(True, result)


# ── Executive Dashboard ────────────────────────────────────────────────────────

@router.get("/executive-dashboard")
async def executive_dashboard(
    current_user: dict = Depends(rbac("firm", "read")),
    _limit: None = Depends(ai_limit("intelligence")),
):
    """The firm's operational position, computed from its records.

    Only the summary sentence can be a model's, and the payload says whether it
    was (`summary_source`) — see `get_executive_dashboard`."""
    firm_id = current_user["firm_id"]
    # "All clients" means the CALLER's clients. effective_client_ids returns
    # None for a Partner and a set for anyone assignment-scoped; this endpoint
    # answered across the whole firm for every role until 11-09-2026, and
    # firm:read reaches Manager while _FIRMWIDE_ROLES is Partner only.
    result = await _service().get_executive_dashboard(
        firm_id, allowed_client_ids=effective_client_ids(current_user))
    return api_response(True, result)


# ── What this router no longer has (ai-10) ──────────────────────────────────
#
# Four routes were DELETED, each because it looked like an AI feature and was not:
#
#   GET  /recommendations and POST /recommendations/{id}/action
#       `ai_recommendations` has had no production generator since the table was
#       built — `create_recommendation` has no caller outside tests — so the
#       Insights tab behind them was empty for every firm, and its empty state
#       said "All insights have been actioned", a congratulation for work that
#       was never produced. The "accept" button only flipped a status: the row's
#       `action_data` was never executed by anything.
#   POST /actions
#       Wrote an `ai_actions` row, set it `executed` and returned
#       `{"status": "executed"}` after a comment saying "simplified — in
#       production this would call the respective service". It executed nothing.
#       A status the code did not earn is the worst kind of fake: it is the one
#       a screen would have trusted.
#   GET  /summaries
#       Filtered the in-memory `MOCK_SUMMARIES` list directly, whatever the mode,
#       so in production it answered an empty list for every firm while the real
#       summaries sat in `ai_summaries` where only the intelligence endpoints
#       read them.
#
# The storage layer (`ai_recommendations` and its repository methods) stays: a
# real generator would need it. `tests/test_ai_surfaces_are_not_fake_or_dead.py`
# holds the rule that no AI route may serve a literal sample or claim an
# execution nothing performed.
