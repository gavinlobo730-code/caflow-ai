"""Pydantic models for Phase 11 AI Copilot Platform."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Optional, List, Literal
from pydantic import BaseModel, Field


ContextType = Literal["global", "client", "compliance", "workflow", "executive", "relationship"]
SummaryType = Literal["client", "compliance", "workflow", "executive", "relationship"]
RecommendationType = Literal["risk", "opportunity", "compliance", "workflow", "relationship", "health"]
RecommendationPriority = Literal["critical", "high", "medium", "low"]
RecommendationStatus = Literal["pending", "accepted", "dismissed", "snoozed"]
ActionType = Literal["create_task", "send_notification", "trigger_workflow", "create_alert", "update_status"]


# ── Conversation models ───────────────────────────────────────────────────────

class ConversationCreateIn(BaseModel):
    title: Optional[str] = None
    context_type: ContextType = "global"
    context_id: Optional[str] = None  # e.g., client_id


class ConversationOut(BaseModel):
    id: str
    firm_id: str
    user_id: str
    title: str
    context_type: str
    context_id: Optional[str]
    message_count: int
    last_message_at: Optional[datetime]
    is_archived: bool
    created_at: datetime
    updated_at: datetime


# ── Message models ────────────────────────────────────────────────────────────

class MessageIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    context_type: Optional[ContextType] = None
    context_id: Optional[str] = None  # override conversation context for a single message


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    firm_id: str
    role: str  # user|assistant
    content: str
    tokens_used: Optional[int]
    model_used: Optional[str]
    metadata: dict[str, Any]
    feedback_rating: Optional[int]
    created_at: datetime


class ChatResponse(BaseModel):
    message: MessageOut
    suggested_questions: List[str] = Field(default_factory=list)
    referenced_entities: List[dict[str, Any]] = Field(default_factory=list)


# ── Feedback models ───────────────────────────────────────────────────────────

class FeedbackIn(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    feedback_text: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


# ── Summary models ────────────────────────────────────────────────────────────

class SummaryOut(BaseModel):
    id: str
    firm_id: str
    summary_type: str
    entity_id: Optional[str]
    title: str
    content: str
    key_points: List[str]
    metadata: dict[str, Any]
    model_used: str
    generated_at: datetime
    expires_at: Optional[datetime]
    is_stale: bool


# ── Recommendation models ─────────────────────────────────────────────────────

class RecommendationOut(BaseModel):
    id: str
    firm_id: str
    client_id: Optional[str]
    client_name: Optional[str] = None
    recommendation_type: str
    priority: str
    title: str
    description: str
    rationale: Optional[str]
    action_label: Optional[str]
    action_data: dict[str, Any]
    status: str
    snoozed_until: Optional[datetime]
    acted_by: Optional[str]
    acted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class RecommendationActionIn(BaseModel):
    action: Literal["accept", "dismiss", "snooze"]
    snooze_days: Optional[int] = None  # required when action=snooze


# ── AI Action models ──────────────────────────────────────────────────────────

class AIActionIn(BaseModel):
    action_type: ActionType
    action_data: dict[str, Any] = Field(default_factory=dict)
    recommendation_id: Optional[str] = None


class AIActionOut(BaseModel):
    id: str
    firm_id: str
    recommendation_id: Optional[str]
    action_type: str
    action_data: dict[str, Any]
    status: str
    executed_by: Optional[str]
    executed_at: Optional[datetime]
    result_data: Optional[dict[str, Any]]
    error_message: Optional[str]
    created_at: datetime


# ── Intelligence response shapes ──────────────────────────────────────────────

class ClientIntelligence(BaseModel):
    client_id: str
    client_name: str
    profile_summary: str
    compliance_summary: str
    health_summary: str
    risk_summary: str
    opportunity_summary: str
    recommended_actions: List[RecommendationOut]
    key_metrics: dict[str, Any]
    generated_at: datetime


class ComplianceIntelligence(BaseModel):
    firm_id: str
    upcoming_risks: List[dict[str, Any]]
    filing_bottlenecks: List[dict[str, Any]]
    missing_documents: List[dict[str, Any]]
    compliance_health_score: int
    at_risk_clients: List[dict[str, Any]]
    generated_at: datetime


class WorkflowIntelligence(BaseModel):
    firm_id: str
    failing_workflows: List[dict[str, Any]]
    overdue_approvals: List[dict[str, Any]]
    recurring_bottlenecks: List[dict[str, Any]]
    recommendations: List[RecommendationOut]
    generated_at: datetime


class RelationshipIntelligence(BaseModel):
    firm_id: str
    ownership_risks: List[dict[str, Any]]
    cross_client_conflicts: List[dict[str, Any]]
    high_risk_entities: List[dict[str, Any]]
    recommendations: List[RecommendationOut]
    generated_at: datetime


class ExecutiveDashboard(BaseModel):
    firm_id: str
    revenue_insights: dict[str, Any]
    capacity_insights: dict[str, Any]
    client_risk_insights: dict[str, Any]
    churn_signals: List[dict[str, Any]]
    growth_opportunities: List[dict[str, Any]]
    firm_health_summary: dict[str, Any]
    ai_summary: str
    generated_at: datetime


# ── Suggested questions ───────────────────────────────────────────────────────

GLOBAL_SUGGESTED_QUESTIONS = [
    "Which clients are at risk this month?",
    "Show pending GST filings due this week.",
    "Which clients have overdue tasks?",
    "Show onboarding bottlenecks.",
    "Which workflows have failed recently?",
    "Show clients with health score below 60.",
    "What TDS returns are due this quarter?",
    "Summarize firm compliance status.",
]

CLIENT_SUGGESTED_QUESTIONS = [
    "Summarize this client.",
    "What filings are pending for this client?",
    "Show this client's health score breakdown.",
    "Are there any risks for this client?",
    "What tasks are overdue for this client?",
    "Show relationship conflicts for this client.",
]

COMPLIANCE_SUGGESTED_QUESTIONS = [
    "Which GSTR-3B filings are due this month?",
    "Show TDS defaults across all clients.",
    "Which clients have pending advance tax?",
    "Show MCA due dates.",
    "Which clients have missing documents for filings?",
]
