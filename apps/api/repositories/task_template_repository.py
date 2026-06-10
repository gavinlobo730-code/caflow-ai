from typing import Optional
from repositories.base import BaseRepository


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class TaskTemplateRepository(BaseRepository[dict]):

    def find_all(self, firm_id: Optional[str] = None) -> list[dict]:
        query = _get_db().table("task_templates").select("*")
        # Return system templates (firm_id IS NULL) plus firm-specific ones
        if firm_id:
            result = query.or_(f"firm_id.eq.{firm_id},firm_id.is.null").order("name").execute()
        else:
            result = query.is_("firm_id", None).order("name").execute()
        return result.data or []

    def find_by_id(self, id: str) -> Optional[dict]:
        result = _get_db().table("task_templates").select("*").eq("id", id).maybe_single().execute()
        return result.data

    def create(self, data: dict) -> dict:
        result = _get_db().table("task_templates").insert({
            **data,
            "created_at": self.now_iso(),
            "updated_at": self.now_iso(),
        }).execute()
        return result.data[0]

    def update(self, id: str, data: dict) -> Optional[dict]:
        result = _get_db().table("task_templates").update({
            **data,
            "updated_at": self.now_iso(),
        }).eq("id", id).execute()
        return result.data[0] if result.data else None

    def delete(self, id: str) -> bool:
        result = _get_db().table("task_templates").delete().eq("id", id).execute()
        return len(result.data) > 0


task_template_repo = TaskTemplateRepository()
