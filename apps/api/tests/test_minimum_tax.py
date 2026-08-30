"""
Minimum taxes — MAT under §115JB and AMT under §115JC to §115JF.

Neither existed. A company with large book profits and small taxable income —
the exact case MAT was written for — was computed as owing almost nothing.

They are not one rule with two names:

  MAT   companies, 15% of BOOK PROFIT (Companies Act profit as adjusted by
        Explanation 1), and NOT applicable to a §115BAA or §115BAB company.
  AMT   everyone else, 18.5% of ADJUSTED TOTAL INCOME, and only where a §10AA,
        §35AD or Chapter VI-A Part C deduction has been claimed.

Verified against published sources for FY 2025-26 before being written down.
"""
import pytest

from domain.income_tax.entity_rates import CRORE_PAISE
from domain.income_tax.minimum_tax import (
    apply_minimum_tax, compute_amt, compute_mat, minimum_tax_rates_for,
)

FY = "2025-26"
LAKH = 1_00_000_00


# ── MAT, §115JB ──────────────────────────────────────────────────────────────

def test_mat_is_fifteen_percent_of_book_profit():
    r = compute_mat(book_profit_paise=1 * CRORE_PAISE, fy=FY)
    assert r.applies is True
    assert r.section == "115JB"
    assert r.minimum_tax_before_surcharge_paise == 15 * LAKH


def test_mat_effective_rate_with_surcharge_and_cess():
    """15% × 1.07 × 1.04 = 16.692% once the 7% company surcharge bites."""
    r = compute_mat(book_profit_paise=5 * CRORE_PAISE, fy=FY)
    assert r.minimum_tax_paise * 100 / (5 * CRORE_PAISE) == pytest.approx(16.692)


def test_mat_does_not_apply_to_a_115baa_company():
    """That regime trades the incentives away for a lower rate, so there is
    nothing left for a floor to catch. Charging MAT on top would tax a company
    twice for giving up its deductions."""
    r = compute_mat(book_profit_paise=5 * CRORE_PAISE, company_regime="115BAA", fy=FY)
    assert r.applies is False
    assert r.minimum_tax_paise == 0
    assert any("115BAA" in x for x in r.reasons)


def test_mat_does_not_apply_to_a_115bab_company():
    r = compute_mat(book_profit_paise=5 * CRORE_PAISE, company_regime="115BAB", fy=FY)
    assert r.applies is False


def test_mat_says_its_base_is_book_profit_not_taxable_income():
    """The difference between them is the entire reason the section exists."""
    r = compute_mat(book_profit_paise=1 * CRORE_PAISE, fy=FY)
    assert "book profit" in " ".join(r.reasons)
    assert "not taxable income" in " ".join(r.reasons)


def test_a_book_loss_produces_no_mat():
    r = compute_mat(book_profit_paise=-2 * CRORE_PAISE, fy=FY)
    assert r.minimum_tax_paise == 0


# ── AMT, §115JC ──────────────────────────────────────────────────────────────

def test_amt_is_eighteen_point_five_percent_of_adjusted_total_income():
    """18.5% × 1.04 = 19.24% below the surcharge threshold."""
    r = compute_amt(adjusted_total_income_paise=50 * LAKH, assessee="llp",
                    claimed_specified_deduction=True, fy=FY)
    assert r.applies is True
    assert r.section == "115JC"
    assert r.minimum_tax_paise * 100 / (50 * LAKH) == pytest.approx(19.24)


def test_the_rate_stays_in_integers_despite_being_a_half_percent():
    """18.5% cannot be an integer percent. It is held as tenths so no float
    enters a tax computation — CLAUDE.md, integer paise throughout."""
    assert minimum_tax_rates_for(FY).amt_rate_percent_x10 == 185
    r = compute_amt(adjusted_total_income_paise=1 * CRORE_PAISE, assessee="firm",
                    claimed_specified_deduction=True, fy=FY)
    assert r.minimum_tax_before_surcharge_paise == 1 * CRORE_PAISE * 185 // 1000
    assert isinstance(r.minimum_tax_paise, int)


def test_amt_needs_a_triggering_deduction_to_apply_at_all():
    """A taxpayer who claimed no §10AA, §35AD or Chapter VI-A Part C deduction
    is outside Chapter XII-BA entirely — not merely below its threshold."""
    r = compute_amt(adjusted_total_income_paise=5 * CRORE_PAISE, assessee="llp",
                    claimed_specified_deduction=False, fy=FY)
    assert r.applies is False
    assert any("does not apply at all" in x for x in r.reasons)


def test_a_company_is_charged_under_mat_not_amt():
    r = compute_amt(adjusted_total_income_paise=5 * CRORE_PAISE,
                    assessee="domestic_company",
                    claimed_specified_deduction=True, fy=FY)
    assert r.applies is False
    assert any("§115JB instead" in x for x in r.reasons)


# ── §115JEE's threshold, and who does NOT get it ─────────────────────────────

@pytest.mark.parametrize("assessee", ["individual", "huf", "aop", "boi",
                                      "artificial_juridical_person"])
def test_the_twenty_lakh_cushion_covers_individuals_and_the_like(assessee):
    r = compute_amt(adjusted_total_income_paise=20 * LAKH, assessee=assessee,
                    claimed_specified_deduction=True, fy=FY)
    assert r.applies is False
    assert any("115JEE" in x for x in r.reasons)


def test_the_cushion_is_lost_one_paise_over_twenty_lakh():
    r = compute_amt(adjusted_total_income_paise=20 * LAKH + 1,
                    assessee="individual", claimed_specified_deduction=True, fy=FY)
    assert r.applies is True


@pytest.mark.parametrize("assessee", ["firm", "llp"])
def test_a_firm_or_llp_has_no_cushion_at_any_income(assessee):
    """The asymmetry that is easy to miss and expensive. §115JEE names
    individuals, HUFs, AOPs, BOIs and artificial juridical persons — a firm or
    LLP is absent. Extending the threshold to them silently zeroes the
    liability of every small LLP that claims §35AD."""
    small = compute_amt(adjusted_total_income_paise=1 * LAKH, assessee=assessee,
                        claimed_specified_deduction=True, fy=FY)
    assert small.applies is True
    assert small.minimum_tax_paise > 0
    assert any("no §115JEE threshold" in x for x in small.reasons)


# ── The higher applies, and the excess is a credit ───────────────────────────

def test_the_minimum_applies_when_it_exceeds_ordinary_tax():
    m = compute_mat(book_profit_paise=5 * CRORE_PAISE, fy=FY)
    out = apply_minimum_tax(regular_tax_paise=10 * LAKH, minimum=m, fy=FY)
    assert out.minimum_tax_applied is True
    assert out.tax_payable_paise == m.minimum_tax_paise


def test_ordinary_tax_stands_when_it_is_the_higher():
    m = compute_mat(book_profit_paise=1 * CRORE_PAISE, fy=FY)
    out = apply_minimum_tax(regular_tax_paise=5 * CRORE_PAISE, minimum=m, fy=FY)
    assert out.minimum_tax_applied is False
    assert out.tax_payable_paise == 5 * CRORE_PAISE
    assert out.credit_generated_paise == 0


def test_the_excess_becomes_a_credit():
    """Paying a minimum tax is not a penalty. Charging the floor without
    recording the credit turns a timing difference into a permanent cost — a
    real loss to the client, invisible in the year it happens because the
    return still balances."""
    m = compute_mat(book_profit_paise=5 * CRORE_PAISE, fy=FY)
    out = apply_minimum_tax(regular_tax_paise=10 * LAKH, minimum=m, fy=FY)
    assert out.credit_generated_paise == m.minimum_tax_paise - 10 * LAKH
    assert any("115JAA" in x for x in out.reasons)


def test_an_amt_credit_is_attributed_to_115jd_not_115jaa():
    """Separate provisions, separate sections. Naming the wrong one sends a CA
    to the wrong schedule of the return."""
    a = compute_amt(adjusted_total_income_paise=1 * CRORE_PAISE, assessee="llp",
                    claimed_specified_deduction=True, fy=FY)
    out = apply_minimum_tax(regular_tax_paise=1 * LAKH, minimum=a, fy=FY)
    assert any("115JD" in x for x in out.reasons)
    assert not any("115JAA" in x for x in out.reasons)


def test_the_credit_runs_fifteen_assessment_years():
    m = compute_mat(book_profit_paise=5 * CRORE_PAISE, fy=FY)
    out = apply_minimum_tax(regular_tax_paise=10 * LAKH, minimum=m,
                            assessment_year_end=2027, fy=FY)
    assert out.credit_expires_after_ay == 2042
    assert minimum_tax_rates_for(FY).credit_carry_forward_years == 15


def test_no_credit_arises_where_the_minimum_does_not_apply():
    m = compute_mat(book_profit_paise=5 * CRORE_PAISE, company_regime="115BAA", fy=FY)
    out = apply_minimum_tax(regular_tax_paise=10 * LAKH, minimum=m, fy=FY)
    assert out.tax_payable_paise == 10 * LAKH
    assert out.credit_generated_paise == 0


# ── FY versioning ────────────────────────────────────────────────────────────

def test_the_verified_year_carries_the_checked_figures():
    r = minimum_tax_rates_for(FY)
    assert r.verified is True
    assert r.mat_rate_percent == 15
    assert r.amt_rate_percent_x10 == 185
    assert r.amt_threshold_paise == 20 * LAKH


def test_an_unverified_year_carries_forward_and_says_so():
    later = minimum_tax_rates_for("2026-27")
    assert later.verified is False
    assert later.mat_rate_percent == minimum_tax_rates_for(FY).mat_rate_percent
