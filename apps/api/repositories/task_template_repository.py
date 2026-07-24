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

    def find_by_id(self, id: str, firm_id: Optional[str] = None) -> Optional[dict]:
        """Fetch a template by id. When firm_id is given, only the caller's own
        templates or shared system templates (firm_id IS NULL) are visible —
        mirrors find_all's scoping so a firm can't read another firm's private
        template by guessing/enumerating its id."""
        query = _get_db().table("task_templates").select("*").eq("id", id)
        if firm_id:
            query = query.or_(f"firm_id.eq.{firm_id},firm_id.is.null")
        result = query.maybe_single().execute()
        return result.data

    def create(self, data: dict) -> dict:
        result = _get_db().table("task_templates").insert({
            **data,
            "created_at": self.now_iso(),
            "updated_at": self.now_iso(),
        }).execute()
        return result.data[0]

    def update(self, id: str, data: dict, firm_id: Optional[str] = None) -> Optional[dict]:
        """Update a template. When firm_id is given, the update is scoped to
        rows owned by that firm (strict — system templates with firm_id IS
        NULL never match .eq(), so no firm can edit a shared system template
        through this path)."""
        query = _get_db().table("task_templates").update({
            **data,
            "updated_at": self.now_iso(),
        }).eq("id", id)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        result = query.execute()
        return result.data[0] if result.data else None

    def delete(self, id: str, firm_id: Optional[str] = None) -> bool:
        """Delete a template. When firm_id is given, the delete is scoped to
        rows owned by that firm (system templates are never deletable through
        this path, matching update's semantics)."""
        query = _get_db().table("task_templates").delete().eq("id", id)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        result = query.execute()
        return len(result.data) > 0


task_template_repo = TaskTemplateRepository()
