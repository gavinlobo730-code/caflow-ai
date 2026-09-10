"""
Income Tax Return computation API.
IT Act 1961 — Section 80C, 80D, 80G, 87A, 111A, 112A, 234B/C etc.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
"""
from __future__ import annotations
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from typing import Annotated, Optional
from models.common import api_response
from core.authz import assert_client_access, can_access_client
from core.permissions import rbac
from core.ist_clock import ist_today
from domain.income_tax.itr_engine import (
    ITREngine, ITRComputeRequest, Deductions80C, Deductions80D, Donation80G, HRADetails, itr_engine,
)
from domain.income_tax.capital_gains_engine import (
    compute_capital_gains, ASSET_TYPES, REGISTER_ASSET_TYPES, CII_BY_FY, LATEST_CII_FY,
    ASSESSEE_TYPES, ASSESSEE_UNSPECIFIED,
)
from domain.income_tax.assessee import assessee_kind_for_entity_type
from domain.income_tax.advance_tax_interest_engine import (
    compute_234a_interest, compute_234b_interest, compute_234c_interest,
    installment_schedule, installment_rules, InstallmentPayment, INSTALLMENT_RULES,
)
from domain.income_tax.itr_json import build_itr_payload, itr_field_placements
from domain.income_tax.loss_set_off import BroughtForwardLoss, KNOWN_LOSS_TYPES
from domain.income_tax.presumptive import (
    compute_44ad, compute_44ada, compute_44ae, GoodsCarriage,
)
from services.compliance_obligation_service import itr_due_date_for_client, fy_end_year
from models.fy import FYLabel, OptionalFYLabel

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
    # IT Act §80G's four categories are the PRODUCT of two independent facts
    # about the donee, and this model carried only one of them — so every
    # donation was deducted at its percentage with no ceiling at all.
    #
    # Default True, matching the engine: §80G(4) caps donations in the residual
    # category at 10% of adjusted gross total income, and an unlisted donee IS
    # the residual category. A fund listed in §80G(1)(i) — the PM National
    # Relief Fund and its neighbours — has to be marked, because the direction
    # that guesses wrong here under-claims rather than over-claims.
    subject_to_qualifying_limit: bool = True
    # §80G(5D) bars a deduction for a cash donation over ₹2,000. Tri-state on
    # purpose: None is "the CA did not say", which the engine allows while
    # raising a warning, because a zero for "paid by cheque" and a zero for
    # "nobody stated the mode" must not be the same number.
    paid_in_cash: Optional[bool] = None


class HRAInput(BaseModel):
    basic_salary_paise: int = 0
    hra_received_paise: int = 0
    rent_paid_paise: int = 0
    is_metro: bool = False


class BroughtForwardLossInput(BaseModel):
    """One row of brought_forward_losses, as the screen holds it.

    `amount_paise` is what REMAINS of the loss (remaining_amount_paise), not
    what it originally was — a loss already partly utilised in an earlier year
    can only relieve what is left of it.
    """
    loss_type: str
    amount_paise: int = Field(ge=0)
    assessment_year: Optional[str] = None
    expiry_assessment_year: Optional[str] = None
    is_expired: bool = False
    source_itr_ack: Optional[str] = None

    @field_validator("loss_type")
    @classmethod
    def a_type_with_a_rule(cls, v: str) -> str:
        t = str(v or "").strip().lower()
        if t not in KNOWN_LOSS_TYPES:
            raise ValueError(
                f"loss_type must be one of {', '.join(sorted(KNOWN_LOSS_TYPES))} "
                f"— the head decides which section reaches the loss.")
        return t


class ComputeITRRequest(BaseModel):
    # WHO IS BEING ASSESSED.
    #
    # `entity_type` is the RAW value off the client record — 'Private Limited',
    # 'LLP', 'Proprietorship'. The screen passes what it read and this endpoint
    # maps it, because the mapping is statutory knowledge and CLAUDE.md keeps
    # that in apps/api: a PROPRIETORSHIP is an individual (the proprietor is
    # assessed, on the slabs, with §87A), and a TRUST or a co-operative SOCIETY
    # is refused because §§11-13/§164 and §80P are not modelled here.
    #
    # `assessee_kind` is the explicit override, for a caller that already knows.
    # When both are absent the assessee is an individual, which is the whole of
    # the previous behaviour — this endpoint computed individual slabs for
    # every client, including the four Private Limited companies on the live
    # book, which owe 22%/25%/30% from the first rupee with no §87A rebate.
    entity_type: Optional[str] = None
    assessee_kind: Optional[str] = None

    # Company only — §115BAA (22%) and §115BAB (15%) are elections, and their
    # surcharge is a FLAT 10% whatever the income.
    company_regime: str = "normal"
    # The 25%/30% test looks at the turnover of a year TWO BACK, never the year
    # being taxed. Absent, the higher rate is used: the concession has to be
    # established rather than assumed.
    turnover_in_reference_year_paise: Optional[int] = None
    # §115JB book profit (a company) or §115JC's adjusted total income (a firm
    # or LLP). Book profit is the Companies Act profit as adjusted by
    # Explanation 1 to §115JB(2) — NOT taxable income, which is why it cannot
    # be derived and has to be supplied.
    book_profit_paise: Optional[int] = None
    # §115JC applies only where a §10AA, §35AD or Chapter VI-A Part C deduction
    # has been CLAIMED — a taxpayer who claimed none is outside Chapter XII-BA
    # entirely, not merely below a threshold.
    claimed_specified_deduction: bool = False
    # For the fifteen-year expiry of the MAT/AMT credit (§115JAA, §115JD).
    assessment_year_end: Optional[int] = None

    # Financial year the statutory rates should be resolved for, e.g.
    # "2025-26". Omit to default to today's FY. See domain/income_tax/
    # statutory_rates.py — the response's rates_verified flag tells the
    # caller whether this FY's numbers are confirmed against a Finance Act
    # or carried forward pending verification.
    fy: OptionalFYLabel = None

    # Income heads (all paise)
    gross_salary_paise: int = 0
    other_income_paise: int = 0
    house_property_income_paise: int = 0
    business_income_paise: int = 0
    # Add-backs accepted in the computation workspace (§40A(3), §43B, ...).
    # A disallowance increases taxable business income.
    disallowances_paise: int = 0
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

    # IT-10. Losses carried forward from earlier years, as brought_forward_losses
    # holds them. Passed straight through to the engine, which sets each off only
    # against the head its own section reaches (§72 business, §73 speculation,
    # §71B house property, §74 capital) — see domain/income_tax/loss_set_off.py.
    #
    # The presumptive figure is here for the same reason: the engine has honoured
    # it since IT-01, and no request model carried it, so the §44AD/§44ADA/§44AE
    # branch was unreachable from this endpoint (IT-16).
    brought_forward_losses: list[BroughtForwardLossInput] = Field(default_factory=list)
    presumptive_income_paise: Optional[int] = Field(default=None, ge=0)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/compute")
def compute_itr(req: ComputeITRRequest, current_user: dict = Depends(rbac("income_tax", "compute"))):
    """
    Compute ITR tax liability from income and deduction inputs.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
    Returns full computation working, deduction breakdown, and net payable/refund.
    """
    # Resolve WHO is being assessed before anything is computed. An unmapped
    # entity type is REFUSED rather than defaulted to "individual": the default
    # is what produced the defect, and it produced it silently.
    kind = req.assessee_kind
    if kind is None:
        if req.entity_type is None:
            kind = "individual"
        else:
            kind, refusal = assessee_kind_for_entity_type(req.entity_type)
            if kind is None:
                raise HTTPException(status_code=422, detail=refusal)
    elif kind not in ("individual", "firm", "llp", "domestic_company"):
        raise HTTPException(
            status_code=422,
            detail=(f"Unknown assessee kind {kind!r}. Expected one of "
                    "individual, firm, llp, domestic_company."))

    engine_req = ITRComputeRequest(
        fy=req.fy,
        assessee_kind=kind,
        company_regime=req.company_regime,
        turnover_in_reference_year_paise=req.turnover_in_reference_year_paise,
        book_profit_paise=req.book_profit_paise,
        claimed_specified_deduction=req.claimed_specified_deduction,
        assessment_year_end=req.assessment_year_end,
        gross_salary_paise=req.gross_salary_paise,
        other_income_paise=req.other_income_paise,
        house_property_income_paise=req.house_property_income_paise,
        business_income_paise=req.business_income_paise,
        disallowances_paise=req.disallowances_paise,
        presumptive_income_paise=req.presumptive_income_paise,
        brought_forward_losses=[
            BroughtForwardLoss(
                loss_type=l.loss_type,
                amount_paise=l.amount_paise,
                assessment_year=l.assessment_year,
                expiry_assessment_year=l.expiry_assessment_year,
                is_expired=l.is_expired,
                source_itr_ack=l.source_itr_ack,
            )
            for l in req.brought_forward_losses
        ],
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
                subject_to_qualifying_limit=d.subject_to_qualifying_limit,
                paid_in_cash=d.paid_in_cash,
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
        # WHO was assessed, and on what basis. Reported rather than inferred
        # from `regime`: a firm has no regime at all, and a screen reading
        # `regime === "new" ? "New" : "Old"` printed "Old Regime" for one.
        "assessee": {
            "kind": result.assessee_kind,
            "rate_percent": result.entity_rate_percent,
            # The year the 25%/30% turnover test looks at — two back, never the
            # year being taxed.
            "turnover_reference_fy": result.turnover_reference_fy,
            "workings": result.entity_workings,
        },
        # §115JB / §115JC. `credit_paise` is the point: §115JAA and §115JD carry
        # the excess forward for fifteen assessment years, and charging the
        # floor without recording the credit turns a timing difference into a
        # permanent cost that is invisible in the year it is incurred.
        "minimum_tax": {
            "section": result.minimum_tax_section,
            "applies": result.minimum_tax_applies,
            "minimum_tax_paise": result.minimum_tax_paise,
            "applied": result.minimum_tax_applied,
            "credit_paise": result.minimum_tax_credit_paise,
            "credit_expires_after_ay": result.minimum_tax_credit_expires_after_ay,
            "reasons": result.minimum_tax_reasons,
        },
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
        # What the brought-forward losses actually relieved, and the working
        # behind it: which section reached which head, and what is carried
        # forward still. A total with no breakdown is not checkable, and a
        # loss the statute would not let through has to be visibly NOT set off
        # rather than quietly absent.
        "brought_forward": {
            "set_off_paise": result.brought_forward_set_off_paise,
            "lines": result.brought_forward_set_off,
        },
        "warnings": result.warnings,
        "validation_errors": result.validation_errors,
        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        "ca_review_required": True,
    })


@router.get("/financial-years")
def supported_financial_years(current_user: dict = Depends(rbac("income_tax", "read"))):
    """The financial years this build can actually compute.

    THE DEAD-CONTROL RULE, applied to a dropdown.
        statutory_rates.rates_for() falls back to the latest verified year for
        any FY not in its registry. That is right for a FUTURE year — the
        Finance Act has not been passed, so carrying the last known rates
        forward and flagging them is the honest answer. It is wrong for a PAST
        year, whose rates are settled, published and different: FY 2023-24 has
        its own new-regime slabs, its own ₹7,00,000 §87A threshold and its own
        pre-Budget-2024 capital gains rates.

        The tax workspace's picker offered three years and the registry held
        two of them, so two of the three silently computed at the wrong year's
        rates with nothing on screen to say so. A screen must not offer a year
        the engine cannot compute; only the server knows which those are.
    """
    from domain.income_tax.statutory_rates import RATES_BY_FY, current_fy
    years = sorted(RATES_BY_FY.keys(), reverse=True)
    return api_response(True, {
        "financial_years": [
            {"fy": fy, "verified": RATES_BY_FY[fy].verified}
            for fy in years
        ],
        "current_fy": current_fy(),
    })


@router.get("/assessee-kind")
def resolve_assessee_kind(
    entity_type: str = Query(..., description="The raw clients.entity_type value"),
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    """Which assessee a client's entity type makes them, and why not.

    THE SAME RULE AS /financial-years, applied to a form rather than a dropdown.
    A screen has to know BEFORE it computes whether to offer a §115BAC new/old
    election or a §115BAA/§115BAB one, and whether to ask for book profit —
    and that answer is statutory (a PROPRIETORSHIP is an individual; a trust is
    refused because §§11-13 and §164 are not modelled). CLAUDE.md keeps
    statutory rules in apps/api, so the screen asks rather than deciding.

    A refusal comes back as `kind: null` with the sentence, so the screen can
    say WHAT is missing instead of offering a computation that will 422.
    """
    kind, refusal = assessee_kind_for_entity_type(entity_type)
    return api_response(True, {
        "entity_type": entity_type,
        "kind": kind,
        "is_entity": kind in ("firm", "llp", "domestic_company"),
        "refusal": refusal,
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
    # The fifth proviso to §112(1) lets a RESIDENT INDIVIDUAL OR HUF pay the
    # lower of 12.5% without indexation and 20% with it, on immovable property
    # acquired before 23-07-2024. A company, an LLP or a non-resident never
    # gets it. Defaulting to "unspecified" charges the flat 12.5% and returns
    # both candidate figures with a note saying why the option was withheld —
    # so an unanswered question reads as an unanswered question rather than as
    # a claim nobody was entitled to make.
    assessee_type: str = ASSESSEE_UNSPECIFIED

    @field_validator("assessee_type")
    @classmethod
    def valid_assessee_type(cls, v: str) -> str:
        if v not in ASSESSEE_TYPES:
            raise ValueError(f"assessee_type must be one of {sorted(ASSESSEE_TYPES)}")
        return v

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
        assessee_type=req.assessee_type,
    )
    return api_response(True, _cg_response(result))


@router.get("/capital-gains")
def list_capital_gains(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    # Sweep finding: client_id came from the query string and was only
    # ever filtered into the firm-scoped WHERE clause, never checked
    # against the caller's assignment — an unassigned Executive/Reviewer
    # could list another staff member's assigned client's capital-gains
    # register just by supplying its id. create_capital_gains already
    # closed this for the write side (see the task #238 comment below).
    assert_client_access(current_user, client_id)
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
    # task #238 audit finding: client_id was caller-supplied and never checked
    # against the caller's firm, unlike this file's own save_advance_tax
    # (task #230 fix) — the identical gap, missed on this sibling endpoint.
    assert_client_access(current_user, req.client_id)
    db = _db()
    result = compute_capital_gains(
        req.asset_type, req.purchase_date, req.sale_date,
        req.purchase_cost_paise, req.sale_value_paise, req.improvement_cost_paise,
        assessee_type=req.assessee_type,
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


def _assert_capital_gains_scope(current_user: dict, record_id: str, db) -> None:
    """Resolve a capital_gains row and 404 unless it belongs to the caller's
    firm and the caller may access its client. Row-addressed by record_id, so
    (unlike list/create) there is no client_id to check until the row is
    fetched — delete_capital_gains previously checked only firm_id, letting
    an unassigned Executive/Reviewer delete another staff member's assigned
    client's capital-gains record. Mock mode (db is None) has no persistent
    store to protect against, matching every other handler in this module."""
    if db is None:
        return
    row = (db.table("capital_gains").select("client_id").eq("id", record_id)
           .eq("firm_id", current_user["firm_id"]).execute())
    rec = (row.data or [None])[0]
    if not rec or not can_access_client(current_user, rec.get("client_id")):
        raise HTTPException(status_code=404, detail="Capital gains record not found")


@router.delete("/capital-gains/{record_id}")
def delete_capital_gains(
    record_id: str,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    db = _db()
    _assert_capital_gains_scope(current_user, record_id, db)
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
    fy: FYLabel
    estimated_tax_paise: int = Field(ge=0)
    installments: list[AdvanceTaxInstallmentInput] = Field(default_factory=list)
    #: §211(1) proviso — a §44AD/§44ADA assessee pays the whole advance tax by
    #: 15 March, so there is ONE instalment and §234C(1)(b) is the charging
    #: limb. Supplied rather than inferred: whether §44AD or §44ADA is opted
    #: into is the CA's determination, and no figure this endpoint receives
    #: decides it (IT-06).
    is_presumptive_44ad_44ada: bool = False

    @field_validator("installments")
    @classmethod
    def one_entry_per_installment_number(cls, v: list[AdvanceTaxInstallmentInput]) -> list[AdvanceTaxInstallmentInput]:
        numbers = [i.installment_number for i in v]
        if len(numbers) != len(set(numbers)):
            raise ValueError("installments must not repeat an installment_number")
        return v


def _at_response(estimated_tax_paise: int, req_installments: list[AdvanceTaxInstallmentInput],
                 fy: str, *, is_presumptive_44ad_44ada: bool = False) -> dict:
    result = compute_234c_interest(
        fy, estimated_tax_paise,
        [InstallmentPayment(i.installment_number, i.paid_amount_paise, i.paid_date) for i in req_installments],
        is_presumptive_44ad_44ada=is_presumptive_44ad_44ada,
    )
    return {
        "fy": fy,
        "estimated_tax_paise": estimated_tax_paise,
        "total_interest_paise": result.total_interest_paise,
        # Which limb, not just which section. §234C(1)(a) and §234C(1)(b) are
        # different sentences with different schedules, and a response that says
        # only "Section 234C" leaves a one-instalment answer looking like a
        # three-instalment one that lost its rows.
        "section_ref": ("Section 234C(1)(b)" if result.is_presumptive_44ad_44ada
                        else "Section 234C(1)(a)"),
        "is_presumptive_44ad_44ada": result.is_presumptive_44ad_44ada,
        "basis": result.basis,
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

    TWO SCHEDULES, AND THE CALLER SAYS WHICH (IT-06). §208 gives four
    instalments; the proviso to §211(1) gives a §44AD/§44ADA assessee ONE, the
    whole amount by 15 March. This charged such an assessee for deferring three
    instalments that were never due — ₹1,00,000 paid in full on 15 March, exactly
    as the statute requires, came back with ₹4,050 of interest.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal"""
    return api_response(True, _at_response(
        req.estimated_tax_paise, req.installments, req.fy,
        is_presumptive_44ad_44ada=req.is_presumptive_44ad_44ada))


# ── §234A and §234B — the two the CA could not reach (IT-13) ─────────────────
#
# advance_tax_interest_engine has carried compute_234a_interest and
# compute_234b_interest, complete and tested, while this router imported only
# compute_234c_interest. So a CA saw the instalment-shortfall interest and
# neither of the other two, and the three are not alternatives: §234C charges
# fixed notional periods per instalment, §234B charges the actual months from
# 1 April of the assessment year where advance tax plus TDS fell below 90% of
# assessed tax, and §234A charges the delay in FURNISHING the return. A return
# filed late on fully-paid tax owes 234A and nothing else; a return filed on
# time on half-paid tax owes 234B and nothing else.


class ComputeSection234ABRequest(BaseModel):
    """Everything both sections need, plus the three facts that decide the
    §139(1) due date — because §234A's whole charge hangs on that date and
    guessing it is not available.

    The due date is NOT accepted from the caller. It is derived by
    compliance_obligation_service.itr_due_date_for_client, which is the one
    authority for it, and its `decided` / `basis` / `statutory_gaps` come back
    in the response. Where the statute does not settle it on facts the app
    holds, that service returns the EARLIER of the two dates and says so —
    early costs nothing and late costs exactly this interest.
    """
    fy: FYLabel
    tax_on_total_income_paise: int = Field(ge=0)
    #: §234B charges on ASSESSED tax. It is normally the same figure as the tax
    #: on total income; it is a separate field because the two diverge after an
    #: assessment, and silently reusing one for the other would charge the
    #: wrong base on the section whose base is the whole argument.
    assessed_tax_paise: Optional[int] = Field(default=None, ge=0)
    tds_tcs_paise: int = Field(default=0, ge=0)
    advance_tax_paid_paise: int = Field(default=0, ge=0)
    relief_paise: int = Field(default=0, ge=0)
    #: None means NOT YET FURNISHED, which is not the same as nil interest —
    #: the engine runs the period to the assessment date and says it is still
    #: running. Reporting zero for an unfiled return would tell a CA the
    #: cheapest moment to file is never.
    return_furnished_on: Optional[str] = None
    assessment_date: Optional[str] = None
    entity_type: Optional[str] = None
    has_tax_audit_engagement: bool = False
    has_transfer_pricing_report: bool = False

    @field_validator("return_furnished_on", "assessment_date")
    @classmethod
    def a_real_date_or_nothing(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, ""):
            return None
        try:
            date.fromisoformat(v[:10])
        except ValueError:
            raise ValueError("dates must be ISO YYYY-MM-DD")
        return v[:10]


def _section_interest_payload(r) -> dict:
    return {
        "section": r.section,
        "applies": r.applies,
        "base_paise": r.base_paise,
        "months": r.months,
        "interest_paise": r.interest_paise,
        "from_date": r.from_date.isoformat() if r.from_date else None,
        "to_date": r.to_date.isoformat() if r.to_date else None,
        # Shown, not summarised: each sentence names the rule it applied and
        # the figures it applied it to, which is what a CA checks.
        "reasons": list(r.reasons),
    }


@router.post("/interest/234ab")
def compute_234ab_interest(
    req: ComputeSection234ABRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Stateless §234A and §234B interest — persists nothing.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal"""
    due = itr_due_date_for_client(
        req.fy,
        entity_type=req.entity_type,
        has_tax_audit_engagement=req.has_tax_audit_engagement,
        has_transfer_pricing_report=req.has_transfer_pricing_report,
    )
    due_date = date.fromisoformat(due["due_date"])
    assessment_date = date.fromisoformat(req.assessment_date) if req.assessment_date else ist_today()
    furnished = date.fromisoformat(req.return_furnished_on) if req.return_furnished_on else None

    s234a = compute_234a_interest(
        tax_on_total_income_paise=req.tax_on_total_income_paise,
        tds_tcs_paise=req.tds_tcs_paise,
        advance_tax_paid_paise=req.advance_tax_paid_paise,
        relief_paise=req.relief_paise,
        due_date=due_date,
        return_furnished_on=furnished,
        assessment_date=assessment_date,
    )
    # §234B runs from 1 April of the ASSESSMENT year — not the end of the
    # financial year, and not any instalment date.
    s234b = compute_234b_interest(
        assessed_tax_paise=(req.assessed_tax_paise
                            if req.assessed_tax_paise is not None
                            else req.tax_on_total_income_paise),
        advance_tax_paid_paise=req.advance_tax_paid_paise,
        tds_tcs_paise=req.tds_tcs_paise,
        assessment_year_start=date(fy_end_year(req.fy), 4, 1),
        assessment_date=assessment_date,
    )
    return api_response(True, {
        "fy": req.fy,
        "section_234a": _section_interest_payload(s234a),
        "section_234b": _section_interest_payload(s234b),
        "total_interest_paise": s234a.interest_paise + s234b.interest_paise,
        # The provenance of the date §234A is charged from. `decided: false`
        # means the statute does not settle it on facts held here and the
        # EARLIER date was taken — the interest below is then a floor, not a
        # figure to rely on, and statutory_gaps names what would settle it.
        "itr_due_date": due,
        "assessment_date": assessment_date.isoformat(),
        "return_furnished_on": furnished.isoformat() if furnished else None,
    })


# ── §44AD, §44ADA and §44AE — reachable from nothing (IT-16) ─────────────────
#
# The engines are complete and covered by tests/test_presumptive_taxation.py,
# and ITRComputeRequest already honours their output at
# itr_engine.py:presumptive_income_paise — but no request model carried the
# inputs, so the branch was unreachable from outside the test suite. These
# three endpoints are the missing half.


class Compute44ADRequest(BaseModel):
    fy: OptionalFYLabel = None
    turnover_paise: int = Field(ge=0)
    #: The split matters: the 3 crore ceiling and the 6% rate both turn on how
    #: much of the turnover came through a bank. Sending only the total gets
    #: the 8% rate on everything and the lower limit.
    digital_turnover_paise: int = Field(default=0, ge=0)
    cash_receipts_paise: int = Field(default=0, ge=0)
    declared_income_paise: Optional[int] = Field(default=None, ge=0)


class Compute44ADARequest(BaseModel):
    fy: OptionalFYLabel = None
    gross_receipts_paise: int = Field(ge=0)
    cash_receipts_paise: int = Field(default=0, ge=0)
    declared_income_paise: Optional[int] = Field(default=None, ge=0)


class GoodsCarriageInput(BaseModel):
    gross_vehicle_weight_kg: int = Field(gt=0)
    #: Every month or PART of a month owned — a vehicle bought on 28 March is
    #: owned for a part of March and that month is charged in full.
    months_owned: int = Field(ge=0, le=12)


class Compute44AERequest(BaseModel):
    fy: OptionalFYLabel = None
    vehicles: list[GoodsCarriageInput] = Field(default_factory=list)
    declared_income_paise: Optional[int] = Field(default=None, ge=0)


def _presumptive_payload(r) -> dict:
    return {
        "section": r.section,
        "eligible": r.eligible,
        "presumptive_income_paise": r.presumptive_income_paise,
        "declared_income_paise": r.declared_income_paise,
        "turnover_limit_paise": r.turnover_limit_paise,
        "enhanced_limit_applied": r.enhanced_limit_applied,
        "reasons": list(r.reasons),
        "workings": list(r.workings),
    }


@router.post("/presumptive/44ad")
def compute_presumptive_44ad(
    req: Compute44ADRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """§44AD — presumptive income of an eligible business. Persists nothing.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal"""
    return api_response(True, _presumptive_payload(compute_44ad(
        turnover_paise=req.turnover_paise,
        digital_turnover_paise=req.digital_turnover_paise,
        cash_receipts_paise=req.cash_receipts_paise,
        declared_income_paise=req.declared_income_paise,
        fy=req.fy,
    )))


@router.post("/presumptive/44ada")
def compute_presumptive_44ada(
    req: Compute44ADARequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """§44ADA — presumptive income of a specified profession. Persists nothing.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal"""
    return api_response(True, _presumptive_payload(compute_44ada(
        gross_receipts_paise=req.gross_receipts_paise,
        cash_receipts_paise=req.cash_receipts_paise,
        declared_income_paise=req.declared_income_paise,
        fy=req.fy,
    )))


@router.post("/presumptive/44ae")
def compute_presumptive_44ae(
    req: Compute44AERequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """§44AE — presumptive income from goods carriages. Persists nothing.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal"""
    return api_response(True, _presumptive_payload(compute_44ae(
        vehicles=[GoodsCarriage(gross_vehicle_weight_kg=v.gross_vehicle_weight_kg,
                                months_owned=v.months_owned)
                  for v in req.vehicles],
        declared_income_paise=req.declared_income_paise,
        fy=req.fy,
    )))


# ── "This figure goes in this field" (IT-17) ─────────────────────────────────
#
# itr_field_placements is the useful half of a return generator without the
# dangerous half: it says where each computed number belongs in the form and
# leaves the FILE to the department's own utility. Every path in it is checked
# against the seven committed schemas in domain/income_tax/schemas/ by
# tests/test_itr_schema_paths.py — and until now neither it nor build_itr_payload
# was imported anywhere outside those tests, so a CA had the computation and no
# way to see where any of it went.
#
# This deliberately does NOT expose generate_itr_json. That function refuses
# with SoftwareProviderNotRegistered until the Third Party Software Utility
# Developer registration exists, and the refusal is right: a JSON this software
# emits without that registration is not a file the portal will take. See
# docs/compliance/07-getting-permission-to-file.md.

_ITR_FORMS = ("ITR-1", "ITR-2", "ITR-3", "ITR-4", "ITR-5", "ITR-6", "ITR-7")


class ITRFieldPlacementsRequest(BaseModel):
    form: str
    assessment_year: str = "2026-27"
    gross_total_income_paise: int = Field(default=0, ge=0)
    total_deductions_paise: int = Field(default=0, ge=0)
    total_income_paise: int = Field(default=0, ge=0)
    tax_on_total_income_paise: int = Field(default=0, ge=0)
    rebate_87a_paise: int = Field(default=0, ge=0)
    surcharge_paise: int = Field(default=0, ge=0)
    cess_paise: int = Field(default=0, ge=0)
    total_tax_paise: int = Field(default=0, ge=0)
    tds_tcs_paise: int = Field(default=0, ge=0)
    advance_tax_paid_paise: int = Field(default=0, ge=0)
    self_assessment_tax_paise: int = Field(default=0, ge=0)
    interest_234a_paise: int = Field(default=0, ge=0)
    interest_234b_paise: int = Field(default=0, ge=0)
    interest_234c_paise: int = Field(default=0, ge=0)

    @field_validator("form")
    @classmethod
    def a_form_that_exists(cls, v: str) -> str:
        f = (v or "").strip().upper()
        if f not in _ITR_FORMS:
            raise ValueError(f"form must be one of {', '.join(_ITR_FORMS)}")
        return f


@router.post("/itr/field-placements")
def itr_field_placements_endpoint(
    req: ITRFieldPlacementsRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Where each computed figure belongs in the form, in whole rupees.

    Rupee rounding happens HERE and not earlier: this is the statutory payload
    boundary, the same place domain/gst/money.py rounds for GSTR-1 and GSTR-3B.

    `not_on_this_form: true` is an ANSWER, not a missing mapping — §87A has no
    home on ITR-5/6/7 and surcharge none on ITR-1/4, and saying so is what
    stops a CA hunting for a field that does not exist.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
    """
    payload = build_itr_payload(
        form=req.form,
        assessment_year=req.assessment_year,
        gross_total_income_paise=req.gross_total_income_paise,
        total_deductions_paise=req.total_deductions_paise,
        total_income_paise=req.total_income_paise,
        tax_on_total_income_paise=req.tax_on_total_income_paise,
        rebate_87a_paise=req.rebate_87a_paise,
        surcharge_paise=req.surcharge_paise,
        cess_paise=req.cess_paise,
        total_tax_paise=req.total_tax_paise,
        tds_tcs_paise=req.tds_tcs_paise,
        advance_tax_paid_paise=req.advance_tax_paid_paise,
        self_assessment_tax_paise=req.self_assessment_tax_paise,
        interest_234a_paise=req.interest_234a_paise,
        interest_234b_paise=req.interest_234b_paise,
        interest_234c_paise=req.interest_234c_paise,
    )
    return api_response(True, {
        "form": payload.form,
        "assessment_year": payload.assessment_year,
        "placements": itr_field_placements(payload),
        # Whether the paths came from a schema a human downloaded and checked,
        # or from a mapping nobody has confirmed against the department's file.
        # can_emit_file is the SAME fact under its other name (itr_json.py sets
        # both from `verified`): it says the paths are trustworthy, NOT that a
        # file may be produced. The registration gate is separate and lives in
        # generate_itr_json, which this endpoint deliberately does not call.
        "schema_is_verified": payload.schema_is_verified,
        "can_emit_file": payload.can_emit_file,
        "notes": list(payload.notes),
    })


@router.get("/advance-tax")
def list_advance_tax(
    client_id: str = Query(...),
    fy: Annotated[FYLabel, Query()] = ...,
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    # Same gap as list_capital_gains above — client_id was filtered into the
    # query but never checked against the caller's assignment.
    assert_client_access(current_user, client_id)
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
    server-side from the FY's advance-tax schedule, never trusted from the
    client. Interest itself is never stored (it is derived, not a fact);
    call /advance-tax/compute for the current computed breakdown.

    WHICH SCHEDULE (IT-06). §208's four instalments, or the ONE the proviso to
    §211(1) gives a §44AD/§44ADA assessee. Writing four rows for a presumptive
    client records three instalments the statute never required, and the
    register would then disagree with the interest computation beside it — which
    is worse than either being wrong alone.

    Changing a client's basis DELETES the rows the new schedule does not have.
    An upsert alone would leave the three §208 rows behind, and a stale row with
    a real paid_date on it reads as a payment against a live obligation.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal"""
    # task #230 audit finding: client_id was caller-supplied and never
    # checked against the caller's firm. Combined with the (now-fixed, see
    # migration 238) firm_id-blind UNIQUE(client_id, financial_year,
    # installment_number), any authenticated income-tax user could upsert
    # against ANOTHER firm's client_id, silently overwriting that firm's
    # real advance-tax payment record (amount/date/challan) with attacker
    # values and reassigning it to their own firm_id.
    assert_client_access(current_user, req.client_id)
    db = _db()
    due_dates = dict(installment_schedule(
        req.fy, is_presumptive_44ad_44ada=req.is_presumptive_44ad_44ada))
    required_percent = {
        r.number: r.cumulative_required_percent
        for r in installment_rules(
            is_presumptive_44ad_44ada=req.is_presumptive_44ad_44ada)
    }
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
            "required_percent": required_percent[number],
            "estimated_tax_paise": req.estimated_tax_paise,
            "paid_amount_paise": inst.paid_amount_paise if inst else 0,
            "paid_date": inst.paid_date.isoformat() if inst and inst.paid_date else None,
            "challan_number": inst.challan_number if inst else None,
        })
    if not db:
        return api_response(True, rows)
    result = (db.table("advance_tax_payments")
              .upsert(rows, on_conflict="firm_id,client_id,financial_year,installment_number").execute())
    # Rows the schedule no longer has. Only ever non-empty when a client's basis
    # changed — a presumptive client keeps instalment 4 and loses 1, 2 and 3.
    stale = [n for n in (1, 2, 3, 4) if n not in due_dates]
    if stale:
        (db.table("advance_tax_payments").delete()
         .eq("firm_id", current_user["firm_id"]).eq("client_id", req.client_id)
         .eq("financial_year", req.fy).in_("installment_number", stale).execute())
    return api_response(True, result.data or rows)


# ── IT Act §32 and the book-to-tax bridge (IT-09 ≡ FA-06) ────────────────────
#
# Two engines that existed and could not be reached. `book_to_tax_bridge` was
# imported by no router at all — its own docstring said the §32 line was the
# largest single adjustment in the bridge and that nothing in this codebase
# computed it, and both halves of that were true. `domain/income_tax/section_32`
# is the missing half; these two endpoints are what let a CA see either.

class Section32BlockIn(BaseModel):
    """One block's opening position, as only a CA can state it.

    Everything else about a block — its additions, its deletions — is derived
    from the fixed-asset register. These four are not derivable: see
    migration 357, which says why for each.
    """
    client_id: str
    financial_year: FYLabel
    block_key: str = Field(min_length=1, max_length=120)
    #: A block IS a rate under §2(11). Appendix I is a statutory table this
    #: product does not hold, so the rate comes in with the block.
    rate_percent: int = Field(ge=0, le=100)
    #: Off last year's return. No default: a zero is a claim that the block is
    #: empty, and it would allow no depreciation at all.
    opening_wdv_paise: int = Field(ge=0)
    #: §50's second limb. None = nobody has said, and the computation says so.
    assets_remain: Optional[bool] = None
    notes: Optional[str] = None


@router.get("/section-32")
def section_32_depreciation(
    client_id: str,
    fy: Annotated[FYLabel, Query(description="YYYY-YY, e.g. 2025-26")],
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Depreciation allowable under IT Act §32 for one client and one year.

    Per BLOCK, at the block's rate, on the block's written-down value — not per
    asset over a useful life, which is Schedule II and is what the accounts
    carry. See domain/income_tax/section_32.py for what the engine refuses to
    decide and why each refusal is a human step.

    `is_complete` is the field to read before using the figure: false means an
    asset is unassigned, a block has no opening written-down value, or an
    addition has no put-to-use date — each named in `statutory_gaps`.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
    """
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, {"financial_year": fy, "blocks": [],
                                   "depreciation_paise": 0,
                                   "additional_depreciation_paise": 0,
                                   "allowance_paise": 0,
                                   "short_term_capital_gain_paise": 0,
                                   "unclassified_assets": [],
                                   "blocks_without_opening_wdv": [],
                                   "statutory_gaps": [], "is_complete": True})
    from services.section_32_service import section_32_service
    return api_response(True, section_32_service.assemble(
        db, current_user["firm_id"], client_id, fy))


@router.put("/section-32/blocks")
def upsert_section_32_block(
    req: Section32BlockIn,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Record a block's opening written-down value and rate for a year.

    One row per (client, year, block): the computation reads exactly one, and a
    second would silently double the opening figure — which is why the unique
    key is on the table and this is an upsert rather than an insert.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
    """
    assert_client_access(current_user, req.client_id)
    db = _db()
    row = {
        "firm_id": current_user["firm_id"], "client_id": req.client_id,
        "financial_year": req.financial_year, "block_key": req.block_key.strip(),
        "rate_percent": req.rate_percent,
        "opening_wdv_paise": req.opening_wdv_paise,
        "assets_remain": req.assets_remain, "notes": req.notes,
        # public.users.id — the INTERNAL user id, not the Supabase auth id
        # (CLAUDE.md).
        "created_by": current_user.get("id"),
    }
    if not db:
        return api_response(True, row)
    out = (db.table("income_tax_asset_blocks")
           .upsert(row, on_conflict="firm_id,client_id,financial_year,block_key")
           .execute())
    return api_response(True, (out.data or [row])[0])


class BookToTaxBridgeRequest(BaseModel):
    """The bridge's inputs. §32 is fetched, not supplied."""
    client_id: str
    fy: FYLabel
    book_profit_paise: int
    disallowances_paise: int = 0
    depreciation_per_books_paise: int = 0
    brought_forward_loss_set_off_paise: int = 0


@router.post("/book-to-tax-bridge")
def book_to_tax_bridge(
    req: BookToTaxBridgeRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Profit per the accounts, down to taxable income, one named adjustment at
    a time.

    The §32 figure is READ from the block register rather than taken from the
    caller — that was the whole reason the bridge sat unreachable. Where the
    block register is incomplete the figure is withheld and the bridge marks
    ITSELF incomplete, which is exactly what it was built to do: assuming the
    two depreciation figures equal would make the bridge foot perfectly while
    understating the difference to nil, and a bridge that reconciles and lies is
    worse than one that refuses to reconcile.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
    """
    assert_client_access(current_user, req.client_id)
    from domain.income_tax.book_to_tax_bridge import build_bridge

    section_32 = None
    db = _db()
    if db:
        from services.section_32_service import section_32_service
        section_32 = section_32_service.assemble(
            db, current_user["firm_id"], req.client_id, req.fy)

    bridge = build_bridge(
        book_profit_paise=req.book_profit_paise,
        disallowances_paise=req.disallowances_paise,
        depreciation_per_books_paise=req.depreciation_per_books_paise,
        depreciation_under_section_32_paise=(
            section_32["allowance_paise"]
            if section_32 and section_32["is_complete"] else None),
        brought_forward_loss_set_off_paise=req.brought_forward_loss_set_off_paise,
    )
    return api_response(True, {
        "book_profit_paise": bridge.book_profit_paise,
        "lines": [
            {"label": l.label, "amount_paise": l.amount_paise,
             "direction": l.direction, "reference": l.reference,
             "derived": l.derived, "note": l.note}
            for l in bridge.lines
        ],
        "taxable_income_paise": bridge.taxable_income_paise,
        "is_complete": bridge.is_complete,
        "missing": list(bridge.missing),
        "reasons": list(bridge.reasons),
        "foots": bridge.foots(),
        # The §32 answer beside the bridge, so a CA who sees "incomplete" can
        # see WHY without a second request.
        "section_32": section_32,
    })
