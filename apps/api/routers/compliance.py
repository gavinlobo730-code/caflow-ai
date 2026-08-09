from fastapi import APIRouter, Depends, HTTPException
from models.common import api_response
from core.permissions import rbac
from core.authz import filter_by_client, assert_client_access
from repositories.compliance_repository import compliance_repo
from repositories.client_repository import client_repo
from services.compliance_engine import (
    gstr1_due_date, gstr3b_due_date, gstr9_due_date,
    itr_due_date, advance_tax_due_dates, enrich_compliance_task
)
from datetime import date

router = APIRouter(prefix="/api/compliance", tags=["compliance"])


@router.get("/tasks")
def list_compliance_tasks(
    client_id: str | None = None,
    status: str | None = None,
    current_user: dict = Depends(rbac("compliance_record", "read")),
):
    firm_id = current_user.get("firm_id")
    tasks = compliance_repo.find_all(firm_id=firm_id, client_id=client_id, status=status)
    tasks = filter_by_client(current_user, tasks)  # M2/M5: assignment scope
    return api_response(True, {"tasks": tasks, "total": len(tasks)})


@router.get("/calendar")
def compliance_calendar(current_user: dict = Depends(rbac("compliance_record", "read"))):
    firm_id = current_user.get("firm_id")
    tasks = compliance_repo.find_all(firm_id=firm_id)
    tasks = filter_by_client(current_user, tasks)  # M2/M5: assignment scope
    tasks = sorted(tasks, key=lambda t: t.get("due_date", ""))

    # Enrich with client_name from the client repo
    clients = client_repo.find_all(firm_id=firm_id)
    client_map = {c["id"]: c["client_name"] for c in clients}
    events = [{**t, "client_name": client_map.get(t.get("client_id", ""), "Unknown")} for t in tasks]
    return api_response(True, {"events": events})


@router.post("/seed")
def seed_compliance_calendar(
    client_id: str,
    financial_year: str | None = None,
    current_user: dict = Depends(rbac("compliance_record", "write")),
):
    """
    Generate standard GST/ITR/TDS compliance tasks for a client for the given financial year.
    Ref: CGST Act 2017 Sections 37, 39, 44; IT Act 1961 Section 139.
    """
    firm_id = current_user.get("firm_id")

    # Sweep finding: this checked only client.firm_id == firm_id (a bespoke
    # inline firm-boundary check, the tally_migration.py-shaped gap) and
    # never the caller's assignment — an Executive/Manager could seed ~30
    # compliance task rows into any other staff member's assigned client
    # just by supplying its id. assert_client_access subsumes the firm-
    # boundary check (client_repo.find_by_id is looked up inside it too).
    assert_client_access(current_user, client_id)

    today = date.today()
    # Financial year is the April-start year; default to current FY
    # Accepts: int 2025, str "2025", or str "2025-26" (frontend format)
    fy_int: int
    if financial_year is None:
        fy_int = today.year if today.month >= 4 else today.year - 1
    elif isinstance(financial_year, str) and "-" in financial_year:
        # "2025-26" → extract start year
        try:
            fy_int = int(financial_year.split("-")[0])
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid financial_year format. Use 2025 or '2025-26'.")
    else:
        try:
            fy_int = int(financial_year)
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="Invalid financial_year. Use 2025 or '2025-26'.")
    financial_year = fy_int

    fy_end = financial_year + 1  # calendar year when March 31 falls

    tasks_to_seed = []

    # Monthly GSTR-1 and GSTR-3B for each month of the financial year (Apr–Mar)
    for month_offset in range(12):
        period_month = ((3 + month_offset) % 12) + 1  # Apr=4 .. Mar=3
        period_year = financial_year if period_month >= 4 else fy_end

        period_start = date(period_year, period_month, 1)
        import calendar as _cal
        last_day = _cal.monthrange(period_year, period_month)[1]
        period_end = date(period_year, period_month, last_day)

        tasks_to_seed += [
            {
                "client_id": client_id,
                "firm_id": firm_id,
                "compliance_type": "GSTR1",
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "due_date": gstr1_due_date(period_year, period_month).isoformat(),
                "status": "pending",
            },
            {
                "client_id": client_id,
                "firm_id": firm_id,
                "compliance_type": "GSTR3B",
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "due_date": gstr3b_due_date(period_year, period_month).isoformat(),
                "status": "pending",
            },
        ]

    # Annual returns
    tasks_to_seed += [
        {
            "client_id": client_id,
            "firm_id": firm_id,
            "compliance_type": "GSTR9",
            "period_start": date(financial_year, 4, 1).isoformat(),
            "period_end": date(fy_end, 3, 31).isoformat(),
            "due_date": gstr9_due_date(fy_end).isoformat(),
            "status": "pending",
        },
        {
            "client_id": client_id,
            "firm_id": firm_id,
            "compliance_type": "ITR",
            "period_start": date(financial_year, 4, 1).isoformat(),
            "period_end": date(fy_end, 3, 31).isoformat(),
            "due_date": itr_due_date(fy_end).isoformat(),
            "status": "pending",
        },
    ]

    # TDS quarterly returns
    tds_quarters = [
        ("Q1", date(financial_year, 4, 1),  date(financial_year, 6, 30)),
        ("Q2", date(financial_year, 7, 1),  date(financial_year, 9, 30)),
        ("Q3", date(financial_year, 10, 1), date(financial_year, 12, 31)),
        ("Q4", date(fy_end, 1, 1),          date(fy_end, 3, 31)),
    ]
    from services.compliance_engine import tds_return_due_date
    for quarter, p_start, p_end in tds_quarters:
        tasks_to_seed.append({
            "client_id": client_id,
            "firm_id": firm_id,
            "compliance_type": "TDS26Q",
            "period_start": p_start.isoformat(),
            "period_end": p_end.isoformat(),
            "due_date": tds_return_due_date(quarter, fy_end).isoformat(),
            "status": "pending",
        })

    seeded = []
    for task_data in tasks_to_seed:
        enriched = enrich_compliance_task(dict(task_data))
        record = compliance_repo.create(enriched)
        seeded.append(record)

    return api_response(True, {"seeded": len(seeded), "tasks": seeded})


@router.get("/due-dates/calculate")
def calculate_due_dates(year: int, month: int, current_user: dict = Depends(rbac("compliance_record", "read"))):
    """
    Calculate all GST due dates for a given month.
    Ref: CGST Act 2017, Sections 37 and 39.
    """
    fy_end = year if month <= 3 else year + 1
    return api_response(True, {
        "period": f"{year}-{month:02d}",
        "gstr1_due_date": gstr1_due_date(year, month).isoformat(),
        "gstr3b_due_date": gstr3b_due_date(year, month).isoformat(),
        "gstr9_due_date": gstr9_due_date(fy_end).isoformat(),
        "itr_due_date": itr_due_date(fy_end).isoformat(),
        "advance_tax_schedule": advance_tax_due_dates(fy_end),
    })
