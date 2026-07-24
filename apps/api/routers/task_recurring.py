from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access
from repositories.assignment_rule_repository import assignment_rule_repo

router = APIRouter(prefix="/api/task-recurring", tags=["task-recurring"])


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class RecurringCreate(BaseModel):
    client_id: Optional[str] = None
    template_id: Optional[str] = None
    assignee_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    priority: str = "medium"
    frequency: str  # daily, weekly, monthly, quarterly, annual
    next_due_date: str  # YYYY-MM-DD
    is_active: bool = True


class RecurringUpdate(BaseModel):
    client_id: Optional[str] = None
    assignee_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    frequency: Optional[str] = None
    next_due_date: Optional[str] = None
    is_active: Optional[bool] = None


class AssignmentRuleCreate(BaseModel):
    rule_type: str  # 'fixed_user', 'by_role', 'by_team', 'fallback'
    target_value: Optional[str] = None  # user_id, role, team_id, or NULL
    priority: int = 0
    is_active: bool = True


class AssignmentRuleUpdate(BaseModel):
    rule_type: Optional[str] = None
    target_value: Optional[str] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


VALID_FREQUENCIES = {"daily", "weekly", "monthly", "quarterly", "annual"}
VALID_RULE_TYPES = {"fixed_user", "by_role", "by_team", "fallback"}


@router.get("")
def list_recurring(current_user: dict = Depends(rbac("task", "read"))):
    firm_id = current_user.get("firm_id")
    db = _get_db()
    result = db.table("task_recurring_configs").select("*").eq("firm_id", firm_id).order("next_due_date").execute()
    configs = result.data or []

    # Enrich with template names — scoped to this firm's own templates or
    # shared system templates (firm_id IS NULL), never another firm's private
    # template even if a stray template_id somehow ended up on a config row.
    template_ids = list({c["template_id"] for c in configs if c.get("template_id")})
    template_map = {}
    if template_ids:
        tpl_result = db.table("task_templates").select("id, name").in_("id", template_ids).or_(
            f"firm_id.eq.{firm_id},firm_id.is.null"
        ).execute()
        template_map = {t["id"]: t["name"] for t in (tpl_result.data or [])}

    # Enrich with client names — scoped to this firm only.
    client_ids = list({c["client_id"] for c in configs if c.get("client_id")})
    client_map = {}
    if client_ids:
        cl_result = db.table("clients").select("id, client_name").in_("id", client_ids).eq("firm_id", firm_id).execute()
        client_map = {c["id"]: c["client_name"] for c in (cl_result.data or [])}

    for c in configs:
        c["template_name"] = template_map.get(c.get("template_id"))
        c["client_name"] = client_map.get(c.get("client_id"))

    return api_response(True, {"configs": configs, "total": len(configs)})


@router.post("")
def create_recurring(body: RecurringCreate, current_user: dict = Depends(rbac("task", "write"))):
    if body.frequency not in VALID_FREQUENCIES:
        raise HTTPException(status_code=400, detail=f"Invalid frequency. Must be one of: {', '.join(VALID_FREQUENCIES)}")
    if not body.title and not body.template_id:
        raise HTTPException(status_code=400, detail="Either title or template_id is required")

    firm_id = current_user.get("firm_id")
    db = _get_db()

    # client_id/template_id are caller-supplied — verify ownership before
    # inserting, so a recurring config can't be planted cross-referencing
    # another firm's real client/template (which would then leak that firm's
    # client_name/template_name back out through list_recurring's enrichment).
    if body.client_id:
        assert_client_access(current_user, body.client_id)
    if body.template_id:
        tpl = db.table("task_templates").select("id").eq("id", body.template_id).or_(
            f"firm_id.eq.{firm_id},firm_id.is.null"
        ).maybe_single().execute()
        if not tpl.data:
            raise HTTPException(status_code=404, detail="Template not found")

    now = _now_iso()
    result = db.table("task_recurring_configs").insert({
        "firm_id": firm_id,
        "client_id": body.client_id,
        "template_id": body.template_id,
        "assignee_id": body.assignee_id,
        "title": body.title,
        "description": body.description,
        "priority": body.priority,
        "frequency": body.frequency,
        "next_due_date": body.next_due_date,
        "is_active": body.is_active,
        "created_at": now,
        "updated_at": now,
    }).execute()
    return api_response(True, {"config": result.data[0]})


@router.put("/{config_id}")
def update_recurring(config_id: str, body: RecurringUpdate, current_user: dict = Depends(rbac("task", "write"))):
    firm_id = current_user.get("firm_id")
    db = _get_db()
    existing = db.table("task_recurring_configs").select("id").eq("id", config_id).eq("firm_id", firm_id).maybe_single().execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Recurring config not found")

    if body.client_id:
        assert_client_access(current_user, body.client_id)

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "frequency" in updates and updates["frequency"] not in VALID_FREQUENCIES:
        raise HTTPException(status_code=400, detail=f"Invalid frequency")
    updates["updated_at"] = _now_iso()
    result = db.table("task_recurring_configs").update(updates).eq("id", config_id).eq("firm_id", firm_id).execute()
    return api_response(True, {"config": result.data[0] if result.data else None})


@router.delete("/{config_id}")
def delete_recurring(config_id: str, current_user: dict = Depends(rbac("task", "write"))):
    firm_id = current_user.get("firm_id")
    db = _get_db()
    db.table("task_recurring_configs").delete().eq("id", config_id).eq("firm_id", firm_id).execute()
    return api_response(True, {"deleted": True})


@router.post("/generate")
def generate_tasks(current_user: dict = Depends(rbac("task", "write"))):
    from services.recurring_task_service import generate_due_recurring_tasks
    firm_id = current_user.get("firm_id")
    created = generate_due_recurring_tasks(firm_id=firm_id)
    return api_response(True, {"generated": len(created), "tasks": created})


@router.get("/{config_id}/rules")
def list_assignment_rules(config_id: str, current_user: dict = Depends(rbac("task", "read"))):
    firm_id = current_user.get("firm_id")
    db = _get_db()

    # Verify config exists and belongs to firm
    config_result = db.table("task_recurring_configs").select("id").eq("id", config_id).eq("firm_id", firm_id).maybe_single().execute()
    if not config_result.data:
        raise HTTPException(status_code=404, detail="Recurring config not found")

    rules = assignment_rule_repo.find_all(firm_id=firm_id, recurring_config_id=config_id)
    return api_response(True, {"rules": rules, "total": len(rules)})


@router.post("/{config_id}/rules")
def create_assignment_rule(config_id: str, body: AssignmentRuleCreate, current_user: dict = Depends(rbac("task", "write"))):
    firm_id = current_user.get("firm_id")
    db = _get_db()

    # Validate rule_type
    if body.rule_type not in VALID_RULE_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid rule_type. Must be one of: {', '.join(VALID_RULE_TYPES)}")

    # Verify config exists and belongs to firm
    config_result = db.table("task_recurring_configs").select("id").eq("id", config_id).eq("firm_id", firm_id).maybe_single().execute()
    if not config_result.data:
        raise HTTPException(status_code=404, detail="Recurring config not found")

    # For fixed_user type, verify the user exists and belongs to firm
    if body.rule_type == "fixed_user" and body.target_value:
        user_result = db.table("users").select("id").eq("id", body.target_value).eq("firm_id", firm_id).maybe_single().execute()
        if not user_result.data:
            raise HTTPException(status_code=400, detail="Invalid user_id for fixed_user rule")

    rule = assignment_rule_repo.create({
        "firm_id": firm_id,
        "recurring_config_id": config_id,
        "rule_type": body.rule_type,
        "target_value": body.target_value,
        "priority": body.priority,
        "is_active": body.is_active,
    })
    return api_response(True, {"rule": rule})


@router.patch("/{config_id}/rules/{rule_id}")
def update_assignment_rule(config_id: str, rule_id: str, body: AssignmentRuleUpdate, current_user: dict = Depends(rbac("task", "write"))):
    firm_id = current_user.get("firm_id")
    db = _get_db()

    # Verify rule exists and belongs to firm
    rule_result = db.table("assignment_rules").select("id").eq("id", rule_id).eq("firm_id", firm_id).eq("recurring_config_id", config_id).maybe_single().execute()
    if not rule_result.data:
        raise HTTPException(status_code=404, detail="Assignment rule not found")

    # Validate rule_type if provided
    if body.rule_type and body.rule_type not in VALID_RULE_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid rule_type. Must be one of: {', '.join(VALID_RULE_TYPES)}")

    # For fixed_user type, verify the user exists and belongs to firm
    if body.rule_type == "fixed_user" and body.target_value:
        user_result = db.table("users").select("id").eq("id", body.target_value).eq("firm_id", firm_id).maybe_single().execute()
        if not user_result.data:
            raise HTTPException(status_code=400, detail="Invalid user_id for fixed_user rule")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    rule = assignment_rule_repo.update(rule_id, updates)
    return api_response(True, {"rule": rule})


@router.delete("/{config_id}/rules/{rule_id}")
def delete_assignment_rule(config_id: str, rule_id: str, current_user: dict = Depends(rbac("task", "write"))):
    firm_id = current_user.get("firm_id")
    db = _get_db()

    # Verify rule exists and belongs to firm
    rule_result = db.table("assignment_rules").select("id").eq("id", rule_id).eq("firm_id", firm_id).eq("recurring_config_id", config_id).maybe_single().execute()
    if not rule_result.data:
        raise HTTPException(status_code=404, detail="Assignment rule not found")

    assignment_rule_repo.delete(rule_id)
    return api_response(True, {"deleted": True})
