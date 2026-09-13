"""Sections 54, 54B, 54EC and 54F — the reinvestment exemption (IT-19).

WHAT WAS WRONG
    `capital_gains_engine` computed the gain, the holding period and the rate
    and stopped, and there was nowhere in the product to record that the money
    had gone back into a new asset. On a house sale the whole of that gain is
    routinely exempt under s.54, so the tax the register showed was the tax on
    a gain the client may not owe tax on at all.

WHAT IS PINNED HERE
    The four sections' arithmetic and the ways they DIFFER, because that is
    where this goes wrong: s.54F apportions on net consideration where s.54
    takes the lower of two amounts, s.54EC's Rs 50 lakh spans two financial
    years rather than one, and s.54B is the only one a short-term gain
    reaches. Every refusal, in both directions — a section that does not reach
    the asset, a claim outside its window, and each of the three facts no
    ledger holds. And that nothing exempts more gain than there was, however
    many claims sit against one transfer.

⚠️ EVERY FIGURE AND WINDOW IS `[S]`-GRADED — direct egress is refused at this
    environment's proxy, incometax.gov.in included, so none of it was read
    against the bare Act. The tests below assert the constants EXACTLY, so a
    correction is one edit and shows up as a deliberate change.
"""
from __future__ import annotations

import inspect
import re
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException

import routers.income_tax as it
import services.capital_gain_exemption_service as cgx
from domain.income_tax import reinvestment_exemption as rex

_API = Path(__file__).resolve().parent.parent
_MIG = _API / "migrations"

TRANSFER = date(2025, 6, 10)


def _claim(section: str, **kw) -> rex.Reinvestment:
    base = dict(cost_paise=0, acquisition_kind="purchase",
                acquisition_date=date(2025, 9, 1), description="New asset")
    base.update(kw)
    return rex.Reinvestment(section=section, **base)


def _compute(**kw) -> rex.ExemptionResult:
    """A Rs 1 crore transfer with a Rs 40 lakh gain, long-term, land or
    building, by an individual."""
    base = dict(
        gain_paise=40_00_000 * 100,
        net_consideration_paise=1_00_00_000 * 100,
        transfer_date=TRANSFER,
        is_long_term=True,
        transferred_asset_nature=rex.NATURE_LAND_OR_BUILDING,
        assessee_is_individual_or_huf=True,
        reinvestments=(),
    )
    base.update(kw)
    return rex.compute_exemption(**base)


# ══ the figures, asserted exactly ════════════════════════════════════════════

def test_the_statutory_figures_are_what_they_are():
    assert rex.SECTION_54EC_CAP_PAISE == 50_00_000 * 100
    assert rex.SECTION_54_54F_COST_CEILING_PAISE == 10_00_00_000 * 100
    assert rex.SECTION_54_TWO_HOUSE_GAIN_LIMIT_PAISE == 2_00_00_000 * 100
    assert rex.SECTION_54EC_WINDOW_MONTHS == 6
    assert rex.SECTION_54EC_LOCK_IN_YEARS == 5
    assert rex.SECTION_54EC_LAND_OR_BUILDING_FROM == date(2018, 4, 1)
    assert rex.SECTION_54_54F_COST_CEILING_FIRST_FY == "2023-24"


@pytest.mark.parametrize("section,before,after,construction", [
    ("54", 12, 24, 36),
    ("54B", None, 24, None),
    ("54EC", None, 6, None),
    ("54F", 12, 24, 36),
])
def test_each_sections_windows(section, before, after, construction):
    r = rex.RULES[section]
    assert r.purchase_before_months == before
    assert r.purchase_after_months == after
    assert r.construction_after_months == construction


def test_the_module_says_every_figure_is_unverified():
    """The house rule for anything not read off a primary source. Egress is
    refused here, so a reader must be told that before relying on a number."""
    doc = rex.__doc__ or ""
    assert "[S]" in doc
    assert "egress" in doc.lower()


# ══ s.54 — the lower of two amounts ══════════════════════════════════════════

def test_s54_exempts_the_lower_of_the_gain_and_the_cost():
    r = _compute(
        transferred_asset_nature=rex.NATURE_RESIDENTIAL_HOUSE,
        reinvestments=(_claim("54", cost_paise=25_00_000 * 100),))
    assert r.total_exemption_paise == 25_00_000 * 100
    assert r.taxable_gain_paise == 15_00_000 * 100


def test_s54_never_exempts_more_than_the_gain():
    r = _compute(
        transferred_asset_nature=rex.NATURE_RESIDENTIAL_HOUSE,
        reinvestments=(_claim("54", cost_paise=90_00_000 * 100),))
    assert r.total_exemption_paise == 40_00_000 * 100
    assert r.taxable_gain_paise == 0


def test_s54_does_not_reach_a_sale_that_was_not_a_residential_house():
    r = _compute(reinvestments=(_claim("54", cost_paise=40_00_000 * 100),))
    assert r.total_exemption_paise == 0
    assert any("does not reach" in g for g in r.claims[0].gaps)


# ══ s.54F — PROPORTIONATE, and this is the one that gets confused with s.54 ══

def test_s54F_apportions_on_net_consideration_and_is_not_the_lower_of_two():
    """A Rs 1 crore sale, a Rs 40 lakh gain and a Rs 50 lakh house. s.54's
    rule would exempt Rs 40 lakh; s.54F exempts Rs 20 lakh. Applying the wrong
    one halves the tax."""
    r = _compute(reinvestments=(
        _claim("54F", cost_paise=50_00_000 * 100, other_residential_houses_owned=0),))
    assert r.total_exemption_paise == 20_00_000 * 100
    assert r.taxable_gain_paise == 20_00_000 * 100
    assert any("PROPORTIONATE" in w for w in r.claims[0].working)


def test_s54F_exempts_the_whole_gain_when_the_cost_reaches_the_net_consideration():
    r = _compute(reinvestments=(
        _claim("54F", cost_paise=1_00_00_000 * 100, other_residential_houses_owned=1),))
    assert r.total_exemption_paise == 40_00_000 * 100


def test_s54F_refuses_where_how_many_other_houses_is_not_recorded():
    """A fact no ledger holds. Blank is a THIRD state and must not read as
    zero — zero would assert the assessee owned none."""
    r = _compute(reinvestments=(_claim("54F", cost_paise=50_00_000 * 100),))
    assert r.total_exemption_paise == 0
    assert any("MORE THAN ONE" in g for g in r.claims[0].gaps)


def test_s54F_is_refused_where_two_other_houses_were_owned():
    r = _compute(reinvestments=(
        _claim("54F", cost_paise=50_00_000 * 100, other_residential_houses_owned=2),))
    assert r.total_exemption_paise == 0
    assert any("at most one" in g for g in r.claims[0].gaps)


def test_s54F_does_not_reach_the_sale_of_a_residential_house():
    r = _compute(
        transferred_asset_nature=rex.NATURE_RESIDENTIAL_HOUSE,
        reinvestments=(_claim("54F", cost_paise=50_00_000 * 100,
                              other_residential_houses_owned=0),))
    assert r.total_exemption_paise == 0


def test_the_s54F_fraction_is_floored():
    """The exemption is what tax is NOT charged on, so a rounding that grows
    it grows the shortfall the client pays s.234B interest on."""
    r = rex.compute_exemption(
        gain_paise=100, net_consideration_paise=3, transfer_date=TRANSFER,
        is_long_term=True, transferred_asset_nature=rex.NATURE_OTHER,
        assessee_is_individual_or_huf=True,
        reinvestments=(_claim("54F", cost_paise=1, other_residential_houses_owned=0),))
    assert r.total_exemption_paise == 33  # 100 x 1 / 3 = 33.33 -> 33


# ══ s.54EC — the cap, and the six-month window ═══════════════════════════════

def test_s54EC_is_capped_at_fifty_lakh():
    r = _compute(reinvestments=(
        _claim("54EC", cost_paise=80_00_000 * 100, acquisition_kind="bonds",
               acquisition_date=date(2025, 9, 1)),))
    # The gain is Rs 40 lakh, so the cap is not what binds here — the gain is.
    assert r.total_exemption_paise == 40_00_000 * 100
    assert r.claims[0].amount_considered_paise == 50_00_000 * 100


def test_the_fifty_lakh_cap_binds_on_a_larger_gain():
    r = _compute(gain_paise=80_00_000 * 100, reinvestments=(
        _claim("54EC", cost_paise=80_00_000 * 100, acquisition_kind="bonds",
               acquisition_date=date(2025, 9, 1)),))
    assert r.total_exemption_paise == 50_00_000 * 100


def test_the_fifty_lakh_cap_says_it_spans_two_financial_years():
    """The second proviso applies it to the year of transfer AND the year
    after it together. Reading it as Rs 50 lakh a year doubles the
    exemption."""
    r = _compute(reinvestments=(
        _claim("54EC", cost_paise=10_00_000 * 100, acquisition_kind="bonds",
               acquisition_date=date(2025, 9, 1)),))
    assert any("year of transfer and the following one together" in c
               for c in r.claims[0].caveats)


def test_a_bond_bought_after_six_months_is_refused():
    r = _compute(reinvestments=(
        _claim("54EC", cost_paise=10_00_000 * 100, acquisition_kind="bonds",
               acquisition_date=date(2026, 1, 5)),))
    assert r.total_exemption_paise == 0
    assert r.claims[0].deadline == date(2025, 12, 10)
    assert r.claims[0].within_time is False


def test_s54EC_reached_any_long_term_asset_before_the_finance_act_2018():
    """A belated or revised return for such a year is still filed at the law
    of that year — the same fork shape as the 23-07-2024 capital-gains fork."""
    r = rex.compute_exemption(
        gain_paise=40_00_000 * 100, net_consideration_paise=1_00_00_000 * 100,
        transfer_date=date(2017, 6, 10), is_long_term=True,
        transferred_asset_nature=rex.NATURE_OTHER,
        assessee_is_individual_or_huf=True,
        reinvestments=(rex.Reinvestment(
            section="54EC", cost_paise=10_00_000 * 100, acquisition_kind="bonds",
            acquisition_date=date(2017, 9, 1)),))
    assert r.total_exemption_paise == 10_00_000 * 100
    assert any("01-04-2018" in c for c in r.claims[0].caveats)


@pytest.mark.parametrize("nature", [rex.NATURE_LAND_OR_BUILDING,
                                    rex.NATURE_RESIDENTIAL_HOUSE,
                                    rex.NATURE_AGRICULTURAL_LAND])
def test_s54EC_reaches_everything_that_is_land_or_building(nature):
    """A residential house is a building and agricultural land is land. Rural
    agricultural land is not a capital asset at all (s.2(14)(iii)) so no gain
    arises on it, but urban agricultural land is — and leaving either out
    would refuse an exemption the section gives."""
    r = _compute(transferred_asset_nature=nature, reinvestments=(
        _claim("54EC", cost_paise=10_00_000 * 100, acquisition_kind="bonds",
               acquisition_date=date(2025, 9, 1)),))
    assert r.total_exemption_paise == 10_00_000 * 100, r.claims[0].gaps


def test_s54EC_does_not_reach_shares_after_the_finance_act_2018():
    r = _compute(transferred_asset_nature=rex.NATURE_OTHER, reinvestments=(
        _claim("54EC", cost_paise=10_00_000 * 100, acquisition_kind="bonds",
               acquisition_date=date(2025, 9, 1)),))
    assert r.total_exemption_paise == 0


def test_s54EC_reaches_any_assessee():
    """The one section in this family with no individual-or-HUF limb — a
    company selling a building gets it."""
    r = _compute(assessee_is_individual_or_huf=False, reinvestments=(
        _claim("54EC", cost_paise=10_00_000 * 100, acquisition_kind="bonds",
               acquisition_date=date(2025, 9, 1)),))
    assert r.total_exemption_paise == 10_00_000 * 100


def test_s54EC_has_no_capital_gains_accounts_scheme_limb():
    """The section requires the bonds themselves inside six months, and a
    deposit is not a subscription."""
    r = _compute(reinvestments=(
        _claim("54EC", cost_paise=0, acquisition_kind="bonds",
               acquisition_date=date(2025, 9, 1),
               cgas_deposit_paise=10_00_000 * 100,
               cgas_deposit_date=date(2025, 7, 1)),))
    assert r.total_exemption_paise == 0
    assert any("no Capital Gains Accounts Scheme limb" in g for g in r.claims[0].gaps)


# ══ s.54B — the short-term one ═══════════════════════════════════════════════

def test_s54B_reaches_a_short_term_gain():
    """Its charging words describe the USE of the land in the two preceding
    years, not a holding period. Treating it like its neighbours refuses a
    claim the Act allows."""
    r = _compute(
        is_long_term=False,
        transferred_asset_nature=rex.NATURE_AGRICULTURAL_LAND,
        reinvestments=(_claim("54B", cost_paise=25_00_000 * 100,
                              agricultural_use_two_years=True),))
    assert r.total_exemption_paise == 25_00_000 * 100


@pytest.mark.parametrize("section", ["54", "54EC", "54F"])
def test_every_other_section_refuses_a_short_term_gain(section):
    r = _compute(
        is_long_term=False,
        transferred_asset_nature=rex.NATURE_LAND_OR_BUILDING,
        reinvestments=(_claim(section, cost_paise=25_00_000 * 100,
                              other_residential_houses_owned=0,
                              acquisition_kind="bonds" if section == "54EC" else "purchase"),))
    assert r.total_exemption_paise == 0
    assert any("LONG-TERM" in g for g in r.claims[0].gaps)


def test_s54B_refuses_where_the_agricultural_use_is_not_recorded():
    r = _compute(
        transferred_asset_nature=rex.NATURE_AGRICULTURAL_LAND,
        reinvestments=(_claim("54B", cost_paise=25_00_000 * 100),))
    assert r.total_exemption_paise == 0
    assert any("two years immediately preceding" in g for g in r.claims[0].gaps)


# ══ the facts nobody holds ═══════════════════════════════════════════════════

def test_an_unrecorded_asset_nature_refuses_every_claim_and_says_what_to_record():
    r = _compute(transferred_asset_nature=None,
                 reinvestments=(_claim("54", cost_paise=40_00_000 * 100),))
    assert r.total_exemption_paise == 0
    assert any("has not been recorded" in g for g in r.gaps)


@pytest.mark.parametrize("section", ["54", "54B", "54F"])
def test_an_unknown_assessee_refuses_the_three_individual_only_sections(section):
    r = _compute(
        assessee_is_individual_or_huf=None,
        transferred_asset_nature=rex.NATURE_AGRICULTURAL_LAND,
        reinvestments=(_claim(section, cost_paise=25_00_000 * 100,
                              other_residential_houses_owned=0,
                              agricultural_use_two_years=True),))
    assert r.total_exemption_paise == 0
    assert any("individual or a Hindu" in g for g in r.claims[0].gaps)


def test_a_company_is_refused_s54_by_name():
    r = _compute(
        assessee_is_individual_or_huf=False,
        assessee_description="Private Limited",
        transferred_asset_nature=rex.NATURE_RESIDENTIAL_HOUSE,
        reinvestments=(_claim("54", cost_paise=40_00_000 * 100),))
    assert r.total_exemption_paise == 0
    assert any("Private Limited" in g for g in r.claims[0].gaps)


# ══ the Capital Gains Accounts Scheme ════════════════════════════════════════

def test_a_deposit_before_the_due_date_counts_as_utilised():
    r = _compute(
        transferred_asset_nature=rex.NATURE_RESIDENTIAL_HOUSE,
        return_due_date=date(2026, 7, 31), return_due_date_is_decided=True,
        reinvestments=(_claim("54", cost_paise=0, acquisition_date=None,
                              cgas_deposit_paise=30_00_000 * 100,
                              cgas_deposit_date=date(2026, 7, 15)),))
    assert r.total_exemption_paise == 30_00_000 * 100


def test_a_deposit_after_the_due_date_does_not():
    r = _compute(
        transferred_asset_nature=rex.NATURE_RESIDENTIAL_HOUSE,
        return_due_date=date(2026, 7, 31), return_due_date_is_decided=True,
        reinvestments=(_claim("54", cost_paise=0, acquisition_date=None,
                              cgas_deposit_paise=30_00_000 * 100,
                              cgas_deposit_date=date(2026, 8, 15)),))
    assert r.total_exemption_paise == 0
    assert any("does not count as utilised" in g for g in r.claims[0].gaps)


def test_an_undated_deposit_is_refused_rather_than_counted():
    r = _compute(
        transferred_asset_nature=rex.NATURE_RESIDENTIAL_HOUSE,
        reinvestments=(_claim("54", cost_paise=0, acquisition_date=None,
                              cgas_deposit_paise=30_00_000 * 100),))
    assert r.total_exemption_paise == 0
    assert any("with no date" in g for g in r.claims[0].gaps)


def test_an_undecided_due_date_says_the_stricter_test_was_used():
    r = _compute(
        transferred_asset_nature=rex.NATURE_RESIDENTIAL_HOUSE,
        return_due_date=date(2026, 7, 31), return_due_date_is_decided=False,
        reinvestments=(_claim("54", cost_paise=0, acquisition_date=None,
                              cgas_deposit_paise=30_00_000 * 100,
                              cgas_deposit_date=date(2026, 7, 15)),))
    assert any("stricter test" in c for c in r.claims[0].caveats)


# ══ several claims against one transfer ══════════════════════════════════════

def test_two_claims_together_never_exempt_more_gain_than_there_was():
    """s.54EC bonds and a s.54F house are not mutually exclusive on a sale of
    land, and nothing in either section exempts more than there was."""
    r = _compute(reinvestments=(
        _claim("54EC", cost_paise=30_00_000 * 100, acquisition_kind="bonds",
               acquisition_date=date(2025, 9, 1)),
        _claim("54F", cost_paise=1_00_00_000 * 100, other_residential_houses_owned=0),
    ))
    assert r.total_exemption_paise == 40_00_000 * 100
    assert r.taxable_gain_paise == 0
    assert r.claims[0].exemption_paise == 30_00_000 * 100
    assert r.claims[1].exemption_paise == 10_00_000 * 100
    assert any("nothing exempts more gain than there was" in w
               for w in r.claims[1].working)


# ══ the windows ══════════════════════════════════════════════════════════════

def test_a_house_purchased_a_year_before_the_transfer_is_in_time():
    r = _compute(
        transferred_asset_nature=rex.NATURE_RESIDENTIAL_HOUSE,
        reinvestments=(_claim("54", cost_paise=25_00_000 * 100,
                              acquisition_date=date(2024, 8, 1)),))
    assert r.total_exemption_paise == 25_00_000 * 100


def test_a_construction_has_no_year_before_limb():
    """s.54 and s.54F let the assessee have PURCHASED a house in the year
    before the transfer, but a CONSTRUCTION must be within three years AFTER
    it — applying the earlier date to a construction allows a claim the
    section does not."""
    r = _compute(
        transferred_asset_nature=rex.NATURE_RESIDENTIAL_HOUSE,
        reinvestments=(_claim("54", cost_paise=25_00_000 * 100,
                              acquisition_kind="construction",
                              acquisition_date=date(2024, 8, 1)),))
    assert r.total_exemption_paise == 0
    assert any("before" in g and "earliest date" in g for g in r.claims[0].gaps)


def test_a_construction_gets_three_years():
    r = _compute(
        transferred_asset_nature=rex.NATURE_RESIDENTIAL_HOUSE,
        reinvestments=(_claim("54", cost_paise=25_00_000 * 100,
                              acquisition_kind="construction",
                              acquisition_date=date(2028, 5, 1)),))
    assert r.claims[0].deadline == date(2028, 6, 10)
    assert r.total_exemption_paise == 25_00_000 * 100


def test_an_unfinished_construction_reports_its_deadline_rather_than_refusing():
    """"Not finished yet" is the ordinary state of a s.54 construction claim
    in the year of transfer."""
    r = _compute(
        transferred_asset_nature=rex.NATURE_RESIDENTIAL_HOUSE,
        reinvestments=(_claim("54", cost_paise=25_00_000 * 100,
                              acquisition_kind="construction",
                              acquisition_date=None),))
    assert r.total_exemption_paise == 25_00_000 * 100
    assert r.claims[0].deadline == date(2028, 6, 10)
    assert any("No acquisition date recorded" in c for c in r.claims[0].caveats)


# ══ the Rs 10 crore ceiling ══════════════════════════════════════════════════

def test_the_finance_act_2023_ceiling_applies_from_fy_2023_24():
    r = _compute(gain_paise=15_00_00_000 * 100,
                 net_consideration_paise=20_00_00_000 * 100,
                 transferred_asset_nature=rex.NATURE_RESIDENTIAL_HOUSE,
                 reinvestments=(_claim("54", cost_paise=12_00_00_000 * 100),))
    assert r.total_exemption_paise == 10_00_00_000 * 100


def test_the_ceiling_does_not_reach_an_earlier_transfer():
    r = rex.compute_exemption(
        gain_paise=15_00_00_000 * 100, net_consideration_paise=20_00_00_000 * 100,
        transfer_date=date(2022, 6, 10), is_long_term=True,
        transferred_asset_nature=rex.NATURE_RESIDENTIAL_HOUSE,
        assessee_is_individual_or_huf=True,
        reinvestments=(rex.Reinvestment(
            section="54", cost_paise=12_00_00_000 * 100,
            acquisition_kind="purchase", acquisition_date=date(2022, 9, 1)),))
    assert r.total_exemption_paise == 12_00_00_000 * 100


def test_the_ceiling_does_not_reach_s54EC_or_s54B():
    for section in ("54EC", "54B"):
        assert not rex._cost_ceiling_applies(section, TRANSFER)


# ══ what is named rather than modelled ═══════════════════════════════════════

def test_the_two_house_option_is_held_but_never_applied():
    """The proviso is exercisable ONCE IN THE ASSESSEE'S LIFETIME and nothing
    here can know whether it has been used."""
    src = inspect.getsource(rex)
    assert "SECTION_54_TWO_HOUSE_GAIN_LIMIT_PAISE" in src
    body = src[src.index("def compute_exemption"):]
    assert "SECTION_54_TWO_HOUSE_GAIN_LIMIT_PAISE" not in body, (
        "the two-house proviso must not be applied — it is once in a lifetime")


def test_a_transferred_new_asset_is_reported_and_no_earlier_year_recomputed():
    r = _compute(
        transferred_asset_nature=rex.NATURE_RESIDENTIAL_HOUSE,
        reinvestments=(_claim("54", cost_paise=25_00_000 * 100,
                              new_asset_transferred_on=date(2027, 1, 1)),))
    assert r.total_exemption_paise == 25_00_000 * 100
    assert any("withdraws this exemption" in c for c in r.claims[0].caveats)
    assert any("not computed here" in c for c in r.claims[0].caveats)


def test_the_net_consideration_caveat_names_what_the_register_does_not_hold():
    r = _compute(reinvestments=(
        _claim("54F", cost_paise=50_00_000 * 100, other_residential_houses_owned=0),))
    assert any("s.48(i)" in c and "understated" in c for c in r.caveats)


def test_the_caveat_is_not_emitted_where_no_section_apportions():
    r = _compute(transferred_asset_nature=rex.NATURE_RESIDENTIAL_HOUSE,
                 reinvestments=(_claim("54", cost_paise=25_00_000 * 100),))
    assert not any("s.48(i)" in c for c in r.caveats)


# ══ the service — which facts it reads ═══════════════════════════════════════

@pytest.mark.parametrize("entity,expected", [
    ("Individual", True),
    ("Proprietorship", True),
    ("Private Limited", False),
    ("LLP", False),
    ("Trust", False),
    # A value migration 001's CHECK does not have reads as UNKNOWN, never as a
    # company — a new entity type must refuse rather than fall through.
    ("Cooperative Society", None),
    (None, None),
    ("", None),
])
def test_the_individual_or_huf_test_is_tri_state(entity, expected):
    assert cgx.individual_or_huf(entity) is expected


def test_the_gain_read_is_the_registers_own_s48_figure():
    """NOT the indexed one. Post 23-07-2024 s.112 charges without indexation,
    and `indexed_cost_paise` is left NULL whenever the index was a fallback —
    a reader that picked whichever happened to be present would give two
    clients different exemptions on identical facts."""
    src = inspect.getsource(cgx.exemption_for_entry)
    # The docstring says WHY it is not read; the code must not read it.
    body = src.split('"""')[-1]
    assert "indexed_cost_paise" not in body
    assert 'entry.get("sale_value_paise")' in body


def test_the_claim_projection_carries_every_column_the_engine_reads():
    """A read that omits `cgas_deposit_date` reports the deposit as undated
    and refuses a claim that was in time."""
    for column in ("acquisition_date", "cgas_deposit_paise", "cgas_deposit_date",
                   "other_residential_houses_owned", "agricultural_use_two_years",
                   "new_asset_transferred_on", "cost_paise", "acquisition_kind"):
        assert column in cgx.CLAIM_COLUMNS, column


def test_the_routers_literal_projection_is_the_services_documented_one():
    """TWO SPELLINGS, PINNED. The query has to be a literal — the column guard
    reads every `.select()` against the real schema and a constant is
    invisible to it — but CLAIM_COLUMNS is what says WHY each column is
    needed, and the two must not drift."""
    src = inspect.getsource(it._entry_and_claims)
    # The FIRST .select is the register entry's own "*"; the claims are the
    # second, which is the one this is about.
    literal = src.split('capital_gain_reinvestments").select(')[1].split(")")[0]
    spelled = "".join(re.findall(r'"([^"]*)"', literal))
    assert spelled == cgx.CLAIM_COLUMNS, (
        f"the router selects {spelled!r}, the service documents "
        f"{cgx.CLAIM_COLUMNS!r}")


def test_a_row_becomes_a_reinvestment_with_no_field_defaulted_away():
    row = {
        "id": "r1", "section": "54F", "cost_paise": "500000",
        "acquisition_kind": "purchase", "acquisition_date": "2025-09-01",
        "cgas_deposit_paise": 0, "cgas_deposit_date": None,
        "other_residential_houses_owned": 0, "agricultural_use_two_years": None,
        "new_asset_transferred_on": None, "new_asset_description": "Flat",
    }
    r = cgx.to_reinvestment(row)
    assert r.section == "54F"
    assert r.cost_paise == 500000
    assert r.acquisition_date == date(2025, 9, 1)
    # 0 is a recorded answer and must not become None.
    assert r.other_residential_houses_owned == 0
    assert r.agricultural_use_two_years is None


def test_an_entry_with_no_sale_date_refuses_rather_than_measuring_a_window():
    r = cgx.exemption_for_entry(
        {"sale_value_paise": 100, "purchase_cost_paise": 50}, [], client_id="C1")
    assert r.total_exemption_paise == 0
    assert any("no sale date" in g for g in r.gaps)


# ══ the migration ════════════════════════════════════════════════════════════

_M385 = "385_a_reinvestment_can_be_recorded_against_a_capital_gain.sql"
_M385_BACK = "385_a_reinvestment_can_be_recorded_against_a_capital_gain_rollback.sql"


def _mig(name: str) -> str:
    return (_MIG / name).read_text(encoding="utf-8")


def _sql(name: str) -> str:
    """The migration with its `--` prose stripped. Every assertion below is
    about what the STATEMENTS do; the header deliberately discusses the
    columns it decided NOT to add, and matching on that would pass or fail on
    the commentary."""
    return "\n".join(l for l in _mig(name).splitlines()
                      if not l.lstrip().startswith("--"))


def test_the_nature_column_is_nullable_with_no_default():
    """Nullable and undefaulted is the whole design: guessing is unsafe in
    both directions."""
    sql = _sql(_M385)
    assert re.search(r"ADD COLUMN IF NOT EXISTS transferred_asset_nature TEXT\s*;", sql)
    for nature in rex.ASSET_NATURES:
        assert f"'{nature}'" in sql
    assert "DEFAULT 'residential_house'" not in sql


def test_the_claim_table_stores_no_exemption_amount():
    """The caps and the sections move by Finance Act; a stored figure would be
    right on the day it was written and silently wrong afterwards."""
    sql = _sql(_M385)
    assert "exemption_paise" not in sql
    assert "is_exempt" not in sql


def test_the_eligibility_facts_are_nullable_with_no_default():
    sql = _sql(_M385)
    for column in ("other_residential_houses_owned", "agricultural_use_two_years"):
        line = next(l for l in sql.splitlines() if l.strip().startswith(column))
        assert "NOT NULL" not in line and "DEFAULT" not in line, line


def test_the_claim_table_is_read_only_from_the_browser():
    """Migration 164's shape on the parent table: the exemption is computed
    server-side and there is no legitimate frontend write path."""
    sql = _sql(_M385)
    grants = [l.strip() for l in sql.splitlines() if l.strip().startswith("GRANT")]
    to_browser = [g for g in grants if "authenticated" in g]
    assert to_browser == ["GRANT SELECT ON public.capital_gain_reinvestments TO authenticated;"], (
        f"the browser must have SELECT and nothing else: {to_browser}")


def test_the_claim_table_is_assignment_scoped():
    """Migration 084's loop has never run again (see 370), so a table created
    now carries only its firm-wide policy unless it says otherwise."""
    sql = _sql(_M385)
    assert "capital_gain_reinvestments_assignment_scope" in sql
    assert "AS RESTRICTIVE FOR ALL" in sql
    assert "public.can_access_client(client_id::text)" in sql


def test_the_rollback_undoes_both_halves():
    back = _mig(_M385_BACK)
    assert "DROP TABLE IF EXISTS public.capital_gain_reinvestments" in back
    assert "DROP COLUMN IF EXISTS transferred_asset_nature" in back


# ══ the endpoints ════════════════════════════════════════════════════════════

CALLER = {"firm_id": "F1", "id": "u1", "role": "Partner", "email": "p@f.test"}


def test_the_sections_endpoint_serves_the_engines_own_vocabulary():
    """Served so the screen holds no second copy to drift from."""
    body = it.get_reinvestment_sections(current_user=CALLER)
    data = body["data"]
    assert [s["section"] for s in data["sections"]] == list(rex.RULES)
    assert data["asset_natures"] == list(rex.ASSET_NATURES)
    assert data["acquisition_kinds"] == list(rex.ACQUISITION_KINDS)
    # The one difference that decides the figure is on the wire.
    assert next(s for s in data["sections"] if s["section"] == "54F")["proportionate"] is True
    assert next(s for s in data["sections"] if s["section"] == "54")["proportionate"] is False


@pytest.mark.parametrize("bad", ["54EE", "80C", "", "54f"])
def test_an_unknown_section_is_refused_at_the_model(bad):
    with pytest.raises(Exception):
        it.ReinvestmentIn(section=bad, new_asset_description="x")


@pytest.mark.parametrize("bad", ["gift", "inheritance"])
def test_an_unknown_acquisition_kind_is_refused_at_the_model(bad):
    with pytest.raises(Exception):
        it.ReinvestmentIn(section="54", new_asset_description="x", acquisition_kind=bad)


def test_a_blank_acquisition_kind_is_not_recorded_as_one():
    assert it.ReinvestmentIn(section="54", new_asset_description="x",
                             acquisition_kind="").acquisition_kind is None


@pytest.mark.parametrize("bad", ["house", "shares", "RESIDENTIAL_HOUSE"])
def test_an_unknown_asset_nature_is_refused_at_the_register_model(bad):
    with pytest.raises(Exception):
        it.CreateCapitalGainsRequest(
            client_id="C1", asset_description="x", asset_type="property",
            purchase_date=date(2020, 1, 1), sale_date=TRANSFER,
            purchase_cost_paise=1, sale_value_paise=2,
            transferred_asset_nature=bad)


def test_an_omitted_nature_is_stored_as_none_rather_than_defaulted():
    req = it.CreateCapitalGainsRequest(
        client_id="C1", asset_description="x", asset_type="property",
        purchase_date=date(2020, 1, 1), sale_date=TRANSFER,
        purchase_cost_paise=1, sale_value_paise=2)
    assert req.transferred_asset_nature is None


def test_the_create_path_persists_the_nature():
    src = inspect.getsource(it.create_capital_gains)
    assert '"transferred_asset_nature": req.transferred_asset_nature,' in src


def test_every_reinvestment_endpoint_resolves_the_entry_before_touching_a_claim():
    """Scope-checked through the ENTRY, which is what carries the client_id."""
    for fn in (it.get_capital_gain_exemption, it.add_capital_gain_reinvestment,
               it.delete_capital_gain_reinvestment):
        assert "_entry_and_claims(" in inspect.getsource(fn), fn.__name__
    resolver = inspect.getsource(it._entry_and_claims)
    assert "can_access_client(current_user, entry.get(\"client_id\"))" in resolver
    assert 'eq("firm_id", current_user["firm_id"])' in resolver


def test_a_claim_is_recorded_even_when_it_does_not_yet_qualify():
    """A claim refused for a missing fact is the ordinary state of one entered
    before the CA has asked the client — refusing the WRITE would leave them
    nowhere to put what they do know."""
    src = inspect.getsource(it.add_capital_gain_reinvestment)
    assert "compute_exemption" not in src
    assert "RECORDED WHETHER OR NOT IT QUALIFIES" in src
