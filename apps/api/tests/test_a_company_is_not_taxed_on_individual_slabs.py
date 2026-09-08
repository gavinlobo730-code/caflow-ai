"""
IT-01 — a firm, an LLP and a company have a tax computation at all.

WHAT WAS WRONG
    domain/income_tax/entity_rates.py and minimum_tax.py were complete and
    tested, and imported by nothing outside their own package. The one
    computation endpoint the product has, POST /api/income-tax/compute, ran
    INDIVIDUAL slabs for every client.

    So a CA opened Client → Income Tax → Tax Computation for a Private Limited
    company, typed in the profit, and got tax computed nil to ₹4 lakh, 5% to
    ₹8 lakh, with a ₹60,000 §87A rebate. A company pays 22%/25%/30% from the
    first rupee and gets no rebate. On the live book — 4 Private Limited, 1 LLP,
    1 Partnership, 1 Proprietorship, no individuals — the endpoint fitted none
    of the clients.

    Measured on ₹50,00,000 of business income for FY 2025-26: an individual
    (new regime) owes ₹11,23,200 and a company owes ₹15,60,000. The screen
    showed every company the first figure.

EVERY NUMBER BELOW IS ARRIVED AT FROM THE STATUTE, not read back off the
implementation. The workings are in the docstrings.
"""
from __future__ import annotations

import pytest

from domain.income_tax.assessee import assessee_kind_for_entity_type
from domain.income_tax.itr_engine import ITRComputeRequest, ITREngine

FY = "2025-26"
FIFTY_LAKH = 50_00_000 * 100


def _tax(**kw) -> "object":
    kw.setdefault("fy", FY)
    return ITREngine().compute(ITRComputeRequest(**kw))


# ── who is being assessed ────────────────────────────────────────────────────

@pytest.mark.parametrize("entity_type,expected", [
    ("Private Limited", "domestic_company"),
    ("private_limited", "domestic_company"),      # the underscore fold
    ("PRIVATE  LIMITED", "domestic_company"),
    ("Public Limited", "domestic_company"),
    ("One Person Company", "domestic_company"),
    ("LLP", "llp"),
    ("Partnership", "firm"),
    ("Individual", "individual"),
])
def test_the_client_entity_type_maps_to_an_assessee(entity_type, expected):
    kind, refusal = assessee_kind_for_entity_type(entity_type)
    assert kind == expected, entity_type
    assert refusal is None


def test_a_proprietorship_is_an_individual():
    """THE ONE THAT IS NOT OBVIOUS. A proprietorship is not a person in tax law
    — the proprietor is assessed, on the ordinary slabs, with §87A and the whole
    of Chapter VI-A. Charging it 30% as a 'business entity' would be as wrong in
    the other direction as charging a company on slabs."""
    assert assessee_kind_for_entity_type("Proprietorship") == ("individual", None)


@pytest.mark.parametrize("entity_type,must_say", [
    ("Trust", "164"),
    ("Society", "80P"),
    ("", "no entity type recorded"),
    (None, "no entity type recorded"),
    ("Hovercraft", "no tax basis recorded"),
])
def test_an_unmodelled_entity_is_refused_and_the_refusal_names_the_gap(entity_type, must_say):
    """A trust is taxed under §§11-13 or §164; a co-operative society has its
    own schedule and §80P. Neither is modelled, so neither is guessed — the
    refusal names the sections so a CA knows WHAT is missing."""
    kind, refusal = assessee_kind_for_entity_type(entity_type)
    assert kind is None
    assert refusal and must_say in refusal


# ── the charge ───────────────────────────────────────────────────────────────

def test_a_company_pays_thirty_per_cent_from_the_first_rupee():
    """₹50,00,000 at 30% is ₹15,00,000. No surcharge — the 7% bracket starts
    above ₹1 crore. Cess at 4% of ₹15,00,000 is ₹60,000. Total ₹15,60,000.

    The 25% concession is NOT granted here: `turnover_in_reference_year_paise`
    is absent, and entity_rates uses the higher rate rather than assuming a
    concession nobody established.
    """
    r = _tax(assessee_kind="domestic_company", business_income_paise=FIFTY_LAKH)
    assert r.entity_rate_percent == 30
    assert r.tax_before_cess_paise == 15_00_000 * 100
    assert r.surcharge_paise == 0
    assert r.cess_paise == 60_000 * 100
    assert r.total_tax_paise == 15_60_000 * 100


def test_the_same_profit_as_an_individual_is_a_third_less():
    """THE MEASUREMENT. This is what every company on the live book was shown."""
    company = _tax(assessee_kind="domestic_company", business_income_paise=FIFTY_LAKH)
    individual = _tax(business_income_paise=FIFTY_LAKH)
    assert individual.total_tax_paise == 11_23_200 * 100
    assert company.total_tax_paise == 15_60_000 * 100
    assert company.total_tax_paise - individual.total_tax_paise == 4_36_800 * 100


def test_the_turnover_test_looks_two_years_back_and_grants_25_per_cent():
    """§115BA/the Finance Act rate: 25% where turnover in the REFERENCE year did
    not exceed ₹400 crore. For FY 2025-26 the reference year is 2023-24 — not
    the year being taxed, which would move companies across the boundary by a
    whole year and in the wrong direction."""
    r = _tax(assessee_kind="domestic_company", business_income_paise=FIFTY_LAKH,
             turnover_in_reference_year_paise=10_00_00_000 * 100)   # ₹10 crore
    assert r.turnover_reference_fy == "2023-24"
    assert r.entity_rate_percent == 25
    assert r.tax_before_cess_paise == 12_50_000 * 100


def test_115BAA_surcharge_is_flat_ten_per_cent_even_under_a_crore():
    """22% + a FLAT 10% surcharge + 4% cess = 25.168% effective. A normal-regime
    company at the same income pays no surcharge at all, so reusing the normal
    brackets for a company that has opted in understates its tax by a tenth.

    ₹50,00,000 × 22% = ₹11,00,000; surcharge ₹1,10,000; cess 4% of ₹12,10,000 =
    ₹48,400. Total ₹12,58,400.
    """
    r = _tax(assessee_kind="domestic_company", company_regime="115BAA",
             business_income_paise=FIFTY_LAKH)
    assert r.entity_rate_percent == 22
    assert r.surcharge_paise == 1_10_000 * 100
    assert r.total_tax_paise == 12_58_400 * 100
    assert r.regime == "115BAA"


@pytest.mark.parametrize("kind", ["firm", "llp"])
def test_a_firm_and_an_llp_pay_a_flat_thirty_per_cent(kind):
    """No slabs, no exemption limit, from the first rupee."""
    r = _tax(assessee_kind=kind, business_income_paise=FIFTY_LAKH)
    assert r.entity_rate_percent == 30
    assert r.total_tax_paise == 15_60_000 * 100
    assert r.rebate_87a_paise == 0, "§87A reaches 'an individual, being a resident'"
    assert r.standard_deduction_paise == 0, "§16(ia) is a salary deduction"
    assert r.regime == "", "a firm has no §115BAC regime, and 'new'/'old' would lie"


def test_an_entity_gets_no_standard_deduction_and_no_rebate():
    """At ₹6,00,000 an individual pays nothing (the §87A rebate wipes it out).
    A firm at the same income pays 30% + cess = ₹1,87,200."""
    firm = _tax(assessee_kind="firm", business_income_paise=6_00_000 * 100)
    individual = _tax(business_income_paise=6_00_000 * 100)
    assert individual.total_tax_paise == 0
    assert firm.total_tax_paise == 1_87_200 * 100


# ── §115JB and §115JC ────────────────────────────────────────────────────────

def test_MAT_bites_where_book_profit_dwarfs_taxable_income():
    """§115JB is 15% of BOOK PROFIT, and the gap between book profit and taxable
    income is the whole reason the section exists.

    ₹1,00,000 of taxable income at 30% is ₹30,000, cess ₹1,200 → ₹31,200.
    ₹50,00,000 of book profit at 15% is ₹7,50,000, cess ₹30,000 → ₹7,80,000.
    The minimum is payable and the excess of ₹7,48,800 becomes a §115JAA credit
    for fifteen assessment years.
    """
    r = _tax(assessee_kind="domestic_company", business_income_paise=1_00_000 * 100,
             book_profit_paise=FIFTY_LAKH, assessment_year_end=2027)
    assert r.minimum_tax_section == "115JB"
    assert r.minimum_tax_applied is True
    assert r.total_tax_paise == 7_80_000 * 100
    assert r.minimum_tax_credit_paise == 7_48_800 * 100
    assert r.minimum_tax_credit_expires_after_ay == 2042
    # The components describe the MINIMUM, so the three still add to the total.
    assert (r.tax_before_cess_paise + r.surcharge_paise + r.cess_paise
            == r.total_tax_paise)


def test_MAT_does_not_bite_where_the_ordinary_tax_is_higher():
    r = _tax(assessee_kind="domestic_company", business_income_paise=FIFTY_LAKH,
             book_profit_paise=10_00_000 * 100)
    assert r.minimum_tax_applied is False
    assert r.minimum_tax_credit_paise == 0
    assert r.total_tax_paise == 15_60_000 * 100


def test_a_company_with_no_book_profit_supplied_is_WARNED_not_silently_cleared():
    """Book profit is the Companies Act profit as adjusted by Explanation 1 to
    §115JB(2). It is not taxable income and cannot be derived from it — so its
    absence is a gap that has to be said out loud, not a §115JB of nil."""
    r = _tax(assessee_kind="domestic_company", business_income_paise=FIFTY_LAKH)
    assert r.minimum_tax_section == ""
    assert any("115JB was not tested" in w for w in r.warnings)


def test_AMT_needs_a_triggering_deduction_to_have_been_claimed():
    """§115JC applies only where a §10AA, §35AD or Chapter VI-A Part C deduction
    has been CLAIMED. A firm that claimed none is outside Chapter XII-BA
    entirely — not merely below a threshold."""
    without = _tax(assessee_kind="firm", business_income_paise=FIFTY_LAKH)
    assert without.minimum_tax_applies is False
    with_it = _tax(assessee_kind="firm", business_income_paise=FIFTY_LAKH,
                   claimed_specified_deduction=True)
    assert with_it.minimum_tax_section == "115JC"
    assert with_it.minimum_tax_applies is True


def test_a_115BAA_company_is_outside_MAT_altogether():
    r = _tax(assessee_kind="domestic_company", company_regime="115BAA",
             business_income_paise=1_00_000 * 100, book_profit_paise=FIFTY_LAKH)
    assert r.minimum_tax_applies is False
    assert r.total_tax_paise < 7_80_000 * 100


# ── what an entity request may NOT contain ───────────────────────────────────

@pytest.mark.parametrize("field,names", [
    ("gross_salary_paise", "Salaries"),
    ("nps_80ccd1b_paise", "80CCD(1B)"),
    ("savings_interest_80tta_paise", "80TTA"),
    ("home_loan_interest_24b_paise", "24(b)"),
])
def test_an_individual_only_input_is_refused_rather_than_ignored(field, names):
    """Ignoring it would tell a CA the deduction was allowed. The refusal names
    the section and says what to do instead."""
    r = _tax(assessee_kind="firm", business_income_paise=FIFTY_LAKH, **{field: 1})
    assert r.validation_errors
    assert names in r.validation_errors[0]
    assert r.total_tax_paise == 0, "nothing is computed on a refused request"


def test_capital_gains_are_refused_rather_than_charged_at_the_flat_rate():
    """§111A (20%), §112A (12.5% over ₹1,25,000) and §112 (12.5%) charge ANY
    assessee and OVERRIDE the flat rate for those components. Folding a
    company's listed-equity LTCG into total income at 30% would more than
    double the tax on the one figure a CA is least likely to re-derive."""
    r = _tax(assessee_kind="domestic_company", business_income_paise=FIFTY_LAKH,
             capital_gains_ltcg_paise=10_00_000 * 100)
    assert r.validation_errors
    assert "112A" in r.validation_errors[0]
    assert "not modelled" in r.validation_errors[0]


# ── what an entity request may contain ───────────────────────────────────────

def test_80G_is_available_to_a_company_and_the_10_per_cent_ceiling_applies():
    """§80G(1) gives the deduction to 'any assessee', and §80G(4) caps the
    limited category at 10% of adjusted gross total income.

    ₹50,00,000 of income; a ₹10,00,000 donation at 100% but subject to the
    limit, so the ceiling is ₹5,00,000. Tax on ₹45,00,000 at 30% = ₹13,50,000,
    cess ₹54,000 → ₹14,04,000.
    """
    from domain.income_tax.itr_engine import Donation80G

    r = _tax(assessee_kind="domestic_company", business_income_paise=FIFTY_LAKH,
             donations_80g=[Donation80G(description="Relief fund",
                                        amount_paise=10_00_000 * 100,
                                        deduction_pct=100,
                                        subject_to_qualifying_limit=True,
                                        paid_in_cash=False)])
    assert r.deduction_80g_paise == 5_00_000 * 100
    assert r.taxable_income_paise == 45_00_000 * 100
    assert r.total_tax_paise == 14_04_000 * 100


def test_a_house_property_loss_is_capped_at_two_lakh_for_an_entity_too():
    """§71(3A) binds every assessee. §115BAC's outright denial does NOT run
    here — that section reaches only an individual or HUF, and applying it to a
    company would deny a set-off the Act allows."""
    r = _tax(assessee_kind="firm", business_income_paise=FIFTY_LAKH,
             house_property_income_paise=-5_00_000 * 100)
    assert r.gross_total_income_paise == FIFTY_LAKH - 2_00_000 * 100


def test_presumptive_income_replaces_business_income_for_a_firm_too():
    """§44AD(2) deems every §30-§38 deduction already allowed, so the
    presumptive figure IS the business income — adding book profit on top would
    tax the same business twice."""
    r = _tax(assessee_kind="firm", business_income_paise=99_00_000 * 100,
             presumptive_income_paise=8_00_000 * 100)
    assert r.taxable_income_paise == 8_00_000 * 100


# ═════════════════════════════════════════════════════════════════════════════
# THROUGH THE ENDPOINT — the mapping happens in apps/api, not on a screen
# ═════════════════════════════════════════════════════════════════════════════
#
# The screen sends the raw `clients.entity_type` it already read. Deciding that
# 'Private Limited' is a company and 'Proprietorship' is an individual is
# statutory knowledge, and CLAUDE.md keeps that in apps/api.

CALLER = {"firm_id": "firm-1", "id": "u1"}


def _post(**payload):
    import routers.income_tax as it_router
    from routers.income_tax import ComputeITRRequest

    payload.setdefault("fy", FY)
    return it_router.compute_itr(ComputeITRRequest(**payload), CALLER)


def test_the_endpoint_maps_the_client_entity_type_itself():
    r = _post(entity_type="Private Limited", business_income_paise=FIFTY_LAKH)
    assert r["success"] is True
    assert r["data"]["assessee"]["kind"] == "domestic_company"
    assert r["data"]["assessee"]["rate_percent"] == 30
    assert r["data"]["tax"]["total_tax_paise"] == 15_60_000 * 100
    assert r["data"]["assessee"]["workings"], "the reasoning travels with the figure"


def test_a_proprietorship_still_gets_the_slabs_through_the_endpoint():
    r = _post(entity_type="Proprietorship", business_income_paise=FIFTY_LAKH)
    assert r["data"]["assessee"]["kind"] == "individual"
    assert r["data"]["tax"]["total_tax_paise"] == 11_23_200 * 100


def test_an_unmodelled_entity_type_is_a_422_with_the_reason():
    """Not a silent fall-back to the individual slabs. That default is what
    produced the defect, and it produced it silently."""
    import pytest as _pytest
    from fastapi import HTTPException

    with _pytest.raises(HTTPException) as e:
        _post(entity_type="Trust", business_income_paise=FIFTY_LAKH)
    assert e.value.status_code == 422
    assert "164" in e.value.detail


def test_an_unknown_assessee_kind_is_refused_by_name():
    import pytest as _pytest
    from fastapi import HTTPException

    with _pytest.raises(HTTPException) as e:
        _post(assessee_kind="partnership", business_income_paise=FIFTY_LAKH)
    assert e.value.status_code == 422
    assert "domestic_company" in e.value.detail


def test_no_entity_type_at_all_is_still_an_individual():
    """Every existing caller is unchanged: the field is optional and its
    absence means what the endpoint has always done."""
    r = _post(gross_salary_paise=12_00_000 * 100)
    assert r["data"]["assessee"]["kind"] == "individual"
    assert r["data"]["regime"] == "new"


def test_the_minimum_tax_block_reaches_the_response():
    r = _post(entity_type="Private Limited", business_income_paise=1_00_000 * 100,
              book_profit_paise=FIFTY_LAKH, assessment_year_end=2027)
    mt = r["data"]["minimum_tax"]
    assert mt["section"] == "115JB"
    assert mt["applied"] is True
    assert mt["credit_paise"] == 7_48_800 * 100
    assert mt["credit_expires_after_ay"] == 2042
    assert mt["reasons"], "the credit needs its reasoning, or nobody claims it"
