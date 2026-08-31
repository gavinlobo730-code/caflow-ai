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

from pydantic import BaseModel, EmailStr

from models.common import api_response
from models.payroll import EmployeeIn, EmployeeUpdateIn, SalaryStructureIn, PayrollRunIn, RunStatusIn, PayrollDisburseIn
from core.authz import assert_client_access, filter_by_client
from core.permissions import rbac
from services.timeline_service import timeline_service
from services import employee_portal_service
from services.internal_client_service import assert_not_internal_for_payroll
import calendar

from domain.payroll.ecr import build_ecr
from domain.payroll.esic import build_esic_return
from domain.payroll.annexure2 import build_annexure_ii
from domain.payroll.lwf import classify_state as classify_lwf_state
from domain.payroll.professional_tax import classify_state as classify_pt_state
from domain.payroll.form24q import (
    build_24q_from_payroll, months_in_quarter, QUARTER_MONTHS)
from domain.tds.tds_computer import TDSDeducteeRecord
from domain.payroll.statutory import esi_contribution_period
from domain.payroll.statutory import rates_for as payroll_rates_for


def _fy_for_month(month: str) -> Optional[str]:
    """Indian FY label for a "YYYY-MM" payroll month — April to March."""
    try:
        y, m = int(month[:4]), int(month[5:7])
    except (ValueError, IndexError):
        return None
    start = y if m >= 4 else y - 1
    return f"{start}-{str(start + 1)[2:]}"
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



# ── Client-assignment scope (M2) ──────────────────────────────────────────────
# `core.authz` makes only the **Partner** firm-wide (`_FIRMWIDE_ROLES`); a
# Manager, Executive or Reviewer sees only the clients in
# `user_client_assignments`. This router did not import core.authz at all, and
# it is the most sensitive surface the sweep has reached: individual salaries,
# PAN, PF/ESI numbers, employee bank details, and endpoints that finalize,
# DISBURSE and reverse a payroll run.
#
#   * `payroll_employees`, `payroll_runs`, `salary_structures` — client_id
#     NOT NULL. Guarded directly.
#   * `payroll_slips` — a `run_id` and an `employee_id` and NOTHING else: no
#     client_id, and no firm_id either. One person's payslip is stored in a
#     table with no tenant column at all, so it is scoped through its run.
#     (Tenant scoping for the PDF already lived in payslip_pdf_service; what
#     was missing is the client check on top of it.)

def _run_client_id(db, current_user: dict, run_id: str) -> tuple[bool, Optional[str]]:
    """`(row_exists, client_id)` for a payroll run, firm-scoped."""
    rows = (db.table("payroll_runs").select("client_id")
            .eq("id", run_id).eq("firm_id", current_user["firm_id"])
            .limit(1).execute().data) or []
    return (bool(rows), rows[0].get("client_id") if rows else None)


def _assert_run_scope(db, current_user: dict, run_id: str) -> Optional[str]:
    """404 unless the caller may act on this payroll run's client.

    404 rather than 403, and the same 404 as "no such run" — otherwise the
    status code becomes an oracle for which run ids are real.
    """
    if not db:
        return None                      # mock mode: no assignments table
    found, client_id = _run_client_id(db, current_user, run_id)
    if not found:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    assert_client_access(current_user, client_id)
    return client_id


def _assert_employee_scope(db, current_user: dict, employee_id: str) -> Optional[str]:
    if not db:
        return None
    rows = (db.table("payroll_employees").select("client_id")
            .eq("id", employee_id).eq("firm_id", current_user["firm_id"])
            .limit(1).execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Employee not found")
    assert_client_access(current_user, rows[0].get("client_id"))
    return rows[0].get("client_id")


def _assert_slip_scope(db, current_user: dict, slip_id: str) -> Optional[str]:
    """A payslip has no tenant column of its own — resolve its run first.

    Two hops, and the FIRST one cannot be firm-scoped because payroll_slips has
    no firm_id: the run lookup is what establishes both the firm and the client,
    which is why it must not be skipped when the slip row is found.
    """
    if not db:
        return None
    rows = (db.table("payroll_slips").select("run_id")
            .eq("id", slip_id).limit(1).execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Salary slip not found")
    return _assert_run_scope(db, current_user, rows[0]["run_id"])


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


def _statutory_gaps(emp: dict) -> list[str]:
    """Statutory deductions this employee's state levies that we did not compute.

    A zero PT for Delhi and a zero PT for Gujarat are the same number meaning
    opposite things — "nothing is due" and "something is due and nobody worked
    it out". _compute_pt cannot tell them apart, because it returns an int; this
    does, so the run can report it.

    LWF is here for a blunter reason: this module does not deduct it anywhere,
    so every employer who owes it has been shown a payslip that quietly omits a
    statutory deduction.
    """
    gaps: list[str] = []
    if emp.get("pt_applicable"):
        pt = classify_pt_state(emp.get("pt_state"))
        if pt.is_gap:
            gaps.append(f"{(emp.get('name') or emp.get('id') or 'employee')}: {pt.note}")
    lwf = classify_lwf_state(emp.get("pt_state"))
    if lwf.is_gap:
        gaps.append(f"{(emp.get('name') or emp.get('id') or 'employee')}: {lwf.note}")
    return gaps


def _to_nearest_rupee(paise: int) -> int:
    """Round a contribution to the nearest rupee, half up, in integer paise.

    EPFO requires each member's contributions to be rounded to the rupee, and
    the difference is not cosmetic: 8.33% of the ₹15,000 ceiling is ₹1,249.50,
    which is why every published EPF table says ₹1,250 EPS and ₹550 EPF rather
    than ₹1,249.50 and ₹550.50. Carrying the paise through would put a figure
    on the ECR that the portal does not accept and that no CA would recognise.

    Integer arithmetic throughout — CLAUDE.md's rule, and the reason this is not
    round(paise / 100) * 100.
    """
    return ((paise + 50) // 100) * 100


def _members_contributing_earlier_this_period(db, firm_id: str, client_id: str,
                                              month: str) -> set:
    """Employee ids who already contributed to ESI in this contribution period.

    ESI Rule 50's continuation only applies to someone who WAS covered when the
    period began — not to a new joiner who starts above the ceiling, who is
    simply outside the scheme. The distinction cannot be made from this month's
    wage, so it is made from the months already run.

    A failure here returns the empty set rather than raising: the run must still
    be computable, and the empty set is the conservative answer (nobody is kept
    in past the ceiling) rather than the one that over-deducts from people who
    were never covered.
    """
    try:
        period = esi_contribution_period(month)
        runs = (db.table("payroll_runs").select("id, month")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .execute().data) or []
        earlier = [r["id"] for r in runs
                   if r.get("month") and r["month"] < month
                   and esi_contribution_period(r["month"]) == period]
        if not earlier:
            return set()
        slips = (db.table("payroll_slips").select("employee_id, esi_employee_paise")
                 .in_("run_id", earlier).execute().data) or []
        return {s["employee_id"] for s in slips
                if int(s.get("esi_employee_paise") or 0) > 0}
    except Exception:
        _logger.exception("could not read ESI coverage history for %s %s", client_id, month)
        return set()


def _compute_pf(pf_wages_paise: int, fy: Optional[str] = None,
                eps_eligible: bool = True) -> dict:
    """
    PF per EPF & MP Act 1952 §6, SPLIT as the Employees' Pension Scheme requires.

    §6 sets the employee's contribution at 12% of "basic wages, dearness
    allowance and retaining allowance (if any)", and the employer matches it.
    The ₹15,000 ceiling applies to that same Basic+DA base, not Basic alone —
    task #229 fixed a caller that passed basic_paise only and silently
    under-computed both halves for anyone with a nonzero da_percent. No
    retaining allowance is modelled here (it is not on the employee master), so
    pf_wages_paise is Basic + DA.

    WHAT CHANGED, AND WHY IT MATTERS BEYOND THE LEDGER

    This used to return a flat {"employee": 12%, "employer": 12%}. The
    employee's 12% is indeed all EPF, but the EMPLOYER's 12% is not: EPS 1995 ¶3
    diverts 8.33% of PF wages — capped at 8.33% of ₹15,000, i.e. ₹1,250 — to the
    pension fund, and only the remainder stays in EPF. At or below the ceiling
    that is 8.33% pension + 3.67% provident fund; above it the pension amount
    stops rising and the EPF half absorbs the rest.

    Lumping the two together is not merely an imprecise trial balance. The
    EPFO's ECR return carries EPF wages, EPS wages, the EPF contribution, the
    EPS contribution and the difference between them as separate columns per
    member, so a single employer figure cannot produce a valid return at all.

    EDLI (0.5%, EDLI 1976) and administrative charges (0.5%) are returned too.
    Both are employer costs OUTSIDE the 12% and are deducted from nobody. The
    admin charge carries a minimum of ₹500 per ESTABLISHMENT per month, which no
    single payslip can settle — the per-employee 0.5% is computed here and the
    floor is applied when the run is totalled. EDLI admin has been nil since
    01-04-2017.

    Rates and ceilings come from domain/payroll/statutory.py, versioned by FY.
    """
    r = payroll_rates_for(fy).pf
    capped = min(pf_wages_paise, r.wage_ceiling_paise)

    # Employee's whole share is EPF.
    employee = _to_nearest_rupee(capped * r.employee_rate_bps // 10000)

    # Employer's share splits. EPS is computed on its OWN ceiling, which is why
    # it is not simply 8.33% of `capped` — the two ceilings are separate figures
    # in the statute even though both are ₹15,000 today.
    employer_total = _to_nearest_rupee(capped * r.employer_rate_bps // 10000)
    eps_wages = min(pf_wages_paise, r.eps_ceiling_paise)
    employer_eps = _to_nearest_rupee(eps_wages * r.eps_rate_bps // 10000)
    # Never let the pension half exceed the employer's total: if a future
    # notification moved the ceilings apart, the subtraction below must not go
    # negative and quietly credit EPF with a negative contribution.
    employer_eps = min(employer_eps, employer_total)
    # EPS 1995 para 6, as amended by GSR 609(E) w.e.f. 01-09-2014: someone who
    # joined EPF on or after that date with pay above the ceiling at JOINING is
    # not a pension-scheme member at all, and the whole employer share stays in
    # EPF. Carried on the employee master rather than derived — see migration
    # 295 for why pay-today cannot answer a question about pay-at-joining.
    if not eps_eligible:
        employer_eps = 0
    employer_epf = employer_total - employer_eps

    edli = _to_nearest_rupee(min(pf_wages_paise, r.edli_ceiling_paise) * r.edli_rate_bps // 10000)
    admin = _to_nearest_rupee(capped * r.admin_rate_bps // 10000)

    return {
        "employee": employee,
        # Kept so every existing caller and every stored slip keeps its meaning:
        # the employer's total 12%, which is what "pf_employer_paise" has always
        # held and what the GL credits in aggregate.
        "employer": employer_total,
        "employer_eps": employer_eps,
        "employer_epf": employer_epf,
        "edli": edli,
        "admin": admin,
    }


def _compute_esi(gross_paise: int, fy: Optional[str] = None,
                 covered_at_period_start: bool = False) -> dict:
    """
    ESI per ESI Act §2(9); rates from the notification of 13-06-2019.

    Employee 0.75% and employer 3.25% of gross. The ₹21,000 figure is an
    ELIGIBILITY threshold, not a cap — contribution is on the whole of a covered
    member's wages, with no ceiling on the amount.

    RULE 50: CROSSING THE CEILING DOES NOT END COVERAGE MID-PERIOD

    This used to return zero the moment gross exceeded ₹21,000 in any month.
    ESI Rule 50 says otherwise: contribution periods run April-September and
    October-March, and an employee whose wages rise above the ceiling PART WAY
    THROUGH a period remains an employee until that period ends. Someone on
    ₹20,500 in April raised to ₹24,000 in May contributes on the full ₹24,000
    every month to September, and leaves the scheme in October.

    Dropping them in May under-deducts the employee, under-pays the employer's
    share, and under-states the ESIC challan for five months — and it is the
    employer who is liable for the shortfall with interest, not the employee.

    `covered_at_period_start` is the caller's answer to "was this member
    contributing earlier in this same contribution period?", which only the
    payroll history knows. It defaults to False so a caller that has not been
    taught the rule behaves as before rather than silently over-deducting
    someone who was never covered.
    """
    r = payroll_rates_for(fy).esi
    if gross_paise > r.wage_ceiling_paise and not covered_at_period_start:
        return {"employee": 0, "employer": 0}
    employee = math.floor(gross_paise * r.employee_rate_bps / 10000)
    employer = math.floor(gross_paise * r.employer_rate_bps / 10000)
    return {"employee": employee, "employer": employer}


def _compute_slip(emp: dict, attendance: Optional[dict] = None, fy: Optional[str] = None,
                  esi_covered_at_period_start: bool = False,
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
    pf   = (_compute_pf(basic + da, fy, eps_eligible=emp.get("eps_eligible", True))
            if emp.get("pf_applicable")
            else {"employee": 0, "employer": 0, "employer_eps": 0,
                  "employer_epf": 0, "edli": 0, "admin": 0})
    esi  = (_compute_esi(gross, fy, covered_at_period_start=esi_covered_at_period_start)
            if emp.get("esi_applicable") else {"employee": 0, "employer": 0})
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
        # Stored, not recomputed at ECR time: the return must agree with the
        # ledger, and two implementations of one split drift. Migration 295.
        "pf_employer_eps_paise": pf["employer_eps"],
        "pf_employer_epf_paise": pf["employer_epf"],
        "edli_paise":            pf["edli"],
        "pf_admin_paise":        pf["admin"],
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
    active-only behaviour so existing dashboard/run callers are unaffected.

    The firm-wide branch is exactly why this needs narrowing rather than a bare
    check: an Executive assigned to two clients would otherwise get every
    employee in the firm, salary and PAN included, in one call."""
    if client_id:
        assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, [])
    q = db.table("payroll_employees").select("*").eq("firm_id", current_user["firm_id"])
    if not include_inactive:
        q = q.eq("status", "active")
    if client_id:
        q = q.eq("client_id", client_id)
    res = q.order("name").execute()
    rows = res.data or []
    if not client_id:
        rows = filter_by_client(current_user, rows)
    return api_response(True, rows)


@router.post("/employees")
def create_employee(
    data: EmployeeIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    assert_client_access(current_user, data.client_id)
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
    _assert_employee_scope(_db(), current_user, employee_id)
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
    _assert_employee_scope(_db(), current_user, employee_id)
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
    assert_client_access(current_user, client_id)
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
    assert_client_access(current_user, data.client_id)
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
    if client_id:
        assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, [])
    q = db.table("payroll_runs").select("*").eq("firm_id", current_user["firm_id"])
    if client_id:
        q = q.eq("client_id", client_id)
    res = q.order("month", desc=True).execute()
    rows = res.data or []
    if not client_id:
        rows = filter_by_client(current_user, rows)
    return api_response(True, rows)


@router.post("/runs")
def create_run(
    data: PayrollRunIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """
    Create a draft payroll run and compute slips for all active employees.
    Computation is deterministic from employee master + attendance.
    """
    assert_client_access(current_user, data.client_id)
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

    # ESI Rule 50: someone whose wages rise above the ceiling PART WAY THROUGH a
    # contribution period stays in the scheme until that period ends. Answering
    # that needs the payroll history, which _compute_slip cannot see — so it is
    # resolved once here, for the whole run, and passed in.
    #
    # "Was this member contributing earlier in THIS period?" is read off the
    # slips already posted for the same period rather than inferred from their
    # current wage, because the current wage is exactly the thing that changed.
    esi_covered_earlier = _members_contributing_earlier_this_period(
        db, current_user["firm_id"], client_id, month)

    # Statutory deductions this run did NOT compute because the state's rules are
    # not modelled. Collected per employee and returned with the run: a zero PT
    # for Delhi and a zero PT for Gujarat are the same number meaning opposite
    # things, and only one of them is a liability nobody has settled.
    statutory_gaps: list[str] = []

    for emp in emps:
        att_res = db.table("attendance").select("*").eq("employee_id", emp["id"]).eq("month", m).eq("year", y).execute()
        attendance = (att_res.data or [None])[0]

        slip = _compute_slip(emp, attendance, fy=fy, pt_month=m,
                             esi_covered_at_period_start=emp["id"] in esi_covered_earlier)
        statutory_gaps.extend(_statutory_gaps(emp))
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
    # Returned WITH the run rather than logged: an omitted statutory deduction
    # that only appears in a log is an omitted statutory deduction.
    return api_response(True, {**run, "statutory_gaps": statutory_gaps})


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
    _assert_run_scope(_db(), current_user, run_id)
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
    _assert_slip_scope(_db(), current_user, slip_id)
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
    _assert_run_scope(_db(), current_user, run_id)
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
    _assert_run_scope(_db(), current_user, run_id)
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
    _assert_run_scope(_db(), current_user, run_id)
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
    _assert_run_scope(_db(), current_user, run_id)
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
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, {"month": month, "slips": []})
    run = db.table("payroll_runs").select("id, status, total_gross_paise, total_net_paise, headcount").eq("firm_id", current_user["firm_id"]).eq("client_id", client_id).eq("month", month).execute()
    if not run.data:
        return api_response(True, {"month": month, "run": None, "slips": []})
    run_id = run.data[0]["id"]
    slips = db.table("payroll_slips").select("*, payroll_employees(name, pan, designation, department, bank_account_no, bank_ifsc)").eq("run_id", run_id).execute()
    return api_response(True, {"month": month, "run": run.data[0], "slips": slips.data or []})


@router.get("/runs/{run_id}/ecr")
def run_ecr(
    run_id: str,
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """Build the EPFO Electronic Challan cum Return for a finalised run.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    Returns the file's text for a human to download and upload at
    unifiedportal-emp.epfindia.gov.in. Nothing here transmits anything, and
    nothing is written.

    Every figure comes off the stored payslips. The split between EPS and EPF is
    read, never recomputed — a return that disagreed with the general ledger
    would be worse than no return, and two implementations of one statutory
    split drift the first time a ceiling moves.

    A run that is not yet finalised is refused rather than filed: the ECR is a
    return of contributions actually made, and a draft run's figures can still
    change. `problems` names every member the file cannot carry — no UAN, a
    ceiling breached, absent all month yet contributing — so they are fixed
    before the upload rather than after the portal rejects the batch.
    """
    db = _db()
    if not db:
        return api_response(True, {"run_id": run_id, "lines": "", "members": [],
                                   "problems": [], "totals": {}, "filable": False})
    _assert_run_scope(db, current_user, run_id)

    run = (db.table("payroll_runs").select("*").eq("id", run_id)
           .eq("firm_id", current_user["firm_id"]).maybe_single().execute().data)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.get("status") not in ("finalized", "paid"):
        raise HTTPException(
            status_code=409,
            detail="This run is not finalised yet. The ECR reports contributions "
                   "actually made, and a draft run's figures can still change.")

    slips = (db.table("payroll_slips").select("*")
             .eq("run_id", run_id).execute().data) or []
    emp_ids = [s.get("employee_id") for s in slips if s.get("employee_id")]
    employees = []
    if emp_ids:
        employees = (db.table("payroll_employees")
                     .select("id, name, uan, pf_applicable, eps_eligible")
                     .eq("firm_id", current_user["firm_id"])
                     .in_("id", emp_ids).execute().data) or []
    by_id = {e["id"]: e for e in employees}

    month = str(run.get("month") or "")
    try:
        y, m = int(month[:4]), int(month[5:7])
        days_in_month = calendar.monthrange(y, m)[1]
    except (ValueError, IndexError):
        # An unparseable month must not silently become 31 and let a bad NCP
        # figure through the day-count check.
        raise HTTPException(status_code=422,
                            detail=f"Run month {month!r} is not YYYY-MM; cannot bound NCP days.")

    ceiling = payroll_rates_for(_fy_for_month(month)).pf.wage_ceiling_paise
    ecr = build_ecr(slips=slips, employees_by_id=by_id,
                    days_in_month=days_in_month, wage_ceiling_paise=ceiling)

    return api_response(True, {
        "run_id": run_id,
        "month": month,
        "filename": f"ECR_{month.replace('-', '')}.txt",
        "lines": ecr.to_text(),
        "members": [m.to_line() for m in ecr.members],
        "problems": ecr.problems,
        "totals": ecr.totals(),
        "filable": ecr.is_filable,
        "disclaimer": "CA REVIEW REQUIRED — upload this to the EPFO portal yourself. "
                      "Nothing has been transmitted.",
    })


@router.get("/runs/{run_id}/esic")
def run_esic(
    run_id: str,
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """Build the ESIC monthly contribution return for a finalised run.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    Returns CSV for a human to upload at esic.gov.in. Nothing transmits.

    A member with no wages this month comes back as a PROBLEM rather than a row:
    ESIC wants a reason code and, for some reasons, a last working day, and this
    system does not record why somebody was unpaid. Guessing would be a false
    statement about their service on a filed return. See domain/payroll/esic.py.
    """
    db = _db()
    if not db:
        return api_response(True, {"run_id": run_id, "csv": "", "problems": [],
                                   "totals": {}, "filable": False})
    _assert_run_scope(db, current_user, run_id)

    run = (db.table("payroll_runs").select("*").eq("id", run_id)
           .eq("firm_id", current_user["firm_id"]).maybe_single().execute().data)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.get("status") not in ("finalized", "paid"):
        raise HTTPException(
            status_code=409,
            detail="This run is not finalised yet. The return reports contributions "
                   "actually made, and a draft run's figures can still change.")

    slips = (db.table("payroll_slips").select("*")
             .eq("run_id", run_id).execute().data) or []
    emp_ids = [s.get("employee_id") for s in slips if s.get("employee_id")]
    employees = []
    if emp_ids:
        employees = (db.table("payroll_employees")
                     .select("id, name, esi_number, esi_applicable")
                     .eq("firm_id", current_user["firm_id"])
                     .in_("id", emp_ids).execute().data) or []
    by_id = {e["id"]: e for e in employees}

    month = str(run.get("month") or "")
    try:
        y, m = int(month[:4]), int(month[5:7])
        days_in_month = calendar.monthrange(y, m)[1]
    except (ValueError, IndexError):
        raise HTTPException(status_code=422,
                            detail=f"Run month {month!r} is not YYYY-MM; cannot count days.")

    ret = build_esic_return(slips=slips, employees_by_id=by_id,
                            days_in_month=days_in_month)
    return api_response(True, {
        "run_id": run_id,
        "month": month,
        "contribution_period": esi_contribution_period(month),
        "filename": f"ESIC_{month.replace('-', '')}.csv",
        "csv": ret.to_csv(),
        "problems": ret.problems,
        "totals": ret.totals(),
        "filable": ret.is_filable,
        "disclaimer": "CA REVIEW REQUIRED — upload this to the ESIC portal yourself. "
                      "Nothing has been transmitted.",
    })


@router.get("/24q-source")
def form_24q_from_payroll(
    client_id: str = Query(...),
    financial_year: str = Query(..., description='e.g. "2026-27"'),
    quarter: str = Query(..., description="Q1 | Q2 | Q3 | Q4"),
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """Assemble Form 24Q's deductee rows from finalised payroll.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT

    Until now routers/tds.py's compute_24q took every deductee from the request
    body, so a CA who had just run payroll re-keyed each employee's name, PAN,
    gross and tax by hand for all three months. Beyond the labour, that is where
    the return stops agreeing with the books — and the mismatch surfaces as a
    TRACES default months later.

    Nothing here computes tax. The TDS is what payroll deducted and what the
    ledger was credited; this only puts it in the shape 24Q wants.
    """
    assert_client_access(current_user, client_id)
    if quarter not in QUARTER_MONTHS:
        raise HTTPException(status_code=422, detail=f"Quarter must be one of {sorted(QUARTER_MONTHS)}.")

    db = _db()
    if not db:
        return api_response(True, {"financial_year": financial_year, "quarter": quarter,
                                   "deductees": [], "problems": [], "totals": {},
                                   "ready": False})

    months = months_in_quarter(financial_year, quarter)
    runs = (db.table("payroll_runs")
            .select("id, month, status")
            .eq("firm_id", current_user["firm_id"]).eq("client_id", client_id)
            .in_("month", months).execute().data) or []
    # Only finalised runs: a draft's figures can still change, and a return
    # built on them would be filed against numbers that later moved.
    usable = [r for r in runs if r.get("status") in ("finalized", "paid")]
    draft_months = sorted(r["month"] for r in runs if r not in usable)

    slips_by_month: dict = {}
    emp_ids: set = set()
    for run in usable:
        rows = (db.table("payroll_slips").select("*")
                .eq("run_id", run["id"]).execute().data) or []
        slips_by_month.setdefault(run["month"], []).extend(rows)
        emp_ids |= {r.get("employee_id") for r in rows if r.get("employee_id")}

    employees = []
    if emp_ids:
        employees = (db.table("payroll_employees").select("id, name, pan")
                     .eq("firm_id", current_user["firm_id"])
                     .in_("id", list(emp_ids)).execute().data) or []

    challans = (db.table("tds_challans")
                .select("challan_no, bsr_code, payment_date, section, tds_paise")
                .eq("firm_id", current_user["firm_id"]).eq("client_id", client_id)
                .eq("financial_year", financial_year).eq("quarter", quarter)
                .execute().data) or []

    src = build_24q_from_payroll(
        slips_by_month=slips_by_month,
        employees_by_id={e["id"]: e for e in employees},
        challans=challans,
        record_cls=TDSDeducteeRecord,
    )
    if draft_months:
        src.problems.append(
            "Payroll for " + ", ".join(draft_months) + " is not finalised, so it is "
            "not in this return. Finalise those runs first, or the quarter will be "
            "short.")

    return api_response(True, {
        "client_id": client_id,
        "financial_year": financial_year,
        "quarter": quarter,
        "months": months,
        "deductees": [d.__dict__ for d in src.deductees],
        "challans": src.challans,
        "problems": src.problems,
        "employees_with_nil_tds": src.employees_with_nil_tds,
        "totals": src.totals(),
        "ready": src.is_ready,
        "disclaimer": "CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Review every row, "
                      "then file on TRACES yourself.",
    })


@router.get("/24q-annexure-ii")
def form_24q_annexure_ii(
    client_id: str = Query(...),
    financial_year: str = Query(..., description='e.g. "2026-27"'),
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """The annual salary detail that TRACES turns into Form 16 Part B.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT

    THERE IS NO FORM 16 GENERATOR HERE, AND THERE SHOULD NOT BE. CBDT
    Notification 09/2019 requires Part B of the salary TDS certificate to be
    DOWNLOADED FROM TRACES for every deduction on or after 01-04-2018; Part A
    had been TRACES-only for years. An employer who prints their own Form 16 has
    issued nothing.

    TRACES builds Part B from one input — Annexure II of the Q4 24Q return, in
    the format Notification 36/2019 substituted. So this is the thing that
    actually produces Form 16, and it is what payroll can honestly supply.

    `gaps` names what payroll cannot know and the employee holds: §17(2)
    perquisites, exemptions under §10, Chapter VI-A. They do not block — an
    annexure with no Chapter VI-A is correct for someone who declared none — but
    they are stated rather than left as silent zeroes.
    """
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, {"financial_year": financial_year, "rows": [],
                                   "problems": [], "gaps": [], "totals": {},
                                   "ready": False})

    months = [m for q in ("Q1", "Q2", "Q3", "Q4")
              for m in months_in_quarter(financial_year, q)]
    runs = (db.table("payroll_runs").select("id, month, status")
            .eq("firm_id", current_user["firm_id"]).eq("client_id", client_id)
            .in_("month", months).execute().data) or []
    usable = [r for r in runs if r.get("status") in ("finalized", "paid")]

    slips: list = []
    emp_ids: set = set()
    for run in usable:
        rows = (db.table("payroll_slips").select("*")
                .eq("run_id", run["id"]).execute().data) or []
        slips.extend(rows)
        emp_ids |= {r.get("employee_id") for r in rows if r.get("employee_id")}

    employees = []
    if emp_ids:
        employees = (db.table("payroll_employees").select("id, name, pan")
                     .eq("firm_id", current_user["firm_id"])
                     .in_("id", list(emp_ids)).execute().data) or []

    rates = rates_for(financial_year)
    ann = build_annexure_ii(
        slips=slips,
        employees_by_id={e["id"]: e for e in employees},
        standard_deduction_paise=rates.new_regime_standard_deduction_paise,
        months_expected=len(usable) or 12,
    )
    missing_months = sorted(set(months) - {r["month"] for r in usable})
    if missing_months:
        ann.gaps.append(
            "No finalised payroll for " + ", ".join(missing_months) + ". Annexure II "
            "covers the whole year, so any month missing here is salary the "
            "certificate will not show.")

    return api_response(True, {
        "client_id": client_id,
        "financial_year": financial_year,
        "rows": [{**r.__dict__,
                  "gross_salary_paise": r.gross_salary_paise,
                  "net_salary_paise": r.net_salary_paise,
                  "income_under_salaries_paise": r.income_under_salaries_paise}
                 for r in ann.rows],
        "problems": ann.problems,
        "gaps": ann.gaps,
        "totals": ann.totals(),
        "ready": ann.is_ready,
        "form_16_note": "Form 16 itself is downloaded from TRACES after this Annexure "
                        "II is filed with Q4 — CBDT Notification 09/2019. Nothing here "
                        "issues a certificate.",
        "disclaimer": "CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.",
    })


@router.get("/reports/statutory-summary")
def statutory_summary(
    client_id: str = Query(...),
    month: str = Query(...),
    current_user: dict = Depends(rbac("payroll", "read"))
):
    assert_client_access(current_user, client_id)
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


# ─── Employee portal provisioning ────────────────────────────────────────────
# Migration 262 made the employee portal readable; migration 264 + these three
# endpoints are what actually links an employee to a login. Guarded by
# rbac("payroll", "write") — Manager and up, the same tier that edits salaries,
# because handing someone access to salary data is a payroll decision.

class EmployeePortalInviteIn(BaseModel):
    email: EmailStr


@router.post("/employees/{employee_id}/portal-invite")
def invite_employee_portal(
    employee_id: str,
    data: EmployeePortalInviteIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """Issue a single-use activation link for one employee.

    The plaintext token is returned ONCE, here — only its sha256 is stored — so
    the caller can deliver the link if the email does not arrive. It is not
    retrievable afterwards; re-inviting mints a new one and invalidates this.
    """
    _assert_employee_scope(_db(), current_user, employee_id)
    result = employee_portal_service.invite_employee(
        current_user["firm_id"], employee_id, str(data.email), actor=current_user)
    return api_response(True, result)


@router.post("/employees/{employee_id}/portal-revoke")
def revoke_employee_portal(
    employee_id: str,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """Withdraw portal access. Clears the identity binding as well as the flag,
    so re-enabling later cannot silently restore an ex-employee's access."""
    _assert_employee_scope(_db(), current_user, employee_id)
    return api_response(True, employee_portal_service.revoke_employee_portal(
        current_user["firm_id"], employee_id, actor=current_user))


@router.get("/employees/{employee_id}/portal-status")
def employee_portal_status(
    employee_id: str,
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """Whether this employee has been invited / activated. Never returns the
    token hash."""
    _assert_employee_scope(_db(), current_user, employee_id)
    return api_response(True, employee_portal_service.portal_status(
        current_user["firm_id"], employee_id, actor=current_user))
