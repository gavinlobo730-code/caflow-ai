"""Repository for Phase 10 Workflow Automation Engine."""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta
from typing import Optional, Any
from repositories.base import BaseRepository


def _now() -> str:
    return datetime.utcnow().isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


class WorkflowRepository(BaseRepository):

    # ── Templates ─────────────────────────────────────────────────────────────

    def list_templates(
        self,
        firm_id: str,
        category: Optional[str] = None,
        trigger_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        templates = [t for t in MOCK_TEMPLATES if t["firm_id"] in (firm_id, "system")]
        if category:
            templates = [t for t in templates if t["category"] == category]
        if trigger_type:
            templates = [t for t in templates if t["trigger_type"] == trigger_type]
        if is_active is not None:
            templates = [t for t in templates if t["is_active"] == is_active]
        if search:
            q = search.lower()
            templates = [t for t in templates if q in t["name"].lower() or q in (t.get("description") or "").lower()]
        return templates[offset: offset + limit]

    def get_template(self, firm_id: str, template_id: str) -> Optional[dict]:
        for t in MOCK_TEMPLATES:
            if t["id"] == template_id and t["firm_id"] in (firm_id, "system"):
                t["steps"] = self.list_steps(template_id)
                return t
        return None

    def create_template(self, firm_id: str, data: dict, user_id: Optional[str] = None) -> dict:
        steps = data.pop("steps", [])
        template = {
            "id": _uid(),
            "firm_id": firm_id,
            "is_system": False,
            "version": 1,
            "execution_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "avg_duration_ms": None,
            "created_by": user_id,
            "updated_by": user_id,
            "created_at": _now(),
            "updated_at": _now(),
            **data,
        }
        MOCK_TEMPLATES.append(template)
        saved_steps = []
        for i, step in enumerate(steps):
            saved_steps.append(self._create_step(template["id"], {**step, "step_order": i}))
        template["steps"] = saved_steps
        return template

    def update_template(self, firm_id: str, template_id: str, data: dict, user_id: Optional[str] = None) -> Optional[dict]:
        for t in MOCK_TEMPLATES:
            if t["id"] == template_id and t["firm_id"] == firm_id:
                steps = data.pop("steps", None)
                t.update({k: v for k, v in data.items() if v is not None})
                t["version"] += 1
                t["updated_by"] = user_id
                t["updated_at"] = _now()
                if steps is not None:
                    MOCK_STEPS[:] = [s for s in MOCK_STEPS if s["template_id"] != template_id]
                    for i, step in enumerate(steps):
                        self._create_step(template_id, {**step, "step_order": i})
                t["steps"] = self.list_steps(template_id)
                return t
        return None

    def delete_template(self, firm_id: str, template_id: str) -> bool:
        orig = len(MOCK_TEMPLATES)
        MOCK_TEMPLATES[:] = [t for t in MOCK_TEMPLATES if not (t["id"] == template_id and t["firm_id"] == firm_id)]
        return len(MOCK_TEMPLATES) < orig

    # ── Steps ─────────────────────────────────────────────────────────────────

    def list_steps(self, template_id: str) -> list[dict]:
        return sorted([s for s in MOCK_STEPS if s["template_id"] == template_id], key=lambda s: s["step_order"])

    def _create_step(self, template_id: str, data: dict) -> dict:
        step = {"id": _uid(), "template_id": template_id, "created_at": _now(), **data}
        MOCK_STEPS.append(step)
        return step

    # ── Instances ─────────────────────────────────────────────────────────────

    def list_instances(
        self,
        firm_id: str,
        template_id: Optional[str] = None,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        instances = [i for i in MOCK_INSTANCES if i["firm_id"] == firm_id]
        if template_id:
            instances = [i for i in instances if i["template_id"] == template_id]
        if client_id:
            instances = [i for i in instances if i.get("client_id") == client_id]
        if status:
            instances = [i for i in instances if i["status"] == status]
        instances.sort(key=lambda i: i["created_at"], reverse=True)
        return instances[offset: offset + limit]

    def get_instance(self, firm_id: str, instance_id: str) -> Optional[dict]:
        for i in MOCK_INSTANCES:
            if i["id"] == instance_id and i["firm_id"] == firm_id:
                return i
        return None

    def create_instance(self, firm_id: str, template_id: str, trigger_event: str, trigger_data: dict, client_id: Optional[str] = None) -> dict:
        instance = {
            "id": _uid(),
            "firm_id": firm_id,
            "template_id": template_id,
            "client_id": client_id,
            "trigger_event": trigger_event,
            "trigger_data": trigger_data,
            "status": "pending",
            "current_step_id": None,
            "context_data": {},
            "started_at": None,
            "completed_at": None,
            "failed_at": None,
            "error_message": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        MOCK_INSTANCES.append(instance)
        return instance

    def update_instance_status(self, instance_id: str, status: str, **kwargs: Any) -> Optional[dict]:
        for i in MOCK_INSTANCES:
            if i["id"] == instance_id:
                i["status"] = status
                i["updated_at"] = _now()
                for k, v in kwargs.items():
                    if v is not None:
                        i[k] = v
                return i
        return None

    # ── Action Logs ───────────────────────────────────────────────────────────

    def log_action(self, instance_id: str, data: dict) -> dict:
        log = {"id": _uid(), "instance_id": instance_id, "created_at": _now(), **data}
        MOCK_ACTION_LOGS.append(log)
        return log

    def list_action_logs(self, instance_id: str) -> list[dict]:
        return [l for l in MOCK_ACTION_LOGS if l["instance_id"] == instance_id]

    # ── Executions (Audit) ────────────────────────────────────────────────────

    def log_execution(self, instance_id: str, firm_id: str, event_type: str, event_data: dict, actor_id: Optional[str] = None) -> dict:
        event = {
            "id": _uid(),
            "instance_id": instance_id,
            "firm_id": firm_id,
            "event_type": event_type,
            "event_data": event_data,
            "actor_id": actor_id,
            "actor_type": "user" if actor_id else "system",
            "created_at": _now(),
        }
        MOCK_EXECUTIONS.append(event)
        return event

    def list_executions(self, firm_id: str, instance_id: Optional[str] = None, limit: int = 100) -> list[dict]:
        events = [e for e in MOCK_EXECUTIONS if e["firm_id"] == firm_id]
        if instance_id:
            events = [e for e in events if e["instance_id"] == instance_id]
        events.sort(key=lambda e: e["created_at"], reverse=True)
        return events[:limit]

    # ── Failures ──────────────────────────────────────────────────────────────

    def log_failure(self, instance_id: str, firm_id: str, error_type: str, error_message: str, step_id: Optional[str] = None, step_name: Optional[str] = None, error_data: Optional[dict] = None) -> dict:
        failure = {
            "id": _uid(),
            "instance_id": instance_id,
            "firm_id": firm_id,
            "step_id": step_id,
            "step_name": step_name,
            "error_type": error_type,
            "error_message": error_message,
            "error_data": error_data,
            "retry_count": 0,
            "resolved": False,
            "resolved_at": None,
            "resolved_by": None,
            "created_at": _now(),
        }
        MOCK_FAILURES.append(failure)
        return failure

    def list_failures(self, firm_id: str, resolved: Optional[bool] = False, limit: int = 50) -> list[dict]:
        failures = [f for f in MOCK_FAILURES if f["firm_id"] == firm_id]
        if resolved is not None:
            failures = [f for f in failures if f["resolved"] == resolved]
        failures.sort(key=lambda f: f["created_at"], reverse=True)
        return failures[:limit]

    def resolve_failure(self, firm_id: str, failure_id: str, user_id: str) -> Optional[dict]:
        for f in MOCK_FAILURES:
            if f["id"] == failure_id and f["firm_id"] == firm_id:
                f["resolved"] = True
                f["resolved_at"] = _now()
                f["resolved_by"] = user_id
                return f
        return None

    # ── Approvals ─────────────────────────────────────────────────────────────

    def create_approval(self, firm_id: str, instance_id: str, data: dict) -> dict:
        approval = {
            "id": _uid(),
            "firm_id": firm_id,
            "instance_id": instance_id,
            "status": "pending",
            "responded_at": None,
            "responder_id": None,
            "response_notes": None,
            "created_at": _now(),
            "updated_at": _now(),
            **data,
        }
        MOCK_APPROVALS.append(approval)
        return approval

    def list_approvals(self, firm_id: str, status: Optional[str] = None, approver_id: Optional[str] = None, limit: int = 50) -> list[dict]:
        approvals = [a for a in MOCK_APPROVALS if a["firm_id"] == firm_id]
        if status:
            approvals = [a for a in approvals if a["status"] == status]
        if approver_id:
            approvals = [a for a in approvals if a.get("approver_id") == approver_id]
        approvals.sort(key=lambda a: a["created_at"], reverse=True)
        return approvals[:limit]

    def get_approval(self, firm_id: str, approval_id: str) -> Optional[dict]:
        for a in MOCK_APPROVALS:
            if a["id"] == approval_id and a["firm_id"] == firm_id:
                return a
        return None

    def respond_approval(self, firm_id: str, approval_id: str, decision: str, responder_id: str, notes: Optional[str] = None) -> Optional[dict]:
        for a in MOCK_APPROVALS:
            if a["id"] == approval_id and a["firm_id"] == firm_id and a["status"] == "pending":
                a["status"] = decision  # "approved" | "rejected"
                a["responded_at"] = _now()
                a["responder_id"] = responder_id
                a["response_notes"] = notes
                a["updated_at"] = _now()
                return a
        return None

    def escalate_overdue_approvals(self) -> list[dict]:
        now = datetime.utcnow().isoformat()
        escalated = []
        for a in MOCK_APPROVALS:
            if a["status"] == "pending" and a.get("escalation_at") and a["escalation_at"] < now and a.get("escalated_to"):
                a["status"] = "escalated"
                a["updated_at"] = _now()
                escalated.append(a)
        return escalated

    # ── Schedules ─────────────────────────────────────────────────────────────

    def list_schedules(self, firm_id: str, is_active: Optional[bool] = None) -> list[dict]:
        schedules = [s for s in MOCK_SCHEDULES if s["firm_id"] == firm_id]
        if is_active is not None:
            schedules = [s for s in schedules if s["is_active"] == is_active]
        return schedules

    def create_schedule(self, firm_id: str, data: dict, user_id: Optional[str] = None) -> dict:
        schedule = {
            "id": _uid(),
            "firm_id": firm_id,
            "last_run_at": None,
            "next_run_at": None,
            "last_run_status": None,
            "run_count": 0,
            "created_by": user_id,
            "created_at": _now(),
            "updated_at": _now(),
            **data,
        }
        MOCK_SCHEDULES.append(schedule)
        return schedule

    def toggle_schedule(self, firm_id: str, schedule_id: str, is_active: bool) -> Optional[dict]:
        for s in MOCK_SCHEDULES:
            if s["id"] == schedule_id and s["firm_id"] == firm_id:
                s["is_active"] = is_active
                s["updated_at"] = _now()
                return s
        return None

    def delete_schedule(self, firm_id: str, schedule_id: str) -> bool:
        orig = len(MOCK_SCHEDULES)
        MOCK_SCHEDULES[:] = [s for s in MOCK_SCHEDULES if not (s["id"] == schedule_id and s["firm_id"] == firm_id)]
        return len(MOCK_SCHEDULES) < orig

    # ── Analytics ─────────────────────────────────────────────────────────────

    def get_analytics(self, firm_id: str, template_id: Optional[str] = None) -> list[dict]:
        from datetime import date
        now = datetime.utcnow()
        seven_days_ago = (now - timedelta(days=7)).isoformat()
        thirty_days_ago = (now - timedelta(days=30)).isoformat()

        templates = [t for t in MOCK_TEMPLATES if t["firm_id"] in (firm_id, "system")]
        if template_id:
            templates = [t for t in templates if t["id"] == template_id]

        result = []
        for t in templates:
            instances = [i for i in MOCK_INSTANCES if i["template_id"] == t["id"] and i["firm_id"] == firm_id]
            successful = len([i for i in instances if i["status"] == "completed"])
            failed = len([i for i in instances if i["status"] == "failed"])
            total = len(instances)
            success_rate = (successful * 100 // total) if total > 0 else 0
            pending_approvals = len([a for a in MOCK_APPROVALS if a["firm_id"] == firm_id and
                                     any(i["template_id"] == t["id"] for i in MOCK_INSTANCES if i["id"] == a["instance_id"])
                                     and a["status"] == "pending"])
            last_7 = len([i for i in instances if i["created_at"] >= seven_days_ago])
            last_30 = len([i for i in instances if i["created_at"] >= thirty_days_ago])
            result.append({
                "template_id": t["id"],
                "template_name": t["name"],
                "total_executions": total,
                "successful": successful,
                "failed": failed,
                "success_rate": success_rate,
                "avg_duration_ms": t.get("avg_duration_ms"),
                "pending_approvals": pending_approvals,
                "executions_last_7_days": last_7,
                "executions_last_30_days": last_30,
            })
        return result


workflow_repo = WorkflowRepository()


# ── Mock data ─────────────────────────────────────────────────────────────────
_now_str = _now()
_d = lambda days: (datetime.utcnow() - timedelta(days=days)).isoformat()

MOCK_TEMPLATES: list[dict] = [
    {
        "id": "wft-001",
        "firm_id": "system",
        "name": "GST Filing Reminder Workflow",
        "description": "Automatically notify teams 7 days and 2 days before GSTR-3B due date.",
        "category": "gst",
        "trigger_type": "gst_due",
        "trigger_config": {"days_before": 7},
        "conditions": {"logic": "AND", "rules": [], "groups": []},
        "is_active": True,
        "is_system": True,
        "version": 1,
        "execution_count": 45,
        "success_count": 43,
        "failure_count": 2,
        "avg_duration_ms": 1200,
        "created_by": None,
        "updated_by": None,
        "created_at": _d(90),
        "updated_at": _d(5),
    },
    {
        "id": "wft-002",
        "firm_id": "system",
        "name": "Client Onboarding Workflow",
        "description": "Complete client onboarding: KYC → Engagement Letter → Task Setup → Welcome.",
        "category": "onboarding",
        "trigger_type": "onboarding_started",
        "trigger_config": {},
        "conditions": {"logic": "AND", "rules": [], "groups": []},
        "is_active": True,
        "is_system": True,
        "version": 2,
        "execution_count": 18,
        "success_count": 16,
        "failure_count": 2,
        "avg_duration_ms": 86400000,  # 1 day average
        "created_by": None,
        "updated_by": None,
        "created_at": _d(120),
        "updated_at": _d(10),
    },
    {
        "id": "wft-003",
        "firm_id": "system",
        "name": "Health Score Alert Workflow",
        "description": "Escalate to Partner when client health score drops below 40.",
        "category": "health",
        "trigger_type": "health_score_below_threshold",
        "trigger_config": {"threshold": 40},
        "conditions": {"logic": "AND", "rules": [{"field": "score", "operator": "<", "value": "40", "value_type": "number"}], "groups": []},
        "is_active": True,
        "is_system": True,
        "version": 1,
        "execution_count": 8,
        "success_count": 8,
        "failure_count": 0,
        "avg_duration_ms": 500,
        "created_by": None,
        "updated_by": None,
        "created_at": _d(60),
        "updated_at": _d(2),
    },
    {
        "id": "wft-004",
        "firm_id": "system",
        "name": "TDS Filing Reminder",
        "description": "Remind executives 10 days before TDS return due date.",
        "category": "tds",
        "trigger_type": "tds_due",
        "trigger_config": {"days_before": 10},
        "conditions": {"logic": "AND", "rules": [], "groups": []},
        "is_active": True,
        "is_system": True,
        "version": 1,
        "execution_count": 22,
        "success_count": 20,
        "failure_count": 2,
        "avg_duration_ms": 800,
        "created_by": None,
        "updated_by": None,
        "created_at": _d(80),
        "updated_at": _d(3),
    },
    {
        "id": "wft-005",
        "firm_id": "system",
        "name": "Conflict Detection Alert",
        "description": "Notify Partner on cross-client relationship conflict detection.",
        "category": "relationship",
        "trigger_type": "conflict_detected",
        "trigger_config": {},
        "conditions": {"logic": "AND", "rules": [], "groups": []},
        "is_active": True,
        "is_system": True,
        "version": 1,
        "execution_count": 5,
        "success_count": 5,
        "failure_count": 0,
        "avg_duration_ms": 400,
        "created_by": None,
        "updated_by": None,
        "created_at": _d(45),
        "updated_at": _d(1),
    },
]

MOCK_STEPS: list[dict] = [
    # Steps for wft-001 (GST Filing Reminder)
    {"id": "wfs-001a", "template_id": "wft-001", "step_order": 0, "step_type": "trigger", "name": "GST Due Trigger", "description": None, "config": {"trigger_type": "gst_due"}, "next_step_id": "wfs-001b", "true_branch_step_id": None, "false_branch_step_id": None, "created_at": _d(90)},
    {"id": "wfs-001b", "template_id": "wft-001", "step_order": 1, "step_type": "action", "name": "Notify Executive", "description": "Send in-app notification to assigned executive", "config": {"action_type": "send_notification", "params": {"severity": "high", "title": "GST Filing Due Soon"}}, "next_step_id": "wfs-001c", "true_branch_step_id": None, "false_branch_step_id": None, "created_at": _d(90)},
    {"id": "wfs-001c", "template_id": "wft-001", "step_order": 2, "step_type": "action", "name": "Create Filing Task", "description": "Auto-create task for GST filing", "config": {"action_type": "create_task", "params": {"title": "File GSTR-3B", "priority": "high"}}, "next_step_id": None, "true_branch_step_id": None, "false_branch_step_id": None, "created_at": _d(90)},
    # Steps for wft-002 (Onboarding)
    {"id": "wfs-002a", "template_id": "wft-002", "step_order": 0, "step_type": "trigger", "name": "Onboarding Started", "description": None, "config": {}, "next_step_id": "wfs-002b", "true_branch_step_id": None, "false_branch_step_id": None, "created_at": _d(120)},
    {"id": "wfs-002b", "template_id": "wft-002", "step_order": 1, "step_type": "action", "name": "Create KYC Task", "description": None, "config": {"action_type": "create_task", "params": {"title": "Collect KYC Documents", "priority": "high"}}, "next_step_id": "wfs-002c", "true_branch_step_id": None, "false_branch_step_id": None, "created_at": _d(120)},
    {"id": "wfs-002c", "template_id": "wft-002", "step_order": 2, "step_type": "approval", "name": "Partner Approval — Engagement Letter", "description": "Partner must approve engagement letter before onboarding continues", "config": {"approver_role": "Partner", "title": "Approve Engagement Letter", "due_hours": 48}, "next_step_id": "wfs-002d", "true_branch_step_id": None, "false_branch_step_id": None, "created_at": _d(120)},
    {"id": "wfs-002d", "template_id": "wft-002", "step_order": 3, "step_type": "action", "name": "Send Welcome Notification", "description": None, "config": {"action_type": "send_notification", "params": {"severity": "info", "title": "Client Onboarded Successfully"}}, "next_step_id": None, "true_branch_step_id": None, "false_branch_step_id": None, "created_at": _d(120)},
]

MOCK_INSTANCES: list[dict] = [
    {
        "id": "wfi-001",
        "firm_id": "firm-001",
        "template_id": "wft-001",
        "client_id": "c-001",
        "trigger_event": "gst_due",
        "trigger_data": {"days_remaining": 7, "filing_type": "GSTR-3B", "period": "May 2026"},
        "status": "completed",
        "current_step_id": None,
        "context_data": {"notification_id": "notif-001", "task_id": "task-gst-001"},
        "started_at": _d(3),
        "completed_at": _d(3),
        "failed_at": None,
        "error_message": None,
        "created_at": _d(3),
        "updated_at": _d(3),
    },
    {
        "id": "wfi-002",
        "firm_id": "firm-001",
        "template_id": "wft-002",
        "client_id": "c-010",
        "trigger_event": "onboarding_started",
        "trigger_data": {"client_name": "New Tech Pvt Ltd"},
        "status": "waiting_approval",
        "current_step_id": "wfs-002c",
        "context_data": {"kyc_task_id": "task-kyc-002"},
        "started_at": _d(1),
        "completed_at": None,
        "failed_at": None,
        "error_message": None,
        "created_at": _d(1),
        "updated_at": _d(0),
    },
]

MOCK_ACTION_LOGS: list[dict] = [
    {
        "id": "wal-001",
        "instance_id": "wfi-001",
        "step_id": "wfs-001b",
        "step_name": "Notify Executive",
        "action_type": "send_notification",
        "action_config": {"severity": "high", "title": "GST Filing Due Soon"},
        "status": "success",
        "started_at": _d(3),
        "completed_at": _d(3),
        "duration_ms": 120,
        "result_data": {"notification_id": "notif-001"},
        "error_message": None,
        "created_at": _d(3),
    },
]

MOCK_EXECUTIONS: list[dict] = []
MOCK_FAILURES: list[dict] = []
MOCK_APPROVALS: list[dict] = [
    {
        "id": "wfa-001",
        "firm_id": "firm-001",
        "instance_id": "wfi-002",
        "step_id": "wfs-002c",
        "step_name": "Partner Approval — Engagement Letter",
        "approver_role": "Partner",
        "approver_id": None,
        "status": "pending",
        "title": "Approve Engagement Letter for New Tech Pvt Ltd",
        "description": "Please review and approve the engagement letter to proceed with onboarding.",
        "context_data": {"client_id": "c-010", "client_name": "New Tech Pvt Ltd"},
        "due_at": (datetime.utcnow() + timedelta(hours=24)).isoformat(),
        "escalation_at": (datetime.utcnow() + timedelta(hours=48)).isoformat(),
        "escalated_to": "Partner",
        "responded_at": None,
        "responder_id": None,
        "response_notes": None,
        "created_at": _d(1),
        "updated_at": _d(1),
    },
]
MOCK_SCHEDULES: list[dict] = [
    {
        "id": "wsch-001",
        "firm_id": "firm-001",
        "template_id": "wft-001",
        "name": "Monthly GST Check",
        "cron_expression": "0 9 1 * *",
        "timezone": "Asia/Kolkata",
        "is_active": True,
        "last_run_at": _d(12),
        "next_run_at": (datetime.utcnow() + timedelta(days=19)).isoformat(),
        "last_run_status": "success",
        "run_count": 5,
        "created_by": None,
        "created_at": _d(150),
        "updated_at": _d(12),
    },
]
