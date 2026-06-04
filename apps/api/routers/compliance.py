from fastapi import APIRouter, Depends
from models.common import api_response
from core.permissions import rbac
from mock_data import MOCK_COMPLIANCE_TASKS, MOCK_CLIENTS, CLIENT_INDEX
from services.compliance_engine import (
    gstr1_due_date, gstr3b_due_date, gstr9_due_date,
    itr_due_date, advance_tax_due_dates, enrich_compliance_task
)
from datetime import date

router = APIRouter(prefix="/api/compliance", tags=["compliance"])


@router.get("/tasks")
def list_compliance_tasks(client_id: str | None = None, status: str | None = None, current_user: dict = Depends(rbac("compliance_record", "read"))):
    tasks = MOCK_COMPLIANCE_TASKS
    if client_id:
        tasks = [t for t in tasks if t["client_id"] == client_id]
    if status:
        tasks = [t for t in tasks if t["status"] == status]
    return api_response(True, {"tasks": tasks, "total": len(tasks)})


@router.get("/calendar")
def compliance_calendar(current_user: dict = Depends(rbac("compliance_record", "read"))):
    tasks = sorted(MOCK_COMPLIANCE_TASKS, key=lambda t: t["due_date"])
    client_map = {c["id"]: c["client_name"] for c in MOCK_CLIENTS}
    events = [
        {**t, "client_name": client_map.get(t["client_id"], "Unknown")}
        for t in tasks
    ]
    return api_response(True, {"events": events})


@router.get("/due-dates/calculate")
def calculate_due_dates(year: int, month: int, current_user: dict = Depends(rbac("compliance_record", "read"))):
    """
    Calculate all GST due dates for a given month.
    Ref: CGST Act 2017, Sections 37 and 39.
    """
    today = date.today()
    fy_end = year if month <= 3 else year + 1
    return api_response(True, {
        "period": f"{year}-{month:02d}",
        "gstr1_due_date": gstr1_due_date(year, month).isoformat(),
        "gstr3b_due_date": gstr3b_due_date(year, month).isoformat(),
        "gstr9_due_date": gstr9_due_date(fy_end).isoformat(),
        "itr_due_date": itr_due_date(fy_end).isoformat(),
        "advance_tax_schedule": advance_tax_due_dates(fy_end),
    })
