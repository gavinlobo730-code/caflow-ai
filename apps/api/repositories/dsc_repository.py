"""
DSC (Digital Signature Certificate) repository.

Mirrors the canonical client_repository pattern: a single interface with a
mock (in-memory) branch for development/tests and a Supabase branch for
production, selected by the presence of SUPABASE_URL.

Soft-delete only — DSC history is preserved, never hard-deleted (see
migration 120). Real DB columns (migration 014): id, firm_id, holder_name,
pan, dsc_type, purpose, issued_date, expiry_date, issued_by, token_no, notes,
created_at, updated_at; plus deleted_at, deleted_by (migration 120).
"""
import os
from typing import Optional
from repositories.base import BaseRepository

_USE_MOCK = not os.environ.get("SUPABASE_URL")

# In-memory store for mock mode. Defined locally (not in mock_data.py) — the
# DSC tracker seeds no fictional holders; the firm's real data only.
_MOCK_DSC: list[dict] = []


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class DSCRepository(BaseRepository[dict]):

    def find_all(self, firm_id: Optional[str] = None) -> list[dict]:
        if _USE_MOCK:
            rows = [
                r for r in _MOCK_DSC
                if not r.get("deleted_at") and (not firm_id or r.get("firm_id") == firm_id)
            ]
            return sorted(rows, key=lambda r: r.get("expiry_date") or "")
        query = _get_db().table("dsc_records").select("*").is_("deleted_at", None)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        result = query.order("expiry_date").execute()
        return result.data or []

    def find_by_id(self, id: str, firm_id: Optional[str] = None) -> Optional[dict]:
        # firm_id is an optional defense-in-depth scope. Callers SHOULD pass it
        # so a single forgotten check cannot leak another firm's record. When
        # omitted, callers MUST themselves enforce firm membership in the router.
        if _USE_MOCK:
            r = next((x for x in _MOCK_DSC if x.get("id") == id), None)
            if not r or r.get("deleted_at"):
                return None
            if firm_id and r.get("firm_id") != firm_id:
                return None
            return r
        query = _get_db().table("dsc_records").select("*").eq("id", id).is_("deleted_at", None)
        if firm_id:
            query = query.eq("firm_id", firm_id)
        result = query.maybe_single().execute()
        return result.data

    def create(self, data: dict) -> dict:
        if _USE_MOCK:
            import uuid
            record = {
                "id": str(uuid.uuid4()),
                **data,
                "created_at": self.now_iso(),
                "updated_at": self.now_iso(),
                "deleted_at": None,
                "deleted_by": None,
            }
            _MOCK_DSC.append(record)
            return record
        result = _get_db().table("dsc_records").insert(
            {**data, "created_at": self.now_iso(), "updated_at": self.now_iso()}
        ).execute()
        return result.data[0]

    def update(self, id: str, data: dict) -> Optional[dict]:
        if _USE_MOCK:
            record = next((x for x in _MOCK_DSC if x.get("id") == id), None)
            if not record or record.get("deleted_at"):
                return None
            record.update({**data, "updated_at": self.now_iso()})
            return record
        result = _get_db().table("dsc_records").update(
            {**data, "updated_at": self.now_iso()}
        ).eq("id", id).execute()
        return result.data[0] if result.data else None

    def soft_delete(self, id: str, deleted_by: Optional[str] = None) -> bool:
        if _USE_MOCK:
            record = next((x for x in _MOCK_DSC if x.get("id") == id), None)
            if not record or record.get("deleted_at"):
                return False
            record["deleted_at"] = self.now_iso()
            record["deleted_by"] = deleted_by
            record["updated_at"] = self.now_iso()
            return True
        result = _get_db().table("dsc_records").update({
            "deleted_at": self.now_iso(),
            "deleted_by": deleted_by,
        }).eq("id", id).execute()
        return bool(result.data)


dsc_repo = DSCRepository()
