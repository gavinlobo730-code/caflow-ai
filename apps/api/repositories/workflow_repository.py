"""Repository for Phase 10 Workflow Automation Engine.

Dual-path: real Supabase when SUPABASE_URL is set, otherwise in-memory mock
data (dev mode). Pattern mirrors client_repository.py.

Tables used:
  workflow_templates, workflow_steps, workflow_triggers,
  workflow_conditions, workflow_instances, workflow_action_logs,
  workflow_executions, workflow_failures, workflow_approvals,
  workflow_schedules
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from typing import Optional, Any

from repositories.base import BaseRepository

_USE_MOCK = not os.environ.get("SUPABASE_URL")


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


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
        if _USE_MOCK:
            templates = [t for t in MOCK_TEMPLATES if t["firm_id"] in (firm_id, "system")]
            if category:
                templates = [t for t in templates if t["category"] == category]
            if trigger_type:
                templates = [t for t in templates if t["trigger_type"] == trigger_type]
            if is_active is not None:
                templates = [t for t in templates if t.get("is_active") == is_active]
            if search:
                q = search.lower()
                templates = [t for t in templates if q in t["name"].lower() or q in (t.get("description") or "").lower()]
            return templates[offset: offset + limit]

        db = _get_db()
        query = (
            db.table("workflow_templates")
            .select("*")
            .or_(f"firm_id.eq.{firm_id},is_system.eq.true")
        )
        if category:
            query = query.eq("category", category)
        if trigger_type:
            query = query.eq("trigger_type", trigger_type)
        if is_active is not None:
            query = query.eq("is_active", is_active)
        if search:
            query = query.ilike("name", f"%{search}%")
        query = query.range(offset, offset + limit - 1).order("created_at", desc=True)
        result = query.execute()
        return result.data or []

    def get_template(self, firm_id: str, template_id: str) -> Optional[dict]:
        if _USE_MOCK:
            for t in MOCK_TEMPLATES:
                if t["id"] == template_id and t["firm_id"] in (firm_id, "system"):
                    t = dict(t)
                    t["steps"] = self.list_steps(template_id)
                    return t
            return None

        db = _get_db()
        result = (
            db.table("workflow_templates")
            .select("*")
            .eq("id", template_id)
            .or_(f"firm_id.eq.{firm_id},is_system.eq.true")
            .maybe_single()
            .execute()
        )
        if not result.data:
            return None
        template = result.data
        template["steps"] = self.list_steps(template_id)
        return template

    def create_template(self, firm_id: str, data: dict, user_id: Optional[str] = None) -> dict:
        if _USE_MOCK:
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

        steps = data.pop("steps", [])
        payload = {
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
        db = _get_db()
        result = db.table("workflow_templates").insert(payload).execute()
        template = result.data[0]
        saved_steps = []
        for i, step in enumerate(steps):
            saved_steps.append(self._create_step(template["id"], {**step, "step_order": i}))
        template["steps"] = saved_steps
        return template

    def update_template(self, firm_id: str, template_id: str, data: dict, user_id: Optional[str] = None) -> Optional[dict]:
        if _USE_MOCK:
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

        steps = data.pop("steps", None)
        update_payload = {k: v for k, v in data.items() if v is not None}
        update_payload["updated_by"] = user_id
        update_payload["updated_at"] = _now()
        db = _get_db()
        # Increment version via raw expression isn't directly supported; fetch then bump
        existing = self.get_template(firm_id, template_id)
        if not existing or existing["firm_id"] != firm_id:
            return None
        update_payload["version"] = existing.get("version", 1) + 1
        result = (
            db.table("workflow_templates")
            .update(update_payload)
            .eq("id", template_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        if not result.data:
            return None
        template = result.data[0]
        if steps is not None:
            db.table("workflow_steps").delete().eq("template_id", template_id).execute()
            for i, step in enumerate(steps):
                self._create_step(template_id, {**step, "step_order": i})
        template["steps"] = self.list_steps(template_id)
        return template

    def delete_template(self, firm_id: str, template_id: str) -> bool:
        if _USE_MOCK:
            orig = len(MOCK_TEMPLATES)
            MOCK_TEMPLATES[:] = [t for t in MOCK_TEMPLATES if not (t["id"] == template_id and t["firm_id"] == firm_id)]
            return len(MOCK_TEMPLATES) < orig

        db = _get_db()
        result = (
            db.table("workflow_templates")
            .delete()
            .eq("id", template_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        return bool(result.data)

    def toggle_template(self, firm_id: str, template_id: str) -> Optional[dict]:
        if _USE_MOCK:
            for t in MOCK_TEMPLATES:
                if t["id"] == template_id and t["firm_id"] == firm_id:
                    t["is_active"] = not t["is_active"]
                    t["updated_at"] = _now()
                    return t
            return None

        existing = self.get_template(firm_id, template_id)
        if not existing or existing["firm_id"] != firm_id:
            return None
        db = _get_db()
        result = (
            db.table("workflow_templates")
            .update({"is_active": not existing["is_active"], "updated_at": _now()})
            .eq("id", template_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        return result.data[0] if result.data else None

    # ── Steps ─────────────────────────────────────────────────────────────────

    def list_steps(self, template_id: str) -> list[dict]:
        if _USE_MOCK:
            return sorted(
                [s for s in MOCK_STEPS if s["template_id"] == template_id],
                key=lambda s: s["step_order"],
            )

        db = _get_db()
        result = (
            db.table("workflow_steps")
            .select("*")
            .eq("template_id", template_id)
            .order("step_order")
            .execute()
        )
        return result.data or []

    def _create_step(self, template_id: str, data: dict) -> dict:
        if _USE_MOCK:
            step = {"id": _uid(), "template_id": template_id, "created_at": _now(), **data}
            MOCK_STEPS.append(step)
            return step

        db = _get_db()
        payload = {"id": _uid(), "template_id": template_id, "created_at": _now(), **data}
        result = db.table("workflow_steps").insert(payload).execute()
        return result.data[0]

    def create_step(self, template_id: str, data: dict) -> dict:
        return self._create_step(template_id, data)

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
        if _USE_MOCK:
            instances = [i for i in MOCK_INSTANCES if i["firm_id"] == firm_id]
            if template_id:
                instances = [i for i in instances if i["template_id"] == template_id]
            if client_id:
                instances = [i for i in instances if i.get("client_id") == client_id]
            if status:
                instances = [i for i in instances if i["status"] == status]
            instances.sort(key=lambda i: i["created_at"], reverse=True)
            return instances[offset: offset + limit]

        db = _get_db()
        query = db.table("workflow_instances").select("*").eq("firm_id", firm_id)
        if template_id:
            query = query.eq("template_id", template_id)
        if client_id:
            query = query.eq("client_id", client_id)
        if status:
            query = query.eq("status", status)
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        result = query.execute()
        return result.data or []

    def get_instance(self, firm_id: str, instance_id: str) -> Optional[dict]:
        if _USE_MOCK:
            for i in MOCK_INSTANCES:
                if i["id"] == instance_id and i["firm_id"] == firm_id:
                    return i
            return None

        db = _get_db()
        result = (
            db.table("workflow_instances")
            .select("*")
            .eq("id", instance_id)
            .eq("firm_id", firm_id)
            .maybe_single()
            .execute()
        )
        return result.data

    def create_instance(
        self,
        firm_id: str,
        template_id: str,
        trigger_event: str,
        trigger_data: dict,
        client_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        if _USE_MOCK:
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
                "idempotency_key": idempotency_key,
                "started_at": None,
                "completed_at": None,
                "failed_at": None,
                "error_message": None,
                "created_at": _now(),
                "updated_at": _now(),
            }
            MOCK_INSTANCES.append(instance)
            return instance

        db = _get_db()
        payload = {
            "id": _uid(),
            "firm_id": firm_id,
            "template_id": template_id,
            "client_id": client_id,
            "trigger_event": trigger_event,
            "trigger_data": trigger_data,
            "status": "pending",
            "current_step_id": None,
            "context_data": {},
            "idempotency_key": idempotency_key,
            "started_at": None,
            "completed_at": None,
            "failed_at": None,
            "error_message": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        result = db.table("workflow_instances").insert(payload).execute()
        return result.data[0]

    def update_instance_status(
        self,
        firm_id: str,
        instance_id: str,
        status: str,
        current_step_id: Optional[str] = None,
        error_message: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[dict]:
        if _USE_MOCK:
            for i in MOCK_INSTANCES:
                if i["id"] == instance_id:
                    i["status"] = status
                    i["updated_at"] = _now()
                    if current_step_id is not None:
                        i["current_step_id"] = current_step_id
                    if error_message is not None:
                        i["error_message"] = error_message
                    for k, v in kwargs.items():
                        if v is not None:
                            i[k] = v
                    return i
            return None

        db = _get_db()
        update_payload: dict = {"status": status, "updated_at": _now()}
        if current_step_id is not None:
            update_payload["current_step_id"] = current_step_id
        if error_message is not None:
            update_payload["error_message"] = error_message
        for k, v in kwargs.items():
            if v is not None:
                update_payload[k] = v
        result = (
            db.table("workflow_instances")
            .update(update_payload)
            .eq("id", instance_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        return result.data[0] if result.data else None

    # ── Idempotency ───────────────────────────────────────────────────────────

    def check_idempotency(
        self,
        firm_id: str,
        template_id: str,
        trigger_event: str,
        idempotency_key: str,
    ) -> Optional[dict]:
        """Return existing instance if one already ran with this idempotency_key."""
        if _USE_MOCK:
            for i in MOCK_INSTANCES:
                if (
                    i["firm_id"] == firm_id
                    and i["template_id"] == template_id
                    and i["trigger_event"] == trigger_event
                    and i.get("idempotency_key") == idempotency_key
                ):
                    return i
            return None

        db = _get_db()
        result = (
            db.table("workflow_instances")
            .select("*")
            .eq("firm_id", firm_id)
            .eq("template_id", template_id)
            .eq("trigger_event", trigger_event)
            .eq("idempotency_key", idempotency_key)
            .maybe_single()
            .execute()
        )
        return result.data

    # ── Action Logs ───────────────────────────────────────────────────────────

    def log_action(
        self,
        instance_id: str,
        step_id: str,
        step_name: str,
        action_type: str,
        config: dict,
        status: str,
        result_data: Optional[dict] = None,
        error_message: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> dict:
        if _USE_MOCK:
            log = {
                "id": _uid(),
                "instance_id": instance_id,
                "step_id": step_id,
                "step_name": step_name,
                "action_type": action_type,
                "action_config": config,
                "status": status,
                "started_at": _now(),
                "completed_at": _now() if status != "running" else None,
                "duration_ms": duration_ms,
                "result_data": result_data,
                "error_message": error_message,
                "created_at": _now(),
            }
            MOCK_ACTION_LOGS.append(log)
            return log

        db = _get_db()
        payload = {
            "id": _uid(),
            "instance_id": instance_id,
            "step_id": step_id,
            "step_name": step_name,
            "action_type": action_type,
            "action_config": config,
            "status": status,
            "started_at": _now(),
            "completed_at": _now() if status != "running" else None,
            "duration_ms": duration_ms,
            "result_data": result_data,
            "error_message": error_message,
            "created_at": _now(),
        }
        result = db.table("workflow_action_logs").insert(payload).execute()
        return result.data[0]

    def update_action_log(self, log_id: str, status: str, result_data: Optional[dict] = None, error_message: Optional[str] = None, duration_ms: Optional[int] = None) -> Optional[dict]:
        if _USE_MOCK:
            for log in MOCK_ACTION_LOGS:
                if log["id"] == log_id:
                    log["status"] = status
                    log["completed_at"] = _now()
                    if result_data is not None:
                        log["result_data"] = result_data
                    if error_message is not None:
                        log["error_message"] = error_message
                    if duration_ms is not None:
                        log["duration_ms"] = duration_ms
                    return log
            return None

        db = _get_db()
        payload: dict = {"status": status, "completed_at": _now()}
        if result_data is not None:
            payload["result_data"] = result_data
        if error_message is not None:
            payload["error_message"] = error_message
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        result = db.table("workflow_action_logs").update(payload).eq("id", log_id).execute()
        return result.data[0] if result.data else None

    def list_action_logs(self, instance_id: str) -> list[dict]:
        if _USE_MOCK:
            return [log for log in MOCK_ACTION_LOGS if log["instance_id"] == instance_id]

        db = _get_db()
        result = (
            db.table("workflow_action_logs")
            .select("*")
            .eq("instance_id", instance_id)
            .order("created_at")
            .execute()
        )
        return result.data or []

    # ── Executions (Audit Trail) ───────────────────────────────────────────────

    def log_execution(
        self,
        instance_id: str,
        firm_id: str,
        event_type: str,
        event_data: dict,
        actor_id: Optional[str] = None,
        actor_type: str = "system",
    ) -> dict:
        if _USE_MOCK:
            event = {
                "id": _uid(),
                "instance_id": instance_id,
                "firm_id": firm_id,
                "event_type": event_type,
                "event_data": event_data,
                "actor_id": actor_id,
                "actor_type": actor_type if actor_id else "system",
                "created_at": _now(),
            }
            MOCK_EXECUTIONS.append(event)
            return event

        db = _get_db()
        payload = {
            "id": _uid(),
            "instance_id": instance_id,
            "firm_id": firm_id,
            "event_type": event_type,
            "event_data": event_data,
            "actor_id": actor_id,
            "actor_type": actor_type if actor_id else "system",
            "created_at": _now(),
        }
        result = db.table("workflow_executions").insert(payload).execute()
        return result.data[0]

    def list_executions(self, firm_id: str, instance_id: Optional[str] = None, limit: int = 50) -> list[dict]:
        if _USE_MOCK:
            events = [e for e in MOCK_EXECUTIONS if e["firm_id"] == firm_id]
            if instance_id:
                events = [e for e in events if e["instance_id"] == instance_id]
            events.sort(key=lambda e: e["created_at"], reverse=True)
            return events[:limit]

        db = _get_db()
        query = db.table("workflow_executions").select("*").eq("firm_id", firm_id)
        if instance_id:
            query = query.eq("instance_id", instance_id)
        query = query.order("created_at", desc=True).limit(limit)
        result = query.execute()
        return result.data or []

    # ── Failures ──────────────────────────────────────────────────────────────

    def log_failure(
        self,
        firm_id: str,
        instance_id: str,
        step_id: Optional[str],
        error_type: str,
        error_message: str,
        error_data: Optional[dict] = None,
        retry_count: int = 0,
    ) -> dict:
        if _USE_MOCK:
            failure = {
                "id": _uid(),
                "instance_id": instance_id,
                "firm_id": firm_id,
                "step_id": step_id,
                "error_type": error_type,
                "error_message": error_message,
                "error_data": error_data,
                "retry_count": retry_count,
                "resolved": False,
                "resolved_at": None,
                "resolved_by": None,
                "created_at": _now(),
            }
            MOCK_FAILURES.append(failure)
            return failure

        db = _get_db()
        payload = {
            "id": _uid(),
            "instance_id": instance_id,
            "firm_id": firm_id,
            "step_id": step_id,
            "error_type": error_type,
            "error_message": error_message,
            "error_data": error_data,
            "retry_count": retry_count,
            "resolved": False,
            "resolved_at": None,
            "resolved_by": None,
            "created_at": _now(),
        }
        result = db.table("workflow_failures").insert(payload).execute()
        return result.data[0]

    def list_failures(self, firm_id: str, resolved: Optional[bool] = False, limit: int = 50) -> list[dict]:
        if _USE_MOCK:
            failures = [f for f in MOCK_FAILURES if f["firm_id"] == firm_id]
            if resolved is not None:
                failures = [f for f in failures if f["resolved"] == resolved]
            failures.sort(key=lambda f: f["created_at"], reverse=True)
            return failures[:limit]

        db = _get_db()
        query = db.table("workflow_failures").select("*").eq("firm_id", firm_id)
        if resolved is not None:
            query = query.eq("resolved", resolved)
        query = query.order("created_at", desc=True).limit(limit)
        result = query.execute()
        return result.data or []

    def resolve_failure(self, firm_id: str, failure_id: str, resolved_by: str) -> Optional[dict]:
        if _USE_MOCK:
            for f in MOCK_FAILURES:
                if f["id"] == failure_id and f["firm_id"] == firm_id:
                    f["resolved"] = True
                    f["resolved_at"] = _now()
                    f["resolved_by"] = resolved_by
                    return f
            return None

        db = _get_db()
        result = (
            db.table("workflow_failures")
            .update({"resolved": True, "resolved_at": _now(), "resolved_by": resolved_by})
            .eq("id", failure_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        return result.data[0] if result.data else None

    # ── Approvals ─────────────────────────────────────────────────────────────

    def create_approval(
        self,
        firm_id: str,
        instance_id: str,
        step_id: str,
        step_name: str,
        approver_role: str,
        title: str,
        description: str,
        context_data: dict,
        due_at: Optional[str] = None,
    ) -> dict:
        if _USE_MOCK:
            approval = {
                "id": _uid(),
                "firm_id": firm_id,
                "instance_id": instance_id,
                "step_id": step_id,
                "step_name": step_name,
                "approver_role": approver_role,
                "approver_id": None,
                "title": title,
                "description": description,
                "context_data": context_data,
                "due_at": due_at,
                "status": "pending",
                "responded_at": None,
                "responder_id": None,
                "response_notes": None,
                "created_at": _now(),
                "updated_at": _now(),
            }
            MOCK_APPROVALS.append(approval)
            return approval

        db = _get_db()
        payload = {
            "id": _uid(),
            "firm_id": firm_id,
            "instance_id": instance_id,
            "step_id": step_id,
            "step_name": step_name,
            "approver_role": approver_role,
            "approver_id": None,
            "title": title,
            "description": description,
            "context_data": context_data,
            "due_at": due_at,
            "status": "pending",
            "responded_at": None,
            "responder_id": None,
            "response_notes": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        result = db.table("workflow_approvals").insert(payload).execute()
        return result.data[0]

    def list_approvals(self, firm_id: str, status: Optional[str] = None, limit: int = 50) -> list[dict]:
        if _USE_MOCK:
            approvals = [a for a in MOCK_APPROVALS if a["firm_id"] == firm_id]
            if status:
                approvals = [a for a in approvals if a["status"] == status]
            approvals.sort(key=lambda a: a["created_at"], reverse=True)
            return approvals[:limit]

        db = _get_db()
        query = db.table("workflow_approvals").select("*").eq("firm_id", firm_id)
        if status:
            query = query.eq("status", status)
        query = query.order("created_at", desc=True).limit(limit)
        result = query.execute()
        return result.data or []

    def get_approval(self, firm_id: str, approval_id: str) -> Optional[dict]:
        if _USE_MOCK:
            for a in MOCK_APPROVALS:
                if a["id"] == approval_id and a["firm_id"] == firm_id:
                    return a
            return None

        db = _get_db()
        result = (
            db.table("workflow_approvals")
            .select("*")
            .eq("id", approval_id)
            .eq("firm_id", firm_id)
            .maybe_single()
            .execute()
        )
        return result.data

    def respond_approval(
        self,
        firm_id: str,
        approval_id: str,
        decision: str,
        response_notes: str,
        responder_id: str,
    ) -> Optional[dict]:
        if _USE_MOCK:
            for a in MOCK_APPROVALS:
                if a["id"] == approval_id and a["firm_id"] == firm_id and a["status"] == "pending":
                    a["status"] = decision  # "approved" | "rejected"
                    a["responded_at"] = _now()
                    a["responder_id"] = responder_id
                    a["response_notes"] = response_notes
                    a["updated_at"] = _now()
                    return a
            return None

        db = _get_db()
        result = (
            db.table("workflow_approvals")
            .update({
                "status": decision,
                "responded_at": _now(),
                "responder_id": responder_id,
                "response_notes": response_notes,
                "updated_at": _now(),
            })
            .eq("id", approval_id)
            .eq("firm_id", firm_id)
            .eq("status", "pending")
            .execute()
        )
        return result.data[0] if result.data else None

    def escalate_overdue_approvals(self, firm_id: str) -> list[dict]:
        now_str = _now()
        if _USE_MOCK:
            escalated = []
            for a in MOCK_APPROVALS:
                if (
                    a["firm_id"] == firm_id
                    and a["status"] == "pending"
                    and a.get("due_at")
                    and a["due_at"] < now_str
                ):
                    a["status"] = "escalated"
                    a["updated_at"] = _now()
                    escalated.append(a)
            return escalated

        db = _get_db()
        result = (
            db.table("workflow_approvals")
            .update({"status": "escalated", "updated_at": _now()})
            .eq("firm_id", firm_id)
            .eq("status", "pending")
            .lt("due_at", now_str)
            .execute()
        )
        return result.data or []

    # ── Schedules ─────────────────────────────────────────────────────────────

    def list_schedules(self, firm_id: str, is_active: Optional[bool] = None) -> list[dict]:
        if _USE_MOCK:
            schedules = [s for s in MOCK_SCHEDULES if s["firm_id"] == firm_id]
            if is_active is not None:
                schedules = [s for s in schedules if s["is_active"] == is_active]
            return schedules

        db = _get_db()
        query = db.table("workflow_schedules").select("*").eq("firm_id", firm_id)
        if is_active is not None:
            query = query.eq("is_active", is_active)
        result = query.order("created_at", desc=True).execute()
        return result.data or []

    def create_schedule(
        self,
        firm_id: str,
        template_id: str,
        name: str,
        cron_expression: str,
        timezone: str = "Asia/Kolkata",
        user_id: Optional[str] = None,
    ) -> dict:
        if _USE_MOCK:
            schedule = {
                "id": _uid(),
                "firm_id": firm_id,
                "template_id": template_id,
                "name": name,
                "cron_expression": cron_expression,
                "timezone": timezone,
                "is_active": True,
                "last_run_at": None,
                "next_run_at": None,
                "last_run_status": None,
                "run_count": 0,
                "created_by": user_id,
                "created_at": _now(),
                "updated_at": _now(),
            }
            MOCK_SCHEDULES.append(schedule)
            return schedule

        db = _get_db()
        payload = {
            "id": _uid(),
            "firm_id": firm_id,
            "template_id": template_id,
            "name": name,
            "cron_expression": cron_expression,
            "timezone": timezone,
            "is_active": True,
            "last_run_at": None,
            "next_run_at": None,
            "last_run_status": None,
            "run_count": 0,
            "created_by": user_id,
            "created_at": _now(),
            "updated_at": _now(),
        }
        result = db.table("workflow_schedules").insert(payload).execute()
        return result.data[0]

    def toggle_schedule(self, firm_id: str, schedule_id: str) -> Optional[dict]:
        if _USE_MOCK:
            for s in MOCK_SCHEDULES:
                if s["id"] == schedule_id and s["firm_id"] == firm_id:
                    s["is_active"] = not s["is_active"]
                    s["updated_at"] = _now()
                    return s
            return None

        db = _get_db()
        # Fetch current state first to toggle
        result = (
            db.table("workflow_schedules")
            .select("is_active")
            .eq("id", schedule_id)
            .eq("firm_id", firm_id)
            .maybe_single()
            .execute()
        )
        if not result.data:
            return None
        new_state = not result.data["is_active"]
        update_result = (
            db.table("workflow_schedules")
            .update({"is_active": new_state, "updated_at": _now()})
            .eq("id", schedule_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        return update_result.data[0] if update_result.data else None

    def delete_schedule(self, firm_id: str, schedule_id: str) -> bool:
        if _USE_MOCK:
            orig = len(MOCK_SCHEDULES)
            MOCK_SCHEDULES[:] = [s for s in MOCK_SCHEDULES if not (s["id"] == schedule_id and s["firm_id"] == firm_id)]
            return len(MOCK_SCHEDULES) < orig

        db = _get_db()
        result = (
            db.table("workflow_schedules")
            .delete()
            .eq("id", schedule_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        return bool(result.data)

    def update_schedule_run(
        self,
        schedule_id: str,
        status: str,
        next_run_at: Optional[str] = None,
    ) -> Optional[dict]:
        if _USE_MOCK:
            for s in MOCK_SCHEDULES:
                if s["id"] == schedule_id:
                    s["last_run_at"] = _now()
                    s["last_run_status"] = status
                    s["run_count"] = s.get("run_count", 0) + 1
                    if next_run_at:
                        s["next_run_at"] = next_run_at
                    s["updated_at"] = _now()
                    return s
            return None

        db = _get_db()
        payload: dict = {
            "last_run_at": _now(),
            "last_run_status": status,
            "updated_at": _now(),
        }
        if next_run_at:
            payload["next_run_at"] = next_run_at
        # Increment run_count via fetch+update
        cur = db.table("workflow_schedules").select("run_count").eq("id", schedule_id).maybe_single().execute()
        payload["run_count"] = (cur.data.get("run_count", 0) + 1) if cur.data else 1
        result = db.table("workflow_schedules").update(payload).eq("id", schedule_id).execute()
        return result.data[0] if result.data else None

    def list_schedules_due(self, now_iso: str) -> list[dict]:
        """Return all active schedules whose next_run_at <= now_iso (mock mode)."""
        if _USE_MOCK:
            return [
                s for s in MOCK_SCHEDULES
                if s.get("is_active", False)
                and s.get("next_run_at") is not None
                and s["next_run_at"] <= now_iso
            ]
        # Real DB path — caller should query directly via Supabase client
        db = _get_db()
        result = (
            db.table("workflow_schedules")
            .select("*")
            .eq("is_active", True)
            .lte("next_run_at", now_iso)
            .execute()
        )
        return result.data or []

    def _update_step(self, step_id: str, data: dict) -> Optional[dict]:
        """Update a workflow step by id (mock only — used by tests for cycle/link setup)."""
        if _USE_MOCK:
            for s in MOCK_STEPS:
                if s["id"] == step_id:
                    s.update(data)
                    s["updated_at"] = _now()
                    return s
            return None
        db = _get_db()
        result = db.table("workflow_steps").update(data).eq("id", step_id).execute()
        return result.data[0] if result.data else None

    # ── Analytics ─────────────────────────────────────────────────────────────

    def get_analytics(self, firm_id: str, template_id: Optional[str] = None) -> list[dict]:
        now = datetime.utcnow()
        seven_days_ago = (now - timedelta(days=7)).isoformat()
        thirty_days_ago = (now - timedelta(days=30)).isoformat()

        if _USE_MOCK:
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
                instance_ids = {i["id"] for i in instances}
                pending_approvals = len([
                    a for a in MOCK_APPROVALS
                    if a["firm_id"] == firm_id
                    and a["instance_id"] in instance_ids
                    and a["status"] == "pending"
                ])
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

        # Real DB: separate queries, aggregate in Python
        db = _get_db()
        tmpl_query = (
            db.table("workflow_templates")
            .select("id, name, avg_duration_ms")
            .or_(f"firm_id.eq.{firm_id},is_system.eq.true")
        )
        if template_id:
            tmpl_query = tmpl_query.eq("id", template_id)
        templates = (tmpl_query.execute().data or [])

        if not templates:
            return []

        template_ids = [t["id"] for t in templates]
        # Fetch all instances for these templates in this firm
        inst_result = (
            db.table("workflow_instances")
            .select("id, template_id, status, created_at")
            .eq("firm_id", firm_id)
            .in_("template_id", template_ids)
            .execute()
        )
        all_instances = inst_result.data or []

        # Fetch pending approvals for this firm
        appr_result = (
            db.table("workflow_approvals")
            .select("instance_id")
            .eq("firm_id", firm_id)
            .eq("status", "pending")
            .execute()
        )
        pending_approval_instance_ids = {a["instance_id"] for a in (appr_result.data or [])}

        result = []
        for t in templates:
            tid = t["id"]
            instances = [i for i in all_instances if i["template_id"] == tid]
            successful = sum(1 for i in instances if i["status"] == "completed")
            failed = sum(1 for i in instances if i["status"] == "failed")
            total = len(instances)
            success_rate = (successful * 100 // total) if total > 0 else 0
            instance_ids = {i["id"] for i in instances}
            pending_approvals = len(instance_ids & pending_approval_instance_ids)
            last_7 = sum(1 for i in instances if i["created_at"] >= seven_days_ago)
            last_30 = sum(1 for i in instances if i["created_at"] >= thirty_days_ago)
            result.append({
                "template_id": tid,
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
        "avg_duration_ms": 86400000,
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
        "idempotency_key": None,
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
        "idempotency_key": None,
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
