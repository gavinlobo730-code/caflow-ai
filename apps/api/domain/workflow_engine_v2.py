"""
Phase 10 Workflow Automation Engine.
Evaluates triggers, conditions, and executes multi-step workflow actions.
Supports: tasks, notifications, lifecycle, health, AI actions, approvals, delays, branches.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta
from typing import Optional, Any
import logging

_logger = logging.getLogger("caflow.workflow_engine")


class WorkflowEngineV2:
    """Core workflow execution engine."""

    def __init__(self) -> None:
        from repositories.workflow_repository import workflow_repo
        self._repo = workflow_repo

    # ── Public: Trigger event ─────────────────────────────────────────────────

    def fire_trigger(
        self,
        firm_id: str,
        trigger_type: str,
        trigger_data: dict,
        client_id: Optional[str] = None,
    ) -> list[dict]:
        """Evaluate all active templates for this trigger; start instances for matches."""
        templates = self._repo.list_templates(firm_id=firm_id, is_active=True)
        started: list[dict] = []
        for template in templates:
            if template["trigger_type"] != trigger_type:
                continue
            if not self._matches_trigger_config(template.get("trigger_config", {}), trigger_data):
                continue
            if template.get("conditions") and not self._evaluate_conditions(template["conditions"], trigger_data):
                continue
            instance = self._repo.create_instance(
                firm_id=firm_id,
                template_id=template["id"],
                trigger_event=trigger_type,
                trigger_data=trigger_data,
                client_id=client_id,
            )
            self._repo.log_execution(instance["id"], firm_id, "started", {"template_name": template["name"]})
            self._repo.update_instance_status(instance["id"], "running", started_at=datetime.utcnow().isoformat())
            result = self._execute_steps(template, instance, trigger_data, firm_id)
            started.append(result)
        return started

    # ── Condition evaluation ──────────────────────────────────────────────────

    def _matches_trigger_config(self, config: dict, data: dict) -> bool:
        """Check trigger_config constraints (e.g., days_before, threshold)."""
        if not config:
            return True
        for key, expected in config.items():
            if key == "days_before":
                actual = data.get("days_remaining", data.get("days_before", 999))
                if actual > expected:
                    return False
            elif key == "threshold":
                actual = data.get("score", data.get("value", 0))
                if actual >= expected:
                    return False
            elif key == "severity":
                if data.get("severity") != expected:
                    return False
        return True

    def _evaluate_conditions(self, condition_group: dict, data: dict) -> bool:
        """Recursively evaluate a nested condition group (AND/OR)."""
        if not condition_group:
            return True
        logic = condition_group.get("logic", "AND")
        rules = condition_group.get("rules", [])
        groups = condition_group.get("groups", [])

        results: list[bool] = []
        for rule in rules:
            results.append(self._eval_rule(rule, data))
        for group in groups:
            results.append(self._evaluate_conditions(group, data))

        if not results:
            return True
        if logic == "AND":
            return all(results)
        return any(results)

    def _eval_rule(self, rule: dict, data: dict) -> bool:
        field = rule.get("field", "")
        op = rule.get("operator", "=")
        expected_raw = rule.get("value", "")
        value_type = rule.get("value_type", "string")
        actual = data.get(field)

        try:
            if value_type == "number":
                expected = float(expected_raw)
                actual = float(actual) if actual is not None else 0.0
                if op == ">":  return actual > expected
                if op == "<":  return actual < expected
                if op == "=":  return actual == expected
                if op == ">=": return actual >= expected
                if op == "<=": return actual <= expected
            elif value_type == "date":
                from datetime import date
                today = date.today()
                expected_date = datetime.fromisoformat(str(expected_raw)).date()
                actual_date = datetime.fromisoformat(str(actual)).date() if actual else today
                if op == "before":      return actual_date < expected_date
                if op == "after":       return actual_date > expected_date
                if op == "within_days":
                    delta = int(expected_raw)
                    return (actual_date - today).days <= delta
            else:  # string
                actual_str = str(actual or "")
                if op == "equals":      return actual_str == str(expected_raw)
                if op == "contains":    return str(expected_raw).lower() in actual_str.lower()
                if op == "starts_with": return actual_str.lower().startswith(str(expected_raw).lower())
        except Exception:
            pass
        return False

    # ── Step execution ────────────────────────────────────────────────────────

    def _execute_steps(self, template: dict, instance: dict, context: dict, firm_id: str) -> dict:
        steps = sorted(template.get("steps", []), key=lambda s: s["step_order"])
        # Build step map for branching
        step_map = {s["id"]: s for s in steps}
        current = next((s for s in steps if s["step_type"] != "trigger"), None)
        max_steps = 50  # guard against infinite loops
        executed = 0

        while current and executed < max_steps:
            executed += 1
            log = self._repo.log_action(instance["id"], {
                "step_id": current["id"],
                "step_name": current["name"],
                "action_type": current["step_type"],
                "action_config": current.get("config", {}),
                "status": "running",
                "started_at": datetime.utcnow().isoformat(),
            })
            try:
                result, next_step_id = self._execute_step(current, instance, context, firm_id)
                # Update log
                for l in __import__('repositories.workflow_repository', fromlist=['MOCK_ACTION_LOGS']).MOCK_ACTION_LOGS:
                    if l["id"] == log["id"]:
                        l["status"] = "success"
                        l["completed_at"] = datetime.utcnow().isoformat()
                        l["result_data"] = result
                        break
                context.update(result or {})
                self._repo.log_execution(instance["id"], firm_id, "step_completed", {"step": current["name"], "result": result})
                current = step_map.get(next_step_id) if next_step_id else None
            except Exception as exc:
                _logger.exception("Workflow step failed: %s", exc)
                self._repo.log_failure(
                    instance["id"], firm_id,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    step_id=current["id"],
                    step_name=current["name"],
                )
                self._repo.update_instance_status(
                    instance["id"], "failed",
                    failed_at=datetime.utcnow().isoformat(),
                    error_message=str(exc),
                )
                self._repo.log_execution(instance["id"], firm_id, "failed", {"step": current["name"], "error": str(exc)})
                return instance

        if instance["status"] == "running":
            self._repo.update_instance_status(
                instance["id"], "completed",
                completed_at=datetime.utcnow().isoformat(),
                context_data=context,
            )
            self._repo.log_execution(instance["id"], firm_id, "completed", {"steps_executed": executed})
        return instance

    def _execute_step(self, step: dict, instance: dict, context: dict, firm_id: str) -> tuple[dict, Optional[str]]:
        """Execute a single step. Returns (result_dict, next_step_id)."""
        step_type = step["step_type"]
        config = step.get("config", {})

        if step_type == "action":
            result = self._execute_action(config, instance, context, firm_id)
            return result, step.get("next_step_id")

        elif step_type == "condition":
            # condition step acts as a branch point
            matched = self._evaluate_conditions(config.get("condition", {}), {**context, **instance["trigger_data"]})
            next_id = step.get("true_branch_step_id") if matched else step.get("false_branch_step_id")
            return {"condition_matched": matched}, next_id

        elif step_type == "branch":
            matched = self._evaluate_conditions(config.get("condition", {}), {**context, **instance["trigger_data"]})
            next_id = step.get("true_branch_step_id") if matched else step.get("false_branch_step_id")
            return {"branch_taken": "true" if matched else "false"}, next_id

        elif step_type == "approval":
            # Create approval record and pause instance
            due_hours = config.get("due_hours", 48)
            due_at = (datetime.utcnow() + timedelta(hours=due_hours)).isoformat()
            escalation_at = (datetime.utcnow() + timedelta(hours=due_hours + 24)).isoformat()
            approval = self._repo.create_approval(firm_id, instance["id"], {
                "step_id": step["id"],
                "step_name": step["name"],
                "approver_role": config.get("approver_role", "Partner"),
                "title": config.get("title", "Approval Required"),
                "description": config.get("description", ""),
                "context_data": context,
                "due_at": due_at,
                "escalation_at": escalation_at,
                "escalated_to": config.get("escalate_to"),
            })
            self._repo.update_instance_status(instance["id"], "waiting_approval", current_step_id=step.get("next_step_id"))
            # Halt execution here — will resume when approved
            raise _ApprovalPause(approval["id"])

        elif step_type == "delay":
            # In production this would schedule a job; in mock we skip the actual delay
            delay_hours = config.get("delay_hours", 1)
            return {"delayed_hours": delay_hours}, step.get("next_step_id")

        return {}, step.get("next_step_id")

    def _execute_action(self, config: dict, instance: dict, context: dict, firm_id: str) -> dict:
        """Execute an action step. Returns result_data dict."""
        action_type = config.get("action_type", "")
        params = config.get("params", {})

        if action_type == "create_task":
            task_id = f"task-wf-{str(uuid.uuid4())[:8]}"
            _logger.info("WF: create_task '%s' for firm %s", params.get("title"), firm_id)
            return {"task_id": task_id, "title": params.get("title", "Workflow Task")}

        elif action_type == "assign_task":
            return {"assigned_to": params.get("user_id"), "task_id": params.get("task_id")}

        elif action_type == "send_notification":
            notif_id = f"notif-wf-{str(uuid.uuid4())[:8]}"
            _logger.info("WF: send_notification '%s' for firm %s", params.get("title"), firm_id)
            return {"notification_id": notif_id}

        elif action_type == "send_email":
            return {"email_sent": True, "to": params.get("to")}

        elif action_type == "update_status":
            return {"updated_entity": params.get("entity_type"), "new_status": params.get("status")}

        elif action_type == "change_owner":
            return {"owner_changed_to": params.get("user_id")}

        elif action_type == "archive_client":
            return {"client_archived": True, "client_id": context.get("client_id")}

        elif action_type == "create_proposal":
            return {"proposal_id": f"prop-wf-{str(uuid.uuid4())[:8]}"}

        elif action_type == "create_alert":
            return {"alert_id": f"alert-wf-{str(uuid.uuid4())[:8]}"}

        elif action_type == "trigger_ai_review":
            return {"ai_review_requested": True}

        elif action_type == "request_ai_summary":
            return {"ai_summary_requested": True, "entity_id": params.get("entity_id")}

        return {"action_executed": action_type}

    # ── Resume after approval ─────────────────────────────────────────────────

    def resume_after_approval(self, firm_id: str, instance_id: str, approved: bool, user_id: str) -> Optional[dict]:
        """Continue workflow execution after an approval decision."""
        instance = self._repo.get_instance(firm_id, instance_id)
        if not instance or instance["status"] != "waiting_approval":
            return None
        if not approved:
            self._repo.update_instance_status(instance_id, "cancelled")
            self._repo.log_execution(instance_id, firm_id, "cancelled", {"reason": "approval_rejected", "by": user_id})
            return instance
        # Get template steps from the stored next_step_id
        template = self._repo.get_template(firm_id, instance["template_id"])
        if not template:
            return None
        self._repo.update_instance_status(instance_id, "running")
        self._repo.log_execution(instance_id, firm_id, "approved", {"by": user_id})
        # Continue from current_step_id
        next_step = next((s for s in template.get("steps", []) if s["id"] == instance.get("current_step_id")), None)
        if next_step:
            context = instance.get("context_data", {})
            step_map = {s["id"]: s for s in template.get("steps", [])}
            current = next_step
            executed = 0
            while current and executed < 50:
                executed += 1
                try:
                    result, next_id = self._execute_step(current, instance, context, firm_id)
                    context.update(result or {})
                    current = step_map.get(next_id) if next_id else None
                except _ApprovalPause:
                    return instance
                except Exception as exc:
                    self._repo.update_instance_status(instance_id, "failed", error_message=str(exc))
                    return instance
        self._repo.update_instance_status(instance_id, "completed", completed_at=datetime.utcnow().isoformat())
        return instance


class _ApprovalPause(Exception):
    """Raised to halt workflow execution pending approval."""
    def __init__(self, approval_id: str) -> None:
        self.approval_id = approval_id
        super().__init__(f"Waiting for approval: {approval_id}")


workflow_engine = WorkflowEngineV2()
