"""
Income Tax Return computation engine.
IT Act 1961 — Section 80C, 80CCD, 80D, 80G, 80TTA, 80TTB, 10(13A), 24(b), 87A.
New regime slabs: Finance Act 2025 (FY 2025-26 onwards).
Old regime slabs: Standard slab for individuals (non-senior, senior, very-senior).

All monetary values in integer paise. Never float.
# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ── Constants (all paise) ─────────────────────────────────────────────────────

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

# Standard deduction — Finance Act 2024 (FY 2024-25 onwards)
STANDARD_DEDUCTION_PAISE: int = 75_000 * 100

# IT Act Section 87A rebate thresholds
# New regime: income ≤ ₹12L → zero tax
REBATE_87A_NEW_THRESHOLD_PAISE: int = 1_200_000 * 100
# Old regime: income ≤ ₹5L → zero tax
REBATE_87A_OLD_THRESHOLD_PAISE: int = 500_000 * 100
REBATE_87A_OLD_MAX_PAISE: int = 12_500 * 100

# Surcharge thresholds (IT Act Section 2(29C))
SURCHARGE_THRESHOLD_50L_PAISE: int = 5_000_000 * 100
SURCHARGE_THRESHOLD_1CR_PAISE: int = 10_000_000 * 100
SURCHARGE_THRESHOLD_2CR_PAISE: int = 20_000_000 * 100
SURCHARGE_THRESHOLD_5CR_PAISE: int = 50_000_000 * 100

# Health and Education Cess — 4%
CESS_RATE_BPS: int = 400


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
        result = ITRComputeResult()
        result.regime = "new" if req.use_new_regime else "old"

        # 1. Standard deduction on salary (both regimes, IT Act Section 16(ia))
        std_ded = min(STANDARD_DEDUCTION_PAISE, req.gross_salary_paise)
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

        # 5. Tax computation
        if req.use_new_regime:
            tax = self._new_regime_tax(ordinary_taxable)
        else:
            tax = self._old_regime_tax(ordinary_taxable, req.is_senior_citizen, req.is_very_senior_citizen)

        # Special rate capital gains (add on top of slab tax)
        # IT Act Section 111A: STCG on equity @ 20% (Budget 2024)
        stcg_tax = req.capital_gains_stcg_paise * 2000 // 10000
        # IT Act Section 112A: LTCG on equity @ 12.5% (Budget 2024), exemption ₹1.25L
        ltcg_exempt = 125_000 * 100
        ltcg_taxable = max(0, req.capital_gains_ltcg_paise - ltcg_exempt)
        ltcg_tax = ltcg_taxable * 1250 // 10000
        # IT Act Section 112: LTCG other @ 12.5% (post-Budget 2024)
        ltcg_other_tax = req.capital_gains_ltcg_other_paise * 1250 // 10000

        tax_before_rebate = tax + stcg_tax + ltcg_tax + ltcg_other_tax

        # 6. Rebate u/s 87A
        rebate = 0
        if req.use_new_regime:
            if taxable_income <= REBATE_87A_NEW_THRESHOLD_PAISE:
                rebate = tax_before_rebate  # full tax wiped (only slab tax, not special rate CG tax)
                rebate = min(rebate, tax)  # rebate only against slab tax
        else:
            if taxable_income <= REBATE_87A_OLD_THRESHOLD_PAISE:
                rebate = min(tax, REBATE_87A_OLD_MAX_PAISE)
        result.rebate_87a_paise = rebate
        result.tax_before_cess_paise = max(0, tax_before_rebate - rebate)

        # 7. Surcharge (IT Act Section 2(29C))
        surcharge = self._compute_surcharge(result.tax_before_cess_paise, taxable_income, req.use_new_regime)
        result.surcharge_paise = surcharge

        # 8. Health and Education Cess @ 4% on (tax + surcharge)
        cess_base = result.tax_before_cess_paise + surcharge
        result.cess_paise = cess_base * CESS_RATE_BPS // 10000
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

    # ── Slab computation ─────────────────────────────────────────────────────

    def _new_regime_tax(self, income_paise: int) -> int:
        """
        New regime slabs — Finance Act 2025 (FY 2025-26 and 2026-27).
        0-4L: 0%, 4-8L: 5%, 8-12L: 10%, 12-16L: 15%, 16-20L: 20%, 20-24L: 25%, 24L+: 30%
        """
        if income_paise <= 0:
            return 0
        L = 10_000  # 1 lakh = 100 rupees * 100 paise = 10000 paise... wait
        # 1 lakh = 1,00,000 rupees = 1,00,000 * 100 paise = 1,00,00,000 paise = 10^7
        # Let L = 100_000 * 100 = 10_000_000 paise per lakh? No...
        # 1 rupee = 100 paise. 1 lakh rupees = 100_000 rupees = 100_000 * 100 paise = 10_000_000 paise
        # But in our system: gross_salary_paise is in paise. So ₹4L = 4,00,000 rupees = 4,00,00,000 paise
        # Actually let's just work in paise directly.
        # ₹4,00,000 = 4_00_000 * 100 paise? No. ₹1 = 100 paise. ₹4L = ₹4,00,000 = 400000 * 100 = 40000000 paise
        # That seems right. Let me use the same basis as the frontend: L = 100 * 100 = 10000 (1 lakh = 100 * L)
        # So ₹4L = 400 * L = 400 * 10000 = 4000000... that doesn't match either.
        # Frontend: const L = 100 * 100; // 1 lakh in paise = 10000 paise → 1L = 100*100 = 10000
        # So L = 10000 means ₹100 = 1L? That's wrong. Let me check: 100 * 100 = 10000 paise = ₹100. So L = ₹100 not ₹1L.
        # Frontend comment says "1 lakh in paise" = 10000. But 1 lakh = 100000 rupees = 10000000 paise. That's wrong!
        # Actually: "1L rupees = 100 * 100 paise" means the frontend is using L as ₹1 = L/100 concept? No...
        # Reading more carefully: "1L = 100*100 = 10000" -- this seems to be saying 1 unit of their system = ₹100.
        # Then "400 * L" = 400 * 10000 = 4000000 paise = ₹40000 (not ₹4L).
        # Wait, const L = 100 * 100 -- "100 cents * 100"? Actually I think the frontend has a bug:
        # The comment says "1 lakh in paise = 10000" which is WRONG. 1 lakh rupees = 1,00,000 rupees = 1,00,00,000 paise.
        # But looking at the slab: "SLAB = [{upto: 400*L, rate: 0}...]" with L=10000, 400*L = 4,000,000 paise = ₹40,000. Not ₹4L!
        # I think there's a bug in the frontend. Let me use CORRECT values.
        # ₹4L = 4,00,000 rupees = 4,00,00,000 paise? No: ₹1 = 100p, ₹4L = 400000 * 100p = 40,000,000p? That seems huge.
        # Wait: we use paise everywhere. ₹1 = 100 paise. ₹1L = ₹1,00,000 = 1,00,000 * 100 = 1,00,00,000 paise.
        # Hmm but all our paise values for individual items are like ₹50,000 = 5,000,000 paise (5 million). That seems right.
        # So ₹12L threshold for 87A = 12,00,000 * 100 = 12,00,00,000 paise = 1,200,000,000 paise = 1.2 billion. That matches REBATE_87A_NEW_THRESHOLD_PAISE above.
        # Let me just use absolute paise values directly.
        # ₹4L = 4_00_000 rupees = 4_00_000 * 100 paise = 40_000_000 paise

        slabs = [
            (400_000 * 100, 0),       # 0-4L: 0%
            (800_000 * 100, 500),     # 4-8L: 5% → 500 bps
            (1_200_000 * 100, 1000),  # 8-12L: 10%
            (1_600_000 * 100, 1500),  # 12-16L: 15%
            (2_000_000 * 100, 2000),  # 16-20L: 20%
            (2_400_000 * 100, 2500),  # 20-24L: 25%
        ]
        tax = 0
        prev = 0
        for upto, rate_bps in slabs:
            if income_paise <= prev:
                break
            slab_income = min(income_paise, upto) - prev
            tax += slab_income * rate_bps // 10000
            prev = upto
        if income_paise > 2_400_000 * 100:
            tax += (income_paise - 2_400_000 * 100) * 3000 // 10000
        return tax

    def _old_regime_tax(self, income_paise: int, senior: bool, very_senior: bool) -> int:
        """
        Old regime slabs.
        Non-senior: 0-2.5L=0%, 2.5-5L=5%, 5-10L=20%, 10L+=30%
        Senior (60-80): 0-3L=0%, 3-5L=5%, 5-10L=20%, 10L+=30%
        Very senior (80+): 0-5L=0%, 5-10L=20%, 10L+=30%
        """
        if income_paise <= 0:
            return 0
        L = 100_000 * 100  # 1 lakh in paise

        if very_senior:
            brackets = [
                (5 * L, 0),
                (10 * L, 2000),
            ]
            top_rate = 3000
        elif senior:
            brackets = [
                (3 * L, 0),
                (5 * L, 500),
                (10 * L, 2000),
            ]
            top_rate = 3000
        else:
            brackets = [
                (250_000 * 100, 0),
                (500_000 * 100, 500),
                (1_000_000 * 100, 2000),
            ]
            top_rate = 3000

        tax = 0
        prev = 0
        for upto, rate_bps in brackets:
            if income_paise <= prev:
                break
            slab_income = min(income_paise, upto) - prev
            tax += slab_income * rate_bps // 10000
            prev = upto

        if income_paise > prev:
            tax += (income_paise - prev) * top_rate // 10000
        return tax

    def _compute_surcharge(self, tax_paise: int, income_paise: int, new_regime: bool) -> int:
        """
        IT Act Section 2(29C): surcharge on individuals.
        New regime max surcharge 25% (capped by Finance Act 2023).
        Old regime max surcharge 37% for >5 Cr.
        """
        if income_paise <= SURCHARGE_THRESHOLD_50L_PAISE:
            return 0

        if new_regime:
            if income_paise <= SURCHARGE_THRESHOLD_1CR_PAISE:
                rate_bps = 1000  # 10%
            elif income_paise <= SURCHARGE_THRESHOLD_2CR_PAISE:
                rate_bps = 1500  # 15%
            else:
                rate_bps = 2500  # 25% (capped for new regime)
        else:
            if income_paise <= SURCHARGE_THRESHOLD_1CR_PAISE:
                rate_bps = 1000
            elif income_paise <= SURCHARGE_THRESHOLD_2CR_PAISE:
                rate_bps = 1500
            elif income_paise <= SURCHARGE_THRESHOLD_5CR_PAISE:
                rate_bps = 2500
            else:
                rate_bps = 3700  # 37%

        return tax_paise * rate_bps // 10000


itr_engine = ITREngine()
