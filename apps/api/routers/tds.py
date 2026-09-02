"""
TDS API — 24Q/26Q return computation and filing preparation.

IT Act Section 192 (salary TDS), Section 194 (non-salary TDS).
All monetary amounts in integer paise.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to TRACES or any government portal.
"""
from fastapi import APIRouter, HTTPException, Query, status, Depends
from pydantic import BaseModel, Field
from typing import Optional
from core.permissions import rbac
from core.authz import assert_client_access
from domain.tds import TDSComputer, TDSDeducteeRecord
from domain.tds.section_rates import tds_rates_for
from domain.tds.tds_computer import is_company_pan, has_pan as pan_on_file
from repositories.tds_repository import tds_repo

router = APIRouter(prefix="/api/tds", tags=["tds"])
computer = TDSComputer()


# ── Client-assignment scope (M2) ──────────────────────────────────────────────
# This router imported no authz at all. `/returns/{client_id}` and
# `/deductions/{client_id}` name a client in the PATH and returned that client's
# filed returns and every TDS deduction on their books to any member of the
# firm; the two `/from-books` endpoints read a client's posted purchase bills or
# finalized payroll runs out of the ledger.
#
# The two `/compute` endpoints are guarded too even though they are, today, pure
# functions over caller-supplied rows that never read `req.client_id`. An
# exemption would be true right now and silently false the first time somebody
# uses the field the request model already requires — and the sweep's honesty
# tests check that an exempted ROUTE still exists, not that its REASON still
# holds. One line is cheaper than that trap.
#
# `/compute-amount` and `/sections` are exempt and stay that way: neither has a
# client_id to check. `/sections` returns the statutory rate table itself.


# ── Request / Response Models ─────────────────────────────────────────────────

class DeducteeInput(BaseModel):
    deductee_name: str
    deductee_pan: str
    section: str
    nature_of_payment: str
    payment_date: str
    payment_amount_paise: int = Field(gt=0)
    tds_rate_pct: float
    tds_deducted_paise: int = Field(ge=0)
    tds_deposited_paise: int = Field(ge=0)
    challan_no: str
    bsr_code: str
    challan_date: str
    is_lower_deduction: bool = False
    lower_deduction_cert: Optional[str] = None


class ChallanInput(BaseModel):
    challan_no: str
    bsr_code: str
    payment_date: str
    tds_paise: int
    surcharge_paise: int = 0
    interest_paise: int = 0
    total_paise: int
    bank_name: Optional[str] = None
    section: Optional[str] = None


class Compute26QRequest(BaseModel):
    client_id: str
    tan: str
    deductor_name: str
    deductor_pan: str
    deductor_address: str
    financial_year: str
    quarter: str
    deductees: list[DeducteeInput]
    challans: list[ChallanInput] = []


class Compute24QRequest(BaseModel):
    client_id: str
    tan: str
    deductor_name: str
    deductor_pan: str
    deductor_address: str
    financial_year: str
    quarter: str
    deductees: list[DeducteeInput]
    challans: list[ChallanInput] = []


class FromBooksRequest(BaseModel):
    client_id: str
    financial_year: str = Field(..., description="e.g. 2025-26")
    quarter: str = Field(..., description="Q1, Q2, Q3, Q4")
    tan: str
    deductor_name: str
    deductor_pan: str
    deductor_address: str


class TDSAmountRequest(BaseModel):
    section: str
    payment_amount_paise: int = Field(gt=0)
    is_company: bool = False
    # Financial year to resolve thresholds/rates for (e.g. "2025-26");
    # omit for the current FY. See domain/tds/section_rates.py.
    fy: Optional[str] = None
    # IT Act §206AA — set False to model a payee with no PAN on file (rate
    # floors at the registry's section_206aa_floor_rate_bps). Defaults to
    # True (has a PAN) so existing callers' behaviour is unchanged.
    has_pan: bool = True
    # Optional: when supplied, is_company/has_pan above are IGNORED and
    # instead derived from the PAN itself via is_company_pan()/has_pan() —
    # the same authoritative derivation the real purchase-bill TDS deduction
    # already uses (routers/purchase_bills.py), so a caller with a payee's
    # PAN on file never has to duplicate that rule itself.
    pan: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/26q/compute")
def compute_26q(req: Compute26QRequest, user: dict = Depends(rbac("tds", "compute"))):
    """
    Compute Form 26Q (non-salary TDS) return structure.
    IT Act Section 194 series.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    assert_client_access(user, req.client_id)
    records = [
        TDSDeducteeRecord(
            deductee_name=d.deductee_name,
            deductee_pan=d.deductee_pan,
            section=d.section,
            nature_of_payment=d.nature_of_payment,
            payment_date=d.payment_date,
            payment_amount_paise=d.payment_amount_paise,
            tds_rate_pct=d.tds_rate_pct,
            tds_deducted_paise=d.tds_deducted_paise,
            tds_deposited_paise=d.tds_deposited_paise,
            challan_no=d.challan_no,
            bsr_code=d.bsr_code,
            challan_date=d.challan_date,
            is_lower_deduction=d.is_lower_deduction,
            lower_deduction_cert=d.lower_deduction_cert,
        )
        for d in req.deductees
    ]

    challans_list = [c.model_dump() for c in req.challans]

    payload = computer.compute_26q(
        tan=req.tan,
        deductor_name=req.deductor_name,
        deductor_pan=req.deductor_pan,
        deductor_address=req.deductor_address,
        financial_year=req.financial_year,
        quarter=req.quarter,
        deductees=records,
        challans=challans_list,
    )

    return {
        "success": True,
        "data": {
            "form": "26Q",
            "tan": payload.tan,
            "deductor_name": payload.deductor_name,
            "financial_year": payload.financial_year,
            "quarter": payload.quarter,
            "quarter_end_date": payload.quarter_end_date,
            "total_payment_paise": payload.total_payment_paise,
            "total_tds_deducted_paise": payload.total_tds_deducted_paise,
            "total_tds_deposited_paise": payload.total_tds_deposited_paise,
            "deductee_count": len(payload.deductees),
            "deductees": [
                {
                    "deductee_name": d.deductee_name,
                    "deductee_pan": d.deductee_pan,
                    "section": d.section,
                    "nature_of_payment": d.nature_of_payment,
                    "payment_date": d.payment_date,
                    "payment_amount_paise": d.payment_amount_paise,
                    "tds_rate_pct": d.tds_rate_pct,
                    "tds_deducted_paise": d.tds_deducted_paise,
                    "tds_deposited_paise": d.tds_deposited_paise,
                    "challan_no": d.challan_no,
                    "bsr_code": d.bsr_code,
                    "challan_date": d.challan_date,
                    "is_lower_deduction": d.is_lower_deduction,
                }
                for d in payload.deductees
            ],
            "challans": payload.challans,
            "validation_errors": payload.validation_errors,
            "warnings": payload.warnings,
        },
        "error": None,
    }


@router.post("/24q/compute")
def compute_24q(req: Compute24QRequest, user: dict = Depends(rbac("tds", "compute"))):
    """
    Compute Form 24Q (salary TDS) return structure.
    IT Act Section 192.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    assert_client_access(user, req.client_id)
    records = [
        TDSDeducteeRecord(
            deductee_name=d.deductee_name,
            deductee_pan=d.deductee_pan,
            section=d.section,
            nature_of_payment=d.nature_of_payment,
            payment_date=d.payment_date,
            payment_amount_paise=d.payment_amount_paise,
            tds_rate_pct=d.tds_rate_pct,
            tds_deducted_paise=d.tds_deducted_paise,
            tds_deposited_paise=d.tds_deposited_paise,
            challan_no=d.challan_no,
            bsr_code=d.bsr_code,
            challan_date=d.challan_date,
        )
        for d in req.deductees
    ]

    challans_list = [c.model_dump() for c in req.challans]

    payload = computer.compute_24q(
        tan=req.tan,
        deductor_name=req.deductor_name,
        deductor_pan=req.deductor_pan,
        deductor_address=req.deductor_address,
        financial_year=req.financial_year,
        quarter=req.quarter,
        deductees=records,
        challans=challans_list,
    )

    return {
        "success": True,
        "data": {
            "form": "24Q",
            "tan": payload.tan,
            "deductor_name": payload.deductor_name,
            "financial_year": payload.financial_year,
            "quarter": payload.quarter,
            "quarter_end_date": payload.quarter_end_date,
            "total_salary_paise": payload.total_salary_paise,
            "total_tds_deducted_paise": payload.total_tds_deducted_paise,
            "total_tds_deposited_paise": payload.total_tds_deposited_paise,
            "deductee_count": len(payload.deductees),
            "deductees": [
                {
                    "deductee_name": d.deductee_name,
                    "deductee_pan": d.deductee_pan,
                    "section": d.section,
                    "payment_amount_paise": d.payment_amount_paise,
                    "tds_deducted_paise": d.tds_deducted_paise,
                    "tds_deposited_paise": d.tds_deposited_paise,
                    "challan_no": d.challan_no,
                }
                for d in payload.deductees
            ],
            "challans": payload.challans,
            "validation_errors": payload.validation_errors,
            "warnings": payload.warnings,
        },
        "error": None,
    }


@router.post("/26q/from-books")
def compute_26q_from_books(req: FromBooksRequest, user: dict = Depends(rbac("tds", "compute"))):
    """
    Build Form 26Q (non-salary TDS) ENTIRELY from posted purchase bills and
    reconcile the total to the GL "TDS Payable" control account.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to TRACES or any government portal.
    """
    from core.supabase_client import get_supabase
    from services.tds_return_service import tds_26q_from_books
    assert_client_access(user, req.client_id)
    db = get_supabase()
    firm_id = user["firm_id"]
    try:
        data = tds_26q_from_books(
            db, firm_id, req.client_id, req.financial_year, req.quarter,
            req.tan, req.deductor_name, req.deductor_pan, req.deductor_address,
        )
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    return {"success": True, "data": data, "error": None}


@router.post("/24q/from-books")
def compute_24q_from_books(req: FromBooksRequest, user: dict = Depends(rbac("tds", "compute"))):
    """
    Build Form 24Q (salary TDS) ENTIRELY from finalized payroll runs and
    reconcile the total to the GL "TDS Payable - Salary" control account.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to TRACES or any government portal.
    """
    from core.supabase_client import get_supabase
    from services.tds_return_service import tds_24q_from_books
    assert_client_access(user, req.client_id)
    db = get_supabase()
    firm_id = user["firm_id"]
    try:
        data = tds_24q_from_books(
            db, firm_id, req.client_id, req.financial_year, req.quarter,
            req.tan, req.deductor_name, req.deductor_pan, req.deductor_address,
        )
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    return {"success": True, "data": data, "error": None}


@router.post("/compute-amount")
def compute_tds_amount(req: TDSAmountRequest, user: dict = Depends(rbac("tds", "compute"))):
    """
    Calculate TDS for a single payment given section and amount.
    Returns applicable rate and TDS amount in paise, resolved for the
    requested FY (defaults to the current FY).
    IT Act Chapter XVII-B.
    """
    is_company = is_company_pan(req.pan) if req.pan is not None else req.is_company
    has_pan_on_file = pan_on_file(req.pan) if req.pan is not None else req.has_pan
    try:
        resolution = computer.resolve_tds(
            req.section, req.payment_amount_paise, is_company=is_company, fy=req.fy,
            has_pan=has_pan_on_file)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown TDS section: {req.section}")

    rates = tds_rates_for(req.fy)
    rule = rates.sections[resolution.section]
    return {
        "success": True,
        "data": {
            "section": resolution.section,
            "fy": rates.fy,
            "rates_verified": rates.verified,
            "payment_amount_paise": req.payment_amount_paise,
            "threshold_paise": rule.single_threshold_paise,
            "aggregate_threshold_paise": rule.aggregate_threshold_paise,
            "tds_applicable": resolution.applies,
            "applicable_rate_pct": resolution.rate_pct,
            "tds_paise": resolution.tds_paise,
        },
        "error": None,
    }


@router.get("/sections")
def list_tds_sections(fy: Optional[str] = None, user: dict = Depends(rbac("tds", "read"))):
    """List all TDS sections with thresholds and rates for the given FY
    (defaults to the current FY)."""
    rates = tds_rates_for(fy)
    sections = [
        {
            "section": sec,
            "threshold_paise": rule.single_threshold_paise,
            "aggregate_threshold_paise": rule.aggregate_threshold_paise,
            "rate_individual_pct": rule.individual_rate_bps / 100,
            "rate_company_pct": rule.company_rate_bps / 100,
        }
        for sec, rule in rates.sections.items()
    ]
    return {
        "success": True,
        "data": {"fy": rates.fy, "rates_verified": rates.verified, "sections": sections},
        "error": None,
    }


@router.get("/returns/{client_id}")
def get_tds_returns(client_id: str, user: dict = Depends(rbac("tds", "read"))):
    """Fetch all TDS returns for a client."""
    assert_client_access(user, client_id)
    firm_id = user["firm_id"]
    data = tds_repo.get_returns(client_id=client_id, firm_id=firm_id)
    return {"success": True, "data": data, "error": None}


@router.get("/deductions/{client_id}")
def get_tds_deductions(
    client_id: str,
    financial_year: Optional[str] = None,
    quarter: Optional[str] = None,
    return_type: Optional[str] = Query(
        None, description="Filter to one quarterly statement — '26Q' (payments "
                          "to residents) or '27Q' (payments to non-residents), "
                          "which Rule 31A(4) keeps apart. Omit for both."),
    user: dict = Depends(rbac("tds", "read")),
):
    """Fetch TDS deductions for a client, optionally filtered by FY/quarter.

    The register holds 26Q and 27Q rows together, because they come from the
    same purchase bills and the same deduction event. They are FILED apart, so
    a caller assembling either one has to say which — Rule 31A(4)(a) and (b).
    """
    # An omitted parameter reaches a DIRECT call as FastAPI's Query default
    # object, not None — truthy, and not a valid return_type, so the validation
    # below would 422 every caller that never asked for a filter. Normalised the
    # same way routers/gst_workspace.py's return_type filter already is; its
    # comment records the same trap.
    if not isinstance(return_type, str):
        return_type = None
    assert_client_access(user, client_id)
    firm_id = user["firm_id"]
    if return_type is not None and return_type not in ("24Q", "26Q", "27Q", "27EQ"):
        raise HTTPException(
            status_code=422,
            detail="return_type must be one of 24Q, 26Q, 27Q or 27EQ "
                   "(migration 014's CHECK on tds_deductions.return_type).")
    data = tds_repo.get_deductions(
        client_id=client_id,
        firm_id=firm_id,
        financial_year=financial_year,
        quarter=quarter,
        return_type=return_type,
    )
    return {"success": True, "data": data, "error": None}
