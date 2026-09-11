import os

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from models.common import api_response
from core.permissions import rbac
from core.authz import filter_by_client, assert_client_access
from repositories.compliance_repository import compliance_repo
from services.audit_service import log_event
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
from services.gst_filing_record_service import (
    FILING_TYPE_GSTR1, FILING_TYPE_GSTR3B, record_filing)
from datetime import date
from core.ist_clock import ist_today
from typing import Annotated, Optional
from models.fy import FYLabel, OptionalFYLabel

router = APIRouter(prefix="/api/compliance", tags=["compliance"])

_USE_MOCK = not os.environ.get("SUPABASE_URL")


# ── Recording that something was filed ───────────────────────────────────────
#
# GST-14. The compliance tracker at /gst marked a return filed by writing
# filing_status / filed_date / arn_number straight into compliance_calendar
# over PostgREST — single row and bulk. Three things follow from "straight over
# PostgREST", and each is worse than the last:
#
#   * rbac() never ran, so a Reviewer could mark a client's GSTR-3B filed;
#   * gst_filing_record_service.record_filing never ran, so no row reached
#     public.filings;
#   * public.filings is the ONLY table journal_period_lock_reason (migration
#     266) reads. So a return marked filed from the tracker did NOT lock its
#     period — the books could still move under a return already with the
#     government, which is the entire thing the lock exists to prevent.
#
# Meanwhile the client GST workspace, which records a filing properly, showed
# the same return as a draft. Two screens, one return, opposite answers.
#
# The vocabulary this settles on is public.filings, because that is what the
# lock reads. Both paths write it now.

# compliance_calendar.compliance_type → the filings.filing_type it records
# under. Deliberately NOT every calendar type.
_CALENDAR_TYPE_TO_FILING_TYPE = {
    "GSTR1":  FILING_TYPE_GSTR1,
    "GSTR3B": FILING_TYPE_GSTR3B,
}

# Why a type can be marked filed on the calendar and still lock nothing. Said
# out loud, per type, and returned to the caller: a silent no-op here is the
# same defect in a new place — the CA has to be able to see that the tick did
# not close the period.
_NO_FILING_ROW_REASON = {
    "GSTR9": ("GSTR-9 is the annual return. Furnishing it closes the CORRECTION "
              "WINDOW under §37(3)/§39(9)/§16(4) — see "
              "compliance_engine.correction_window_closes() — which is a "
              "different rule from the period lock. Recording it here would "
              "freeze a whole financial year's books."),
    "ITR":    "An income-tax return is not a GST period; the GST period lock does not apply.",
    "TDS26Q": "A TDS return is not a GST period; the GST period lock does not apply.",
}
_NO_FILING_ROW_DEFAULT = (
    "public.filings records GST returns of supplies (GSTR-1 and GSTR-3B). "
    "This obligation is tracked on the calendar but closes no GST period."
)


class MarkFiledIn(BaseModel):
    filed_date: str
    arn: Optional[str] = None

    @field_validator("filed_date")
    @classmethod
    def a_real_past_date(cls, v: str) -> str:
        """YYYY-MM-DD, and not in the future.

        The shape check keeps a typo out of `filings.filed_date`, which is a
        DATE column — without it a malformed value is a 500 from Postgres
        rather than a 422 the CA can act on. The past check is the same
        reasoning as the value itself: a return cannot have been filed
        tomorrow, and this is the field the audit reads to say when it went.
        IST, because a filing date is an Indian calendar date.
        """
        try:
            when = date.fromisoformat((v or "").strip())
        except ValueError:
            raise ValueError("filed_date must be YYYY-MM-DD")
        if when > ist_today():
            raise ValueError("filed_date cannot be in the future")
        return when.isoformat()


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


@router.get("/tax-audit-due-dates")
def tax_audit_due_dates(
    financial_year: Annotated[FYLabel, Query(
        description="YYYY-YY or YYYY-YYYY, e.g. 2025-26")],
    current_user: dict = Depends(rbac("compliance_record", "read")),
):
    """When the §44AB audit report and the return that follows it are due.

    TWO DATES, AND THEY ARE A MONTH APART. Explanation (ii) to §44AB, as
    substituted by the Finance Act 2020 w.e.f. AY 2020-21, defines the
    "specified date" as the date ONE MONTH PRIOR to the §139(1) due date. So
    the report is due 30 September and the return 31 October, and dating the
    report at the return's date shows every audit client a deadline a month
    late — on the obligation whose lateness carries §271B, 0.5% of turnover
    capped at ₹1,50,000. It is also the wrong sequence: §139(1)'s own date
    assumes the report is already on record.

    THIS EXISTS SO THE BROWSER DOES NOT STATE IT. The Tax Audit Tracker's
    header read "Due: 30 November" as a hardcoded string — wrong by two months
    against the report and by a month against the return, and unfixable by any
    backend change because no backend was involved. CLAUDE.md: statutory rules
    live in apps/api.

    THE PREMISE IS AUDIT. Both dates are computed with is_audit=True, which is
    what puts a client on that page at all — this endpoint answers "for an
    assessee to whom §44AB applies", not "for anyone". Whether it applies is a
    turnover question the app does not hold; GET /api/compliance/itr-due-date
    resolves the return's date for a NAMED client, and says when it cannot.

    Stateless: it names no assessee and reads nothing.
    """
    fy_end = int(financial_year[:4]) + 1
    # Imported here, not at module level, and the comment at the top of this
    # file says why: `itr_due_date` answers "which date is 31 July and which is
    # 31 October", not "which one does THIS assessee have", and calling it with
    # is_audit defaulting to False is what gave every company client 31 July.
    # This caller passes is_audit=True EXPLICITLY and says so in its docstring
    # and in `basis`, which is the one shape that is not that bug.
    from services.compliance_engine import itr_due_date, tax_audit_report_due_date
    return api_response(True, {
        "financial_year": financial_year,
        "report_due_date": tax_audit_report_due_date(fy_end).isoformat(),
        "return_due_date": itr_due_date(fy_end, is_audit=True).isoformat(),
        "basis": ("IT Act §44AB Explanation (ii) — the specified date is one "
                  "month prior to the §139(1) due date. Assumes §44AB applies; "
                  "a §92E transfer-pricing case is not modelled."),
    })


@router.get("/payroll-deposit-due-dates/fy")
def payroll_deposit_due_dates_for_fy(
    financial_year: Annotated[FYLabel, Query(description="e.g. 2026-27")],
    current_user: dict = Depends(rbac("compliance_record", "read")),
):
    """The same answer for all twelve wage months of one financial year.

    The firm-level payroll report is a WHOLE-YEAR statutory calendar, so asking
    the per-month endpoint twelve times would be twelve round trips for
    arithmetic. One call, twelve months, and the four return dates once.

    `financial_year` is an FYLabel, so "2026-28" is refused rather than read as
    2026-27 — see models/fy.py. Written `Annotated[FYLabel, Query(...)]` and not
    `FYLabel = Query(...)`, which validates NOTHING: FastAPI builds the field
    from Query() in the default position and discards the Annotated metadata,
    silently, so the endpoint reads as guarded.
    """
    from services import compliance_engine as ce

    start_year = int(financial_year[:4])
    fy_end = start_year + 1
    months = [(start_year, m) for m in range(4, 13)] + \
             [(fy_end, m) for m in range(1, 4)]
    return api_response(True, {
        "financial_year": financial_year,
        "months": [
            {
                "year": y, "month": m,
                "quarter": ce.tds_quarter_of_month(m),
                "deposits": [
                    {"label": d["label"], "authority": d["authority"],
                     "statute": d["statute"], "due_date": d["due_date"].isoformat()}
                    for d in ce.payroll_deposit_due_dates(y, m)
                ],
            }
            for y, m in months
        ],
        "returns": [
            {"label": f"TDS return {r['quarter']}", "quarter": r["quarter"],
             "authority": "Income Tax Department",
             "statute": "IT Act Rule 31A(2)",
             "due_date": r["due_date"].isoformat()}
            for r in ce.tds_return_due_dates_for_fy(fy_end)
        ],
        "gaps": [
            "Professional tax is not in this calendar. Its due date is fixed by "
            "each state and there is no single rule, so a date shown here would "
            "be wrong for most clients. Check the state's own due date for any "
            "employee whose state levies PT."
        ],
    })


@router.get("/payroll-deposit-due-dates")
def payroll_deposit_due_dates(
    year: int, month: int,
    current_user: dict = Depends(rbac("compliance_record", "read")),
):
    """Every statutory deposit arising from one month's payroll, and the TDS
    return the month falls in.

    WHY THIS ENDPOINT EXISTS (PAY-19). `compliance_engine` has computed these
    since it was written and CLAUDE.md names it "the single source for every
    due date" — but the two payroll calendars in apps/web did not call it or
    anything else. They built their own lists in the browser, and the two
    disagreed with the engine and with each other:

      * both INVENTED a monthly Professional Tax row, dated the last day of the
        month and described as "Maharashtra: Rs 200 if > Rs 10,000", FOR EVERY
        CLIENT. The engine deliberately omits PT — its date is fixed by each
        state, there is no single rule, and this codebase models the slabs for
        four states of twenty-two. A wrong date in a CA's calendar is worse
        than a missing one, which is exactly what payroll_deposit_due_dates'
        own docstring says.
      * both OMITTED the ESI deposit (the 15th, reg. 31) and the monthly salary
        TDS deposit (the 7th, Rule 30(2) — 30 April for March). Those are the
        two that attract interest: s.201(1A)(ii) charges 1.5% a month from the
        date of DEDUCTION, so three weeks late on March costs two months of it.

    NO CLIENT, so no client scoping: this is a calendar calculator for a
    period, the same shape as /due-dates/calculate beside it, and it is listed
    under the same exemption for the same reason.

    PROFESSIONAL TAX IS RETURNED AS A NAMED GAP rather than omitted silently.
    A calendar that simply has no PT row cannot be told apart from one whose
    client has no PT liability, and the CA is the only one who can settle it.
    """
    from services import compliance_engine as ce

    if not 1 <= month <= 12:
        raise HTTPException(status_code=422,
                            detail=f"month must be 1-12 — got {month}.")

    deposits = [
        {"label": d["label"], "authority": d["authority"],
         "statute": d["statute"], "due_date": d["due_date"].isoformat()}
        for d in ce.payroll_deposit_due_dates(year, month)
    ]

    # ALL FOUR QUARTERS OF THE MONTH'S OWN FINANCIAL YEAR, not "the quarter this
    # month is in". That distinction is a defect the browser had: January is Q4,
    # whose return is not due until 31 May, while the Q3 return is due on
    # 31 JANUARY itself — so a CA opening the calendar in January was shown a
    # deadline five months out and not the one falling that week. Returning all
    # four takes the choice away from the caller.
    #
    # Rule 31A(2) sets one date per quarter whatever the form — 24Q, 26Q, 27Q —
    # and Q4 is the exception: 31 May, not the end of the month following
    # quarter end.
    fy_end = year if month <= 3 else year + 1
    return api_response(True, {
        "period": {"year": year, "month": month,
                   "quarter": ce.tds_quarter_of_month(month),
                   "financial_year_end": fy_end},
        "deposits": deposits,
        "returns": [
            {"label": f"TDS return {r['quarter']}", "quarter": r["quarter"],
             "authority": "Income Tax Department",
             "statute": "IT Act Rule 31A(2)",
             "due_date": r["due_date"].isoformat()}
            for r in ce.tds_return_due_dates_for_fy(fy_end)
        ],
        "gaps": [
            "Professional tax is not in this list. Its due date is fixed by "
            "each state and there is no single rule, so a date shown here "
            "would be wrong for most clients. Check the state's own due date "
            "for any employee whose state levies PT."
        ],
    })


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


@router.patch("/calendar/{record_id}/filed")
def mark_calendar_entry_filed(
    record_id: str,
    body: MarkFiledIn,
    current_user: dict = Depends(rbac("compliance_record", "write")),
):
    """Record that a calendar obligation was filed — and, for a GST return,
    close its period.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing here talks to a portal.
    # This records what a human has already filed there, which is exactly the
    # genuine path CLAUDE.md describes: the CA files on gst.gov.in, then tells
    # the software.

    Answers three things the caller must be able to see, because the previous
    implementation answered none of them:

      * `filing_recorded` — whether a public.filings row was written, which is
        the same as whether the period is now locked;
      * `filing_not_recorded_reason` — if not, WHY, per compliance type. A
        GSTR-9 tick is a real thing to record and still locks nothing;
      * `workspace_return` — a prepared GSTR-1/3B for the same client and
        period that is NOT yet submitted in the client workspace. That is the
        disagreement GST-14 is about, and it is surfaced rather than resolved:
        moving a prepared return to "submitted" needs Manager+ and an explicit
        ca_approved on the workspace endpoint (CGST §37), and marking a
        calendar row is not that approval.
    """
    firm_id = current_user.get("firm_id") or ""
    if _USE_MOCK:
        # No compliance_calendar in mock mode — the table is written by the
        # frontend and read here; there is nothing to stand in for.
        raise HTTPException(status_code=503,
                            detail="Recording a filing needs the database.")

    from core.supabase_client import get_supabase
    db = get_supabase()

    rows = (db.table("compliance_calendar")
            .select("id, firm_id, client_id, compliance_type, period_start, "
                    "period_end, due_date, filing_status, filed_date, arn_number")
            .eq("id", record_id).eq("firm_id", firm_id).limit(1).execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Compliance entry not found")
    row = rows[0]
    # The caller may only touch a client they are assigned to (M2). Reading the
    # row firm-scoped is not enough: firm_id alone let one staff member mark
    # another's client filed.
    assert_client_access(current_user, row.get("client_id"))

    ctype = str(row.get("compliance_type") or "")
    arn = (body.arn or "").strip() or None
    # The payload is written INLINE rather than built into a variable, because
    # test_backend_columns_exist_pg.py can only read the column names out of a
    # literal dict — an .update(variable) is counted as an unreadable reference
    # and its columns stop being checked against the real schema.
    updated = (db.table("compliance_calendar").update({
        "filing_status": "filed",
        "filed_date": body.filed_date,
        "arn_number": arn,
    }).eq("id", record_id).eq("firm_id", firm_id).execute().data or [])
    record = updated[0] if updated else {
        **row, "filing_status": "filed",
        "filed_date": body.filed_date, "arn_number": arn}

    filing_type = _CALENDAR_TYPE_TO_FILING_TYPE.get(ctype)
    start = str(row.get("period_start") or "")[:10]
    end = str(row.get("period_end") or "")[:10]
    filing_row = None
    # Both bounds, or no filings row. compliance_calendar has them NOT NULL, so
    # this cannot happen against the real schema — but record_filing would
    # otherwise fall back to period_bounds("") and raise ValueError, turning a
    # malformed row into a 500 instead of a recorded tick with a stated reason.
    if filing_type and len(start) == 10 and len(end) == 10:
        # The calendar's OWN bounds, not a month derived from them: a QRMP
        # client's GSTR-1 obligation covers a quarter, and locking only its
        # first month would leave two filed months editable.
        filing_row = record_filing(
            db, firm_id=firm_id, client_id=row.get("client_id") or "",
            filing_type=filing_type, period=f"{start[5:7]}{start[0:4]}",
            filed_date=body.filed_date, arn=arn, bounds=(start, end),
        )

    log_event(firm_id, "compliance_calendar", record_id, "mark_filed",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"),
              new_data={"compliance_type": ctype, "filed_date": body.filed_date,
                        "arn": arn, "period_locked": bool(filing_row)})

    return api_response(True, {
        "record": record,
        "filing_recorded": bool(filing_row),
        "filing_not_recorded_reason": (
            None if filing_row
            else _NO_FILING_ROW_REASON.get(ctype, _NO_FILING_ROW_DEFAULT)
        ),
        "period_locked_from": (filing_row or {}).get("period_start"),
        "period_locked_to": (filing_row or {}).get("period_end"),
        "workspace_return": _unsubmitted_workspace_return(
            db, firm_id, row.get("client_id") or "", ctype, start),
    })


def _unsubmitted_workspace_return(db, firm_id: str, client_id: str,
                                  compliance_type: str, period_start: str):
    """A prepared GSTR-1/3B for the same client and month that is still not
    submitted in the client workspace.

    Reported, never changed. The tracker saying "filed" and the workspace
    saying "draft" is the contradiction GST-14 names; the honest resolution is
    to show the CA that the prepared return still needs approving there, not to
    approve it from here — the workspace endpoint requires Manager+ and an
    explicit ca_approved for exactly that transition (CGST §37).
    """
    if not (client_id and len(period_start) == 10):
        return None
    period = f"{period_start[5:7]}{period_start[0:4]}"
    # The two tables are named as LITERALS, in two branches, rather than looked
    # up into db.table(variable). A dynamic table name is invisible to
    # test_backend_columns_exist_pg.py — it counts it as an unreadable
    # reference and stops checking the columns entirely — and this query names
    # four of them. Two branches cost three lines and keep them checkable.
    try:
        if compliance_type == "GSTR1":
            table = "gstr1_returns"
            found = (db.table("gstr1_returns").select("id, period, status")
                     .eq("firm_id", firm_id).eq("client_id", client_id)
                     .eq("period", period).limit(1).execute().data) or []
        elif compliance_type == "GSTR3B":
            table = "gstr3b_returns"
            found = (db.table("gstr3b_returns").select("id, period, status")
                     .eq("firm_id", firm_id).eq("client_id", client_id)
                     .eq("period", period).limit(1).execute().data) or []
        else:
            return None
    except Exception:                                            # noqa: BLE001
        return None
    if not found or found[0].get("status") == "submitted":
        return None
    return {"id": found[0].get("id"), "period": period,
            "status": found[0].get("status"), "table": table}
