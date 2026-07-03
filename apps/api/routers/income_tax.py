"""
Income Tax Return computation API.
IT Act 1961 — Section 80C, 80D, 80G, 87A, 111A, 112A, 234B/C etc.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from models.common import api_response
from core.permissions import rbac
from domain.income_tax.itr_engine import (
    ITREngine, ITRComputeRequest, Deductions80C, Deductions80D, Donation80G, HRADetails, itr_engine,
)

router = APIRouter(prefix="/api/income-tax", tags=["income-tax"])


# ── Request models (Pydantic) ─────────────────────────────────────────────────

class S80CInput(BaseModel):
    ppf_paise: int = 0
    elss_paise: int = 0
    lic_paise: int = 0
    nsc_paise: int = 0
    home_loan_principal_paise: int = 0
    tuition_fees_paise: int = 0
    fd_5yr_paise: int = 0
    sukanya_samriddhi_paise: int = 0
    ulip_paise: int = 0


class S80DInput(BaseModel):
    self_family_premium_paise: int = 0
    self_family_is_senior: bool = False
    parents_premium_paise: int = 0
    parents_is_senior: bool = False


class Donation80GInput(BaseModel):
    description: str = ""
    amount_paise: int = 0
    deduction_pct: int = Field(default=100, ge=50, le=100)


class HRAInput(BaseModel):
    basic_salary_paise: int = 0
    hra_received_paise: int = 0
    rent_paid_paise: int = 0
    is_metro: bool = False


class ComputeITRRequest(BaseModel):
    # Financial year the statutory rates should be resolved for, e.g.
    # "2025-26". Omit to default to today's FY. See domain/income_tax/
    # statutory_rates.py — the response's rates_verified flag tells the
    # caller whether this FY's numbers are confirmed against a Finance Act
    # or carried forward pending verification.
    fy: Optional[str] = None

    # Income heads (all paise)
    gross_salary_paise: int = 0
    other_income_paise: int = 0
    house_property_income_paise: int = 0
    business_income_paise: int = 0
    capital_gains_stcg_paise: int = 0
    capital_gains_ltcg_paise: int = 0
    capital_gains_ltcg_other_paise: int = 0
    exempt_income_paise: int = 0

    # Regime
    use_new_regime: bool = True
    is_senior_citizen: bool = False
    is_very_senior_citizen: bool = False

    # Deductions
    s80c: S80CInput = Field(default_factory=S80CInput)
    nps_80ccd1b_paise: int = 0
    s80d: S80DInput = Field(default_factory=S80DInput)
    donations_80g: list[Donation80GInput] = Field(default_factory=list)
    savings_interest_80tta_paise: int = 0
    hra: HRAInput = Field(default_factory=HRAInput)
    home_loan_interest_24b_paise: int = 0
    other_deductions_paise: int = 0

    # Already paid
    tds_deducted_paise: int = 0
    advance_tax_paid_paise: int = 0


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/compute")
def compute_itr(req: ComputeITRRequest, current_user: dict = Depends(rbac("income_tax", "compute"))):
    """
    Compute ITR tax liability from income and deduction inputs.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
    Returns full computation working, deduction breakdown, and net payable/refund.
    """
    engine_req = ITRComputeRequest(
        fy=req.fy,
        gross_salary_paise=req.gross_salary_paise,
        other_income_paise=req.other_income_paise,
        house_property_income_paise=req.house_property_income_paise,
        business_income_paise=req.business_income_paise,
        capital_gains_stcg_paise=req.capital_gains_stcg_paise,
        capital_gains_ltcg_paise=req.capital_gains_ltcg_paise,
        capital_gains_ltcg_other_paise=req.capital_gains_ltcg_other_paise,
        exempt_income_paise=req.exempt_income_paise,
        use_new_regime=req.use_new_regime,
        is_senior_citizen=req.is_senior_citizen,
        is_very_senior_citizen=req.is_very_senior_citizen,
        s80c=Deductions80C(
            ppf_paise=req.s80c.ppf_paise,
            elss_paise=req.s80c.elss_paise,
            lic_paise=req.s80c.lic_paise,
            nsc_paise=req.s80c.nsc_paise,
            home_loan_principal_paise=req.s80c.home_loan_principal_paise,
            tuition_fees_paise=req.s80c.tuition_fees_paise,
            fd_5yr_paise=req.s80c.fd_5yr_paise,
            sukanya_samriddhi_paise=req.s80c.sukanya_samriddhi_paise,
            ulip_paise=req.s80c.ulip_paise,
        ),
        nps_80ccd1b_paise=req.nps_80ccd1b_paise,
        s80d=Deductions80D(
            self_family_premium_paise=req.s80d.self_family_premium_paise,
            self_family_is_senior=req.s80d.self_family_is_senior,
            parents_premium_paise=req.s80d.parents_premium_paise,
            parents_is_senior=req.s80d.parents_is_senior,
        ),
        donations_80g=[
            Donation80G(
                description=d.description,
                amount_paise=d.amount_paise,
                deduction_pct=d.deduction_pct,
            ) for d in req.donations_80g
        ],
        savings_interest_80tta_paise=req.savings_interest_80tta_paise,
        hra=HRADetails(
            basic_salary_paise=req.hra.basic_salary_paise,
            hra_received_paise=req.hra.hra_received_paise,
            rent_paid_paise=req.hra.rent_paid_paise,
            is_metro=req.hra.is_metro,
        ),
        home_loan_interest_24b_paise=req.home_loan_interest_24b_paise,
        other_deductions_paise=req.other_deductions_paise,
        tds_deducted_paise=req.tds_deducted_paise,
        advance_tax_paid_paise=req.advance_tax_paid_paise,
    )

    result = itr_engine.compute(engine_req)

    return api_response(True, {
        "regime": result.regime,
        "fy": result.fy,
        "rates_verified": result.rates_verified,
        "income": {
            "gross_total_paise": result.gross_total_income_paise,
            "standard_deduction_paise": result.standard_deduction_paise,
            "total_deductions_paise": result.total_deductions_paise,
            "taxable_income_paise": result.taxable_income_paise,
        },
        "deductions": {
            "s80c_paise": result.deduction_80c_paise,
            "s80ccd_paise": result.deduction_80ccd_paise,
            "s80d_paise": result.deduction_80d_paise,
            "s80g_paise": result.deduction_80g_paise,
            "s80tta_paise": result.deduction_80tta_paise,
            "hra_paise": result.deduction_hra_paise,
            "s24b_paise": result.deduction_24b_paise,
        },
        "tax": {
            "tax_before_cess_paise": result.tax_before_cess_paise,
            "rebate_87a_paise": result.rebate_87a_paise,
            "surcharge_paise": result.surcharge_paise,
            "cess_paise": result.cess_paise,
            "total_tax_paise": result.total_tax_paise,
        },
        "payable": {
            "tds_and_advance_paise": result.tds_and_advance_paise,
            "net_payable_paise": result.net_payable_paise,
            "is_refund": result.net_payable_paise < 0,
        },
        "warnings": result.warnings,
        "validation_errors": result.validation_errors,
        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        "ca_review_required": True,
    })


@router.post("/hra/compute")
def compute_hra(
    basic_salary_paise: int,
    hra_received_paise: int,
    rent_paid_paise: int,
    is_metro: bool = False,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Compute HRA exemption under IT Act Section 10(13A)."""
    hra = HRADetails(
        basic_salary_paise=basic_salary_paise,
        hra_received_paise=hra_received_paise,
        rent_paid_paise=rent_paid_paise,
        is_metro=is_metro,
    )
    exemption = hra.exemption_paise()
    return api_response(True, {
        "exemption_paise": exemption,
        "taxable_hra_paise": max(0, hra_received_paise - exemption),
        "section": "IT Act Section 10(13A)",
    })
