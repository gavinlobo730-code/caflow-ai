"""Compliance business logic."""
from typing import Optional
from repositories.compliance_repository import compliance_repo
from repositories.client_repository import client_repo
from core.permissions import require_permission
from services.compliance_engine import (
    gstr1_due_date, gstr3b_due_date, gstr9_due_date,
    itr_due_date, advance_tax_due_dates, enrich_compliance_task
)


class ComplianceService:

    def get_calendar(self, firm_id: Optional[str] = None) -> list[dict]:
        require_permission("Partner", "compliance_record", "read")
        tasks = compliance_repo.find_all(firm_id=firm_id)
        client_map = {c["id"]: c["client_name"] for c in client_repo.find_all(firm_id=firm_id)}
        return sorted(
            [{**t, "client_name": client_map.get(t["client_id"], "Unknown")} for t in tasks],
            key=lambda t: t["due_date"]
        )

    def calculate_due_dates(self, year: int, month: int) -> dict:
        fy_end = year if month <= 3 else year + 1
        return {
            "period": f"{year}-{month:02d}",
            "gstr1_due_date": gstr1_due_date(year, month).isoformat(),
            "gstr3b_due_date": gstr3b_due_date(year, month).isoformat(),
            "gstr9_due_date": gstr9_due_date(fy_end).isoformat(),
            "itr_due_date": itr_due_date(fy_end).isoformat(),
            "advance_tax_schedule": advance_tax_due_dates(fy_end),
        }

    def get_overdue_summary(self, firm_id: Optional[str] = None) -> dict:
        overdue = compliance_repo.find_overdue(firm_id=firm_id)
        due_soon = compliance_repo.find_due_within_days(7, firm_id=firm_id)
        return {
            "overdue_count": len(overdue),
            "due_within_7_days": len(due_soon),
            "overdue_by_type": _count_by_key(overdue, "compliance_type"),
        }


def _count_by_key(items: list[dict], key: str) -> dict:
    counts: dict[str, int] = {}
    for item in items:
        k = item.get(key, "unknown")
        counts[k] = counts.get(k, 0) + 1
    return counts


compliance_service = ComplianceService()
