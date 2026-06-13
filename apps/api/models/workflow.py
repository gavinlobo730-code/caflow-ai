"""Pydantic models for Phase 10 Workflow Automation Engine."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Optional, List, Literal
from pydantic import BaseModel, Field


# ── Enums (as Literal types) ─────────────────────────────────────────────────

TriggerType = Literal[
    # Client events
    "client_created", "client_archived", "client_restored",
    "client_health_changed", "client_risk_detected",
    # Compliance events
    "gst_due", "tds_due", "itr_due", "roc_due",
    # Lifecycle events
    "lead_created", "proposal_sent", "onboarding_started",
    "onboarding_completed", "renewal_due",
    # Relationship events
    "relationship_created", "conflict_detected", "ownership_changed",
    # Health events
    "health_score_below_threshold", "health_alert_created",
    # AI events
    "ai_risk_detected", "ai_opportunity_detected",
    # Schedule (synthetic trigger for schedule-based workflows)
    "scheduled",
]

StepType = Literal["trigger", "condition", "action", "approval", "delay", "branch"]
WorkflowStatus = Literal["pending", "running", "completed", "failed", "cancelled", "waiting_approval"]
ApprovalStatus = Literal["pending", "approved", "rejected", "escalated", "expired"]
ActionLogStatus = Literal["pending", "running", "success", "failed", "skipped"]
ConditionOperator = Literal[">", "<", "=", ">=", "<=", "contains", "equals", "starts_with", "before", "after", "within_days"]
LogicalGroup = Literal["AND", "OR"]
WorkflowCategory = Literal[
    "general", "onboarding", "compliance", "accounting", "payroll",
    "gst", "tds", "mca", "income_tax", "lifecycle", "health", "relationship",
]


# ── Condition models ─────────────────────────────────────────────────────────

class ConditionRule(BaseModel):
    field: str
    operator: ConditionOperator
    value: str
    value_type: Literal["string", "number", "date", "boolean"] = "string"


class ConditionGroup(BaseModel):
    logic: LogicalGroup = "AND"
    rules: List[ConditionRule] = Field(default_factory=list)
    groups: List["ConditionGroup"] = Field(default_factory=list)  # nested


ConditionGroup.model_rebuild()


# ── Step config shapes ────────────────────────────────────────────────────────

class ActionConfig(BaseModel):
    action_type: str  # create_task|assign_task|send_email|send_notification|update_status|...
    params: dict[str, Any] = Field(default_factory=dict)


class ApprovalConfig(BaseModel):
    approver_role: Literal["Partner", "Manager"]
    title: str
    description: str = ""
    due_hours: int = 48  # hours before escalation
    escalate_to: Optional[Literal["Partner", "Manager"]] = None


class DelayConfig(BaseModel):
    delay_hours: int = 1


class BranchConfig(BaseModel):
    condition: ConditionGroup
    true_label: str = "Yes"
    false_label: str = "No"


# ── Step model ────────────────────────────────────────────────────────────────

class WorkflowStepIn(BaseModel):
    step_order: int
    step_type: StepType
    name: str
    description: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)
    next_step_id: Optional[str] = None
    true_branch_step_id: Optional[str] = None
    false_branch_step_id: Optional[str] = None


class WorkflowStepOut(WorkflowStepIn):
    id: str
    template_id: str
    created_at: datetime


# ── Template models ───────────────────────────────────────────────────────────

class WorkflowTemplateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    category: WorkflowCategory = "general"
    trigger_type: TriggerType
    trigger_config: dict[str, Any] = Field(default_factory=dict)
    conditions: dict[str, Any] = Field(default_factory=dict)  # ConditionGroup serialized
    steps: List[WorkflowStepIn] = Field(default_factory=list)
    is_active: bool = True


class WorkflowTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[WorkflowCategory] = None
    trigger_type: Optional[TriggerType] = None
    trigger_config: Optional[dict[str, Any]] = None
    conditions: Optional[dict[str, Any]] = None
    steps: Optional[List[WorkflowStepIn]] = None
    is_active: Optional[bool] = None


class WorkflowTemplateOut(BaseModel):
    id: str
    firm_id: str
    name: str
    description: Optional[str]
    category: str
    trigger_type: str
    trigger_config: dict[str, Any]
    conditions: dict[str, Any]
    is_active: bool
    is_system: bool
    version: int
    execution_count: int
    success_count: int
    failure_count: int
    avg_duration_ms: Optional[int]
    steps: List[WorkflowStepOut] = Field(default_factory=list)
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime


# ── Instance models ───────────────────────────────────────────────────────────

class WorkflowInstanceOut(BaseModel):
    id: str
    firm_id: str
    template_id: str
    template_name: Optional[str] = None
    client_id: Optional[str]
    trigger_event: str
    trigger_data: dict[str, Any]
    status: str
    current_step_id: Optional[str]
    context_data: dict[str, Any]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    failed_at: Optional[datetime]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime


# ── Action log models ─────────────────────────────────────────────────────────

class ActionLogOut(BaseModel):
    id: str
    instance_id: str
    step_id: Optional[str]
    step_name: Optional[str]
    action_type: str
    action_config: dict[str, Any]
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    duration_ms: Optional[int]
    result_data: Optional[dict[str, Any]]
    error_message: Optional[str]
    created_at: datetime


# ── Execution / audit ─────────────────────────────────────────────────────────

class ExecutionOut(BaseModel):
    id: str
    instance_id: str
    firm_id: str
    event_type: str
    event_data: dict[str, Any]
    actor_id: Optional[str]
    actor_type: str
    created_at: datetime


# ── Approval models ───────────────────────────────────────────────────────────

class ApprovalResponseIn(BaseModel):
    decision: Literal["approved", "rejected"]
    response_notes: Optional[str] = None


class ApprovalOut(BaseModel):
    id: str
    instance_id: str
    firm_id: str
    step_id: Optional[str]
    step_name: Optional[str]
    approver_role: str
    approver_id: Optional[str]
    status: str
    title: str
    description: Optional[str]
    context_data: dict[str, Any]
    due_at: Optional[datetime]
    escalation_at: Optional[datetime]
    escalated_to: Optional[str]
    responded_at: Optional[datetime]
    responder_id: Optional[str]
    response_notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    # Enriched
    template_name: Optional[str] = None
    client_name: Optional[str] = None


# ── Schedule models ───────────────────────────────────────────────────────────

class WorkflowScheduleIn(BaseModel):
    template_id: str
    name: str
    cron_expression: str
    timezone: str = "Asia/Kolkata"
    is_active: bool = True


class WorkflowScheduleOut(BaseModel):
    id: str
    firm_id: str
    template_id: str
    template_name: Optional[str] = None
    name: str
    cron_expression: str
    timezone: str
    is_active: bool
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    last_run_status: Optional[str]
    run_count: int
    created_at: datetime
    updated_at: datetime


# ── Failure models ────────────────────────────────────────────────────────────

class FailureOut(BaseModel):
    id: str
    instance_id: str
    firm_id: str
    step_id: Optional[str]
    step_name: Optional[str]
    error_type: str
    error_message: str
    error_data: Optional[dict[str, Any]]
    retry_count: int
    resolved: bool
    resolved_at: Optional[datetime]
    created_at: datetime


# ── Analytics ─────────────────────────────────────────────────────────────────

class WorkflowAnalytics(BaseModel):
    template_id: str
    template_name: str
    total_executions: int
    successful: int
    failed: int
    success_rate: int  # integer percentage
    avg_duration_ms: Optional[int]
    pending_approvals: int
    executions_last_7_days: int
    executions_last_30_days: int
