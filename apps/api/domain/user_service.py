"""User/team business logic."""
from typing import Optional
from repositories.user_repository import user_repo
from repositories.task_repository import task_repo
from core.permissions import require_permission, get_accessible_resources


class UserService:

    def get_team_with_workload(self, firm_id: Optional[str] = None, actor_role: str = "Partner") -> list[dict]:
        require_permission(actor_role, "team", "read")
        from services.task_service import compute_team_workload
        from mock_data import MOCK_TASKS
        members = user_repo.find_all(firm_id=firm_id)
        return compute_team_workload(MOCK_TASKS, members)

    def get_permissions(self, user_id: str, actor_role: str = "Partner") -> dict:
        user = user_repo.get_or_raise(user_id)
        return {
            "user": user,
            "permissions": get_accessible_resources(user.get("role", "Executive")),
        }


user_service = UserService()
