"""
Income Tax Return computation engine.
IT Act 1961 — Section 80C, 80CCD, 80D, 80G, 80TTA, 80TTB, 10(13A), 24(b), 87A.

Slab/rebate/surcharge rates come from domain.income_tax.statutory_rates — the
single, FY-versioned source of truth (Tier 2 R2.3). See that module's
docstring for which financial years are verified against a confirmed Finance
Act versus carried forward pending confirmation.

All monetary values in integer paise. Never float.
# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from domain.income_tax.statutory_rates import (
    FYTaxRates, apply_rebate_87a, apply_surcharge_with_marginal_relief,
    cess_paise, rates_for, resolve_surcharge_bracket, slab_tax_paise,
)


# ── Constants (all paise) ─────────────────────────────────────────────────────
# Chapter VI-A deduction limits are stable across recent Finance Acts (unlike
# the slabs/rebate/surcharge in statutory_rates.py) — kept here rather than
# FY-versioned unless a specific limit is found to have changed.

# IT Act Section 80C — aggregate limit
LIMIT_80C_PAISE: int = 150_000 * 100

# IT Act Section 80CCD(1B) — additional NPS
LIMIT_80CCD1B_PAISE: int = 50_000 * 100

# IT Act Section 80D limits
LIMIT_80D_SELF_PAISE: int = 25_000 * 100
LIMIT_80D_SELF_SENIOR_PAISE: int = 50_000 * 100
LIMIT_80D_PARENTS_PAISE: int = 25_000 * 100
LIMIT_80D_PARENTS_SENIOR_PAISE: int = 50_000 * 100

# IT Act Section 80TTA (savings interest for non-senior)
LIMIT_80TTA_PAISE: int = 10_000 * 100

# IT Act Section 80TTB (all interest for senior citizen)
LIMIT_80TTB_PAISE: int = 50_000 * 100

# IT Act Section 24(b) — home loan interest self-occupied
LIMIT_24B_PAISE: int = 200_000 * 100


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Deductions80C:
    """IT Act Section 80C eligible investments."""
    ppf_paise: int = 0
    elss_paise: int = 0
    lic_paise: int = 0
    nsc_paise: int = 0
    home_loan_principal_paise: int = 0
    tuition_fees_paise: int = 0
    fd_5yr_paise: int = 0
    sukanya_samriddhi_paise: int = 0
    ulip_paise: int = 0

    def total_paise(self) -> int:
        return (self.ppf_paise + self.elss_paise + self.lic_paise
                + self.nsc_paise + self.home_loan_principal_paise
                + self.tuition_fees_paise + self.fd_5yr_paise
                + self.sukanya_samriddhi_paise + self.ulip_paise)


@dataclass
class Deductions80D:
    """IT Act Section 80D — health insurance premiums."""
    self_family_premium_paise: int = 0
    self_family_is_senior: bool = False
    parents_premium_paise: int = 0
    parents_is_senior: bool = False

    def eligible_paise(self) -> int:
        self_limit = LIMIT_80D_SELF_SENIOR_PAISE if self.self_family_is_senior else LIMIT_80D_SELF_PAISE
        parents_limit = LIMIT_80D_PARENTS_SENIOR_PAISE if self.parents_is_senior else LIMIT_80D_PARENTS_PAISE
        return min(self.self_family_premium_paise, self_limit) + min(self.parents_premium_paise, parents_limit)


@dataclass
class Donation80G:
    description: str
    amount_paise: int
    deduction_pct: int  # 100 or 50

    def eligible_paise(self) -> int:
        return self.amount_paise * self.deduction_pct // 100


@dataclass
class HRADetails:
    """IT Act Section 10(13A) — House Rent Allowance."""
    basic_salary_paise: int = 0
    hra_received_paise: int = 0
    rent_paid_paise: int = 0
    is_metro: bool = False

    def exemption_paise(self) -> int:
        """Min of: actual HRA, 50%/40% of basic, rent paid minus 10% of basic."""
        if self.rent_paid_paise == 0:
            return 0
        pct_basic = 5000 if self.is_metro else 4000  # basis points
        half_basic = self.basic_salary_paise * pct_basic // 10000
        rent_minus_ten = max(0, self.rent_paid_paise - self.basic_salary_paise * 1000 // 10000)
        return min(self.hra_received_paise, min(half_basic, rent_minus_ten))


@dataclass
class ITRComputeRequest:
    """Full income + deduction inputs for ITR computation."""
    # Income heads (all paise)
    gross_salary_paise: int = 0
    other_income_paise: int = 0        # interest, dividend etc
    house_property_income_paise: int = 0   # negative = loss
    business_income_paise: int = 0
    capital_gains_stcg_paise: int = 0
    capital_gains_ltcg_paise: int = 0      # equity, 12.5% (Section 112A)
    capital_gains_ltcg_other_paise: int = 0  # property, debt MF etc, 12.5%/20%
    exempt_income_paise: int = 0

    # Regime
    use_new_regime: bool = True
    is_senior_citizen: bool = False       # 60-80 years
    is_very_senior_citizen: bool = False  # > 80 years

    # Financial year (e.g. "2025-26"); defaults to the current FY. See
    # domain.income_tax.statutory_rates for which years are verified.
    fy: Optional[str] = None

    # Deductions (only applicable under old regime except standard deduction)
    s80c: Deductions80C = field(default_factory=Deductions80C)
    nps_80ccd1b_paise: int = 0
    s80d: Deductions80D = field(default_factory=Deductions80D)
    donations_80g: list[Donation80G] = field(default_factory=list)
    savings_interest_80tta_paise: int = 0
    hra: HRADetails = field(default_factory=HRADetails)
    home_loan_interest_24b_paise: int = 0
    other_deductions_paise: int = 0

    # TDS already deducted (for net payable computation)
    tds_deducted_paise: int = 0
    advance_tax_paid_paise: int = 0


@dataclass
class ITRComputeResult:
    """Computed ITR result — all amounts in paise."""
    # Income summary
    gross_total_income_paise: int = 0
    total_deductions_paise: int = 0
    taxable_income_paise: int = 0

    # Deduction breakdown
    deduction_80c_paise: int = 0
    deduction_80ccd_paise: int = 0
    deduction_80d_paise: int = 0
    deduction_80g_paise: int = 0
    deduction_80tta_paise: int = 0
    deduction_hra_paise: int = 0
    deduction_24b_paise: int = 0
    standard_deduction_paise: int = 0

    # Tax computation
    tax_before_cess_paise: int = 0
    surcharge_paise: int = 0
    cess_paise: int = 0
    total_tax_paise: int = 0
    rebate_87a_paise: int = 0

    # Payable
    tds_and_advance_paise: int = 0
    net_payable_paise: int = 0  # negative = refund

    # Meta
    regime: str = "new"
    fy: str = ""
    rates_verified: bool = True  # False -> see domain.income_tax.statutory_rates
    warnings: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)


# ── Engine ────────────────────────────────────────────────────────────────────

class ITREngine:
    """
    Compute ITR tax liability from income and deduction inputs.
    IT Act 1961 — all computation in integer paise.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """

    def compute(self, req: ITRComputeRequest) -> ITRComputeResult:
        rates = rates_for(req.fy)
        result = ITRComputeResult()
        result.regime = "new" if req.use_new_regime else "old"
        result.fy = rates.fy
        result.rates_verified = rates.verified

        # 1. Standard deduction on salary (IT Act Section 16(ia)). F17 fix:
        # this used to apply the NEW regime's ₹75,000 to both regimes — the
        # old regime's standard deduction has been ₹50,000 since Finance Act
        # 2019 and was never revised alongside the new-regime increases.
        std_ded_limit = (rates.new_regime_standard_deduction_paise if req.use_new_regime
                         else rates.old_regime_standard_deduction_paise)
        std_ded = min(std_ded_limit, req.gross_salary_paise)
        result.standard_deduction_paise = std_ded

        # 2. Gross Total Income
        # House property: capped at -2,00,000 if self-occupied (Section 71)
        house_property = max(req.house_property_income_paise, -LIMIT_24B_PAISE)
        salary_after_std_ded = max(0, req.gross_salary_paise - std_ded)

        # Capital gains are computed separately (special rates)
        ordinary_income = (
            salary_after_std_ded
            + req.other_income_paise
            + house_property
            + req.business_income_paise
        )
        gti = (ordinary_income + req.capital_gains_stcg_paise
               + req.capital_gains_ltcg_paise + req.capital_gains_ltcg_other_paise)
        result.gross_total_income_paise = gti

        # 3. Chapter VI-A deductions (only for old regime for most)
        deductions = 0
        if not req.use_new_regime:
            # 80C
            s80c_total = req.s80c.total_paise()
            s80c_eligible = min(s80c_total, LIMIT_80C_PAISE)
            result.deduction_80c_paise = s80c_eligible
            deductions += s80c_eligible

            # 80CCD(1B) — additional NPS (both regimes allow employer NPS but not employee 80CCD)
            nps_eligible = min(req.nps_80ccd1b_paise, LIMIT_80CCD1B_PAISE)
            result.deduction_80ccd_paise = nps_eligible
            deductions += nps_eligible

            # 80D
            d80d = req.s80d.eligible_paise()
            result.deduction_80d_paise = d80d
            deductions += d80d

            # 80G
            d80g = sum(d.eligible_paise() for d in req.donations_80g)
            result.deduction_80g_paise = d80g
            deductions += d80g

            # 80TTA / 80TTB
            if req.is_senior_citizen or req.is_very_senior_citizen:
                tta_ttb = min(req.savings_interest_80tta_paise, LIMIT_80TTB_PAISE)
            else:
                tta_ttb = min(req.savings_interest_80tta_paise, LIMIT_80TTA_PAISE)
            result.deduction_80tta_paise = tta_ttb
            deductions += tta_ttb

            # HRA exemption (Section 10(13A)) — reduces GTI directly
            hra_exempt = req.hra.exemption_paise()
            result.deduction_hra_paise = hra_exempt
            deductions += hra_exempt

            # Section 24(b) — home loan interest
            d24b = min(req.home_loan_interest_24b_paise, LIMIT_24B_PAISE)
            result.deduction_24b_paise = d24b
            deductions += d24b

            deductions += req.other_deductions_paise

        result.total_deductions_paise = deductions

        # 4. Taxable income
        # Capital gains are excluded from deductions (Section 112A/111A)
        ordinary_taxable = max(0, ordinary_income - deductions)
        taxable_income = (ordinary_taxable + req.capital_gains_stcg_paise
                          + req.capital_gains_ltcg_paise + req.capital_gains_ltcg_other_paise)
        result.taxable_income_paise = taxable_income

        # 5. Tax computation (ordinary/slab income only)
        slabs = self._slabs_for(rates, req.use_new_regime, req.is_senior_citizen, req.is_very_senior_citizen)
        tax = slab_tax_paise(ordinary_taxable, slabs)

        # Special rate capital gains (add on top of slab tax; never eligible
        # for Chapter VI-A deductions or §87A rebate/marginal relief below —
        # see the F17 fix note ahead of the rebate step). Rates are FY-versioned
        # in statutory_rates.py (R3.1) rather than inline here.
        # IT Act Section 111A: STCG on equity
        stcg_tax = req.capital_gains_stcg_paise * rates.stcg_111a_rate_bps // 10000
        # IT Act Section 112A: LTCG on equity, less the exemption
        ltcg_taxable = max(0, req.capital_gains_ltcg_paise - rates.ltcg_112a_exemption_paise)
        ltcg_tax = ltcg_taxable * rates.ltcg_112a_rate_bps // 10000
        # IT Act Section 112: LTCG on any other asset
        ltcg_other_tax = req.capital_gains_ltcg_other_paise * rates.ltcg_112_other_rate_bps // 10000

        # 6. Rebate u/s 87A — reduces slab tax only, never special-rate CG tax.
        # Pre-existing, deliberately conservative position: the CBDT's own ITR
        # utility has historically disallowed an 87A rebate claim against
        # 111A/112A income, a contested point across rulings — not revisited
        # here, since F17 only asked for correct MARGINAL RELIEF, not a
        # change to what the rebate applies against.
        # F17 fix: previously a cliff in BOTH regimes — now marginal relief
        # applies above the threshold, but only under the new regime, where
        # the 115BAC(1A) proviso grants it. The old regime's rebate is a
        # statutory hard cliff (crossing ₹5,00,000 by ₹1 forfeits the whole
        # ₹12,500) — encoded on the RebateRule as data, not a code branch.
        rebate_rule = rates.new_regime_rebate if req.use_new_regime else rates.old_regime_rebate
        rebate = tax - apply_rebate_87a(taxable_income, tax, rebate_rule)
        result.rebate_87a_paise = rebate
        ordinary_tax_after_rebate = max(0, tax - rebate)
        capital_gains_tax = stcg_tax + ltcg_tax + ltcg_other_tax  # Sections 111A + 112A + 112
        result.tax_before_cess_paise = ordinary_tax_after_rebate + capital_gains_tax

        # 7. Surcharge (IT Act Section 2(29C)). F17 fixes:
        #  (a) marginal relief on the slab-tax component, so crossing a
        #      surcharge threshold by a few rupees costs a few rupees, not a
        #      jump to the full new rate on the whole tax amount;
        #  (b) capital-gains surcharge capped at 15% even when the assessee's
        #      overall bracket is higher — Sections 111A/112A since Finance
        #      Act 2019, extended to Section 112 LTCG on ANY asset by Finance
        #      Act 2022. Computed SEPARATELY from ordinary income's
        #      surcharge, both using the SAME resolved bracket (driven by
        #      total taxable income).
        # Marginal relief applies only to the slab-tax component: the
        # discontinuity it exists to smooth is a slab phenomenon, and the
        # "tax at threshold income" baseline is well-defined only for tax
        # that scales with income. Every flat-rate CG component (111A, 112A,
        # 112) instead gets the flat capped bracket rate — one consistent
        # treatment for all special-rate tax.
        new_cap = rates.new_regime_surcharge_cap_percent if req.use_new_regime else None
        slab_tax_at = lambda income: slab_tax_paise(income, slabs)  # noqa: E731
        ordinary_surcharge = apply_surcharge_with_marginal_relief(
            taxable_income, ordinary_tax_after_rebate,
            rates.surcharge_brackets, new_cap, slab_tax_at,
        )
        cg_rate, _ = resolve_surcharge_bracket(
            taxable_income, rates.surcharge_brackets, rates.capital_gains_surcharge_cap_percent)
        cg_surcharge = capital_gains_tax * cg_rate // 100
        surcharge = ordinary_surcharge + cg_surcharge
        result.surcharge_paise = surcharge

        # 8. Health and Education Cess @ 4% on (tax + surcharge)
        result.cess_paise = cess_paise(result.tax_before_cess_paise + surcharge, rates)
        result.total_tax_paise = result.tax_before_cess_paise + surcharge + result.cess_paise

        # 9. Net payable / refund
        result.tds_and_advance_paise = req.tds_deducted_paise + req.advance_tax_paid_paise
        result.net_payable_paise = result.total_tax_paise - result.tds_and_advance_paise

        # 10. Warnings
        if req.use_new_regime and (req.s80c.total_paise() > 0 or req.nps_80ccd1b_paise > 0):
            result.warnings.append("Section 80C/80CCD deductions are not available under the new regime")
        if req.house_property_income_paise < -LIMIT_24B_PAISE:
            result.warnings.append(
                f"House property loss capped at ₹2,00,000 (Section 71). Excess loss ₹"
                f"{(-req.house_property_income_paise - LIMIT_24B_PAISE) // 100:,} carried forward."
            )

        return result

    # ── Slab selection ────────────────────────────────────────────────────────

    @staticmethod
    def _slabs_for(rates: FYTaxRates, use_new_regime: bool, senior: bool, very_senior: bool):
        """Which of the FY's slab tables applies. Old regime distinguishes
        senior (60-79, wider nil band) and very-senior (80+, wider still)
        citizens; the new regime does not (Finance Act 2023 onwards)."""
        if use_new_regime:
            return rates.new_regime_slabs
        if very_senior:
            return rates.old_regime_slabs_very_senior
        if senior:
            return rates.old_regime_slabs_senior
        return rates.old_regime_slabs_general


itr_engine = ITREngine()
