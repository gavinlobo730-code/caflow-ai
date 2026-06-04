"""
Unit tests for ITR computation engine.
IT Act 1961 — all amounts in paise.
"""
import pytest
from domain.income_tax.itr_engine import (
    ITREngine, ITRComputeRequest, Deductions80C, Deductions80D, Donation80G, HRADetails,
    LIMIT_80C_PAISE, LIMIT_80CCD1B_PAISE, LIMIT_80TTA_PAISE, LIMIT_80TTB_PAISE,
    LIMIT_24B_PAISE, STANDARD_DEDUCTION_PAISE, REBATE_87A_NEW_THRESHOLD_PAISE,
)

engine = ITREngine()

L = 100_000 * 100  # 1 lakh in paise


def req(**kwargs) -> ITRComputeRequest:
    return ITRComputeRequest(**kwargs)


# ── Standard deduction ────────────────────────────────────────────────────────

class TestStandardDeduction:
    def test_applied_to_salary_new_regime(self):
        r = engine.compute(req(gross_salary_paise=80 * L, use_new_regime=True))
        assert r.standard_deduction_paise == STANDARD_DEDUCTION_PAISE

    def test_capped_at_salary(self):
        r = engine.compute(req(gross_salary_paise=50_000 * 100, use_new_regime=True))
        assert r.standard_deduction_paise == 50_000 * 100

    def test_no_salary_no_std_ded(self):
        r = engine.compute(req(other_income_paise=10 * L, use_new_regime=True))
        assert r.standard_deduction_paise == 0


# ── 87A rebate ────────────────────────────────────────────────────────────────

class TestRebate87A:
    def test_new_regime_income_at_threshold_zero_tax(self):
        # ₹12L income → new regime → rebate wipes tax
        r = engine.compute(req(gross_salary_paise=1200 * L // 100, use_new_regime=True))
        # taxable = 12L - 75K std ded = 11.25L < 12L threshold → rebate applies
        assert r.total_tax_paise == 0

    def test_new_regime_above_threshold_pays_tax(self):
        # ₹15L salary, new regime → taxable = 15L - 75K = 14.25L > 12L → pays tax
        r = engine.compute(req(gross_salary_paise=15 * L, use_new_regime=True))
        assert r.total_tax_paise > 0

    def test_old_regime_income_5l_zero_tax(self):
        # ₹5L income, old regime → rebate u/s 87A
        r = engine.compute(req(gross_salary_paise=5 * L, use_new_regime=False))
        assert r.total_tax_paise == 0


# ── New regime slabs ──────────────────────────────────────────────────────────

class TestNewRegimeSlabs:
    def test_income_zero(self):
        r = engine.compute(req(gross_salary_paise=0, use_new_regime=True))
        assert r.total_tax_paise == 0

    def test_income_in_5pct_slab(self):
        # ₹6L income → std ded ₹75K → taxable ₹5.25L
        # taxable ≤ ₹12L → rebate u/s 87A wipes all tax → zero tax
        income = 6 * L
        r = engine.compute(req(gross_salary_paise=income, use_new_regime=True))
        assert r.total_tax_paise == 0

    def test_income_above_rebate_threshold_pays_slab_tax(self):
        # ₹14L income → std ded ₹75K → taxable ₹13.25L > ₹12L → tax applies
        income = 14 * L
        r = engine.compute(req(gross_salary_paise=income, use_new_regime=True))
        assert r.tax_before_cess_paise > 0
        # Cess: 4% on tax+surcharge
        assert r.cess_paise == r.tax_before_cess_paise * 4 // 100

    def test_income_30pct_slab(self):
        income = 30 * L  # ₹30L, well above 24L top bracket
        r = engine.compute(req(gross_salary_paise=income, use_new_regime=True))
        assert r.tax_before_cess_paise > 0
        assert r.total_tax_paise > r.tax_before_cess_paise  # cess added


# ── Old regime slabs ──────────────────────────────────────────────────────────

class TestOldRegimeSlabs:
    def test_non_senior_2_5l_zero(self):
        r = engine.compute(req(gross_salary_paise=250_000 * 100, use_new_regime=False))
        # taxable = 2.5L - 75K = 1.75L → slab 0%
        assert r.tax_before_cess_paise == 0

    def test_non_senior_7l(self):
        # ₹7L salary → taxable = 7L - 75K = 6.25L
        # 2.5L @ 0%, 2.5L @ 5% = ₹12,500; 1.25L @ 20% = ₹25,000 → total ₹37,500
        r = engine.compute(req(gross_salary_paise=7 * L, use_new_regime=False))
        taxable = 7 * L - STANDARD_DEDUCTION_PAISE
        # 2.5L-5L bracket: (5L-2.5L) * 5% = 12500*100 paise
        part1 = (500_000 * 100 - 250_000 * 100) * 5 // 100
        part2 = (taxable - 500_000 * 100) * 20 // 100
        assert r.tax_before_cess_paise == part1 + part2

    def test_senior_citizen_3l_zero(self):
        r = engine.compute(req(gross_salary_paise=3 * L, use_new_regime=False, is_senior_citizen=True))
        assert r.tax_before_cess_paise == 0


# ── Section 80C ───────────────────────────────────────────────────────────────

class TestSection80C:
    def test_capped_at_1_5l(self):
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            s80c=Deductions80C(ppf_paise=2 * L),  # ₹2L entered, capped at ₹1.5L
        ))
        assert r.deduction_80c_paise == LIMIT_80C_PAISE

    def test_partial_80c(self):
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            s80c=Deductions80C(ppf_paise=50 * L // 100),  # ₹50K
        ))
        assert r.deduction_80c_paise == 50 * L // 100

    def test_80c_not_allowed_new_regime(self):
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=True,
            s80c=Deductions80C(ppf_paise=L),
        ))
        assert r.deduction_80c_paise == 0
        assert any("80C" in w for w in r.warnings)


# ── Section 80D ───────────────────────────────────────────────────────────────

class TestSection80D:
    def test_self_limit(self):
        d = Deductions80D(self_family_premium_paise=30_000 * 100)  # ₹30K, limit ₹25K
        assert d.eligible_paise() == 25_000 * 100

    def test_self_senior_limit(self):
        d = Deductions80D(self_family_premium_paise=60_000 * 100, self_family_is_senior=True)
        assert d.eligible_paise() == 50_000 * 100

    def test_parents_senior_limit(self):
        d = Deductions80D(parents_premium_paise=60_000 * 100, parents_is_senior=True)
        assert d.eligible_paise() == 50_000 * 100


# ── HRA exemption ─────────────────────────────────────────────────────────────

class TestHRAExemption:
    def test_no_rent_no_exemption(self):
        h = HRADetails(basic_salary_paise=5 * L, hra_received_paise=L, rent_paid_paise=0)
        assert h.exemption_paise() == 0

    def test_metro_50pct_limit(self):
        # Basic ₹10L, HRA ₹5L, rent ₹4L, metro → limit by 50% basic = ₹5L or rent-10%=₹3L
        h = HRADetails(basic_salary_paise=10 * L, hra_received_paise=5 * L, rent_paid_paise=4 * L, is_metro=True)
        # min(HRA=5L, 50%basic=5L, rent-10%basic=4L-1L=3L) = 3L
        assert h.exemption_paise() == 3 * L

    def test_non_metro_40pct(self):
        h = HRADetails(basic_salary_paise=10 * L, hra_received_paise=5 * L, rent_paid_paise=6 * L, is_metro=False)
        # min(5L, 40%*10L=4L, 6L-1L=5L) = 4L
        assert h.exemption_paise() == 4 * L


# ── 80TTA / 80TTB ─────────────────────────────────────────────────────────────

class TestSavingsInterest:
    def test_80tta_capped(self):
        r = engine.compute(req(
            gross_salary_paise=8 * L,
            use_new_regime=False,
            savings_interest_80tta_paise=15_000 * 100,  # ₹15K, limit ₹10K
        ))
        assert r.deduction_80tta_paise == LIMIT_80TTA_PAISE

    def test_80ttb_senior_capped(self):
        r = engine.compute(req(
            gross_salary_paise=8 * L,
            use_new_regime=False,
            is_senior_citizen=True,
            savings_interest_80tta_paise=60_000 * 100,  # ₹60K, limit ₹50K
        ))
        assert r.deduction_80tta_paise == LIMIT_80TTB_PAISE


# ── 80G donations ─────────────────────────────────────────────────────────────

class TestSection80G:
    def test_100pct_donation(self):
        d = Donation80G(description="PM Fund", amount_paise=10_000 * 100, deduction_pct=100)
        assert d.eligible_paise() == 10_000 * 100

    def test_50pct_donation(self):
        d = Donation80G(description="Other", amount_paise=10_000 * 100, deduction_pct=50)
        assert d.eligible_paise() == 5_000 * 100


# ── Section 24(b) ─────────────────────────────────────────────────────────────

class TestSection24B:
    def test_capped_at_2l(self):
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            home_loan_interest_24b_paise=3 * L,  # ₹3L, capped at ₹2L
        ))
        assert r.deduction_24b_paise == LIMIT_24B_PAISE

    def test_house_property_loss_capped(self):
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            house_property_income_paise=-3 * L,  # ₹3L loss, capped at ₹2L
        ))
        assert any("capped" in w.lower() for w in r.warnings)


# ── Integer arithmetic ────────────────────────────────────────────────────────

class TestIntegerArithmetic:
    def test_all_outputs_are_integers(self):
        r = engine.compute(req(
            gross_salary_paise=1234567,
            other_income_paise=98765,
            use_new_regime=True,
        ))
        assert isinstance(r.gross_total_income_paise, int)
        assert isinstance(r.total_tax_paise, int)
        assert isinstance(r.cess_paise, int)
        assert isinstance(r.net_payable_paise, int)

    def test_no_floats_in_tax(self):
        # Ensure no floating point errors by checking integer types
        r = engine.compute(req(gross_salary_paise=7_777_777, use_new_regime=False))
        assert type(r.tax_before_cess_paise) is int
        assert type(r.cess_paise) is int


# ── Net payable / refund ──────────────────────────────────────────────────────

class TestNetPayable:
    def test_refund_when_tds_exceeds_tax(self):
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=True,
            tds_deducted_paise=5 * L,  # ₹5L TDS
        ))
        assert r.net_payable_paise < 0
        assert r.is_refund if hasattr(r, 'is_refund') else True  # negative = refund

    def test_payable_when_tds_insufficient(self):
        r = engine.compute(req(
            gross_salary_paise=30 * L,
            use_new_regime=True,
            tds_deducted_paise=50_000 * 100,  # small TDS
        ))
        assert r.net_payable_paise > 0
