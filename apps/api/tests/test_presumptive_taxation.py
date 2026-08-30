"""
Presumptive taxation — IT Act 1961, §44AD, §44ADA and §44AE.

None of this existed. A large part of an Indian practice's client base — small
traders, doctors, architects, lawyers, lorry owners — files under one of these
schemes, so a product that cannot compute a presumptive return cannot file for
them at all.

FIGURES VERIFIED FOR FY 2025-26 (AY 2026-27) against published sources before
being written down:
  §44AD   8% of turnover, 6% on the part received through prescribed banking
          modes; ceiling 2 crore, raised to 3 crore where cash receipts are
          within 5% of turnover.
  §44ADA  50% of gross receipts; ceiling 50 lakh, raised to 75 lakh on the same
          cash test.
  §44AE   1,000 rupees per ton per month for a heavy goods vehicle (gross
          vehicle weight over 12,000 kg), 7,500 rupees per month otherwise;
          available only while 10 or fewer goods carriages are owned.
"""
import pytest

from domain.income_tax.itr_engine import ITRComputeRequest, ITREngine
from domain.income_tax.presumptive import (
    CRORE_PAISE, LAKH_PAISE, GoodsCarriage, compute_44ad, compute_44ada,
    compute_44ae, limits_for,
)

FY = "2025-26"


# ── §44AD ────────────────────────────────────────────────────────────────────

def test_the_two_rates_apply_to_their_own_slices_of_turnover():
    """8% and 6% are not alternatives to choose between. A business is usually
    part banked and part cash, and the section charges each slice at its own
    rate — picking one rate for the whole turnover misstates every mixed
    business."""
    r = compute_44ad(turnover_paise=150 * LAKH_PAISE,
                     digital_turnover_paise=100 * LAKH_PAISE,
                     cash_receipts_paise=5 * LAKH_PAISE, fy=FY)
    # 6% of 1,00,00,000 = 6,00,000 ; 8% of 50,00,000 = 4,00,000
    assert r.presumptive_income_paise == 10 * LAKH_PAISE
    assert r.eligible is True


def test_wholly_cash_turnover_is_charged_at_eight_percent():
    r = compute_44ad(turnover_paise=50 * LAKH_PAISE, fy=FY)
    assert r.presumptive_income_paise == 4 * LAKH_PAISE


def test_the_ceiling_is_two_crore_when_cash_receipts_are_significant():
    r = compute_44ad(turnover_paise=250 * LAKH_PAISE,
                     cash_receipts_paise=100 * LAKH_PAISE, fy=FY)
    assert r.turnover_limit_paise == 2 * CRORE_PAISE
    assert r.enhanced_limit_applied is False
    assert r.eligible is False
    assert any("exceeds the §44AD ceiling" in x for x in r.reasons)


def test_the_ceiling_rises_to_three_crore_when_cash_is_within_five_percent():
    """The proviso to §44AD(1). Without it a 2.5 crore mostly-banked business
    is wrongly told the scheme is closed to it."""
    r = compute_44ad(turnover_paise=250 * LAKH_PAISE,
                     cash_receipts_paise=10 * LAKH_PAISE, fy=FY)
    assert r.turnover_limit_paise == 3 * CRORE_PAISE
    assert r.enhanced_limit_applied is True
    assert r.eligible is True


def test_cash_of_exactly_five_percent_qualifies():
    """"Does not exceed five per cent" includes five per cent. The comparison
    is by cross-multiplication rather than by computing a percentage, so no
    division rounds a taxpayer across the boundary."""
    r = compute_44ad(turnover_paise=300 * LAKH_PAISE,
                     cash_receipts_paise=15 * LAKH_PAISE, fy=FY)
    assert r.enhanced_limit_applied is True
    assert r.eligible is True


def test_a_paise_over_five_percent_does_not_qualify():
    r = compute_44ad(turnover_paise=300 * LAKH_PAISE,
                     cash_receipts_paise=15 * LAKH_PAISE + 1, fy=FY)
    assert r.enhanced_limit_applied is False
    assert r.eligible is False


def test_declaring_more_than_the_presumptive_figure_is_allowed():
    """§44AD(1): "or a sum higher than the aforesaid sum claimed to have been
    earned"."""
    r = compute_44ad(turnover_paise=50 * LAKH_PAISE,
                     declared_income_paise=6 * LAKH_PAISE, fy=FY)
    assert r.eligible is True
    assert r.presumptive_income_paise == 4 * LAKH_PAISE
    assert r.declared_income_paise == 6 * LAKH_PAISE


def test_declaring_less_is_refused_rather_than_quietly_accepted():
    """§44AD(5) requires books under §44AA and audit under §44AB where income
    is declared below the presumptive figure. Accepting a lower number here
    would produce a return that looks compliant and is not."""
    r = compute_44ad(turnover_paise=50 * LAKH_PAISE,
                     declared_income_paise=1 * LAKH_PAISE, fy=FY)
    assert r.eligible is False
    assert any("§44AD(5)" in x for x in r.reasons)
    assert r.declared_income_paise == 0


def test_the_eligibility_the_figures_cannot_settle_is_stated():
    """Whether the client is a resident individual, HUF or non-LLP firm, and
    is not in a profession, commission or agency business, is not derivable
    from a turnover figure. The scheme says so rather than assuming."""
    r = compute_44ad(turnover_paise=10 * LAKH_PAISE, fy=FY)
    joined = " ".join(r.reasons)
    assert "LLP" in joined and "§44AA(1)" in joined and "agency" in joined


# ── §44ADA ───────────────────────────────────────────────────────────────────

def test_a_profession_declares_half_its_gross_receipts():
    r = compute_44ada(gross_receipts_paise=40 * LAKH_PAISE, fy=FY)
    assert r.presumptive_income_paise == 20 * LAKH_PAISE
    assert r.eligible is True


def test_the_professional_ceiling_is_fifty_lakh_with_significant_cash():
    r = compute_44ada(gross_receipts_paise=60 * LAKH_PAISE,
                      cash_receipts_paise=20 * LAKH_PAISE, fy=FY)
    assert r.turnover_limit_paise == 50 * LAKH_PAISE
    assert r.eligible is False


def test_the_professional_ceiling_rises_to_seventy_five_lakh():
    r = compute_44ada(gross_receipts_paise=60 * LAKH_PAISE,
                      cash_receipts_paise=1 * LAKH_PAISE, fy=FY)
    assert r.turnover_limit_paise == 75 * LAKH_PAISE
    assert r.eligible is True
    assert r.presumptive_income_paise == 30 * LAKH_PAISE


def test_a_professional_may_not_declare_less_either():
    r = compute_44ada(gross_receipts_paise=40 * LAKH_PAISE,
                      declared_income_paise=5 * LAKH_PAISE, fy=FY)
    assert r.eligible is False
    assert any("§44ADA(4)" in x for x in r.reasons)


# ── §44AE ────────────────────────────────────────────────────────────────────

def test_a_heavy_goods_vehicle_earns_one_thousand_per_ton_per_month():
    """1,000 rupees per ton is exactly 1 rupee per kilogram, so a 16,500 kg
    vehicle earns 16,500 a month. Converting to whole tons first would lose
    the half-ton or need a float."""
    r = compute_44ae(vehicles=[GoodsCarriage(16_500, 12)], fy=FY)
    assert r.presumptive_income_paise == 16_500 * 12 * 100


def test_a_lighter_goods_carriage_earns_a_flat_monthly_amount():
    r = compute_44ae(vehicles=[GoodsCarriage(9_000, 12)], fy=FY)
    assert r.presumptive_income_paise == 7_500 * 12 * 100


def test_twelve_tonnes_exactly_is_not_a_heavy_goods_vehicle():
    """"Exceeding 12,000 kg" — a vehicle AT the boundary is not over it, and
    getting this wrong doubles the income of every 12-tonne lorry."""
    at_limit = compute_44ae(vehicles=[GoodsCarriage(12_000, 1)], fy=FY)
    over = compute_44ae(vehicles=[GoodsCarriage(12_001, 1)], fy=FY)
    assert at_limit.presumptive_income_paise == 7_500 * 100
    assert over.presumptive_income_paise == 12_001 * 100


def test_a_mixed_fleet_sums_each_vehicle_on_its_own_basis():
    r = compute_44ae(vehicles=[GoodsCarriage(16_500, 12), GoodsCarriage(9_000, 6)],
                     fy=FY)
    assert r.presumptive_income_paise == (16_500 * 12 + 7_500 * 6) * 100


def test_more_than_ten_carriages_closes_the_scheme():
    """§44AE caps VEHICLES, not turnover — which is what makes it shaped
    differently from the other two schemes."""
    r = compute_44ae(vehicles=[GoodsCarriage(9_000, 12) for _ in range(11)], fy=FY)
    assert r.eligible is False
    assert any("exceeds the §44AE limit" in x for x in r.reasons)


def test_exactly_ten_carriages_is_still_within_the_scheme():
    r = compute_44ae(vehicles=[GoodsCarriage(9_000, 12) for _ in range(10)], fy=FY)
    assert r.eligible is True


# ── The FY-versioned figures ─────────────────────────────────────────────────

def test_the_verified_year_carries_the_figures_checked_against_sources():
    lim = limits_for(FY)
    assert lim.verified is True
    assert lim.s44ad_rate_percent == 8
    assert lim.s44ad_digital_rate_percent == 6
    assert lim.s44ad_turnover_limit_paise == 2 * CRORE_PAISE
    assert lim.s44ad_enhanced_turnover_limit_paise == 3 * CRORE_PAISE
    assert lim.s44ada_rate_percent == 50
    assert lim.s44ada_receipts_limit_paise == 50 * LAKH_PAISE
    assert lim.s44ada_enhanced_receipts_limit_paise == 75 * LAKH_PAISE
    assert lim.enhanced_limit_cash_receipts_percent == 5
    assert lim.s44ae_heavy_gvw_kg == 12_000
    assert lim.s44ae_max_goods_carriages == 10


def test_an_unverified_year_carries_figures_forward_and_says_so():
    """Never guesses at new numbers. A firm filing on an unverified year has to
    confirm against that year's Finance Act, and the flag is how they know."""
    later = limits_for("2026-27")
    assert later.verified is False
    assert later.s44ad_rate_percent == limits_for(FY).s44ad_rate_percent


def test_a_year_beyond_the_registry_falls_back_rather_than_failing():
    assert limits_for("2099-00").fy == "2025-26"


# ── Wired into the return ────────────────────────────────────────────────────

def test_a_presumptive_figure_becomes_the_business_income():
    presumptive = compute_44ad(turnover_paise=50 * LAKH_PAISE, fy=FY)
    res = ITREngine().compute(ITRComputeRequest(
        presumptive_income_paise=presumptive.declared_income_paise, fy=FY))
    assert res.gross_total_income_paise == 4 * LAKH_PAISE


def test_a_presumptive_figure_replaces_book_profit_rather_than_adding_to_it():
    """Both are the same business. Adding them would tax it twice, and both
    numbers look reasonable on their own so nothing would look wrong."""
    res = ITREngine().compute(ITRComputeRequest(
        business_income_paise=9 * LAKH_PAISE,
        presumptive_income_paise=4 * LAKH_PAISE, fy=FY))
    assert res.gross_total_income_paise == 4 * LAKH_PAISE


def test_disallowances_do_not_apply_to_a_presumptive_return():
    """§44AD(2), §44ADA(3) and §44AE(6) deem every deduction under §30 to §38
    already allowed, so there is nothing left to disallow. Adding back a
    §40A(3) cash payment here would charge tax on an expense the section has
    already accounted for."""
    res = ITREngine().compute(ITRComputeRequest(
        presumptive_income_paise=4 * LAKH_PAISE,
        disallowances_paise=2 * LAKH_PAISE, fy=FY))
    assert res.gross_total_income_paise == 4 * LAKH_PAISE


def test_an_ordinary_return_is_unaffected():
    """The field is optional and None means "not presumptive" — every existing
    caller must compute exactly as before."""
    res = ITREngine().compute(ITRComputeRequest(
        business_income_paise=9 * LAKH_PAISE,
        disallowances_paise=1 * LAKH_PAISE, fy=FY))
    assert res.gross_total_income_paise == 10 * LAKH_PAISE
