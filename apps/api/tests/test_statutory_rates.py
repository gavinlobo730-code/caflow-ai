"""
domain.income_tax.statutory_rates — unit tests against hand-worked examples.

This is pure computation logic (no database involved), so exhaustive unit
tests against known-correct worked figures are the appropriate verification
method (CLAUDE.md: verify every change using the most appropriate method).
Several of these examples are the well-known illustrations used to explain
Budget 2025's ₹12L new-regime rebate and marginal relief.
"""
from datetime import date

from domain.income_tax.statutory_rates import (
    RATES_BY_FY, current_fy, rates_for, slab_tax_paise,
    apply_rebate_87a, apply_surcharge_with_marginal_relief, cess_paise,
)


def _slab_tax_fn(slabs):
    return lambda income_paise: slab_tax_paise(income_paise, slabs)

FY = RATES_BY_FY["2025-26"]


def p(rupees: float) -> int:
    return round(rupees * 100)


# ── current_fy / rates_for ────────────────────────────────────────────────────

def test_current_fy_before_april():
    assert current_fy(date(2026, 3, 31)) == "2025-26"


def test_current_fy_after_april():
    assert current_fy(date(2026, 4, 1)) == "2026-27"


def test_rates_for_defaults_to_current_fy():
    assert rates_for() is not None  # smoke: no crash, resolves the real "today"


def test_rates_for_unknown_future_fy_falls_back_to_latest_verified():
    r = rates_for("2030-31")
    assert r.fy == "2025-26"
    assert r.verified is True


def test_fy_2026_27_is_flagged_unverified():
    assert RATES_BY_FY["2026-27"].verified is False


def test_fy_2025_26_is_verified():
    assert RATES_BY_FY["2025-26"].verified is True


# ── slab_tax_paise — new regime ──────────────────────────────────────────────

def test_new_regime_zero_below_4l():
    assert slab_tax_paise(p(400_000), FY.new_regime_slabs) == 0


def test_new_regime_at_12l_boundary():
    # 4-8L @5% = 20,000; 8-12L @10% = 40,000 -> 60,000
    assert slab_tax_paise(p(1_200_000), FY.new_regime_slabs) == p(60_000)


def test_new_regime_top_bracket():
    # 0-4L=0, 4-8L@5%=20k, 8-12L@10%=40k, 12-16L@15%=60k, 16-20L@20%=80k,
    # 20-24L@25%=1,00,000, >24L@30% on the remainder
    income = p(2_500_000)
    expected = p(20_000 + 40_000 + 60_000 + 80_000 + 1_00_000) + p(100_000) * 30 // 100
    assert slab_tax_paise(income, FY.new_regime_slabs) == expected


def test_old_regime_general_at_10l():
    # 2.5-5L@5%=12,500; 5-10L@20%=1,00,000
    assert slab_tax_paise(p(1_000_000), FY.old_regime_slabs_general) == p(1_12_500)


def test_old_regime_senior_has_3l_nil_band():
    # Senior: 0-3L nil (not 0-2.5L) -- ₹2,90,000 must be zero tax.
    assert slab_tax_paise(p(2_90_000), FY.old_regime_slabs_senior) == 0
    assert slab_tax_paise(p(2_90_000), FY.old_regime_slabs_general) > 0


def test_old_regime_very_senior_has_5l_nil_band():
    assert slab_tax_paise(p(4_90_000), FY.old_regime_slabs_very_senior) == 0


# ── §87A rebate + marginal relief ─────────────────────────────────────────────

def test_new_regime_87a_full_rebate_at_exactly_12l():
    tax = slab_tax_paise(p(12_00_000), FY.new_regime_slabs)
    assert tax == p(60_000)
    assert apply_rebate_87a(p(12_00_000), tax, FY.new_regime_rebate) == 0


def test_new_regime_87a_marginal_relief_famous_example():
    """Textbook Budget-2025 example: at ₹12,10,000 (₹10,000 over the rebate
    ceiling), slab tax would be ₹61,500 -- but marginal relief caps the tax at
    the ₹10,000 excess income itself, not the full slab tax."""
    income = p(12_10_000)
    tax = slab_tax_paise(income, FY.new_regime_slabs)
    assert tax == p(61_500)
    relieved = apply_rebate_87a(income, tax, FY.new_regime_rebate)
    assert relieved == p(10_000)


def test_new_regime_87a_marginal_relief_exhausts_once_excess_exceeds_slab_tax():
    """Far enough above the ceiling, marginal relief no longer helps -- the
    assessee just pays ordinary slab tax once it's below the excess-income cap."""
    income = p(20_00_000)
    tax = slab_tax_paise(income, FY.new_regime_slabs)
    relieved = apply_rebate_87a(income, tax, FY.new_regime_rebate)
    assert relieved == tax  # far above 12L, marginal relief cap (8L excess) exceeds tax, so no relief applied


def test_old_regime_87a_full_rebate_at_exactly_5l():
    tax = slab_tax_paise(p(5_00_000), FY.old_regime_slabs_general)
    assert tax == p(12_500)
    assert apply_rebate_87a(p(5_00_000), tax, FY.old_regime_rebate) == 0


def test_old_regime_87a_is_a_hard_cliff_above_5l():
    """The old regime's Section 87A has NO marginal-relief proviso — that
    proviso (Finance Act 2023/2025) is expressly conditioned on income
    chargeable under Section 115BAC(1A), i.e. the new regime. Crossing
    ₹5,00,000 by ₹10,000 forfeits the entire ₹12,500 rebate: full slab tax
    is payable. (Caught by adversarial review — an earlier draft wrongly
    generalized the new regime's relief to both regimes.)"""
    income = p(5_10_000)
    tax = slab_tax_paise(income, FY.old_regime_slabs_general)
    assert tax == p(14_500)  # 12,500 + 20% of 10,000
    after_rebate = apply_rebate_87a(income, tax, FY.old_regime_rebate)
    assert after_rebate == tax  # no rebate, no relief — the statutory cliff


def test_marginal_relief_flags_encode_the_statute():
    assert FY.new_regime_rebate.marginal_relief is True   # 115BAC(1A) proviso
    assert FY.old_regime_rebate.marginal_relief is False  # no proviso — cliff


# ── Surcharge with marginal relief ────────────────────────────────────────────

def test_no_surcharge_below_50l():
    tax = slab_tax_paise(p(40_00_000), FY.old_regime_slabs_general)
    surcharge = apply_surcharge_with_marginal_relief(
        p(40_00_000), tax, FY.surcharge_brackets, None, _slab_tax_fn(FY.old_regime_slabs_general))
    assert surcharge == 0


def test_surcharge_marginal_relief_just_above_50l():
    """Crossing ₹50L by ₹10,000 must not cost more than ₹10,000 in extra
    tax+surcharge -- the classic surcharge marginal-relief guarantee."""
    tax_at_threshold = slab_tax_paise(p(50_00_000), FY.old_regime_slabs_general)
    income = p(50_10_000)
    tax = slab_tax_paise(income, FY.old_regime_slabs_general)
    surcharge = apply_surcharge_with_marginal_relief(
        income, tax, FY.surcharge_brackets, None, _slab_tax_fn(FY.old_regime_slabs_general))
    total_at_threshold = tax_at_threshold  # no surcharge at/below 50L
    total_with_surcharge = tax + surcharge
    assert total_with_surcharge - total_at_threshold == p(10_000)


def test_surcharge_full_rate_far_above_threshold():
    """Well clear of the marginal-relief zone, surcharge is the plain bracket
    rate. Exactly ₹2,00,00,000 does not EXCEED the ₹2 Cr threshold, so the
    15% (>1 Cr) bracket applies here, not the 25% (>2 Cr) one."""
    tax = slab_tax_paise(p(2_00_00_000), FY.old_regime_slabs_general)  # 2 Cr
    surcharge = apply_surcharge_with_marginal_relief(
        p(2_00_00_000), tax, FY.surcharge_brackets, None, _slab_tax_fn(FY.old_regime_slabs_general))
    assert surcharge == tax * 15 // 100


def test_new_regime_surcharge_capped_at_25_percent_even_above_5cr():
    tax = slab_tax_paise(p(6_00_00_000), FY.new_regime_slabs)  # 6 Cr, would be 37% under old regime
    surcharge = apply_surcharge_with_marginal_relief(
        p(6_00_00_000), tax, FY.surcharge_brackets, FY.new_regime_surcharge_cap_percent,
        _slab_tax_fn(FY.new_regime_slabs))
    assert surcharge == tax * 25 // 100


def test_old_regime_surcharge_uncapped_37_percent_above_5cr():
    tax = slab_tax_paise(p(6_00_00_000), FY.old_regime_slabs_general)
    surcharge = apply_surcharge_with_marginal_relief(
        p(6_00_00_000), tax, FY.surcharge_brackets, None, _slab_tax_fn(FY.old_regime_slabs_general))
    assert surcharge == tax * 37 // 100


# ── Cess ──────────────────────────────────────────────────────────────────────

def test_cess_is_4_percent_of_tax_plus_surcharge():
    assert cess_paise(p(1_00_000), FY) == p(4_000)


def test_cess_never_negative():
    assert cess_paise(-500, FY) == 0
