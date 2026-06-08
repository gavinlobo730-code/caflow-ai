"""
TDS API — 24Q/26Q return computation and filing preparation.

IT Act Section 192 (salary TDS), Section 194 (non-salary TDS).
All monetary amounts in integer paise.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to TRACES or any government portal.
"""
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from typing import Optional
from core.permissions import rbac
from domain.tds import TDSComputer, TDSDeducteeRecord
from repositories.tds_repository import tds_repo

router = APIRouter(prefix="/api/tds", tags=["tds"])
computer = TDSComputer()


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


class TDSAmountRequest(BaseModel):
    section: str
    payment_amount_paise: int = Field(gt=0)
    is_company: bool = False


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/26q/compute")
def compute_26q(req: Compute26QRequest, user: dict = Depends(rbac("tds", "compute"))):
    """
    Compute Form 26Q (non-salary TDS) return structure.
    IT Act Section 194 series.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
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


@router.post("/compute-amount")
def compute_tds_amount(req: TDSAmountRequest, user: dict = Depends(rbac("tds", "compute"))):
    """
    Calculate TDS for a single payment given section and amount.
    Returns applicable rate and TDS amount in paise.
    IT Act Section 194.
    """
    from domain.tds.tds_computer import SECTION_THRESHOLDS
    if req.section not in SECTION_THRESHOLDS:
        raise HTTPException(status_code=400, detail=f"Unknown TDS section: {req.section}")

    amount = computer.compute_tds_amount(req.section, req.payment_amount_paise, req.is_company)
    threshold, ind_rate, co_rate = SECTION_THRESHOLDS[req.section]
    applicable_rate = co_rate if req.is_company else ind_rate

    return {
        "success": True,
        "data": {
            "section": req.section,
            "payment_amount_paise": req.payment_amount_paise,
            "threshold_paise": threshold,
            "tds_applicable": req.payment_amount_paise > threshold,
            "applicable_rate_pct": applicable_rate,
            "tds_paise": amount,
        },
        "error": None,
    }


@router.get("/sections")
def list_tds_sections(user: dict = Depends(rbac("tds", "read"))):
    """List all TDS sections with thresholds and rates."""
    from domain.tds.tds_computer import SECTION_THRESHOLDS
    sections = [
        {
            "section": sec,
            "threshold_paise": thresh,
            "rate_individual_pct": ind,
            "rate_company_pct": co,
        }
        for sec, (thresh, ind, co) in SECTION_THRESHOLDS.items()
    ]
    return {"success": True, "data": sections, "error": None}


@router.get("/returns/{client_id}")
def get_tds_returns(client_id: str, user: dict = Depends(rbac("tds", "read"))):
    """Fetch all TDS returns for a client."""
    firm_id = user["firm_id"]
    data = tds_repo.get_returns(client_id=client_id, firm_id=firm_id)
    return {"success": True, "data": data, "error": None}


@router.get("/deductions/{client_id}")
def get_tds_deductions(
    client_id: str,
    financial_year: Optional[str] = None,
    quarter: Optional[str] = None,
    user: dict = Depends(rbac("tds", "read")),
):
    """Fetch TDS deductions for a client, optionally filtered by FY/quarter."""
    firm_id = user["firm_id"]
    data = tds_repo.get_deductions(
        client_id=client_id,
        firm_id=firm_id,
        financial_year=financial_year,
        quarter=quarter,
    )
    return {"success": True, "data": data, "error": None}
