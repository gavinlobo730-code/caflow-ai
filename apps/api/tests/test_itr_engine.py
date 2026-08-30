"""
Unit tests for ITR computation engine.
IT Act 1961 — all amounts in paise.

Every request pins fy="2025-26" (the last training-verified financial year,
see domain.income_tax.statutory_rates) so these tests stay deterministic
regardless of which FY "today" resolves to.
"""
import pytest
from domain.income_tax.itr_engine import (
    ITREngine, ITRComputeRequest, Deductions80C, Deductions80D, Donation80G, HRADetails,
    LIMIT_80C_PAISE, LIMIT_80CCD1B_PAISE, LIMIT_80TTA_PAISE, LIMIT_80TTB_PAISE,
    LIMIT_24B_PAISE, LIMIT_80CCD2_GOVT_PERCENT, LIMIT_80CCD2_OTHER_PERCENT,
)
from domain.income_tax.statutory_rates import RATES_BY_FY

engine = ITREngine()
RATES = RATES_BY_FY["2025-26"]

L = 100_000 * 100  # 1 lakh in paise


def req(**kwargs) -> ITRComputeRequest:
    kwargs.setdefault("fy", "2025-26")
    return ITRComputeRequest(**kwargs)


# ── Standard deduction ────────────────────────────────────────────────────────

class TestStandardDeduction:
    def test_applied_to_salary_new_regime(self):
        r = engine.compute(req(gross_salary_paise=80 * L, use_new_regime=True))
        assert r.standard_deduction_paise == RATES.new_regime_standard_deduction_paise

    def test_applied_to_salary_old_regime(self):
        """F17 fix: the old regime's standard deduction is ₹50,000 (Section
        16(ia), Finance Act 2019) -- previously the new regime's ₹75,000 was
        applied to BOTH regimes unconditionally."""
        r = engine.compute(req(gross_salary_paise=80 * L, use_new_regime=False))
        assert r.standard_deduction_paise == RATES.old_regime_standard_deduction_paise
        assert r.standard_deduction_paise != RATES.new_regime_standard_deduction_paise

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

    def test_new_regime_marginal_relief_famous_budget_2025_example(self):
        """Taxable income ₹12,10,000 (₹10,000 over the ₹12L ceiling): slab tax
        would be ₹61,500, but marginal relief caps it at the ₹10,000 excess."""
        r = engine.compute(req(gross_salary_paise=12_85_000 * 100, use_new_regime=True))
        assert r.taxable_income_paise == 12_10_000 * 100
        assert r.tax_before_cess_paise == 10_000 * 100

    def test_old_regime_income_5l_zero_tax(self):
        # ₹5L income, old regime → rebate u/s 87A
        r = engine.compute(req(gross_salary_paise=5 * L, use_new_regime=False))
        assert r.total_tax_paise == 0

    def test_old_regime_87a_hard_cliff_just_above_5l(self):
        """The old regime's Section 87A has NO marginal relief — the FA
        2023/2025 proviso is conditioned on Section 115BAC(1A) (new regime
        only). Gross ₹5,60,000 - ₹50,000 std ded = taxable ₹5,10,000: the
        entire ₹12,500 rebate is forfeit, full slab tax ₹14,500 is payable.
        (Caught by adversarial review — an earlier draft wrongly applied the
        new regime's relief here and asserted ₹10,000.)"""
        r = engine.compute(req(gross_salary_paise=5_60_000 * 100, use_new_regime=False))
        assert r.taxable_income_paise == 5_10_000 * 100
        assert r.rebate_87a_paise == 0
        assert r.tax_before_cess_paise == 14_500 * 100  # 12,500 + 20% of 10,000 — the cliff


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
        # taxable = 2.5L - 50K std ded (old regime) = 2L → slab 0%
        assert r.tax_before_cess_paise == 0

    def test_non_senior_7l(self):
        # ₹7L salary → taxable = 7L - 50K (old regime std ded) = 6.5L
        # 2.5L @ 0%, 2.5L @ 5% = ₹12,500; 1.5L @ 20% = ₹30,000 → total ₹42,500
        r = engine.compute(req(gross_salary_paise=7 * L, use_new_regime=False))
        taxable = 7 * L - RATES.old_regime_standard_deduction_paise
        part1 = (500_000 * 100 - 250_000 * 100) * 5 // 100
        part2 = (taxable - 500_000 * 100) * 20 // 100
        assert r.tax_before_cess_paise == part1 + part2

    def test_senior_citizen_3l_zero(self):
        r = engine.compute(req(gross_salary_paise=3 * L, use_new_regime=False, is_senior_citizen=True))
        assert r.tax_before_cess_paise == 0


# ── Surcharge (F17) ────────────────────────────────────────────────────────────

class TestSurcharge:
    def test_no_surcharge_below_50l(self):
        r = engine.compute(req(gross_salary_paise=40 * L, use_new_regime=True))
        assert r.surcharge_paise == 0

    def test_surcharge_above_50l(self):
        r = engine.compute(req(gross_salary_paise=60 * L, use_new_regime=True))
        assert r.surcharge_paise > 0

    def test_new_regime_surcharge_capped_at_25_percent(self):
        """Finance Act 2023: the new regime never applies the old regime's
        37% (>5 Cr) surcharge slab -- capped at 25%."""
        r_new = engine.compute(req(gross_salary_paise=6_00_00_000 * 100, use_new_regime=True))
        r_old = engine.compute(req(gross_salary_paise=6_00_00_000 * 100, use_new_regime=False))
        assert r_new.surcharge_paise == r_new.tax_before_cess_paise * 25 // 100
        assert r_old.surcharge_paise == r_old.tax_before_cess_paise * 37 // 100

    def test_equity_capital_gains_surcharge_capped_at_15_percent(self):
        """F17 fix: Sections 111A (STCG equity)/112A (LTCG equity) surcharge
        is capped at 15% even when the assessee's overall income surcharge
        bracket is higher (here, >2 Cr -> 25% for ordinary income)."""
        r = engine.compute(req(
            gross_salary_paise=3_00_00_000 * 100,  # well above the 2 Cr / 25% surcharge bracket
            capital_gains_ltcg_paise=1_00_00_000 * 100,
            use_new_regime=True,
        ))
        # 112A: (1,00,00,000 - 1,25,000 exemption) * 12.5%
        ltcg_tax = (1_00_00_000 * 100 - 125_000 * 100) * 1250 // 10000
        # The LTCG slice of total surcharge must reflect the capped 15% rate,
        # not the 25% ordinary-income bracket rate.
        assert r.surcharge_paise > 0
        implied_avg_rate = r.surcharge_paise * 100 // (r.tax_before_cess_paise)
        # A blended rate strictly below 25% proves the LTCG portion was
        # NOT charged at the full ordinary 25% bracket rate.
        assert implied_avg_rate < 25

    def test_surcharge_marginal_relief_just_above_50l(self):
        tax_at_50l = engine.compute(req(gross_salary_paise=50_50_000 * 100, use_new_regime=True))
        tax_just_above = engine.compute(req(gross_salary_paise=50_60_000 * 100, use_new_regime=True))
        # ₹10,000 more gross salary must not cost more than ₹10,000 extra
        # combined tax+surcharge (pre-cess) -- the marginal relief guarantee.
        # (Both incomes are already just above 50L after std deduction.)
        delta_income = 50_60_000 * 100 - 50_50_000 * 100
        delta_tax = tax_just_above.tax_before_cess_paise - tax_at_50l.tax_before_cess_paise
        delta_surcharge = tax_just_above.surcharge_paise - tax_at_50l.surcharge_paise
        assert delta_tax + delta_surcharge <= delta_income

    def test_section_112_ltcg_other_surcharge_also_capped_at_15_percent(self):
        """Finance Act 2022 extended the 15% surcharge cap from equity CG
        (111A/112A) to LTCG on ANY asset (Section 112). An assessee in the
        25% ordinary bracket must pay exactly 15% surcharge on the Section
        112 tax component, and the flat CG tax must NOT ride the slab-tax
        marginal-relief computation (adversarial-review finding: an earlier
        draft folded 112 tax into the slab bucket, contradicting its own
        treatment of the equity components)."""
        salary = 3_00_00_000 * 100      # deep in the >2Cr / 25% bracket
        ltcg_other = 20_00_000 * 100    # Section 112 (non-equity) LTCG
        with_cg = engine.compute(req(
            gross_salary_paise=salary,
            capital_gains_ltcg_other_paise=ltcg_other,
            use_new_regime=True,
        ))
        without_cg = engine.compute(req(gross_salary_paise=salary, use_new_regime=True))
        ltcg_other_tax = ltcg_other * 1250 // 10000  # 12.5% flat
        assert with_cg.tax_before_cess_paise - without_cg.tax_before_cess_paise == ltcg_other_tax
        # The extra surcharge attributable to the 112 component is exactly
        # 15% of its tax — not the 25% the ordinary income pays.
        extra_surcharge = with_cg.surcharge_paise - without_cg.surcharge_paise
        assert extra_surcharge == ltcg_other_tax * 15 // 100

    def test_capital_gains_rates_are_read_from_the_fy_registry_not_hardcoded(self, monkeypatch):
        """R3.1: 111A/112A/112 rates used to be inline constants in this
        engine; they now live in statutory_rates.py's FYTaxRates. Prove the
        engine actually reads them from there (not a value that happens to
        still match) by swapping in a FYTaxRates with different capital-gains
        rates and confirming the computed tax changes accordingly."""
        import domain.income_tax.itr_engine as itr_engine_module
        import dataclasses
        base = RATES_BY_FY["2025-26"]
        custom = dataclasses.replace(
            base,
            stcg_111a_rate_bps=1000,          # 10% instead of 20%
            ltcg_112a_rate_bps=500,           # 5% instead of 12.5%
            ltcg_112a_exemption_paise=0,      # no exemption instead of ₹1.25L
            ltcg_112_other_rate_bps=2500,     # 25% instead of 12.5%
        )
        monkeypatch.setattr(itr_engine_module, "rates_for", lambda fy=None: custom)

        # Salary chosen well above the ₹12L new-regime rebate threshold (with
        # OR without the extra capital-gains income folded into total taxable
        # income) and well below the first ₹50L surcharge threshold, so the
        # only effect of adding capital gains is the flat-rate CG tax itself
        # -- isolating it from rebate/surcharge threshold-crossing effects.
        salary = 20 * L
        r = engine.compute(req(
            gross_salary_paise=salary,
            capital_gains_stcg_paise=1 * L,
            capital_gains_ltcg_paise=2 * L,
            capital_gains_ltcg_other_paise=1 * L,
            use_new_regime=True,
        ))
        expected_stcg = (1 * L) * 1000 // 10000
        expected_ltcg = (2 * L - 0) * 500 // 10000
        expected_ltcg_other = (1 * L) * 2500 // 10000
        without_cg = engine.compute(req(gross_salary_paise=salary, use_new_regime=True))
        cg_tax_component = r.tax_before_cess_paise - without_cg.tax_before_cess_paise
        assert cg_tax_component == expected_stcg + expected_ltcg + expected_ltcg_other


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


# ── Section 80CCD(2) — employer NPS, both regimes ──────────────────────────────

class TestSection80CCD2:
    def test_available_under_new_regime_unlike_80c(self):
        r = req(
            gross_salary_paise=10 * L, use_new_regime=True,
            employer_nps_80ccd2_paise=1 * L,
        )
        result = engine.compute(r)
        assert result.deduction_80ccd2_paise == 1 * L
        assert not any("80CCD(2)" in w for w in result.warnings)

    def test_available_under_old_regime_too(self):
        r = req(
            gross_salary_paise=10 * L, use_new_regime=False,
            employer_nps_80ccd2_paise=1 * L,
        )
        assert engine.compute(r).deduction_80ccd2_paise == 1 * L

    def test_capped_at_10_percent_for_non_government_employee(self):
        r = req(
            gross_salary_paise=10 * L, use_new_regime=True,
            is_government_employee=False,
            employer_nps_80ccd2_paise=5 * L,  # way over any plausible cap
        )
        result = engine.compute(r)
        assert result.deduction_80ccd2_paise == 10 * L * LIMIT_80CCD2_OTHER_PERCENT // 100

    def test_capped_at_14_percent_for_government_employee(self):
        r = req(
            gross_salary_paise=10 * L, use_new_regime=True,
            is_government_employee=True,
            employer_nps_80ccd2_paise=5 * L,
        )
        result = engine.compute(r)
        assert result.deduction_80ccd2_paise == 10 * L * LIMIT_80CCD2_GOVT_PERCENT // 100

    def test_uses_explicit_salary_base_when_supplied(self):
        """basic+DA may differ from gross salary (which can include HRA/other
        allowances) -- when supplied explicitly, the cap must use it, not gross."""
        r = req(
            gross_salary_paise=20 * L,  # gross includes large allowances
            salary_for_80ccd2_paise=8 * L,  # basic+DA is much smaller
            use_new_regime=True, is_government_employee=False,
            employer_nps_80ccd2_paise=5 * L,
        )
        result = engine.compute(r)
        assert result.deduction_80ccd2_paise == 8 * L * LIMIT_80CCD2_OTHER_PERCENT // 100

    def test_included_in_new_regime_total_deductions(self):
        """80CCD(2) must actually reduce taxable income under the new
        regime, not just appear in the breakdown -- this is the whole point
        of it surviving Section 115BAC(2)(i)'s otherwise-blanket disallowance.
        Uses an income well above the new-regime rebate threshold so the
        reduced tax is actually observable (not masked by 87A zeroing both)."""
        with_ccd2 = engine.compute(req(
            gross_salary_paise=30 * L, use_new_regime=True,
            employer_nps_80ccd2_paise=1 * L,
        ))
        without_ccd2 = engine.compute(req(gross_salary_paise=30 * L, use_new_regime=True))
        assert with_ccd2.taxable_income_paise == without_ccd2.taxable_income_paise - 1 * L
        assert with_ccd2.total_tax_paise < without_ccd2.total_tax_paise


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

    def test_the_old_regime_cap_is_the_71_3a_limit_not_the_24b_one(self):
        """Two ₹2,00,000 limits that are not the same rule: §24(b) caps a
        DEDUCTION for interest, §71(3A) caps the SET-OFF of the resulting
        loss. They are separate constants so neither can be "simplified"
        into the other."""
        from domain.income_tax.itr_engine import LIMIT_SET_OFF_71_3A_PAISE
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            house_property_income_paise=-3 * L,
        ))
        # ₹10L salary − ₹75k standard deduction − ₹2L set-off (not ₹3L).
        no_loss = engine.compute(req(gross_salary_paise=10 * L, use_new_regime=False))
        assert (no_loss.taxable_income_paise - r.taxable_income_paise
                == LIMIT_SET_OFF_71_3A_PAISE)

    def test_the_new_regime_allows_no_house_property_set_off_at_all(self):
        """§115BAC(2): under the new regime a house property loss is not set
        off against income under any other head — the ₹2,00,000 figure is the
        OLD regime's §71(3A) cap and does not apply.

        This is the default regime since AY 2024-25, so getting it wrong
        understated the tax on the return most people now file — by up to
        ₹2,00,000 of income, about ₹62,400 at the top marginal rate."""
        with_loss = engine.compute(req(
            gross_salary_paise=20 * L,
            use_new_regime=True,
            house_property_income_paise=-3 * L,
        ))
        without = engine.compute(req(
            gross_salary_paise=20 * L,
            use_new_regime=True,
        ))
        assert with_loss.taxable_income_paise == without.taxable_income_paise, (
            "a house property loss reduced new-regime taxable income; "
            "§115BAC(2) bars the set-off entirely"
        )
        assert with_loss.total_tax_paise == without.total_tax_paise
        assert any("115BAC" in w for w in with_loss.warnings), (
            "the CA must be told why the loss gave no relief"
        )

    def test_house_property_INCOME_is_still_taxed_under_the_new_regime(self):
        """Only the LOSS set-off is barred. Positive income under the head is
        taxable under both regimes — barring that too would understate nothing
        and overstate everything."""
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=True,
            house_property_income_paise=2 * L,
        ))
        base = engine.compute(req(gross_salary_paise=10 * L, use_new_regime=True))
        assert r.taxable_income_paise - base.taxable_income_paise == 2 * L


# ── Disallowances (§40A(3), §43B) add back to business income ────────────────

class TestDisallowances:
    """The computation workspace records disallowances the CA accepts. Before
    the engine had this field they changed the computed tax by exactly ₹0 —
    the workspace looked like it was doing tax work and was inert."""

    def test_a_disallowance_increases_taxable_income_by_its_amount(self):
        # ₹20L, deliberately clear of the §87A rebate ceiling (₹12,00,000 of
        # taxable income under the new regime for FY 2025-26) — inside it both
        # computations correctly return nil tax and the assertion below would
        # prove nothing.
        base = engine.compute(req(business_income_paise=20 * L, use_new_regime=True))
        with_addback = engine.compute(req(
            business_income_paise=20 * L,
            disallowances_paise=2 * L,
            use_new_regime=True,
        ))
        assert (with_addback.taxable_income_paise - base.taxable_income_paise
                == 2 * L), "a disallowance is an add-back; it must raise income"
        assert with_addback.total_tax_paise > base.total_tax_paise, (
            "and more income at a positive marginal rate means more tax"
        )

    def test_the_add_back_is_paise_exact(self):
        r = engine.compute(req(
            business_income_paise=7_77_777_00,
            disallowances_paise=1_23_456_00,
            use_new_regime=True,
        ))
        base = engine.compute(req(business_income_paise=7_77_777_00, use_new_regime=True))
        assert r.taxable_income_paise - base.taxable_income_paise == 1_23_456_00

    def test_a_disallowance_is_disclosed_in_the_warnings(self):
        r = engine.compute(req(
            business_income_paise=10 * L, disallowances_paise=2 * L,
            use_new_regime=True,
        ))
        assert any("added back to business income" in w for w in r.warnings)

    def test_no_disallowance_changes_nothing(self):
        a = engine.compute(req(business_income_paise=10 * L, use_new_regime=True))
        b = engine.compute(req(business_income_paise=10 * L, disallowances_paise=0,
                               use_new_regime=True))
        assert a.taxable_income_paise == b.taxable_income_paise
        assert not any("added back" in w for w in b.warnings)

    def test_a_negative_disallowance_cannot_reduce_income(self):
        """Nothing should send one, but a disallowance is an add-back by
        definition — letting a negative value through would turn the field
        into an uncited deduction."""
        r = engine.compute(req(business_income_paise=10 * L,
                               disallowances_paise=-5 * L, use_new_regime=True))
        base = engine.compute(req(business_income_paise=10 * L, use_new_regime=True))
        assert r.taxable_income_paise == base.taxable_income_paise


# ── FY resolution and verification flag ──────────────────────────────────────

class TestFYResolution:
    def test_explicit_fy_is_echoed(self):
        r = engine.compute(req(gross_salary_paise=10 * L, use_new_regime=True, fy="2025-26"))
        assert r.fy == "2025-26"
        assert r.rates_verified is True

    def test_unverified_fy_flagged(self):
        r = engine.compute(req(gross_salary_paise=10 * L, use_new_regime=True, fy="2026-27"))
        assert r.fy == "2026-27"
        assert r.rates_verified is False

    def test_no_fy_resolves_to_current(self):
        r = engine.compute(ITRComputeRequest(gross_salary_paise=10 * L, use_new_regime=True))
        assert r.fy  # non-empty, whatever "today" resolves to


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

    def test_payable_when_tds_insufficient(self):
        r = engine.compute(req(
            gross_salary_paise=30 * L,
            use_new_regime=True,
            tds_deducted_paise=50_000 * 100,  # small TDS
        ))
        assert r.net_payable_paise > 0
