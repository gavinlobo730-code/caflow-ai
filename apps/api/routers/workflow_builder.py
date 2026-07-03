"""
Phase 10 — Workflow Builder API.
Endpoints for managing workflow templates, instances, approvals, schedules, analytics.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from models.common import api_response
from models.workflow import (
    WorkflowTemplateIn, WorkflowTemplateUpdate,
    WorkflowScheduleIn, ApprovalResponseIn,
)
from core.permissions import rbac

router = APIRouter(prefix="/api/workflows", tags=["Workflows Phase 10"])


def _repo():
    from repositories.workflow_repository import workflow_repo
    return workflow_repo


def _engine():
    from domain.workflow_engine_v2 import workflow_engine
    return workflow_engine


# ── Templates ──────────────────────────────────────────────────────────────────

@router.get("/templates")
def list_templates(
    category: Optional[str] = None,
    trigger_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    current_user: dict = Depends(rbac("task", "read")),
):
    firm_id = current_user["firm_id"]
    templates = _repo().list_templates(firm_id, category=category, trigger_type=trigger_type,
                                        is_active=is_active, search=search, limit=limit, offset=offset)
    return api_response(True, {"templates": templates, "total": len(templates)})


@router.post("/templates")
def create_template(
    payload: WorkflowTemplateIn,
    current_user: dict = Depends(rbac("task", "write")),
):
    firm_id = current_user["firm_id"]
    user_id = current_user.get("auth_user_id")
    data = payload.model_dump()
    template = _repo().create_template(firm_id, data, user_id)
    return api_response(True, template)


@router.get("/templates/{template_id}")
def get_template(
    template_id: str,
    current_user: dict = Depends(rbac("task", "read")),
):
    firm_id = current_user["firm_id"]
    template = _repo().get_template(firm_id, template_id)
    if not template:
        raise HTTPException(404, "Workflow template not found")
    return api_response(True, template)


@router.patch("/templates/{template_id}")
def update_template(
    template_id: str,
    payload: WorkflowTemplateUpdate,
    current_user: dict = Depends(rbac("task", "write")),
):
    firm_id = current_user["firm_id"]
    user_id = current_user.get("auth_user_id")
    updated = _repo().update_template(firm_id, template_id, payload.model_dump(exclude_none=True), user_id)
    if not updated:
        raise HTTPException(404, "Workflow template not found")
    return api_response(True, updated)


@router.delete("/templates/{template_id}")
def delete_template(
    template_id: str,
    current_user: dict = Depends(rbac("task", "delete")),
):
    firm_id = current_user["firm_id"]
    deleted = _repo().delete_template(firm_id, template_id)
    if not deleted:
        raise HTTPException(404, "Workflow template not found")
    return api_response(True, {"deleted": True, "template_id": template_id})


@router.post("/templates/{template_id}/toggle")
def toggle_template(
    template_id: str,
    current_user: dict = Depends(rbac("task", "write")),
):
    firm_id = current_user["firm_id"]
    template = _repo().get_template(firm_id, template_id)
    if not template:
        raise HTTPException(404, "Workflow template not found")
    updated = _repo().update_template(firm_id, template_id, {"is_active": not template["is_active"]})
    return api_response(True, {"is_active": updated["is_active"]})


# ── Trigger (manually fire a workflow) ────────────────────────────────────────

@router.post("/templates/{template_id}/trigger")
def manually_trigger(
    template_id: str,
    payload: dict = {},
    current_user: dict = Depends(rbac("task", "write")),
):
    """Manually fire a workflow template with optional trigger data."""
    firm_id = current_user["firm_id"]
    template = _repo().get_template(firm_id, template_id)
    if not template:
        raise HTTPException(404, "Workflow template not found")
    results = _engine().fire_trigger(
        firm_id=firm_id,
        trigger_type=template["trigger_type"],
        trigger_data=payload,
        client_id=payload.get("client_id"),
    )
    return api_response(True, {"instances_started": len(results), "instances": results})


# ── Instances ─────────────────────────────────────────────────────────────────

@router.get("/instances")
def list_instances(
    template_id: Optional[str] = None,
    client_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    current_user: dict = Depends(rbac("task", "read")),
):
    firm_id = current_user["firm_id"]
    instances = _repo().list_instances(firm_id, template_id=template_id, client_id=client_id,
                                        status=status, limit=limit, offset=offset)
    return api_response(True, {"instances": instances, "total": len(instances)})


@router.get("/instances/{instance_id}")
def get_instance(
    instance_id: str,
    current_user: dict = Depends(rbac("task", "read")),
):
    firm_id = current_user["firm_id"]
    instance = _repo().get_instance(firm_id, instance_id)
    if not instance:
        raise HTTPException(404, "Workflow instance not found")
    logs = _repo().list_action_logs(instance_id)
    executions = _repo().list_executions(firm_id, instance_id=instance_id)
    return api_response(True, {**instance, "action_logs": logs, "audit_trail": executions})


@router.post("/instances/{instance_id}/cancel")
def cancel_instance(
    instance_id: str,
    current_user: dict = Depends(rbac("task", "write")),
):
    firm_id = current_user["firm_id"]
    instance = _repo().get_instance(firm_id, instance_id)
    if not instance:
        raise HTTPException(404, "Workflow instance not found")
    if instance["status"] in ("completed", "failed", "cancelled"):
        raise HTTPException(400, f"Cannot cancel instance in status: {instance['status']}")
    # F11/F12 hardening: this call passed (instance_id, "cancelled") into a
    # (firm_id, instance_id, status, ...) signature — a TypeError on every
    # cancel; the builder's write paths had never been exercised end to end.
    updated = _repo().update_instance_status(firm_id, instance_id, "cancelled")
    _repo().log_execution(instance_id, firm_id, "cancelled", {"by": current_user.get("auth_user_id")})
    return api_response(True, updated)


# ── Approvals ─────────────────────────────────────────────────────────────────

@router.get("/approvals")
def list_approvals(
    status: Optional[str] = "pending",
    limit: int = Query(50, le=200),
    current_user: dict = Depends(rbac("task", "read")),
):
    firm_id = current_user["firm_id"]
    user_id = current_user.get("auth_user_id")
    approvals = _repo().list_approvals(firm_id, status=status, limit=limit)
    # Enrich with template names
    for a in approvals:
        instance = _repo().get_instance(firm_id, a["instance_id"])
        if instance:
            template = _repo().get_template(firm_id, instance["template_id"])
            a["template_name"] = template["name"] if template else None
            a["client_id"] = instance.get("client_id")
    return api_response(True, {"approvals": approvals, "total": len(approvals)})


@router.post("/approvals/{approval_id}/respond")
def respond_to_approval(
    approval_id: str,
    payload: ApprovalResponseIn,
    current_user: dict = Depends(rbac("task", "write")),
):
    firm_id = current_user["firm_id"]
    user_id = current_user.get("auth_user_id", "unknown")
    # Signature is (firm_id, approval_id, decision, response_notes,
    # responder_id) — the old call swapped the last two, persisting the
    # responder's id as the notes and the notes as the responder.
    approval = _repo().respond_approval(
        firm_id, approval_id, payload.decision, payload.response_notes or "", user_id)
    if not approval:
        raise HTTPException(404, "Approval not found or already responded")
    # Resume/cancel workflow
    _engine().resume_after_approval(
        firm_id,
        approval["instance_id"],
        approved=(payload.decision == "approved"),
        user_id=user_id,
    )
    return api_response(True, approval)


# ── Schedules ─────────────────────────────────────────────────────────────────

@router.get("/schedules")
def list_schedules(
    is_active: Optional[bool] = None,
    current_user: dict = Depends(rbac("task", "read")),
):
    firm_id = current_user["firm_id"]
    schedules = _repo().list_schedules(firm_id, is_active=is_active)
    # Enrich with template names
    for s in schedules:
        template = _repo().get_template(firm_id, s["template_id"])
        s["template_name"] = template["name"] if template else None
    return api_response(True, {"schedules": schedules})


@router.post("/schedules")
def create_schedule(
    payload: WorkflowScheduleIn,
    current_user: dict = Depends(rbac("task", "write")),
):
    firm_id = current_user["firm_id"]
    user_id = current_user.get("auth_user_id")
    template = _repo().get_template(firm_id, payload.template_id)
    if not template:
        raise HTTPException(404, "Workflow template not found")
    # Explicit kwargs — the old call passed the whole payload dict as the
    # template_id positional (TypeError on every schedule creation).
    schedule = _repo().create_schedule(
        firm_id,
        template_id=payload.template_id,
        name=payload.name,
        cron_expression=payload.cron_expression,
        timezone=payload.timezone,
        user_id=user_id,
    )
    return api_response(True, schedule)


@router.patch("/schedules/{schedule_id}/toggle")
def toggle_schedule(
    schedule_id: str,
    current_user: dict = Depends(rbac("task", "write")),
):
    firm_id = current_user["firm_id"]
    # Find schedule
    schedules = _repo().list_schedules(firm_id)
    schedule = next((s for s in schedules if s["id"] == schedule_id), None)
    if not schedule:
        raise HTTPException(404, "Schedule not found")
    # toggle_schedule(firm_id, schedule_id) flips is_active itself — the old
    # call passed a third bool that the 2-arg signature rejects (TypeError).
    updated = _repo().toggle_schedule(firm_id, schedule_id)
    return api_response(True, updated)


@router.delete("/schedules/{schedule_id}")
def delete_schedule(
    schedule_id: str,
    current_user: dict = Depends(rbac("task", "delete")),
):
    firm_id = current_user["firm_id"]
    deleted = _repo().delete_schedule(firm_id, schedule_id)
    if not deleted:
        raise HTTPException(404, "Schedule not found")
    return api_response(True, {"deleted": True})


# ── Analytics ─────────────────────────────────────────────────────────────────

@router.get("/analytics")
def get_analytics(
    template_id: Optional[str] = None,
    days: int = Query(30, ge=1, le=365),
    current_user: dict = Depends(rbac("task", "read")),
):
    """
    GET /api/workflows/analytics?firm_id=&days=30
    Returns workflow performance analytics: execution counts, success rate,
    avg duration, top templates, and common failure patterns.
    Product Bible Chapter 17 — Workflow Engine analytics.
    """
    firm_id = current_user["firm_id"]
    analytics = _repo().get_analytics(firm_id, template_id=template_id)
    pending_approvals = len(_repo().list_approvals(firm_id, status="pending"))
    unresolved_failures = len(_repo().list_failures(firm_id, resolved=False))
    total_executions = sum(a["total_executions"] for a in analytics)
    total_successful = sum(a["successful"] for a in analytics)
    overall_success_rate = (total_successful * 100 // total_executions) if total_executions > 0 else 0

    # Build top_templates sorted by execution count descending
    top_templates = sorted(
        [
            {
                "template_id": a.get("template_id"),
                "template_name": a.get("template_name", "Unknown"),
                "executions": a["total_executions"],
                "success_rate": (
                    (a["successful"] * 100 // a["total_executions"])
                    if a["total_executions"] > 0 else 0
                ),
                "avg_duration_ms": a.get("avg_duration_ms", 0),
            }
            for a in analytics
        ],
        key=lambda x: x["executions"],
        reverse=True,
    )[:10]

    # Aggregate common failure patterns from failure records
    failures = _repo().list_failures(firm_id, resolved=False, limit=200)
    failure_counts: dict[str, int] = {}
    for f in failures:
        error_type = f.get("error_type") or f.get("failure_type") or "unknown"
        failure_counts[error_type] = failure_counts.get(error_type, 0) + 1
    common_failures = [
        {"error_type": k, "count": v}
        for k, v in sorted(failure_counts.items(), key=lambda x: -x[1])
    ][:5]

    # avg_duration_ms: weighted average across all templates
    total_weighted_ms = sum(
        (a.get("avg_duration_ms") or 0) * a["total_executions"]
        for a in analytics
    )
    avg_duration_ms = (total_weighted_ms // total_executions) if total_executions > 0 else 0

    return api_response(True, {
        "total_executions": total_executions,
        "success_rate": overall_success_rate,
        "avg_duration_ms": avg_duration_ms,
        "top_templates": top_templates,
        "common_failures": common_failures,
        # Legacy summary block kept for backward compatibility
        "summary": {
            "total_templates": len(analytics),
            "total_executions": total_executions,
            "overall_success_rate": overall_success_rate,
            "pending_approvals": pending_approvals,
            "unresolved_failures": unresolved_failures,
        },
        "by_template": analytics,
        "days": days,
    })


# ── Failures ──────────────────────────────────────────────────────────────────

@router.get("/failures")
def list_failures(
    resolved: Optional[bool] = False,
    limit: int = 50,
    current_user: dict = Depends(rbac("task", "read")),
):
    firm_id = current_user["firm_id"]
    failures = _repo().list_failures(firm_id, resolved=resolved, limit=limit)
    return api_response(True, {"failures": failures})


@router.post("/failures/{failure_id}/resolve")
def resolve_failure(
    failure_id: str,
    current_user: dict = Depends(rbac("task", "write")),
):
    firm_id = current_user["firm_id"]
    user_id = current_user.get("auth_user_id", "unknown")
    resolved = _repo().resolve_failure(firm_id, failure_id, user_id)
    if not resolved:
        raise HTTPException(404, "Failure not found")
    return api_response(True, resolved)


# ── Executions (audit trail) ──────────────────────────────────────────────────

@router.get("/executions")
def list_executions(
    instance_id: Optional[str] = None,
    limit: int = Query(100, le=500),
    current_user: dict = Depends(rbac("task", "read")),
):
    firm_id = current_user["firm_id"]
    executions = _repo().list_executions(firm_id, instance_id=instance_id, limit=limit)
    return api_response(True, {"executions": executions})
