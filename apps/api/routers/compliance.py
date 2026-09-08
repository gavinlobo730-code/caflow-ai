from fastapi import APIRouter, Depends, HTTPException, Query
from models.common import api_response
from core.permissions import rbac
from core.authz import filter_by_client, assert_client_access
from repositories.compliance_repository import compliance_repo
from repositories.client_repository import client_repo
# itr_due_date is deliberately NOT imported here any more. It answers "which
# date is 31 July and which is 31 October"; it does not answer "which one does
# THIS assessee have", and calling it with is_audit defaulting to False is what
# gave every company client 31 July. Explanation 2 to §139(1) is applied by
# services.compliance_obligation_service.itr_due_date_for_client, which is the
# only thing that reads a client's facts before choosing a branch.
from services.compliance_engine import (
    gstr1_due_date, gstr3b_due_date, gstr9_due_date,
    gst_state_category, MONTHLY, QUARTERLY,
    advance_tax_due_dates, enrich_compliance_task
)
from datetime import date
from typing import Annotated, Optional
from models.fy import FYLabel, OptionalFYLabel

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
    financial_year: OptionalFYLabel = None,
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

    # The client's own GST regime. clients.gst_filing_frequency has existed
    # since migration 001 and is settable on the client form, but nothing read
    # it — every client was seeded the monthly 11th/20th, including QRMP
    # filers, whose GSTR-1 is due the 13th of the month after the QUARTER and
    # whose GSTR-3B is the 22nd or 24th by state. Under §47 a wrong due date
    # costs Rs 50 a day.
    from services.compliance_obligation_service import (
        gst_profile_for, itr_profile_for, itr_due_date_for_client)
    gst_freq, gst_state = gst_profile_for(client_id, firm_id)

    # And the client's own ITR position. Explanation 2 to §139(1) gives a
    # COMPANY 31 October whatever its turnover, and this endpoint used to call
    # itr_due_date(fy_end) with is_audit defaulting to False — so every company
    # client was seeded 31 July, three months early on the calendar and wrong
    # on the row. itr_due_date_for_client decides what the facts held settle
    # and says so when they settle nothing; see its docstring for what §44AB
    # needs that no client row holds.
    itr_entity_type, itr_tax_audit = itr_profile_for(client_id, firm_id)

    tasks_to_seed = []

    # GSTR-1 and GSTR-3B for each month of the financial year (Apr-Mar).
    # NOTE: a QRMP client owes four of each, not twelve, plus eight PMT-06
    # challans. This endpoint is the LEGACY per-month seeder;
    # compliance_obligation_service._gst_obligations is the generator that
    # models the quarterly set properly and is what new work should use. The
    # due dates below are at least correct for the client's regime now —
    # twelve rows carrying the right quarterly date rather than the wrong
    # monthly one — but the row COUNT is still monthly-shaped here.
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
                "due_date": gstr1_due_date(period_year, period_month, gst_freq).isoformat(),
                "status": "pending",
            },
            {
                "client_id": client_id,
                "firm_id": firm_id,
                "compliance_type": "GSTR3B",
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "due_date": gstr3b_due_date(period_year, period_month, gst_freq, gst_state).isoformat(),
                "status": "pending",
            },
        ]

    # Annual returns
    itr_resolved = itr_due_date_for_client(
        f"{financial_year}-{str(fy_end)[-2:]}", itr_entity_type, itr_tax_audit)
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
            "due_date": itr_resolved["due_date"],
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

    out = {"seeded": len(seeded), "tasks": seeded,
           "itr_due_date_basis": itr_resolved["basis"]}
    # An ASSUMED ITR date is reported, never silently seeded. A wrong late date
    # costs §234A interest, a §234F fee and the §80 carry-forward; a wrong early
    # one costs an early chase. The row carries the early one and the CA is told
    # which question is open.
    if itr_resolved["statutory_gaps"]:
        out["statutory_gaps"] = itr_resolved["statutory_gaps"]
    return api_response(True, out)


@router.get("/itr-due-date")
def itr_due_date_for_one_client(
    client_id: str,
    financial_year: Annotated[FYLabel, Query(...)],
    current_user: dict = Depends(rbac("compliance_record", "read")),
):
    """The ITR due date for one client and one financial year, with the clause
    it rests on and any question the facts held do not settle.

    Ref: IT Act 1961 §139(1), Explanation 2 — 31 October for a company or for
    an assessee whose accounts are required to be audited, 30 November where a
    §92E report is required, 31 July otherwise.

    THIS EXISTS SO THE BROWSER DOES NOT DECIDE IT. apps/web/app/income-tax
    carried its own table of entity types "that require audit" and matched it
    against `entity_type.toLowerCase()`, which never equals the title-case
    values migration 001's CHECK constraint allows — so 'Private Limited' and
    'Public Limited', the only two multi-word values and the only two that ARE
    companies, both fell through to 31 July. CLAUDE.md: statutory rules live in
    apps/api. The page now reads this.

    `decided` is the honest half of the answer: false means `due_date` is the
    EARLIER of the two dates and `statutory_gaps` names what would settle it.
    """
    assert_client_access(current_user, client_id)
    from services.compliance_obligation_service import (
        itr_profile_for, itr_due_date_for_client)
    entity_type, tax_audit = itr_profile_for(client_id, current_user.get("firm_id"))
    resolved = itr_due_date_for_client(financial_year, entity_type, tax_audit)
    return api_response(True, {**resolved, "client_id": client_id,
                               "entity_type": entity_type})


@router.get("/due-dates/calculate")
def calculate_due_dates(year: int, month: int,
                        frequency: str = MONTHLY,
                        state_code: Optional[str] = None,
                        current_user: dict = Depends(rbac("compliance_record", "read"))):
    """
    Calculate all GST due dates for a given month.
    Ref: CGST Act 2017, Sections 37 and 39; Rule 61A for QRMP.

    `frequency` is monthly or quarterly (QRMP). A quarterly GSTR-3B falls on the
    22nd or the 24th depending on the state of registration, so `state_code` is
    what decides it; `gstr3b_state_category` in the response is null when the
    state is unknown, which means the date returned is the earlier of the two
    and should be presented as assumed rather than known.

    `itr_due_date` had the same shape of problem and no such warning: it was
    itr_due_date(fy_end) with is_audit defaulting to False, so it stated
    31 July as fact. This endpoint NAMES NO ASSESSEE — it is a calendar
    calculator for a period, and that is why it is exempt from client scoping
    (tests/test_router_client_scope.py) — so it cannot resolve Explanation 2 at
    all. It now says so: `itr_due_date_decided` is false and the gap points at
    GET /api/compliance/itr-due-date, which takes a client and answers
    properly. Giving THIS handler a client parameter instead would have made an
    endpoint that deliberately has no assessee acquire one — and would have
    broken the exemption it is listed under.
    """
    fy_end = year if month <= 3 else year + 1
    freq = QUARTERLY if str(frequency).lower() == QUARTERLY else MONTHLY

    from services.compliance_obligation_service import itr_due_date_for_client
    itr = itr_due_date_for_client(f"{fy_end - 1}-{str(fy_end)[-2:]}")

    return api_response(True, {
        "period": f"{year}-{month:02d}",
        "frequency": freq,
        "gstr1_due_date": gstr1_due_date(year, month, freq).isoformat(),
        "gstr3b_due_date": gstr3b_due_date(year, month, freq, state_code).isoformat(),
        "gstr3b_state_category": gst_state_category(state_code) if freq == QUARTERLY else None,
        "gstr9_due_date": gstr9_due_date(fy_end).isoformat(),
        "itr_due_date": itr["due_date"],
        "itr_due_date_decided": itr["decided"],
        "itr_due_date_basis": itr["basis"],
        "itr_statutory_gaps": [
            "This endpoint names no assessee, so IT Act §139(1) Explanation 2 "
            "cannot be applied: 31 October is the due date for a company and "
            "for anyone whose accounts are required to be audited, 30 November "
            "where a §92E report is required. The date above is the "
            "Explanation 2(c) date. GET /api/compliance/itr-due-date resolves "
            "it for a named client and financial year."
        ],
        "advance_tax_schedule": advance_tax_due_dates(fy_end),
    })
