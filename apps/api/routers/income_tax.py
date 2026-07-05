"""
Income Tax Return computation API.
IT Act 1961 — Section 80C, 80D, 80G, 87A, 111A, 112A, 234B/C etc.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
"""
from __future__ import annotations
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from models.common import api_response
from core.permissions import rbac
from core.ist_clock import ist_today
from domain.income_tax.itr_engine import (
    ITREngine, ITRComputeRequest, Deductions80C, Deductions80D, Donation80G, HRADetails, itr_engine,
)
from domain.income_tax.capital_gains_engine import (
    compute_capital_gains, ASSET_TYPES, REGISTER_ASSET_TYPES, CII_BY_FY, LATEST_CII_FY,
)
from domain.income_tax.advance_tax_interest_engine import (
    compute_234c_interest, installment_schedule, InstallmentPayment, INSTALLMENT_RULES,
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
    # Section 80CCD(2) — employer NPS contribution, available under both
    # regimes (see itr_engine.py's LIMIT_80CCD2_* constants for the
    # government/other cap split and its verification status).
    employer_nps_80ccd2_paise: int = 0
    is_government_employee: bool = False
    salary_for_80ccd2_paise: Optional[int] = None
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
        employer_nps_80ccd2_paise=req.employer_nps_80ccd2_paise,
        is_government_employee=req.is_government_employee,
        salary_for_80ccd2_paise=req.salary_for_80ccd2_paise,
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
            "s80ccd2_paise": result.deduction_80ccd2_paise,
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


# ── Capital Gains (R3.1b) ──────────────────────────────────────────────────────
# Section 45/48/2(42A)/111A/112A/112/115BBH/50AA — see
# domain/income_tax/capital_gains_engine.py for the full computation and its
# verification-status note. Replaces apps/web/app/income-tax/capital-gains/
# page.tsx's client-side compute-and-persist implementation.

def _db():
    import os
    if not os.environ.get("SUPABASE_URL"):
        return None
    from core.supabase_client import get_supabase
    return get_supabase()


@router.get("/capital-gains/cii-table")
def get_cii_table(current_user: dict = Depends(rbac("income_tax", "read"))):
    """Cost Inflation Index table, Section 48 2nd proviso — the single
    source of truth the frontend's reference display reads, instead of
    keeping its own hardcoded copy (which would silently drift from the one
    domain/income_tax/capital_gains_engine.py actually computes with)."""
    return api_response(True, {"cii_by_fy": CII_BY_FY, "latest_verified_fy": LATEST_CII_FY})


_ALL_ASSET_TYPES = set(ASSET_TYPES) | set(REGISTER_ASSET_TYPES)


class ComputeCapitalGainsRequest(BaseModel):
    asset_type: str
    purchase_date: date
    sale_date: date
    purchase_cost_paise: int = Field(ge=0)
    sale_value_paise: int = Field(ge=0)
    improvement_cost_paise: int = Field(default=0, ge=0)

    @field_validator("asset_type")
    @classmethod
    def valid_asset_type(cls, v: str) -> str:
        if v not in _ALL_ASSET_TYPES:
            raise ValueError(f"asset_type must be one of {sorted(_ALL_ASSET_TYPES)}")
        return v

    @field_validator("sale_date")
    @classmethod
    def sale_not_before_purchase(cls, v: date, info) -> date:
        purchase = info.data.get("purchase_date")
        if purchase and v < purchase:
            raise ValueError("sale_date cannot be before purchase_date")
        return v


def _cg_response(r) -> dict:
    return {
        "holding_months": r.holding_months,
        "is_long_term": r.is_long_term,
        "gain_type": "LTCG" if r.is_long_term else "STCG",
        "gain_paise": r.gain_paise,
        "indexed_cost_paise": r.indexed_cost_paise,
        "gain_with_indexation_paise": r.gain_with_indexation_paise,
        "tax_rate_percent": r.tax_rate_percent,
        "tax_with_indexation_percent": r.tax_with_indexation_percent,
        "tax_without_indexation_paise": r.tax_without_indexation_paise,
        "tax_with_indexation_paise": r.tax_with_indexation_paise,
        "tax_liability_paise": r.tax_liability_paise,
        "section_ref": r.section_ref,
        "note": r.note,
        "is_slab_rate_estimate": r.is_slab_rate_estimate,
    }


@router.post("/capital-gains/compute")
def compute_capital_gains_endpoint(
    req: ComputeCapitalGainsRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Stateless capital-gains estimator — does not persist anything.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal"""
    result = compute_capital_gains(
        req.asset_type, req.purchase_date, req.sale_date,
        req.purchase_cost_paise, req.sale_value_paise, req.improvement_cost_paise,
    )
    return api_response(True, _cg_response(result))


@router.get("/capital-gains")
def list_capital_gains(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    db = _db()
    if not db:
        return api_response(True, [])
    res = (db.table("capital_gains").select("*")
           .eq("firm_id", current_user["firm_id"]).eq("client_id", client_id)
           .order("sale_date", desc=True).execute())
    return api_response(True, res.data or [])


class CreateCapitalGainsRequest(ComputeCapitalGainsRequest):
    client_id: str
    asset_description: str = Field(min_length=1)

    @field_validator("asset_type")
    @classmethod
    def register_asset_type(cls, v: str) -> str:
        # The persisted table's CHECK constraint only accepts the register's
        # (coarser) vocabulary, not the calculator's finer "equity"/"unlisted"/
        # "vda"/"gold"/"debt_mf" -- validate against that narrower set here.
        if v not in REGISTER_ASSET_TYPES:
            raise ValueError(f"asset_type must be one of {sorted(REGISTER_ASSET_TYPES)} for a register entry")
        return v


@router.post("/capital-gains")
def create_capital_gains(
    req: CreateCapitalGainsRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Computes AND persists a capital-gains register entry — the gain
    classification, indexed cost, and applicable tax rate are computed here,
    server-side, not trusted from the client.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal"""
    db = _db()
    result = compute_capital_gains(
        req.asset_type, req.purchase_date, req.sale_date,
        req.purchase_cost_paise, req.sale_value_paise, req.improvement_cost_paise,
    )
    payload = {
        "firm_id": current_user["firm_id"],
        "client_id": req.client_id,
        "asset_description": req.asset_description,
        "asset_type": req.asset_type,
        "purchase_date": req.purchase_date.isoformat(),
        "sale_date": req.sale_date.isoformat(),
        "purchase_cost_paise": req.purchase_cost_paise,
        "improvement_cost_paise": req.improvement_cost_paise,
        "sale_value_paise": req.sale_value_paise,
        "indexed_cost_paise": result.indexed_cost_paise,
        "gain_type": "LTCG" if result.is_long_term else "STCG",
        "tax_rate_percent": result.tax_rate_percent,
    }
    if not db:
        return api_response(True, {"id": "mock-id", **payload})
    row = db.table("capital_gains").insert(payload).execute()
    record = (row.data or [{}])[0]
    return api_response(True, {**record, **_cg_response(result)})


@router.delete("/capital-gains/{record_id}")
def delete_capital_gains(
    record_id: str,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    db = _db()
    if not db:
        return api_response(True, {"id": record_id})
    row = (db.table("capital_gains").delete().eq("id", record_id)
           .eq("firm_id", current_user["firm_id"]).execute())
    if not row.data:
        raise HTTPException(status_code=404, detail="Capital gains record not found")
    return api_response(True, {"id": record_id})


# ── Advance tax interest (R3.13a) ───────────────────────────────────────────
# Section 207/208 (instalment schedule) / 234C (interest for deferment) —
# see domain/income_tax/advance_tax_interest_engine.py for the full
# computation and its verification-status note. Replaces apps/web/app/
# income-tax/advance-tax/page.tsx's compute234CInterest(), which used the
# wrong (234B-shaped, actual-delay) formula with no trigger tolerance.

class AdvanceTaxInstallmentInput(BaseModel):
    installment_number: int = Field(ge=1, le=4)
    paid_amount_paise: int = Field(default=0, ge=0)
    paid_date: Optional[date] = None
    challan_number: Optional[str] = None

    @field_validator("paid_date")
    @classmethod
    def paid_date_not_in_future(cls, v: Optional[date]) -> Optional[date]:
        if v and v > ist_today():
            raise ValueError("paid_date cannot be in the future")
        return v


class ComputeAdvanceTaxRequest(BaseModel):
    fy: str
    estimated_tax_paise: int = Field(ge=0)
    installments: list[AdvanceTaxInstallmentInput] = Field(default_factory=list)

    @field_validator("installments")
    @classmethod
    def one_entry_per_installment_number(cls, v: list[AdvanceTaxInstallmentInput]) -> list[AdvanceTaxInstallmentInput]:
        numbers = [i.installment_number for i in v]
        if len(numbers) != len(set(numbers)):
            raise ValueError("installments must not repeat an installment_number")
        return v


def _at_response(estimated_tax_paise: int, req_installments: list[AdvanceTaxInstallmentInput], fy: str) -> dict:
    result = compute_234c_interest(
        fy, estimated_tax_paise,
        [InstallmentPayment(i.installment_number, i.paid_amount_paise, i.paid_date) for i in req_installments],
    )
    return {
        "fy": fy,
        "estimated_tax_paise": estimated_tax_paise,
        "total_interest_paise": result.total_interest_paise,
        "section_ref": "Section 234C",
        "installments": [
            {
                "installment_number": i.installment_number,
                "due_date": i.due_date.isoformat(),
                "cumulative_required_percent": i.cumulative_required_percent,
                "trigger_percent": i.trigger_percent,
                "required_cumulative_paise": i.required_cumulative_paise,
                "actual_cumulative_paid_paise": i.actual_cumulative_paid_paise,
                "is_short": i.is_short,
                "shortfall_paise": i.shortfall_paise,
                "interest_months": i.interest_months,
                "interest_paise": i.interest_paise,
            }
            for i in result.installments
        ],
    }


@router.post("/advance-tax/compute")
def compute_advance_tax_interest(
    req: ComputeAdvanceTaxRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Stateless Section 234C interest estimator — does not persist anything.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal"""
    return api_response(True, _at_response(req.estimated_tax_paise, req.installments, req.fy))


@router.get("/advance-tax")
def list_advance_tax(
    client_id: str = Query(...),
    fy: str = Query(...),
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    db = _db()
    if not db:
        return api_response(True, [])
    res = (db.table("advance_tax_payments").select("*")
           .eq("firm_id", current_user["firm_id"]).eq("client_id", client_id).eq("financial_year", fy)
           .order("installment_number").execute())
    return api_response(True, res.data or [])


_REQUIRED_PERCENT_BY_INSTALLMENT = {r.number: r.cumulative_required_percent for r in INSTALLMENT_RULES}


class SaveAdvanceTaxRequest(ComputeAdvanceTaxRequest):
    client_id: str


@router.post("/advance-tax")
def save_advance_tax(
    req: SaveAdvanceTaxRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Persists the recorded payment facts (paid amount/date/challan) for
    each instalment — due_date and required_percent are always derived
    server-side from the FY's Section 208 schedule, never trusted from the
    client. Interest itself is never stored (it is derived, not a fact);
    call /advance-tax/compute for the current computed breakdown.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal"""
    db = _db()
    due_dates = dict(installment_schedule(req.fy))
    by_number = {i.installment_number: i for i in req.installments}
    rows = []
    for number, due_date in due_dates.items():
        inst = by_number.get(number)
        rows.append({
            "firm_id": current_user["firm_id"],
            "client_id": req.client_id,
            "financial_year": req.fy,
            "installment_number": number,
            "due_date": due_date.isoformat(),
            "required_percent": _REQUIRED_PERCENT_BY_INSTALLMENT[number],
            "estimated_tax_paise": req.estimated_tax_paise,
            "paid_amount_paise": inst.paid_amount_paise if inst else 0,
            "paid_date": inst.paid_date.isoformat() if inst and inst.paid_date else None,
            "challan_number": inst.challan_number if inst else None,
        })
    if not db:
        return api_response(True, rows)
    result = (db.table("advance_tax_payments")
              .upsert(rows, on_conflict="client_id,financial_year,installment_number").execute())
    return api_response(True, result.data or rows)
