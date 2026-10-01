"""A HUF, an AOP and a BOI are assessees with a tax basis of their own (TDS-INCOME-TAX-16).

WHAT WAS WRONG
    `clients.entity_type` was CHECKed to eight values and none was a HUF, an AOP
    or a BOI, so each was recorded as "Individual" and computed on the
    individual slabs WITH the §87A rebate, the §16(ia) standard deduction and
    the senior-citizen slab. §87A reaches "an assessee, being an individual
    resident in India", §16(ia) is a deduction from salary and the higher
    exemption at 60 and 80 is for "every individual", so a family or an
    association was handed three reliefs the Act does not give it. An AOP or a
    BOI has a second problem: §167B charges its whole income at the maximum
    marginal rate in two cases, and an Individual was never charged that.

WHAT IS ASSERTED
    * the three are storable, mapped and spelled the same way on every side
      (the model, the migration, the forms, the vectors);
    * a HUF takes the individual's slabs and regimes with NONE of the three
      reliefs, and with everything else an individual has that the Act extends
      to it — §80C, §80D, §80TTA and the unused-exemption absorption;
    * an AOP or a BOI is REFUSED until the two §167B facts are stated, charged
      at the top rate where either fact says so and on the slabs otherwise,
      with no §87A in either case;
    * the reliefs an individual alone gets are REFUSED on the other three, with
      the section's own words, and not silently dropped;
    * §44AD reaches a HUF and §44ADA does not;
    * the browser's lists are pinned from this side.

NEGATIVE CONTROL
    Against the previous engine every HUF/AOP/BOI computation below fails —
    `assessee_kind="huf"` fell into the individual slab path and took the rebate
    — and the vocabulary, mapping and endpoint tests fail on the missing values.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from domain.income_tax import aop_boi, relief_reach
from domain.income_tax.assessee import (
    ALL_ASSESSEE_KINDS, BASIS_NOTE, DEFAULT_ITR_FORM, SLAB_KINDS,
    assessee_kind_for_entity_type, implies_business_income,
)
from domain.income_tax.chapter_vi_a import ChapterVIAClaims
from domain.income_tax.itr_engine import (
    Deductions80C, Deductions80D, HRADetails, ITRComputeRequest, itr_engine,
)
from domain.income_tax.statutory_rates import rates_for
from models.client import EntityType
from routers import income_tax as it
from services import compliance_obligation_service as ob
from services.compliance_obligation_service import CLIENT_ENTITY_TYPES

API = Path(__file__).resolve().parents[1]
WEB = API.parent / "web"
CALLER = {"id": "u1", "firm_id": "f1", "role": "Partner"}
FY = "2025-26"


def rs(rupees: int) -> int:
    """Rupees to paise — every figure below is hand-worked in rupees."""
    return rupees * 100


def run(**kw):
    kw.setdefault("fy", FY)
    return itr_engine.compute(ITRComputeRequest(**kw))


def tax_rupees(r) -> int:
    return r.total_tax_paise // 100


# ══ the vocabulary, on every side ════════════════════════════════════════════

def test_the_three_are_in_the_model_and_in_the_backends_own_list():
    for value in ("HUF", "AOP", "BOI"):
        assert EntityType(value).value == value
        assert value in CLIENT_ENTITY_TYPES
    assert [e.value for e in EntityType] == list(CLIENT_ENTITY_TYPES)


@pytest.mark.parametrize("spelling,kind", [
    ("HUF", "huf"), ("huf", "huf"), ("Hindu Undivided Family", "huf"),
    ("AOP", "aop"), ("Association of Persons", "aop"),
    ("BOI", "boi"), ("Body of Individuals", "boi"),
])
def test_each_is_its_own_assessee_and_not_an_individual(spelling, kind):
    got, refusal = assessee_kind_for_entity_type(spelling)
    assert (got, refusal) == (kind, None)
    assert got != "individual"


def test_every_kind_is_derived_from_the_literal_and_the_slab_set_is_a_subset():
    assert set(SLAB_KINDS) <= set(ALL_ASSESSEE_KINDS)
    assert {"huf", "aop", "boi"} <= set(ALL_ASSESSEE_KINDS)
    # `minimum_tax` already spoke this vocabulary; the engine must not invent a
    # second spelling of the same assessees.
    from domain.income_tax import minimum_tax
    assert {"huf", "aop", "boi"} <= set(minimum_tax._THRESHOLD_ELIGIBLE)


def test_the_last_migration_to_define_the_check_lists_the_eleven():
    sql = (API / "migrations"
           / "453_a_huf_aop_or_boi_can_be_recorded_as_a_client.sql").read_text(encoding="utf-8")
    m = re.search(r"CHECK \(entity_type IN \((.*?)\)\)", sql, re.S)
    assert m
    assert sorted(re.findall(r"'([^']+)'", m.group(1))) == sorted(CLIENT_ENTITY_TYPES)
    assert "NOT VALID" in sql and "VALIDATE CONSTRAINT clients_entity_type_check" in sql


def test_a_huf_is_not_a_company_and_has_no_forced_business_income():
    for e in ("HUF", "AOP", "BOI"):
        assert not ob.is_companies_act_company(e)
        # A family or an association may or may not carry on a business, so the
        # form waits for a typed figure the way an Individual's does.
        assert implies_business_income(e) is False


def test_the_itr_due_date_for_the_three_is_refused_not_guessed():
    """Explanation 2 to §139(1) settles nothing on entity type alone here, so
    the earlier date is shown, undecided, with the gap named."""
    for e in ("HUF", "AOP", "BOI"):
        r = ob.itr_due_date_for_client("2025-26", e)
        assert r["decided"] is False and r["statutory_gaps"]


# ══ the reach table ══════════════════════════════════════════════════════════

#: Pinned exactly. Every row is [S]-graded — egress is refused — so a later
#: reader with the Act in front of them changes a row with a test failing.
EXPECTED_REACH = {
    "rebate_87a": ("individual",),
    "standard_deduction_16ia": ("individual",),
    "senior_citizen_slab": ("individual",),
    "salary_head": ("individual",),
    "hra_10_13a": ("individual",),
    "s80c": ("individual", "huf"),
    "s80ccd_1b": ("individual",),
    "s80ccd_2": ("individual",),
    "s80d": ("individual", "huf"),
    "s80tta": ("individual", "huf"),
    "s80e": ("individual",),
    "s80ee": ("individual",),
    "s80dd": ("individual", "huf"),
    "s80ddb": ("individual", "huf"),
    "s80u": ("individual",),
    "s80gg": ("individual",),
    "basic_exemption_absorption": ("individual", "huf"),
}


def test_the_reach_table_is_pinned_row_for_row():
    assert {k: v[1] for k, v in relief_reach.RELIEF_REACH.items()} == EXPECTED_REACH
    assert relief_reach.REACH_VERIFIED is False


def test_an_unknown_relief_or_kind_is_refused_not_granted():
    assert relief_reach.reaches("s80c", "individual") is True
    assert relief_reach.reaches("s80c", "weird") is False
    assert relief_reach.reaches("no_such_relief", "individual") is False


def test_every_row_of_the_table_is_consulted_by_the_engine():
    """A row nobody asks is a decoration — the rule is that the engine asks the
    table, not that it contains a particular spelling of a test."""
    src = (API / "domain" / "income_tax" / "itr_engine.py").read_text(encoding="utf-8")
    for key in relief_reach.RELIEF_REACH:
        assert f'"{key}"' in src, f"{key} is in relief_reach and the engine never asks it"


def test_an_individual_is_refused_nothing_and_an_association_everything():
    assert relief_reach.unavailable_for("individual") == []
    assert set(relief_reach.unavailable_for("huf")) == {
        k for k, v in EXPECTED_REACH.items() if "huf" not in v}
    # No row names an AOP or a BOI, so every relief is unavailable to them.
    assert set(relief_reach.unavailable_for("aop")) == set(EXPECTED_REACH)
    assert set(relief_reach.unavailable_for("boi")) == set(EXPECTED_REACH)


# ══ a HUF ════════════════════════════════════════════════════════════════════

def test_a_huf_gets_no_87a_rebate_where_an_individual_does():
    """₹6,00,000 of other income, new regime. An individual: slab tax ₹10,000,
    wholly rebated under §87A (threshold ₹12,00,000). A HUF: ₹10,000 + 4% cess =
    ₹10,400, no rebate, and the rebate is reported as not applying at all."""
    ind = run(assessee_kind="individual", other_income_paise=rs(600_000))
    huf = run(assessee_kind="huf", other_income_paise=rs(600_000))
    assert tax_rupees(ind) == 0 and ind.rebate_87a_paise == rs(10_000)
    assert ind.rebate_87a_applies is True
    assert tax_rupees(huf) == 10_400
    assert huf.rebate_87a_paise == 0 and huf.rebate_87a_applies is False
    assert any("§87A" in w for w in huf.entity_workings)


def test_a_huf_old_regime_has_the_general_slabs_and_no_rebate():
    """₹4,00,000, old regime: ₹2.5 lakh nil, then 5% of ₹1.5 lakh = ₹7,500, plus
    4% cess = ₹7,800. An individual under ₹5 lakh pays nothing."""
    ind = run(assessee_kind="individual", other_income_paise=rs(400_000), use_new_regime=False)
    huf = run(assessee_kind="huf", other_income_paise=rs(400_000), use_new_regime=False)
    assert tax_rupees(ind) == 0
    assert tax_rupees(huf) == 7_800


def test_a_hufs_senior_flag_is_ignored_with_a_sentence_and_the_general_slab_used():
    """A family is never sixty. The flag gives the general slab (the higher tax,
    the direction that cannot under-charge) and the answer says why."""
    general = run(assessee_kind="huf", other_income_paise=rs(400_000), use_new_regime=False)
    flagged = run(assessee_kind="huf", other_income_paise=rs(400_000), use_new_regime=False,
                  is_senior_citizen=True, is_very_senior_citizen=True)
    assert flagged.total_tax_paise == general.total_tax_paise
    assert any("senior" in w and "Hindu undivided family" in w for w in flagged.warnings)
    # The same flag on an individual DOES change the figure — the contrast that
    # shows the flag is ignored for the right reason.
    senior_individual = run(assessee_kind="individual", other_income_paise=rs(400_000),
                            use_new_regime=False, is_senior_citizen=True)
    assert senior_individual.total_tax_paise < general.total_tax_paise


def test_a_huf_gets_the_standard_deduction_of_nobody_because_it_has_no_salary():
    r = run(assessee_kind="huf", gross_salary_paise=rs(1_000_000))
    assert r.validation_errors
    assert any("Salaries" in e and "Hindu undivided family" in e for e in r.validation_errors)
    assert r.total_tax_paise == 0 and r.standard_deduction_paise == 0
    # ... and the individual is untouched: salary reaches the standard deduction.
    ind = run(assessee_kind="individual", gross_salary_paise=rs(1_000_000))
    assert not ind.validation_errors and ind.standard_deduction_paise == rs(75_000)


@pytest.mark.parametrize("claim,section", [
    ({"chapter_vi_a": ChapterVIAClaims(education_loan_interest_paise=rs(50_000))}, "§80E"),
    ({"chapter_vi_a": ChapterVIAClaims(assessee_is_disabled=True)}, "§80U"),
    ({"chapter_vi_a": ChapterVIAClaims(rent_paid_paise=rs(120_000))}, "§80GG"),
    ({"nps_80ccd1b_paise": rs(50_000)}, "§80CCD(1B)"),
    ({"employer_nps_80ccd2_paise": rs(50_000)}, "§80CCD(2)"),
    ({"hra": HRADetails(basic_salary_paise=rs(500_000), hra_received_paise=rs(100_000),
                        rent_paid_paise=rs(150_000))}, "§10(13A)"),
])
def test_an_individuals_alone_relief_is_refused_on_a_huf_with_the_sections_words(claim, section):
    r = run(assessee_kind="huf", other_income_paise=rs(1_000_000),
            use_new_regime=False, **claim)
    assert r.validation_errors, f"{section} was silently accepted for a HUF"
    assert any(section in e for e in r.validation_errors), r.validation_errors
    assert r.total_tax_paise == 0, "nothing is computed on a refused claim"


def test_what_a_huf_does_get_is_the_same_as_an_individuals():
    """§80C, §80D, §80TTA, §80DD and §80DDB name 'an individual or a HUF', and
    the absorption provisos name them too. Parity with an individual proves
    that the three differences are the ONLY ones."""
    common = dict(other_income_paise=rs(1_500_000), use_new_regime=False,
                  s80c=Deductions80C(ppf_paise=rs(150_000)),
                  s80d=Deductions80D(self_family_premium_paise=rs(20_000)),
                  savings_interest_80tta_paise=rs(8_000),
                  chapter_vi_a=ChapterVIAClaims(has_disabled_dependant=True))
    ind = run(assessee_kind="individual", **common)
    huf = run(assessee_kind="huf", **common)
    assert not huf.validation_errors, huf.validation_errors
    assert huf.deduction_80c_paise == ind.deduction_80c_paise == rs(150_000)
    assert huf.deduction_80d_paise == ind.deduction_80d_paise == rs(20_000)
    assert huf.deduction_80tta_paise == ind.deduction_80tta_paise == rs(8_000)
    assert huf.chapter_vi_a_paise == ind.chapter_vi_a_paise > 0
    assert huf.total_tax_paise == ind.total_tax_paise   # above any rebate, the figures coincide


def test_a_huf_above_the_rebate_threshold_pays_exactly_what_an_individual_does():
    """The only differences are the three reliefs, so where none bites the two
    assessees' tax is identical — surcharge ladder and cess included."""
    for income in (rs(1_300_000), rs(6_000_000), rs(30_000_000)):
        ind = run(assessee_kind="individual", other_income_paise=income)
        huf = run(assessee_kind="huf", other_income_paise=income)
        assert huf.total_tax_paise == ind.total_tax_paise, income
        assert huf.surcharge_paise == ind.surcharge_paise, income


def test_a_huf_absorbs_the_unused_basic_exemption_into_a_capital_gain():
    """The three provisos name 'an individual or a HUF, being a resident'. ₹5
    lakh of §111A STCG and nothing else: the first ₹4 lakh is the unused
    exemption, so 20% of ₹1 lakh = ₹20,000 + cess = ₹20,800."""
    r = run(assessee_kind="huf", capital_gains_stcg_paise=rs(500_000))
    assert r.basic_exemption_absorbed_paise == rs(400_000)
    assert tax_rupees(r) == 20_800


# ══ an AOP and a BOI ═════════════════════════════════════════════════════════

@pytest.mark.parametrize("kind", ["aop", "boi"])
def test_an_association_with_no_stated_members_is_refused_not_guessed(kind):
    for facts in ({}, {"aop_shares_determinate": True}):
        r = run(assessee_kind=kind, other_income_paise=rs(1_000_000), **facts)
        assert r.validation_errors == [aop_boi.UNSTATED_REFUSAL]
        assert r.total_tax_paise == 0
    assert "§167B(1)" in aop_boi.UNSTATED_REFUSAL and "§167B(2)" in aop_boi.UNSTATED_REFUSAL


@pytest.mark.parametrize("kind", ["aop", "boi"])
@pytest.mark.parametrize("facts", [
    {"aop_shares_determinate": False},
    {"aop_shares_determinate": False, "aop_any_member_over_exemption": False},
    {"aop_shares_determinate": True, "aop_any_member_over_exemption": True},
])
def test_an_association_is_charged_at_the_top_rate_from_the_first_rupee(kind, facts):
    """₹3,00,000: an individual pays nothing (slab + rebate). An association
    under §167B(1) or (2) pays 30% of the WHOLE ₹3,00,000 = ₹90,000, + 4% cess =
    ₹93,600 — no nil band, no rebate."""
    r = run(assessee_kind=kind, other_income_paise=rs(300_000), **facts)
    assert not r.validation_errors
    assert tax_rupees(r) == 93_600
    assert r.assessee_basis == aop_boi.BASIS_MAXIMUM_MARGINAL_RATE
    assert r.entity_rate_percent == 30
    assert r.rebate_87a_paise == 0 and r.rebate_87a_applies is False
    assert r.assessee_caveats == list(aop_boi.CAVEATS)
    assert run(assessee_kind="individual", other_income_paise=rs(300_000)).total_tax_paise == 0


def test_the_second_fact_is_not_demanded_where_the_shares_are_indeterminate():
    """§167B(1) charges the top rate whatever any member earns, so a caller who
    cannot know a member's income can still compute such an association."""
    r = run(assessee_kind="aop", other_income_paise=rs(300_000),
            aop_shares_determinate=False, aop_any_member_over_exemption=None)
    assert not r.validation_errors and tax_rupees(r) == 93_600


@pytest.mark.parametrize("kind", ["aop", "boi"])
def test_an_association_whose_shares_are_determinate_and_whose_members_are_below_the_limit_uses_the_slabs(kind):
    """₹10,00,000, new regime: 5% of ₹4 lakh = ₹20,000 and 10% of ₹2 lakh =
    ₹20,000 → ₹40,000 + 4% cess = ₹41,600. An individual at this income is wholly
    rebated; an association never is."""
    r = run(assessee_kind=kind, other_income_paise=rs(1_000_000),
            aop_shares_determinate=True, aop_any_member_over_exemption=False)
    assert not r.validation_errors
    assert tax_rupees(r) == 41_600
    assert r.assessee_basis == aop_boi.BASIS_SLAB and r.entity_rate_percent == 0
    assert r.rebate_87a_paise == 0 and r.rebate_87a_applies is False
    assert tax_rupees(run(assessee_kind="individual", other_income_paise=rs(1_000_000))) == 0


def test_the_top_rate_is_read_off_the_slab_table_and_never_stated():
    rates = rates_for(FY)
    assert aop_boi.maximum_marginal_rate_percent(rates.new_regime_slabs) == 30
    assert aop_boi.maximum_marginal_rate_percent(rates.old_regime_slabs_general) == 30
    with pytest.raises(ValueError):
        aop_boi.maximum_marginal_rate_percent(rates.new_regime_slabs[:3])
    src = (API / "domain" / "income_tax" / "aop_boi.py").read_text(encoding="utf-8")
    assert "30" not in re.sub(r'"""[\s\S]*?"""|#.*', "", src).replace("30%", ""), (
        "aop_boi must not carry a rate of its own")


def test_the_top_rate_surcharge_takes_marginal_relief_against_the_same_flat_charge():
    """₹51,00,000 at 30% = ₹15,30,000. The 10% surcharge would add ₹1,53,000 but
    the combined increase over the ₹50 lakh threshold may not exceed the ₹1 lakh
    of income above it: ₹15,00,000 + ₹1,00,000 = ₹16,00,000, so the surcharge is
    ₹70,000. Cess 4% of ₹16,00,000 = ₹64,000."""
    r = run(assessee_kind="aop", other_income_paise=rs(5_100_000), aop_shares_determinate=False)
    assert r.tax_before_cess_paise == rs(1_530_000)
    assert r.surcharge_paise == rs(70_000)
    assert r.cess_paise == rs(64_000)
    assert r.total_tax_paise == rs(1_664_000)


def test_the_new_regime_caps_the_associations_surcharge_at_25_percent():
    r = run(assessee_kind="aop", other_income_paise=rs(100_000_000), aop_shares_determinate=False)
    assert r.surcharge_paise == r.tax_before_cess_paise * 25 // 100


@pytest.mark.parametrize("claim,section", [
    ({"s80c": Deductions80C(ppf_paise=rs(150_000))}, "§80C"),
    ({"s80d": Deductions80D(self_family_premium_paise=rs(20_000))}, "§80D"),
    ({"savings_interest_80tta_paise": rs(8_000)}, "§80TTA"),
    ({"chapter_vi_a": ChapterVIAClaims(has_disabled_dependant=True)}, "§80DD"),
    ({"chapter_vi_a": ChapterVIAClaims(specified_disease_spend_paise=rs(40_000))}, "§80DDB"),
])
def test_an_association_is_refused_the_reliefs_that_name_an_individual_or_a_huf(claim, section):
    r = run(assessee_kind="aop", other_income_paise=rs(1_000_000), use_new_regime=False,
            aop_shares_determinate=True, aop_any_member_over_exemption=False, **claim)
    assert any(section in e and "association of persons" in e for e in r.validation_errors), \
        r.validation_errors


def test_an_association_gets_no_basic_exemption_absorption_on_the_slab_basis():
    """The provisos name an individual or a HUF. ₹5 lakh of §111A STCG is taxed
    at 20% on all of it: ₹1,00,000 + cess = ₹1,04,000 — the figure the engine's
    own comment records for the absorption's absence."""
    r = run(assessee_kind="boi", capital_gains_stcg_paise=rs(500_000),
            aop_shares_determinate=True, aop_any_member_over_exemption=False)
    assert r.basic_exemption_absorbed_paise == 0
    assert tax_rupees(r) == 104_000


def test_an_association_at_the_top_rate_refuses_a_capital_gain_rather_than_choosing():
    r = run(assessee_kind="aop", capital_gains_stcg_paise=rs(500_000),
            aop_shares_determinate=False)
    assert any("§111A" in e and "§167B" in e for e in r.validation_errors)
    assert r.total_tax_paise == 0


def test_every_167b_constant_is_unverified_and_the_caveats_name_what_is_left_out():
    assert aop_boi.VERIFIED is False
    text = " ".join(aop_boi.CAVEATS)
    assert "§2(29C)" in text and "surcharge" in text and "§86" in text


# ══ nothing an individual has moves ══════════════════════════════════════════

@pytest.mark.parametrize("regime", [True, False])
def test_an_individuals_computation_is_unchanged(regime):
    """The figures themselves are pinned by the existing engine suites; this
    asserts only that every new field defaults to the individual's behaviour —
    the rebate applies, the standard deduction is the regime's, and no basis,
    caveat or working is attached."""
    r = run(assessee_kind="individual", gross_salary_paise=rs(1_500_000), use_new_regime=regime)
    assert r.rebate_87a_applies is True
    assert r.assessee_basis == "" and r.assessee_caveats == []
    assert r.standard_deduction_paise == rs(75_000 if regime else 50_000)
    assert r.entity_workings == []


# ══ the router ═══════════════════════════════════════════════════════════════

def _compute(**kw):
    return it.compute_itr(it.ComputeITRRequest(fy=FY, **kw), CALLER)["data"]


def test_the_compute_endpoint_accepts_the_new_kinds_and_maps_the_entity_type():
    for kw in ({"assessee_kind": "huf"}, {"entity_type": "HUF"}):
        d = _compute(other_income_paise=rs(600_000), **kw)
        assert d["assessee"]["kind"] == "huf"
        assert d["assessee"]["rebate_87a_applies"] is False
        assert d["tax"]["total_tax_paise"] == rs(10_400)
        assert d["validation_errors"] == []


def test_the_compute_endpoint_names_all_seven_kinds_when_it_refuses_one():
    with pytest.raises(HTTPException) as e:
        _compute(assessee_kind="partnership_of_cats")
    assert e.value.status_code == 422
    for kind in ALL_ASSESSEE_KINDS:
        assert kind in e.value.detail


def test_the_endpoint_carries_the_two_167b_answers_through():
    d = _compute(entity_type="AOP", other_income_paise=rs(300_000),
                 aop_shares_determinate=False)
    assert d["assessee"]["basis"] == aop_boi.BASIS_MAXIMUM_MARGINAL_RATE
    assert d["assessee"]["rate_percent"] == 30
    assert d["tax"]["total_tax_paise"] == rs(93_600)
    assert d["assessee"]["caveats"]
    refused = _compute(entity_type="BOI", other_income_paise=rs(300_000))
    assert refused["validation_errors"] == [aop_boi.UNSTATED_REFUSAL]


def test_the_assessee_kind_endpoint_serves_the_form_the_reliefs_and_the_questions():
    def ask(entity):
        return it.resolve_assessee_kind(entity, CALLER)["data"]

    huf, aop, ind = ask("HUF"), ask("AOP"), ask("Individual")
    assert (huf["kind"], huf["default_itr_form"], huf["asks_about_members"]) == ("huf", "ITR-2", False)
    assert (aop["kind"], aop["default_itr_form"], aop["asks_about_members"]) == ("aop", "ITR-5", True)
    assert (ask("BOI")["default_itr_form"], ask("BOI")["asks_about_members"]) == ("ITR-5", True)
    assert ind["default_itr_form"] == "ITR-3" and ind["unavailable_reliefs"] == []
    assert ask("Private Limited")["default_itr_form"] == "ITR-6"
    assert ask("Private Limited")["unavailable_reliefs"] == [], \
        "a company's own branch already refuses an individual's inputs by name"
    assert "salary_head" in huf["unavailable_reliefs"] and "s80c" not in huf["unavailable_reliefs"]
    assert "s80c" in aop["unavailable_reliefs"]
    assert huf["basis_note"] == BASIS_NOTE["huf"] and ind["basis_note"] is None
    trust = ask("Trust")
    assert trust["kind"] is None and trust["default_itr_form"] is None and trust["refusal"]


def test_the_default_form_table_covers_every_kind_with_a_form_the_picker_knows():
    from domain.income_tax.itr_json import ITR_FORMS
    assert set(DEFAULT_ITR_FORM) == set(ALL_ASSESSEE_KINDS)
    assert set(DEFAULT_ITR_FORM.values()) <= set(ITR_FORMS)
    assert DEFAULT_ITR_FORM["huf"] != "ITR-1", "ITR-1 is an individual's alone"


# ══ the browser's lists, pinned from this side ═══════════════════════════════
# A guard written in apps/web would assert each list against a copy of itself
# and pass whenever both drifted together — the Schedule III caption lesson.

def _quoted_run_after(path: Path, anchor: str) -> list[str]:
    src = path.read_text(encoding="utf-8")
    start = src.index(anchor)
    end = src.index("];", start)    # not the first "]": `EntityType[]` has one
    found = re.findall(r'"([^"]+)"', src[start + len(anchor):end])
    assert found, f"parsed nothing after {anchor!r} — a selector that matches nothing passes everything"
    return found


ALL_TYPES = [e.value for e in EntityType]


def test_the_client_form_offers_exactly_the_models_values():
    got = _quoted_run_after(WEB / "components" / "ClientFormModal.tsx", "const ENTITY_TYPES = [")
    assert sorted(got) == sorted(ALL_TYPES)


def test_the_bulk_importer_and_the_pipeline_accept_exactly_the_models_values():
    got = _quoted_run_after(WEB / "app" / "clients" / "page.tsx", "const VALID_ENTITY_TYPES = [")
    assert sorted(got) == sorted(ALL_TYPES)
    pipeline = _quoted_run_after(WEB / "app" / "pipeline" / "page.tsx",
                                 "const ENTITY_TYPES: EntityType[] = [")
    assert sorted(pipeline) == sorted(ALL_TYPES)


def test_the_typed_unions_and_label_maps_carry_the_three():
    types = (WEB / "lib" / "types" / "index.ts").read_text(encoding="utf-8")
    fmt = (WEB / "lib" / "services" / "formatting.ts").read_text(encoding="utf-8")
    for value in ("HUF", "AOP", "BOI"):
        assert f'| "{value}"' in types
        assert re.search(rf'\b{value}: "{value}"', fmt)


def test_the_filing_pages_fallback_form_map_equals_the_servers_table():
    src = (WEB / "app" / "clients" / "[id]" / "tax" / "filing" / "page.tsx").read_text(encoding="utf-8")
    start = src.index("const FORM_BY_ASSESSEE_KIND")
    body = src[start:src.index("};", start)]
    parsed = dict(re.findall(r'\b(\w+):\s*"(ITR-\d)"', body))
    assert parsed == DEFAULT_ITR_FORM
    assert "default_itr_form" in src, "the page must prefer the served answer"


def test_the_computation_screen_hides_what_the_server_says_is_unavailable_and_holds_no_list():
    src = (WEB / "app" / "clients" / "[id]" / "tax" / "computation" / "page.tsx").read_text(encoding="utf-8")
    assert "unavailable_reliefs" in src and "asks_about_members" in src
    # It names a relief KEY to ask about, never a kind to decide by.
    code = re.sub(r"/\*[\s\S]*?\*/|//.*", "", src)
    assert not re.search(r'assesseeKind\s*===\s*"(huf|aop|boi)"', code)
    for key in ("salary_head", "s80ccd_2", "s80ccd_1b", "hra_10_13a", "s80e", "s80ee",
                "s80gg", "s80ddb", "s80dd", "s80u", "s80c", "s80d", "s80tta",
                "senior_citizen_slab"):
        assert key in relief_reach.RELIEF_REACH, f"the screen asks about {key!r}, which the server has no row for"
        assert f'"{key}"' in code, f"the screen never asks the server's answer about {key}"
