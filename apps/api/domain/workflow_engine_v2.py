"""
Phase 10 Workflow Automation Engine.
Evaluates triggers, conditions, and executes multi-step workflow actions.
Supports: tasks, notifications, lifecycle, health, AI actions, approvals,
delays, branches.

Key production features:
- Step-map-based execution with O(1) branch resolution
- Cycle detection (visited-set) and MAX_STEPS guard
- Per-step retry with exponential back-off (skipped for approval pauses)
- SHA-256 idempotency key on fire_trigger to prevent duplicate runs
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional, Any

_logger = logging.getLogger("caflow.workflow_engine")

MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]   # seconds between attempts
MAX_STEPS = 100             # absolute cycle-protection cap


class WorkflowEngineV2:
    """Core workflow execution engine."""

    def __init__(self) -> None:
        from repositories.workflow_repository import workflow_repo
        self._repo = workflow_repo

    # Convenience alias used internally
    @property
    def repo(self):
        return self._repo

    # ── Public: Trigger event ─────────────────────────────────────────────────

    def fire_trigger(
        self,
        firm_id: str,
        trigger_type: str,
        trigger_data: dict,
        client_id: Optional[str] = None,
    ) -> list[dict]:
        """Evaluate all active templates for this trigger; start instances for matches.

        An idempotency key (SHA-256 of firm+trigger+client+data) prevents
        duplicate instances when the same event fires more than once.
        """
        # Generate idempotency key from trigger inputs
        key_data = f"{firm_id}:{trigger_type}:{client_id}:{json.dumps(trigger_data, sort_keys=True)}"
        idempotency_key = hashlib.sha256(key_data.encode()).hexdigest()[:32]

        # Validate and enrich trigger_data for the given trigger_type
        if not self._evaluate_trigger(trigger_type, trigger_data):
            return []

        templates = self._repo.list_templates(firm_id=firm_id, is_active=True)
        started: list[dict] = []

        for template in templates:
            if template["trigger_type"] != trigger_type:
                continue
            if not self._matches_trigger_config(template.get("trigger_config", {}), trigger_data):
                continue
            if template.get("conditions") and not self._evaluate_conditions(template["conditions"], trigger_data):
                continue

            # Idempotency check — skip if already running/completed for this key
            existing = self._repo.check_idempotency(firm_id, template["id"], trigger_type, idempotency_key)
            if existing:
                _logger.info(
                    "WF: duplicate trigger skipped — instance %s already exists for key %s",
                    existing["id"], idempotency_key,
                )
                started.append({"instance_id": existing["id"], "status": "duplicate_skipped"})
                continue

            instance = self._repo.create_instance(
                firm_id=firm_id,
                template_id=template["id"],
                trigger_event=trigger_type,
                trigger_data=trigger_data,
                client_id=client_id,
                idempotency_key=idempotency_key,
            )
            self._repo.log_execution(instance["id"], firm_id, "started", {"template_name": template["name"]})
            self._repo.update_instance_status(
                firm_id, instance["id"], "running",
                started_at=datetime.utcnow().isoformat(),
            )
            result = self._execute_steps(template, instance, dict(trigger_data), firm_id)
            started.append(result)

        return started

    # ── Condition evaluation ──────────────────────────────────────────────────

    # ── Trigger type evaluation ───────────────────────────────────────────────

    # Product Bible Chapter 17 — all 7 recognised trigger types.
    SUPPORTED_TRIGGER_TYPES: set[str] = {
        "client_event",        # client lifecycle events (created, status_changed, etc.)
        "compliance_deadline", # compliance due dates approaching or missed
        "ai_signal",           # AI insights trigger workflows
        "scheduled",           # cron-based recurring triggers
        "health_change",       # health score crosses a threshold
        "document_uploaded",   # document ingestion completes
        "portal_activity",     # client portal actions (login, document view, etc.)
    }

    def _evaluate_trigger(self, trigger_type: str, trigger_data: dict) -> bool:
        """
        Validate and pre-process a trigger event before template matching.

        Each trigger type can enrich trigger_data with derived fields so that
        _matches_trigger_config and _evaluate_conditions have a consistent data
        shape regardless of caller convention.

        Returns True when the trigger is valid and should proceed to template
        matching.  Returns False to silently drop unrecognised trigger types.
        """
        if trigger_type == "client_event":
            # Expected keys: event_name, client_id, client_status
            # No transformation needed — passed through as-is.
            return True

        elif trigger_type == "compliance_deadline":
            # Expected keys: compliance_type, due_date, days_remaining
            # Ensure days_remaining is computed if not provided.
            if "due_date" in trigger_data and "days_remaining" not in trigger_data:
                try:
                    from datetime import date
                    due = date.fromisoformat(trigger_data["due_date"])
                    trigger_data["days_remaining"] = (due - date.today()).days
                except Exception:
                    pass
            return True

        elif trigger_type == "ai_signal":
            # Expected keys: insight_id, severity, category
            # Map severity to numeric priority for condition rules.
            _severity_priority = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
            if "severity" in trigger_data and "severity_priority" not in trigger_data:
                trigger_data["severity_priority"] = _severity_priority.get(
                    trigger_data["severity"], 0
                )
            return True

        elif trigger_type == "scheduled":
            # Expected keys: schedule_id, cron_expression, last_run_at
            # Scheduled triggers are always valid.
            return True

        elif trigger_type == "health_change":
            # Expected keys: client_id, old_score, new_score, old_grade, new_grade
            # Add derived field for score delta.
            if "old_score" in trigger_data and "new_score" in trigger_data:
                trigger_data.setdefault(
                    "score_delta",
                    trigger_data["new_score"] - trigger_data["old_score"],
                )
            return True

        elif trigger_type == "document_uploaded":
            # Expected keys: document_id, doc_type, client_id, extraction_confidence
            return True

        elif trigger_type == "portal_activity":
            # Expected keys: client_id, activity_type, portal_user_id
            return True

        else:
            # Allow legacy and custom trigger types through — template matching
            # will filter to only those templates that subscribe to this type.
            return True

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
        return all(results) if logic == "AND" else any(results)

    def _eval_rule(self, rule: dict, data: dict) -> bool:
        field = rule.get("field", "")
        op = rule.get("operator", "=")
        expected_raw = rule.get("value", "")
        value_type = rule.get("value_type", "string")
        actual = data.get(field)

        try:
            if value_type == "number":
                expected = float(expected_raw)
                actual_f = float(actual) if actual is not None else 0.0
                if op == ">":  return actual_f > expected
                if op == "<":  return actual_f < expected
                if op == "=":  return actual_f == expected
                if op == ">=": return actual_f >= expected
                if op == "<=": return actual_f <= expected
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
        """Drive the workflow using a step-map for O(1) branch resolution.

        Uses a visited-set for cycle detection and a MAX_STEPS hard cap.
        Each step is wrapped with retry logic (_execute_step_with_retry).
        Returns a summary dict (not the instance object).
        """
        steps = self._repo.list_steps(template["id"])
        if not steps:
            self._repo.update_instance_status(
                firm_id, instance["id"], "completed",
                completed_at=datetime.utcnow().isoformat(),
            )
            self._repo.log_execution(instance["id"], firm_id, "completed", {"steps_executed": 0})
            return {"status": "completed", "steps_executed": 0}

        # Build step map for O(1) lookup by id
        step_map: dict[str, dict] = {s["id"]: s for s in steps}

        # Skip trigger step — begin at first non-trigger step
        first_non_trigger = next(
            (s for s in sorted(steps, key=lambda s: s["step_order"]) if s["step_type"] != "trigger"),
            None,
        )
        current_step = first_non_trigger
        visited: set[str] = set()
        steps_executed = 0

        while current_step and steps_executed < MAX_STEPS:
            step_id = current_step["id"]

            # Cycle detection
            if step_id in visited:
                self._repo.log_failure(
                    firm_id, instance["id"], step_id,
                    "cycle_detected",
                    f"Cycle detected at step {current_step['name']}",
                )
                self._repo.update_instance_status(
                    firm_id, instance["id"], "failed",
                    error_message="Cycle detected in workflow",
                    failed_at=datetime.utcnow().isoformat(),
                )
                self._repo.log_execution(instance["id"], firm_id, "failed", {"error": "cycle_detected"})
                return {"status": "failed", "error": "cycle_detected"}

            visited.add(step_id)
            steps_executed += 1

            # Update instance to reflect current running step
            self._repo.update_instance_status(firm_id, instance["id"], "running", current_step_id=step_id)

            # Log action start
            log = self._repo.log_action(
                instance_id=instance["id"],
                step_id=step_id,
                step_name=current_step["name"],
                action_type=current_step["step_type"],
                config=current_step.get("config", {}),
                status="running",
            )

            try:
                result, next_step_id = self._execute_step_with_retry(current_step, instance, context, firm_id)

                # Update action log to success
                self._repo.update_action_log(log["id"], "success", result_data=result)

                context.update(result or {})
                self._repo.log_execution(
                    instance["id"], firm_id, "step_completed",
                    {"step": current_step["name"], "result": result},
                )

                # Branch logic: step result next_step_id takes precedence over step config
                if next_step_id:
                    current_step = step_map.get(next_step_id)
                elif current_step.get("next_step_id"):
                    current_step = step_map.get(current_step["next_step_id"])
                else:
                    current_step = None  # end of flow

            except _ApprovalPause as pause:
                self._repo.update_action_log(log["id"], "paused")
                self._repo.log_execution(
                    instance["id"], firm_id, "approval_requested",
                    {"approval_id": pause.approval_id},
                )
                # Execution deliberately halted — will resume via resume_after_approval
                return {"status": "waiting_approval", "approval_id": pause.approval_id, "steps_executed": steps_executed}

            except Exception as exc:
                _logger.exception("Workflow step permanently failed after retries: %s", exc)
                self._repo.update_action_log(log["id"], "failed", error_message=str(exc))
                self._repo.update_instance_status(
                    firm_id, instance["id"], "failed",
                    failed_at=datetime.utcnow().isoformat(),
                    error_message=str(exc),
                )
                self._repo.log_execution(
                    instance["id"], firm_id, "failed",
                    {"step": current_step["name"], "error": str(exc)},
                )
                return {"status": "failed", "error": str(exc), "steps_executed": steps_executed}

        if steps_executed >= MAX_STEPS:
            self._repo.log_failure(
                firm_id, instance["id"], None,
                "max_steps_exceeded",
                f"Workflow exceeded {MAX_STEPS} steps",
            )
            self._repo.update_instance_status(
                firm_id, instance["id"], "failed",
                error_message="Max steps exceeded",
                failed_at=datetime.utcnow().isoformat(),
            )
            self._repo.log_execution(instance["id"], firm_id, "failed", {"error": "max_steps_exceeded"})
            return {"status": "failed", "error": "max_steps_exceeded"}

        self._repo.update_instance_status(
            firm_id, instance["id"], "completed",
            completed_at=datetime.utcnow().isoformat(),
            context_data=context,
        )
        self._repo.log_execution(instance["id"], firm_id, "completed", {"steps_executed": steps_executed})
        return {"status": "completed", "steps_executed": steps_executed}

    def _execute_step_with_retry(
        self,
        step: dict,
        instance: dict,
        context: dict,
        firm_id: str,
    ) -> tuple[dict, Optional[str]]:
        """Execute a step with up to MAX_RETRIES attempts on failure.

        Approval pauses (_ApprovalPause) are never retried — they bubble up
        immediately. Each failed attempt logs a workflow_failure row with the
        attempt number. After all attempts are exhausted the last exception
        is re-raised to the caller.
        """
        last_error: Exception = RuntimeError("No attempt made")
        for attempt in range(MAX_RETRIES):
            try:
                result, next_step_id = self._execute_step(step, instance, context, firm_id)
                if attempt > 0:
                    self._repo.log_execution(
                        instance["id"], instance.get("firm_id", firm_id),
                        "step_retried_success",
                        {"step_id": step["id"], "step_name": step["name"], "attempt": attempt + 1},
                    )
                return result, next_step_id
            except _ApprovalPause:
                raise  # never retry approval pauses
            except Exception as exc:
                last_error = exc
                retry_delay = RETRY_DELAYS[attempt] if attempt < len(RETRY_DELAYS) else 8
                self._repo.log_failure(
                    instance.get("firm_id", firm_id),
                    instance["id"],
                    step["id"],
                    type(exc).__name__,
                    str(exc),
                    {"attempt": attempt + 1, "retry_delay_s": retry_delay},
                    retry_count=attempt + 1,
                )
                _logger.warning(
                    "WF step '%s' attempt %d/%d failed: %s — retrying in %ds",
                    step["name"], attempt + 1, MAX_RETRIES, exc, retry_delay,
                )
                if attempt < MAX_RETRIES - 1:
                    time.sleep(retry_delay)
        raise last_error

    def _execute_step(
        self,
        step: dict,
        instance: dict,
        context: dict,
        firm_id: str,
    ) -> tuple[dict, Optional[str]]:
        """Execute a single step. Returns (result_dict, next_step_id).

        For branch/condition steps next_step_id reflects the taken branch.
        Approval steps raise _ApprovalPause to halt execution.
        """
        step_type = step["step_type"]
        config = step.get("config", {})

        if step_type == "action":
            result = self._execute_action(config, instance, context, firm_id)
            return result, step.get("next_step_id")

        elif step_type in ("condition", "branch"):
            merged_data = {**context, **(instance.get("trigger_data") or {})}
            condition_matched = self._evaluate_conditions(config.get("condition", {}), merged_data)
            next_id = (
                step.get("true_branch_step_id") if condition_matched
                else step.get("false_branch_step_id")
            )
            self._repo.log_execution(
                instance["id"], firm_id, "branch_taken",
                {
                    "step_id": step["id"],
                    "step_name": step["name"],
                    "condition_result": condition_matched,
                    "branch": "true" if condition_matched else "false",
                    "next_step_id": next_id,
                },
            )
            return {"branch_taken": "true" if condition_matched else "false", "next_step_id": next_id}, next_id

        elif step_type == "approval":
            due_hours = config.get("due_hours", 48)
            due_at = (datetime.utcnow() + timedelta(hours=due_hours)).isoformat()
            approval = self._repo.create_approval(
                firm_id=firm_id,
                instance_id=instance["id"],
                step_id=step["id"],
                step_name=step["name"],
                approver_role=config.get("approver_role", "Partner"),
                title=config.get("title", "Approval Required"),
                description=config.get("description", ""),
                context_data=context,
                due_at=due_at,
            )
            # Store the next step to resume from once approved
            self._repo.update_instance_status(
                firm_id, instance["id"],
                "waiting_approval",
                current_step_id=step.get("next_step_id"),
            )
            raise _ApprovalPause(approval["id"])

        elif step_type == "delay":
            # In production this schedules a deferred job; here we log and move on.
            delay_hours = config.get("delay_hours", 1)
            self._repo.log_execution(
                instance["id"], firm_id, "delay_skipped",
                {"step_id": step["id"], "delay_hours": delay_hours},
            )
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

    def resume_after_approval(
        self,
        firm_id: str,
        instance_id: str,
        approved: bool,
        user_id: str,
    ) -> Optional[dict]:
        """Continue workflow execution after an approval decision.

        If rejected the instance is cancelled. If approved, execution
        resumes from the step stored in instance.current_step_id (set by
        the approval step handler before raising _ApprovalPause).
        """
        instance = self._repo.get_instance(firm_id, instance_id)
        if not instance or instance["status"] != "waiting_approval":
            return None

        if not approved:
            self._repo.update_instance_status(firm_id, instance_id, "cancelled")
            self._repo.log_execution(
                instance_id, firm_id, "cancelled",
                {"reason": "approval_rejected", "by": user_id},
            )
            return instance

        template = self._repo.get_template(firm_id, instance["template_id"])
        if not template:
            return None

        self._repo.update_instance_status(firm_id, instance_id, "running")
        self._repo.log_execution(instance_id, firm_id, "approved", {"by": user_id})

        resume_step_id = instance.get("current_step_id")
        if not resume_step_id:
            # Nothing left to run — mark complete
            self._repo.update_instance_status(
                firm_id, instance_id, "completed",
                completed_at=datetime.utcnow().isoformat(),
            )
            return instance

        steps = self._repo.list_steps(template["id"])
        step_map: dict[str, dict] = {s["id"]: s for s in steps}
        current_step = step_map.get(resume_step_id)
        context = dict(instance.get("context_data") or {})
        visited: set[str] = set()
        steps_executed = 0

        while current_step and steps_executed < MAX_STEPS:
            step_id = current_step["id"]
            if step_id in visited:
                self._repo.update_instance_status(
                    firm_id, instance_id, "failed",
                    error_message="Cycle detected during approval resume",
                )
                return instance
            visited.add(step_id)
            steps_executed += 1

            try:
                result, next_step_id = self._execute_step_with_retry(current_step, instance, context, firm_id)
                context.update(result or {})
                if next_step_id:
                    current_step = step_map.get(next_step_id)
                elif current_step.get("next_step_id"):
                    current_step = step_map.get(current_step["next_step_id"])
                else:
                    current_step = None
            except _ApprovalPause as pause:
                self._repo.log_execution(
                    instance_id, firm_id, "approval_requested",
                    {"approval_id": pause.approval_id},
                )
                return instance
            except Exception as exc:
                self._repo.update_instance_status(
                    firm_id, instance_id, "failed",
                    error_message=str(exc),
                    failed_at=datetime.utcnow().isoformat(),
                )
                return instance

        self._repo.update_instance_status(
            firm_id, instance_id, "completed",
            completed_at=datetime.utcnow().isoformat(),
            context_data=context,
        )
        return instance


class _ApprovalPause(Exception):
    """Raised to halt workflow execution pending approval."""
    def __init__(self, approval_id: str) -> None:
        self.approval_id = approval_id
        super().__init__(f"Waiting for approval: {approval_id}")


workflow_engine = WorkflowEngineV2()
