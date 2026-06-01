from typing import Optional
from repositories.base import BaseRepository
from mock_data import MOCK_COMPLIANCE_TASKS
from services.compliance_engine import enrich_compliance_task
from core.exceptions import NotFoundError


class ComplianceRepository(BaseRepository[dict]):

    def find_by_id(self, id: str) -> Optional[dict]:
        return next((t for t in MOCK_COMPLIANCE_TASKS if t["id"] == id), None)

    def find_all(
        self,
        firm_id: Optional[str] = None,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        compliance_type: Optional[str] = None,
    ) -> list[dict]:
        tasks = list(MOCK_COMPLIANCE_TASKS)
        if client_id:
            tasks = [t for t in tasks if t["client_id"] == client_id]
        if status:
            tasks = [t for t in tasks if t["status"] == status]
        if compliance_type:
            tasks = [t for t in tasks if t["compliance_type"] == compliance_type]
        return tasks

    def get_or_raise(self, id: str) -> dict:
        record = self.find_by_id(id)
        if not record:
            raise NotFoundError("ComplianceTask", id)
        return record

    def find_overdue(self, firm_id: Optional[str] = None) -> list[dict]:
        return [t for t in self.find_all(firm_id=firm_id) if t["status"] == "overdue"]

    def find_due_within_days(self, days: int, firm_id: Optional[str] = None) -> list[dict]:
        return [
            t for t in self.find_all(firm_id=firm_id)
            if 0 <= t.get("days_remaining", 999) <= days
        ]

    def create(self, data: dict) -> dict:
        import uuid
        record = {
            "id": str(uuid.uuid4()), **data,
            "created_at": self.now_iso(), "updated_at": self.now_iso()
        }
        enriched = enrich_compliance_task(record)
        MOCK_COMPLIANCE_TASKS.append(enriched)
        return enriched

    def update(self, id: str, data: dict) -> Optional[dict]:
        task = self.find_by_id(id)
        if not task:
            return None
        task.update({**data, "updated_at": self.now_iso()})
        return enrich_compliance_task(task)


compliance_repo = ComplianceRepository()
