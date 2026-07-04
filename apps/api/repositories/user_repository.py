import os
from typing import Optional
from repositories.base import BaseRepository
from core.exceptions import NotFoundError

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from mock_data import MOCK_TEAM_MEMBERS


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class UserRepository(BaseRepository[dict]):

    def find_by_id(self, id: str) -> Optional[dict]:
        if _USE_MOCK:
            return next((u for u in MOCK_TEAM_MEMBERS if u["id"] == id), None)
        result = _get_db().table("users").select("*").eq("id", id).is_("deleted_at", None).maybe_single().execute()
        return result.data

    def find_all(self, firm_id: Optional[str] = None, role: Optional[str] = None, **filters) -> list[dict]:
        if _USE_MOCK:
            users = list(MOCK_TEAM_MEMBERS)
            if role:
                users = [u for u in users if u.get("role") == role]
            return users
        query = _get_db().table("users").select("*").is_("deleted_at", None)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if role:
            query = query.eq("role", role)
        result = query.order("full_name").execute()
        return result.data or []

    def find_by_email(self, email: str) -> Optional[dict]:
        if _USE_MOCK:
            return next((u for u in MOCK_TEAM_MEMBERS if u["email"] == email), None)
        result = _get_db().table("users").select("*").eq("email", email).is_("deleted_at", None).maybe_single().execute()
        return result.data

    def find_by_auth_user_id(self, auth_user_id: str) -> Optional[dict]:
        if _USE_MOCK:
            return None
        result = _get_db().table("users").select("*").eq("auth_user_id", auth_user_id).maybe_single().execute()
        return result.data

    def find_by_invite_token(self, token: str) -> Optional[dict]:
        """A row awaiting invite acceptance (F21 fix) — never matches an
        already-linked row, since auth_user_id must still be NULL."""
        if _USE_MOCK:
            return next((u for u in MOCK_TEAM_MEMBERS
                         if u.get("invite_token") == token and not u.get("auth_user_id")), None)
        result = (_get_db().table("users").select("*")
                  .eq("invite_token", token).is_("auth_user_id", None)
                  .maybe_single().execute())
        return result.data

    def get_or_raise(self, id: str) -> dict:
        user = self.find_by_id(id)
        if not user:
            raise NotFoundError("User", id)
        return user

    def create(self, data: dict) -> dict:
        if _USE_MOCK:
            import uuid
            record = {"id": str(uuid.uuid4()), **data, "created_at": self.now_iso()}
            MOCK_TEAM_MEMBERS.append(record)
            return record
        result = _get_db().table("users").insert({**data, "created_at": self.now_iso(), "updated_at": self.now_iso()}).execute()
        return result.data[0]

    def update(self, id: str, data: dict) -> Optional[dict]:
        if _USE_MOCK:
            user = self.find_by_id(id)
            if not user:
                return None
            user.update({**data, "updated_at": self.now_iso()})
            return user
        result = _get_db().table("users").update({**data, "updated_at": self.now_iso()}).eq("id", id).execute()
        return result.data[0] if result.data else None


user_repo = UserRepository()
