"""
Payroll router — Employee master, salary structures, payroll runs, statutory, reports.

IT Act §192: TDS on salary (monthly deduction, annual projected basis).
EPF Act §6: Employer PF = 12% of (Basic + DA), capped at a ₹15,000 wage ceiling → ₹1,800 max employer contribution.
ESI Act: Employee ESI = 0.75% of gross; Employer ESI = 3.25% of gross (applicable when gross ≤ ₹21,000/month).
PT: State-specific professional tax slab, keyed on the employee's pt_state; an
    unset/unrecognised state withholds nothing (no silent single-state default).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Annotated, Optional
from datetime import datetime, timezone, date
from decimal import Decimal as _Decimal, ROUND_HALF_UP as _ROUND_HALF_UP
import math

from pydantic import BaseModel, EmailStr

import logging

from models.common import api_response
from models.payroll import (EmployeeIn, EmployeeUpdateIn, SalaryStructureIn, PayrollRunIn,
                           RunStatusIn, PayrollDisburseIn, DeclarationIn, DeclarationVerifyIn,
                           StatutoryIdentityIn, PTRegistrationIn,
                           AttendanceIn, PayrollSettingsIn, PTSlabSetIn,
                           OneTimeEarningsIn, PayrollEnablementIn,
                           ReleaseIn, ApplyStructureIn)
from core.authz import assert_client_access, filter_by_client
from core.ist_clock import ist_today, month_end_date
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
from domain.payroll import identity as identity_domain
from domain.payroll import attendance as attendance_domain
from domain.payroll import firm_rates
from domain.payroll import salary_structure as structure_domain
from domain.payroll import professional_tax as pt_domain
from domain.payroll.form24q import (
    build_24q_from_payroll, months_in_quarter, QUARTER_MONTHS)
from domain.tds.tds_computer import TDSDeducteeRecord
from domain.payroll.statutory import esi_contribution_period
from domain.payroll.statutory import rates_for as payroll_rates_for
from domain.payroll.statutory import admin_charge_for_establishment as payroll_admin_charge
from domain.payroll import declarations as decl_domain
from domain.payroll import gratuity as gratuity_domain
from domain.payroll import bonus as bonus_domain
from domain.payroll import leave_encashment as leave_domain
from domain.payroll import settlement as settlement_domain
from domain.payroll import arrears as arrears_domain
from domain.payroll import one_time_earnings as one_time_domain
from domain.payroll import perquisites as perq_domain
from dataclasses import replace as _replace


# Every "read failed, carry on with the safe default" branch below logs through
# this. It was referenced in five of them and never defined, so the first real
# read failure would have raised NameError from inside the except — turning a
# graceful degradation into a 500, and only ever on the day something was
# already going wrong. The `caflow.` prefix matches the rest of the app's
# logging (CLAUDE.md notes the prefix is legacy naming and stays).
_logger = logging.getLogger("caflow.payroll")


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
from models.fy import FYLabel

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


#: The states whose slabs are in this file, verified against the state Act and
#: pinned by tests. For these the code wins over anything a firm records — see
#: firm_rates.slabs_recorded_against_a_modelled_state for why the disagreement
#: is reported rather than resolved either way in silence.
_PT_MODELLED_STATES = pt_domain.MODELLED_STATES


def _compute_pt(gross_paise: int, state: Optional[str] = None,
                month: Optional[int] = None, gender: Optional[str] = None,
                firm_slabs: Optional[list[dict]] = None,
                on: Optional[date] = None) -> int:
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
    if code in _PT_SLABS_BY_STATE:
        return _slab_lookup(_PT_SLABS_BY_STATE[code], gross_paise)

    # Not modelled here. The firm's own reading of the state notification, if it
    # has recorded one and it covers every wage (migration 327). Anything less
    # stays 0 AND stays a reported gap — firm_rates returns usable=False, and
    # _statutory_gaps names the state — so this is never a silent fall-back.
    if firm_slabs and on is not None:
        result = firm_rates.professional_tax(
            firm_slabs, gross_paise=gross_paise, month=month, on=on, state=code)
        if result.usable:
            return result.employee_paise
    return 0


def _attendance_gap(emp: dict, attendance_entered: bool) -> list[str]:
    """The gap when NOBODY entered attendance for this employee this month.

    _compute_slip defaults working_days and days_present to 26 and lop_days to
    0, and public.attendance's own columns default the same way (migration
    027). So a client who has sent nothing produces a run that pays every
    employee a full month — and the slip, and the payslip PDF that prints
    "Working Days 26 / Days Present 26", assert as fact something nobody
    established.

    The same shape as _statutory_gaps and for the same reason: a zero LOP
    because a human confirmed full attendance and a zero LOP because nobody
    said anything are the same number meaning opposite things.

    WARNS RATHER THAN BLOCKS, matching statutory_gaps exactly. A run is a DRAFT
    — nothing is posted, nothing is paid, no journal exists until Finalize —
    so refusing to compute it would stop a CA seeing the very figures that tell
    them what is missing. Inventing a second convention for a second kind of
    gap is how a screen ends up with two ideas of what "incomplete" means.
    """
    if attendance_entered:
        return []
    who = emp.get("name") or emp.get("id") or "employee"
    return [f"{who}: no attendance entered for this month — paid a full month "
            f"on the 26-day default. Enter it, or confirm the default is right."]


def _statutory_gaps(emp: dict, pt_covered: Optional[set] = None) -> list[str]:
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
        state = (emp.get("pt_state") or "").strip().upper()
        pt = classify_pt_state(emp.get("pt_state"))
        # A state the FIRM has recorded usable slabs for is no longer a gap —
        # the deduction was computed, from a notification somebody read
        # (migration 327). Covered is decided once per run, because whether a
        # recorded set is usable depends on the payroll month's date and on the
        # bands covering every wage, not merely on rows existing.
        if pt.is_gap and state not in (pt_covered or set()):
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


def _months_employed_in_fy(joining_date, fy: Optional[str]) -> int:
    """How many months of THIS financial year this employee is paid for.

    §192(1) requires TDS on "the estimated income of the assessee under the head
    Salaries" FOR THAT FINANCIAL YEAR. For someone who joined on 1 October that
    estimate is six months of salary, not twelve — and projecting twelve
    over-deducts severely, because the excess cannot be recovered through §192(3)
    (the projection itself is what is wrong) and is refundable only on
    assessment, a year later.

    Measured at ₹1,00,000 a month: an October joiner earning ₹6,00,000 in the
    year owes nothing after the §16(ia) deduction and the §87A rebate, and a
    twelve-month projection withholds ₹1,46,250 from them.

    An unknown joining date returns 12. That is the pre-existing behaviour and
    the safe direction — §192(1) makes the EMPLOYER liable for an under-
    deduction — but it is also why the joining date is worth capturing: with it,
    the employee keeps their money.
    """
    if not joining_date or not fy:
        return 12
    try:
        joined = date.fromisoformat(str(joining_date)[:10])
        fy_start_year = int(str(fy)[:4])
    except (ValueError, TypeError):
        return 12
    fy_start = date(fy_start_year, 4, 1)
    if joined <= fy_start:
        return 12            # employed for the whole year
    if joined >= date(fy_start_year + 1, 4, 1):
        return 0             # joins after this year ends
    # Inclusive count of the months from the joining month to March.
    return 12 - ((joined.year - fy_start_year) * 12 + joined.month - 4)


def _salary_in_force(db, firm_id: str, client_id: str, month: str) -> dict:
    """{employee_id: the component set to pay them this month}.

    An employee's pay lives on payroll_employees as one current value.
    payroll_salary_revisions (migration 300) records what it was and from when,
    so a month uses the LATEST revision effective on or before that month's
    first day — which is what makes a revision enterable in advance, and a
    backdated one recoverable as arrears.

    An employee with no revision is absent from the result and the caller falls
    back to the master. That is deliberate rather than a backfill: inventing an
    effective date for the pay someone happens to be on today would put a fact
    in the record that nobody established.

    Empty on failure, which pays everyone their current master rate — the
    behaviour before revisions existed, and never a stopped payroll.
    """
    try:
        first_of_month = f"{month}-01"
        # Columns named rather than "*", so every one of them is checked against
        # the real schema by tests/test_backend_columns_exist_pg.py — the insert
        # that writes them takes a list variable, which that scanner cannot read.
        rows = (db.table("payroll_salary_revisions")
                .select("employee_id, effective_from, basic_paise, hra_percent, "
                        "da_percent, lta_paise, medical_paise, "
                        "special_allowance_paise, other_allowances_paise, "
                        "reason, source_structure_id")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .execute().data) or []
        latest: dict = {}
        for r in rows:
            # Compared here rather than in the query: the row count is bounded
            # by headcount times revisions, which is small, and an inequality
            # filter is not part of the query surface the in-memory source
            # implements. ISO dates compare correctly as strings.
            if str(r.get("effective_from") or "") > first_of_month:
                continue
            emp = r.get("employee_id")
            best = latest.get(emp)
            if best is None or str(r.get("effective_from")) > str(best.get("effective_from")):
                latest[emp] = r
        return latest
    except Exception:
        _logger.exception("could not read salary revisions for %s %s", client_id, month)
        return {}


def _loan_instalments_for_run(db, firm_id: str, client_id: str) -> dict:
    """{employee_id: instalment to recover this month}, capped at what is owed.

    An instalment larger than the balance would over-recover, which is the
    employer taking money they are not owed. Closed loans are excluded by the
    query, not filtered afterwards, so a settled loan cannot come back.

    Empty on failure — recovering nothing is recoverable next month; recovering
    twice is not.
    """
    try:
        rows = (db.table("payroll_loans").select("*")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .is_("closed_on", "null").execute().data) or []
        out: dict = {}
        for r in rows:
            owed = int(r.get("outstanding_paise") or 0)
            due = min(int(r.get("monthly_instalment_paise") or 0), max(0, owed))
            if due > 0:
                emp = r.get("employee_id")
                out[emp] = out.get(emp, 0) + due
        return out
    except Exception:
        _logger.exception("could not read employee loans for %s", client_id)
        return {}


def _apply_loan_recoveries(db, firm_id: str, client_id: str, run_id: str) -> int:
    """Reduce each loan's outstanding balance by what this run recovered.

    Done at FINALISATION and nowhere else. A draft run can be deleted and
    recomputed, so reducing a balance when the slips are first computed would
    let one recovery be applied twice — and the second application would look
    exactly like the first. Finalisation is guarded against running twice
    (status is checked and set), so this runs once per run.

    A loan whose balance reaches zero is closed, so it stops being read at all
    next month rather than being filtered out every time.

    Returns how many loans were touched. Never raises: the run's journal has
    already posted by the time this is called, and refusing to finalise a
    correct payroll because a balance could not be written down would be the
    worse failure. A missed write-down leaves the balance too high, which is
    visible on the next payslip and on the loan list.
    """
    try:
        recovered = {}
        for sl in ((db.table("payroll_slips").select("employee_id, loan_recovery_paise")
                    .eq("run_id", run_id).execute().data) or []):
            amount = int(sl.get("loan_recovery_paise") or 0)
            if amount:
                recovered[sl["employee_id"]] = recovered.get(sl["employee_id"], 0) + amount
        if not recovered:
            return 0

        loans = (db.table("payroll_loans").select("*")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .is_("closed_on", "null").execute().data) or []
        touched = 0
        for loan in loans:
            left = recovered.get(loan.get("employee_id"), 0)
            if left <= 0:
                continue
            owed = int(loan.get("outstanding_paise") or 0)
            # Oldest-first is not modelled; where an employee has two loans the
            # recovery is applied in the order the rows come back, and the
            # instalments were summed the same way when it was computed.
            applied = min(left, owed)
            recovered[loan["employee_id"]] = left - applied
            new_balance = owed - applied
            db.table("payroll_loans").update({
                "outstanding_paise": new_balance,
                "closed_on": (str(date.today()) if new_balance == 0 else None),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", loan["id"]).execute()
            touched += 1
        return touched
    except Exception:
        _logger.exception("could not apply loan recoveries for run %s", run_id)
        return 0


def _declarations_for_run(db, firm_id: str, client_id: str,
                          fy: str) -> dict:
    """Every employee's §192 declaration for this financial year, by employee id.

    One query for the run rather than one per employee: the answer is bounded by
    headcount, not by transaction volume, and the alternative is N round trips
    to Mumbai from a service in Singapore (CLAUDE.md, "Reporting performance").

    A failure returns {} — no declarations, so everyone is withheld on the
    §115BAC(1A) default with only the standard deduction. That is the safe
    direction: it is what payroll did before declarations existed, and it
    over-deducts rather than under-deducts. An exception here must never stop a
    month's payroll running.
    """
    try:
        heads = (db.table("payroll_it_declarations").select("*")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .eq("fy", fy).execute().data) or []
        if not heads:
            return {}
        items = (db.table("payroll_it_declaration_items").select("*")
                 .in_("declaration_id", [h["id"] for h in heads])
                 .execute().data) or []
        by_decl: dict = {}
        for it in items:
            by_decl.setdefault(it.get("declaration_id"), []).append(it)
        out: dict = {}
        for h in heads:
            # A draft is the employee still typing. It has no effect on payroll
            # until they submit it — withholding on a half-filled form would be
            # worse than withholding on the default.
            if h.get("status") == decl_domain.STATUS_DRAFT:
                continue
            out[h["employee_id"]] = _declaration_from_rows(h, by_decl.get(h["id"], []))
        return out
    except Exception:
        _logger.exception("could not read IT declarations for %s %s", client_id, fy)
        return {}


def _declaration_from_rows(head: dict, item_rows: list) -> "decl_domain.Declaration":
    """Map the two tables onto the domain object. Kept in one place so the
    endpoint and the payroll run cannot disagree about what a stored
    declaration means."""
    d = decl_domain.Declaration(
        employee_id=str(head.get("employee_id") or ""),
        fy=str(head.get("fy") or ""),
        regime=head.get("regime") or decl_domain.REGIME_NEW,
        status=head.get("status") or decl_domain.STATUS_DRAFT,
        rent_paid_declared_paise=int(head.get("rent_paid_declared_paise") or 0),
        rent_paid_verified_paise=int(head.get("rent_paid_verified_paise") or 0),
        landlord_name=head.get("landlord_name") or "",
        landlord_address=head.get("landlord_address") or "",
        landlord_pan=head.get("landlord_pan") or "",
        rent_is_metro=bool(head.get("rent_is_metro")),
        lta_declared_paise=int(head.get("lta_declared_paise") or 0),
        lta_verified_paise=int(head.get("lta_verified_paise") or 0),
        home_loan_interest_declared_paise=int(head.get("home_loan_interest_declared_paise") or 0),
        home_loan_interest_verified_paise=int(head.get("home_loan_interest_verified_paise") or 0),
        lender_name=head.get("lender_name") or "",
        lender_pan=head.get("lender_pan") or "",
        other_income_declared_paise=int(head.get("other_income_declared_paise") or 0),
        house_property_loss_declared_paise=int(head.get("house_property_loss_declared_paise") or 0),
        proofs_verified=bool(head.get("proofs_verified")),
    )
    for r in item_rows:
        d.items.append(decl_domain.DeclarationItem(
            section=r.get("section") or "",
            label=r.get("label") or "",
            amount_declared_paise=int(r.get("amount_declared_paise") or 0),
            amount_verified_paise=int(r.get("amount_verified_paise") or 0),
            status=r.get("status") or decl_domain.ITEM_DECLARED,
            proof_reference=r.get("proof_reference") or "",
        ))
    return d


def _tds_already_deducted_this_fy(db, firm_id: str, client_id: str,
                                  month: str, fy: str) -> dict:
    """TDS withheld so far this financial year, per employee.

    Returns {employee_id: (tds_paise, months_paid, gross_paise)}. §192(3) adjusts "any excess
    or deficiency arising out of any PREVIOUS deduction ... during the financial
    year", so the adjustment needs both halves: what was actually deducted in the
    FY's earlier months, and how many months those were. Not earlier years, and
    not this month, which is the one being computed.

    Empty on failure, which makes the month's tax the full annual figure spread
    over the remaining months. That over-deducts rather than under-deducts, and
    the employer's liability under §192(1) runs the other way.
    """
    try:
        runs = (db.table("payroll_runs").select("id, month")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .execute().data) or []
        earlier = [r["id"] for r in runs
                   if r.get("month") and r["month"] < month
                   and _fy_for_month(r["month"]) == fy]
        if not earlier:
            return {}
        # gross_paise IS SELECTED. It was not, and the accumulator two lines
        # below has always read `sl.get("gross_paise")` — which on a row that
        # never carried the column is None, so every month's
        # gross_already_paid_paise was zero. The §192 projection then estimated
        # the year as `gross * months_left` alone: a run for October with six
        # months already paid projected six months of income instead of twelve
        # and withheld tax at a slab the employee is not in. It fails in the
        # employee's favour and in the deductor's disfavour, which is why
        # nothing surfaced it — §192(1) makes the EMPLOYER liable for the
        # shortfall, and §201(1A) charges interest on it at 1% a month.
        #
        # PostgREST returns exactly the columns named, so a select list is a
        # contract with the code that reads the rows. This one was a select list
        # narrowed for performance while a reader of the dropped column stayed
        # behind. tests/test_backend_columns_exist_pg.py checks that a named
        # column EXISTS, not that every column read is named — the reverse
        # direction, which is why it stayed green.
        slips = (db.table("payroll_slips").select("employee_id, tds_paise, gross_paise")
                 .in_("run_id", earlier).execute().data) or []
        out: dict = {}
        for sl in slips:
            tds, months, gross = out.get(sl["employee_id"], (0, 0, 0))
            out[sl["employee_id"]] = (tds + int(sl.get("tds_paise") or 0),
                                      months + 1,
                                      gross + int(sl.get("gross_paise") or 0))
        return out
    except Exception:
        _logger.exception("could not read YTD TDS for %s %s", client_id, month)
        return {}


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


def _percent_of(base_paise: int, percent) -> int:
    """A percentage of a paise amount, half-rounded up, in exact decimal.

    Module level rather than nested in _compute_slip because the statutory
    summary derives HRA and DA the same way, and two derivations of one
    percentage drift. Decimal, not float: `float(hra_percent)` produced verified
    off-by-one-paise mismatches against exact arithmetic.
    """
    pct = _Decimal(str(percent or 0))
    return int((_Decimal(base_paise) * pct / 100).quantize(
        _Decimal("1"), rounding=_ROUND_HALF_UP))


def _compute_slip(emp: dict, attendance: Optional[dict] = None, fy: Optional[str] = None,
                  esi_covered_at_period_start: bool = False,
                  pt_month: Optional[int] = None,
                  declaration: Optional["decl_domain.Declaration"] = None,
                  tds_already_deducted_paise: int = 0,
                  months_already_paid: int = 0,
                  loan_instalment_paise: int = 0,
                  gross_already_paid_paise: int = 0,
                  months_employed_in_fy: int = 12,
                  firm_pt_slabs: Optional[list[dict]] = None,
                  pt_on: Optional[date] = None,
                  one_time: Optional["one_time_domain.Bundle"] = None) -> dict:
    """
    Compute a single payroll slip in integer paise. No floating point on final values.
    IT Act Section 192: TDS on salary — simplified monthly deduction (annual
    projected / 12). `fy` should be the financial year the payroll month
    falls in (see current_fy()) so a retroactively-run payroll for an earlier
    FY doesn't pick up a later year's rates; defaults to today's FY if omitted.
    `pt_month` is the calendar month (1-12) of the payroll run — required for the
    states whose Professional Tax depends on the month (Maharashtra's February
    differential, Tamil Nadu's Sep/Mar half-yearly deduction).

    `firm_pt_slabs` are the slabs THIS FIRM recorded off a state notification
    (migration 327), used only for states this file does not model, and only
    where they cover every wage. `pt_on` is the payroll month's end date, which
    picks the version in force — a run for an earlier month must compute at the
    figures that applied to it. Both are loaded once per run, not per employee.

    `one_time` is this employee's one-time and variable earnings for the month
    (migration 331) — incentive, bonus, ex-gratia, arrears — already summed into
    the four bases they feed. It is NOT prorated by attendance and it does NOT
    recur in the §192 projection; both of those are the point of the type. See
    domain/payroll/one_time_earnings.py.
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

    # One-time and variable earnings (migration 331). Added to gross AFTER the
    # proration and deliberately outside _prorate: every component above is a
    # MONTHLY RATE, and a rate earned over 22 of 26 days is worth 22/26 of
    # itself. A bonus is not a rate — it is a decided figure — and scaling a
    # decided figure by attendance pays somebody a fraction of an amount that
    # was never per-day.
    ot = one_time or one_time_domain.EMPTY
    recurring = basic + hra + da + lta + medical + special + other
    gross     = recurring + ot.total_paise

    # EPF Act §6: PF wages = Basic + DA (task #229 — basic alone under-computed PF).
    # Plus whichever one-time earnings the CA recorded AS PF wages, which under
    # EPF Act §2(b) is in practice arrears of basic and DA and nothing else: the
    # section excludes "any bonus, commission or any other similar allowance"
    # from basic wages, so an incentive or a festival bonus does not belong here
    # however large it is.
    pf_wages = basic + da + ot.pf_wages_paise
    pf   = (_compute_pf(pf_wages, fy, eps_eligible=emp.get("eps_eligible", True))
            if emp.get("pf_applicable")
            else {"employee": 0, "employer": 0, "employer_eps": 0,
                  "employer_epf": 0, "edli": 0, "admin": 0})
    # ESI Act §2(22) includes additional remuneration "paid at intervals not
    # exceeding two months", so the ESI wage base takes only the one-time
    # earnings that pass that INTERVAL test — a monthly incentive does, an
    # annual bonus does not. It matters twice over, because this same figure is
    # what the ₹21,000 coverage ceiling is tested against: folding a bonus in
    # here would throw an employee out of ESI for a month on money the Act says
    # is not their wages.
    esi_wages = recurring + ot.esi_wages_paise
    esi  = (_compute_esi(esi_wages, fy, covered_at_period_start=esi_covered_at_period_start)
            if emp.get("esi_applicable") else {"employee": 0, "employer": 0})
    # Professional tax is on the whole of what is earned in the month. The state
    # Acts levy on "salary or wage" without the exclusions the EPF and ESI Acts
    # carry, so gross here is gross — one-time earnings included.
    pt   = _compute_pt(gross, emp.get("pt_state"), month=pt_month, gender=emp.get("gender"),
                       firm_slabs=firm_pt_slabs, on=pt_on) if emp.get("pt_applicable") else 0

    # IT Act §192: TDS on salary, on the year's PROJECTED income. What the
    # employee declared decides the regime and the deductions; §192(3) decides
    # how the resulting annual figure is spread over what is left of the year.
    # The year's ESTIMATED salary, not twelve times this month's. What has
    # already been paid this year is a fact; the rest of the year is this
    # month's pay times the months still to come — which for a mid-year joiner
    # is fewer than twelve, and for a mid-year RAISE picks the new rate up for
    # the remaining months without rewriting the ones already paid.
    months_left = max(0, months_employed_in_fy - max(0, months_already_paid))
    # THE ONE-TIME AMOUNT IS ADDED ONCE, NOT PROJECTED. `gross * months_left`
    # is right for a monthly rate and catastrophic for a decided figure: a
    # ₹50,000 Diwali bonus paid in April would be multiplied by the twelve
    # months still to come and the projection would withhold tax on ₹6 lakh of
    # income the employee will never receive.
    #
    # And the direction of the remaining error is deliberate. §192(1) charges
    # tax on the "estimated income of the assessee under the head Salaries". A
    # variable payment already made is a fact; one not yet made is a guess about
    # somebody else's discretion, so a bonus is estimated as nil until it is
    # paid and then estimated in full. That under-withholds by at most one
    # month, and §192(3) corrects it in the very next run because the run reads
    # what this deductor has already deducted. Projecting the guess forward
    # instead over-withholds every remaining month and refunds at assessment —
    # an error that does not self-correct and that the employee funds.
    #
    # `gross_already_paid_paise` needs no adjustment: earlier months' one-time
    # amounts are in the gross that was actually paid, which is exactly right.
    annual_gross = (max(0, gross_already_paid_paise)
                    + recurring * months_left
                    + ot.taxable_paise)
    tds_monthly = _monthly_tds(
        declaration=declaration,
        annual_gross_paise=annual_gross,
        # Deliberately the RECURRING basic and DA, with no one-time amount in
        # them even where the CA recorded arrears as PF wages. This figure is
        # the §10(13A) salary base against which the HRA exemption's 10% and
        # 40/50% tests run, and arrears of an earlier year inflating it would
        # cut this year's exemption on rent that was paid against this year's
        # salary. Arrears relief has its own path — §89 and Form 10E,
        # domain/payroll/arrears.py — which is where the earlier year belongs.
        basic_plus_da_paise=(basic + da) * 12,
        hra_received_paise=hra * 12,
        professional_tax_paise=pt * 12,
        fy=fy,
        month=pt_month,
        tds_already_deducted_paise=tds_already_deducted_paise,
        months_already_paid=months_already_paid,
    )

    statutory_deductions = pf["employee"] + esi["employee"] + pt + tds_monthly

    # A loan instalment is recovered AFTER the statutory deductions and only out
    # of what is left. An employer may not recover an advance from money that
    # was never there: PF, ESI, professional tax and TDS are owed to somebody
    # else and come first, and a recovery that pushed net pay below zero would
    # be an overdrawn payslip rather than a debt collected.
    loan_recovery = min(max(0, loan_instalment_paise),
                        max(0, gross - statutory_deductions))

    deductions = statutory_deductions + loan_recovery
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
        # Stored, not recomputed from payroll_one_time_earnings at payslip time.
        # Those rows can be edited or deleted after a run and a released payslip
        # has to keep saying what it said; and the two statutory bases cannot be
        # derived back out of a single total once they are gone. Same reasoning
        # as the PF EPS/EPF split (migration 295).
        "one_time_earnings_paise":  ot.total_paise,
        "one_time_pf_wages_paise":  ot.pf_wages_paise,
        "one_time_esi_wages_paise": ot.esi_wages_paise,
        "one_time_taxable_paise":   ot.taxable_paise,
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
        "loan_recovery_paise": loan_recovery,
        "net_paise":          net,
        "working_days":       working_days,
        "days_present":       days_present,
        "lop_days":           lop_days,
    }


def _months_remaining_for_spread(months_already_paid: int) -> int:
    """Months to spread the year's outstanding tax over, this one included.

    Deliberately counted from what THIS EMPLOYER has already paid in the
    financial year, not from the calendar. §192(3) adjusts for "excess or
    deficiency arising out of any previous deduction ... during the financial
    year" — previous deductions by this deductor, which are the only ones it
    knows or answers for.

    Using the calendar instead is a trap with a factor-of-two blast radius. A
    firm that onboards to this system in October has been deducting since April
    through whatever they used before; those deductions are real, are on the
    employee's 26AS, and are invisible here. Spreading the WHOLE year's tax over
    the six months that remain would double every payslip's TDS, and nothing on
    the payslip would look wrong.

    Counting paid months instead degrades to 12 — a plain annual/12, exactly
    what payroll did before §192(3) was applied — whenever this system has no
    history for the year, which is precisely the case where it cannot know what
    was withheld earlier.
    """
    return max(1, 12 - max(0, int(months_already_paid or 0)))


def _monthly_tds(
    *,
    declaration,
    annual_gross_paise: int,
    basic_plus_da_paise: int,
    hra_received_paise: int,
    professional_tax_paise: int,
    fy: Optional[str],
    month: Optional[int],
    tds_already_deducted_paise: int = 0,
    months_already_paid: int = 0,
) -> int:
    """This month's TDS under §192, after §192(3).

    §192(3) is the reason this is not simply annual-tax-over-twelve: "the person
    responsible for paying may, at the time of making any deduction, increase or
    reduce the amount to be deducted ... for the purpose of adjusting any excess
    or deficiency arising out of any previous deduction or failure to deduct
    during the financial year."

    That subsection is what makes a declaration submitted in December work at
    all. Without it, an employee who proves ₹1,50,000 of §80C in December has
    Apr-Nov withheld at the undeclared rate and no mechanism ever gives it back
    — the employer would have over-deducted and the employee would have to claim
    a refund in their return, a year later. Spreading the REMAINING tax over the
    REMAINING months settles it inside the year, which is what the section is
    for and what every payroll department actually does.

    The floor at zero is deliberate and is also the statute: §192 authorises
    DEDUCTING tax, not paying it back. Where someone has already had more
    withheld than the year now needs — a big declaration verified late — the
    excess is refunded on assessment, not through the payslip.
    """
    if declaration is not None:
        # The §10(13A) exemption is the least of three limbs and two of them —
        # the HRA actually received and 50%/40% of salary — are the EMPLOYER's
        # figures, not the employee's. Payroll supplies them here rather than
        # asking the employee to retype what is already on their payslip.
        # Copied, not mutated: a slip computation must not change the
        # declaration its caller holds.
        declaration = _replace(
            declaration,
            hra_basic_plus_da_paise=max(0, basic_plus_da_paise),
            hra_received_paise=max(0, hra_received_paise),
        )

    annual_tax = decl_domain.withholding_tax_paise(
        decl=declaration,
        projected_annual_salary_paise=annual_gross_paise,
        fy=fy,
        # Whether a declaration may rest on what was merely CLAIMED, or only on
        # what was proved, is a question about the month — see
        # _verified_only_from_month.
        verified_only=_verified_only_from_month(month, declaration),
        professional_tax_paise=professional_tax_paise,
    )

    remaining_months = _months_remaining_for_spread(months_already_paid)
    outstanding = annual_tax - max(0, tds_already_deducted_paise)
    if outstanding <= 0:
        return 0
    return outstanding // max(1, remaining_months)


# From this month of the financial year, a declaration stops being taken on
# trust. Month 1 is April, so 10 is January — the point by which employers
# collect proofs, and the last quarter in which a shortfall can still be
# recovered from salary. §192(1) makes the employer answerable for a correct
# deduction, so a claim with no proof behind it must stop reducing tax while
# there is still salary left to correct it against.
PROOF_CUTOFF_MONTH_OF_FY: int = 10


def _verified_only_from_month(month: Optional[int], declaration) -> bool:
    if declaration is None:
        return False
    if not month or not (1 <= int(month) <= 12):
        return False
    m = int(month)
    index_in_fy = m - 3 if m >= 4 else m + 9
    return index_in_fy >= PROOF_CUTOFF_MONTH_OF_FY


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
    assert_payroll_enabled(db, current_user["firm_id"], data.client_id)
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
    assert_payroll_enabled(db, current_user["firm_id"], data.client_id)
    payload = data.model_dump()
    payload["firm_id"] = current_user["firm_id"]
    row = db.table("salary_structures").insert(payload).execute()
    return api_response(True, (row.data or [{}])[0])


@router.post("/salary-structures/{structure_id}/apply")
def apply_salary_structure(
    structure_id: str,
    data: ApplyStructureIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """Apply a named structure to employees, from a date.

    public.salary_structures has existed since migration 054 and NOTHING HAS
    EVER READ IT — a CA could create "Junior — 40/20", see it listed, and every
    employee's basic, HRA and DA still had to be keyed in one at a time.

    IT WRITES A REVISION, NOT A LINK. payroll_salary_revisions (migration 300)
    is what the run reads, so a structure applied from 1 October starts in
    October and does not restate September, which is posted to the ledger. A
    live salary_structure_id on the employee would mean editing a template
    silently restates everybody on it, months in the general ledger included.

    VALIDATED AND REFUSED WHOLE. A structure that does not fit one employee's
    gross — a fixed medical allowance larger than the percentages leave, say —
    stops the whole request. A partial application would leave half a roster on
    the new scale and half on the old, with nothing on the screen saying which.

    `preview` computes all of it, reports all of it, and writes nothing.
    """
    assert_client_access(current_user, data.client_id)
    db = _db()
    firm_id = current_user["firm_id"]

    if not data.assignments:
        raise HTTPException(status_code=422,
                            detail="No employees were sent to apply the structure to.")

    if not db:
        return api_response(True, {"structure_id": structure_id, "applied": 0,
                                   "preview": data.preview, "employees": [],
                                   "notes": []})

    assert_not_internal_for_payroll(data.client_id, firm_id)
    assert_payroll_enabled(db, firm_id, data.client_id)

    structure = (db.table("salary_structures")
                 .select("id, name, basic_percent, hra_percent, da_percent, "
                         "lta_percent, medical_paise, special_percent")
                 .eq("id", structure_id).eq("firm_id", firm_id)
                 .eq("client_id", data.client_id).maybe_single().execute().data)
    if not structure:
        raise HTTPException(status_code=404, detail="Salary structure not found")

    # A row for somebody else's employee would be written under this client's id
    # and pay a person who does not work here.
    roster = {str(e["id"]): e for e in (
        db.table("payroll_employees")
        .select("id, name, other_allowances_paise")
        .eq("firm_id", firm_id).eq("client_id", data.client_id)
        .execute().data) or []}
    strangers = sorted({a.employee_id for a in data.assignments
                        if a.employee_id not in roster})
    if strangers:
        raise HTTPException(
            status_code=422,
            detail=("These employees are not on this client's roster: "
                    + ", ".join(strangers)))

    seen: set = set()
    rows: list[dict] = []
    reported: list[dict] = []
    notes: list[str] = []
    problems: list[str] = []

    for assignment in data.assignments:
        emp = roster[assignment.employee_id]
        who = emp.get("name") or assignment.employee_id
        if assignment.employee_id in seen:
            problems.append(f"{who}: sent twice in one request.")
            continue
        seen.add(assignment.employee_id)
        try:
            applied = structure_domain.apply_structure(
                structure, assignment.monthly_gross_paise)
        except structure_domain.StructureError as e:
            problems.append(f"{who}: {e}")
            continue

        notes.extend(structure_domain.drift_note(who, applied))
        revision = applied.as_revision()
        # Anything the CA had put in other_allowances is a separate decision and
        # no structure head produces it — carried forward rather than zeroed.
        revision["other_allowances_paise"] = int(emp.get("other_allowances_paise") or 0)
        rows.append({
            "firm_id": firm_id, "client_id": data.client_id,
            "employee_id": assignment.employee_id,
            "effective_from": data.effective_from,
            "source_structure_id": structure_id,
            "reason": (data.reason or f"Applied structure: {structure.get('name') or ''}").strip(),
            **revision,
        })
        reported.append({
            "employee_id": assignment.employee_id, "name": who,
            "monthly_gross_paise": applied.monthly_gross_paise,
            **{c.name: c.paise for c in applied.components},
        })

    if problems:
        raise HTTPException(status_code=422, detail={
            "message": ("The structure could not be applied to every employee "
                        "sent, so none of them were changed."),
            "problems": problems,
        })

    # A revision effective inside a month whose payroll is already released does
    # not change that month — the slips are stored — so it is REPORTED rather
    # than refused. Backdating is legitimate: it is how a pay rise agreed in
    # November and effective from September becomes arrears, which this system
    # computes (domain/payroll/arrears.py, IT Act s.89).
    released = (db.table("payroll_runs").select("month, status")
                .eq("firm_id", firm_id).eq("client_id", data.client_id)
                .in_("status", list(_PAYROLL_RELEASED)).execute().data) or []
    affected = sorted(r["month"] for r in released
                      if f"{r['month']}-01" >= data.effective_from[:7] + "-01")
    if affected:
        notes.append(
            "Payroll for " + ", ".join(affected) + " is already released and was "
            "paid at the old figures. Those months are not recomputed; the "
            "difference is arrears, and s.89 relief is computed separately.")

    if data.preview:
        return api_response(True, {
            "structure_id": structure_id, "structure_name": structure.get("name"),
            "effective_from": data.effective_from, "preview": True,
            "applied": 0, "employees": reported, "notes": notes,
        })

    db.table("payroll_salary_revisions").insert(rows).execute()
    timeline_service.log(
        data.client_id, "work", "Salary Structure Applied",
        f"{structure.get('name') or 'Structure'} applied to {len(rows)} employee(s) "
        f"from {data.effective_from}",
        "info", firm_id=firm_id, entity_type="client", entity_id=data.client_id,
        actor_id=current_user.get("auth_user_id"),
    )
    return api_response(True, {
        "structure_id": structure_id, "structure_name": structure.get("name"),
        "effective_from": data.effective_from, "preview": False,
        "applied": len(rows), "employees": reported, "notes": notes,
    })


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
    assert_payroll_enabled(db, current_user["firm_id"], client_id)

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
    totals = {"gross": 0, "net": 0, "pf": 0, "esi": 0, "pt": 0, "tds": 0,
              "loan_recovery": 0, "edli": 0, "admin": 0, "one_time": 0}

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

    # What each employee declared under §192, and what has already been withheld
    # from them this financial year. Both are read once for the whole run.
    declarations = _declarations_for_run(
        db, current_user["firm_id"], client_id, fy)
    tds_ytd = _tds_already_deducted_this_fy(
        db, current_user["firm_id"], client_id, month, fy)

    # The pay in force this month, and any advance being recovered from it.
    revisions = _salary_in_force(db, current_user["firm_id"], client_id, month)
    loan_due = _loan_instalments_for_run(db, current_user["firm_id"], client_id)

    # Statutory deductions this run did NOT compute because the state's rules are
    # not modelled. Collected per employee and returned with the run: a zero PT
    # for Delhi and a zero PT for Gujarat are the same number meaning opposite
    # things, and only one of them is a liability nobody has settled.
    statutory_gaps: list[str] = []

    # The firm's own reading of the state PT notifications (migration 327), read
    # ONCE for the whole run rather than per employee — a 200-employee run in
    # three states is one query, and the slabs cannot change mid-run. `pt_on` is
    # the payroll MONTH's end, not today: a run for an earlier month computes at
    # the figures that applied to it.
    firm_pt_slabs = _read_firm_pt_slabs(db, current_user["firm_id"])
    pt_on = date.fromisoformat(month_end_date(month))
    pt_covered = _states_the_firm_covers(firm_pt_slabs, pt_on)
    # Recorded against a state the code models: reported, never applied. One
    # typo must not replace a table verified against the state Act for every
    # client of this firm.
    statutory_gaps.extend(firm_rates.slabs_recorded_against_a_modelled_state(
        firm_pt_slabs, _PT_MODELLED_STATES))
    # Employees for whom NOBODY entered attendance this month. Reported with
    # the run, never silently defaulted — see _attendance_gap.
    attendance_gaps: list[str] = []

    # ONE query for the whole roster, not one per employee. This read used to
    # sit inside the loop, so a 200-employee run made 200 sequential round
    # trips to Mumbai for rows totalling a few kilobytes.
    #
    # Through _attendance_for so the run and the attendance screen read the
    # same shape, and so the firm filter lives in one place. The employee ids
    # are already firm-scoped, but the service-role key bypasses RLS and
    # CLAUDE.md is explicit that the app-layer firm filter is the primary
    # isolation control rather than an optimisation — this query omitted it.
    attendance_by_emp = _attendance_for(
        db, current_user["firm_id"], [e["id"] for e in emps], y, m)

    # One-time and variable earnings for the month (migration 331), also one
    # query for the whole run.
    one_time_by_emp = _one_time_for(db, current_user["firm_id"], client_id, month)

    for emp in emps:
        # None means NOT ENTERED, and that is now recorded on the slip rather
        # than being indistinguishable from a confirmed full month.
        attendance = attendance_by_emp.get(str(emp["id"]))

        # A revision in force REPLACES the master's components for this month.
        # Merged over the employee row rather than substituted for it, so
        # everything a revision does not carry — PF applicability, PT state,
        # EPS eligibility — still comes from the master.
        rev = revisions.get(emp["id"])
        if rev:
            emp = {**emp, **{k: rev[k] for k in (
                "basic_paise", "hra_percent", "da_percent", "lta_paise",
                "medical_paise", "special_allowance_paise", "other_allowances_paise")
                if k in rev}}

        slip = _compute_slip(emp, attendance, fy=fy, pt_month=m,
                             esi_covered_at_period_start=emp["id"] in esi_covered_earlier,
                             declaration=declarations.get(emp["id"]),
                             tds_already_deducted_paise=tds_ytd.get(emp["id"], (0, 0, 0))[0],
                             months_already_paid=tds_ytd.get(emp["id"], (0, 0, 0))[1],
                             gross_already_paid_paise=tds_ytd.get(emp["id"], (0, 0, 0))[2],
                             months_employed_in_fy=_months_employed_in_fy(
                                 emp.get("joining_date"), fy),
                             loan_instalment_paise=loan_due.get(emp["id"], 0),
                             firm_pt_slabs=firm_pt_slabs, pt_on=pt_on,
                             one_time=one_time_by_emp.get(str(emp["id"])))
        statutory_gaps.extend(_statutory_gaps(emp, pt_covered))
        attendance_gaps.extend(_attendance_gap(emp, attendance is not None))
        slip["run_id"]      = run_id
        slip["employee_id"] = emp["id"]
        slip["attendance_entered"] = attendance is not None

        slips.append(slip)
        totals["gross"] += slip["gross_paise"]
        totals["net"]   += slip["net_paise"]
        totals["pf"]    += slip["pf_employee_paise"] + slip["pf_employer_paise"]
        # EDLI and the administrative charge are EMPLOYER costs outside the 12%,
        # deducted from nobody and remitted on the same challan. They were
        # computed, stored on the slip and shown on the statutory card, and they
        # never reached the ledger — see migration 329.
        totals["edli"]  += int(slip.get("edli_paise") or 0)
        totals["admin"] += int(slip.get("pf_admin_paise") or 0)
        totals["esi"]   += slip["esi_employee_paise"] + slip["esi_employer_paise"]
        totals["pt"]    += slip["pt_paise"]
        totals["tds"]   += slip["tds_paise"]
        totals["loan_recovery"] += slip.get("loan_recovery_paise", 0)
        totals["one_time"] += slip.get("one_time_earnings_paise", 0)

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

    # The ₹500-per-ESTABLISHMENT floor on the admin charge can only be settled
    # here: it is not per member, so summing payslips under-states it for every
    # small client. One rule, in domain/payroll/statutory.py, shared with
    # /statutory-position — which had the floor and was the only place that did.
    totals["admin"] = payroll_admin_charge(totals["admin"], fy)

    # Update run totals
    db.table("payroll_runs").update({
        "total_gross_paise": totals["gross"],
        "total_net_paise":   totals["net"],
        "total_pf_paise":    totals["pf"],
        "total_esi_paise":   totals["esi"],
        "total_pt_paise":    totals["pt"],
        "total_tds_paise":   totals["tds"],
        "total_loan_recovery_paise": totals["loan_recovery"],
        "total_edli_paise":     totals["edli"],
        "total_pf_admin_paise": totals["admin"],
        # How much of this month's gross was NOT the recurring salary bill —
        # the single number that answers "why is this month bigger than last
        # month" before anybody opens a slip.
        "total_one_time_paise": totals["one_time"],
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
    # States this run deducts professional tax in with no PTRC on file. Added
    # to statutory_gaps rather than a list of its own: it is the same kind of
    # fact — a deduction the employer cannot settle — and a screen with three
    # ideas of "incomplete" teaches nobody to read any of them.
    #
    # Reported once per STATE, not once per employee: the registration is a
    # fact about the employer there, and naming it forty times because forty
    # people work in Karnataka would bury every other gap. See
    # domain/payroll/identity.py::pt_registration_gaps.
    _, pt_registrations = _read_statutory_identity(db, current_user["firm_id"], client_id)
    statutory_gaps.extend(identity_domain.pt_registration_gaps(
        {(e.get("pt_state") or "").strip().upper() for e in emps
         if e.get("pt_applicable") and (e.get("pt_state") or "").strip()},
        pt_registrations))

    # Returned WITH the run rather than logged: an omitted statutory deduction
    # that only appears in a log is an omitted statutory deduction.
    return api_response(True, {**run, "statutory_gaps": statutory_gaps,
                               "attendance_gaps": attendance_gaps})


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


# ── The defensible release ───────────────────────────────────────────────────
# Migration 328. create_run returns two lists of things it could not establish —
# statutory_gaps and attendance_gaps — and both were advice. Nothing stopped a
# run being FINALISED with them outstanding, and finalising posts a real,
# immutable general-ledger journal: the warnings stopped being advice at exactly
# the moment nothing was enforcing them.

#: Matches the CHECK in migration 328. A floor under "ok", "-" and ".", which is
#: what a required free-text field collects when nothing asks for more.
_OVERRIDE_REASON_MIN = 20


def _release_gaps(db, firm_id: str, run: dict) -> list[str]:
    """What this run still cannot establish, RECOMPUTED now.

    Not read from the draft. A CA who records the missing state slabs
    (migration 327) or enters the missing attendance (326) between drafting and
    finalising has genuinely closed the gap, and a stored list would still be
    refusing — which teaches people that the block is noise.

    Reads the same things create_run does, once each for the whole run: the
    roster, the firm's PT slabs, the client's PT registrations and the slips.
    """
    if not db:
        return []
    client_id = run.get("client_id")
    month = str(run.get("month") or "")

    emps = (db.table("payroll_employees")
            .select("id, name, pt_applicable, pt_state")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("status", "active").execute().data) or []

    firm_pt_slabs = _read_firm_pt_slabs(db, firm_id)
    try:
        on = date.fromisoformat(month_end_date(month))
    except (ValueError, AttributeError):
        # An unparseable month cannot be dated, so no firm slab can be judged in
        # force. Falling back to today reports MORE gaps, not fewer, which is
        # the safe direction: the other one releases silently.
        on = ist_today()
    covered = _states_the_firm_covers(firm_pt_slabs, on)

    gaps: list[str] = []
    gaps.extend(firm_rates.slabs_recorded_against_a_modelled_state(
        firm_pt_slabs, _PT_MODELLED_STATES))
    gaps.extend(identity_domain.pt_registration_gaps(
        {(e.get("pt_state") or "").strip().upper() for e in emps
         if e.get("pt_applicable") and (e.get("pt_state") or "").strip()},
        _read_statutory_identity(db, firm_id, client_id)[1]))
    for emp in emps:
        gaps.extend(_statutory_gaps(emp, covered))

    # Attendance is read off the SLIPS, not off public.attendance: the slip
    # records what was true when it was computed (migration 324), and an
    # attendance row added afterwards did not go into the figures being
    # released. NULL predates migration 324 and is genuinely unknown, so it is
    # reported rather than assumed in either direction.
    slips = (db.table("payroll_slips").select("employee_id, attendance_entered")
             .eq("run_id", run.get("id")).execute().data) or []
    by_id = {str(e["id"]): e for e in emps}
    for slip in slips:
        entered = slip.get("attendance_entered")
        emp = by_id.get(str(slip.get("employee_id")))
        who = (emp or {}).get("name") or slip.get("employee_id") or "employee"
        if entered is False:
            gaps.extend(_attendance_gap(emp or {"name": who}, False))
        elif entered is None:
            gaps.append(
                f"{who}: this slip predates the attendance record-keeping, so "
                f"whether anybody entered attendance for it cannot be "
                f"established. Regenerate the run to find out.")
    return gaps


def _log_transition(db, firm_id: str, run: dict, to_status: str,
                    actor_id: Optional[str], gaps: Optional[list] = None,
                    override_reason: Optional[str] = None) -> None:
    """Append one row to the transition log, and never let that break the move.

    Written AFTER the transition it records, and swallowed rather than raised:
    a run that finalised and posted its journal HAS finalised, and reporting a
    500 at that point would invite a re-finalisation — the one thing the
    immutability guards exist to prevent.
    """
    if not db:
        return
    try:
        db.table("payroll_run_transitions").insert({
            "firm_id": firm_id,
            "run_id": run.get("id"),
            "from_status": run.get("status"),
            "to_status": to_status,
            "gaps": gaps or [],
            "override_reason": (override_reason or "").strip() or None,
            "actor_id": actor_id,
        }).execute()
    except Exception:
        _logger.exception("payroll transition log failed for run=%s -> %s",
                          run.get("id"), to_status)


def _reason_for_releasing_with(gaps: list, override_reason: Optional[str]) -> str:
    """Return the reason to record, or raise the refusal that blocks the release.

    The gaps are NAMED in the refusal. A count would send the CA back to the
    draft screen to work out which; the sentences are the whole point of having
    collected them.
    """
    reason = (override_reason or "").strip()
    if not gaps:
        return reason
    if not reason:
        raise HTTPException(status_code=409, detail={
            "message": (
                f"This run has {len(gaps)} thing(s) it could not establish, and "
                f"finalising posts a journal that cannot be changed afterwards. "
                f"Resolve them, or record why you are releasing anyway."),
            "gaps": gaps,
        })
    if len(reason) < _OVERRIDE_REASON_MIN:
        raise HTTPException(status_code=422, detail=(
            f"Say why in at least {_OVERRIDE_REASON_MIN} characters. This reason "
            f"goes on the release log beside the {len(gaps)} outstanding item(s) "
            f"and is what a reviewer reads months later."))
    return reason


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
    # Read before the update so the log can record what it moved FROM. The
    # update's own .not_.in_ guard still decides whether the move happens, so
    # this read is for the log and not a check-then-act.
    before = (db.table("payroll_runs").select("id, status, client_id, month")
              .eq("id", run_id).eq("firm_id", current_user["firm_id"])
              .maybe_single().execute().data) or {"id": run_id}

    row = (db.table("payroll_runs").update({"status": new_status}).eq("id", run_id)
           .eq("firm_id", current_user["firm_id"])
           .not_.in_("status", ["finalized", "paid"]).execute())
    if not row.data:
        raise HTTPException(status_code=404, detail="Run not found or already finalized/paid")

    # No gap check: draft <-> review posts no journal and pays nobody, so gaps
    # there are information. Requiring a reason to move a run to review would
    # only teach people to type "n/a" before the moment it matters. The
    # transition is still logged, because the log is a record of what happened
    # rather than a record of what was refused.
    _log_transition(db, current_user["firm_id"], before, new_status,
                    current_user.get("id"))
    return api_response(True, row.data[0])


@router.post("/runs/{run_id}/finalize")
def finalize_run(
    run_id: str,
    current_user: dict = Depends(rbac("payroll", "finalize")),
    # APPENDED, not inserted. Every caller of this function passes run_id and
    # current_user positionally, so putting the new parameter second silently
    # bound the caller into `data` and left current_user as its Depends
    # sentinel — which surfaced as "'Depends' object is not subscriptable" from
    # inside the scope guard. FastAPI does not care about the order; Python's
    # callers do.
    data: Optional[ReleaseIn] = None,
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

    BLOCKED BY AN UNRESOLVED GAP (migration 328). Statutory and attendance gaps
    were shown on the draft and enforced nowhere, so they stopped being advice
    at exactly the moment the figures became immutable. They are RECOMPUTED
    here — a CA who has since recorded the state slabs or entered the
    attendance has genuinely closed the gap — and a release with any
    outstanding needs a Partner's typed reason, which goes on the transition
    log beside them.
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

    # BEFORE the journal, because a refusal after posting would be a run that is
    # not finalized carrying an entry that says it is.
    gaps = _release_gaps(db, firm_id, run)
    reason = _reason_for_releasing_with(gaps, (data.override_reason if data else None))

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

    # The recovery is real now that the run has posted: write the balances down.
    _apply_loan_recoveries(db, firm_id, client_id, run_id)

    db.table("payroll_runs").update({
        "status":          "finalized",
        "finalized_at":    datetime.now(timezone.utc).isoformat(),
        "journal_entry_id": journal_id,
    }).eq("id", run_id).execute()

    _log_transition(db, firm_id, run, "finalized", current_user.get("id"),
                    gaps=gaps, override_reason=reason)

    timeline_service.log(client_id, "work", "Payroll Finalized",
        f"Payroll for {run['month']} finalized — {run.get('headcount', 0)} employees"
        + (f" with {len(gaps)} item(s) overridden" if gaps else ""),
        "warning" if gaps else "success")

    return api_response(True, {"id": run_id, "status": "finalized",
                               "journal_entry_id": journal_id,
                               "overridden_gaps": gaps})


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

    # ist_today(), not the UTC date. A disbursement posts on the day the money
    # left, and that day is the Indian business day: between midnight and 05:30
    # IST the UTC date is still YESTERDAY, so a payment made at 2am on the 1st
    # posted into the previous month — and period_validation_service then
    # validated it against the wrong financial year. Same bug the accrual had.
    payment_date = data.payment_date or ist_today().isoformat()

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

    # Logged, not gap-checked. Disbursement pays out figures that were already
    # released at finalize, where the check belongs — re-refusing here would
    # strand money that has left the bank in a run the software will not admit
    # was paid.
    _log_transition(db, run["firm_id"], run, "paid", current_user.get("id"))

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
    # A reversal is a NEW posting dated when it happens — which is the Indian
    # business day, not the UTC one. Before 05:30 IST they are different days,
    # and on 1 April they are different FINANCIAL YEARS: a reversal made at 2am
    # IST on 1 April would post to 31 March, into a year a CA may have just
    # locked, and be validated against it below.
    reversal_date = ist_today().isoformat()
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

    # ONTO THE TRANSITION LOG, like every other status move (migration 328).
    # It was the only one that did not reach it — and it is the move a reviewer
    # would most want there, because it is the one that UNDOES a release. The
    # log said a run was finalised on the 3rd and paid on the 5th, and nothing
    # at all about the reversal on the 6th that took both back; a month later
    # the run reads as a draft that was never released.
    #
    # `run` still carries the pre-update status, so from_status records what was
    # actually reversed — finalized or paid — rather than the 'review' it has
    # just become.
    _log_transition(db, firm_id, run, "review", current_user.get("id"))

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


# ── The firm's own reading of the state PT slabs ─────────────────────────────
# Migration 327. domain/payroll/professional_tax.py models four of the
# twenty-two states that levy PT and reports the rest as gaps. That refusal is
# right — Article 276 makes the employer liable, so a silent nil is a shortfall
# with interest — and it is also not a product: the only remedy on offer was
# that somebody edits Python.
#
# So the CA records what they READ, once per firm, with the notification it came
# from. See domain/payroll/firm_rates.py for the rules on using one.

_MOCK_PT_SLABS: dict[tuple, list[dict]] = {}

#: Selected everywhere firm slabs are read, so the columns are checked against
#: the real schema by tests/test_backend_columns_exist_pg.py.
def _read_firm_pt_slabs(db, firm_id: str) -> list[dict]:
    if not db:
        return [dict(r) for rows in
                [v for k, v in sorted(_MOCK_PT_SLABS.items()) if k[0] == firm_id]
                for r in rows]
    try:
        return (db.table("firm_pt_slabs")
                # Named inline, and including recorded_by, so every column of
                # this table is checked against the real schema by
                # tests/test_backend_columns_exist_pg.py — the insert is a list
                # comprehension, which that scanner cannot read.
                .select("id, state, effective_from, basis, from_paise, to_paise, "
                        "amount_paise, months, notification_reference, "
                        "notification_date, note, recorded_by")
                .eq("firm_id", firm_id).order("state").execute().data) or []
    except Exception:
        # Degrades to "nothing recorded", which leaves the state a reported gap.
        # The other direction — treating a failed read as "covered" — would
        # deduct nothing and say nothing.
        _logger.exception("firm PT slab read failed for firm=%s", firm_id)
        return []


def _pt_slabs_by_state(slabs: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for row in slabs:
        out.setdefault(str(row.get("state") or "").strip().upper(), []).append(row)
    return out


def _states_the_firm_covers(slabs: list[dict], on: date) -> set[str]:
    """States whose recorded slabs are usable for a run on `on`.

    Usable means: a version effective on or before that date, whose bands start
    at zero and meet end to start. A half-recorded state is NOT covered — a wage
    falling in a hole would otherwise come out as a silent nil, which is the
    fault this whole mechanism exists to avoid importing.

    Excludes the states the code models: for those the code wins and the
    disagreement is reported (firm_rates.slabs_recorded_against_a_modelled_state).
    """
    covered: set[str] = set()
    for state, rows in _pt_slabs_by_state(slabs).items():
        if state in _PT_MODELLED_STATES:
            continue
        version = firm_rates.in_force(rows, on)
        if version and firm_rates.bands_cover_every_wage(version):
            covered.add(state)
    return covered


@router.get("/statutory-values")
def get_statutory_values(
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """What this firm has recorded, and which states still need it.

    Returns the levying/modelled/recorded sets alongside the rows so the Settings
    screen can say "eighteen states levy this, you have recorded three" without
    holding its own copy of who levies what.
    """
    slabs = _read_firm_pt_slabs(_db(), current_user["firm_id"])
    covered = _states_the_firm_covers(slabs, ist_today())
    return api_response(True, {
        "pt_slabs": slabs,
        "pt_levying_states": pt_domain.LEVYING_STATES,
        "pt_modelled_states": sorted(_PT_MODELLED_STATES),
        "pt_recorded_states": sorted(covered),
        "pt_conflicts": firm_rates.slabs_recorded_against_a_modelled_state(
            slabs, _PT_MODELLED_STATES),
    })


@router.put("/statutory-values/pt")
def put_pt_slabs(
    body: PTSlabSetIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """Record one state's slab set, as at one notification.

    THE WHOLE SET IN ONE REQUEST, and that is the point. The bands have to start
    at zero and meet end to start, and a per-band endpoint would let a
    half-recorded state exist between two calls — during which a wage in the hole
    would come out as a silent nil. So the set is validated whole, refused
    whole, and REPLACES that (state, effective_from) rather than adding to it.

    A revision is a NEW effective_from, never an edit of an old one: a run for an
    earlier month must keep computing at the figures that applied to it, and
    those months are posted to the general ledger.
    """
    bands = [b.model_dump() for b in body.bands]
    if not firm_rates.bands_cover_every_wage(bands):
        raise HTTPException(status_code=422, detail=(
            "These slabs do not cover every wage. They must start at 0, each "
            "band's upper bound must be the next band's lower bound, and the "
            "highest band must be left open ('and above'). A wage falling in a "
            "hole would come out as nil, which is indistinguishable from a state "
            "saying nothing is due."))

    bases = {b.get("basis") or "monthly" for b in bands}
    if len(bases) > 1:
        raise HTTPException(status_code=422, detail=(
            "Every band in one slab set must share the same basis — a state "
            "reads its slab against the month or against six months, not both."))

    db = _db()
    firm_id = current_user["firm_id"]
    key = (firm_id, body.state, body.effective_from)
    rows = [{"state": body.state, "effective_from": body.effective_from,
             "notification_reference": body.notification_reference.strip(),
             "notification_date": body.notification_date,
             "note": (body.note or "").strip() or None, **band}
            for band in bands]

    if not db:
        _MOCK_PT_SLABS[key] = rows
        return api_response(True, {"state": body.state,
                                   "effective_from": body.effective_from,
                                   "bands": len(rows)})

    if body.state in _PT_MODELLED_STATES:
        # Recorded, not refused: the CA may well be right that the notification
        # has moved. It is REPORTED on every run rather than applied, so the
        # disagreement reaches somebody who can make the code change.
        _logger.info("caflow.payroll firm %s recorded PT slabs for modelled state %s",
                     firm_id, body.state)

    # Replace rather than merge: a set that was six bands and is now five must
    # not leave the sixth behind, where it would overlap and make the lookup
    # order-dependent.
    (db.table("firm_pt_slabs").delete()
     .eq("firm_id", firm_id).eq("state", body.state)
     .eq("effective_from", body.effective_from).execute())
    db.table("firm_pt_slabs").insert(
        [{"firm_id": firm_id, "recorded_by": current_user.get("id"), **row}
         for row in rows]).execute()

    return api_response(True, {"state": body.state,
                               "effective_from": body.effective_from,
                               "bands": len(rows)})


@router.delete("/statutory-values/pt")
def delete_pt_slabs(
    state: str = Query(..., description='Two-letter state code, e.g. "GJ"'),
    effective_from: str = Query(..., description="The version to remove, YYYY-MM-DD"),
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """Remove one recorded version.

    The state goes back to being a reported gap if nothing earlier remains,
    which is the correct outcome: an employer deducting on slabs nobody stands
    behind is exactly what the gap says.
    """
    state = (state or "").strip().upper()
    db = _db()
    firm_id = current_user["firm_id"]
    if not db:
        _MOCK_PT_SLABS.pop((firm_id, state, effective_from), None)
        return api_response(True, {"state": state, "effective_from": effective_from,
                                   "deleted": True})
    (db.table("firm_pt_slabs").delete()
     .eq("firm_id", firm_id).eq("state", state)
     .eq("effective_from", effective_from).execute())
    return api_response(True, {"state": state, "effective_from": effective_from,
                               "deleted": True})


# ── Attendance: the server-side contract ─────────────────────────────────────
# Migration 326. Until now the ONLY thing that wrote public.attendance was
# app/payroll/attendance/page.tsx, straight through PostgREST — no validation,
# and a Save that wrote a confident default row for every employee in the firm
# whether or not the CA had looked at them. See domain/payroll/attendance.py
# for what that erased and what the identity is.

#: The released statuses. tds_return_service names the same pair
#: _PAYROLL_POSTED; the ECR, the ESIC return, Form 16 and the 24Q all
#: refuse anything outside it, and migration 323 made RLS agree.
_PAYROLL_RELEASED = ("finalized", "paid")

_MOCK_ATTENDANCE: dict[tuple, dict] = {}
_MOCK_ONE_TIME: dict[tuple, dict] = {}
_MOCK_PAYROLL_SETTINGS: dict[tuple, dict] = {}

def _payroll_settings(db, firm_id: str, client_id: str) -> dict:
    """This client's payroll configuration, or {} — never a default.

    A firm that has not agreed a cut-off with this client has not agreed one,
    and cutoff_state reports that as `agreed: false` rather than as being on
    time. See migration 326.
    """
    if not db:
        return dict(_MOCK_PAYROLL_SETTINGS.get((firm_id, client_id), {}))
    try:
        return (db.table("client_payroll_settings")
                .select("inputs_due_day, note, payroll_enabled, "
                        "payroll_enabled_by, payroll_enabled_on")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .maybe_single().execute().data) or {}
    except Exception:
        _logger.exception("payroll settings read failed for client=%s", client_id)
        return {}


def assert_payroll_enabled(db, firm_id: str, client_id: str) -> None:
    """Refuse a payroll WRITE for a client the firm has not switched payroll on for.

    WRITES ONLY, and that asymmetry is the point (migration 332). A client whose
    payroll the firm has stopped running still has Form 16s to issue, an ECR
    history somebody may be asked about, and payslips the employee portal serves.
    Blocking those would make switching payroll off destructive rather than
    administrative, and nobody would dare use the switch.

    NO ROW MEANS NOT ENABLED. client_payroll_settings is sparse — migration 326
    created it for the input cut-off, which most clients have never set — so
    absence is the ordinary state and it is the same answer as false. Migration
    332 backfilled a true row for every client that already had an employee or a
    run, so this cannot switch off a payroll somebody is already running.

    Mock mode has no database and no settings; the guard is a no-op there, the
    same way assert_not_internal_for_payroll's lookup is.
    """
    if not db:
        return

    # Read directly rather than through _payroll_settings, which swallows a
    # failed read into {}. Here the two answers are not the same: "this client
    # is not a payroll client" is a settled fact and a 403, while "the settings
    # could not be read" is a transient failure and must not be reported as the
    # firm having made a decision it did not make. A CA told payroll is switched
    # off would go looking for a Partner to switch it on, and find it already on.
    try:
        row = (db.table("client_payroll_settings").select("payroll_enabled")
               .eq("firm_id", firm_id).eq("client_id", client_id)
               .maybe_single().execute().data) or {}
    except Exception:
        _logger.exception("payroll enablement read failed for client=%s", client_id)
        raise HTTPException(
            status_code=503,
            detail=("Could not check whether payroll is switched on for this "
                    "client, so nothing was written. Try again."))

    if not row.get("payroll_enabled"):
        raise HTTPException(
            status_code=403,
            detail=("Payroll is not switched on for this client. A Partner turns "
                    "it on under Payroll → Settings; until then nothing payroll "
                    "can be created for them. Existing payroll records stay "
                    "readable."))


def _client_roster(db, firm_id: str, client_id: str) -> list[dict]:
    # status = active, matching create_run's own roster query exactly. Showing
    # a leaver here would invite attendance for somebody the run will not
    # compute a slip for, which then reads as entered and explains nothing.
    return (db.table("payroll_employees")
            .select("id, name, designation, status")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("status", "active")
            .execute().data) or []


def _attendance_for(db, firm_id: str, emp_ids: list[str], year: int, month: int) -> dict:
    """Every entered row for these employees in this month, keyed by employee.

    Firm-filtered as well as employee-filtered. The employee ids are already
    firm-scoped by the caller, so this is belt and braces — but the service-role
    key bypasses RLS and CLAUDE.md is explicit that the app-layer firm filter is
    the primary isolation control, not an optimisation.

    Chunked because PostgREST puts the id list in the URL.
    """
    out: dict[str, dict] = {}
    for i in range(0, len(emp_ids), 200):
        # Columns named inline, not via a constant: a select list is the only
        # place these get checked against the real schema by
        # tests/test_backend_columns_exist_pg.py, and it cannot read a Name.
        rows = (db.table("attendance")
                .select("employee_id, working_days, days_present, casual_leaves, "
                        "sick_leaves, earned_leaves, lop_days, entered_by, entered_at")
                .eq("firm_id", firm_id)
                .in_("employee_id", emp_ids[i:i + 200])
                .eq("month", month).eq("year", year)
                .execute().data) or []
        for r in rows:
            out[str(r.get("employee_id"))] = r
    return out


def _one_time_for(db, firm_id: str, client_id: str, month: str) -> dict:
    """Every one-time earning recorded for this client-month, bundled per employee.

    ONE query for the whole run, like the attendance read above and for the same
    reason: a 200-employee run must not make 200 round trips to Mumbai. Scoped
    by client as well as firm — the earnings belong to a client-month the same
    way the run does — and the firm filter is the primary isolation control
    because the service-role key bypasses RLS.

    `month` is the run's "YYYY-MM"; the column is a DATE pinned to the first of
    the month by migration 331's CHECK, so the equality is exact.
    """
    rows = (db.table("payroll_one_time_earnings")
            # Columns named inline, not `*`: a select list is the only place
            # these get checked against the real schema by
            # tests/test_backend_columns_exist_pg.py.
            .select("id, employee_id, kind, label, amount_paise, "
                    "pf_wages, esi_wages, taxable, payment_interval_months")
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .eq("month", f"{month}-01")
            .execute().data) or []
    return one_time_domain.bundles_by_employee(rows)


@router.get("/attendance")
def get_attendance(
    client_id: str = Query(...),
    month: str = Query(..., description='Payroll month, e.g. "2026-08"'),
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """This client's roster for the month, each employee entered or NOT ENTERED.

    `entered` is the absence or presence of a row and nothing else. There is no
    third value and no flag: having no row is what not-entered IS, and the
    moment a default row exists the question can never be asked again — which
    is precisely what the old bulk save did to every employee in the firm.
    """
    assert_client_access(current_user, client_id)
    try:
        year, mon = attendance_domain.parse_month(month)
    except attendance_domain.AttendanceError as e:
        raise HTTPException(status_code=422, detail=str(e))

    db = _db()
    firm_id = current_user["firm_id"]
    if not db:
        rows = [dict(v) for k, v in sorted(_MOCK_ATTENDANCE.items())
                if k[0] == firm_id and k[1] == client_id and k[2] == month]
        return api_response(True, {
            "client_id": client_id, "month": month,
            "days_in_month": attendance_domain.days_in_month(month),
            "employees": rows, "entered_count": len(rows), "not_entered_count": 0,
            "cutoff": attendance_domain.cutoff_state(month, None, ist_today()),
            "locked": False,
        })

    roster = _client_roster(db, firm_id, client_id)
    entered = _attendance_for(db, firm_id, [e["id"] for e in roster], year, mon)

    employees = []
    for emp in roster:
        row = entered.get(str(emp["id"]))
        employees.append({
            "employee_id": emp["id"],
            "name": emp.get("name"),
            "designation": emp.get("designation"),
            "status": emp.get("status"),
            "entered": row is not None,
            **{f: (row or {}).get(f) for f in attendance_domain.DAY_FIELDS},
            "entered_at": (row or {}).get("entered_at"),
        })

    settings = _payroll_settings(db, firm_id, client_id)
    return api_response(True, {
        "client_id": client_id,
        "month": month,
        "days_in_month": attendance_domain.days_in_month(month),
        "employees": employees,
        "entered_count": sum(1 for e in employees if e["entered"]),
        "not_entered_count": sum(1 for e in employees if not e["entered"]),
        "cutoff": attendance_domain.cutoff_state(
            month, settings.get("inputs_due_day"), ist_today()),
        "locked": _attendance_is_locked(db, firm_id, client_id, month) is not None,
        # Migration 332. Reported on the screen a CA opens first, because a
        # client payroll is switched OFF for still answers every read — the
        # roster, last month's slips — and would otherwise look ordinary right
        # up until Save is refused.
        "payroll_enabled": bool(settings.get("payroll_enabled")),
        "payroll_enabled_on": settings.get("payroll_enabled_on"),
    })


def _attendance_is_locked(db, firm_id: str, client_id: str, month: str) -> Optional[str]:
    """The status of a released run for this client-month, or None.

    Attendance is what the slips were computed FROM. Editing it under a
    finalised run does not change a single figure on that run — the slips are
    stored — it just makes the inputs stop explaining the output, and the ECR's
    NCP days stop agreeing with the attendance somebody can now read. Refused
    rather than allowed-and-warned, because nothing downstream re-reads it.
    """
    run = (db.table("payroll_runs").select("status")
           .eq("firm_id", firm_id).eq("client_id", client_id).eq("month", month)
           .maybe_single().execute().data)
    status = (run or {}).get("status")
    return status if status in _PAYROLL_RELEASED else None


@router.put("/attendance")
def put_attendance(
    body: AttendanceIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """Record attendance for the employees in this request, and no others.

    ONLY THE EMPLOYEES SENT. The old page saved its whole editor, which seeded a
    default 26/26 row for everybody with none — so one Save asserted a confident
    full month for the entire firm and there was never a gap to report again.

    Validated and refused WHOLE (domain/payroll/attendance.py): a partial write
    leaves some of a client-month saved and some not, and the ones that failed
    are then indistinguishable from the ones nobody entered.
    """
    assert_client_access(current_user, body.client_id)
    db = _db()
    firm_id = current_user["firm_id"]

    assert_payroll_enabled(db, firm_id, body.client_id)

    if db:
        locked = _attendance_is_locked(db, firm_id, body.client_id, body.month)
        if locked:
            raise HTTPException(
                status_code=409,
                detail=(f"Payroll for {body.month} is {locked}. Its payslips were "
                        f"computed from this attendance and are already posted, so "
                        f"changing it now would leave the inputs disagreeing with "
                        f"the payslips and the ECR. Reverse the run first."))
        roster = {str(e["id"]): (e.get("name") or "") for e in
                  _client_roster(db, firm_id, body.client_id)}
    else:
        roster = {}

    sent_ids = [str(r.employee_id or "").strip() for r in body.rows]
    if db:
        # A row for somebody else's employee would be written under this firm's
        # id and be invisible to the client it actually belongs to.
        strangers = sorted({i for i in sent_ids if i and i not in roster})
        if strangers:
            raise HTTPException(
                status_code=422,
                detail=("These employees are not on this client's roster: "
                        + ", ".join(strangers)))

    try:
        rows = attendance_domain.build_rows(
            [r.model_dump() for r in body.rows], period=body.month,
            names_by_id=roster)
    except attendance_domain.AttendanceError as e:
        raise HTTPException(status_code=422, detail=str(e))

    year, mon = attendance_domain.parse_month(body.month)
    # UTC on disk, as every timestamptz in this schema is. CLAUDE.md's IST
    # rule is about REPORTING a time, not storing one.
    stamped = datetime.now(timezone.utc).isoformat()
    if not db:
        for row in rows:
            _MOCK_ATTENDANCE[(firm_id, body.client_id, body.month, row.employee_id)] = {
                **row.as_write(), "entered_at": stamped}
        return api_response(True, {"client_id": body.client_id, "month": body.month,
                                   "saved": len(rows)})

    db.table("attendance").upsert(
        [{"firm_id": firm_id, "month": mon, "year": year,
          "entered_by": current_user.get("id"), "entered_at": stamped,
          **row.as_write()} for row in rows],
        on_conflict="employee_id,month,year").execute()

    timeline_service.log(
        body.client_id, "work", "Attendance Entered",
        f"Attendance recorded for {len(rows)} employee(s) for {body.month}",
        "info", firm_id=firm_id, entity_type="client", entity_id=body.client_id,
        actor_id=current_user.get("auth_user_id"),
    )
    return api_response(True, {"client_id": body.client_id, "month": body.month,
                               "saved": len(rows)})


@router.get("/one-time-earnings")
def get_one_time_earnings(
    client_id: str,
    month: str,
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """This client-month's one-time earnings, and what the statute says of each.

    `divergence` is the sentence where a saved row disagrees with the statutory
    default — a CA may know something the default cannot, but a disagreement in
    what the ECR and the ESIC return are built from should be VISIBLE rather
    than silent.
    """
    assert_client_access(current_user, client_id)
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        rows = [r for (f, c, m, _eid), r in _MOCK_ONE_TIME.items()
                if f == firm_id and c == client_id and m == month]
    else:
        rows = (db.table("payroll_one_time_earnings")
                .select("id, employee_id, kind, label, amount_paise, pf_wages, "
                        "esi_wages, taxable, payment_interval_months, note, "
                        "entered_by, entered_at")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("month", f"{month}-01")
                .execute().data) or []

    out = []
    for r in rows:
        out.append({**r, "divergence": one_time_domain.divergence_note(r)})

    b = one_time_domain.bundle(rows)
    return api_response(True, {
        "client_id": client_id, "month": month, "rows": out,
        "total_paise": b.total_paise,
        "pf_wages_paise": b.pf_wages_paise,
        "esi_wages_paise": b.esi_wages_paise,
        "taxable_paise": b.taxable_paise,
        "locked": (_attendance_is_locked(db, firm_id, client_id, month) is not None
                   if db else False),
        # Migration 332. Reported here as well as on the attendance read,
        # because this is the tab the switch lives on and a client payroll is
        # off for still answers every read — the screen would look ordinary
        # right up until Save is refused.
        "payroll_enabled": bool(
            (_payroll_settings(db, firm_id, client_id) or {}).get("payroll_enabled")),
        "kinds": list(one_time_domain.KINDS),
    })


@router.put("/one-time-earnings")
def put_one_time_earnings(
    body: OneTimeEarningsIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """Replace this client-month's one-time earnings for the employees named.

    REPLACE, PER EMPLOYEE. An employee sent with no rows has their earnings for
    the month cleared; an employee not sent at all is untouched. Upserting row
    by row instead would make "I deleted the duplicate bonus" impossible to
    express, and keying on (employee, month, kind) would make two separate
    incentives in one month collide into one.

    Refused whole, like attendance: a partial write leaves half a client-month
    saved with nothing on the screen saying which half.
    """
    assert_client_access(current_user, body.client_id)
    db = _db()
    firm_id = current_user["firm_id"]

    assert_payroll_enabled(db, firm_id, body.client_id)

    if db:
        # The same refusal attendance carries, for the same reason: the slips
        # are STORED, so editing the inputs under a released run does not change
        # a figure — it just stops the inputs explaining the output, and stops
        # the ECR's PF wages agreeing with anything a CA can now read.
        locked = _attendance_is_locked(db, firm_id, body.client_id, body.month)
        if locked:
            raise HTTPException(
                status_code=409,
                detail=(f"Payroll for {body.month} is {locked}. Its payslips already "
                        f"carry these earnings, so changing them now would leave the "
                        f"inputs disagreeing with the payslips, the ECR and the "
                        f"ledger. Reverse the run first."))
        roster = {str(e["id"]) for e in _client_roster(db, firm_id, body.client_id)}
        strangers = sorted({str(r.employee_id or "").strip() for r in body.rows}
                           - roster - {""})
        if strangers:
            raise HTTPException(
                status_code=422,
                detail=("These employees are not on this client's roster: "
                        + ", ".join(strangers)))

    try:
        attendance_domain.parse_month(body.month)
    except attendance_domain.AttendanceError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Whole-request validation. Every problem at once, addressed to a row a CA
    # can find on the screen, rather than the first one the loop happens to hit.
    problems: list[str] = []
    for i, r in enumerate(body.rows, start=1):
        for msg in one_time_domain.validate(r.model_dump()):
            problems.append(f"Row {i}: {msg}")
    if problems:
        raise HTTPException(status_code=422, detail=" ".join(problems))

    touched = sorted({str(r.employee_id).strip() for r in body.rows})
    stamped = datetime.now(timezone.utc).isoformat()

    if not db:
        for key in list(_MOCK_ONE_TIME):
            f, c, m, _rid = key
            if (f, c, m) == (firm_id, body.client_id, body.month) and \
               str(_MOCK_ONE_TIME[key].get("employee_id")) in touched:
                del _MOCK_ONE_TIME[key]
        for i, r in enumerate(body.rows):
            _MOCK_ONE_TIME[(firm_id, body.client_id, body.month, f"mock-ote-{i}")] = {
                "id": f"mock-ote-{i}", "employee_id": str(r.employee_id).strip(),
                "kind": r.kind.strip().lower(), "label": r.label,
                "amount_paise": int(r.amount_paise),
                "pf_wages": bool(r.pf_wages), "esi_wages": bool(r.esi_wages),
                "taxable": bool(r.taxable),
                "payment_interval_months": r.payment_interval_months,
                "note": r.note, "entered_at": stamped,
            }
        return api_response(True, {"client_id": body.client_id, "month": body.month,
                                   "saved": len(body.rows),
                                   "employees_touched": len(touched)})

    # Delete-then-insert, scoped to the employees in the request. Not a
    # transaction — PostgREST exposes none here — so the insert is attempted
    # first for a single employee's worth of rows only after that employee's
    # rows are gone, and a failure leaves the month emptier rather than
    # doubled. Duplicated earnings are the worse outcome: they are paid.
    for i in range(0, len(touched), 200):
        (db.table("payroll_one_time_earnings").delete()
         .eq("firm_id", firm_id).eq("client_id", body.client_id)
         .eq("month", f"{body.month}-01")
         .in_("employee_id", touched[i:i + 200]).execute())

    if body.rows:
        db.table("payroll_one_time_earnings").insert(
            [{"firm_id": firm_id, "client_id": body.client_id,
              "month": f"{body.month}-01",
              "employee_id": str(r.employee_id).strip(),
              "kind": r.kind.strip().lower(),
              "label": r.label,
              "amount_paise": int(r.amount_paise),
              "pf_wages": bool(r.pf_wages),
              "esi_wages": bool(r.esi_wages),
              "taxable": bool(r.taxable),
              "payment_interval_months": r.payment_interval_months,
              "note": r.note,
              "entered_by": current_user.get("id"),
              "entered_at": stamped} for r in body.rows]).execute()

    timeline_service.log(
        body.client_id, "work", "Payroll Earnings Recorded",
        f"{len(body.rows)} one-time earning(s) recorded for {body.month}",
        "info", firm_id=firm_id, entity_type="client", entity_id=body.client_id,
        actor_id=current_user.get("auth_user_id"),
    )
    return api_response(True, {"client_id": body.client_id, "month": body.month,
                               "saved": len(body.rows),
                               "employees_touched": len(touched)})


@router.get("/one-time-earnings/defaults")
def one_time_earning_defaults(
    kind: str,
    payment_interval_months: Optional[int] = None,
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """What the three Acts say about this kind of payment, with the reasoning.

    A PROPOSAL for the form to prefill, not a decision. The row stores what was
    saved, because the interval test means "an incentive" answers differently at
    two clients and because a slip has to stay readable after these defaults
    change.
    """
    try:
        d = one_time_domain.statutory_defaults(kind, payment_interval_months)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return api_response(True, {
        "kind": kind, "payment_interval_months": payment_interval_months,
        "pf_wages": d.pf_wages, "esi_wages": d.esi_wages, "taxable": d.taxable,
        "reason": d.reason,
    })


@router.put("/attendance/settings")
def put_payroll_settings(
    body: PayrollSettingsIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """Record the day of the month this client has agreed to send inputs by.

    PATCH-shaped like the statutory identity: an explicit null clears the
    cut-off, which is a firm saying it has no agreed date — different from not
    saying, and the read reports the two differently.
    """
    assert_client_access(current_user, body.client_id)
    sent = body.model_dump(exclude_unset=True)
    update = {k: sent[k] for k in ("inputs_due_day", "note") if k in sent}
    if not update:
        raise HTTPException(status_code=422,
                            detail="Nothing to record. Send inputs_due_day.")
    if isinstance(update.get("note"), str):
        update["note"] = update["note"].strip() or None

    db = _db()
    firm_id = current_user["firm_id"]
    if not db:
        row = {**_MOCK_PAYROLL_SETTINGS.get((firm_id, body.client_id), {}), **update}
        _MOCK_PAYROLL_SETTINGS[(firm_id, body.client_id)] = row
        return api_response(True, {"client_id": body.client_id, **row})

    # Inline, not a payload variable, so the fixed column names are readable to
    # tests/test_backend_columns_exist_pg.py — see its MAX_UNREADABLE note.
    row = (db.table("client_payroll_settings")
           .upsert({"firm_id": firm_id, "client_id": body.client_id,
                    "updated_by": current_user.get("id"), **update},
                   on_conflict="firm_id,client_id").execute().data or [{}])[0]
    return api_response(True, {"client_id": body.client_id,
                               "inputs_due_day": row.get("inputs_due_day"),
                               "note": row.get("note")})


@router.get("/client-states")
def payroll_client_states(
    month: Optional[str] = Query(None, description='Payroll month, e.g. "2026-08". '
                                                   'Defaults to the current IST month.'),
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """Where every client of this firm stands on one payroll month.

    THE FIRM GRAIN. Every other payroll read in this router answers for ONE
    client, because that is where a month is completed. This one answers for the
    firm, because that is where a month is FOUND — and a CA firm's client list
    is the screen they actually open first.

    TWO QUERIES FOR THE WHOLE FIRM, not two per client. Both tables hold at most
    one row per client, so this is a few kilobytes whatever the firm's size; the
    per-client loop that would otherwise sit here is the shape
    docs/architecture/10-payroll.md's reporting rule exists to forbid.

    A client with payroll switched off is REPORTED, not omitted. "We do not run
    payroll for them" and "we do and have not started" are different answers,
    and a list that shows only the second cannot tell a CA which is which.

    SCOPED TO THE CALLER'S CLIENTS, not merely to their firm. This is the one
    payroll endpoint that answers for many clients at once, so it is also the
    one where firm scoping alone would be a leak: an Executive assigned to four
    clients would otherwise read the headcount and net pay of all forty. The
    filter is filter_by_client (core/authz.py), the same helper every other
    firm-wide list in this codebase uses, applied to the assembled rows rather
    than to each query — the rows are already keyed by client_id, and filtering
    once is both cheaper and impossible to apply to only half the data.
    """
    db = _db()
    firm_id = current_user["firm_id"]
    month = (month or ist_today().strftime("%Y-%m")).strip()

    if not db:
        return api_response(True, {"month": month, "clients": []})

    enabled = {}
    for row in ((db.table("client_payroll_settings")
                 .select("client_id, payroll_enabled, inputs_due_day")
                 .eq("firm_id", firm_id).execute().data) or []):
        enabled[str(row.get("client_id"))] = row

    runs = {}
    for row in ((db.table("payroll_runs")
                 .select("client_id, status, headcount, total_net_paise")
                 .eq("firm_id", firm_id).eq("month", month)
                 .execute().data) or []):
        runs[str(row.get("client_id"))] = row

    out = []
    for cid in sorted(set(enabled) | set(runs)):
        setting = enabled.get(cid) or {}
        run = runs.get(cid)
        out.append({
            "client_id": cid,
            "payroll_enabled": bool(setting.get("payroll_enabled")),
            "inputs_due_day": setting.get("inputs_due_day"),
            # None means no run for this month — which for an ENABLED client is
            # "not started" and for a disabled one is simply not applicable.
            # Left as None rather than invented, so the screen can say which.
            "run_status": (run or {}).get("status"),
            "headcount": (run or {}).get("headcount"),
            "total_net_paise": (run or {}).get("total_net_paise"),
        })
    return api_response(True, {"month": month,
                               "clients": filter_by_client(current_user, out)})


@router.put("/enablement")
def put_payroll_enablement(
    body: PayrollEnablementIn,
    current_user: dict = Depends(rbac("payroll", "enable"))
):
    """Switch payroll on or off for one client. PARTNER ONLY.

    THE COST BRAKE (migration 332, docs/architecture/10-payroll.md). Payroll is
    bundled into the subscription rather than priced per employee, so what bounds
    the firm's cost is a decision somebody made rather than how many clients
    happen to exist. It also keeps payroll off the screen for the clients that
    have none, which is most of them.

    A SEPARATE ENDPOINT FROM /attendance/settings, which writes the same row.
    That one is Manager+ — a Manager agreeing an input cut-off with a client is
    doing their job. This one commits the firm to running payroll for a client,
    which is a commercial act. Migration 332 also revokes the column from
    `authenticated` outright, so the browser cannot reach it through PostgREST
    under any policy and this is the only door.

    SWITCHING OFF DESTROYS NOTHING. Every payroll record stays readable — Form
    16s, the ECR history, payslips the employee portal serves — and only WRITES
    are refused. A switch that lost history would be one nobody dared use.
    """
    assert_client_access(current_user, body.client_id)
    assert_not_internal_for_payroll(body.client_id, current_user["firm_id"])

    db = _db()
    firm_id = current_user["firm_id"]
    # UTC on disk, as every timestamptz in this schema is. CLAUDE.md's IST rule
    # is about REPORTING a time, not storing one.
    stamped = datetime.now(timezone.utc).isoformat()

    if not db:
        row = {**_MOCK_PAYROLL_SETTINGS.get((firm_id, body.client_id), {}),
               "payroll_enabled": body.enabled,
               "payroll_enabled_by": current_user.get("id"),
               "payroll_enabled_on": stamped}
        if body.note is not None:
            row["note"] = (body.note or "").strip() or None
        _MOCK_PAYROLL_SETTINGS[(firm_id, body.client_id)] = row
        return api_response(True, {"client_id": body.client_id, **row})

    # Inline, not a payload variable, so the fixed column names are readable to
    # tests/test_backend_columns_exist_pg.py — see its MAX_UNREADABLE note.
    row = (db.table("client_payroll_settings")
           .upsert({"firm_id": firm_id, "client_id": body.client_id,
                    "payroll_enabled": body.enabled,
                    "payroll_enabled_by": current_user.get("id"),
                    "payroll_enabled_on": stamped,
                    "updated_by": current_user.get("id")},
                   on_conflict="firm_id,client_id").execute().data or [{}])[0]

    timeline_service.log(
        body.client_id, "work",
        "Payroll " + ("Enabled" if body.enabled else "Disabled"),
        ("Payroll switched on for this client"
         if body.enabled else
         "Payroll switched off for this client. Existing records stay readable."),
        "info", firm_id=firm_id, entity_type="client", entity_id=body.client_id,
        actor_id=current_user.get("auth_user_id"),
    )
    return api_response(True, {
        "client_id": body.client_id,
        "payroll_enabled": row.get("payroll_enabled"),
        "payroll_enabled_by": row.get("payroll_enabled_by"),
        "payroll_enabled_on": row.get("payroll_enabled_on"),
    })


# ── The client's own statutory registrations ─────────────────────────────────
# Migration 325. Three finished returns below — the ECR, the ESIC contribution
# file and Form 24Q — are returns BY AN ESTABLISHMENT, and until now nothing
# here held the number that identifies it. routers/tds.py still shows the hole:
# Compute24QRequest takes tan, deductor_name, deductor_pan and deductor_address
# in the request BODY, because there was nowhere to read them from.
#
# See domain/payroll/identity.py for why only the TAN is format-checked, and
# why a missing EPF or ESIC code is reported BESIDE a file rather than folded
# into its problems list.

#: Mock-mode store, keyed (firm_id, client_id) and (firm_id, client_id, state).
#: Same device as _MOCK_FINALIZED_RUNS above and for the same reason: the
#: ~7,000-test mock suite runs with SUPABASE_URL unset, and an endpoint that
#: echoed its input back without storing it could not exercise the gap logic
#: that is the whole point of the table.
_MOCK_IDENTITY: dict[tuple, dict] = {}
_MOCK_PT_REGISTRATIONS: dict[tuple, dict] = {}

_IDENTITY_COLUMNS = ("tan", "epf_establishment_code", "esic_employer_code", "lin", "note")


def _read_statutory_identity(db, firm_id: str, client_id: str) -> tuple[dict, list[dict]]:
    """The client's entity registrations and its per-state PT registrations.

    Returns ({}, []) rather than None when nothing is recorded: an absent row
    and a row with every field blank mean the same thing here, and callers all
    ask "is this identifier present", never "does a row exist".
    """
    if not db:
        ident = _MOCK_IDENTITY.get((firm_id, client_id), {})
        pt = [v for k, v in sorted(_MOCK_PT_REGISTRATIONS.items())
              if k[0] == firm_id and k[1] == client_id]
        return (dict(ident), [dict(r) for r in pt])
    try:
        # Columns named rather than "*" so tests/test_backend_columns_exist_pg.py
        # checks them against the real schema — a select list is the only place
        # in this file that names the five identifier columns literally.
        ident = (db.table("client_statutory_identity")
                 .select("tan, epf_establishment_code, esic_employer_code, lin, note")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .maybe_single().execute().data) or {}
        pt = (db.table("client_pt_registrations")
              .select("state, ptrc_number, ptec_number, note")
              .eq("firm_id", firm_id).eq("client_id", client_id)
              .order("state").execute().data) or []
    except Exception:
        # Degrades to "nothing recorded", which reports gaps rather than
        # emitting a return with a blank TAN. The other direction — treating a
        # failed read as "the identifier is fine" — is the one that files.
        _logger.exception("statutory identity read failed for client=%s", client_id)
        return ({}, [])
    return (ident, pt)


@router.get("/statutory-identity")
def get_statutory_identity(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """What this client files its statutory returns under, and what is missing.

    The `fields` block is the Setup screen's own description of itself — name,
    label and what each identifier is for — so the form and the API cannot
    drift into disagreeing about which registrations exist.
    """
    assert_client_access(current_user, client_id)
    ident, pt = _read_statutory_identity(_db(), current_user["firm_id"], client_id)
    return api_response(True, {
        "client_id": client_id,
        "identity": {k: ident.get(k) for k in _IDENTITY_COLUMNS},
        "pt_registrations": pt,
        "fields": [{"name": n, "label": lab, "used_for": use}
                   for n, lab, use in identity_domain.ENTITY_FIELDS],
    })


@router.put("/statutory-identity")
def put_statutory_identity(
    body: StatutoryIdentityIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """Record or amend the entity's registrations.

    PATCH-shaped: only the fields present in the request body are written, so
    a form that edits the EPF code cannot silently clear a TAN it never showed.
    An explicit empty string clears — that is a CA saying this client has none,
    which is a real answer and different from not saying.
    """
    assert_client_access(current_user, body.client_id)
    sent = body.model_dump(exclude_unset=True)

    update: dict = {}
    if "tan" in sent:
        try:
            update["tan"] = identity_domain.normalise_tan(sent["tan"])
        except identity_domain.IdentityError as e:
            raise HTTPException(status_code=422, detail=str(e))
    for col in ("epf_establishment_code", "esic_employer_code", "lin"):
        if col in sent:
            update[col] = identity_domain.normalise_code(sent[col])
    if "note" in sent:
        update["note"] = (sent["note"] or "").strip() or None

    if not update:
        raise HTTPException(status_code=422,
                            detail="Nothing to record. Send at least one registration number.")

    db = _db()
    firm_id = current_user["firm_id"]
    assert_payroll_enabled(db, firm_id, body.client_id)
    if not db:
        row = {**_MOCK_IDENTITY.get((firm_id, body.client_id), {}), **update}
        _MOCK_IDENTITY[(firm_id, body.client_id)] = row
        return api_response(True, {"client_id": body.client_id,
                                   "identity": {k: row.get(k) for k in _IDENTITY_COLUMNS}})

    # UNIQUE (firm_id, client_id) — migration 325 — is what makes this one row
    # per client rather than a new row every time somebody corrects a digit.
    #
    # Written INLINE rather than as a `payload` variable so that
    # tests/test_backend_columns_exist_pg.py can read the three fixed column
    # names and check them against the real schema; a dict built in a variable
    # is invisible to it. The `**update` spread stays unreadable to that
    # scanner by construction — its keys are chosen at runtime from what the
    # request sent, which is the whole point of the PATCH shape — and the GET
    # above names all four of them literally.
    row = (db.table("client_statutory_identity")
           .upsert({"firm_id": firm_id, "client_id": body.client_id,
                    "updated_by": current_user.get("id"), **update},
                   on_conflict="firm_id,client_id").execute().data or [{}])[0]
    timeline_service.log(
        body.client_id, "work", "Statutory Identity Updated",
        "Recorded " + ", ".join(sorted(update)) + " for statutory returns",
        "info", firm_id=firm_id, entity_type="client", entity_id=body.client_id,
        actor_id=current_user.get("auth_user_id"),
    )
    return api_response(True, {"client_id": body.client_id,
                               "identity": {k: row.get(k) for k in _IDENTITY_COLUMNS}})


@router.put("/statutory-identity/pt")
def put_pt_registration(
    body: PTRegistrationIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """Record one state's professional-tax registration.

    One row per (client, state): PT is a state levy under Article 276(2) and an
    employer with staff in two states holds two independent registrations.
    """
    assert_client_access(current_user, body.client_id)
    sent = body.model_dump(exclude_unset=True)
    update: dict = {}
    for col in ("ptrc_number", "ptec_number"):
        if col in sent:
            update[col] = identity_domain.normalise_code(sent[col])
    if "note" in sent:
        update["note"] = (sent["note"] or "").strip() or None
    if not update:
        raise HTTPException(status_code=422,
                            detail="Nothing to record. Send a PTRC or PTEC number.")

    db = _db()
    firm_id = current_user["firm_id"]
    assert_payroll_enabled(db, firm_id, body.client_id)
    key = (firm_id, body.client_id, body.state)
    if not db:
        row = {**_MOCK_PT_REGISTRATIONS.get(key, {}),
               "client_id": body.client_id, "state": body.state, **update}
        _MOCK_PT_REGISTRATIONS[key] = row
        return api_response(True, dict(row))

    # Inline for the same reason as the identity upsert above.
    row = (db.table("client_pt_registrations")
           .upsert({"firm_id": firm_id, "client_id": body.client_id,
                    "state": body.state, "updated_by": current_user.get("id"),
                    **update},
                   on_conflict="firm_id,client_id,state").execute().data or [{}])[0]
    return api_response(True, row)


@router.delete("/statutory-identity/pt")
def delete_pt_registration(
    client_id: str = Query(...),
    state: str = Query(..., description='Two-letter state code, e.g. "MH"'),
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """Remove a state's PT registration — the client no longer employs there.

    Deleting puts the state back into the run's statutory_gaps if anybody is
    still marked pt_applicable in it, which is the correct outcome: an employer
    deducting in a state it is not registered in is exactly what the gap says.
    """
    state = (state or "").strip().upper()
    assert_client_access(current_user, client_id)
    db = _db()
    firm_id = current_user["firm_id"]
    if not db:
        _MOCK_PT_REGISTRATIONS.pop((firm_id, client_id, state), None)
        return api_response(True, {"client_id": client_id, "state": state, "deleted": True})
    (db.table("client_pt_registrations").delete()
     .eq("firm_id", firm_id).eq("client_id", client_id).eq("state", state).execute())
    return api_response(True, {"client_id": client_id, "state": state, "deleted": True})


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

    # BESIDE the file, never inside ecr.problems. The establishment code is not
    # a field on an ECR — EPFO takes the establishment from the portal login —
    # so folding a missing one into problems would flip is_filable and withhold
    # a correct return over a piece of reference data. See
    # domain/payroll/identity.py.
    ident, _pt = _read_statutory_identity(db, current_user["firm_id"], run.get("client_id"))
    estab_gaps = identity_domain.ecr_gaps(ident)

    return api_response(True, {
        "run_id": run_id,
        "month": month,
        "filename": f"ECR_{month.replace('-', '')}.txt",
        "lines": ecr.to_text(),
        "members": [m.to_line() for m in ecr.members],
        "problems": ecr.problems,
        "totals": ecr.totals(),
        "filable": ecr.is_filable,
        "establishment_code": ident.get("epf_establishment_code"),
        "identity_gaps": [g.note for g in estab_gaps],
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

    _esic_identity, _ = _read_statutory_identity(
        db, current_user["firm_id"], run.get("client_id"))
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
        # Beside the file, for the same reason the ECR's establishment code is:
        # esic.gov.in takes the employer from the portal login, so a missing
        # code does not make the return wrong.
        "employer_code": _esic_identity.get("esic_employer_code"),
        "identity_gaps": [g.note for g in identity_domain.esic_gaps(_esic_identity)],
        "disclaimer": "CA REVIEW REQUIRED — upload this to the ESIC portal yourself. "
                      "Nothing has been transmitted.",
    })


@router.get("/24q-source")
def form_24q_from_payroll(
    client_id: str = Query(...),
    financial_year: Annotated[FYLabel, Query(description='e.g. "2026-27"')] = ...,
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
                                   "deductor": {}, "ready": False})

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

    # The deductor header — the four fields routers/tds.py's Compute24QRequest
    # has always taken from the request BODY, because until migration 325 there
    # was nowhere to read them from. A CA re-keyed the TAN every quarter, for
    # every client, and one wrong character files the quarter against somebody
    # else's account.
    #
    # UNLIKE the ECR and ESIC identifiers, a missing TAN is a PROBLEM and
    # therefore clears `ready`: the TAN is IN the return (IT Act s.203A).
    client_row = (db.table("clients")
                  .select("client_name, legal_name, pan, address_line1, address_line2, "
                          "city, state, pincode")
                  .eq("id", client_id).eq("firm_id", current_user["firm_id"])
                  .maybe_single().execute().data) or {}
    identity, _pt = _read_statutory_identity(db, current_user["firm_id"], client_id)
    deductor, deductor_problems = identity_domain.deductor_block(identity, client_row)
    src.problems.extend(deductor_problems)

    return api_response(True, {
        "deductor": deductor,
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
    financial_year: Annotated[FYLabel, Query(description='e.g. "2026-27"')] = ...,
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

    # Each employee's declaration for the year, so the annexure can carry the
    # regime they were withheld on and the reliefs their proofs supported. The
    # §10(13A) formula needs the employer's own figures, so the year's basic+DA
    # and HRA are totalled off the payslips and attached before the build.
    declarations = _declarations_for_run(
        db, current_user["firm_id"], client_id, financial_year)
    for emp_id, decl in declarations.items():
        emp_slips = [sl for sl in slips if sl.get("employee_id") == emp_id]
        declarations[emp_id] = _replace(
            decl,
            hra_basic_plus_da_paise=sum(int(sl.get("basic_paise") or 0)
                                        + int(sl.get("da_paise") or 0)
                                        for sl in emp_slips),
            hra_received_paise=sum(int(sl.get("hra_paise") or 0) for sl in emp_slips),
        )

    # §17(2) perquisites, valued under Rule 3 and recorded for the year
    # (migration 299). Read rather than recomputed: the annexure must agree with
    # what the CA reviewed, and two implementations of one valuation drift.
    perquisites: dict = {}
    for row in ((db.table("payroll_perquisites").select("*")
                 .eq("firm_id", current_user["firm_id"]).eq("client_id", client_id)
                 .eq("fy", financial_year).execute().data) or []):
        perquisites.setdefault(row.get("employee_id"), []).append(row)

    # A leaver's settlement is salary of the year of receipt (§15) and belongs
    # in this annexure like any other month's pay. Read as head-wise totals so
    # the builder can put §17(1)(va) leave encashment and §17(3) gratuity on
    # their own lines rather than lumping both into salary.
    settlements: dict = {}
    for row in ((db.table("payroll_settlements").select("*")
                 .eq("firm_id", current_user["firm_id"]).eq("client_id", client_id)
                 .eq("fy", financial_year).execute().data) or []):
        parts = (db.table("payroll_settlement_components").select("*")
                 .eq("settlement_id", row["id"]).execute().data) or []
        earnings = [p for p in parts if p.get("kind") != "deduction"]
        settlements[row.get("employee_id")] = {
            "gross_17_1_paise": sum(int(p.get("gross_paise") or 0)
                                    for p in earnings if p.get("tax_head") == "17(1)"),
            "gross_17_3_paise": sum(int(p.get("gross_paise") or 0)
                                    for p in earnings if p.get("tax_head") == "17(3)"),
            "exempt_paise": int(row.get("exempt_paise") or 0),
            "tds_paise": int(row.get("tds_paise") or 0),
        }

    rates = rates_for(financial_year)
    ann = build_annexure_ii(
        slips=slips,
        employees_by_id={e["id"]: e for e in employees},
        standard_deduction_paise=rates.new_regime_standard_deduction_paise,
        months_expected=len(usable) or 12,
        declarations_by_employee=declarations,
        perquisites_by_employee=perquisites,
        settlements_by_employee=settlements,
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


# ─── Employee income-tax declarations (IT Act §192, Rule 26C / Form 12BB) ─────
#
# Three statutory objects, kept apart — see domain/payroll/declarations.py for
# why conflating any two of them gets §192 wrong:
#   * the REGIME INTIMATION to the employer (Circular 04/2023) — withholding;
#   * the §115BAC(6) ELECTION (Form 10-IEA or the return) — the assessment;
#   * the FORM 12BB statement (Rule 26C) — the evidence.

@router.put("/declarations")
def upsert_declaration(
    body: DeclarationIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """Record or replace an employee's declaration for a financial year.

    Submitted, not draft: a declaration reaching this endpoint is one the
    employee is standing behind, and payroll withholds on it from the next run.
    Its Chapter VI-A lines are replaced wholesale rather than merged — a
    declaration is a statement of the whole year's intent, and merging would
    leave a withdrawn investment silently in place.

    Validation refuses what cannot be given effect (a missing landlord PAN
    above the Rule 26C threshold, a section this module does not compute) and
    reports separately, without refusing, the things a CA must know — chiefly
    that an old-regime intimation is not a §115BAC(6) election.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    assert_client_access(current_user, body.client_id)
    assert_not_internal_for_payroll(body.client_id, current_user["firm_id"])

    candidate = decl_domain.Declaration(
        employee_id=body.employee_id,
        fy=body.fy,
        regime=body.regime,
        status=decl_domain.STATUS_SUBMITTED,
        rent_paid_declared_paise=max(0, body.rent_paid_declared_paise),
        landlord_name=body.landlord_name or "",
        landlord_address=body.landlord_address or "",
        landlord_pan=(body.landlord_pan or "").upper(),
        rent_is_metro=bool(body.rent_is_metro),
        lta_declared_paise=max(0, body.lta_declared_paise),
        home_loan_interest_declared_paise=max(0, body.home_loan_interest_declared_paise),
        lender_name=body.lender_name or "",
        lender_pan=(body.lender_pan or "").upper(),
        other_income_declared_paise=max(0, body.other_income_declared_paise),
        house_property_loss_declared_paise=max(0, body.house_property_loss_declared_paise),
    )
    for it in body.items:
        candidate.items.append(decl_domain.DeclarationItem(
            section=it.section,
            label=it.label or "",
            amount_declared_paise=max(0, it.amount_declared_paise),
            proof_reference=it.proof_reference or "",
        ))

    problems = decl_domain.validate(candidate)
    if problems:
        raise HTTPException(status_code=422, detail={"problems": problems})

    db = _db()
    assert_payroll_enabled(db, current_user["firm_id"], body.client_id)
    if not db:
        return api_response(True, {"declaration": None, "problems": [],
                                   "notices": decl_domain.notices(candidate)})

    now = datetime.now(timezone.utc).isoformat()
    # Upserted on the (employee_id, fy) unique index from migration 296 rather
    # than select-then-branch: one declaration per employee per year is the
    # invariant, and a check-then-act would let two concurrent submissions each
    # pass the check and both insert.
    #
    # Re-declaring RESETS the verification. The figures the CA checked are no
    # longer the figures being claimed, and carrying the old verdict forward
    # would let a raised claim inherit the proof for a smaller one.
    #
    # The payload is written out in full rather than assembled in a helper so
    # tests/test_backend_columns_exist_pg.py can read the column names and check
    # them against the real schema — these tables are new, and the frontend will
    # write them directly through PostgREST where nothing else would catch a
    # misspelt column.
    row = (db.table("payroll_it_declarations").upsert({
        "firm_id": current_user["firm_id"],
        "client_id": body.client_id,
        "employee_id": body.employee_id,
        "fy": body.fy,
        "regime": body.regime,
        "status": decl_domain.STATUS_SUBMITTED,
        "rent_paid_declared_paise": max(0, body.rent_paid_declared_paise),
        "rent_paid_verified_paise": 0,
        "landlord_name": body.landlord_name or "",
        "landlord_address": body.landlord_address or "",
        "landlord_pan": (body.landlord_pan or "").upper(),
        "rent_is_metro": bool(body.rent_is_metro),
        "lta_declared_paise": max(0, body.lta_declared_paise),
        "lta_verified_paise": 0,
        "home_loan_interest_declared_paise": max(0, body.home_loan_interest_declared_paise),
        "home_loan_interest_verified_paise": 0,
        "lender_name": body.lender_name or "",
        "lender_pan": (body.lender_pan or "").upper(),
        "other_income_declared_paise": max(0, body.other_income_declared_paise),
        "house_property_loss_declared_paise": max(0, body.house_property_loss_declared_paise),
        "proofs_verified": False,
        "verified_at": None,
        "verified_by": None,
        "submitted_at": now,
        "updated_at": now,
    }, on_conflict="employee_id,fy").execute().data or [{}])[0]
    decl_id = row.get("id")

    # Chapter VI-A lines are replaced wholesale: a declaration states the whole
    # year's intent, and merging would leave a withdrawn investment in place.
    if decl_id:
        db.table("payroll_it_declaration_items").delete().eq("declaration_id", decl_id).execute()

    for i in candidate.items:
        if not decl_id:
            break
        # One literal insert per line rather than a comprehension, for the same
        # reason the header payload is spelled out: a comprehension is opaque to
        # the column check, and these columns have nothing else guarding them.
        db.table("payroll_it_declaration_items").insert({
            "firm_id": current_user["firm_id"],
            "declaration_id": decl_id,
            "section": i.section,
            "label": i.label,
            "amount_declared_paise": i.amount_declared_paise,
            "amount_verified_paise": 0,
            "status": decl_domain.ITEM_DECLARED,
            "proof_reference": i.proof_reference,
        }).execute()

    timeline_service.log(
        body.client_id, "work", "IT Declaration Recorded",
        f"§192 declaration recorded for {body.fy} on the "
        f"{body.regime} regime", "info",
        firm_id=current_user.get("firm_id", ""),
        entity_type="payroll_it_declaration", entity_id=decl_id,
        actor_id=current_user.get("auth_user_id"))

    return api_response(True, {
        "declaration_id": decl_id,
        "problems": [],
        "notices": decl_domain.notices(candidate),
    })


@router.get("/declarations")
def list_declarations(
    client_id: str = Query(...),
    fy: Annotated[FYLabel, Query()] = ...,
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """Every declaration for a client and financial year, with what is wrong
    with it and what the CA must know about it.

    PROBLEMS are reasons a claim cannot be allowed as it stands — a missing
    landlord PAN above the Rule 26C threshold, a section this module cannot
    give effect to. NOTICES are things that do not block: an old-regime
    intimation that still needs Form 10-IEA, a claim the new regime disallows,
    proofs outstanding with the fourth quarter approaching.

    Both are computed here rather than by the caller, and both matter for
    portal-filed declarations especially: an employee writes these tables
    directly through PostgREST and never passes through validate(), so this
    list is the first place anyone sees what is wrong with what they filed.
    """
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, {"declarations": []})

    heads = (db.table("payroll_it_declarations").select("*")
             .eq("firm_id", current_user["firm_id"]).eq("client_id", client_id)
             .eq("fy", fy).execute().data) or []
    items_by_decl: dict = {}
    if heads:
        rows = (db.table("payroll_it_declaration_items").select("*")
                .in_("declaration_id", [h["id"] for h in heads]).execute().data) or []
        for r in rows:
            items_by_decl.setdefault(r.get("declaration_id"), []).append(r)

    out = []
    for h in heads:
        d = _declaration_from_rows(h, items_by_decl.get(h["id"], []))
        out.append({**h,
                    "items": items_by_decl.get(h["id"], []),
                    # PROBLEMS as well as notices, because an employee filing
                    # through the portal writes the tables directly and never
                    # passes through this module's validate(). Rule 26C lives
                    # here, in one place; this list is where the person who has
                    # to act on it sees it. A declaration missing the landlord's
                    # PAN is a claim that cannot be allowed as it stands, and
                    # the CA needs to know that before Q4, not after.
                    "problems": decl_domain.validate(d),
                    "notices": decl_domain.notices(d)})
    return api_response(True, {"declarations": out})


@router.post("/declarations/{declaration_id}/verify")
def verify_declaration(
    declaration_id: str,
    body: DeclarationVerifyIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """Record what the proofs actually support.

    A verified amount may be LESS than what was declared and never more; the
    domain layer refuses the reverse and migration 296 carries the same rule as
    a CHECK constraint, because the frontend writes these tables directly
    through PostgREST where no endpoint validation runs at all.

    `proofs_verified` is the switch that matters. Until it is set, the declared
    figures keep reducing tax for the first three quarters; from the fourth they
    stop, because §192(1) makes the EMPLOYER answerable for a correct deduction
    and an unproved claim left in place becomes a Q4 shortfall with no salary
    left to recover it from.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    assert_client_access(current_user, body.client_id)
    db = _db()
    if not db:
        return api_response(True, {"declaration_id": declaration_id, "problems": []})

    head = (db.table("payroll_it_declarations").select("*")
            .eq("id", declaration_id).eq("firm_id", current_user["firm_id"])
            .maybe_single().execute().data)
    if not head:
        raise HTTPException(status_code=404, detail="Declaration not found")

    rows = (db.table("payroll_it_declaration_items").select("*")
            .eq("declaration_id", declaration_id).execute().data) or []
    by_section = {r.get("section"): r for r in rows}

    def _proved(value, declared_field: str, label: str) -> int:
        """A proof may support LESS than was claimed, never more."""
        declared = int(head.get(declared_field) or 0)
        if value is None:
            return int(head.get(declared_field.replace("declared", "verified")) or 0)
        if value > declared:
            raise HTTPException(
                status_code=422,
                detail=f"{label}: ₹{value / 100:,.2f} verified against "
                       f"₹{declared / 100:,.2f} declared. A proof can support less "
                       f"than was claimed, never more — raise the declaration first.")
        return max(0, int(value))

    now = datetime.now(timezone.utc).isoformat()

    for it in body.items:
        row = by_section.get(it.section)
        if not row:
            raise HTTPException(
                status_code=422,
                detail=f"No {it.section} line was declared, so there is nothing to "
                       f"verify against it.")
        declared = int(row.get("amount_declared_paise") or 0)
        verified = int(it.amount_verified_paise or 0)
        if verified > declared:
            raise HTTPException(
                status_code=422,
                detail=f"{it.section}: ₹{verified / 100:,.2f} verified against "
                       f"₹{declared / 100:,.2f} declared. A proof can support less "
                       f"than was claimed, never more — raise the declaration first.")
        db.table("payroll_it_declaration_items").update({
            "amount_verified_paise": max(0, verified),
            "status": it.status or decl_domain.ITEM_VERIFIED,
            "proof_reference": it.proof_reference or row.get("proof_reference") or "",
        }).eq("id", row["id"]).execute()

    # Spelled out rather than assembled, so the column check can read it.
    db.table("payroll_it_declarations").update({
        "proofs_verified": bool(body.proofs_verified),
        "rent_paid_verified_paise": _proved(
            body.rent_paid_verified_paise, "rent_paid_declared_paise", "Rent"),
        "lta_verified_paise": _proved(
            body.lta_verified_paise, "lta_declared_paise", "Leave travel"),
        "home_loan_interest_verified_paise": _proved(
            body.home_loan_interest_verified_paise,
            "home_loan_interest_declared_paise", "Home loan interest"),
        "status": (decl_domain.STATUS_VERIFIED if body.proofs_verified
                   else head.get("status") or decl_domain.STATUS_SUBMITTED),
        "verified_at": now if body.proofs_verified else head.get("verified_at"),
        "verified_by": (current_user.get("id") if body.proofs_verified
                        else head.get("verified_by")),
        "updated_at": now,
    }).eq("id", declaration_id).execute()

    timeline_service.log(
        body.client_id, "work", "IT Declaration Verified",
        f"Investment proofs reviewed for {head.get('fy')}", "info",
        firm_id=current_user.get("firm_id", ""),
        entity_type="payroll_it_declaration", entity_id=declaration_id,
        actor_id=current_user.get("auth_user_id"))

    return api_response(True, {"declaration_id": declaration_id, "problems": []})


# ─── Statutory position, computed here rather than in the browser ─────────────

@router.get("/statutory-position")
def statutory_position(
    client_id: str = Query(...),
    month: str = Query(..., description='"YYYY-MM"'),
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """PF, ESI and gratuity for every employee of a client, as at a month.

    Distinct from /reports/statutory-summary, which reports what a FINALISED RUN
    actually deducted. This one projects from the employee master and answers
    "where does each employee stand today" — including people no run has covered
    yet, and gratuity, which no run computes.

    THIS EXISTS BECAUSE THE FRONTEND WAS COMPUTING IT

    app/payroll/statutory/page.tsx carried its own calcPF, calcESIC and
    calcGratuity in TypeScript, with its own copies of the ₹15,000 and ₹21,000
    ceilings — against CLAUDE.md's rule that computation lives in apps/api. They
    had drifted from the backend in four ways, each of them wrong in a
    different direction:

      * PF was computed on BASIC ALONE. §6 of the EPF Act says basic wages plus
        dearness allowance, which task #229 fixed on the backend and never here.
        Every employee with a DA component had their PF understated.
      * the employer's 12% was split as a flat 3.67% / 8.33%. The EPS half is
        capped at 8.33% of the ceiling (₹1,250), so above the ceiling the split
        is not 3.67/8.33 at all — and eps_eligible (migration 295) was not
        considered, so a member excluded from EPS by GSR 609(E) was shown a
        pension contribution they do not get.
      * ESI ignored Rule 50: someone whose wages cross the ceiling mid-period
        stays in the scheme until the period ends.
      * gratuity read `emp.date_of_joining`, WHICH IS NOT A COLUMN. The column
        is joining_date (migration 093). Because the page selected "*", PostgREST
        returned rows without that key rather than erroring, so the value was
        undefined for everyone and GRATUITY DISPLAYED AS ZERO FOR EVERY
        EMPLOYEE, silently, for as long as the page has existed.

    All four are now one implementation, here, with the tests that already
    guard it.

    `as at a month` matters for gratuity: length of service is measured to the
    end of that month, so the figure is "what would be payable if they left
    now" — which is what a provision is for.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    assert_client_access(current_user, client_id)

    # Validated BEFORE the database is reached: whether the input is well formed
    # has nothing to do with whether there is a database behind it, and a
    # malformed month that returns an empty result instead of a 422 tells the
    # caller their query found nothing rather than that they asked wrongly.
    try:
        y, m = int(month[:4]), int(month[5:7])
        as_at = date(y, m, calendar.monthrange(y, m)[1])
    except (ValueError, IndexError):
        raise HTTPException(status_code=422, detail='month must be "YYYY-MM"')
    fy = _fy_for_month(month)

    db = _db()
    if not db:
        return api_response(True, {"month": month, "rows": [], "totals": {},
                                   "gaps": []})

    emps = (db.table("payroll_employees").select("*")
            .eq("firm_id", current_user["firm_id"]).eq("client_id", client_id)
            .eq("status", "active").execute().data) or []

    esi_covered_earlier = _members_contributing_earlier_this_period(
        db, current_user["firm_id"], client_id, month)

    rows: list[dict] = []
    gaps: list[str] = []
    totals = {"pf_employee_paise": 0, "pf_employer_paise": 0,
              "pf_employer_eps_paise": 0, "pf_employer_epf_paise": 0,
              "edli_paise": 0, "pf_admin_paise": 0,
              "esi_employee_paise": 0, "esi_employer_paise": 0,
              "gratuity_paise": 0}

    for emp in emps:
        basic = int(emp.get("basic_paise") or 0)
        da = _percent_of(basic, emp.get("da_percent", 0))
        hra = _percent_of(basic, emp.get("hra_percent", 0))
        gross = (basic + hra + da
                 + int(emp.get("lta_paise") or 0)
                 + int(emp.get("medical_paise") or 0)
                 + int(emp.get("special_allowance_paise") or 0)
                 + int(emp.get("other_allowances_paise") or 0))

        pf = (_compute_pf(basic + da, fy, eps_eligible=emp.get("eps_eligible", True))
              if emp.get("pf_applicable")
              else {"employee": 0, "employer": 0, "employer_eps": 0,
                    "employer_epf": 0, "edli": 0, "admin": 0})
        esi = (_compute_esi(gross, fy,
                            covered_at_period_start=emp["id"] in esi_covered_earlier)
               if emp.get("esi_applicable") else {"employee": 0, "employer": 0})

        joining = emp.get("joining_date")
        grat = gratuity_domain.compute(
            basic_plus_da_paise=basic + da,
            joining=date.fromisoformat(str(joining)) if joining else None,
            leaving=as_at,
            covered_by_the_act=bool(emp.get("gratuity_act_covered", True)),
        )
        for r in grat.reasons:
            # Not eligible yet is the ordinary case, not a problem worth
            # reporting for every junior employee in the firm. A MISSING
            # joining date is, because it is the one that looks identical.
            if not joining:
                gaps.append(f"{emp.get('name') or emp['id']}: {r}")

        rows.append({
            "employee_id": emp["id"],
            "name": emp.get("name"),
            "basic_paise": basic,
            "da_paise": da,
            "gross_paise": gross,
            "pf_applicable": bool(emp.get("pf_applicable")),
            "esi_applicable": bool(emp.get("esi_applicable")),
            "pf_employee_paise": pf["employee"],
            "pf_employer_paise": pf["employer"],
            "pf_employer_eps_paise": pf["employer_eps"],
            "pf_employer_epf_paise": pf["employer_epf"],
            "edli_paise": pf["edli"],
            "pf_admin_paise": pf["admin"],
            "eps_eligible": bool(emp.get("eps_eligible", True)),
            "esi_employee_paise": esi["employee"],
            "esi_employer_paise": esi["employer"],
            "joining_date": joining,
            "gratuity_payable_paise": grat.payable_paise,
            "gratuity_eligible": grat.eligible,
            "gratuity_years": grat.service_years_counted,
            "gratuity_reasons": grat.reasons,
        })
        totals["pf_employee_paise"] += pf["employee"]
        totals["pf_employer_paise"] += pf["employer"]
        totals["pf_employer_eps_paise"] += pf["employer_eps"]
        totals["pf_employer_epf_paise"] += pf["employer_epf"]
        totals["edli_paise"] += pf["edli"]
        totals["pf_admin_paise"] += pf["admin"]
        totals["esi_employee_paise"] += esi["employee"]
        totals["esi_employer_paise"] += esi["employer"]
        totals["gratuity_paise"] += grat.payable_paise

    # The EPF administrative charge has a statutory MINIMUM of ₹500 a month per
    # ESTABLISHMENT, not per member — so it can only be settled on the run
    # total, never on one payslip. MOVED to domain/payroll/statutory.py rather
    # than copied when create_run needed the same rule: two implementations of
    # one statutory floor drift, and this one was the only place that had it.
    totals["pf_admin_paise"] = payroll_admin_charge(totals["pf_admin_paise"], fy)

    return api_response(True, {
        "month": month, "financial_year": fy,
        "rows": rows, "totals": totals, "gaps": gaps,
    })


# ─── Full and final settlement ───────────────────────────────────────────────

class SettlementIn(BaseModel):
    """What only a human knows about a departure.

    Everything else — length of service, wages, PF, the gratuity and leave
    formulae — comes off the employee master and the year's payslips. These are
    the facts no record holds: why they left, what the contract says about
    notice, and what they still owe.
    """
    client_id: str
    leaving_date: str                      # ISO
    on_death_or_disablement: bool = False
    on_retirement: bool = True             # decides §10(10AA) entirely
    is_government_employee: bool = False

    salary_to_last_day_paise: int = 0
    leave_days_encashed: int = 0
    leave_encashment_paise: int = 0

    # §12 of the Bonus Act compares ₹7,000 with the minimum wage for the
    # scheduled employment. There is no table of those; supplying it is a
    # human step.
    bonus_accounting_year: Optional[str] = None
    bonus_rate_bps: int = 833
    bonus_months_worked: int = 0
    bonus_working_days: int = 0
    minimum_wage_monthly_paise: Optional[int] = None

    notice_pay_recovered_paise: int = 0
    loans_outstanding_paise: int = 0
    other_recoveries_paise: int = 0

    # Lifetime limits under §10(10) and §10(10AA) are aggregated across
    # employers. Absent, the full limit is assumed and the response says so.
    gratuity_exemption_already_used_paise: Optional[int] = None
    leave_exemption_already_used_paise: Optional[int] = None
    gratuity_amount_actually_paid_paise: Optional[int] = None
    average_last_ten_months_paise: Optional[int] = None


def _parse_leaving_date(value: str) -> date:
    """Validated BEFORE the database is reached, in both settlement endpoints.

    Whether the input is well formed has nothing to do with whether there is a
    database behind it, and a malformed date that returns an empty result
    instead of a 422 tells the caller their request found nothing rather than
    that they asked wrongly.
    """
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422,
                            detail="leaving_date must be ISO (YYYY-MM-DD)")


def _compose_settlement(emp: dict, body: "SettlementIn"):
    """(settlement, gratuity result, leaving date) from an employee and the facts.

    ONE computation path, shared by the preview and the recording. A second copy
    would drift, and the drift would be invisible: a CA would approve one set of
    figures on screen and a different set would reach the ledger.
    """
    leaving = _parse_leaving_date(body.leaving_date)

    basic = int(emp.get("basic_paise") or 0)
    da = _percent_of(basic, emp.get("da_percent", 0))
    joining = emp.get("joining_date")

    grat = gratuity_domain.compute(
        basic_plus_da_paise=basic + da,
        joining=date.fromisoformat(str(joining)) if joining else None,
        leaving=leaving,
        covered_by_the_act=bool(emp.get("gratuity_act_covered", True)),
        on_death_or_disablement=body.on_death_or_disablement,
        amount_actually_paid_paise=body.gratuity_amount_actually_paid_paise,
        exemption_already_used_paise=body.gratuity_exemption_already_used_paise,
        average_last_ten_months_paise=body.average_last_ten_months_paise,
    )

    leave = None
    if body.leave_encashment_paise or body.leave_days_encashed:
        leave = leave_domain.compute(
            amount_received_paise=body.leave_encashment_paise,
            average_monthly_salary_paise=(body.average_last_ten_months_paise
                                          if body.average_last_ten_months_paise is not None
                                          else basic + da),
            completed_years_of_service=grat.completed_years,
            leave_days_encashed=body.leave_days_encashed,
            on_retirement=body.on_retirement,
            is_government_employee=body.is_government_employee,
            exemption_already_used_paise=body.leave_exemption_already_used_paise,
        )
        if body.average_last_ten_months_paise is None:
            leave.gaps.append(
                "§10(10AA)'s 'average salary' is the average of the LAST TEN "
                "MONTHS' basic and DA. The current rate was used instead. Where "
                "pay changed in the final ten months the two differ, and the "
                "average is the one the section asks for."
            )

    bon = None
    if body.bonus_accounting_year:
        bon = bonus_domain.compute(
            accounting_year=body.bonus_accounting_year,
            monthly_salary_paise=basic + da,
            months_worked=body.bonus_months_worked,
            working_days_in_year=body.bonus_working_days,
            rate_bps=body.bonus_rate_bps,
            minimum_wage_monthly_paise=body.minimum_wage_monthly_paise,
        )

    s_ = settlement_domain.build(
        salary_to_last_day_paise=body.salary_to_last_day_paise,
        gratuity=grat if (grat.eligible or grat.reasons) else None,
        leave=leave,
        bonus=bon,
        notice_pay_recovered_paise=body.notice_pay_recovered_paise,
        loans_outstanding_paise=body.loans_outstanding_paise,
        other_recoveries_paise=body.other_recoveries_paise,
    )
    # A gratuity that is simply not due yet is an answer, not a gap — but it has
    # to be visible, or a CA cannot tell "nil" from "not computed".
    if grat.reasons:
        s_.gaps.extend(grat.reasons)
    return s_, grat, leaving


def _settlement_payload(employee_id: str, emp: dict, s, grat, body) -> dict:
    """The response shape, shared so a preview and a recording describe the same
    thing in the same words."""
    return {
        "employee_id": employee_id,
        "employee_name": emp.get("name"),
        "leaving_date": body.leaving_date,
        "components": [
            {"label": c.label, "gross_paise": c.gross_paise,
             "exempt_paise": c.exempt_paise, "taxable_paise": c.taxable_paise,
             "statute": c.statute, "tax_head": c.tax_head,
             "exempt_section": c.exempt_section}
            for c in s.components
        ],
        "deductions": [
            {"label": d.label, "gross_paise": d.gross_paise, "statute": d.statute}
            for d in s.deductions
        ],
        "totals": {
            "gross_paise": s.gross_paise,
            "exempt_paise": s.exempt_paise,
            # What belongs in the salary head for the year. Recoveries do not
            # reduce it — taking notice pay back does not un-earn the salary.
            "taxable_paise": s.taxable_paise,
            "deductions_paise": s.deductions_paise,
            "net_payable_paise": s.net_payable_paise,
            "gross_17_1_paise": s.gross_by_head(settlement_domain.HEAD_17_1),
            "gross_17_3_paise": s.gross_by_head(settlement_domain.HEAD_17_3),
        },
        "exempt_by_section": s.exempt_by_section(),
        "gratuity_detail": {
            "eligible": grat.eligible,
            "completed_years": grat.completed_years,
            "years_counted": grat.service_years_counted,
            "payable_paise": grat.payable_paise,
            "exempt_paise": grat.exempt_paise,
        },
        "gaps": s.gaps,
        "problems": s.problems,
    }


@router.post("/employees/{employee_id}/settlement")
def preview_settlement(
    employee_id: str,
    body: SettlementIn,
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """What a leaver is owed — computed, not written.

    A leaver's last payment is not a payslip with a different date on it. It is
    a composition of separate entitlements, each with its own statute, its own
    base and its own tax treatment, netted against what the employee owes back.
    Each component is computed by the module that owns its statute
    (domain/payroll/gratuity.py, leave_encashment.py, bonus.py) and composed by
    settlement.py; nothing here re-derives any of them.

    Read-only on purpose. Recording it is a separate call, because settling an
    employee ends their employment, releases money, posts to the general ledger
    and fixes their §17(1) for the year — none of which should happen as a side
    effect of a preview.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    assert_client_access(current_user, body.client_id)
    _parse_leaving_date(body.leaving_date)

    db = _db()
    if not db:
        return api_response(True, {"employee_id": employee_id, "components": [],
                                   "deductions": [], "totals": {}, "gaps": [],
                                   "problems": []})

    emp = (db.table("payroll_employees").select("*")
           .eq("id", employee_id).eq("firm_id", current_user["firm_id"])
           .maybe_single().execute().data)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    s, grat, _ = _compose_settlement(emp, body)
    payload = _settlement_payload(employee_id, emp, s, grat, body)
    payload["disclaimer"] = ("CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing "
                             "here is written, paid or filed.")
    return api_response(True, payload)


class SettlementRecordIn(SettlementIn):
    """Recording adds the two facts a preview does not need."""
    # Marks the employee. The Act does not distinguish, but the employer's own
    # records do, and §9 of the Bonus Act turns on dismissal rather than exit.
    new_status: str = "resigned"
    # Set when the money actually left, so the ledger date is the payment date
    # rather than the day someone happened to press the button.
    payment_date: Optional[str] = None


@router.post("/employees/{employee_id}/settlement/record")
def record_settlement(
    employee_id: str,
    body: SettlementRecordIn,
    current_user: dict = Depends(rbac("payroll", "finalize"))
):
    """Record a leaver's settlement: store it, withhold on it, post it, close them.

    Until this existed the settlement was computed and NOTHING CONSUMED IT — no
    ledger entry, no withholding, and no §17(1) for the year, so a CA read the
    figures off a screen and re-entered the taxable part by hand before Q4.

    What this does, in the order it matters:

      1. COMPOSES the settlement through the same path the preview uses. One
         computation, so the figures a CA approved are the figures recorded.

      2. WITHHOLDS under §192. The taxable part is salary of the year of
         RECEIPT (§15), so it is added to the year's projected income and the
         tax already deducted is credited against it — §192(3)'s adjustment,
         the same one every month's payroll makes. Floored at zero: §192
         authorises deducting tax, not refunding it.

      3. POSTS to the general ledger, through the one posting kernel.

      4. MARKS the employee resigned or terminated with their leaving date, so
         no later run pays them again.

    Refused where the settlement has PROBLEMS — an employee owing more than the
    settlement covers has nothing to pay and a debt to collect separately, and
    posting a negative payment would be a fiction. Gaps do not block: a missing
    minimum wage or an unknown prior exemption makes a figure uncertain, not
    wrong, and blocking on them would stop a CA settling anybody.

    Guarded at payroll:finalize — Partner — because this releases money and ends
    an employment, which is the same weight as finalising a run.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    assert_client_access(current_user, body.client_id)
    assert_not_internal_for_payroll(body.client_id, current_user["firm_id"])

    if body.new_status not in ("resigned", "terminated"):
        raise HTTPException(
            status_code=422,
            detail="new_status must be 'resigned' or 'terminated'.")
    _parse_leaving_date(body.leaving_date)

    db = _db()
    assert_payroll_enabled(db, current_user["firm_id"], body.client_id)
    if not db:
        return api_response(True, {"employee_id": employee_id, "recorded": False})

    emp = (db.table("payroll_employees").select("*")
           .eq("id", employee_id).eq("firm_id", current_user["firm_id"])
           .maybe_single().execute().data)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    s, grat, leaving = _compose_settlement(emp, body)

    if s.problems:
        raise HTTPException(status_code=409, detail={"problems": s.problems})

    already = (db.table("payroll_settlements").select("id")
               .eq("firm_id", current_user["firm_id"])
               .eq("employee_id", employee_id)
               .eq("leaving_date", leaving.isoformat()).execute().data) or []
    if already:
        raise HTTPException(
            status_code=409,
            detail="This departure has already been settled. Settling it twice "
                   "would double the gratuity, the ledger entry and the §17(1) "
                   "figure — each of which looks correct on its own.")

    fy = _fy_for_month(leaving.isoformat()[:7])

    # ── §192 on the taxable part ─────────────────────────────────────────────
    # Salary of the year of RECEIPT (§15). Added to what the year has already
    # paid, with the tax already deducted credited against it — §192(3)'s
    # adjustment, exactly as a monthly run makes it.
    ytd = _tds_already_deducted_this_fy(
        db, current_user["firm_id"], body.client_id, "9999-99", fy)
    tds_paid, _months, gross_paid = ytd.get(employee_id, (0, 0, 0))
    declarations = _declarations_for_run(
        db, current_user["firm_id"], body.client_id, fy)

    annual_tax = decl_domain.withholding_tax_paise(
        decl=declarations.get(employee_id),
        projected_annual_salary_paise=gross_paid + s.taxable_paise,
        fy=fy,
        # A settlement is the end of the employment, so nothing is coming that
        # could still be proved. Only what was verified counts.
        verified_only=True,
    )
    tds = max(0, annual_tax - max(0, tds_paid))
    net_paid = max(0, s.net_payable_paise - tds)

    # ── Store ────────────────────────────────────────────────────────────────
    row = (db.table("payroll_settlements").insert({
        "firm_id": current_user["firm_id"],
        "client_id": body.client_id,
        "employee_id": employee_id,
        "fy": fy or "",
        "leaving_date": leaving.isoformat(),
        "gross_paise": s.gross_paise,
        "exempt_paise": s.exempt_paise,
        "taxable_paise": s.taxable_paise,
        "deductions_paise": s.deductions_paise,
        "tds_paise": tds,
        "net_paid_paise": net_paid,
        "created_by": current_user.get("id"),
    }).execute().data or [{}])[0]
    settlement_id = row.get("id")

    for c in s.components:
        db.table("payroll_settlement_components").insert({
            "firm_id": current_user["firm_id"],
            "settlement_id": settlement_id,
            "kind": "earning",
            "label": c.label,
            "gross_paise": c.gross_paise,
            "exempt_paise": c.exempt_paise,
            "tax_head": c.tax_head,
            "exempt_section": c.exempt_section,
            "statute": c.statute,
        }).execute()
    for d in s.deductions:
        db.table("payroll_settlement_components").insert({
            "firm_id": current_user["firm_id"],
            "settlement_id": settlement_id,
            "kind": "deduction",
            "label": d.label,
            "gross_paise": d.gross_paise,
            "exempt_paise": 0,
            "tax_head": settlement_domain.HEAD_17_1,
            "exempt_section": "",
            "statute": d.statute,
        }).execute()

    # ── Post ─────────────────────────────────────────────────────────────────
    journal_id = None
    try:
        from services.phase2_journal_service import Phase2JournalService
        journal_id = Phase2JournalService().journal_for_settlement(
            settlement={
                "id": settlement_id,
                "leaving_date": leaving.isoformat(),
                "payment_date": body.payment_date or leaving.isoformat(),
                "gross_paise": s.gross_paise,
                "tds_paise": tds,
                "net_paid_paise": net_paid,
                "loan_recovery_paise": max(0, body.loans_outstanding_paise),
                "cost_reductions_paise": (max(0, body.notice_pay_recovered_paise)
                                          + max(0, body.other_recoveries_paise)),
                "employee_name": emp.get("name") or "",
            },
            firm_id=current_user["firm_id"], client_id=body.client_id)
        if journal_id:
            db.table("payroll_settlements").update(
                {"journal_entry_id": journal_id}).eq("id", settlement_id).execute()
    except Exception:
        # The settlement is already stored. Rolling it back because the ledger
        # refused would lose the computation a Partner just approved, and the
        # posting is retryable against a stored settlement; an unposted one is
        # visible because journal_entry_id is null.
        _logger.exception("could not post the settlement journal for %s", settlement_id)

    # ── Close the employee ───────────────────────────────────────────────────
    db.table("payroll_employees").update({
        "status": body.new_status,
        "is_active": False,
    }).eq("id", employee_id).eq("firm_id", current_user["firm_id"]).execute()

    timeline_service.log(
        body.client_id, "work", "Settlement Recorded",
        f"{emp.get('name') or 'Employee'} settled on {leaving.isoformat()} — "
        f"net ₹{net_paid / 100:,.2f}", "info",
        firm_id=current_user.get("firm_id", ""),
        entity_type="payroll_settlement", entity_id=settlement_id,
        actor_id=current_user.get("auth_user_id"))

    payload = _settlement_payload(employee_id, emp, s, grat, body)
    payload.update({
        "settlement_id": settlement_id,
        "financial_year": fy,
        "tds_paise": tds,
        "net_paid_paise": net_paid,
        "journal_entry_id": journal_id,
        "posted": bool(journal_id),
        "employee_status": body.new_status,
        "disclaimer": "CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Recorded and "
                      "posted; nothing has been filed with any authority.",
    })
    if not journal_id:
        payload["problems"] = list(payload.get("problems") or []) + [
            "The settlement is recorded but its ledger entry did not post. It is "
            "retryable, and until it posts the salary cost is missing from the "
            "books — see the server log for why."
        ]
    return api_response(True, payload)


# ─── Arrears and §89(1) relief ───────────────────────────────────────────────

class ArrearSliceIn(BaseModel):
    fy: FYLabel
    amount_paise: int
    # The employee's total income for that year AS ORIGINALLY ASSESSED. It comes
    # off their own return, not from payroll — the employer never held it.
    total_income_that_year_paise: Optional[int] = None


class ArrearsReliefIn(BaseModel):
    client_id: str
    receipt_fy: str
    total_income_receipt_year_paise: int
    arrears: list[ArrearSliceIn] = []
    use_new_regime: bool = True
    # The proviso to §89 read with Rule 21AA: no Form 10E, no relief.
    form_10e_acknowledgement: Optional[str] = None


@router.post("/employees/{employee_id}/arrears-relief")
def arrears_relief(
    employee_id: str,
    body: ArrearsReliefIn,
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """§89(1) relief on salary arrears, per Rule 21A(2).

    Salary is taxed in the year of RECEIPT (§15), so a revision backdated three
    years lands three years' arrears in one year's income and pushes the
    employee through slabs they would never have reached. §89 compares the tax
    with what would have been paid had each instalment fallen in its own year,
    and relieves the excess.

    Two refusals rather than plausible numbers:

      * a year the statutory rate registry does not hold. rates_for() returns
        the latest verified year's figures for a year it lacks — the documented
        convention — and §89 is a comparison of years AT THEIR OWN RATES, so a
        substitute turns the whole computation into a fiction that looks
        reasonable.
      * no Form 10E. The proviso to §89, read with Rule 21AA, bars relief
        unless it was filed before the return; a return claiming §89 without one
        draws a §143(1) intimation disallowing the relief in full. The amount is
        still computed and shown, so the CA can see what filing the form is
        worth.

    Computes and returns; writes nothing.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    assert_client_access(current_user, body.client_id)

    result = arrears_domain.compute_relief(
        receipt_fy=body.receipt_fy,
        total_income_receipt_year_paise=body.total_income_receipt_year_paise,
        arrears=[arrears_domain.ArrearSlice(
            fy=a.fy, amount_paise=a.amount_paise,
            total_income_that_year_paise=a.total_income_that_year_paise)
            for a in body.arrears],
        use_new_regime=body.use_new_regime,
        form_10e_acknowledgement=body.form_10e_acknowledgement,
    )
    return api_response(True, {
        "employee_id": employee_id,
        "receipt_fy": body.receipt_fy,
        "relief_paise": result.relief_paise,
        "available": result.available,
        "blocked_reason": result.blocked_reason,
        "tax_with_arrears_paise": result.tax_on_receipt_year_with_arrears_paise,
        "tax_without_arrears_paise": result.tax_on_receipt_year_without_arrears_paise,
        "difference_a_paise": result.difference_a_paise,
        "difference_b_paise": result.difference_b_paise,
        "per_year": result.per_year,
        "gaps": result.gaps,
        "disclaimer": "CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Form 10E must be "
                      "filed on the e-filing portal before the return; nothing "
                      "here files it.",
    })


# ─── §17(2) perquisites, valued under Rule 3 ─────────────────────────────────

class PerquisiteValuationIn(BaseModel):
    """Rule 3's inputs. Each block is optional — an employee with a car and no
    flat sends only the car."""
    client_id: str
    fy: FYLabel
    salary_for_rule_3_paise: int = 0

    # Rule 3(1) — accommodation
    accommodation: bool = False
    population_lakh: int = 0
    accommodation_months: int = 12
    employer_owns_accommodation: bool = True
    actual_lease_rent_paise: int = 0
    rent_recovered_from_employee_paise: int = 0

    # Rule 3(2) — motor car
    motor_car: bool = False
    car_months: int = 12
    engine_litres: float = 1.4
    employer_bears_running_costs: bool = True
    with_driver: bool = False
    car_wholly_official: bool = False
    car_wholly_personal: bool = False
    car_amount_recovered_paise: int = 0

    # Rule 3(7)(i) — concessional loan
    loan: bool = False
    loan_maximum_outstanding_paise: int = 0
    # Published by SBI on the first day of the previous year. Not derivable —
    # absent it the loan is refused rather than valued at a guess.
    sbi_rate_bps: Optional[int] = None
    loan_interest_charged_paise: int = 0
    loan_months: int = 12
    loan_for_specified_disease: bool = False

    # Rule 3(7)(iii) and (iv)
    meals_provided: int = 0
    cost_per_meal_paise: int = 0
    gifts_total_paise: int = 0


@router.post("/employees/{employee_id}/perquisites/value")
def value_perquisites(
    employee_id: str,
    body: PerquisiteValuationIn,
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """Value an employee's §17(2) perquisites under Rule 3. Computes only.

    Separate from recording them, because the two are different decisions: what
    Rule 3 says a benefit is worth, and whether the firm accepts that valuation
    for the year. The second changes an employee's taxable salary and their Form
    16, so it is an explicit act rather than a side effect of a calculation.

    Anything Rule 3 needs and payroll cannot supply comes back as a gap rather
    than a number: the SBI rate for a concessional loan, and the actual running
    expenditure for a car used wholly privately.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    assert_client_access(current_user, body.client_id)

    result = perq_domain.PerquisiteResult()

    if body.accommodation:
        item, gaps = perq_domain.value_accommodation(
            fy=body.fy,
            salary_for_rule_3_paise=body.salary_for_rule_3_paise,
            population_lakh=body.population_lakh,
            months=body.accommodation_months,
            employer_owns=body.employer_owns_accommodation,
            actual_lease_rent_paise=body.actual_lease_rent_paise,
            rent_recovered_from_employee_paise=body.rent_recovered_from_employee_paise,
        )
        result.items.append(item)
        result.gaps.extend(gaps)

    if body.motor_car:
        item, gaps = perq_domain.value_motor_car(
            months=body.car_months, engine_litres=body.engine_litres,
            employer_bears_running_costs=body.employer_bears_running_costs,
            with_driver=body.with_driver,
            wholly_official=body.car_wholly_official,
            wholly_personal=body.car_wholly_personal,
            amount_recovered_paise=body.car_amount_recovered_paise,
        )
        if item is not None:
            result.items.append(item)
        result.gaps.extend(gaps)

    if body.loan:
        item, gaps = perq_domain.value_concessional_loan(
            maximum_monthly_outstanding_paise=body.loan_maximum_outstanding_paise,
            sbi_rate_bps_on_first_day=body.sbi_rate_bps,
            interest_actually_charged_paise=body.loan_interest_charged_paise,
            months=body.loan_months,
            for_specified_disease=body.loan_for_specified_disease,
        )
        if item is not None:
            result.items.append(item)
        result.gaps.extend(gaps)

    if body.meals_provided:
        result.items.append(perq_domain.value_meals(
            meals_provided=body.meals_provided,
            cost_per_meal_paise=body.cost_per_meal_paise))

    if body.gifts_total_paise:
        result.items.append(perq_domain.value_gifts(
            total_gifts_paise=body.gifts_total_paise))

    return api_response(True, {
        "employee_id": employee_id,
        "fy": body.fy,
        "items": [{"label": i.label, "value_paise": i.value_paise,
                   "rule": i.rule, "note": i.note} for i in result.items],
        "total_paise": result.total_paise,
        "gaps": result.gaps,
        "disclaimer": "CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing is "
                      "recorded until it is saved separately.",
    })


class PerquisiteRecordIn(BaseModel):
    client_id: str
    fy: FYLabel
    items: list[dict] = []


@router.put("/employees/{employee_id}/perquisites")
def record_perquisites(
    employee_id: str,
    body: PerquisiteRecordIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """Record the year's perquisite valuations for an employee.

    Replaces the year's set wholesale rather than merging, for the same reason
    a declaration's Chapter VI-A lines are replaced: this is a statement of the
    whole year's position, and merging would leave a withdrawn benefit — a car
    returned in June — valued for the full year.

    These figures reach the employee's Form 16 through 24Q Annexure II, so they
    are written at payroll:write, the same tier that edits pay.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    assert_client_access(current_user, body.client_id)
    assert_not_internal_for_payroll(body.client_id, current_user["firm_id"])
    db = _db()
    assert_payroll_enabled(db, current_user["firm_id"], body.client_id)
    if not db:
        return api_response(True, {"employee_id": employee_id, "recorded": 0})

    db.table("payroll_perquisites").delete() \
        .eq("firm_id", current_user["firm_id"]) \
        .eq("employee_id", employee_id).eq("fy", body.fy).execute()

    recorded = 0
    for item in body.items:
        value = int(item.get("value_paise") or 0)
        if value < 0:
            raise HTTPException(
                status_code=422,
                detail=f"{item.get('label')}: a perquisite cannot be negative.")
        # Written out literally so tests/test_backend_columns_exist_pg.py can
        # read the column names — see the declaration endpoints for why.
        db.table("payroll_perquisites").insert({
            "firm_id": current_user["firm_id"],
            "client_id": body.client_id,
            "employee_id": employee_id,
            "fy": body.fy,
            "label": str(item.get("label") or "Perquisite"),
            "rule": str(item.get("rule") or ""),
            "value_paise": value,
            "note": str(item.get("note") or ""),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        recorded += 1

    timeline_service.log(
        body.client_id, "work", "Perquisites Valued",
        f"§17(2) perquisites recorded for {body.fy} ({recorded} line"
        f"{'' if recorded == 1 else 's'})", "info",
        firm_id=current_user.get("firm_id", ""),
        entity_type="payroll_employee", entity_id=employee_id,
        actor_id=current_user.get("auth_user_id"))

    return api_response(True, {"employee_id": employee_id, "fy": body.fy,
                               "recorded": recorded})


# ─── Salary revisions and employee loans ─────────────────────────────────────

class SalaryRevisionIn(BaseModel):
    """The whole component set as at an effective date, not a delta.

    Deltas compose, and composing them across a backdated revision inserted
    between two others gives a different answer depending on the order they
    were entered.
    """
    client_id: str
    effective_from: str                    # ISO date
    basic_paise: int = 0
    hra_percent: float = 0
    da_percent: float = 0
    lta_paise: int = 0
    medical_paise: int = 0
    special_allowance_paise: int = 0
    other_allowances_paise: int = 0
    reason: str = ""


@router.post("/employees/{employee_id}/salary-revisions")
def add_salary_revision(
    employee_id: str,
    body: SalaryRevisionIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """Record a salary revision effective from a date.

    A month's payroll uses the latest revision effective on or before that
    month's first day, so one may be entered in advance without affecting the
    months before it — and a BACKDATED one, which is the ordinary case since
    increments are usually agreed months after they take effect, gives arrears
    something to be computed from.

    Recording a revision does not re-run anything. Months already finalised keep
    the figures they were paid on, because payroll_slips stores each component
    as paid; what a backdated revision creates is a DIFFERENCE, and settling it
    is a separate decision (see /arrears-relief for the §89 side).

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    assert_client_access(current_user, body.client_id)
    assert_not_internal_for_payroll(body.client_id, current_user["firm_id"])
    try:
        effective = date.fromisoformat(body.effective_from)
    except ValueError:
        raise HTTPException(status_code=422,
                            detail="effective_from must be ISO (YYYY-MM-DD)")
    if body.basic_paise < 0:
        raise HTTPException(status_code=422, detail="basic cannot be negative")

    db = _db()
    assert_payroll_enabled(db, current_user["firm_id"], body.client_id)
    if not db:
        return api_response(True, {"employee_id": employee_id, "recorded": False})

    row = (db.table("payroll_salary_revisions").insert({
        "firm_id": current_user["firm_id"],
        "client_id": body.client_id,
        "employee_id": employee_id,
        "effective_from": effective.isoformat(),
        "basic_paise": body.basic_paise,
        "hra_percent": body.hra_percent,
        "da_percent": body.da_percent,
        "lta_paise": body.lta_paise,
        "medical_paise": body.medical_paise,
        "special_allowance_paise": body.special_allowance_paise,
        "other_allowances_paise": body.other_allowances_paise,
        "reason": body.reason,
        "created_by": current_user.get("id"),
    }).execute().data or [{}])[0]

    timeline_service.log(
        body.client_id, "work", "Salary Revised",
        f"Revision effective {effective.isoformat()}"
        f"{': ' + body.reason if body.reason else ''}", "info",
        firm_id=current_user.get("firm_id", ""),
        entity_type="payroll_employee", entity_id=employee_id,
        actor_id=current_user.get("auth_user_id"))

    return api_response(True, {"employee_id": employee_id,
                               "revision_id": row.get("id"),
                               "effective_from": effective.isoformat()})


@router.get("/employees/{employee_id}/salary-revisions")
def list_salary_revisions(
    employee_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("payroll", "read"))
):
    """An employee's pay history, newest first."""
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, {"revisions": []})
    rows = (db.table("payroll_salary_revisions").select("*")
            .eq("firm_id", current_user["firm_id"])
            .eq("employee_id", employee_id).execute().data) or []
    rows.sort(key=lambda r: str(r.get("effective_from") or ""), reverse=True)
    return api_response(True, {"revisions": rows})


class EmployeeLoanIn(BaseModel):
    client_id: str
    principal_paise: int
    monthly_instalment_paise: int
    # Rule 3(7)(i): below the SBI rate for the same kind of loan, the shortfall
    # is a perquisite. Zero means interest-free.
    interest_rate_bps: int = 0
    purpose: str = ""
    started_on: Optional[str] = None


@router.post("/employees/{employee_id}/loans")
def add_employee_loan(
    employee_id: str,
    body: EmployeeLoanIn,
    current_user: dict = Depends(rbac("payroll", "write"))
):
    """Record a loan or advance to be recovered through the payslip.

    Recovery happens AFTER the statutory deductions and only out of what is
    left: PF, ESI, professional tax and TDS are owed to somebody else and come
    first, and a recovery that pushed net pay below zero would be an overdrawn
    payslip rather than a debt collected.

    An interest-free or concessional loan is also a PERQUISITE under Rule
    3(7)(i), valued at the SBI rate less what was charged. Recording the
    recovery does not value it — that is /perquisites/value — and the response
    says so when the rate is nil, because an employer who lends interest-free
    and records only the recovery has an unvalued perquisite in the employee's
    Form 16.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    assert_client_access(current_user, body.client_id)
    assert_not_internal_for_payroll(body.client_id, current_user["firm_id"])
    if body.principal_paise <= 0:
        raise HTTPException(status_code=422, detail="principal must be positive")
    if body.monthly_instalment_paise <= 0:
        raise HTTPException(status_code=422, detail="instalment must be positive")

    db = _db()
    assert_payroll_enabled(db, current_user["firm_id"], body.client_id)
    notices = []
    if body.interest_rate_bps == 0:
        notices.append(
            "This loan is interest-free, which makes it a perquisite under Rule "
            "3(7)(i) — valued at the State Bank of India's rate for the same kind "
            "of loan as on the first day of the previous year, less any interest "
            "charged. Nothing is chargeable where the aggregate does not exceed "
            "₹20,000. Value it before Q4 so it reaches the employee's Form 16."
        )
    if not db:
        return api_response(True, {"employee_id": employee_id, "notices": notices})

    row = (db.table("payroll_loans").insert({
        "firm_id": current_user["firm_id"],
        "client_id": body.client_id,
        "employee_id": employee_id,
        "principal_paise": body.principal_paise,
        "outstanding_paise": body.principal_paise,
        "monthly_instalment_paise": body.monthly_instalment_paise,
        "interest_rate_bps": body.interest_rate_bps,
        "purpose": body.purpose,
        "started_on": body.started_on,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).execute().data or [{}])[0]

    return api_response(True, {"employee_id": employee_id,
                               "loan_id": row.get("id"),
                               "outstanding_paise": body.principal_paise,
                               "notices": notices})


@router.get("/employees/{employee_id}/loans")
def list_employee_loans(
    employee_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("payroll", "read"))
):
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, {"loans": []})
    rows = (db.table("payroll_loans").select("*")
            .eq("firm_id", current_user["firm_id"])
            .eq("employee_id", employee_id).execute().data) or []
    return api_response(True, {"loans": rows})
