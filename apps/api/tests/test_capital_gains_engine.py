"""
domain.income_tax.capital_gains_engine — unit tests against hand-worked
examples, cross-checked against the pre-existing frontend implementation
this module replaces (apps/web/app/income-tax/capital-gains/page.tsx).

Several expectations in here USED to pin behaviour the statute does not
support, and are corrected in place rather than deleted, because each one
records a real defect:

  * the whole file assumed the post-23-07-2024 rates applied to every
    transfer whatever its date. The Finance (No. 2) Act 2024 amended
    Sections 111A, 112A, 112, 2(42A) and the second proviso to Section 48
    for transfers made ON OR AFTER 23 July 2024 only, so a 2023 transfer of
    listed equity was charged 20%/12.5% when the law charged 15%/10%;
  * holding period was counted in whole calendar months, so an asset bought
    on 2 Jan 2024 and sold on 1 Jan 2025 — 364 days — came out long-term;
  * test_debt_mf_is_flagged_as_slab_rate_estimate asserted Section 50AA
    over a unit ACQUIRED in 2020 and sold in January 2023. Section 50AA
    reaches a unit "acquired on or after the 1st day of April, 2023" and
    did not exist on that sale date at all;
  * cii_for("2025-26") was pinned at 380, a figure with no source. CBDT
    Notification 70/2025 notifies 376.

All amounts in integer paise. L = ₹1,00,000 in paise.
"""
from datetime import date

import pytest

from domain.income_tax.capital_gains_engine import (
    compute_capital_gains, holding_months, is_long_term, long_term_threshold_months,
    cii_for, fy_for_date, CII_BY_FY, LATEST_CII_FY, FINANCE_NO2_ACT_2024,
    SECTION_50AA_FROM, ASSESSEE_RESIDENT_INDIVIDUAL_HUF, ASSESSEE_OTHER,
    ASSESSEE_UNSPECIFIED,
)

L = 100_000 * 100

# A transfer on either side of the Finance (No. 2) Act 2024 fork.
BEFORE = date(2024, 7, 22)
ON_OR_AFTER = date(2024, 7, 23)


# ── CII / FY helpers ──────────────────────────────────────────────────────────

def test_fy_for_date_before_april():
    assert fy_for_date(date(2025, 3, 31)) == "2024-25"


def test_fy_for_date_from_april():
    assert fy_for_date(date(2025, 4, 1)) == "2025-26"


def test_cii_2025_26_is_376_not_380():
    """CBDT Notification 70/2025 of 01-07-2025 notifies 376 for FY 2025-26.
    The table carried 380, which no source asserts."""
    assert cii_for("2025-26") == 376


def test_cii_2026_27_is_notified_and_present():
    """384, Notification 85/2026 — the table stopped at 2025-26, so every
    FY 2026-27 indexation silently used the previous year's index."""
    assert cii_for("2026-27") == 384


def test_latest_verified_cii_fy_is_not_moved_by_a_secondary_source():
    """Both new figures are secondary-sourced (no government host is
    reachable from this environment). Correcting a wrong value is right;
    moving the human-verified marker on the same evidence is the
    'silently promotes a guess to a verified figure' failure CLAUDE.md
    names, so the marker stays behind the table."""
    assert LATEST_CII_FY == "2025-26"


def test_cii_unknown_future_year_falls_back_to_the_newest_in_the_table():
    """And to the NEWEST ENTRY, not to the verification marker.

    THE REGRESSION THIS PINS. The fallback used to read LATEST_CII_FY, which is
    deliberately held behind the table (the test above). Once 2026-27 went in at
    384, `cii_for("2027-28")` answered **376** — older and LOWER than a figure
    the table already held. A lower index on the acquisition year shrinks the
    indexed cost, grows the gain and raises the tax, so a marker whose whole
    purpose is to stop a guess becoming a fact was changing a liability.
    """
    newest = max(CII_BY_FY)
    assert cii_for("2030-31") == CII_BY_FY[newest] == 384
    assert cii_for("2030-31") > CII_BY_FY[LATEST_CII_FY], (
        "the fallback must not be older than the table's own newest entry")
    # Every year in the table still answers itself — the fallback is only for
    # years that are not there.
    for fy, cii in CII_BY_FY.items():
        assert cii_for(fy) == cii, fy


# ── Holding-period classification (Section 2(42A)) ────────────────────────────

def test_equity_sold_exactly_twelve_months_later_is_still_short_term():
    """Section 2(42A) counts the period of holding to the date IMMEDIATELY
    PRECEDING the transfer, so a sale exactly 12 months after purchase is a
    holding of 12 months less a day and the asset is short-term. The whole
    calendar-month counter this replaces returned 12 and classified it
    long-term."""
    assert is_long_term("equity", date(2024, 1, 1), date(2025, 1, 1)) is False
    assert is_long_term("equity", date(2024, 1, 1), date(2025, 1, 2)) is True


def test_equity_one_day_short_of_twelve_months_is_short_term():
    """364 days. Bare month subtraction gave (2025-2024)*12 + (1-1) = 12."""
    assert is_long_term("equity", date(2024, 1, 2), date(2025, 1, 1)) is False
    r = compute_capital_gains("equity", date(2024, 1, 2), date(2025, 1, 1), 1 * L, 2 * L)
    assert r.is_long_term is False
    assert r.section_ref == "Section 111A"


def test_month_end_purchase_does_not_shift_the_boundary():
    """31 Jan + 12 months clamps to 31 Jan, not to 1 Feb."""
    assert is_long_term("equity", date(2024, 1, 31), date(2025, 1, 31)) is False
    assert is_long_term("equity", date(2024, 1, 31), date(2025, 2, 1)) is True


def test_other_assets_boundary_is_twenty_four_months_from_23_jul_2024():
    for t in ("property", "unlisted", "gold", "bonds", "other"):
        assert is_long_term(t, date(2023, 8, 1), date(2025, 8, 1)) is False   # exactly 24m
        assert is_long_term(t, date(2023, 8, 1), date(2025, 8, 2)) is True


def test_non_property_assets_needed_thirty_six_months_before_23_jul_2024():
    """Section 2(42A) knew a 36-month period for an asset that was neither a
    listed security nor immovable property until the Finance (No. 2) Act
    2024 collapsed it to 24. Applying 24 to a 2023 transfer called a
    two-year holding long-term when it was short-term."""
    for t in ("unlisted", "gold", "bonds", "other"):
        assert long_term_threshold_months(t, BEFORE) == 36
        assert long_term_threshold_months(t, ON_OR_AFTER) == 24
        assert is_long_term(t, date(2021, 1, 1), date(2023, 6, 1)) is False   # 29 months
        assert is_long_term(t, date(2020, 1, 1), date(2023, 6, 1)) is True    # 41 months


def test_immovable_property_kept_twenty_four_months_on_both_sides():
    assert long_term_threshold_months("property", BEFORE) == 24
    assert long_term_threshold_months("property", ON_OR_AFTER) == 24


def test_listed_equity_is_twelve_months_on_both_sides():
    for t in ("equity", "equity_shares", "mutual_funds"):
        assert long_term_threshold_months(t, BEFORE) == 12
        assert long_term_threshold_months(t, ON_OR_AFTER) == 12


def test_holding_months_counts_completed_months_of_the_holding_period():
    """1 Jan to 1 Jun is four completed months and thirty days, not five —
    the period of holding ends on 31 May."""
    assert holding_months(date(2024, 1, 1), date(2024, 6, 1)) == 4
    assert holding_months(date(2024, 1, 1), date(2024, 6, 2)) == 5
    assert holding_months(date(2020, 1, 1), date(2023, 1, 1)) == 35


@pytest.mark.parametrize("asset_type", ["equity", "property", "gold"])
@pytest.mark.parametrize(
    "purchase,sale",
    [
        (date(2024, 1, 1), date(2025, 1, 1)),
        (date(2024, 1, 1), date(2025, 1, 2)),
        (date(2021, 3, 15), date(2024, 3, 14)),
        (date(2021, 3, 15), date(2026, 3, 16)),
        (date(2020, 2, 29), date(2022, 2, 28)),
    ],
)
def test_display_month_count_and_classification_never_disagree(asset_type, purchase, sale):
    """The two used to be one function, then two; they must stay consistent
    or the UI shows '24 months' beside 'Short Term'."""
    expected = holding_months(purchase, sale) >= long_term_threshold_months(asset_type, sale)
    assert is_long_term(asset_type, purchase, sale) is expected


# ── Section 111A — STCG, listed equity ────────────────────────────────────────

def test_equity_stcg_is_15_percent_before_23_jul_2024():
    r = compute_capital_gains("equity", date(2024, 1, 1), date(2024, 6, 1), 1 * L, 1.5 * L)
    assert r.is_long_term is False
    assert r.section_ref == "Section 111A"
    assert r.tax_rate_percent == 15.0
    assert r.gain_paise == int(0.5 * L)
    assert r.tax_liability_paise == int(0.5 * L * 15 / 100)
    assert r.is_slab_rate_estimate is False


def test_equity_stcg_is_20_percent_from_23_jul_2024():
    r = compute_capital_gains("equity", date(2024, 5, 1), ON_OR_AFTER, 1 * L, 1.5 * L)
    assert r.tax_rate_percent == 20.0
    assert r.tax_liability_paise == int(0.5 * L * 20 / 100)


def test_equity_stcg_rate_switches_exactly_on_23_jul_2024():
    before = compute_capital_gains("equity", date(2024, 1, 1), BEFORE, 1 * L, 1.5 * L)
    on = compute_capital_gains("equity", date(2024, 1, 1), ON_OR_AFTER, 1 * L, 1.5 * L)
    assert (before.tax_rate_percent, on.tax_rate_percent) == (15.0, 20.0)


def test_equity_shares_register_type_gets_same_treatment_as_equity():
    """R3.1b fix: the register's coarser 'equity_shares'/'mutual_funds' asset
    types must resolve to the identical 111A/112A treatment as the
    calculator's 'equity' type -- proving the unification didn't silently
    diverge behavior for the register's own vocabulary."""
    a = compute_capital_gains("equity", date(2024, 1, 1), date(2024, 6, 1), 1 * L, 1.5 * L)
    b = compute_capital_gains("equity_shares", date(2024, 1, 1), date(2024, 6, 1), 1 * L, 1.5 * L)
    c = compute_capital_gains("mutual_funds", date(2024, 1, 1), date(2024, 6, 1), 1 * L, 1.5 * L)
    assert a.tax_rate_percent == b.tax_rate_percent == c.tax_rate_percent == 15.0
    assert a.tax_liability_paise == b.tax_liability_paise == c.tax_liability_paise


# ── Section 112A — LTCG, listed equity ───────────────────────────────────────

def test_equity_ltcg_below_exemption_is_zero_tax():
    r = compute_capital_gains("equity", date(2020, 1, 1), date(2023, 1, 2), 1 * L, int(1.8 * L))
    assert r.is_long_term is True
    assert r.section_ref == "Section 112A"
    assert r.gain_paise == int(0.8 * L)  # below the ₹1,00,000 exemption then in force
    assert r.tax_liability_paise == 0


def test_equity_ltcg_before_23_jul_2024_is_10_percent_over_1_lakh():
    """Section 112A charged 10% over ₹1,00,000 until the Finance (No. 2) Act
    2024 made it 12.5% over ₹1,25,000. Both the rate and the exemption were
    being applied to transfers years before either existed."""
    r = compute_capital_gains("equity", date(2020, 1, 1), date(2023, 1, 2), 1 * L, 4 * L)
    assert r.gain_paise == 3 * L
    assert r.tax_rate_percent == 10.0
    assert r.tax_liability_paise == round((3 * L - 100_000_00) * 10 / 100)


def test_equity_ltcg_from_23_jul_2024_is_12_5_percent_over_1_25_lakh():
    r = compute_capital_gains("equity", date(2020, 1, 1), ON_OR_AFTER, 1 * L, 4 * L)
    assert r.tax_rate_percent == 12.5
    assert r.tax_liability_paise == round((3 * L - 125_000_00) * 125 / 1000)


def test_equity_ltcg_exemption_switches_exactly_on_23_jul_2024():
    """A gain of ₹1,10,000 is fully exempt from 23-07-2024 and taxable
    before it — the clearest single number separating the two ceilings."""
    gain = int(1.1 * L)
    before = compute_capital_gains("equity", date(2020, 1, 1), BEFORE, 1 * L, 1 * L + gain)
    on = compute_capital_gains("equity", date(2020, 1, 1), ON_OR_AFTER, 1 * L, 1 * L + gain)
    assert before.tax_liability_paise == round((gain - 100_000_00) * 10 / 100)
    assert on.tax_liability_paise == 0


# ── Section 50AA — debt mutual funds ─────────────────────────────────────────

def test_debt_mf_acquired_from_1_apr_2023_is_the_50aa_slab_rate_estimate():
    r = compute_capital_gains("debt_mf", SECTION_50AA_FROM, date(2025, 6, 1), 1 * L, 2 * L)
    assert r.tax_rate_percent == 30.0
    assert r.is_slab_rate_estimate is True
    assert r.section_ref.startswith("Section 50AA")


def test_debt_mf_acquired_before_1_apr_2023_is_not_reached_by_50aa():
    """The test this replaces asserted Section 50AA over a unit bought on
    1 Jan 2020 and sold on 1 Jan 2023 — the section reaches a unit
    'acquired on or after the 1st day of April, 2023' and had not commenced
    on that sale date at all. Such a unit is an ordinary capital asset: held
    exactly 36 months to 1 Jan 2023 it is SHORT-term (the 36-month period
    then in force is a threshold to exceed), so it lands at slab rate for a
    completely different reason — under Section 48, not Section 50AA."""
    r = compute_capital_gains("debt_mf", date(2020, 1, 1), date(2023, 1, 1), 1 * L, 2 * L)
    assert r.section_ref == "Section 48"
    assert "50AA" not in r.section_ref
    assert r.is_long_term is False
    assert r.is_slab_rate_estimate is True
    assert "Section 50AA does not reach it" in r.note


def test_old_debt_mf_held_long_enough_gets_section_112_not_slab_rate():
    """Same unit, one day longer: 36 months and a day is long-term, and a
    pre-23-07-2024 transfer of it is charged 20% WITH indexation. Section
    50AA would have charged slab rate on the whole gain."""
    r = compute_capital_gains("debt_mf", date(2020, 1, 1), date(2023, 1, 2), 1 * L, 4 * L)
    assert r.is_long_term is True
    assert r.section_ref == "Section 112"
    assert r.tax_rate_percent == 20.0
    assert r.is_slab_rate_estimate is False


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


def test_non_property_ltcg_from_23_jul_2024_is_flat_12_5_no_indexation_choice():
    """R3.1b fix: the pre-existing register logic hardcoded 20% for every
    non-equity LTCG asset type, never computing the 12.5% flat alternative
    at all. Unlisted/gold/bonds/other must get 12.5% flat with NO indexation
    choice (only immovable property gets that choice) — for a transfer from
    23-07-2024, which is when the 12.5% rate begins."""
    for t in ("unlisted", "gold", "bonds", "other"):
        r = compute_capital_gains(t, date(2020, 1, 1), date(2025, 6, 1), 1 * L, 4 * L)
        assert r.tax_rate_percent == 12.5
        assert r.tax_with_indexation_percent is None
        assert r.tax_liability_paise == round(3 * L * 125 / 1000)


def test_non_property_ltcg_before_23_jul_2024_is_20_percent_with_indexation():
    """Indexation was MANDATORY under the second proviso to Section 48 for a
    transfer before 23-07-2024, not an option — so the tax is 20% of the
    indexed gain, and there is no lower-of comparison to offer."""
    r = compute_capital_gains("gold", date(2010, 6, 1), date(2023, 6, 1), 10 * L, 50 * L)
    assert r.is_long_term is True
    assert r.section_ref == "Section 112"
    assert r.tax_rate_percent == 20.0
    assert r.tax_with_indexation_percent is None
    # FY 2010-11 CII 167 -> FY 2023-24 CII 348.
    indexed_cost = round(10 * L * 348 / 167)
    assert r.indexed_cost_paise == indexed_cost
    assert r.tax_liability_paise == round((50 * L - indexed_cost) * 20 / 100)


def test_property_ltcg_offers_indexation_choice_and_flat_wins_for_large_real_gain():
    """A gain much larger than plausible CII-driven inflation -> the flat
    12.5% (lower absolute rate) beats 20% with indexation, even though
    indexation reduces the taxable base."""
    r = compute_capital_gains(
        "property", date(2023, 6, 1), date(2025, 8, 1), 10 * L, 50 * L,
        assessee_type=ASSESSEE_RESIDENT_INDIVIDUAL_HUF,
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
    r = compute_capital_gains(
        "property", date(2023, 6, 1), date(2025, 8, 1), 10 * L, 50 * L,
        assessee_type=ASSESSEE_RESIDENT_INDIVIDUAL_HUF,
    )
    assert r.tax_without_indexation_paise == round(max(0, r.gain_paise) * 125 / 1000)
    assert r.tax_with_indexation_paise == round(max(0, r.gain_with_indexation_paise) * 20 / 100)
    assert r.tax_liability_paise == min(r.tax_without_indexation_paise, r.tax_with_indexation_paise)


def test_non_property_has_no_with_indexation_amount():
    r = compute_capital_gains("gold", date(2020, 1, 1), date(2025, 6, 1), 1 * L, 4 * L)
    assert r.tax_with_indexation_paise is None
    assert r.tax_without_indexation_paise == r.tax_liability_paise


def test_property_ltcg_indexation_wins_for_long_holding_with_high_cii_ratio():
    """A long holding period spanning a large CII ratio (FY2001-02 CII=100
    to FY2025-26 CII=376) with a moderate real gain -> indexation shrinks
    the taxable base enough that 20% on the indexed gain beats 12.5% on the
    un-indexed gain. 100 -> 376 divides exactly, so no rounding is in play."""
    r = compute_capital_gains(
        "property", date(2001, 6, 1), date(2025, 6, 1), 10 * L, 50 * L,
        assessee_type=ASSESSEE_RESIDENT_INDIVIDUAL_HUF,
    )
    assert r.holding_months == 287       # 23 years 11 months and 30 days
    assert r.indexed_cost_paise == round(37.6 * L)   # 10L * 376/100, exact
    assert r.gain_with_indexation_paise == round(12.4 * L)  # 50L - 37.6L
    tax_flat = round(40 * L * 125 / 1000)      # gain_paise = 50L-10L = 40L
    tax_indexed = round(12.4 * L * 20 / 100)
    assert tax_indexed < tax_flat
    assert r.tax_liability_paise == tax_indexed
    assert r.tax_rate_percent == 12.5
    assert r.tax_with_indexation_percent == 20.0


# ── The fifth proviso to Section 112(1) is not open to everyone ─────────────

def test_grandfathered_indexation_option_is_refused_to_a_company_or_llp():
    """The fifth proviso to Section 112(1) caps the tax at 20% with
    indexation only for a RESIDENT INDIVIDUAL or HUF. A company, an LLP, a
    firm and a non-resident pay the flat 12.5%. The option used to be handed
    to every caller because nothing recorded who the assessee was."""
    args = ("property", date(2001, 6, 1), date(2025, 6, 1), 10 * L, 50 * L)
    eligible = compute_capital_gains(*args, assessee_type=ASSESSEE_RESIDENT_INDIVIDUAL_HUF)
    company = compute_capital_gains(*args, assessee_type=ASSESSEE_OTHER)
    assert eligible.tax_liability_paise < company.tax_liability_paise
    assert company.tax_liability_paise == company.tax_without_indexation_paise
    # Both candidate figures stay visible so a CA can see what was refused.
    assert company.tax_with_indexation_paise == eligible.tax_liability_paise
    assert "resident individual or HUF" in company.note


def test_unstated_assessee_type_does_not_get_the_option_but_is_told_so():
    """No caller supplies the assessee's status today, so the default must
    be the direction that cannot under-tax — and it must say why."""
    r = compute_capital_gains(
        "property", date(2001, 6, 1), date(2025, 6, 1), 10 * L, 50 * L,
        assessee_type=ASSESSEE_UNSPECIFIED,
    )
    assert r.tax_liability_paise == r.tax_without_indexation_paise
    assert "State it to claim the option" in r.note


def test_default_assessee_type_is_the_unspecified_one():
    explicit = compute_capital_gains(
        "property", date(2001, 6, 1), date(2025, 6, 1), 10 * L, 50 * L,
        assessee_type=ASSESSEE_UNSPECIFIED,
    )
    default = compute_capital_gains("property", date(2001, 6, 1), date(2025, 6, 1), 10 * L, 50 * L)
    assert default.tax_liability_paise == explicit.tax_liability_paise


def test_property_acquired_after_the_cutoff_gets_no_indexation_option_at_all():
    """The proviso grandfathers property ACQUIRED before 23-07-2024. Bought
    after it, there is nothing to grandfather — flat 12.5% and no
    alternative rate, even for a resident individual."""
    r = compute_capital_gains(
        "property", ON_OR_AFTER, date(2027, 6, 1), 10 * L, 50 * L,
        assessee_type=ASSESSEE_RESIDENT_INDIVIDUAL_HUF,
    )
    assert r.is_long_term is True
    assert r.tax_rate_percent == 12.5
    assert r.tax_with_indexation_percent is None
    assert r.tax_with_indexation_paise is None


def test_property_transferred_before_the_cutoff_is_20_percent_with_indexation():
    """Not the same thing as the grandfathered option: before 23-07-2024
    indexation was mandatory for everybody, with no 12.5% alternative."""
    r = compute_capital_gains(
        "property", date(2015, 6, 1), BEFORE, 10 * L, 50 * L,
        assessee_type=ASSESSEE_RESIDENT_INDIVIDUAL_HUF,
    )
    assert r.tax_rate_percent == 20.0
    assert r.tax_with_indexation_percent is None
    indexed_cost = round(10 * L * 363 / 254)   # FY 2015-16 CII 254 -> FY 2024-25 CII 363
    assert r.indexed_cost_paise == indexed_cost
    assert r.tax_liability_paise == round((50 * L - indexed_cost) * 20 / 100)


def test_the_fork_date_constant_is_23_july_2024():
    assert FINANCE_NO2_ACT_2024 == date(2024, 7, 23)


# ── Integer-only arithmetic ────────────────────────────────────────────────────

def test_all_paise_amounts_are_integers():
    r = compute_capital_gains("property", date(2001, 6, 1), date(2025, 6, 1), 10 * L, 50 * L, 1 * L)
    for v in (r.gain_paise, r.indexed_cost_paise, r.gain_with_indexation_paise, r.tax_liability_paise):
        assert isinstance(v, int)
