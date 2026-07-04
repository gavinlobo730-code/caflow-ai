import os
import uuid
from datetime import date
from typing import Optional
from repositories.base import BaseRepository

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from mock_data import MOCK_COMPLIANCE_RECORDS


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class ComplianceRecordsRepository(BaseRepository[dict]):

    def find_by_id(self, id: str) -> Optional[dict]:
        if _USE_MOCK:
            return next((r for r in MOCK_COMPLIANCE_RECORDS if r["id"] == id), None)
        result = _get_db().table("compliance_records").select("*").eq("id", id).is_("deleted_at", "null").maybe_single().execute()
        return result.data

    def find_all(
        self,
        firm_id: Optional[str] = None,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        compliance_type: Optional[str] = None,
        exclude_statuses: Optional[list[str]] = None,
    ) -> list[dict]:
        if _USE_MOCK:
            records = list(MOCK_COMPLIANCE_RECORDS)
            if firm_id:
                records = [r for r in records if r.get("firm_id") == firm_id]
            if client_id:
                records = [r for r in records if r["client_id"] == client_id]
            if status:
                records = [r for r in records if r["status"] == status]
            if compliance_type:
                records = [r for r in records if r["compliance_type"] == compliance_type]
            if exclude_statuses:
                records = [r for r in records if r.get("status") not in exclude_statuses]
            return records

        query = _get_db().table("compliance_records").select("*").is_("deleted_at", "null")
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if client_id:
            query = query.eq("client_id", client_id)
        if status:
            query = query.eq("status", status)
        if compliance_type:
            query = query.eq("compliance_type", compliance_type)
        if exclude_statuses:
            query = query.not_.in_("status", exclude_statuses)
        result = query.order("due_date").execute()
        return result.data or []

    def count_all(self, firm_id: Optional[str] = None, client_id: Optional[str] = None) -> int:
        """Lightweight row count (no full-row fetch) — for metrics that need a
        total across the firm's entire history without paying to transfer it."""
        if _USE_MOCK:
            return len(self.find_all(firm_id=firm_id, client_id=client_id))
        query = _get_db().table("compliance_records").select("id", count="exact").is_("deleted_at", "null")
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if client_id:
            query = query.eq("client_id", client_id)
        result = query.execute()
        return result.count or 0

    def create(self, data: dict) -> dict:
        if _USE_MOCK:
            record = {"id": str(uuid.uuid4()), **data, "created_at": self.now_iso(), "updated_at": self.now_iso()}
            MOCK_COMPLIANCE_RECORDS.append(record)
            return record
        payload = {k: v for k, v in data.items() if v is not None}
        payload.setdefault("created_at", self.now_iso())
        payload.setdefault("updated_at", self.now_iso())
        result = _get_db().table("compliance_records").insert(payload).execute()
        return result.data[0]

    def update(self, id: str, data: dict) -> Optional[dict]:
        if _USE_MOCK:
            record = self.find_by_id(id)
            if not record:
                return None
            record.update({**data, "updated_at": self.now_iso()})
            return record
        payload = {k: v for k, v in data.items() if v is not None}
        payload["updated_at"] = self.now_iso()
        result = _get_db().table("compliance_records").update(payload).eq("id", id).execute()
        return result.data[0] if result.data else None


compliance_records_repo = ComplianceRecordsRepository()
