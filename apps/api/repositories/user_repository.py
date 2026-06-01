from typing import Optional
from repositories.base import BaseRepository
from mock_data import MOCK_TEAM_MEMBERS
from core.exceptions import NotFoundError


class UserRepository(BaseRepository[dict]):

    def find_by_id(self, id: str) -> Optional[dict]:
        return next((u for u in MOCK_TEAM_MEMBERS if u["id"] == id), None)

    def find_all(self, firm_id: Optional[str] = None, role: Optional[str] = None, **filters) -> list[dict]:
        users = list(MOCK_TEAM_MEMBERS)
        if role:
            users = [u for u in users if u.get("role") == role]
        return users

    def find_by_email(self, email: str) -> Optional[dict]:
        return next((u for u in MOCK_TEAM_MEMBERS if u["email"] == email), None)

    def get_or_raise(self, id: str) -> dict:
        user = self.find_by_id(id)
        if not user:
            raise NotFoundError("User", id)
        return user

    def create(self, data: dict) -> dict:
        import uuid
        record = {"id": str(uuid.uuid4()), **data, "created_at": self.now_iso()}
        MOCK_TEAM_MEMBERS.append(record)
        return record

    def update(self, id: str, data: dict) -> Optional[dict]:
        user = self.find_by_id(id)
        if not user:
            return None
        user.update({**data, "updated_at": self.now_iso()})
        return user


user_repo = UserRepository()
