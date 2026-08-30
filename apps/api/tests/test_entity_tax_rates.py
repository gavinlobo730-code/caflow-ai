"""
Tax rates for entities that are not individuals — firm, LLP, domestic company.

domain/income_tax/statutory_rates carried the INDIVIDUAL slabs and nothing
else, so a practice serving a partnership, an LLP or a company could not
compute their liability at all. Each pays on a completely different basis from
an individual and from each other.

Figures verified against published sources for FY 2025-26 before being written
down. The effective rates below are the arithmetic every Indian CA knows by
heart, which is what makes them worth asserting: 31.2%, 34.944%, 26%, 25.168%
and 17.16% are recognisable on sight, so a wrong constant shows up here rather
than in a client's demand notice.
"""
import pytest

from domain.income_tax.entity_rates import (
    CRORE_PAISE, compute_entity_tax, entity_rates_for, turnover_reference_fy,
)

FY = "2025-26"
LAKH = 1_00_000_00


def _effective_percent(income_paise: int, **kw) -> float:
    r = compute_entity_tax(total_income_paise=income_paise, fy=FY, **kw)
    return r.total_tax_paise * 100 / income_paise


# ── Firms and LLPs ───────────────────────────────────────────────────────────

def test_a_firm_pays_thirty_percent_from_the_first_rupee():
    """No slabs, no exemption limit. Applying individual slabs to a firm — the
    only rates that existed before this — undercharges every small firm."""
    r = compute_entity_tax(total_income_paise=1 * LAKH, entity="firm", fy=FY)
    assert r.rate_percent == 30
    assert r.tax_before_surcharge_paise == 30_000_00
    assert r.surcharge_paise == 0


def test_an_llp_is_taxed_exactly_as_a_firm():
    """The LLP Act changes who they are, not what they pay."""
    firm = compute_entity_tax(total_income_paise=80 * LAKH, entity="firm", fy=FY)
    llp = compute_entity_tax(total_income_paise=80 * LAKH, entity="llp", fy=FY)
    assert llp.total_tax_paise == firm.total_tax_paise


def test_a_firm_below_one_crore_pays_no_surcharge():
    assert _effective_percent(50 * LAKH, entity="firm") == pytest.approx(31.2)


def test_a_firm_above_one_crore_pays_twelve_percent_surcharge():
    """30% × 1.12 × 1.04 = 34.944%."""
    assert _effective_percent(2 * CRORE_PAISE, entity="firm") == pytest.approx(34.944)


def test_marginal_relief_applies_at_the_firm_surcharge_threshold():
    """Crossing one crore by a rupee must not cost more than a rupee of extra
    tax. Without relief the surcharge lands on the whole liability at once."""
    at = compute_entity_tax(total_income_paise=1 * CRORE_PAISE, entity="firm", fy=FY)
    just_over = compute_entity_tax(total_income_paise=1 * CRORE_PAISE + 100,
                                   entity="firm", fy=FY)
    extra_income = 100
    extra_tax = just_over.total_tax_paise - at.total_tax_paise
    assert extra_tax <= extra_income * 2, (
        f"crossing the threshold by {extra_income} paise cost {extra_tax} paise"
    )


# ── The turnover reference year ──────────────────────────────────────────────

def test_the_turnover_test_looks_two_years_back():
    """For FY 2025-26 (AY 2026-27) the 400 crore test is on FY 2023-24, NOT on
    the year being taxed. Using the current year's turnover moves companies
    across the 25%/30% boundary in the wrong direction and by a whole year."""
    assert turnover_reference_fy("2025-26") == "2023-24"
    assert turnover_reference_fy("2024-25") == "2022-23"


def test_the_result_names_the_year_its_turnover_test_used():
    r = compute_entity_tax(total_income_paise=1 * CRORE_PAISE,
                           entity="domestic_company", fy=FY,
                           turnover_in_reference_year_paise=300 * CRORE_PAISE)
    assert r.turnover_reference_fy == "2023-24"
    assert "2023-24" in " ".join(r.workings)


# ── Domestic company, normal regime ──────────────────────────────────────────

def test_turnover_within_four_hundred_crore_gives_the_lower_rate():
    r = compute_entity_tax(total_income_paise=1 * CRORE_PAISE,
                           entity="domestic_company", fy=FY,
                           turnover_in_reference_year_paise=400 * CRORE_PAISE)
    assert r.rate_percent == 25


def test_turnover_above_four_hundred_crore_gives_thirty_percent():
    r = compute_entity_tax(total_income_paise=1 * CRORE_PAISE,
                           entity="domestic_company", fy=FY,
                           turnover_in_reference_year_paise=400 * CRORE_PAISE + 1)
    assert r.rate_percent == 30


def test_an_unknown_turnover_takes_the_HIGHER_rate():
    """The concession has to be established, not assumed. Guessing the lower
    rate understates the liability, which is the direction that produces a
    demand notice rather than a refund."""
    r = compute_entity_tax(total_income_paise=1 * CRORE_PAISE,
                           entity="domestic_company", fy=FY)
    assert r.rate_percent == 30
    assert any("has to be established, not assumed" in w for w in r.workings)


def test_company_surcharge_has_two_steps():
    """7% above one crore, 12% above ten."""
    below = compute_entity_tax(total_income_paise=50 * LAKH,
                               entity="domestic_company", fy=FY)
    mid = compute_entity_tax(total_income_paise=5 * CRORE_PAISE,
                             entity="domestic_company", fy=FY)
    high = compute_entity_tax(total_income_paise=50 * CRORE_PAISE,
                              entity="domestic_company", fy=FY)
    assert below.surcharge_paise == 0
    assert mid.surcharge_paise == mid.tax_before_surcharge_paise * 7 // 100
    assert high.surcharge_paise == high.tax_before_surcharge_paise * 12 // 100


# ── The concessional regimes ─────────────────────────────────────────────────

def test_115baa_is_twenty_two_percent_and_lands_at_25_168():
    """22 × 1.10 × 1.04 = 25.168%, the figure every CA recognises."""
    assert _effective_percent(50 * LAKH, entity="domestic_company",
                              company_regime="115BAA") == pytest.approx(25.168)


def test_115bab_is_fifteen_percent_and_lands_at_17_16():
    """15 × 1.10 × 1.04 = 17.16%."""
    assert _effective_percent(50 * LAKH, entity="domestic_company",
                              company_regime="115BAB") == pytest.approx(17.16)


def test_the_concessional_surcharge_applies_below_one_crore_too():
    """The trap. A normal company under one crore pays NO surcharge; a §115BAA
    company at the same income pays 10%. Reusing the normal brackets for a
    company that has opted in understates its tax by a tenth."""
    normal = compute_entity_tax(total_income_paise=50 * LAKH,
                                entity="domestic_company", fy=FY,
                                turnover_in_reference_year_paise=10 * CRORE_PAISE)
    baa = compute_entity_tax(total_income_paise=50 * LAKH,
                             entity="domestic_company", fy=FY,
                             company_regime="115BAA")
    assert normal.surcharge_paise == 0
    assert baa.surcharge_paise == baa.tax_before_surcharge_paise * 10 // 100


def test_the_concessional_surcharge_does_not_step_up_at_ten_crore():
    """Flat means flat. It is 10% at every income, so a large §115BAA company
    must not pick up the normal regime's 12%."""
    for income in (50 * LAKH, 5 * CRORE_PAISE, 500 * CRORE_PAISE):
        r = compute_entity_tax(total_income_paise=income, entity="domestic_company",
                               fy=FY, company_regime="115BAA")
        assert r.surcharge_paise == r.tax_before_surcharge_paise * 10 // 100


def test_a_concessional_company_ignores_the_turnover_test():
    """§115BAA's rate does not depend on turnover, so supplying one — or not —
    must not move it."""
    with_turnover = compute_entity_tax(
        total_income_paise=50 * LAKH, entity="domestic_company", fy=FY,
        company_regime="115BAA", turnover_in_reference_year_paise=900 * CRORE_PAISE)
    without = compute_entity_tax(total_income_paise=50 * LAKH,
                                 entity="domestic_company", fy=FY,
                                 company_regime="115BAA")
    assert with_turnover.total_tax_paise == without.total_tax_paise
    assert with_turnover.rate_percent == 22


# ── Housekeeping ─────────────────────────────────────────────────────────────

def test_every_figure_is_integer_paise():
    r = compute_entity_tax(total_income_paise=1_23_45_678, entity="firm", fy=FY)
    for value in (r.tax_before_surcharge_paise, r.surcharge_paise, r.cess_paise,
                  r.total_tax_paise):
        assert isinstance(value, int)


def test_nil_income_produces_nil_tax():
    r = compute_entity_tax(total_income_paise=0, entity="firm", fy=FY)
    assert r.total_tax_paise == 0


def test_a_negative_total_income_is_floored_rather_than_refunded():
    r = compute_entity_tax(total_income_paise=-5 * LAKH, entity="firm", fy=FY)
    assert r.total_tax_paise == 0


def test_the_verified_year_carries_the_figures_checked_against_sources():
    rates = entity_rates_for(FY)
    assert rates.verified is True
    assert rates.firm_rate_percent == 30
    assert rates.company_rate_percent == 30
    assert rates.company_concessional_rate_percent == 25
    assert rates.company_turnover_limit_paise == 400 * CRORE_PAISE
    assert rates.company_turnover_lookback_years == 2
    assert rates.s115baa_rate_percent == 22
    assert rates.s115bab_rate_percent == 15
    assert rates.concessional_surcharge_percent == 10


def test_an_unverified_year_carries_forward_and_says_so():
    later = entity_rates_for("2026-27")
    assert later.verified is False
    assert later.firm_rate_percent == entity_rates_for(FY).firm_rate_percent


def test_an_unknown_entity_is_refused_by_name():
    with pytest.raises(ValueError, match="not an entity"):
        compute_entity_tax(total_income_paise=1 * LAKH, entity="trust", fy=FY)
