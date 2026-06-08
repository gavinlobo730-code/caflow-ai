from fastapi import APIRouter, Depends
from pydantic import BaseModel
from core.permissions import rbac
from typing import Any
from models.common import api_response
from repositories.automation_repository import automation_repo
from domain.automation_engine import evaluate_rules

router = APIRouter(prefix="/api/automation", tags=["automation"])


class TriggerBody(BaseModel):
    trigger_type: str
    trigger_data: dict[str, Any] = {}


@router.get("/rules")
def list_rules(current_user: dict = Depends(rbac("automation", "read"))):
    firm_id = current_user.get("firm_id")
    rules = automation_repo.get_rules(firm_id=firm_id)
    return api_response(True, rules)


@router.patch("/rules/{rule_id}/toggle")
def toggle(rule_id: str, enabled: bool = True, current_user: dict = Depends(rbac("automation", "write"))):
    firm_id = current_user.get("firm_id")
    rule = automation_repo.toggle_rule(rule_id, enabled, firm_id=firm_id)
    if rule is None:
        return api_response(False, None, "Rule not found")
    return api_response(True, rule)


@router.get("/executions")
def executions(limit: int = 50, current_user: dict = Depends(rbac("automation", "read"))):
    firm_id = current_user.get("firm_id")
    log = automation_repo.get_executions(firm_id=firm_id, limit=limit)
    return api_response(True, log)


@router.get("/stats")
def stats(current_user: dict = Depends(rbac("automation", "read"))):
    firm_id = current_user.get("firm_id")
    s = automation_repo.get_stats(firm_id=firm_id)
    return api_response(True, s)


@router.post("/trigger")
def manual_trigger(body: TriggerBody, current_user: dict = Depends(rbac("automation", "write"))):
    firm_id = current_user.get("firm_id")
    executed = evaluate_rules(body.trigger_type, body.trigger_data, firm_id=firm_id)
    return api_response(True, {"executions": executed, "count": len(executed)})
