import os
import uuid
from typing import Optional
from repositories.base import BaseRepository

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from domain.automation_engine import MOCK_AUTOMATION_RULES, MOCK_AUTOMATION_EXECUTIONS, _rule_index


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class AutomationRepository(BaseRepository[dict]):

    def get_rules(self, firm_id: Optional[str] = None) -> list[dict]:
        if _USE_MOCK:
            return list(MOCK_AUTOMATION_RULES)

        query = _get_db().table("automation_rules").select("*")
        if firm_id:
            query = query.eq("firm_id", firm_id)
        result = query.order("created_at").execute()
        return result.data or []

    def toggle_rule(self, rule_id: str, enabled: bool, firm_id: Optional[str] = None) -> Optional[dict]:
        if _USE_MOCK:
            rule = _rule_index.get(rule_id)
            if rule:
                rule["is_enabled"] = enabled
            return rule

        query = _get_db().table("automation_rules").update({"is_enabled": enabled}).eq("id", rule_id)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        result = query.execute()
        return result.data[0] if result.data else None

    def log_execution(self, execution: dict) -> dict:
        if _USE_MOCK:
            MOCK_AUTOMATION_EXECUTIONS.append(execution)
            return execution

        payload = {k: v for k, v in execution.items() if v is not None and k != "rule_name"}
        result = _get_db().table("automation_executions").insert(payload).execute()
        return result.data[0]

    def get_executions(self, firm_id: Optional[str] = None, limit: int = 50) -> list[dict]:
        if _USE_MOCK:
            sorted_execs = sorted(MOCK_AUTOMATION_EXECUTIONS, key=lambda e: e["executed_at"], reverse=True)
            return sorted_execs[:limit]

        # Join via rule to get firm-scoped executions
        rule_ids_result = _get_db().table("automation_rules").select("id").eq("firm_id", firm_id).execute()
        if not rule_ids_result.data:
            return []
        rule_ids = [r["id"] for r in rule_ids_result.data]
        result = (
            _get_db()
            .table("automation_executions")
            .select("*")
            .in_("rule_id", rule_ids)
            .order("executed_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    def get_stats(self, firm_id: Optional[str] = None) -> dict:
        from datetime import date
        rules = self.get_rules(firm_id=firm_id)
        executions = self.get_executions(firm_id=firm_id, limit=1000)
        today_str = date.today().isoformat()
        active_rules = sum(1 for r in rules if r.get("is_enabled"))
        executions_today = sum(1 for e in executions if e.get("executed_at", "")[:10] == today_str)
        tasks_created = sum(
            1 for e in executions
            if e.get("status") == "success" and isinstance(e.get("result_data"), dict) and "task_id" in e.get("result_data", {})
        )
        notifications_sent = sum(
            1 for e in executions
            if e.get("status") == "success" and isinstance(e.get("result_data"), dict) and "notification_id" in e.get("result_data", {})
        )
        return {
            "rules_active": active_rules,
            "executions_today": executions_today,
            "tasks_created": tasks_created,
            "notifications_sent": notifications_sent,
        }


automation_repo = AutomationRepository()
