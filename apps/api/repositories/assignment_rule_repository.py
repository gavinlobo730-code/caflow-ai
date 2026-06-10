import os
from typing import Optional
from repositories.base import BaseRepository
from core.exceptions import NotFoundError

_USE_MOCK = not os.environ.get("SUPABASE_URL")


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class AssignmentRuleRepository(BaseRepository[dict]):

    def find_by_id(self, id: str) -> Optional[dict]:
        if _USE_MOCK:
            return None
        result = _get_db().table("assignment_rules").select("*").eq("id", id).maybe_single().execute()
        return result.data

    def find_all(self, firm_id: Optional[str] = None, recurring_config_id: Optional[str] = None, **filters) -> list[dict]:
        if _USE_MOCK:
            return []
        query = _get_db().table("assignment_rules").select("*")
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if recurring_config_id:
            query = query.eq("recurring_config_id", recurring_config_id)
        result = query.order("priority").execute()
        return result.data or []

    def find_by_recurring_config(self, recurring_config_id: str) -> list[dict]:
        """Find all rules for a recurring config, ordered by priority."""
        if _USE_MOCK:
            return []
        result = (
            _get_db().table("assignment_rules")
            .select("*")
            .eq("recurring_config_id", recurring_config_id)
            .eq("is_active", True)
            .order("priority")
            .execute()
        )
        return result.data or []

    def create(self, data: dict) -> dict:
        if _USE_MOCK:
            import uuid
            record = {"id": str(uuid.uuid4()), **data, "created_at": self.now_iso(), "updated_at": self.now_iso()}
            return record
        result = _get_db().table("assignment_rules").insert({
            **data,
            "created_at": self.now_iso(),
            "updated_at": self.now_iso()
        }).execute()
        return result.data[0] if result.data else None

    def update(self, id: str, data: dict) -> Optional[dict]:
        if _USE_MOCK:
            return None
        result = _get_db().table("assignment_rules").update({
            **data,
            "updated_at": self.now_iso()
        }).eq("id", id).execute()
        return result.data[0] if result.data else None

    def delete(self, id: str) -> bool:
        if _USE_MOCK:
            return True
        _get_db().table("assignment_rules").delete().eq("id", id).execute()
        return True

    def delete_by_recurring_config(self, recurring_config_id: str) -> bool:
        """Delete all rules for a recurring config."""
        if _USE_MOCK:
            return True
        _get_db().table("assignment_rules").delete().eq("recurring_config_id", recurring_config_id).execute()
        return True

    def evaluate_rules(self, firm_id: str, recurring_config_id: str, available_users: list[dict]) -> Optional[str]:
        """
        Evaluate assignment rules in priority order and return the assignee_id.

        Args:
            firm_id: The firm ID
            recurring_config_id: The recurring config ID
            available_users: List of user dicts with 'id', 'role', 'team_id' fields

        Returns:
            The assignee_id (user UUID as string) or None if no match found
        """
        if _USE_MOCK:
            return None

        rules = self.find_by_recurring_config(recurring_config_id)

        # Build lookup structures for faster access
        user_by_id = {u["id"]: u for u in available_users}
        users_by_role = {}
        users_by_team = {}

        for user in available_users:
            role = user.get("role")
            if role:
                if role not in users_by_role:
                    users_by_role[role] = []
                users_by_role[role].append(user)

            team_id = user.get("team_id")
            if team_id:
                if team_id not in users_by_team:
                    users_by_team[team_id] = []
                users_by_team[team_id].append(user)

        # Evaluate each rule in priority order
        for rule in rules:
            rule_type = rule.get("rule_type")
            target_value = rule.get("target_value")

            if rule_type == "fixed_user":
                # Return the fixed user if they are in available_users
                if target_value and target_value in user_by_id:
                    return target_value

            elif rule_type == "by_role":
                # Find first user with matching role
                if target_value and target_value in users_by_role:
                    matching_users = users_by_role[target_value]
                    if matching_users:
                        return matching_users[0]["id"]

            elif rule_type == "by_team":
                # Find first user in matching team
                if target_value and target_value in users_by_team:
                    matching_users = users_by_team[target_value]
                    if matching_users:
                        return matching_users[0]["id"]

            elif rule_type == "fallback":
                # Return first available user
                if available_users:
                    return available_users[0]["id"]

        # No matching rule found
        return None

    def get_or_raise(self, id: str) -> dict:
        rule = self.find_by_id(id)
        if not rule:
            raise NotFoundError("AssignmentRule", id)
        return rule


assignment_rule_repo = AssignmentRuleRepository()
