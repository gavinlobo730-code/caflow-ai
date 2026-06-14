"""
Payroll router — Employee master, salary structures, payroll runs, statutory, reports.

IT Act §192: TDS on salary (monthly deduction, annual projected basis).
PF Act: Employer PF = 12% of basic (up to ₹15,000 basic ceiling → ₹1,800 max employer contribution).
ESI Act: Employee ESI = 0.75% of gross; Employer ESI = 3.25% of gross (applicable when gross ≤ ₹21,000/month).
PT: State-specific professional tax slab (default: Karnataka slab used as fallback).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from datetime import datetime, timezone
import math

from models.common import api_response
from models.payroll import EmployeeIn, EmployeeUpdateIn, SalaryStructureIn, PayrollRunIn, RunStatusIn
from core.permissions import rbac
from services.timeline_service import timeline_service
from services.internal_client_service import assert_not_internal_for_payroll

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


# ─── PT Slabs (Karnataka as default; extend per state) ────────────────────────
_PT_SLABS_KA = [
    (0,        14999_00,  0),
    (15000_00, 29999_00, 150_00),
    (30000_00, None,     200_00),
]

def _compute_pt(gross_paise: int, state: Optional[str] = None) -> int:
    """Professional Tax per month in paise. IT Act §16(iii) — deductible from salary."""
    for low, high, tax in _PT_SLABS_KA:
        if gross_paise >= low and (high is None or gross_paise <= high):
            return tax
    return 0


def _compute_pf(basic_paise: int) -> dict:
    """
    PF computation per EPF Act.
    Employee contribution: 12% of basic (capped at ₹15,000 basic → max ₹1,800).
    Employer contribution: 12% of basic (same cap).
    """
    # Cap basic at ₹15,000 for PF computation
    capped = min(basic_paise, 1500000)
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


def _compute_slip(emp: dict, attendance: Optional[dict] = None) -> dict:
    """
    Compute a single payroll slip in integer paise. No floating point on final values.
    IT Act §192: TDS on salary — simplified monthly deduction (annual / 12).
    """
    working_days  = (attendance or {}).get("working_days", 26)
    days_present  = (attendance or {}).get("days_present", 26)
    lop_days      = (attendance or {}).get("lop_days", 0)

    lop_factor = max(0, (working_days - lop_days)) / max(working_days, 1)

    basic     = math.floor(emp.get("basic_paise", 0) * lop_factor)
    hra       = math.floor(basic * float(emp.get("hra_percent", 0)) / 100)
    da        = math.floor(basic * float(emp.get("da_percent", 0)) / 100)
    lta       = math.floor(emp.get("lta_paise", 0) * lop_factor)
    medical   = math.floor(emp.get("medical_paise", 0) * lop_factor)
    special   = math.floor(emp.get("special_allowance_paise", 0) * lop_factor)
    gross     = basic + hra + da + lta + medical + special

    pf   = _compute_pf(basic) if emp.get("pf_applicable") else {"employee": 0, "employer": 0}
    esi  = _compute_esi(gross) if emp.get("esi_applicable") else {"employee": 0, "employer": 0}
    pt   = _compute_pt(gross, emp.get("pt_state")) if emp.get("pt_applicable") else 0

    # IT Act §192: simplified monthly TDS = (annual taxable - std deduction ₹50k) / 12
    # Standard deduction ₹50,000 per annum (Finance Act 2018)
    annual_gross = gross * 12
    std_deduction_paise = 5000000  # ₹50,000
    taxable_annual = max(0, annual_gross - std_deduction_paise)
    tds_monthly = _compute_tds_192(taxable_annual)

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


def _compute_tds_192(taxable_annual_paise: int) -> int:
    """
    IT Act §192: TDS on salary, new tax regime FY 2024-25 slabs.
    Monthly deduction = annual tax / 12.
    """
    rupees = taxable_annual_paise / 100
    tax = 0.0
    if rupees <= 300000:
        tax = 0
    elif rupees <= 700000:
        tax = (rupees - 300000) * 0.05
    elif rupees <= 1000000:
        tax = 20000 + (rupees - 700000) * 0.10
    elif rupees <= 1200000:
        tax = 50000 + (rupees - 1000000) * 0.15
    elif rupees <= 1500000:
        tax = 80000 + (rupees - 1200000) * 0.20
    else:
        tax = 140000 + (rupees - 1500000) * 0.30

    # 4% health & education cess (Finance Act §2)
    tax = tax * 1.04
    monthly = math.floor((tax / 12) * 100)  # convert to paise
    return monthly


# ─── Employee Master ──────────────────────────────────────────────────────────

@router.get("/employees")
def list_employees(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("payroll", "read"))
):
    db = _db()
    if not db:
        return api_response(True, [])
    res = db.table("payroll_employees").select("*").eq("firm_id", current_user["firm_id"]).eq("client_id", client_id).eq("status", "active").order("name").execute()
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
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("payroll", "read"))
):
    db = _db()
    if not db:
        return api_response(True, [])
    res = db.table("payroll_runs").select("*").eq("firm_id", current_user["firm_id"]).eq("client_id", client_id).order("month", desc=True).execute()
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

    # Create run record
    run_res = db.table("payroll_runs").insert({
        "firm_id":   current_user["firm_id"],
        "client_id": client_id,
        "month":     month,
        "status":    "draft",
    }).execute()
    run = (run_res.data or [{}])[0]
    run_id = run["id"]

    # Fetch active employees
    emps = db.table("payroll_employees").select("*").eq("firm_id", current_user["firm_id"]).eq("client_id", client_id).eq("status", "active").execute().data or []

    m, y = int(month.split("-")[1]), int(month.split("-")[0])

    slips = []
    totals = {"gross": 0, "net": 0, "pf": 0, "esi": 0, "pt": 0, "tds": 0}

    for emp in emps:
        att_res = db.table("attendance").select("*").eq("employee_id", emp["id"]).eq("month", m).eq("year", y).execute()
        attendance = (att_res.data or [None])[0]

        slip = _compute_slip(emp, attendance)
        slip["run_id"]      = run_id
        slip["employee_id"] = emp["id"]

        slips.append(slip)
        totals["gross"] += slip["gross_paise"]
        totals["net"]   += slip["net_paise"]
        totals["pf"]    += slip["pf_employee_paise"] + slip["pf_employer_paise"]
        totals["esi"]   += slip["esi_employee_paise"] + slip["esi_employer_paise"]
        totals["pt"]    += slip["pt_paise"]
        totals["tds"]   += slip["tds_paise"]

    if slips:
        db.table("payroll_slips").insert(slips).execute()

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
    db = _db()
    if not db:
        return api_response(True, [])
    slips = db.table("payroll_slips").select("*, payroll_employees(name, pan, designation, department)").eq("run_id", run_id).eq("firm_id", current_user["firm_id"]).execute()
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
    """Move run to 'review' or back to 'draft'. Finalization is a separate endpoint."""
    db = _db()
    new_status = data.status
    if not db:
        # Mock: track finalized runs to enforce immutability
        if run_id in _MOCK_FINALIZED_RUNS:
            raise HTTPException(status_code=409, detail="Run already finalized — cannot change status")
        return api_response(True, {"id": run_id, "status": new_status})
    row = db.table("payroll_runs").update({"status": new_status}).eq("id", run_id).neq("status", "finalized").execute()
    if not row.data:
        raise HTTPException(status_code=404, detail="Run not found or already finalized")
    return api_response(True, row.data[0])


@router.post("/runs/{run_id}/finalize")
def finalize_run(
    run_id: str,
    current_user: dict = Depends(rbac("payroll", "finalize"))
):
    """
    Finalize payroll run — Partner only. Immutable after this point.
    Creates journal entry per Product Bible immutability rules:

    Dr  Salaries Expense        (total gross)
      Cr  Net Salary Payable    (total net pay)
      Cr  PF Payable            (employee + employer PF)
      Cr  ESI Payable           (employee + employer ESI)
      Cr  PT Payable
      Cr  TDS Payable - Salary  (feeds 24Q)

    IT Act §192 TDS recorded for 24Q return.
    """
    db = _db()
    if not db:
        if run_id in _MOCK_FINALIZED_RUNS:
            raise HTTPException(status_code=409, detail="Run already finalized")
        _MOCK_FINALIZED_RUNS.add(run_id)
        return api_response(True, {"id": run_id, "status": "finalized"})

    run = db.table("payroll_runs").select("*").eq("id", run_id).single().execute().data
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] == "finalized":
        raise HTTPException(status_code=409, detail="Run already finalized")

    client_id = run["client_id"]
    firm_id   = run["firm_id"]

    # Create payroll journal
    from services.phase2_journal_service import Phase2JournalService
    svc = Phase2JournalService()
    journal_id = svc.journal_for_payroll(run, firm_id, client_id)

    db.table("payroll_runs").update({
        "status":          "finalized",
        "finalized_at":    datetime.now(timezone.utc).isoformat(),
        "journal_entry_id": journal_id,
    }).eq("id", run_id).execute()

    timeline_service.log(client_id, "work", "Payroll Finalized",
        f"Payroll for {run['month']} finalized — {run.get('headcount', 0)} employees", "success")

    return api_response(True, {"id": run_id, "status": "finalized", "journal_entry_id": journal_id})


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
