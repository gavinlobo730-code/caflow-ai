import os
from typing import Optional
from datetime import date, datetime, timedelta
from repositories.base import BaseRepository

_USE_MOCK = not os.environ.get("SUPABASE_URL")


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class EscalationRuleRepository(BaseRepository[dict]):

    def find_by_id(self, id: str) -> Optional[dict]:
        if _USE_MOCK:
            return None
        result = _get_db().table("escalation_rules").select("*").eq("id", id).maybe_single().execute()
        return result.data

    def find_all(self, firm_id: Optional[str] = None, rule_type: Optional[str] = None, **filters) -> list[dict]:
        if _USE_MOCK:
            return []
        query = _get_db().table("escalation_rules").select("*")
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if rule_type:
            query = query.eq("rule_type", rule_type)
        result = query.eq("is_active", True).execute()
        return result.data or []

    def find_active_by_firm(self, firm_id: str) -> list[dict]:
        """Find all active escalation rules for a firm."""
        if _USE_MOCK:
            return []
        result = (
            _get_db().table("escalation_rules")
            .select("*")
            .eq("firm_id", firm_id)
            .eq("is_active", True)
            .execute()
        )
        return result.data or []

    def get_applicable_escalations(self, firm_id: str, task: dict) -> list[dict]:
        """
        Get escalation rules applicable to a task based on its due date.

        Args:
            firm_id: The firm ID
            task: Task dict with id, due_date, status fields

        Returns:
            List of applicable escalation rules
        """
        if _USE_MOCK:
            return []

        if not task.get("due_date") or task.get("status") == "completed":
            return []

        today = date.today()
        due_date = datetime.fromisoformat(task["due_date"]).date() if isinstance(task["due_date"], str) else task["due_date"]

        all_rules = self.find_active_by_firm(firm_id)
        applicable = []

        for rule in all_rules:
            rule_type = rule.get("rule_type")
            days_threshold = rule.get("days_threshold", 0)

            if rule_type == "due_soon":
                # Task is due in exactly N days
                days_until_due = (due_date - today).days
                if days_until_due == days_threshold:
                    applicable.append(rule)

            elif rule_type in ("overdue", "reassign_overdue", "manager_notify"):
                # Task is overdue by at least N days
                days_overdue = (today - due_date).days
                if days_overdue >= days_threshold:
                    applicable.append(rule)

        return applicable

    def create(self, data: dict) -> dict:
        if _USE_MOCK:
            import uuid
            record = {
                "id": str(uuid.uuid4()),
                **data,
                "created_at": self.now_iso(),
                "updated_at": self.now_iso()
            }
            return record
        result = _get_db().table("escalation_rules").insert({
            **data,
            "created_at": self.now_iso(),
            "updated_at": self.now_iso()
        }).execute()
        return result.data[0] if result.data else None

    def update(self, id: str, data: dict) -> Optional[dict]:
        if _USE_MOCK:
            return None
        result = _get_db().table("escalation_rules").update({
            **data,
            "updated_at": self.now_iso()
        }).eq("id", id).execute()
        return result.data[0] if result.data else None

    def delete(self, id: str) -> bool:
        if _USE_MOCK:
            return True
        _get_db().table("escalation_rules").delete().eq("id", id).execute()
        return True

    def get_or_raise(self, id: str) -> dict:
        from core.exceptions import NotFoundError
        rule = self.find_by_id(id)
        if not rule:
            raise NotFoundError("EscalationRule", id)
        return rule


escalation_rule_repo = EscalationRuleRepository()
