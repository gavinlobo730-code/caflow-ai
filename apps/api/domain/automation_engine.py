"""
Automation Engine.
Executes rule-based automations: Risk Detected → Create Task → Notify.
Rules are evaluated when trigger events occur.
"""
from datetime import date, timedelta, datetime
from typing import Optional
import uuid


today = date.today()

MOCK_AUTOMATION_RULES: list[dict] = [
    {
        "id": "rule-001",
        "name": "Critical Risk → Create Review Task",
        "trigger_type": "risk_detected",
        "trigger_config": {"severity": "critical"},
        "action_type": "create_task",
        "action_config": {
            "title": "Review Critical Risk",
            "priority": "critical",
            "description": "A critical risk has been detected. Immediate CA review required.",
        },
        "is_enabled": True,
        "created_at": (today - timedelta(days=30)).isoformat(),
    },
    {
        "id": "rule-002",
        "name": "Document Uploaded → Create Review Task",
        "trigger_type": "document_uploaded",
        "trigger_config": {},
        "action_type": "create_task",
        "action_config": {
            "title": "Review Document",
            "priority": "medium",
            "description": "New document uploaded. Review and validate extraction results.",
        },
        "is_enabled": True,
        "created_at": (today - timedelta(days=28)).isoformat(),
    },
    {
        "id": "rule-003",
        "name": "Compliance Due in 7 Days → Notify",
        "trigger_type": "compliance_due",
        "trigger_config": {"days_remaining": 7},
        "action_type": "send_notification",
        "action_config": {
            "title": "Compliance Deadline Approaching",
            "body": "Filing due in 7 days. Begin preparation immediately.",
            "severity": "high",
        },
        "is_enabled": True,
        "created_at": (today - timedelta(days=25)).isoformat(),
    },
    {
        "id": "rule-004",
        "name": "AIS Mismatch → Create Insight",
        "trigger_type": "risk_detected",
        "trigger_config": {"category": "AIS_MISMATCH"},
        "action_type": "create_insight",
        "action_config": {
            "category": "risk",
            "severity": "high",
            "title": "AIS Mismatch Detected — Reconciliation Required",
        },
        "is_enabled": True,
        "created_at": (today - timedelta(days=20)).isoformat(),
    },
    {
        "id": "rule-005",
        "name": "3-Day Deadline → Create Filing Task",
        "trigger_type": "deadline_approaching",
        "trigger_config": {"days": 3},
        "action_type": "create_task",
        "action_config": {
            "title": "File Compliance",
            "priority": "critical",
            "description": "Filing deadline in 3 days. Initiate final filing steps.",
        },
        "is_enabled": True,
        "created_at": (today - timedelta(days=15)).isoformat(),
    },
]

MOCK_AUTOMATION_EXECUTIONS: list[dict] = [
    {
        "id": "exec-001",
        "rule_id": "rule-001",
        "rule_name": "Critical Risk → Create Review Task",
        "trigger_data": {"risk_id": "eng-risk-001", "severity": "critical", "client_id": "c-005"},
        "status": "success",
        "result_data": {"task_id": "task-gen-001", "title": "Review Critical Risk"},
        "error_message": None,
        "executed_at": (today - timedelta(days=10)).isoformat(),
    },
    {
        "id": "exec-002",
        "rule_id": "rule-002",
        "rule_name": "Document Uploaded → Create Review Task",
        "trigger_data": {"document_id": "doc-003", "client_id": "c-005"},
        "status": "success",
        "result_data": {"task_id": "task-gen-002", "title": "Review Document"},
        "error_message": None,
        "executed_at": (today - timedelta(days=10)).isoformat(),
    },
    {
        "id": "exec-003",
        "rule_id": "rule-003",
        "rule_name": "Compliance Due in 7 Days → Notify",
        "trigger_data": {"record_id": "cr-006", "days_remaining": 7, "client_id": "c-001"},
        "status": "success",
        "result_data": {"notification_id": "notif-gen-001"},
        "error_message": None,
        "executed_at": (today - timedelta(days=7)).isoformat(),
    },
    {
        "id": "exec-004",
        "rule_id": "rule-004",
        "rule_name": "AIS Mismatch → Create Insight",
        "trigger_data": {"risk_id": "eng-risk-004", "category": "AIS_MISMATCH", "client_id": "c-003"},
        "status": "success",
        "result_data": {"insight_id": "aiv2-005"},
        "error_message": None,
        "executed_at": (today - timedelta(days=7)).isoformat(),
    },
    {
        "id": "exec-005",
        "rule_id": "rule-001",
        "rule_name": "Critical Risk → Create Review Task",
        "trigger_data": {"risk_id": "eng-risk-002", "severity": "critical", "client_id": "c-003"},
        "status": "success",
        "result_data": {"task_id": "task-gen-003", "title": "Review Critical Risk — GSTR-3B Overdue"},
        "error_message": None,
        "executed_at": (today - timedelta(days=8)).isoformat(),
    },
    {
        "id": "exec-006",
        "rule_id": "rule-005",
        "rule_name": "3-Day Deadline → Create Filing Task",
        "trigger_data": {"days_remaining": 3, "client_id": "c-001", "compliance_type": "GSTR1"},
        "status": "success",
        "result_data": {"task_id": "task-gen-004", "title": "File Compliance — GSTR1"},
        "error_message": None,
        "executed_at": (today - timedelta(days=3)).isoformat(),
    },
    {
        "id": "exec-007",
        "rule_id": "rule-002",
        "rule_name": "Document Uploaded → Create Review Task",
        "trigger_data": {"document_id": "doc-004", "client_id": "c-003"},
        "status": "success",
        "result_data": {"task_id": "task-gen-005", "title": "Review Document — AIS"},
        "error_message": None,
        "executed_at": (today - timedelta(days=7)).isoformat(),
    },
    {
        "id": "exec-008",
        "rule_id": "rule-002",
        "rule_name": "Document Uploaded → Create Review Task",
        "trigger_data": {"document_id": "doc-005", "client_id": "c-002"},
        "status": "failed",
        "result_data": None,
        "error_message": "Client assignment not found for task creation",
        "executed_at": (today - timedelta(days=3)).isoformat(),
    },
    {
        "id": "exec-009",
        "rule_id": "rule-003",
        "rule_name": "Compliance Due in 7 Days → Notify",
        "trigger_data": {"record_id": "cr-002", "days_remaining": 7, "client_id": "c-002"},
        "status": "skipped",
        "result_data": {"reason": "Notification already sent for this record"},
        "error_message": None,
        "executed_at": (today - timedelta(days=6)).isoformat(),
    },
    {
        "id": "exec-010",
        "rule_id": "rule-001",
        "rule_name": "Critical Risk → Create Review Task",
        "trigger_data": {"risk_id": "eng-risk-003", "severity": "critical", "client_id": "c-003"},
        "status": "success",
        "result_data": {"task_id": "task-gen-006", "title": "Review Critical Risk — GSTR-1 Overdue"},
        "error_message": None,
        "executed_at": (today - timedelta(days=6)).isoformat(),
    },
]

_rule_index = {r["id"]: r for r in MOCK_AUTOMATION_RULES}


def evaluate_rules(trigger_type: str, trigger_data: dict, firm_id: Optional[str] = None) -> list[dict]:
    """Find matching enabled rules, execute actions, persist executions."""
    from repositories.automation_repository import automation_repo
    all_rules = automation_repo.get_rules(firm_id=firm_id)
    matching = [r for r in all_rules if r["is_enabled"] and r["trigger_type"] == trigger_type]
    executed: list[dict] = []
    for rule in matching:
        cfg = rule["trigger_config"]
        if "severity" in cfg and trigger_data.get("severity") != cfg["severity"]:
            continue
        if "category" in cfg and trigger_data.get("category") != cfg["category"]:
            continue
        if "days_remaining" in cfg:
            if trigger_data.get("days_remaining", 999) > cfg["days_remaining"]:
                continue
        if "days" in cfg:
            if trigger_data.get("days_remaining", 999) > cfg["days"]:
                continue

        execution = {
            "id": f"exec-{str(uuid.uuid4())[:8]}",
            "rule_id": rule["id"],
            "rule_name": rule.get("name", ""),
            "trigger_data": trigger_data,
            "status": "success",
            "result_data": {"action": rule["action_type"], "config": rule["action_config"]},
            "error_message": None,
            "executed_at": datetime.utcnow().isoformat(),
        }
        automation_repo.log_execution(execution)
        executed.append(execution)
    return executed


def get_rules() -> list[dict]:
    return list(MOCK_AUTOMATION_RULES)


def toggle_rule(rule_id: str, enabled: bool) -> dict | None:
    rule = _rule_index.get(rule_id)
    if rule:
        rule["is_enabled"] = enabled
    return rule


def get_execution_log(limit: int = 50) -> list[dict]:
    sorted_execs = sorted(MOCK_AUTOMATION_EXECUTIONS, key=lambda e: e["executed_at"], reverse=True)
    return sorted_execs[:limit]


def get_automation_stats() -> dict:
    today_str = today.isoformat()
    active_rules = len([r for r in MOCK_AUTOMATION_RULES if r["is_enabled"]])
    executions_today = len([
        e for e in MOCK_AUTOMATION_EXECUTIONS
        if e["executed_at"][:10] == today_str
    ])
    tasks_created = len([
        e for e in MOCK_AUTOMATION_EXECUTIONS
        if e["status"] == "success" and e.get("result_data", {}) and "task_id" in (e.get("result_data") or {})
    ])
    notifications_sent = len([
        e for e in MOCK_AUTOMATION_EXECUTIONS
        if e["status"] == "success" and e.get("result_data", {}) and "notification_id" in (e.get("result_data") or {})
    ])
    return {
        "rules_active": active_rules,
        "executions_today": executions_today,
        "tasks_created": tasks_created,
        "notifications_sent": notifications_sent,
    }
