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
from domain.income_tax.assessee import AssesseeKind, assessee_kind_for_entity_type
from domain.income_tax.chapter_vi_a import ChapterVIAClaims
from domain.income_tax import self_assessment as sa_domain
from services import self_assessment_service
from domain.income_tax import msmed_interest as _msmed
from domain.income_tax import reinvestment_exemption as rex
from services import capital_gain_exemption_service as cgx
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
from models.fy import AYLabel, FYLabel, OptionalAYLabel, OptionalFYLabel
from core.ist_clock import normalise_fy_label

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
    # THE WAY INTO THE §80CCE CAP FOR EVERYTHING §80C(2) LISTS AND THIS FORM
    # DOES NOT. Deductions80C has carried `other_paise` since it was written
    # (itr_engine.py) and no request model exposed it, so a CA with stamp duty
    # on a house, an §80CCD(1) contribution or a scheduled-bank term deposit
    # had nowhere to put it except `other_deductions_paise` — which is OUTSIDE
    # §80CCE and so escapes the ₹1,50,000 cap altogether. Claimed here it is
    # inside the cap, which is where §80CCE puts it.
    other_paise: int = 0


class S80DInput(BaseModel):
    self_family_premium_paise: int = 0
    self_family_is_senior: bool = False
    parents_premium_paise: int = 0
    parents_is_senior: bool = False
    #: A PREVENTIVE HEALTH CHECK-UP is allowed WITHIN the ceiling, not on top
    #: of it — ₹5,000 of the ₹25,000 or ₹50,000. It is also the one part of
    #: §80D that may be paid in cash.
    self_family_preventive_paise: int = 0
    parents_preventive_paise: int = 0
    #: MEDICAL EXPENDITURE on an UNINSURED senior citizen, against the same
    #: ceiling. The route a CA needs most often — an eighty-year-old parent no
    #: insurer will cover — and there was no field for it, so the spend went
    #: into the unlabelled "other deductions" figure with no cap at all.
    self_family_medical_paise: int = 0
    parents_medical_paise: int = 0


def _chapter_vi_a_claims(inp: "ChapterVIAInput") -> ChapterVIAClaims:
    """The API shape into the domain shape, with the one DATE parsed here.

    The boundary parses; the rule does not. `housing_loan_sanctioned_on`
    arrives as a string and `chapter_vi_a.housing_loan_section` takes a `date`,
    so a malformed one becomes None — which that function reads as "no date
    given" and answers by allowing NOTHING, because §80EE's and §80EEA's limits
    differ by ₹1,00,000 and there is no safe default between them.
    """
    from datetime import date as _date

    sanctioned = None
    raw = (inp.housing_loan_sanctioned_on or "").strip()
    if raw:
        try:
            sanctioned = _date.fromisoformat(raw[:10])
        except ValueError:
            sanctioned = None
    return ChapterVIAClaims(
        education_loan_interest_paise=inp.education_loan_interest_paise,
        education_loan_year=inp.education_loan_year,
        housing_loan_extra_interest_paise=inp.housing_loan_extra_interest_paise,
        housing_loan_sanctioned_on=sanctioned,
        has_disabled_dependant=inp.has_disabled_dependant,
        dependant_disability_is_severe=inp.dependant_disability_is_severe,
        assessee_is_disabled=inp.assessee_is_disabled,
        assessee_disability_is_severe=inp.assessee_disability_is_severe,
        specified_disease_spend_paise=inp.specified_disease_spend_paise,
        specified_disease_reimbursed_paise=inp.specified_disease_reimbursed_paise,
        patient_is_senior=inp.patient_is_senior,
        rent_paid_paise=inp.rent_paid_paise,
        receives_hra=inp.receives_hra,
    )


class ChapterVIAInput(BaseModel):
    """§80E, §80EE/§80EEA, §80DD, §80DDB, §80U and §80GG (IT-32).

    Everything here used to be lumped into `other_deductions_paise` — one
    unlabelled figure with no ceiling and no section attribution, which is
    exactly the set of deductions most likely to be questioned.
    `domain/income_tax/chapter_vi_a.py` is the authority for every limit.

    The two DISABILITY facts are booleans rather than a percentage on purpose:
    the Act's test is a CERTIFIED band (40% and 80%), a typed 79 and a typed 80
    differ by ₹50,000 of deduction, and it is the Form 10-IA certificate that
    decides — not a number a form should invite somebody to guess at.
    """
    education_loan_interest_paise: int = 0
    #: Which of §80E's eight assessment years this is. Omitting it is allowed
    #: and NAMED: the deduction runs out and nothing here counts the years.
    education_loan_year: Optional[int] = Field(default=None, ge=1)
    housing_loan_extra_interest_paise: int = 0
    #: §80EE and §80EEA are shut windows keyed on the SANCTION date, which fixes
    #: the section for the life of the loan. Their limits differ by ₹1,00,000,
    #: so an absent date allows NOTHING rather than one being assumed.
    housing_loan_sanctioned_on: Optional[str] = None
    has_disabled_dependant: bool = False
    dependant_disability_is_severe: bool = False
    assessee_is_disabled: bool = False
    assessee_disability_is_severe: bool = False
    specified_disease_spend_paise: int = 0
    specified_disease_reimbursed_paise: int = 0
    #: The PATIENT's age band sets §80DDB's ceiling, not the assessee's.
    patient_is_senior: bool = False
    rent_paid_paise: int = 0
    #: §80GG is only for an assessee who receives NO house rent allowance.
    #: Where HRA is received, §10(13A) is the relief and is already computed.
    receives_hra: bool = False


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
    assessment_year: OptionalAYLabel = None
    expiry_assessment_year: OptionalAYLabel = None
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

    # WAS THIS ASSESSEE RESIDENT IN INDIA THIS YEAR (§6)?
    #
    # Defaults True, which is what this endpoint has always assumed — §87A is
    # granted unconditionally and reaches only "an individual, being a
    # resident". Exposing it changes nothing for an existing caller and lets
    # one that knows better say so: a NON-resident individual does not get the
    # basic-exemption absorption in the provisos to §111A(1), §112(1)(a)(ii)
    # and §112A(2), and is charged on the whole capital gain.
    #
    # Not read off the client record on purpose — `clients` has no residential
    # status column, and §6 turns on days present in India, which no ledger
    # holds. This is the CA's answer, not a derived one.
    is_resident: bool = True

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
    chapter_vi_a: ChapterVIAInput = Field(default_factory=ChapterVIAInput)
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
        is_resident=req.is_resident,
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
            other_paise=req.s80c.other_paise,
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
            self_family_preventive_paise=req.s80d.self_family_preventive_paise,
            parents_preventive_paise=req.s80d.parents_preventive_paise,
            self_family_medical_paise=req.s80d.self_family_medical_paise,
            parents_medical_paise=req.s80d.parents_medical_paise,
        ),
        chapter_vi_a=_chapter_vi_a_claims(req.chapter_vi_a),
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
        # WHAT EACH HEAD CAME TO (IT-17). These are the figures a CA keys into
        # Part B-TI, and they are NOT the request's own inputs: salary is after
        # the §16(ia) standard deduction, business after the disallowances were
        # added back and any presumptive substitution applied, each capital head
        # after the brought-forward loss §72/§74 let it absorb. The form's head
        # lines ask for income CHARGEABLE UNDER THE HEAD, so the inputs would be
        # the wrong figure under the right label.
        #
        # Empty for a firm, an LLP or a company — the entity branch computes one
        # figure and has no heads, which `assessee` already reports.
        "income_heads": result.income_heads_paise,
        "deductions": {
            "s80c_paise": result.deduction_80c_paise,
            "s80ccd_paise": result.deduction_80ccd_paise,
            "s80ccd2_paise": result.deduction_80ccd2_paise,
            "s80d_paise": result.deduction_80d_paise,
            "s80g_paise": result.deduction_80g_paise,
            "s80tta_paise": result.deduction_80tta_paise,
            "hra_paise": result.deduction_hra_paise,
            "s24b_paise": result.deduction_24b_paise,
            # IT-32. §80E, §80EE/§80EEA, §80DD, §80DDB, §80U and §80GG, ONE
            # LINE EACH — what was claimed, what was allowed, and the sentence
            # naming the ceiling that bit. A total alone would restate exactly
            # what `other_deductions_paise` was: these are the deductions most
            # likely to be questioned, and the CA is the one who has to defend
            # the working. `restricted_paise` on a line is the part the section
            # did NOT allow, which is invisible in any total.
            "chapter_vi_a_paise": result.chapter_vi_a_paise,
            "chapter_vi_a_lines": result.chapter_vi_a_lines,
        },
        "tax": {
            "tax_before_cess_paise": result.tax_before_cess_paise,
            "rebate_87a_paise": result.rebate_87a_paise,
            "surcharge_paise": result.surcharge_paise,
            "cess_paise": result.cess_paise,
            "total_tax_paise": result.total_tax_paise,
        },
        # THE CAPITAL-GAINS WORKING, WHICH NOTHING USED TO CARRY OUT OF THE
        # ENGINE. `basic_exemption_absorbed_paise` and
        # `basic_exemption_absorption` were computed and documented as existing
        # "so a CA can see WHICH gain the exemption was set against"; a grep
        # across the routers and the whole frontend returned nothing. So the
        # screen showed ₹20,800 of tax on a ₹5,00,000 STCG and no account of
        # the ₹4,00,000 that vanished — the right number with its reasoning
        # withheld, on a working the CA is the one who has to defend.
        #
        # The absorption is a CHOICE the statute does not make: the provisos to
        # §111A(1), §112(1)(a)(ii) and §112A(2) fix no order between the three,
        # and this engine takes the highest rate first because that is most
        # beneficial. A reader is entitled to check that, which they cannot do
        # from a total.
        "capital_gains": {
            "lines": result.capital_gains_lines,
            "tax_paise": result.capital_gains_tax_paise,
            "basic_exemption_absorbed_paise": result.basic_exemption_absorbed_paise,
            "basic_exemption_absorption": result.basic_exemption_absorption,
        },
        # §10 income, echoed rather than acted on. It does not enter total
        # income and the tax is right without it — but the field is on the
        # request, the client Tax Computation tab renders an input for it, and
        # until now `compute()` never read it, so a CA typed a figure that
        # changed nothing and nothing said so. Reported here so the screen can
        # say "received, not taxable" instead of silently discarding it.
        "exempt_income": {
            "reported_paise": result.exempt_income_reported_paise,
            "note": "Section 10 income is reported (Schedule EI) and is not "
                    "part of total income, so it does not change the tax.",
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
    from services.compliance_engine import advance_tax_due_dates
    years = sorted(RATES_BY_FY.keys(), reverse=True)
    fy_now = current_fy()
    return api_response(True, {
        "financial_years": [
            {"fy": fy, "verified": RATES_BY_FY[fy].verified}
            for fy in years
        ],
        "current_fy": fy_now,
        # THE INSTALMENT CALENDAR FOR THE YEAR THIS RESPONSE ALREADY NAMES
        # (IT-33). The Income Tax hub carried four hardcoded strings — "15 Jun
        # 2025" through "15 Mar 2026" — under a heading that also hardcoded
        # "FY 2025-26", so on any date in FY 2026-27 the first panel of the
        # module showed four elapsed instalments for the wrong year. §211's
        # dates are derived by `compliance_engine.advance_tax_due_dates` and
        # always were; nothing called it from here.
        #
        # Served beside `current_fy` rather than from a new endpoint, and from
        # the SERVER rather than computed in the browser from `new Date()`:
        # `current_fy` is IST (core.ist_clock), and a browser in another zone
        # flips the financial year on 31 March.
        "current_fy_advance_tax": advance_tax_due_dates(int(fy_now[:4]) + 1),
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


@router.get("/tax-audit/applicability")
def tax_audit_applicability(
    nature: str = Query(..., description="business | profession — the ACTIVITY, never inferred from the amount"),
    turnover_paise: int = Query(..., ge=0, description="Sales/turnover for a business, gross receipts for a profession"),
    financial_year: Annotated[OptionalFYLabel, Query()] = None,
    cash_receipts_paise: Optional[int] = Query(None, ge=0),
    cash_payments_paise: Optional[int] = Query(None, ge=0),
    total_payments_paise: Optional[int] = Query(None, ge=0),
    is_company: bool = Query(False),
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    """Whether §44AB requires a tax audit, on the facts stated.

    THE SCREEN USED TO DECIDE THIS ITSELF, AND GOT IT BACKWARDS (IT-11). The
    Tax Audit tracker read the NATURE of the activity off the AMOUNT — above
    ₹1 crore it said "business", between ₹50 lakh and ₹1 crore it said
    "profession" — so a trader with ₹60 lakh of turnover was told an audit was
    mandatory when clause (a) does not reach them at all. It also never
    applied the proviso to §44AB(a), so a client with ₹4 crore of turnover and
    2% of it in cash was told the same. CLAUDE.md: statutory rules live in
    apps/api.

    Reads nothing and writes nothing — this is arithmetic on figures the
    caller states, like the §32 and HRA endpoints beside it. It does NOT
    decide the ITR due date: `compliance_obligation_service.itr_due_date_for_client`
    is the authority for that and deliberately refuses where no audit
    engagement is recorded, because an applicability ANSWER is not the same
    fact as an audit actually being carried out.
    """
    from domain.income_tax import tax_audit as ta
    try:
        result = ta.answer(
            nature=nature,
            turnover_paise=turnover_paise,
            financial_year=financial_year,
            cash_receipts_paise=cash_receipts_paise,
            cash_payments_paise=cash_payments_paise,
            total_payments_paise=total_payments_paise,
            is_company=is_company,
        )
    except ValueError as e:
        return api_response(False, None, str(e))

    data = result.to_dict()
    # The SPECIFIED DATE, derived rather than restated — Explanation (ii) to
    # §44AB is one month before the §139(1) date, and compliance_engine owns
    # both so a CBDT extension of one moves the other.
    if result.required:
        from services import compliance_engine as ce
        fye = fy_end_year(result.financial_year)
        data["report_due_date"] = ce.tax_audit_report_due_date(fye).isoformat()
        data["return_due_date"] = ce.itr_due_date(fye, is_audit=True).isoformat()
    else:
        data["report_due_date"] = None
        data["return_due_date"] = None
    return api_response(True, data)


@router.get("/regime-election")
def regime_election(
    wants_old_regime: bool = Query(..., description="What the client wants for this year"),
    has_business_income: bool = Query(..., description="THE FACT THE WHOLE RULE TURNS ON — §115BAC(6) has two clauses, not one rule with variations"),
    financial_year: Annotated[FYLabel, Query()] = ...,
    form_10iea_filed_on: Optional[str] = Query(None, description="The date it was ACTUALLY filed (YYYY-MM-DD); omit if it has not been"),
    is_audit: bool = Query(False),
    has_transfer_pricing_report: bool = Query(False),
    business_income_ceased: bool = Query(False, description="§115BAC(6)(i)'s escape — clause (ii) becomes available instead"),
    prior: list[str] = Query(default_factory=list, description="An earlier year's election as FY:action, e.g. 2024-25:opted_out or 2025-26:withdrew. Repeat the parameter."),
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    """Which regime applies, and what the CA must do to get there.

    `domain/income_tax/regime_election.py` has held §115BAC(6) and Rule 21AGA
    since it was written and **had no caller at all** — the module's own
    docstring says why that mattered: a missed Form 10-IEA taxes a client on
    the new regime for a year they planned around the old one and CANNOT be
    cured after the due date, and a withdrawal made without realising it is
    final closes an option worth lakhs over a career. Neither failure is
    visible in the return, which computes cleanly either way.

    Reads nothing and writes nothing — arithmetic and dates on facts the
    caller states, like the §44AB and HRA endpoints beside it. The due date
    comes from `compliance_engine.itr_due_date` through the domain module, so
    a CBDT extension moves it here too.

    PRIOR-YEAR HISTORY IS AN INPUT, NEVER ASSUMED. The product holds no filing
    history, so clause (i)'s once-only withdrawal cannot be derived. Supplying
    nothing is answered as `history_unknown`, which is a DIFFERENT answer from
    "the option is available": assuming availability would tell a CA the old
    regime is open when their client spent it years ago, and that is the
    dangerous direction.
    """
    from domain.income_tax import regime_election as re_mod

    filed_on = None
    if form_10iea_filed_on:
        try:
            filed_on = date.fromisoformat(str(form_10iea_filed_on)[:10])
        except ValueError:
            return api_response(False, None,
                                "form_10iea_filed_on must be a date (YYYY-MM-DD).")

    # `FY:action`, parsed HERE rather than in the domain module: the wire
    # format is this endpoint's business and the rule is not.
    prior_elections: list[re_mod.PriorElection] = []
    for raw in prior:
        fy, _, action = str(raw).partition(":")
        action = action.strip().lower()
        if action not in ("opted_out", "withdrew"):
            return api_response(False, None, (
                f"'{raw}' is not a prior election. Use FY:action, where action "
                f"is opted_out or withdrew — e.g. 2024-25:withdrew."))
        try:
            fy = normalise_fy_label(fy)
        except ValueError as e:
            return api_response(False, None, f"'{raw}': {e}")
        prior_elections.append(re_mod.PriorElection(fy=fy, action=action))

    result = re_mod.evaluate_election(
        wants_old_regime=wants_old_regime,
        has_business_income=has_business_income,
        financial_year_end=fy_end_year(financial_year),
        form_10iea_filed_on=filed_on,
        is_audit=is_audit,
        has_transfer_pricing_report=has_transfer_pricing_report,
        prior_elections=prior_elections or None,
        business_income_ceased=business_income_ceased,
    )
    return api_response(True, {
        "financial_year": financial_year,
        "regime": result.regime,
        "route": result.route,
        "form_10iea_required": result.form_10iea_required,
        "due_date": result.due_date.isoformat() if result.due_date else None,
        "election_is_available": result.election_is_available,
        "history_unknown": result.history_unknown,
        "reasons": list(result.reasons),
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
    # IT-28. The proviso to §2(42A) gives a security LISTED in a recognised
    # stock exchange in India a 12-month holding period against 24 for
    # everything else, and `asset_type` cannot carry it. A TRI-STATE: None
    # means nobody recorded it, which takes the unlisted period — more tax,
    # not less — and comes back as a named gap on the response.
    is_listed_security: Optional[bool] = None
    # IT-19. §55(2)(ac) deems the cost of a §112A asset acquired before
    # 01-02-2018 to be the higher of the actual cost and the lower of this and
    # the sale value. The WHOLE holding's figure, not a per-share price. None
    # leaves the actual cost standing and names the over-statement.
    fmv_31_01_2018_paise: Optional[int] = Field(default=None, ge=0)
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
        # IT-29. A DIFFERENT fact from is_slab_rate_estimate above, which is
        # about the RATE: this says the Cost Inflation Index itself fell back
        # to the newest year the table holds. The screen shows the figure
        # either way — an estimate is what a CA wants in May, before June's
        # notification — and now says which it is.
        "indexation_is_estimated": r.indexation_is_estimated,
        "indexation_note": r.indexation_note,
        # IT-19 / IT-28. The cost §48 was actually computed on — the actual
        # cost, or the §55(2)(ac) deemed cost where the substitution ran — and
        # the two lists that are NOT interchangeable: `gaps` are facts nobody
        # recorded and a CA has to go and find, `caveats` are settled reasons
        # a section does not reach this transfer. The screen renders them
        # differently for that reason.
        "cost_of_acquisition_paise": r.cost_of_acquisition_paise,
        "grandfathered_cost_is_applied": r.grandfathered_cost_is_applied,
        "grandfathering_working": list(r.grandfathering_working),
        "gaps": list(r.gaps),
        "caveats": list(r.caveats),
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
        is_listed_security=req.is_listed_security,
        fmv_31_01_2018_paise=req.fmv_31_01_2018_paise,
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
    # IT-19 — optional, because it decides no figure the create path computes.
    # A gain recorded without it is a complete register entry; only the
    # exemption working refuses, and it says what to record.
    transferred_asset_nature: Optional[str] = None

    @field_validator("transferred_asset_nature")
    @classmethod
    def known_nature(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if v not in rex.ASSET_NATURES:
            raise ValueError(
                f"transferred_asset_nature must be one of {sorted(rex.ASSET_NATURES)}")
        return v

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
        is_listed_security=req.is_listed_security,
        fmv_31_01_2018_paise=req.fmv_31_01_2018_paise,
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
        # NULL RATHER THAN A PROVISIONAL INDEX (IT-29). `indexed_cost_paise` is
        # nullable, and nothing recomputes a stored row: a figure written from
        # an unnotified year's fallback index is wrong the moment the
        # notification lands, and it is wrong in the direction that OVERSTATES
        # the gain. An absence the CA can fill in is honest; a stale number
        # that reads as computed is not. The response still carries the
        # estimate and the sentence saying why, so nothing is hidden — only
        # nothing is STORED that will silently go stale.
        "indexed_cost_paise": (None if result.indexation_is_estimated
                               else result.indexed_cost_paise),
        "gain_type": "LTCG" if result.is_long_term else "STCG",
        "tax_rate_percent": result.tax_rate_percent,
        # IT-19. What was SOLD, in the vocabulary the s.54 family charges on.
        # `asset_type` cannot carry it: 'property' covers both a residential
        # house and a plot, and s.54 reaches one while s.54F reaches the
        # other. None is stored where the caller did not say, and the
        # exemption working then REFUSES rather than guessing.
        "transferred_asset_nature": req.transferred_asset_nature,
        # IT-28 and IT-19 (migration 402). Two facts nothing here can derive,
        # stored as given and NULL where the caller did not say. Unlike
        # `indexed_cost_paise` above these are INPUTS, not derived figures:
        # whether the security was listed and what it was worth on
        # 31-01-2018 are fixed facts that do not go stale, so storing them is
        # what makes the entry complete. The DEEMED cost §55(2)(ac) builds out
        # of the second one is deliberately not stored — it is derived on
        # every read, because the section's own limbs move by Finance Act.
        "is_listed_security": req.is_listed_security,
        "fmv_31_01_2018_paise": req.fmv_31_01_2018_paise,
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


# ── s.54 / 54B / 54EC / 54F reinvestment exemption (IT-19) ──────────────────
# The engine is domain/income_tax/reinvestment_exemption.py and it computes
# nothing here: this file reads the register entry and its claims and hands
# them over. Every refusal comes back as a sentence, because a screen showing
# a CA their register needs to say what to go and record.
# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal


class ReinvestmentIn(BaseModel):
    section: str
    new_asset_description: str = Field(min_length=1)
    acquisition_kind: Optional[str] = None
    acquisition_date: Optional[date] = None
    cost_paise: int = Field(default=0, ge=0)
    cgas_deposit_paise: int = Field(default=0, ge=0)
    cgas_deposit_date: Optional[date] = None
    # The two facts no ledger holds. Optional so a claim can be recorded
    # before the CA has asked the client; the working then names the gap.
    other_residential_houses_owned: Optional[int] = Field(default=None, ge=0)
    agricultural_use_two_years: Optional[bool] = None
    new_asset_transferred_on: Optional[date] = None
    notes: Optional[str] = None

    @field_validator("section")
    @classmethod
    def known_section(cls, v: str) -> str:
        if v not in rex.SECTIONS:
            raise ValueError(f"section must be one of {sorted(rex.SECTIONS)}")
        return v

    @field_validator("acquisition_kind")
    @classmethod
    def known_kind(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if v not in rex.ACQUISITION_KINDS:
            raise ValueError(
                f"acquisition_kind must be one of {sorted(rex.ACQUISITION_KINDS)}")
        return v


def _claim_response(c: rex.ClaimResult) -> dict:
    return {
        "section": c.section,
        "heading": c.heading,
        "allowed": c.allowed,
        "exemption_paise": c.exemption_paise,
        "amount_considered_paise": c.amount_considered_paise,
        "deadline": c.deadline.isoformat() if c.deadline else None,
        "within_time": c.within_time,
        "working": c.working,
        "gaps": c.gaps,
        "caveats": c.caveats,
    }


def _exemption_response(r: rex.ExemptionResult, claim_rows: list[dict]) -> dict:
    by_index = list(claim_rows)
    claims = []
    for i, c in enumerate(r.claims):
        row = by_index[i] if i < len(by_index) else {}
        claims.append({**_claim_response(c),
                       "id": row.get("id"),
                       "new_asset_description": row.get("new_asset_description")})
    return {
        "gain_paise": r.gain_paise,
        "total_exemption_paise": r.total_exemption_paise,
        "taxable_gain_paise": r.taxable_gain_paise,
        "claims": claims,
        "gaps": r.gaps,
        "caveats": r.caveats,
    }


@router.get("/capital-gains/sections")
def get_reinvestment_sections(
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    """The four sections and what each one reaches — served so the screen has
    no second copy of the vocabulary to drift from."""
    return api_response(True, {
        "sections": [{
            "section": r.section,
            "heading": r.heading,
            "reaches": list(r.reaches),
            "requires_long_term": r.requires_long_term,
            "new_asset": r.new_asset,
            "proportionate": r.proportionate,
            "cgas_available": r.cgas_available,
            "invested_cap_paise": r.invested_cap_paise,
            "lock_in_years": r.lock_in_years,
        } for r in rex.RULES.values()],
        "asset_natures": list(rex.ASSET_NATURES),
        "acquisition_kinds": list(rex.ACQUISITION_KINDS),
    })


def _entry_and_claims(current_user: dict, record_id: str, db):
    """The register entry, scope-checked, and its claims — or a 404."""
    if db is None:
        return None, []
    row = (db.table("capital_gains").select("*").eq("id", record_id)
           .eq("firm_id", current_user["firm_id"]).limit(1).execute())
    entry = (row.data or [None])[0]
    if not entry or not can_access_client(current_user, entry.get("client_id")):
        raise HTTPException(status_code=404, detail="Capital gains record not found")
    # THE PROJECTION IS SPELLED OUT rather than passed as `cgx.CLAIM_COLUMNS`,
    # and that is not a style choice: `tests/test_backend_columns_exist_pg.py`
    # reads every `.select()` against the real schema and can only do so on a
    # literal — a constant is invisible to it and counts against the
    # unreadable-reference budget. The service keeps CLAIM_COLUMNS as the
    # documented projection and a test holds the two identical.
    claims = (db.table("capital_gain_reinvestments").select(
                  "id, capital_gain_id, section, new_asset_description, "
                  "acquisition_kind, acquisition_date, cost_paise, "
                  "cgas_deposit_paise, cgas_deposit_date, "
                  "other_residential_houses_owned, agricultural_use_two_years, "
                  "new_asset_transferred_on, notes, created_at")
              .eq("capital_gain_id", record_id)
              .eq("firm_id", current_user["firm_id"])
              .order("created_at").execute())
    return entry, (claims.data or [])


@router.get("/capital-gains/{record_id}/exemption")
def get_capital_gain_exemption(
    record_id: str,
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    """What s.54 / 54B / 54EC / 54F exempt on this transfer, claim by claim."""
    db = _db()
    if db is None:
        return api_response(True, {"gain_paise": 0, "total_exemption_paise": 0,
                                   "taxable_gain_paise": 0, "claims": [],
                                   "gaps": [], "caveats": []})
    entry, claim_rows = _entry_and_claims(current_user, record_id, db)
    result = cgx.exemption_for_entry(entry, claim_rows,
                                     client_id=entry["client_id"],
                                     firm_id=current_user["firm_id"])
    return api_response(True, _exemption_response(result, claim_rows))


@router.post("/capital-gains/{record_id}/reinvestments")
def add_capital_gain_reinvestment(
    record_id: str,
    req: ReinvestmentIn,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Record a claim against one register entry.

    THE CLAIM IS RECORDED WHETHER OR NOT IT QUALIFIES, and the working says
    which. A claim refused for a missing fact is the ordinary state of one
    entered before the CA has asked the client how many other houses they own
    — refusing the WRITE would leave them nowhere to put what they do know.
    """
    db = _db()
    if db is None:
        return api_response(True, {"id": "mock-id", **req.model_dump(mode="json")})
    entry, _ = _entry_and_claims(current_user, record_id, db)
    # Written inline for the same reason the projection above is: the column
    # guard reads a literal dict and a `payload` variable is invisible to it.
    row = db.table("capital_gain_reinvestments").insert({
        "firm_id": current_user["firm_id"],
        "client_id": entry["client_id"],
        "capital_gain_id": record_id,
        "section": req.section,
        "new_asset_description": req.new_asset_description,
        "acquisition_kind": req.acquisition_kind,
        "acquisition_date": req.acquisition_date.isoformat() if req.acquisition_date else None,
        "cost_paise": req.cost_paise,
        "cgas_deposit_paise": req.cgas_deposit_paise,
        "cgas_deposit_date": req.cgas_deposit_date.isoformat() if req.cgas_deposit_date else None,
        "other_residential_houses_owned": req.other_residential_houses_owned,
        "agricultural_use_two_years": req.agricultural_use_two_years,
        "new_asset_transferred_on": (req.new_asset_transferred_on.isoformat()
                                     if req.new_asset_transferred_on else None),
        "notes": req.notes,
        "created_by": current_user.get("id"),
    }).execute()
    return api_response(True, (row.data or [{}])[0])


@router.delete("/capital-gains/{record_id}/reinvestments/{claim_id}")
def delete_capital_gain_reinvestment(
    record_id: str,
    claim_id: str,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    db = _db()
    if db is None:
        return api_response(True, {"id": claim_id})
    # Scope-checked through the parent entry, which is what carries the
    # client_id — the same shape as _assert_capital_gains_scope.
    _entry_and_claims(current_user, record_id, db)
    row = (db.table("capital_gain_reinvestments").delete()
           .eq("id", claim_id).eq("capital_gain_id", record_id)
           .eq("firm_id", current_user["firm_id"]).execute())
    if not row.data:
        raise HTTPException(status_code=404, detail="Reinvestment claim not found")
    return api_response(True, {"id": claim_id})


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
        # §140A(1)'s own figure — the tax payable on the basis of the return
        # after the credits the section names. Served from HERE because this
        # endpoint already has all four inputs and the screen must not
        # subtract them itself: the §140A panel passes this straight through
        # as the tax due. Computed by `self_assessment.tax_payable_on_return`
        # rather than read off §234A's base, which happens to be the same
        # figure under a different provision.
        "section_140a_tax_due_paise": sa_domain.tax_payable_on_return(
            tax_on_total_income_paise=req.tax_on_total_income_paise,
            tds_tcs_paise=req.tds_tcs_paise,
            advance_tax_paid_paise=req.advance_tax_paid_paise,
            relief_paise=req.relief_paise),
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
    #: REQUIRED. §44AD's Explanation (a) names who it reaches, and this product
    #: records the entity type on every client — so the engine decides it
    #: rather than appending "confirm before opting in" to a result that reads
    #: as eligible. Optional here would put the hole back: a Private Limited
    #: company would be told a scheme it cannot use is available to it.
    assessee_kind: AssesseeKind
    #: §44AD reaches a RESIDENT assessee only. Defaults true, matching
    #: ComputeITRRequest, and the screen sends what the CA answered there.
    is_resident: bool = True
    turnover_paise: int = Field(ge=0)
    #: The split matters: the 3 crore ceiling and the 6% rate both turn on how
    #: much of the turnover came through a bank. Sending only the total gets
    #: the 8% rate on everything and the lower limit.
    digital_turnover_paise: int = Field(default=0, ge=0)
    cash_receipts_paise: int = Field(default=0, ge=0)
    declared_income_paise: Optional[int] = Field(default=None, ge=0)


class Compute44ADARequest(BaseModel):
    fy: OptionalFYLabel = None
    #: REQUIRED, for the same reason as §44AD's — see Compute44ADRequest.
    assessee_kind: AssesseeKind
    is_resident: bool = True
    gross_receipts_paise: int = Field(ge=0)
    cash_receipts_paise: int = Field(default=0, ge=0)
    declared_income_paise: Optional[int] = Field(default=None, ge=0)


class GoodsCarriageInput(BaseModel):
    gross_vehicle_weight_kg: int = Field(gt=0)
    #: Every month or PART of a month owned — a vehicle bought on 28 March is
    #: owned for a part of March and that month is charged in full.
    months_owned: int = Field(ge=0, le=12)


class Compute44AERequest(BaseModel):
    #: NO assessee_kind here, deliberately. §44AE reaches "an assessee who owns
    #: not more than ten goods carriages" — any person, a company included — so
    #: a kind test would refuse a transporter the section charges. See
    #: domain/income_tax/presumptive.ELIGIBLE_PRESUMPTIVE_ASSESSEES.
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
        assessee_kind=req.assessee_kind,
        is_resident=req.is_resident,
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
        assessee_kind=req.assessee_kind,
        is_resident=req.is_resident,
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

# The list is `itr_json`'s, derived from its own `ITRForm` Literal — the
# same seven the field mappings and the committed Department schemas are
# keyed on. It was restated here, which is one more copy to keep in step
# (IT-23: the filing SCREEN's copy had already fallen behind at four).
from domain.income_tax.itr_json import ITR_FORMS as _ITR_FORMS


class ITRFieldPlacementsRequest(BaseModel):
    form: str
    assessment_year: AYLabel = "2026-27"
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




# ── IT Act §140A — the Challan 280 a return is accompanied by (IT-13) ────────
#
# §140A(1) makes the assessee liable to pay the tax, interest and fee due on a
# return BEFORE furnishing it, and requires the return to be "accompanied by
# proof of payment". That proof is a Challan 280 and nothing here recorded one,
# so Schedule IT was keyed off a bank receipt and the ITR keying sheet printed
# §140A as a structural nil.
#
# `domain/income_tax/self_assessment.py` is the authority for §140A(1)'s
# appropriation order and `services/self_assessment_service.py` reads the rows.
# These three endpoints decide nothing either of them decides.
#
# # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal

import re as _re

_BSR_CODE_RE = _re.compile(r"^[0-9]{7}$")


class SelfAssessmentChallanIn(BaseModel):
    """One Challan 280, as the bank receipt states it.

    EVERY FIGURE IS RECORDED, NONE IS DERIVED. `total_paise` is what left the
    account and is the figure Schedule IT declares; the five-way split is what
    the challan says it was paid towards. The two are not reconciled here — see
    `self_assessment.SPLIT_DOES_NOT_FOOT` — because both came off the same
    document and replacing one with the other would hide a keying error.
    """
    client_id: str
    financial_year: FYLabel
    #: Seven numeric digits, the same shape migration 112 gave
    #: `tds_challans.bsr_code`, enforced here as well as in the CHECK so the
    #: screen gets a sentence rather than a database error.
    bsr_code: str
    deposit_date: date
    challan_serial_no: str = Field(min_length=1, max_length=40)
    tax_paise: int = Field(default=0, ge=0)
    surcharge_paise: int = Field(default=0, ge=0)
    cess_paise: int = Field(default=0, ge=0)
    interest_paise: int = Field(default=0, ge=0)
    fee_paise: int = Field(default=0, ge=0)
    #: What Schedule IT's Amount column takes and what §140A(1) appropriates.
    total_paise: int = Field(ge=0)
    major_head: str = sa_domain.MAJOR_HEAD_OTHER
    minor_head: str = sa_domain.MINOR_HEAD_SELF_ASSESSMENT
    bank_name: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("bsr_code")
    @classmethod
    def seven_digits(cls, v: str) -> str:
        value = (v or "").strip()
        if not _BSR_CODE_RE.match(value):
            raise ValueError(
                "bsr_code is the seven-digit code of the bank branch that "
                "collected the challan, as printed on the counterfoil")
        return value

    @field_validator("challan_serial_no")
    @classmethod
    def serial_present(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            raise ValueError("challan_serial_no is required — it is one of "
                             "Schedule IT's three identifying particulars")
        return value

    @field_validator("major_head")
    @classmethod
    def known_major_head(cls, v: str) -> str:
        if v not in sa_domain.MAJOR_HEADS:
            raise ValueError(
                f"major_head must be one of {list(sa_domain.MAJOR_HEADS)} "
                f"(0020 = company, 0021 = any other assessee)")
        return v

    @field_validator("minor_head")
    @classmethod
    def known_minor_head(cls, v: str) -> str:
        if v not in sa_domain.MINOR_HEADS:
            raise ValueError(
                f"minor_head must be one of {list(sa_domain.MINOR_HEADS)} "
                f"(300 = self-assessment tax, 100 = advance tax, "
                f"400 = tax on regular assessment)")
        return v


@router.get("/self-assessment")
def list_self_assessment_challans(
    client_id: str = Query(...),
    fy: Annotated[FYLabel, Query()] = ...,
    #: The dues, if the caller has them. All three OPTIONAL and their absence
    #: is NAMED rather than defaulted: a CA records a challan before the
    #: computation is finished, and appropriating against a liability nobody
    #: has computed would invent an outstanding figure. The interest is the
    #: Advance Tax screen's §234A/B/C working — it is not re-derived here, see
    #: `self_assessment.INTEREST_IS_NOT_DERIVED_HERE`.
    tax_due_paise: Optional[int] = Query(default=None, ge=0),
    interest_due_paise: Optional[int] = Query(default=None, ge=0),
    fee_due_paise: Optional[int] = Query(default=None, ge=0),
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    """Every §140A challan for one client-year, and how the total lands.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal"""
    assert_client_access(current_user, client_id)
    return api_response(True, self_assessment_service.position(
        _db(), firm_id=current_user["firm_id"], client_id=client_id,
        financial_year=fy, tax_due_paise=tax_due_paise,
        interest_due_paise=interest_due_paise, fee_due_paise=fee_due_paise))


@router.post("/self-assessment")
def create_self_assessment_challan(
    req: SelfAssessmentChallanIn,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Record a Challan 280 against a client-year.

    A DUPLICATE IS REFUSED WITH A SENTENCE. The same BSR code, deposit date and
    serial number is the same payment, and recording it twice would double the
    credit claimed on the return — the one error this table can cause on its
    own. Migration 407's unique index is the backstop; this is the message.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal"""
    assert_client_access(current_user, req.client_id)
    db = _db()
    if not db:
        # Mock mode echoes the request. There is no stored row to read back
        # and nothing downstream reads this, and echoing it rather than
        # building a second copy of the column mapping keeps the INSERT below
        # the only place that names the columns — see the comment there.
        return api_response(True, req.model_dump(mode="json"))
    existing = (db.table("self_assessment_challans")
                .select("id, bsr_code, deposit_date, challan_serial_no")
                .eq("firm_id", current_user["firm_id"])
                .eq("bsr_code", req.bsr_code)
                .eq("deposit_date", req.deposit_date.isoformat())
                .eq("challan_serial_no", req.challan_serial_no)
                .limit(1).execute())
    if existing.data:
        return api_response(False, None, (
            f"Challan {req.challan_serial_no} deposited on "
            f"{req.deposit_date.isoformat()} at BSR {req.bsr_code} is already "
            f"recorded. The same three particulars are the same payment, and "
            f"entering it twice would claim the credit twice on the return."))
    # THE PAYLOAD IS A LITERAL AT THE CALL SITE, not a dict built above and
    # passed by name. `test_backend_columns_exist_pg` reads inserts as
    # LITERALS and counts a payload reached through a name as unreadable —
    # and PostgREST rejects the WHOLE write with PGRST204 for one wrong key,
    # so an unreadable payload is exactly where a typo has nothing else to
    # catch it. The same decision the §32(1)(iia) asset write records.
    res = db.table("self_assessment_challans").insert({
        "firm_id": current_user["firm_id"],
        "client_id": req.client_id,
        "financial_year": req.financial_year,
        "bsr_code": req.bsr_code,
        "deposit_date": req.deposit_date.isoformat(),
        "challan_serial_no": req.challan_serial_no,
        "tax_paise": req.tax_paise,
        "surcharge_paise": req.surcharge_paise,
        "cess_paise": req.cess_paise,
        "interest_paise": req.interest_paise,
        "fee_paise": req.fee_paise,
        "total_paise": req.total_paise,
        "major_head": req.major_head,
        "minor_head": req.minor_head,
        "bank_name": req.bank_name,
        "notes": req.notes,
        "created_by": current_user.get("id"),
    }).execute()
    return api_response(True, (res.data or [{}])[0])


@router.delete("/self-assessment/{challan_id}")
def delete_self_assessment_challan(
    challan_id: str,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Remove a challan recorded in error.

    Nothing is posted by recording one, so nothing is unwound by removing one:
    this table holds the record of a payment made at a bank, not a journal. A
    challan the client actually paid should be corrected rather than deleted,
    which is why the screen asks.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal"""
    db = _db()
    if not db:
        return api_response(True, {"id": challan_id})
    # The client scope is checked off the ROW rather than off a caller-supplied
    # client_id — a challan id alone must not authorise a read of somebody
    # else's client, and the firm filter is the primary isolation control.
    found = (db.table("self_assessment_challans").select("id, client_id")
             .eq("id", challan_id).eq("firm_id", current_user["firm_id"])
             .limit(1).execute())
    if not found.data:
        raise HTTPException(status_code=404, detail="Challan not found")
    assert_client_access(current_user, str(found.data[0].get("client_id")))
    (db.table("self_assessment_challans").delete().eq("id", challan_id)
     .eq("firm_id", current_user["firm_id"]).execute())
    return api_response(True, {"id": challan_id})
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


@router.get("/msme-43bh")
def msme_section_43bh(
    client_id: str,
    fy: Annotated[FYLabel, Query(description="YYYY-YY, e.g. 2025-26")],
    bank_rate_bps: Annotated[Optional[int], Query(
        ge=0, le=5000,
        description="RBI Bank Rate over the delay, in basis points (675 = 6.75%). "
                    "MSMED §16 charges THREE TIMES this. Omit it and the §16 "
                    "working still comes back, with the charge refused and named.",
    )] = None,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """What §43B(h) adds back this year, and what it releases — DERIVED (PUR-15).

    The Finance Act 2023 inserted clause (h) with effect from AY 2024-25: a sum
    payable to a MICRO or SMALL enterprise beyond the MSMED §15 time limit is
    deductible only in the year it is actually paid. **The first proviso to
    §43B does not reach clause (h)**, so paying before the §139(1) return date
    does not save it — the commonest mistake with this clause, and it is on
    every answer.

    THE LIMIT IS FIFTEEN DAYS unless a written agreement says otherwise
    (MSMED §2(b)), and at most forty-five even then (the proviso to §15).
    Forty-five is the number everybody quotes and it is the exception.

    Read from `purchase_bills`, their payment allocations and
    `vendors.msme_status` — not from a table the CA re-keys. Correct a bill and
    this figure changes with it. A vendor whose MSMED classification is not
    recorded is NAMED, never assumed either way: whether a supplier is micro or
    small is a fact about their Udyam registration that no ledger holds.

    Every live bill is read, not only the year's own — an earlier year's bill
    paid late during this year comes back as a deduction now.

    AND `msmed_interest` IS THE OTHER NUMBER. §43B(h) defers a DEDUCTION; MSMED
    §16 makes the buyer liable to the SUPPLIER for compound interest with
    monthly rests at three times the RBI Bank Rate, which §23 then disallows
    outright — so paying it never releases it, and the two add-backs are
    independent. A working that reports only the deferral reports the smaller
    figure.

    **THE BANK RATE IS NOT HELD HERE AND IS NOT GUESSED.** It moves by RBI
    notification partway through a year and a delay spanning a change is
    governed by more than one, so `bank_rate_bps` is the CA's own figure — the
    shape `public.dtaa_treaty_rates` uses for a treaty rate. Omit it and the
    working still names which bills are accruing, from when and over how many
    monthly rests, with the charge itself refused in `gaps`.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal. This
    # computes a working for the tax computation; it writes nothing.
    """
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, {
            "financial_year": fy, "applicable": True, "disallowed_paise": 0,
            "allowed_on_payment_paise": 0, "bills": [], "gaps": [],
            "caveats": [], "source": "mock", "ca_review_required": True,
            # The §16 shape is present in mock mode too, so a screen reading it
            # does not have to branch on which backend answered.
            "msmed_interest": _msmed.compute(
                [], financial_year=fy, bank_rate_bps=bank_rate_bps).to_dict()})
    from services.msme_43bh_service import MSME43BHError, for_financial_year
    try:
        return api_response(True, for_financial_year(
            db, current_user["firm_id"], client_id, fy,
            bank_rate_bps=bank_rate_bps))
    except MSME43BHError as e:
        raise HTTPException(status_code=422, detail=str(e))


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
                                   # The §32(1)(iia) working is present in mock
                                   # mode too, so a screen reading it does not
                                   # have to branch on which backend answered.
                                   "additional_depreciation": {
                                       "reaches_the_assessee": False,
                                       "gaps": [], "caveats": [],
                                       "verified": False},
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


class Section32BusinessIn(BaseModel):
    """Whether §32(1)(iia) reaches this assessee at all (IT-09).

    A BARE BOOLEAN AND NOT A TRI-STATE ON THE WIRE. The column is nullable and
    NULL means nobody has said, but that state is what the client ARRIVES in —
    there is nothing to send to reach it, and offering a "don't know" on a
    screen would invite somebody to answer the question with a shrug and make
    the gap look settled.
    """
    client_id: str
    #: §32(1)(iia)'s own opening words: engaged in the business of manufacture
    #: or production of any article or thing, or in the generation,
    #: transmission or distribution of power.
    section_32_1_iia_business: bool


@router.put("/section-32/business")
def set_section_32_1_iia_business(
    req: Section32BusinessIn,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Record whether the client is within §32(1)(iia) (IT-09).

    THE WHO HALF. Until migration 406 this fact did not exist anywhere and
    `section_32_service` passed a hardcoded `False` for every addition, so the
    screen's "Additional u/s 32(1)(iia)" row was a structural ₹0 for every
    client — a nil meaning "we cannot see it" rendered as a nil meaning "there
    was none".

    It is recorded on the CLIENT rather than on each asset because it is true
    of every asset they own or of none, and one column asserting both halves
    would give a trading company's new forklift the same answer as a factory's.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
    """
    assert_client_access(current_user, req.client_id)
    db = _db()
    answer = {"client_id": req.client_id,
              "section_32_1_iia_business": req.section_32_1_iia_business}
    if not db:
        return api_response(True, answer)
    # The payload is written out HERE rather than built above and passed by
    # name. It has one literal key and nothing dynamic about it, and
    # `test_backend_columns_exist_pg` can only check a column it can read: a
    # `.update(patch)` is invisible to it, which on a single-column write is
    # the one place a typo would have nothing else to catch it. That file's
    # own budget comments record the same trade made five times before.
    out = (db.table("clients")
           .update({"section_32_1_iia_business": req.section_32_1_iia_business})
           .eq("id", req.client_id).eq("firm_id", current_user["firm_id"])
           .execute())
    if not (out.data or []):
        raise HTTPException(status_code=404, detail="Client not found")
    return api_response(True, answer)


# NO SECOND DOOR FOR THE ASSET HALF, AND THAT IS A DECISION (IT-09).
#
# A dedicated `PUT /section-32/asset-eligibility` was written and deleted. The
# ordinary asset PATCH already carries `additional_depreciation_eligible` —
# Tier A on `routers/fixed_assets`, so it runs the same rbac(), the same tier
# rules and the same period checks as every other classification on the row —
# and a second endpoint writing one column of `fixed_assets` is a second write
# path for one fact. That is the `public.suppliers` shape: one screen writing a
# column no other path reads, found months later when a CA's answer had been
# going nowhere.
#
# It costs a CA a navigation from the §32 screen to the asset register, and the
# panel there says so. Saving that click by building a rival door is the trade
# this repository has recorded as wrong more than once.
class BookToTaxBridgeRequest(BaseModel):
    """The bridge's inputs, and THREE OF THEM ARE NOW OPTIONAL.

    §32 was already fetched rather than supplied. Book profit, the depreciation
    charged in the accounts and the §43B(h) disallowance are figures these books
    ALSO hold, so leaving one out derives it and says where it came from —
    `services/book_to_tax_service.py` records why a re-keyed figure drifts from
    the ledger the moment anything is corrected.

    A value that IS supplied wins, and is marked `derived: false` on its own
    line. That is not a fallback: a CA may be bridging a client whose accounts
    were prepared elsewhere, and refusing their figure would make the screen
    useless for exactly the clients whose bridge is hardest.

    `brought_forward_loss_set_off_paise` stays REQUIRED-OR-ZERO and is never
    derived. §72, §73(4), §74 and §71B each let a loss reach only certain HEADS
    of income and the bridge holds one figure for the whole computation, so a
    set-off derived from it would assert a head-wise answer nothing here can
    see. The refusal is named in the response.
    """
    client_id: str
    fy: FYLabel
    book_profit_paise: Optional[int] = None
    disallowances_paise: Optional[int] = None
    depreciation_per_books_paise: Optional[int] = None
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
    from services import book_to_tax_service as _b2t

    section_32 = None
    db = _db()
    if db:
        from services.section_32_service import section_32_service
        section_32 = section_32_service.assemble(
            db, current_user["firm_id"], req.client_id, req.fy)

    # THE THREE DERIVABLE INPUTS. A caller's value wins; anything omitted is
    # read out of these books and carries a sentence saying so. A figure that
    # could not be read comes back None and is passed as 0 WITH ITS REASON —
    # zero depreciation in the accounts and depreciation that could not be read
    # are different facts, and the bridge's `reasons` is where the second one
    # belongs.
    if db:
        resolved = _b2t.resolve_inputs(
            db, current_user["firm_id"], req.client_id, req.fy, current_user,
            book_profit_paise=req.book_profit_paise,
            disallowances_paise=req.disallowances_paise,
            depreciation_per_books_paise=req.depreciation_per_books_paise)
    else:
        resolved = {
            k: _b2t.DerivedInput(v, _b2t.CALLER_SUPPLIED, False)
            for k, v in (("book_profit", req.book_profit_paise or 0),
                         ("disallowances", req.disallowances_paise or 0),
                         ("depreciation_per_books",
                          req.depreciation_per_books_paise or 0))
        }
    unreadable = [d.source for d in resolved.values() if d.value is None]

    bridge = build_bridge(
        book_profit_paise=resolved["book_profit"].value or 0,
        disallowances_paise=resolved["disallowances"].value or 0,
        depreciation_per_books_paise=(
            resolved["depreciation_per_books"].value or 0),
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
        # A figure that could not be READ makes the bridge incomplete, for the
        # same reason a withheld §32 figure does: it foots on a zero that is
        # not a measurement.
        "is_complete": bridge.is_complete and not unreadable,
        "missing": list(bridge.missing),
        "reasons": list(bridge.reasons) + unreadable
                   + [_b2t.BF_LOSS_IS_NOT_DERIVED],
        "foots": bridge.foots(),
        # Where each input came from, so a reader can tell a figure this
        # product derived from one somebody typed.
        "inputs": {k: v.to_dict() for k, v in resolved.items()},
        # The §32 answer beside the bridge, so a CA who sees "incomplete" can
        # see WHY without a second request.
        "section_32": section_32,
    })


# ── Form 3CD (IT-11) — the statement of particulars annexed to a tax audit ──
# report. See domain/income_tax/form_3cd.py for the clause vocabulary (which
# clauses this product derives, and why the rest are named rather than
# guessed) and services/form_3cd_service.py for where each derived figure
# comes from. Every derived clause reuses an existing module — nothing here
# recomputes §32, §43B(h), MSMED §16 interest, brought-forward losses, TDS
# compliance or the GST-registration split.

@router.get("/form-3cd")
def form_3cd_register(
    client_id: str,
    fy: Annotated[FYLabel, Query(description="YYYY-YY, e.g. 2025-26")],
    nature: Optional[str] = Query(
        None, description="business | profession — needed only to resolve "
                          "clause 8 (§44AB), and never inferred from turnover"),
    bank_rate_bps: Optional[int] = Query(
        None, description="RBI Bank Rate over the delay, for clause 22's "
                          "MSMED §16 interest — not held here, refused if "
                          "omitted"),
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    """The 44-clause register: every clause this product can honestly answer,
    computed from the books, and every other clause named with the reason —
    or the CA's own recorded answer, where one has been saved.

    Reads only. `PUT /form-3cd` is where a CA records a manual clause.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
    """
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        from domain.income_tax import form_3cd as f3cd
        return api_response(True, f3cd.build_register(
            client_id=client_id, financial_year=fy, derived={}).to_dict())
    from services.form_3cd_service import build
    return api_response(True, build(
        db, current_user["firm_id"], client_id, fy,
        nature=nature, bank_rate_bps=bank_rate_bps))


class Form3cdManualClauses(BaseModel):
    clauses: dict = Field(
        default_factory=dict,
        description="clause code -> the CA's own value/note, for a clause "
                    "this product does not derive")
    status: str = Field("draft", description="draft | review | finalised")

    @field_validator("status")
    @classmethod
    def _known_status(cls, v: str) -> str:
        allowed = {"draft", "review", "finalised"}
        if v not in allowed:
            raise ValueError(f"status must be one of {sorted(allowed)}")
        return v


@router.put("/form-3cd")
def save_form_3cd_manual_clauses(
    client_id: str,
    fy: Annotated[FYLabel, Query(description="YYYY-YY, e.g. 2025-26")],
    req: Form3cdManualClauses,
    current_user: dict = Depends(rbac("income_tax", "write")),
):
    """Record the CA's own answers for clauses this product does not derive.

    Stored on `tax_audit_checklists` (migration 014) — a table that has
    existed since the first schema sweep with no reader or writer anywhere in
    this codebase until now. A clause code that is ALSO one this product
    derives is stored but never shown in its place: `GET /form-3cd` only
    consults a manual entry for a code absent from what it could derive, so a
    note saved against clause 18 can never shadow a live §32 figure.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
    """
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, {"client_id": client_id, "financial_year": fy,
                                   "clauses_json": req.clauses,
                                   "status": req.status})
    from services.form_3cd_service import save_manual_clauses
    return api_response(True, save_manual_clauses(
        db, current_user["firm_id"], client_id, fy, req.clauses, req.status))
