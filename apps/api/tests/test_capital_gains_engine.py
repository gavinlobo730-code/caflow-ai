"""
domain.income_tax.capital_gains_engine — unit tests against hand-worked
examples, cross-checked against the pre-existing frontend implementation
this module replaces (apps/web/app/income-tax/capital-gains/page.tsx).

All amounts in integer paise. L = ₹1,00,000 in paise.
"""
from datetime import date

from domain.income_tax.capital_gains_engine import (
    compute_capital_gains, holding_months, is_long_term, cii_for, fy_for_date,
    CII_BY_FY, LATEST_CII_FY,
)

L = 100_000 * 100


# ── CII / FY helpers ──────────────────────────────────────────────────────────

def test_fy_for_date_before_april():
    assert fy_for_date(date(2025, 3, 31)) == "2024-25"


def test_fy_for_date_from_april():
    assert fy_for_date(date(2025, 4, 1)) == "2025-26"


def test_cii_known_year():
    assert cii_for("2025-26") == 380


def test_cii_unknown_future_year_falls_back_to_latest():
    assert cii_for("2030-31") == CII_BY_FY[LATEST_CII_FY]


# ── Holding-period classification (Section 2(42A)) ────────────────────────────

def test_equity_12_months_is_long_term_boundary():
    assert is_long_term("equity", 12) is True
    assert is_long_term("equity", 11) is False


def test_other_assets_24_months_is_long_term_boundary():
    for t in ("property", "unlisted", "gold", "bonds", "other"):
        assert is_long_term(t, 24) is True
        assert is_long_term(t, 23) is False


def test_holding_months_counts_whole_months():
    assert holding_months(date(2024, 1, 1), date(2024, 6, 1)) == 5
    assert holding_months(date(2020, 1, 1), date(2023, 1, 1)) == 36


# ── Section 111A — STCG, listed equity ────────────────────────────────────────

def test_equity_stcg_20_percent():
    r = compute_capital_gains("equity", date(2024, 1, 1), date(2024, 6, 1), 1 * L, 1.5 * L)
    assert r.is_long_term is False
    assert r.section_ref == "Section 111A"
    assert r.tax_rate_percent == 20.0
    assert r.gain_paise == int(0.5 * L)
    assert r.tax_liability_paise == int(0.5 * L * 20 / 100)
    assert r.is_slab_rate_estimate is False


def test_equity_shares_register_type_gets_same_treatment_as_equity():
    """R3.1b fix: the register's coarser 'equity_shares'/'mutual_funds' asset
    types must resolve to the identical 111A/112A treatment as the
    calculator's 'equity' type -- proving the unification didn't silently
    diverge behavior for the register's own vocabulary."""
    a = compute_capital_gains("equity", date(2024, 1, 1), date(2024, 6, 1), 1 * L, 1.5 * L)
    b = compute_capital_gains("equity_shares", date(2024, 1, 1), date(2024, 6, 1), 1 * L, 1.5 * L)
    c = compute_capital_gains("mutual_funds", date(2024, 1, 1), date(2024, 6, 1), 1 * L, 1.5 * L)
    assert a.tax_rate_percent == b.tax_rate_percent == c.tax_rate_percent == 20.0
    assert a.tax_liability_paise == b.tax_liability_paise == c.tax_liability_paise


# ── Section 112A — LTCG, listed equity, ₹1.25L exemption ─────────────────────

def test_equity_ltcg_below_exemption_is_zero_tax():
    r = compute_capital_gains("equity", date(2020, 1, 1), date(2023, 1, 1), 1 * L, 2 * L)
    assert r.is_long_term is True
    assert r.section_ref == "Section 112A"
    assert r.gain_paise == 1 * L  # below the 1.25L exemption
    assert r.tax_liability_paise == 0


def test_equity_ltcg_above_exemption_taxed_on_excess_only():
    r = compute_capital_gains("equity", date(2020, 1, 1), date(2023, 1, 1), 1 * L, 4 * L)
    assert r.gain_paise == 3 * L
    taxable = 3 * L - 125_000_00
    assert r.tax_rate_percent == 12.5
    assert r.tax_liability_paise == round(taxable * 125 / 1000)


# ── Section 50AA — debt mutual funds (slab-rate estimate) ─────────────────────

def test_debt_mf_is_flagged_as_slab_rate_estimate():
    r = compute_capital_gains("debt_mf", date(2020, 1, 1), date(2023, 1, 1), 1 * L, 2 * L)
    assert r.tax_rate_percent == 30.0
    assert r.is_slab_rate_estimate is True
    assert r.section_ref.startswith("Section 50AA")


# ── Section 115BBH — VDA/crypto, flat regardless of holding period ───────────

def test_vda_flat_30_percent_regardless_of_short_or_long_term():
    short = compute_capital_gains("vda", date(2024, 1, 1), date(2024, 6, 1), 1 * L, 2 * L)
    long = compute_capital_gains("vda", date(2020, 1, 1), date(2023, 1, 1), 1 * L, 2 * L)
    assert short.tax_rate_percent == long.tax_rate_percent == 30.0
    assert short.tax_liability_paise == long.tax_liability_paise == round(1 * L * 30 / 100)
    assert short.is_slab_rate_estimate is False


# ── Section 112 — other assets (property/unlisted/gold/bonds/other) ─────────

def test_other_asset_stcg_is_flagged_slab_rate_estimate():
    for t in ("property", "unlisted", "gold", "bonds", "other"):
        r = compute_capital_gains(t, date(2024, 1, 1), date(2024, 6, 1), 1 * L, 2 * L)
        assert r.is_long_term is False
        assert r.tax_rate_percent == 30.0
        assert r.is_slab_rate_estimate is True


def test_non_property_ltcg_is_flat_12_5_no_indexation_choice():
    """R3.1b fix: the pre-existing register logic hardcoded 20% for every
    non-equity LTCG asset type, never computing the 12.5% flat alternative
    at all. Unlisted/gold/bonds/other must now correctly get 12.5% flat with
    NO indexation choice (only immovable property gets that choice)."""
    for t in ("unlisted", "gold", "bonds", "other"):
        r = compute_capital_gains(t, date(2020, 1, 1), date(2023, 1, 1), 1 * L, 4 * L)
        assert r.tax_rate_percent == 12.5
        assert r.tax_with_indexation_percent is None
        assert r.tax_liability_paise == round(3 * L * 125 / 1000)


def test_property_ltcg_offers_indexation_choice_and_flat_wins_for_large_real_gain():
    """A gain much larger than plausible CII-driven inflation -> the flat
    12.5% (lower absolute rate) beats 20% with indexation, even though
    indexation reduces the taxable base."""
    r = compute_capital_gains(
        "property", date(2023, 6, 1), date(2025, 8, 1), 10 * L, 50 * L,
    )
    assert r.is_long_term is True
    assert r.tax_rate_percent == 12.5
    assert r.tax_with_indexation_percent == 20.0
    tax_flat = round(max(0, r.gain_paise) * 125 / 1000)
    tax_indexed = round(max(0, r.gain_with_indexation_paise) * 20 / 100)
    assert tax_flat < tax_indexed
    assert r.tax_liability_paise == tax_flat


def test_property_ltcg_exposes_both_explicit_tax_amounts_not_just_the_final_one():
    """Callers must never have to re-derive tax_rate_percent * gain_paise
    themselves (a float re-computation that could round differently from
    the engine's own integer round-half-up) -- both candidate amounts are
    exposed explicitly."""
    r = compute_capital_gains("property", date(2023, 6, 1), date(2025, 8, 1), 10 * L, 50 * L)
    assert r.tax_without_indexation_paise == round(max(0, r.gain_paise) * 125 / 1000)
    assert r.tax_with_indexation_paise == round(max(0, r.gain_with_indexation_paise) * 20 / 100)
    assert r.tax_liability_paise == min(r.tax_without_indexation_paise, r.tax_with_indexation_paise)


def test_non_property_has_no_with_indexation_amount():
    r = compute_capital_gains("gold", date(2020, 1, 1), date(2023, 1, 1), 1 * L, 4 * L)
    assert r.tax_with_indexation_paise is None
    assert r.tax_without_indexation_paise == r.tax_liability_paise


def test_property_ltcg_indexation_wins_for_long_holding_with_high_cii_ratio():
    """A long holding period spanning a large CII ratio (FY2001-02 CII=100
    to FY2025-26 CII=380, an exact 3.8x with no rounding) with a moderate
    real gain -> indexation shrinks the taxable base enough that 20% on the
    indexed gain beats 12.5% on the un-indexed gain."""
    r = compute_capital_gains(
        "property", date(2001, 6, 1), date(2025, 6, 1), 10 * L, 50 * L,
    )
    assert r.holding_months == 288
    assert r.indexed_cost_paise == 38 * L  # 10L * 380/100, exact, no rounding
    assert r.gain_with_indexation_paise == 12 * L  # 50L - 38L
    tax_flat = round(40 * L * 125 / 1000)      # gain_paise = 50L-10L = 40L
    tax_indexed = round(12 * L * 20 / 100)
    assert tax_indexed < tax_flat
    assert r.tax_liability_paise == tax_indexed
    assert r.tax_rate_percent == 12.5
    assert r.tax_with_indexation_percent == 20.0


# ── Integer-only arithmetic ────────────────────────────────────────────────────

def test_all_paise_amounts_are_integers():
    r = compute_capital_gains("property", date(2001, 6, 1), date(2025, 6, 1), 10 * L, 50 * L, 1 * L)
    for v in (r.gain_paise, r.indexed_cost_paise, r.gain_with_indexation_paise, r.tax_liability_paise):
        assert isinstance(v, int)
