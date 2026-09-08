"""
Two statutory limits domain.income_tax.itr_engine did not apply at all.

1. IT Act Section 71(3) — a loss under the head "Capital gains" cannot be
   set off against income under any other head; Section 74 carries it
   forward instead. A negative capital-gains figure used to flow straight
   into gross total income AND into the special-rate tax line, so entering a
   ₹5,00,000 short-term capital loss beside a ₹20,00,000 salary cut the
   year's tax from ₹1,92,400 to ₹88,400 — relief the section denies twice
   over.

2. IT Act Section 80G(4) — the qualifying limit. Donations in the category
   that carries one qualify only up to 10% of adjusted gross total income.
   Nothing capped anything: a ₹9,00,000 donation at 50% against a
   ₹10,00,000 salary produced a ₹4,50,000 deduction. Section 80G(5D)'s cash
   bar was missing too.

Every request pins fy="2025-26" (the last training-verified financial year,
see domain.income_tax.statutory_rates) so these tests stay deterministic
regardless of which FY "today" resolves to. All amounts in integer paise.
"""
from domain.income_tax.itr_engine import (
    ITREngine, ITRComputeRequest, Deductions80C, Donation80G,
    LIMIT_80G_QUALIFYING_PERCENT, LIMIT_80G_CASH_PAISE,
)

engine = ITREngine()

L = 100_000 * 100  # 1 lakh in paise


def req(**kwargs) -> ITRComputeRequest:
    kwargs.setdefault("fy", "2025-26")
    return ITRComputeRequest(**kwargs)


def _warning_mentioning(result, *needles) -> str:
    for w in result.warnings:
        if all(n in w for n in needles):
            return w
    raise AssertionError(f"no warning mentioning {needles!r} in {result.warnings!r}")


# ── Section 71(3) / Section 74 — a capital loss is not other-head relief ────

class TestCapitalLossIsNotSetOffAgainstOtherHeads:
    def test_a_short_term_capital_loss_does_not_reduce_the_tax_on_salary(self):
        """The reported defect, in the numbers it was reported in."""
        salary_only = engine.compute(req(gross_salary_paise=20 * L))
        with_loss = engine.compute(req(
            gross_salary_paise=20 * L,
            capital_gains_stcg_paise=-5 * L,
        ))
        assert with_loss.total_tax_paise == salary_only.total_tax_paise
        assert with_loss.gross_total_income_paise == salary_only.gross_total_income_paise
        assert with_loss.taxable_income_paise == salary_only.taxable_income_paise

    def test_each_capital_gains_head_is_floored_independently(self):
        salary_only = engine.compute(req(gross_salary_paise=20 * L))
        for field in ("capital_gains_stcg_paise", "capital_gains_ltcg_paise",
                      "capital_gains_ltcg_other_paise"):
            r = engine.compute(req(gross_salary_paise=20 * L, **{field: -5 * L}))
            assert r.total_tax_paise == salary_only.total_tax_paise, field
            assert r.gross_total_income_paise == salary_only.gross_total_income_paise, field

    def test_a_capital_loss_never_produces_negative_tax_on_its_own(self):
        r = engine.compute(req(capital_gains_ltcg_other_paise=-5 * L))
        assert r.total_tax_paise == 0
        assert r.tax_before_cess_paise == 0
        assert r.gross_total_income_paise == 0

    def test_the_dropped_loss_is_named_with_its_section_and_amount(self):
        """A silently dropped loss is its own trap — the figure the CA typed
        simply disappears from the computation."""
        r = engine.compute(req(gross_salary_paise=20 * L, capital_gains_stcg_paise=-5 * L))
        w = _warning_mentioning(r, "Short-term capital loss", "Section 71(3)")
        assert "₹500,000" in w
        assert "Section 74" in w

    def test_each_loss_head_is_named_separately(self):
        r = engine.compute(req(
            gross_salary_paise=20 * L,
            capital_gains_stcg_paise=-1 * L,
            capital_gains_ltcg_paise=-2 * L,
            capital_gains_ltcg_other_paise=-3 * L,
        ))
        _warning_mentioning(r, "Short-term capital loss", "₹100,000")
        _warning_mentioning(r, "Section 112A", "₹200,000")
        _warning_mentioning(r, "Section 112", "₹300,000")

    def test_the_intra_head_set_off_this_engine_does_not_do_is_declared(self):
        """Sections 70(2)/70(3) would let this short-term loss be set off
        against the long-term gain WITHIN the head. This engine floors each
        head instead, which can tax a gain the loss should have absorbed —
        so it says so rather than leaving the CA to discover it."""
        r = engine.compute(req(
            gross_salary_paise=20 * L,
            capital_gains_stcg_paise=-5 * L,
            capital_gains_ltcg_other_paise=5 * L,
        ))
        _warning_mentioning(r, "70(2)", "70(3)")

    def test_no_intra_head_warning_when_there_is_nothing_to_set_off_against(self):
        r = engine.compute(req(gross_salary_paise=20 * L, capital_gains_stcg_paise=-5 * L))
        assert not [w for w in r.warnings if "70(2)" in w]

    def test_a_positive_capital_gain_is_still_taxed_exactly_as_before(self):
        """The floor must not touch the ordinary case."""
        r = engine.compute(req(gross_salary_paise=20 * L, capital_gains_stcg_paise=5 * L))
        salary_only = engine.compute(req(gross_salary_paise=20 * L))
        rates = __import__("domain.income_tax.statutory_rates", fromlist=["RATES_BY_FY"]).RATES_BY_FY["2025-26"]
        expected = 5 * L * rates.stcg_111a_rate_bps // 10000
        assert r.tax_before_cess_paise - salary_only.tax_before_cess_paise == expected


# ── Section 80G(4) — the qualifying limit ──────────────────────────────────

class TestSection80GQualifyingLimit:
    def test_the_reported_defect_a_9_lakh_donation_against_a_10_lakh_salary(self):
        """Salary ₹10,00,000, less the old regime's ₹50,000 standard
        deduction, is an adjusted gross total income of ₹9,50,000. The
        qualifying amount is 10% of that — ₹95,000 — and half of it is
        deductible: ₹47,500, not ₹4,50,000."""
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            donations_80g=[Donation80G("Approved trust", 9 * L, 50)],
        ))
        assert r.deduction_80g_paise == 47_500 * 100

    def test_a_donation_inside_the_limit_is_deducted_in_full(self):
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            donations_80g=[Donation80G("Approved trust", 50_000 * 100, 50)],
        ))
        assert r.deduction_80g_paise == 25_000 * 100

    def test_the_ceiling_is_ten_percent_of_adjusted_gross_total_income(self):
        assert LIMIT_80G_QUALIFYING_PERCENT == 10

    def test_the_limit_is_explained_with_both_figures_when_it_bites(self):
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            donations_80g=[Donation80G("Approved trust", 9 * L, 50)],
        ))
        w = _warning_mentioning(r, "Section 80G(4)")
        assert "₹900,000" in w and "₹95,000" in w and "₹950,000" in w

    def test_no_qualifying_limit_warning_when_the_donation_fits(self):
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            donations_80g=[Donation80G("Approved trust", 50_000 * 100, 50)],
        ))
        assert not [w for w in r.warnings if "Section 80G(4)" in w]


class TestSection80GNotEveryDonationCarriesTheLimit:
    def test_a_fund_listed_in_80g_1_i_is_deducted_without_any_ceiling(self):
        """The PM National Relief Fund and its neighbours are 100%, no
        qualifying limit. The old model had only amount and percentage and
        could not express the difference at all."""
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            donations_80g=[Donation80G("PM National Relief Fund", 9 * L, 100,
                                       subject_to_qualifying_limit=False)],
        ))
        assert r.deduction_80g_paise == 9 * L

    def test_the_default_is_subject_to_the_limit(self):
        """An unmarked donee is the residual category the section itself
        puts it in, and it is the direction that cannot over-claim."""
        assert Donation80G("x", 1 * L, 50).subject_to_qualifying_limit is True

    def test_an_unlimited_donation_does_not_consume_the_limited_one_s_ceiling(self):
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            donations_80g=[
                Donation80G("PM National Relief Fund", 2 * L, 100,
                            subject_to_qualifying_limit=False),
                Donation80G("Approved trust", 9 * L, 50),
            ],
        ))
        # ₹2,00,000 at 100% with no ceiling, plus 50% of the ₹95,000 that
        # qualifies out of the limited ₹9,00,000.
        assert r.deduction_80g_paise == 2 * L + 47_500 * 100

    def test_mixed_percentages_inside_the_ceiling_are_apportioned_pro_rata(self):
        """FLAGGED CHOICE, pinned so a later change is deliberate. Section
        80G(4) caps the AGGREGATE of the limited donations and does not say
        which of them the qualifying amount is made of. Practice adjusts it
        against the 100% donations first (₹95,000 here); this engine
        apportions pro rata (₹47,500 at 100% + ₹47,500 at 50% = ₹71,250),
        which can never exceed the most-beneficial figure, and says so."""
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            donations_80g=[
                Donation80G("Limited 100% donee", 5 * L, 100),
                Donation80G("Limited 50% donee", 5 * L, 50),
            ],
        ))
        assert r.deduction_80g_paise == 71_250 * 100
        _warning_mentioning(r, "pro rata", "CA review required")

    def test_no_apportionment_warning_when_every_limited_donation_shares_a_rate(self):
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            donations_80g=[Donation80G("A", 5 * L, 50), Donation80G("B", 5 * L, 50)],
        ))
        assert not [w for w in r.warnings if "pro rata" in w]


class TestAdjustedGrossTotalIncome:
    def test_capital_gains_are_outside_the_base(self):
        """Sections 112(2) and 111A(2) take the special-rate gains out of
        gross total income before any Chapter VI-A deduction is computed. If
        they were left in, the ceiling here would be ₹5,95,000 instead of
        ₹95,000 and the deduction ₹2,50,000 instead of ₹47,500."""
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            capital_gains_ltcg_paise=50 * L,
            donations_80g=[Donation80G("Approved trust", 5 * L, 50)],
        ))
        assert r.deduction_80g_paise == 47_500 * 100

    def test_other_chapter_via_deductions_come_off_the_base_first(self):
        """Section 80G(4): gross total income reduced by "any amount in
        respect of which the assessee is entitled to a deduction under any
        other provision of this Chapter". ₹9,50,000 − ₹1,50,000 of 80C
        leaves ₹8,00,000, a ₹80,000 ceiling and a ₹40,000 deduction."""
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            s80c=Deductions80C(ppf_paise=int(1.5 * L)),
            donations_80g=[Donation80G("Approved trust", 5 * L, 50)],
        ))
        assert r.deduction_80c_paise == int(1.5 * L)
        assert r.deduction_80g_paise == 40_000 * 100

    def test_the_standard_deduction_is_already_out_of_the_base(self):
        """It is a Section 16(ia) deduction from the salary head, so gross
        total income is net of it before Section 80G(4) starts."""
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            donations_80g=[Donation80G("Approved trust", 5 * L, 50)],
        ))
        # 10% of (₹10,00,000 − ₹50,000) = ₹95,000, half of which is ₹47,500.
        assert r.deduction_80g_paise == 47_500 * 100


class TestSection80G5DCashBar:
    def test_a_cash_donation_over_2000_gets_nothing(self):
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            donations_80g=[Donation80G("Cash to trust", 5_000 * 100, 50, paid_in_cash=True)],
        ))
        assert r.deduction_80g_paise == 0
        _warning_mentioning(r, "Section 80G(5D)", "₹5,000")

    def test_a_cash_donation_of_exactly_2000_is_still_allowed(self):
        """The section bars a sum EXCEEDING ₹2,000."""
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            donations_80g=[Donation80G("Cash", LIMIT_80G_CASH_PAISE, 50, paid_in_cash=True)],
        ))
        assert r.deduction_80g_paise == 1_000 * 100

    def test_the_same_donation_paid_by_bank_is_allowed(self):
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            donations_80g=[Donation80G("Bank transfer", 5_000 * 100, 50, paid_in_cash=False)],
        ))
        assert r.deduction_80g_paise == 2_500 * 100
        assert not [w for w in r.warnings if "80G(5D)" in w]

    def test_a_disallowed_cash_donation_does_not_consume_the_qualifying_ceiling(self):
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            donations_80g=[
                Donation80G("Cash", 9 * L, 50, paid_in_cash=True),
                Donation80G("Bank transfer", 50_000 * 100, 50, paid_in_cash=False),
            ],
        ))
        assert r.deduction_80g_paise == 25_000 * 100

    def test_an_unstated_mode_of_payment_is_allowed_but_reported(self):
        """No caller supplies the mode today. A zero for "paid by cheque"
        and a zero for "nobody said" must not be the same number."""
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            donations_80g=[Donation80G("Approved trust", 50_000 * 100, 50)],
        ))
        assert r.deduction_80g_paise == 25_000 * 100
        _warning_mentioning(r, "Section 80G(5D)", "no mode of payment is recorded")

    def test_a_small_donation_with_no_stated_mode_raises_nothing(self):
        """Under ₹2,000 the mode cannot change the answer, so saying so
        would be noise."""
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=False,
            donations_80g=[Donation80G("Small", 1_500 * 100, 50)],
        ))
        assert r.deduction_80g_paise == 750 * 100
        assert not [w for w in r.warnings if "80G(5D)" in w]


class TestSection80GUnderTheNewRegime:
    def test_no_deduction_and_the_silence_is_explained(self):
        """Section 115BAC(2) allows no Chapter VI-A deduction except
        80CCD(2)/80CCH(2)/80JJAA. Donations were being entered and dropped
        with nothing said."""
        r = engine.compute(req(
            gross_salary_paise=10 * L,
            use_new_regime=True,
            donations_80g=[Donation80G("Approved trust", 5 * L, 50)],
        ))
        assert r.deduction_80g_paise == 0
        _warning_mentioning(r, "115BAC(2)", "₹500,000")
