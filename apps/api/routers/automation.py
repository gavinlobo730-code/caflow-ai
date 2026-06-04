from fastapi import APIRouter, Depends
from pydantic import BaseModel
from core.permissions import rbac
from typing import Any
from models.common import api_response
from domain.automation_engine import (
    get_rules,
    toggle_rule,
    get_execution_log,
    get_automation_stats,
    evaluate_rules,
)

router = APIRouter(prefix="/api/automation", tags=["automation"])


class TriggerBody(BaseModel):
    trigger_type: str
    trigger_data: dict[str, Any] = {}


@router.get("/rules")
def list_rules(current_user: dict = Depends(rbac("automation", "read"))):
    rules = get_rules()
    return api_response(True, rules)


@router.patch("/rules/{rule_id}/toggle")
def toggle(rule_id: str, enabled: bool = True, current_user: dict = Depends(rbac("automation", "write"))):
    rule = toggle_rule(rule_id, enabled)
    if rule is None:
        return api_response(False, None, "Rule not found")
    return api_response(True, rule)


@router.get("/executions")
def executions(limit: int = 50, current_user: dict = Depends(rbac("automation", "read"))):
    log = get_execution_log(limit=limit)
    return api_response(True, log)


@router.get("/stats")
def stats(current_user: dict = Depends(rbac("automation", "read"))):
    s = get_automation_stats()
    return api_response(True, s)


@router.post("/trigger")
def manual_trigger(body: TriggerBody, current_user: dict = Depends(rbac("automation", "write"))):
    executed = evaluate_rules(body.trigger_type, body.trigger_data)
    return api_response(True, {"executions": executed, "count": len(executed)})
