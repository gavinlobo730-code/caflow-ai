import os
from typing import Optional
from repositories.base import BaseRepository
from services.compliance_engine import enrich_compliance_task
from core.exceptions import NotFoundError

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from mock_data import MOCK_COMPLIANCE_TASKS


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class ComplianceRepository(BaseRepository[dict]):

    def find_by_id(self, id: str) -> Optional[dict]:
        if _USE_MOCK:
            return next((t for t in MOCK_COMPLIANCE_TASKS if t["id"] == id), None)
        result = _get_db().table("compliance_tasks").select("*").eq("id", id).maybe_single().execute()
        return result.data

    def find_all(
        self,
        firm_id: Optional[str] = None,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        compliance_type: Optional[str] = None,
    ) -> list[dict]:
        if _USE_MOCK:
            tasks = list(MOCK_COMPLIANCE_TASKS)
            if client_id:
                tasks = [t for t in tasks if t["client_id"] == client_id]
            if status:
                tasks = [t for t in tasks if t["status"] == status]
            if compliance_type:
                tasks = [t for t in tasks if t["compliance_type"] == compliance_type]
            return tasks

        query = _get_db().table("compliance_tasks").select("*")
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if client_id:
            query = query.eq("client_id", client_id)
        if status:
            query = query.eq("status", status)
        if compliance_type:
            query = query.eq("compliance_type", compliance_type)
        result = query.order("due_date").execute()
        return result.data or []

    def get_or_raise(self, id: str) -> dict:
        record = self.find_by_id(id)
        if not record:
            raise NotFoundError("ComplianceTask", id)
        return record

    def find_overdue(self, firm_id: Optional[str] = None) -> list[dict]:
        return [t for t in self.find_all(firm_id=firm_id) if t.get("status") == "overdue"]

    def find_due_within_days(self, days: int, firm_id: Optional[str] = None) -> list[dict]:
        return [
            t for t in self.find_all(firm_id=firm_id)
            if 0 <= t.get("days_remaining", 999) <= days
        ]

    def create(self, data: dict) -> dict:
        if _USE_MOCK:
            import uuid
            record = {"id": str(uuid.uuid4()), **data, "created_at": self.now_iso(), "updated_at": self.now_iso()}
            enriched = enrich_compliance_task(record)
            MOCK_COMPLIANCE_TASKS.append(enriched)
            return enriched
        result = _get_db().table("compliance_tasks").insert({**data, "created_at": self.now_iso(), "updated_at": self.now_iso()}).execute()
        return result.data[0]

    def update(self, id: str, data: dict) -> Optional[dict]:
        if _USE_MOCK:
            task = self.find_by_id(id)
            if not task:
                return None
            task.update({**data, "updated_at": self.now_iso()})
            return enrich_compliance_task(task)
        result = _get_db().table("compliance_tasks").update({**data, "updated_at": self.now_iso()}).eq("id", id).execute()
        return result.data[0] if result.data else None


compliance_repo = ComplianceRepository()
