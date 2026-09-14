"""Reading a client's year for the statutory bonus register (PAY-23).

This module FETCHES; `domain/payroll/bonus_register.py` and
`domain/payroll/bonus.py` DECIDE. Nothing here applies a section.

WHAT IT HAS TO GO AND GET, AND WHY EACH SOURCE

  §2(21) SALARY is basic plus dearness allowance and nothing else — no HRA, no
  overtime, no other allowance. `payroll_employees` holds `basic_paise` and
  `da_percent`, which is exactly that pair; the slip's `gross_paise` is NOT it
  and using it would inflate every bonus.

  MONTHS WORKED are months with a RELEASED payroll run — `finalized` or `paid`.
  A DRAFT run has paid nobody (PAY-04's reasoning: reading one credits an
  employee with something that never happened), and here it would put a month
  of salary into a statutory debt on the strength of a run the CA has not
  approved.

  WORKING DAYS come from `attendance.days_present` over the accounting year's
  twelve months. §8 counts days actually WORKED, so `days_present` is the
  column and `working_days` (the establishment's days in the month) is not.
  Where no attendance row exists for the year the answer is None — the domain
  module decides what an unknown count means, and it deliberately does not read
  it as nil.
"""
from __future__ import annotations

from typing import Optional

from core.db_paging import fetch_all
from core.ist_clock import fy_bounds
from domain.payroll import bonus_register

#: `payroll_runs.status` values that mean somebody was actually paid. The same
#: pair `routers/payroll.py::_PAYROLL_RELEASED` uses and migration 323 made RLS
#: agree with — named here rather than imported, because importing a router
#: from a service is the wrong direction and one refactor from a cycle.
RELEASED_RUN_STATUSES = ("finalized", "paid")


def _fy_months(accounting_year: str) -> list:
    """The twelve (year, month) pairs of the accounting year.

    `fy_bounds` answers ISO STRINGS, not dates — taken as they come rather than
    parsed, because the two things wanted from them here are a (year, month)
    pair and a `YYYY-MM` prefix, and both are already in the string.
    """
    start, end = (str(x)[:7] for x in fy_bounds(accounting_year))
    out = []
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    while (y, m) <= (ey, em):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _percent_of(base_paise: int, percent) -> int:
    try:
        return int(base_paise) * int(float(percent or 0) * 100) // 10000
    except (TypeError, ValueError):
        return 0


def read_register(db, *, firm_id: str, client_id: str,
                  accounting_year: str) -> dict:
    """The register for one client's accounting year, plus its declaration."""
    declaration = _declaration(db, firm_id=firm_id, client_id=client_id,
                              accounting_year=accounting_year)

    employees = fetch_all(
        lambda: db.table("payroll_employees")
        .select("id, name, basic_paise, da_percent, is_active")
        .eq("firm_id", firm_id).eq("client_id", client_id),
        key="id", label="bonus.employees")

    months = _months_worked(db, firm_id=firm_id, client_id=client_id,
                            accounting_year=accounting_year)
    days = _working_days(db, firm_id=firm_id, accounting_year=accounting_year,
                         employee_ids={str(e["id"]) for e in employees})
    disqualified = _disqualifications(db, firm_id=firm_id, client_id=client_id,
                                     accounting_year=accounting_year)

    rows = []
    for e in employees:
        eid = str(e.get("id"))
        basic = int(e.get("basic_paise") or 0)
        rows.append({
            "employee_id": eid,
            "name": e.get("name"),
            # §2(21) — basic plus DA. Nothing else.
            "monthly_salary_paise": basic + _percent_of(basic, e.get("da_percent")),
            "months_worked": months.get(eid, 0),
            "working_days": days.get(eid),
            "disqualified_ground": disqualified.get(eid),
        })

    register = bonus_register.build(
        accounting_year=accounting_year,
        employees=rows,
        rate_bps=(declaration or {}).get("rate_bps"),
        minimum_wage_monthly_paise=(declaration or {}).get("minimum_wage_monthly_paise"),
        scheduled_employment=(declaration or {}).get("scheduled_employment"),
    )
    out = register.as_dict()
    out["declaration"] = declaration
    out["section_9_grounds"] = [
        {"value": k, "label": v} for k, v in bonus_register.SECTION_9_GROUNDS.items()
    ]
    if not employees:
        out["gaps"].append(
            "No employees are on this client's payroll master, so there is "
            "nothing to compute. The Act reaches an establishment employing "
            "twenty or more persons (§1(3)); whether this client is one is not "
            "decided here.")
    return out


def _declaration(db, *, firm_id: str, client_id: str,
                 accounting_year: str) -> Optional[dict]:
    rows = (
        db.table("bonus_declarations")
        .select("id, accounting_year, rate_bps, allocable_surplus_paise, "
                "minimum_wage_monthly_paise, scheduled_employment, notes")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("accounting_year", accounting_year).limit(1).execute().data
    ) or []
    return rows[0] if rows else None


def _months_worked(db, *, firm_id: str, client_id: str,
                   accounting_year: str) -> dict:
    """Months with a RELEASED run carrying this employee's slip.

    Two reads, not one per employee: the year's released runs, then their slips
    by run id. `payroll_slips` has no `firm_id` — it is scoped through its run,
    which is what the parent read carries.
    """
    # `payroll_runs.month` is TEXT in `YYYY-MM`, which sorts lexically the way
    # it sorts chronologically — so a range filter is exact here, unlike the
    # MMYYYY periods `gstr9_service` has to name one by one.
    first, last = (str(x)[:7] for x in fy_bounds(accounting_year))
    runs = fetch_all(
        lambda: db.table("payroll_runs").select("id, month, status")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .in_("status", list(RELEASED_RUN_STATUSES))
        .gte("month", first).lte("month", last),
        key="id", label="bonus.runs")
    run_ids = [str(r["id"]) for r in runs]
    if not run_ids:
        return {}
    slips = fetch_all(
        lambda: db.table("payroll_slips").select("id, run_id, employee_id")
        .in_("run_id", run_ids),
        key="id", label="bonus.slips")
    counted: dict = {}
    seen: set = set()
    by_run = {str(r["id"]): str(r.get("month") or "") for r in runs}
    for s in slips:
        eid, rid = str(s.get("employee_id")), str(s.get("run_id"))
        # One month counts once however many slips it carries — a re-run or a
        # correction is not a second month of service.
        key = (eid, by_run.get(rid, rid))
        if key in seen:
            continue
        seen.add(key)
        counted[eid] = counted.get(eid, 0) + 1
    return counted


def _working_days(db, *, firm_id: str, accounting_year: str,
                  employee_ids: set) -> dict:
    """Days ACTUALLY worked in the year, or absent where nothing is recorded.

    A missing key means "not recorded" and the domain module decides what that
    means; a key present with 0 means the attendance says zero. The two are
    different facts and collapsing them is what would disqualify an employee
    on the strength of a row nobody wrote.
    """
    if not employee_ids:
        return {}
    months = _fy_months(accounting_year)
    years = sorted({y for y, _ in months})
    rows = fetch_all(
        lambda: db.table("attendance")
        .select("id, employee_id, month, year, days_present")
        .eq("firm_id", firm_id).in_("year", years),
        key="id", label="bonus.attendance")
    wanted = set(months)
    out: dict = {}
    for r in rows:
        eid = str(r.get("employee_id"))
        if eid not in employee_ids:
            continue
        try:
            pair = (int(r.get("year")), int(r.get("month")))
        except (TypeError, ValueError):
            continue
        if pair not in wanted:
            continue
        out[eid] = out.get(eid, 0) + int(r.get("days_present") or 0)
    return out


def _disqualifications(db, *, firm_id: str, client_id: str,
                       accounting_year: str) -> dict:
    rows = fetch_all(
        lambda: db.table("bonus_disqualifications")
        .select("id, employee_id, ground, dismissed_on")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("accounting_year", accounting_year),
        key="id", label="bonus.disqualifications")
    return {str(r["employee_id"]): r.get("ground") for r in rows}


def save_declaration(db, *, firm_id: str, client_id: str, accounting_year: str,
                     rate_bps: Optional[int], allocable_surplus_paise: Optional[int],
                     minimum_wage_monthly_paise: Optional[int],
                     scheduled_employment: Optional[str], notes: Optional[str],
                     actor_id: Optional[str]) -> dict:
    """Record or replace the employer's §10/§11 determination for the year."""
    existing = _declaration(db, firm_id=firm_id, client_id=client_id,
                            accounting_year=accounting_year)
    payload = {
        "rate_bps": int(rate_bps) if rate_bps is not None else 833,
        "allocable_surplus_paise": allocable_surplus_paise,
        "minimum_wage_monthly_paise": minimum_wage_monthly_paise,
        "scheduled_employment": scheduled_employment,
        "notes": notes,
    }
    if existing:
        from datetime import datetime, timezone
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        # The tenant filter on the UPDATE as well as the id: the service-role
        # key bypasses RLS, and an id that came from a read of another firm's
        # row would otherwise be written. The columns are written OUT rather
        # than passed as `payload`, so the column ratchet
        # (tests/test_backend_columns_exist_pg.py) can read which ones this
        # touches — a variable is invisible to it.
        (db.table("bonus_declarations").update({
            "rate_bps": payload["rate_bps"],
            "allocable_surplus_paise": payload["allocable_surplus_paise"],
            "minimum_wage_monthly_paise": payload["minimum_wage_monthly_paise"],
            "scheduled_employment": payload["scheduled_employment"],
            "notes": payload["notes"],
            "updated_at": payload["updated_at"],
         }).eq("firm_id", firm_id).eq("id", existing["id"]).execute())
        return {**existing, **payload}
    inserted = db.table("bonus_declarations").insert({
        "firm_id": firm_id, "client_id": client_id,
        "accounting_year": accounting_year, "created_by": actor_id,
        "rate_bps": payload["rate_bps"],
        "allocable_surplus_paise": payload["allocable_surplus_paise"],
        "minimum_wage_monthly_paise": payload["minimum_wage_monthly_paise"],
        "scheduled_employment": payload["scheduled_employment"],
        "notes": payload["notes"],
    }).execute()
    return (inserted.data or [{}])[0]
