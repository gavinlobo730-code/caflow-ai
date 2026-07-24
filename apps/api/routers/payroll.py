"""
Payroll router — Employee master, salary structures, payroll runs, statutory, reports.

IT Act §192: TDS on salary (monthly deduction, annual projected basis).
EPF Act §6: Employer PF = 12% of (Basic + DA), capped at a ₹15,000 wage ceiling → ₹1,800 max employer contribution.
ESI Act: Employee ESI = 0.75% of gross; Employer ESI = 3.25% of gross (applicable when gross ≤ ₹21,000/month).
PT: State-specific professional tax slab, keyed on the employee's pt_state; an
    unset/unrecognised state withholds nothing (no silent single-state default).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from datetime import datetime, timezone, date
from decimal import Decimal as _Decimal, ROUND_HALF_UP as _ROUND_HALF_UP
import math

from models.common import api_response
from models.payroll import EmployeeIn, EmployeeUpdateIn, SalaryStructureIn, PayrollRunIn, RunStatusIn, PayrollDisburseIn
from core.permissions import rbac
from services.timeline_service import timeline_service
from services.internal_client_service import assert_not_internal_for_payroll
from domain.income_tax.statutory_rates import (
    rates_for, slab_tax_paise, apply_rebate_87a,
    apply_surcharge_with_marginal_relief, cess_paise, current_fy,
)

router = APIRouter(prefix="/api/payroll", tags=["payroll"])

# Mock mode is determined per-request by _db() returning None when SUPABASE_URL
# is unset (dev/test). No module-level flag — the live backend always uses the
# real Supabase client. _MOCK_FINALIZED_RUNS only holds state under that fallback.
_MOCK_FINALIZED_RUNS: set[str] = set()  # tracks finalized run IDs in mock mode


def _db():
    import os
    if not os.environ.get("SUPABASE_URL"):
        return None
    from core.supabase_client import get_supabase
    return get_supabase()


# ─── PT Slabs by state ─────────────────────────────────────────────────────────
# Profession Tax is levied under each STATE's own Profession Tax Act, not a
# central statute, so the slab depends on the employee's pt_state — there is
# no single national default.
#
# Karnataka: Karnataka Tax on Professions, Trades, Callings and Employments
# Act, 1976, Schedule Serial No. 1 (salary & wage earners), as amended by the
# Karnataka Tax on Professions, Trades, Callings and Employments (Amendment)
# Act, 2023 (Governor's assent 13 Mar 2023; in force w.e.f. 1 April 2023).
# The amendment raised the exemption ceiling from ₹15,000 to ₹25,000 and
# collapsed the earlier graduated ₹150/₹200 tiers into a single flat rate:
#     gross monthly salary/wage  < ₹25,000  → Nil
#                               ≥ ₹25,000  → ₹200/month
# Karnataka levies no February differential (unlike Maharashtra); annual
# maximum is ₹2,400. Anyone earning < ₹25,000/month (the old code taxed them
# from ₹15,000) must not have PT withheld post-01-Apr-2023.
_PT_SLABS_KA = [
    (0,        24999_99,  0),        # gross < ₹25,000 → Nil
    (25000_00, None,     200_00),    # gross ≥ ₹25,000 → ₹200/month
]

# West Bengal: The West Bengal State Tax on Professions, Trades, Callings and
# Employments Act, 1979, Schedule (salary & wage earners). A 5-tier monthly
# slab on monthly gross (annual maximum ₹2,400). The old single-tier table
# (flat ₹200 above ₹10,000) over-withheld everyone earning ₹10,001–₹40,000,
# who owe ₹110/₹130/₹150 — not ₹200.
_PT_SLABS_WB = [
    (0,         10000_00,  0),        # ≤ ₹10,000 → Nil
    (10000_01,  15000_00, 110_00),    # ₹10,001–₹15,000 → ₹110
    (15000_01,  25000_00, 130_00),    # ₹15,001–₹25,000 → ₹130
    (25000_01,  40000_00, 150_00),    # ₹25,001–₹40,000 → ₹150
    (40000_01,  None,     200_00),    # > ₹40,000     → ₹200
]

# Maharashtra: Maharashtra State Tax on Professions, Trades, Callings and
# Employments Act, 1975, Schedule I (salary & wage earners). Unlike KA/WB it is
# NOT a plain monthly-gross slab — two statutory twists are handled in
# _compute_pt_mh below rather than a table:
#   • February differential: the top (>₹10,000) tier pays ₹300 in February and
#     ₹200 in the other 11 months, so the year totals the ₹2,500 cap.
#   • Women's exemption (w.e.f. 01-Apr-2023): women earning ≤ ₹25,000/month pay
#     nil. Needs the employee's gender; an unspecified gender defaults to the
#     standard (non-exempt) slab — we never grant an exemption we can't
#     substantiate (that would under-withhold).
# The men's/base slab itself: ≤₹7,500 nil, ₹7,501–₹10,000 → ₹175, >₹10,000 → ₹200.
_MH_NIL_MAX          = 7500_00     # ≤ this → Nil (base slab)
_MH_175_MAX          = 10000_00    # ₹7,501–₹10,000 → ₹175
_MH_MID_TAX          = 175_00
_MH_TOP_TAX          = 200_00      # >₹10,000, 11 months
_MH_TOP_TAX_FEBRUARY = 300_00      # >₹10,000, February only
_MH_WOMEN_EXEMPT_MAX = 25000_00    # women ≤ this → Nil (w.e.f. 01-Apr-2023)

# Tamil Nadu: TN Municipal Laws (Second Amendment) Act 1998 / Greater Chennai
# Corporation profession-tax schedule. TN is levied HALF-YEARLY on HALF-YEARLY
# income (each band below is a 6-month figure and a 6-month tax), remitted by
# 30 Sep (Apr–Sep) and 31 Mar (Oct–Mar). We therefore deduct the whole
# half-yearly amount in the September (month 9) and March (month 3) payroll
# runs and nil otherwise — this is common payroll practice, matches the
# remittance cycle, and reconciles to the exact liability with no paise drift.
# Half-yearly income is approximated as 6 × the run-month gross (the slip engine
# is stateless per month, so it cannot sum the half-year's actual earnings).
#
# ⚠️ AMOUNTS PENDING CA CONFIRMATION: these are the long-standing Greater Chennai
# Corporation half-yearly amounts. A revision was notified for H2 FY2024-25
# (reported middle-band amounts ₹180 / ₹425 / ₹930) but public reporting is
# inconsistent and local bodies outside Chennai differ. Confirm the current
# local-body amounts before relying on TN withholding; they are isolated here
# for a one-line swap. Thresholds are HALF-YEARLY rupees.
_PT_SLABS_TN_HALF_YEARLY = [
    (0,          21000_00,   0),        # ≤ ₹21,000 (6-mo) → Nil
    (21000_01,   30000_00,  135_00),    # ₹21,001–₹30,000 → ₹135
    (30000_01,   45000_00,  315_00),    # ₹30,001–₹45,000 → ₹315
    (45000_01,   60000_00,  690_00),    # ₹45,001–₹60,000 → ₹690
    (60000_01,   75000_00, 1025_00),    # ₹60,001–₹75,000 → ₹1,025
    (75000_01,   None,     1250_00),    # > ₹75,000       → ₹1,250
]

# States whose PT is a plain monthly-gross → monthly-tax slab.
_PT_SLABS_BY_STATE = {
    "KA": _PT_SLABS_KA,
    "WB": _PT_SLABS_WB,
}

_FEMALE_TOKENS = {"f", "female", "woman", "women", "w"}


def _slab_lookup(slabs, amount_paise: int) -> int:
    for low, high, tax in slabs:
        if amount_paise >= low and (high is None or amount_paise <= high):
            return tax
    return 0


def _compute_pt_mh(gross_paise: int, month: Optional[int], gender: Optional[str]) -> int:
    """Maharashtra PT (Act 1975, Sch. I) — see the _MH_* constants above."""
    is_february = (month == 2)
    top = _MH_TOP_TAX_FEBRUARY if is_february else _MH_TOP_TAX
    if (gender or "").strip().lower() in _FEMALE_TOKENS:
        # Women: exempt up to ₹25,000/month; above that, same top rate as men.
        return 0 if gross_paise <= _MH_WOMEN_EXEMPT_MAX else top
    # Base/men's slab (also the default when gender is unspecified).
    if gross_paise <= _MH_NIL_MAX:
        return 0
    if gross_paise <= _MH_175_MAX:
        return _MH_MID_TAX
    return top


def _compute_pt_tn(gross_paise: int, month: Optional[int]) -> int:
    """Tamil Nadu PT — half-yearly levy deducted in Sep (month 9) and Mar (month
    3) only; nil in the other months. Half-yearly income ≈ 6 × monthly gross."""
    if month not in (9, 3):
        return 0
    return _slab_lookup(_PT_SLABS_TN_HALF_YEARLY, gross_paise * 6)


def _compute_pt(gross_paise: int, state: Optional[str] = None,
                month: Optional[int] = None, gender: Optional[str] = None) -> int:
    """Professional Tax for the run month in paise. IT Act §16(iii) — PT actually
    paid is deductible from salary income; the PT liability itself is fixed by
    the employee's state. KA/WB are plain monthly slabs; MH and TN have their
    own rules (February differential + women's exemption / half-yearly levy) and
    take the payroll `month` (1-12) and, for MH, the employee `gender`. An unset
    or unrecognised state returns 0 rather than falling back to any one state's
    rate — the CA must set pt_state explicitly for PT to be withheld."""
    code = (state or "").strip().upper()
    if code == "MH":
        return _compute_pt_mh(gross_paise, month, gender)
    if code == "TN":
        return _compute_pt_tn(gross_paise, month)
    return _slab_lookup(_PT_SLABS_BY_STATE.get(code, ()), gross_paise)


def _compute_pf(pf_wages_paise: int) -> dict:
    """
    PF computation per EPF Act 1952 Section 6: contribution is 12% of "basic
    wages, dearness allowance and retaining allowance (if any)" — the ₹15,000
    statutory wage ceiling applies to that same Basic+DA base, not Basic
    alone. task #229: the caller previously passed basic_paise only, silently
    under-computing (and under-posting to the GL) both the employee and
    employer contribution for any employee with a nonzero da_percent. No
    retaining allowance is modelled by this payroll module (not a component
    of the employee master), so pf_wages_paise is Basic + DA here.
    Employee contribution: 12% of PF wages (capped at ₹15,000 → max ₹1,800).
    Employer contribution: 12% of PF wages (same cap).
    """
    # Cap PF wages at ₹15,000 for PF computation
    capped = min(pf_wages_paise, 1500000)
    employee = math.floor(capped * 12 / 100)
    employer = math.floor(capped * 12 / 100)
    return {"employee": employee, "employer": employer}


def _compute_esi(gross_paise: int) -> dict:
    """
    ESI computation per ESI Act §2(9).
    Applicable only if gross ≤ ₹21,000/month.
    Employee: 0.75% of gross. Employer: 3.25% of gross.
    """
    if gross_paise > 2100000:
        return {"employee": 0, "employer": 0}
    employee = math.floor(gross_paise * 75 / 10000)
    employer = math.floor(gross_paise * 325 / 10000)
    return {"employee": employee, "employer": employer}


def _compute_slip(emp: dict, attendance: Optional[dict] = None, fy: Optional[str] = None,
                  pt_month: Optional[int] = None) -> dict:
    """
    Compute a single payroll slip in integer paise. No floating point on final values.
    IT Act Section 192: TDS on salary — simplified monthly deduction (annual
    projected / 12). `fy` should be the financial year the payroll month
    falls in (see current_fy()) so a retroactively-run payroll for an earlier
    FY doesn't pick up a later year's rates; defaults to today's FY if omitted.
    `pt_month` is the calendar month (1-12) of the payroll run — required for the
    states whose Professional Tax depends on the month (Maharashtra's February
    differential, Tamil Nadu's Sep/Mar half-yearly deduction).
    """
    working_days  = (attendance or {}).get("working_days", 26)
    days_present  = (attendance or {}).get("days_present", 26)
    lop_days      = (attendance or {}).get("lop_days", 0)

    # Integer/Decimal-only proration (CLAUDE.md: rupee calculations must never
    # use floating point — the previous `(working_days - lop_days) / working_days`
    # float division, then multiplying HRA/DA's fractional percent via
    # float(hra_percent), produced verified off-by-one-paise mismatches
    # against exact Decimal arithmetic). working_days is floored at 1 to avoid
    # a divide-by-zero on malformed attendance data; lop_days is clamped to
    # [0, working_days] so a negative lop_days (or one exceeding working_days)
    # can no longer push the proration factor above 1.0 and pay an employee
    # more than their declared salary, nor below 0.
    working_days = max(1, int(working_days))
    lop_days = min(max(0, int(lop_days)), working_days)
    present_days = working_days - lop_days

    def _prorate(amount_paise) -> int:
        return (int(amount_paise or 0) * present_days) // working_days

    def _percent_of(base_paise: int, percent) -> int:
        pct = _Decimal(str(percent or 0))
        return int((_Decimal(base_paise) * pct / 100).quantize(_Decimal("1"), rounding=_ROUND_HALF_UP))

    basic     = _prorate(emp.get("basic_paise", 0))
    hra       = _percent_of(basic, emp.get("hra_percent", 0))
    da        = _percent_of(basic, emp.get("da_percent", 0))
    lta       = _prorate(emp.get("lta_paise", 0))
    medical   = _prorate(emp.get("medical_paise", 0))
    special   = _prorate(emp.get("special_allowance_paise", 0))
    # other_allowances_paise is a real employee-master field (models/payroll.py,
    # captured by the Add-Employee form and the CSV importer) that was
    # previously dropped from gross entirely — understating gross AND net for
    # any employee who had one. LOP-prorated like every other fixed component.
    other     = _prorate(emp.get("other_allowances_paise", 0))
    gross     = basic + hra + da + lta + medical + special + other

    # EPF Act §6: PF wages = Basic + DA (task #229 — basic alone under-computed PF).
    pf   = _compute_pf(basic + da) if emp.get("pf_applicable") else {"employee": 0, "employer": 0}
    esi  = _compute_esi(gross) if emp.get("esi_applicable") else {"employee": 0, "employer": 0}
    pt   = _compute_pt(gross, emp.get("pt_state"), month=pt_month, gender=emp.get("gender")) if emp.get("pt_applicable") else 0

    # IT Act §192: simplified monthly TDS = annual tax on (projected annual
    # gross - standard deduction) / 12. Standard deduction and slabs come
    # from the FY-versioned registry (domain/income_tax/statutory_rates.py) —
    # the new-regime figure applies since payroll withholding defaults to the
    # new regime (see _compute_tds_192).
    rates = rates_for(fy)
    annual_gross = gross * 12
    std_deduction_paise = rates.new_regime_standard_deduction_paise
    taxable_annual = max(0, annual_gross - std_deduction_paise)
    tds_monthly = _compute_tds_192(taxable_annual, fy=fy)

    deductions = pf["employee"] + esi["employee"] + pt + tds_monthly
    net = gross - deductions

    return {
        "gross_paise":        gross,
        "basic_paise":        basic,
        "hra_paise":          hra,
        "da_paise":           da,
        "lta_paise":          lta,
        "medical_paise":      medical,
        "special_allowance_paise": special,
        "other_allowances_paise":  other,
        "pf_employee_paise":  pf["employee"],
        "pf_employer_paise":  pf["employer"],
        "esi_employee_paise": esi["employee"],
        "esi_employer_paise": esi["employer"],
        "pt_paise":           pt,
        "tds_paise":          tds_monthly,
        "net_paise":          net,
        "working_days":       working_days,
        "days_present":       days_present,
        "lop_days":           lop_days,
    }


def _compute_tds_192(taxable_annual_paise: int, fy: Optional[str] = None) -> int:
    """
    IT Act Section 192: TDS on salary, computed on projected annual taxable
    income. Employees are withheld under the new tax regime by default —
    Section 115BAC(1A) makes the new regime the default for individuals, and
    absent an employee declaration opting for the old regime (not yet
    modelled by this payroll module — see roadmap), the employer withholds
    on the new-regime basis. Includes Section 87A rebate (with marginal
    relief) and Section 2(29C) surcharge (with marginal relief) — a
    correctly-configured employer payroll system applies both when
    projecting a high earner's annual withholding, not just the plain slab
    rate. Rates come from the FY-versioned registry (statutory_rates.py),
    the same source of truth used by the ITR engine. Integer paise
    throughout — never float (CLAUDE.md).
    """
    rates = rates_for(fy)
    slabs = rates.new_regime_slabs
    tax = slab_tax_paise(taxable_annual_paise, slabs)
    tax_after_rebate = apply_rebate_87a(taxable_annual_paise, tax, rates.new_regime_rebate)
    surcharge = apply_surcharge_with_marginal_relief(
        taxable_annual_paise, tax_after_rebate, rates.surcharge_brackets,
        rates.new_regime_surcharge_cap_percent,
        lambda income_paise: slab_tax_paise(income_paise, slabs),
    )
    annual_tax = tax_after_rebate + surcharge
    annual_tax += cess_paise(annual_tax, rates)
    return annual_tax // 12


# ─── Employee Master ──────────────────────────────────────────────────────────

@router.get("/employees")
def list_employees(
    client_id: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """client_id is optional — a firm-wide payroll dashboard lists every
    client's employees in one call; a per-client workspace passes client_id
    to scope the result.

    include_inactive=True also returns resigned/terminated employees (for the
    Employees roster's "show inactive" toggle); default keeps the historical
    active-only behaviour so existing dashboard/run callers are unaffected."""
    db = _db()
    if not db:
        return api_response(True, [])
    q = db.table("payroll_employees").select("*").eq("firm_id", current_user["firm_id"])
    if not include_inactive:
        q = q.eq("status", "active")
    if client_id:
        q = q.eq("client_id", client_id)
    res = q.order("name").execute()
    return api_response(True, res.data or [])


@router.post("/employees")
def create_employee(
    data: EmployeeIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    db = _db()
    if not db:
        return api_response(True, {"id": "mock-id", **data.model_dump()})
    # Guardrail G4: no payroll/HR for the internal practice client.
    assert_not_internal_for_payroll(data.client_id, current_user["firm_id"])
    payload = data.model_dump()
    payload["firm_id"] = current_user["firm_id"]
    payload["status"] = "active"
    row = db.table("payroll_employees").insert(payload).execute()
    emp = (row.data or [{}])[0]
    timeline_service.log(data.client_id, "work", "Employee Added",
        f"{data.name} added to payroll", "info")
    return api_response(True, emp)


@router.patch("/employees/{employee_id}")
def update_employee(
    employee_id: str,
    data: EmployeeUpdateIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    db = _db()
    update = data.model_dump(exclude_none=True)
    if not db:
        return api_response(True, update)
    row = db.table("payroll_employees").update(update).eq("id", employee_id).eq("firm_id", current_user["firm_id"]).execute()
    return api_response(True, (row.data or [{}])[0])


@router.delete("/employees/{employee_id}")
def delete_employee(
    employee_id: str,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """Hard-delete an employee — allowed ONLY when they have never appeared in a
    payroll run. An employee with payslips is part of the statutory record (Form
    16, 24Q, PF/ESI returns) and must be preserved: the caller should deactivate
    (PATCH status=resigned/terminated) instead, so history stays intact. Mirrors
    the customer/vendor "delete-if-unused, else deactivate" guard."""
    db = _db()
    if not db:
        return api_response(True, {"id": employee_id, "deleted": True})

    # Firm-scoped existence check (maybe_single: another firm's row 404s as missing).
    emp = (db.table("payroll_employees").select("id, name, client_id")
           .eq("id", employee_id).eq("firm_id", current_user["firm_id"]).maybe_single().execute().data)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    slip = (db.table("payroll_slips").select("id")
            .eq("employee_id", employee_id).limit(1).execute().data)
    if slip:
        raise HTTPException(
            status_code=409,
            detail="This employee has payroll history and cannot be deleted. Deactivate them (mark resigned/terminated) instead.",
        )

    db.table("payroll_employees").delete().eq("id", employee_id).eq("firm_id", current_user["firm_id"]).execute()
    timeline_service.log(emp["client_id"], "work", "Employee Deleted",
        f"{emp.get('name', 'Employee')} removed from payroll (no payroll history)", "info")
    return api_response(True, {"id": employee_id, "deleted": True})


# ─── Salary Structures ────────────────────────────────────────────────────────

@router.get("/salary-structures")
def list_salary_structures(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("payroll", "read"))
):
    db = _db()
    if not db:
        return api_response(True, [])
    res = db.table("salary_structures").select("*").eq("firm_id", current_user["firm_id"]).eq("client_id", client_id).order("name").execute()
    return api_response(True, res.data or [])


@router.post("/salary-structures")
def create_salary_structure(
    data: SalaryStructureIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    db = _db()
    if not db:
        return api_response(True, {"id": "mock-id", **data.model_dump()})
    # Guardrail G4: no payroll/HR for the internal practice client.
    assert_not_internal_for_payroll(data.client_id, current_user["firm_id"])
    payload = data.model_dump()
    payload["firm_id"] = current_user["firm_id"]
    row = db.table("salary_structures").insert(payload).execute()
    return api_response(True, (row.data or [{}])[0])


# ─── Payroll Runs ─────────────────────────────────────────────────────────────

@router.get("/runs")
def list_runs(
    client_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """client_id is optional — see list_employees above for why."""
    db = _db()
    if not db:
        return api_response(True, [])
    q = db.table("payroll_runs").select("*").eq("firm_id", current_user["firm_id"])
    if client_id:
        q = q.eq("client_id", client_id)
    res = q.order("month", desc=True).execute()
    return api_response(True, res.data or [])


@router.post("/runs")
def create_run(
    data: PayrollRunIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """
    Create a draft payroll run and compute slips for all active employees.
    Computation is deterministic from employee master + attendance.
    """
    db = _db()
    client_id = data.client_id
    month     = data.month  # e.g. "2026-06"

    if not db:
        return api_response(True, {"id": "mock-run", "month": month, "status": "draft"})

    # Guardrail G4: no payroll/HR for the internal practice client.
    assert_not_internal_for_payroll(client_id, current_user["firm_id"])

    # Check for duplicate run
    existing = db.table("payroll_runs").select("id").eq("firm_id", current_user["firm_id"]).eq("client_id", client_id).eq("month", month).execute()
    if existing.data:
        raise HTTPException(status_code=409, detail=f"Payroll run for {month} already exists")

    # task #229 audit finding: the SELECT above is a check-then-act race with
    # no backing DB constraint until migration 237 — two concurrent requests
    # for the same (firm, client, month) could both pass it and both insert a
    # run row. The UNIQUE index (migration 237) is the authoritative backstop
    # for the race this SELECT can't close; translate a concurrent collision
    # into the same friendly 409 instead of a raw 500, mirroring
    # routers/sales_invoices.py's identical duplicate-number guard.
    from services.numbering import is_unique_violation
    try:
        run_res = db.table("payroll_runs").insert({
            "firm_id":   current_user["firm_id"],
            "client_id": client_id,
            "month":     month,
            "status":    "draft",
        }).execute()
    except Exception as e:
        if is_unique_violation(e):
            raise HTTPException(status_code=409, detail=f"Payroll run for {month} already exists")
        raise
    run = (run_res.data or [{}])[0]
    run_id = run["id"]

    # Fetch active employees
    emps = db.table("payroll_employees").select("*").eq("firm_id", current_user["firm_id"]).eq("client_id", client_id).eq("status", "active").execute().data or []

    m, y = int(month.split("-")[1]), int(month.split("-")[0])
    fy = current_fy(date(y, m, 1))  # FY of the payroll period, not "today"

    slips = []
    totals = {"gross": 0, "net": 0, "pf": 0, "esi": 0, "pt": 0, "tds": 0}

    for emp in emps:
        att_res = db.table("attendance").select("*").eq("employee_id", emp["id"]).eq("month", m).eq("year", y).execute()
        attendance = (att_res.data or [None])[0]

        slip = _compute_slip(emp, attendance, fy=fy, pt_month=m)
        slip["run_id"]      = run_id
        slip["employee_id"] = emp["id"]

        slips.append(slip)
        totals["gross"] += slip["gross_paise"]
        totals["net"]   += slip["net_paise"]
        totals["pf"]    += slip["pf_employee_paise"] + slip["pf_employer_paise"]
        totals["esi"]   += slip["esi_employee_paise"] + slip["esi_employer_paise"]
        totals["pt"]    += slip["pt_paise"]
        totals["tds"]   += slip["tds_paise"]

    # Atomicity: the run header row was inserted first (above), but PostgREST
    # exposes no multi-statement transaction here — so if the slip insert
    # fails we compensate by deleting the just-created header. Without this a
    # failed slip insert strands an empty run whose (firm, client, month)
    # duplicate-guard then 409s every retry, permanently blocking that month.
    if slips:
        try:
            db.table("payroll_slips").insert(slips).execute()
        except Exception:
            db.table("payroll_runs").delete().eq("id", run_id).eq("firm_id", current_user["firm_id"]).execute()
            raise

    # Update run totals
    db.table("payroll_runs").update({
        "total_gross_paise": totals["gross"],
        "total_net_paise":   totals["net"],
        "total_pf_paise":    totals["pf"],
        "total_esi_paise":   totals["esi"],
        "total_pt_paise":    totals["pt"],
        "total_tds_paise":   totals["tds"],
        "headcount":         len(emps),
    }).eq("id", run_id).execute()

    run["totals"] = totals
    run["headcount"] = len(emps)
    timeline_service.log(
        client_id, "work", "Payroll Run Created",
        f"Draft payroll run for {month} created with {len(emps)} employees",
        "info", firm_id=current_user.get("firm_id", ""),
        entity_type="payroll_run", entity_id=run_id,
        actor_id=current_user.get("auth_user_id"),
    )
    return api_response(True, run)


@router.get("/runs/{run_id}/slips")
def get_run_slips(
    run_id: str,
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """R2.10 fix: payroll_slips has no firm_id column (migrations 014/093 —
    it's tenant-scoped transitively via run_id -> payroll_runs.firm_id, same
    as the RLS policy). The previous .eq("firm_id", ...) filter directly on
    payroll_slips referenced a column that doesn't exist, which PostgREST
    rejects outright against a real (non-mock) database — this endpoint
    could never return data in production. Fixed to verify the run belongs
    to the caller's firm first (like salary_register below), then query
    slips by run_id alone."""
    db = _db()
    if not db:
        return api_response(True, [])
    run = db.table("payroll_runs").select("id").eq("id", run_id).eq("firm_id", current_user["firm_id"]).execute()
    if not run.data:
        raise HTTPException(status_code=404, detail=f"Payroll run {run_id} not found")
    slips = db.table("payroll_slips").select("*, payroll_employees(name, pan, designation, department)").eq("run_id", run_id).execute()
    return api_response(True, slips.data or [])


@router.get("/salary-slips/{slip_id}/pdf")
def download_salary_slip_pdf(
    slip_id: str,
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """
    Render and download a salary slip (payslip) PDF.

    Shows firm/employer header, employee name + PAN, pay period, an earnings
    table, a deductions table (PF/ESI/PT/TDS), gross & net pay, and a footer.
    All rupee amounts are formatted from integer paise — no float arithmetic.
    Firm-scoped: the slip's payroll run must belong to the caller's firm.
    """
    from fastapi.responses import Response
    from services.payslip_pdf_service import get_payslip_pdf

    if not _db():
        raise HTTPException(status_code=503, detail="Payslip PDF unavailable in mock mode")

    try:
        pdf_bytes, filename = get_payslip_pdf(slip_id, current_user.get("firm_id"))
    except ValueError:
        raise HTTPException(status_code=404, detail="Salary slip not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/runs/{run_id}/status")
def update_run_status(
    run_id: str,
    data: RunStatusIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """Move run to 'review' or back to 'draft'. Finalization is a separate endpoint.

    Immutability guard covers BOTH terminal states, not just "finalized": a
    "paid" run has already had its accrual AND disbursement journals posted,
    so reverting it to draft/review would let finalize_run (which only checks
    for "finalized") re-post a second full accrual journal for the same
    month — journal_for_payroll's idempotency dedup keys on
    (firm, client, reference_no=PAY-{month}, entry_date=today), not the
    payroll period, so re-finalizing on a later calendar day does not match
    the original entry and silently double-posts."""
    db = _db()
    new_status = data.status
    if not db:
        # Mock: track finalized runs to enforce immutability
        if run_id in _MOCK_FINALIZED_RUNS:
            raise HTTPException(status_code=409, detail="Run already finalized — cannot change status")
        return api_response(True, {"id": run_id, "status": new_status})
    row = (db.table("payroll_runs").update({"status": new_status}).eq("id", run_id)
           .eq("firm_id", current_user["firm_id"])
           .not_.in_("status", ["finalized", "paid"]).execute())
    if not row.data:
        raise HTTPException(status_code=404, detail="Run not found or already finalized/paid")
    return api_response(True, row.data[0])


@router.post("/runs/{run_id}/finalize")
def finalize_run(
    run_id: str,
    current_user: dict = Depends(rbac("payroll", "finalize"))
):
    """
    Finalize payroll run — Partner only. Immutable after this point.
    Creates journal entry per Product Bible immutability rules:

    Dr  Salaries Expense        (gross wages + employer PF/ESI = total cost)
      Cr  Net Salary Payable    (total net pay)
      Cr  PF Payable            (employee + employer PF)
      Cr  ESI Payable           (employee + employer ESI)
      Cr  PT Payable
      Cr  TDS Payable - Salary  (feeds 24Q)

    IT Act §192 TDS recorded for 24Q return. The run is marked finalized ONLY if
    the journal actually posts, so a posting failure leaves the run re-runnable
    rather than immutably finalized with no GL entry.
    """
    db = _db()
    if not db:
        if run_id in _MOCK_FINALIZED_RUNS:
            raise HTTPException(status_code=409, detail="Run already finalized")
        _MOCK_FINALIZED_RUNS.add(run_id)
        return api_response(True, {"id": run_id, "status": "finalized"})

    # F1/F4 fix: scope by firm_id -- an unscoped lookup let any Partner finalize
    # (and post a real, immutable GL journal for) another firm's payroll run by
    # guessing its run_id. maybe_single() (not single()) so a run belonging to
    # a different firm is indistinguishable from a nonexistent one -- both
    # cleanly 404 instead of the query raising.
    run = (db.table("payroll_runs").select("*").eq("id", run_id)
           .eq("firm_id", current_user["firm_id"]).maybe_single().execute().data)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    # A "paid" run must be just as terminal as a "finalized" one here: it has
    # already had its accrual journal posted (that's how it reached "paid" in
    # the first place), so re-finalizing it would post a SECOND accrual
    # journal for the same month. journal_for_payroll's idempotency dedup
    # keys on (firm, client, reference_no=PAY-{month}, entry_date=today), not
    # the payroll period, so it does not catch a re-finalization on a later
    # calendar day -- this guard is the actual backstop.
    if run["status"] in ("finalized", "paid"):
        raise HTTPException(status_code=409, detail=f"Run already {run['status']}")

    client_id = run["client_id"]
    firm_id   = run["firm_id"]

    # Nothing to post (no active employees / all-zero run) — refuse gracefully
    # instead of building an empty journal that the kernel rejects (would 500).
    if int(run.get("total_gross_paise") or 0) <= 0:
        raise HTTPException(status_code=400, detail="Cannot finalize an empty payroll run (no computed salary).")

    # Post the payroll journal FIRST; only mark the run finalized if it posted.
    from services.phase2_journal_service import Phase2JournalService
    svc = Phase2JournalService()
    journal_id = svc.journal_for_payroll(run, firm_id, client_id)
    if not journal_id:
        # As of task #103, journal_for_payroll re-raises unexpected posting
        # failures instead of swallowing them into a None return — so a
        # falsy journal_id here can now only happen in _USE_MOCK mode. Kept
        # as a defensive guard: do NOT mark the run finalized — leaving it
        # re-runnable so the Partner can retry once the cause is cleared (a retry is
        # safe: the kernel dedupes on reference_no=PAY-{month}). Prevents an
        # immutable "finalized" run with no GL entry reported as success.
        return api_response(False, None, "Payroll journal could not be posted. The run was not finalized; please retry.")

    db.table("payroll_runs").update({
        "status":          "finalized",
        "finalized_at":    datetime.now(timezone.utc).isoformat(),
        "journal_entry_id": journal_id,
    }).eq("id", run_id).execute()

    timeline_service.log(client_id, "work", "Payroll Finalized",
        f"Payroll for {run['month']} finalized — {run.get('headcount', 0)} employees", "success")

    return api_response(True, {"id": run_id, "status": "finalized", "journal_entry_id": journal_id})


@router.post("/runs/{run_id}/disburse")
def disburse_run(
    run_id: str,
    data: PayrollDisburseIn,
    current_user: dict = Depends(rbac("payroll", "finalize"))
):
    """
    Mark a FINALIZED payroll run as PAID — Partner only.

    Posts the salary disbursement journal, clearing the Net Salary Payable
    liability raised at finalization against the bank the salaries were paid from:

        Dr  Net Salary Payable   (total net pay)
          Cr  Bank               (total net pay)

    The run is marked paid ONLY if the journal actually posts, so a posting
    failure leaves it re-runnable rather than 'paid' with no GL entry.
    """
    db = _db()
    if not db:
        return api_response(True, {"id": run_id, "status": "paid"})

    # Firm-scoped lookup (maybe_single: another firm's run 404s like a missing one).
    run = (db.table("payroll_runs").select("*").eq("id", run_id)
           .eq("firm_id", current_user["firm_id"]).maybe_single().execute().data)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] == "paid":
        raise HTTPException(status_code=409, detail="Payroll run already marked paid.")
    if run["status"] != "finalized":
        raise HTTPException(status_code=400, detail="Only a finalized payroll run can be disbursed. Finalize it first.")
    if int(run.get("total_net_paise") or 0) <= 0:
        raise HTTPException(status_code=400, detail="This payroll run has no net pay to disburse.")

    # Resolve the chosen bank account (same client + firm) and its linked GL account.
    bank = (db.table("bank_accounts").select("id, coa_account_id, bank_name, is_active")
            .eq("id", data.bank_account_id).eq("firm_id", current_user["firm_id"])
            .eq("client_id", run["client_id"]).maybe_single().execute().data)
    if not bank:
        raise HTTPException(status_code=404, detail="Bank account not found for this client.")
    if not bank.get("coa_account_id"):
        raise HTTPException(status_code=400,
                            detail=f"Link {bank.get('bank_name', 'this bank account')} to a ledger account before disbursing salaries from it.")

    payment_date = data.payment_date or str(datetime.now(timezone.utc).date())

    from services.phase2_journal_service import Phase2JournalService
    svc = Phase2JournalService()
    journal_id = svc.journal_for_payroll_disbursement(
        run, bank["coa_account_id"], run["firm_id"], run["client_id"], payment_date)
    if not journal_id:
        # Only reachable in mock mode (the service re-raises real posting failures);
        # defensive — do NOT mark paid without a GL entry.
        return api_response(False, None,
                            "Salary disbursement journal could not be posted. The run was not marked paid; please retry.")

    db.table("payroll_runs").update({
        "status":                        "paid",
        "paid_at":                       datetime.now(timezone.utc).isoformat(),
        "disbursement_journal_entry_id": journal_id,
        "paid_from_account_id":          data.bank_account_id,
        "payment_reference":             (data.payment_reference or None),
    }).eq("id", run_id).eq("firm_id", current_user["firm_id"]).execute()

    _net = int(run.get("total_net_paise") or 0)  # integer paise → ₹ display, no float
    timeline_service.log(run["client_id"], "work", "Salary Disbursed",
        f"Payroll for {run['month']} paid from {bank.get('bank_name', 'bank')} "
        f"(₹{_net // 100:,}.{_net % 100:02d} net)", "success",
        firm_id=run["firm_id"], entity_type="payroll_run", entity_id=run_id,
        actor_id=current_user.get("auth_user_id"))

    return api_response(True, {"id": run_id, "status": "paid",
                              "disbursement_journal_entry_id": journal_id})


@router.post("/runs/{run_id}/reverse")
def reverse_run(
    run_id: str,
    current_user: dict = Depends(rbac("payroll", "finalize"))
):
    """
    Reverse a finalized or paid payroll run — Partner only. Reverses the
    disbursement journal (if the run was paid) and the accrual journal, then
    reopens the run at 'review' so it can be corrected and re-finalized.

    Payroll needs its own reversal path because the generic
    POST /api/journal/{id}/reverse explicitly refuses to reverse a
    "Payment"-typed entry (it redirects the caller to
    /api/purchase-payments/{id}/reverse, which does not apply to payroll —
    there is no purchase_payments row for a salary disbursement, a dead
    end), and even for the accrual journal (entry_type="Journal", which that
    endpoint DOES allow) it has no awareness of payroll_runs: it never
    resets status/journal_entry_id, so the run stays stuck 'finalized'/'paid'
    with a journal_entry_id pointing at a now-reversed entry, and
    finalize_run's own guard then permanently blocks re-posting a corrected
    run for that month.
    """
    db = _db()
    if not db:
        return api_response(True, {"id": run_id, "status": "review"})

    firm_id = current_user["firm_id"]
    run = (db.table("payroll_runs").select("*").eq("id", run_id)
           .eq("firm_id", firm_id).maybe_single().execute().data)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] not in ("finalized", "paid"):
        raise HTTPException(status_code=400,
                            detail="Only a finalized or paid payroll run can be reversed.")

    from services.phase2_journal_service import phase2_journal_service
    from services.period_validation_service import period_validation_service
    reversal_date = str(datetime.now(timezone.utc).date())
    # FY-lock: a reversal is a new posting — block it if its date is in a locked year.
    period_validation_service.validate_posting_date(firm_id, reversal_date)

    # Undo in reverse order: disbursement (if any) depends on the accrual
    # having been posted first, so it must be reversed before the accrual.
    if run.get("disbursement_journal_entry_id"):
        phase2_journal_service.reverse_entry(
            db, firm_id, run["disbursement_journal_entry_id"], reversal_date,
            narration=f"Reversal of payroll disbursement for {run['month']}",
            created_by=current_user.get("id"),
        )
    if run.get("journal_entry_id"):
        phase2_journal_service.reverse_entry(
            db, firm_id, run["journal_entry_id"], reversal_date,
            narration=f"Reversal of payroll accrual for {run['month']}",
            created_by=current_user.get("id"),
        )

    db.table("payroll_runs").update({
        "status":                        "review",
        "journal_entry_id":              None,
        "disbursement_journal_entry_id": None,
        "finalized_at":                  None,
        "paid_at":                       None,
        "paid_from_account_id":          None,
        "payment_reference":             None,
    }).eq("id", run_id).eq("firm_id", firm_id).execute()

    timeline_service.log(run["client_id"], "work", "Payroll Reversed",
        f"Payroll for {run['month']} reversed and reopened for correction", "warning",
        firm_id=firm_id, entity_type="payroll_run", entity_id=run_id,
        actor_id=current_user.get("auth_user_id"))

    return api_response(True, {"id": run_id, "status": "review"})


# ─── Reports ──────────────────────────────────────────────────────────────────

@router.get("/reports/salary-register")
def salary_register(
    client_id: str = Query(...),
    month: str = Query(...),
    current_user: dict = Depends(rbac("payroll", "read"))
):
    db = _db()
    if not db:
        return api_response(True, {"month": month, "slips": []})
    run = db.table("payroll_runs").select("id, status, total_gross_paise, total_net_paise, headcount").eq("firm_id", current_user["firm_id"]).eq("client_id", client_id).eq("month", month).execute()
    if not run.data:
        return api_response(True, {"month": month, "run": None, "slips": []})
    run_id = run.data[0]["id"]
    slips = db.table("payroll_slips").select("*, payroll_employees(name, pan, designation, department, bank_account_no, bank_ifsc)").eq("run_id", run_id).execute()
    return api_response(True, {"month": month, "run": run.data[0], "slips": slips.data or []})


@router.get("/reports/statutory-summary")
def statutory_summary(
    client_id: str = Query(...),
    month: str = Query(...),
    current_user: dict = Depends(rbac("payroll", "read"))
):
    db = _db()
    if not db:
        return api_response(True, {})
    run = db.table("payroll_runs").select("*").eq("firm_id", current_user["firm_id"]).eq("client_id", client_id).eq("month", month).execute()
    if not run.data:
        return api_response(True, None)
    r = run.data[0]
    return api_response(True, {
        "month":          month,
        "pf_total_paise": r.get("total_pf_paise", 0),
        "esi_total_paise": r.get("total_esi_paise", 0),
        "pt_total_paise": r.get("total_pt_paise", 0),
        "tds_24q_paise":  r.get("total_tds_paise", 0),
        "gross_paise":    r.get("total_gross_paise", 0),
        "net_paise":      r.get("total_net_paise", 0),
        "headcount":      r.get("headcount", 0),
    })
