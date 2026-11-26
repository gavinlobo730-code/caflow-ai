"""The unforeseen income offered from the capital gains register carries the ANNUAL §112A exemption once and, where the year's total
income is given, the surcharge, both from the FY-versioned registry only (POST-A-075).

WHAT WAS WRONG
    The offered tax was the register's per-transfer figure plus cess: it took the §112A exemption off EVERY transfer (so two ₹1,25,000
    gains were each wholly exempt) and carried no surcharge.

WHAT IS HELD
    * across the year's listed-equity long-term gains in date order the exemption is used once and the offers add up to the tax on the
      aggregate gain; a loss in the section nets in its place;
    * the surcharge is the registry's bracket for the total income given, capped for the capital-gains sections; absent a total income
      none is offered and the sentence says so;
    * a year the registry does not hold is not filled with another year's figure: the register's own figure stays and the sentence
      from `statutory_rates.fy_rate_gap` says what was not applied; a held, unverified year applies and says so;
    * the rupee amounts below are worked by hand from the registry's rates (12.5% over ₹1,25,000; cess 4%; surcharge 15% on ₹1.5 crore).
"""
from __future__ import annotations

import pytest

import routers.income_tax as it
from domain.income_tax import statutory_rates as sr
from domain.income_tax import unforeseen_offer as uo

S = "Section 112A"


def _t(rid, day, gain, section=S, engine_tax=0):
    return uo.Transfer(rid, day, section, gain, engine_tax)


def _offer(transfers, fy, total_income_paise, kind="individual"):
    return uo.offer(transfers, fy, total_income_paise, assessee_kind=kind)


def test_the_annual_exemption_is_used_once_across_the_years_112a_gains():
    # Two gains of ₹1,25,000 and ₹2,00,000: the exemption covers the first and ₹1,25,000 of the second.
    got, _ = _offer([_t("a", "2025-06-01", 1_25_000_00), _t("b", "2025-09-01", 2_00_000_00)], "2025-26", None)
    assert got[0].tax_before_surcharge_paise == 0
    assert got[1].tax_before_surcharge_paise == (3_25_000_00 - 1_25_000_00) * 1250 // 10_000 == 25_000_00
    assert sum(o.tax_before_surcharge_paise for o in got) == (3_25_000_00 - 1_25_000_00) * 1250 // 10_000


def test_the_order_is_the_order_the_gains_arose_not_the_order_given():
    got, _ = _offer([_t("late", "2025-09-01", 2_00_000_00), _t("early", "2025-06-01", 1_25_000_00)], "2025-26", None)
    assert [o.tax_before_surcharge_paise for o in got] == [25_000_00, 0]


def test_a_loss_in_the_section_nets_in_its_place():
    got, _ = _offer([_t("g1", "2025-05-01", 3_00_000_00), _t("loss", "2025-07-01", -2_00_000_00),
                     _t("g2", "2025-09-01", 2_00_000_00)], "2025-26", None)
    # The year nets to 3.0L, whose tax is on 1.75L. g1 alone reaches that; the loss takes the running total down to 1.0L and g2
    # only brings it back to 3.0L, so g2 adds nothing the year had not already reached and is offered nil, not the same tax again.
    year_tax = 1_75_000_00 * 1250 // 10_000
    assert got[0].tax_before_surcharge_paise == year_tax
    assert got[1].tax_before_surcharge_paise == 0
    assert got[2].tax_before_surcharge_paise == 0
    assert sum(o.tax_before_surcharge_paise for o in got) == year_tax


def test_a_gain_that_a_later_loss_cancels_is_offered_nothing():
    # The year's net §112A gain is nil, so no tax arose from it: nothing is offered for the gain the loss cancelled.
    got, _ = _offer([_t("g", "2025-07-01", 3_00_000_00), _t("loss", "2025-08-01", -3_00_000_00)], "2025-26", None)
    assert [o.tax_before_surcharge_paise for o in got] == [0, 0]


def test_the_offers_never_add_up_to_more_than_the_years_tax():
    # Peaks and troughs: whatever the order, the offers add up to the tax on the year's net gain and attach to the earliest gains.
    seq = [_t("a", "2025-05-01", 4_00_000_00), _t("l1", "2025-06-01", -3_00_000_00), _t("b", "2025-07-01", 5_00_000_00),
           _t("l2", "2025-08-01", -4_00_000_00), _t("c", "2025-09-01", 1_00_000_00)]
    got, _ = _offer(seq, "2025-26", None)
    net = 4_00_000_00 - 3_00_000_00 + 5_00_000_00 - 4_00_000_00 + 1_00_000_00
    year_tax = (net - 1_25_000_00) * 1250 // 10_000
    assert sum(o.tax_before_surcharge_paise for o in got) == year_tax
    assert got[0].tax_before_surcharge_paise == year_tax, "the first gain already reaches the year's figure"


def test_a_gain_of_another_section_keeps_the_registers_figure():
    got, _ = _offer([_t("s", "2025-06-01", 5_00_000_00, section="Section 111A", engine_tax=1_00_000_00)], "2025-26", None)
    assert got[0].tax_before_surcharge_paise == 1_00_000_00


def test_the_surcharge_is_the_registry_bracket_for_the_total_income_given_and_capped_for_these_sections():
    gain = 2_00_000_00
    base = (gain - 1_25_000_00) * 1250 // 10_000
    # Total income 1.5 crore: ordinary bracket 15% (above 1 crore); the capital-gains cap is 15%.
    got, notes = _offer([_t("a", "2025-06-01", gain)], "2025-26", 1_50_000_000_00)
    assert got[0].surcharge_rate_percent == 15 and got[0].surcharge_paise == base * 15 // 100
    assert got[0].tax_paise == base + base * 15 // 100 + (base + base * 15 // 100) * 4 // 100
    assert any("marginal relief is not modelled" in n for n in notes)
    # Total income 6 crore: the bracket would be 25% and the cap holds it at 15.
    capped, _ = _offer([_t("a", "2025-06-01", gain)], "2025-26", 6_00_000_000_00)
    assert capped[0].surcharge_rate_percent == sr.RATES_BY_FY["2025-26"].capital_gains_surcharge_cap_percent == 15
    # Below every bracket: nothing.
    none, _ = _offer([_t("a", "2025-06-01", gain)], "2025-26", 40_00_000_00)
    assert none[0].surcharge_paise == 0 and none[0].surcharge_rate_percent == 0


def test_without_a_total_income_no_surcharge_is_offered_and_the_sentence_says_so():
    got, notes = _offer([_t("a", "2025-06-01", 2_00_000_00)], "2025-26", None)
    assert got[0].surcharge_paise == 0 and got[0].surcharge_rate_percent is None
    assert any("Surcharge is NOT included" in n for n in notes)


@pytest.mark.parametrize("kind", ["domestic_company", "firm", "llp", None])
def test_a_firm_an_llp_a_company_or_an_unknown_assessee_is_not_given_an_individuals_surcharge(kind):
    # The registry's ladder (10% over 50 lakh, 15% over 1 crore, capped at 15 for these sections) is an individual's: a company at
    # 1.5 crore bears another ladder, so none is offered and the sentence says why, whatever total income is given.
    got, notes = _offer([_t("a", "2025-06-01", 2_00_000_00)], "2025-26", 1_50_000_000_00, kind=kind)
    assert got[0].surcharge_paise == 0 and got[0].surcharge_rate_percent is None
    assert any("firm, an LLP or a company" in n for n in notes), notes
    assert not any("Give the year's total income" in n for n in notes), "giving the income would not include it"


@pytest.mark.parametrize("kind", ["huf", "aop", "boi"])
def test_the_other_slab_assessees_take_the_ladder_the_computation_gives_them(kind):
    got, _ = _offer([_t("a", "2025-06-01", 2_00_000_00)], "2025-26", 1_50_000_000_00, kind=kind)
    assert got[0].surcharge_rate_percent == 15


def test_the_unused_basic_exemption_is_named_as_not_applied():
    _, notes = _offer([_t("a", "2025-06-01", 2_00_000_00)], "2025-26", None)
    assert any("basic exemption the slab income did not use" in n for n in notes)
    _, company = _offer([_t("a", "2025-06-01", 2_00_000_00)], "2025-26", None, kind="domestic_company")
    assert not any("basic exemption" in n for n in company), "a company has no basic exemption to leave out"


def test_a_slab_taxed_gain_gets_no_surcharge_and_the_sentence_says_why():
    got, notes = _offer([_t("d", "2025-06-01", 2_00_000_00, section="Section 50AA (Finance Act 2023)", engine_tax=60_000_00)],
                          "2025-26", 1_50_000_000_00)
    assert got[0].surcharge_paise == 0
    assert any("own slab" in n for n in notes)


def test_a_year_the_registry_does_not_hold_is_not_filled_with_another_years_figure():
    assert "2019-20" not in sr.RATES_BY_FY
    got, notes = _offer([_t("a", "2019-06-01", 5_00_000_00, engine_tax=77_00_000)], "2019-20", 1_50_000_000_00)
    assert got[0].tax_before_surcharge_paise == 77_00_000 and got[0].surcharge_paise == 0
    assert any(n == sr.fy_rate_gap("2019-20") for n in notes)
    assert any("NOT applied" in n for n in notes)


def test_a_held_but_unverified_year_applies_the_registry_and_says_it_is_unverified():
    assert sr.RATES_BY_FY["2026-27"].verified is False
    got, notes = _offer([_t("a", "2026-06-01", 2_00_000_00)], "2026-27", None)
    assert got[0].tax_before_surcharge_paise == 75_000_00 * 1250 // 10_000
    assert any(n == sr.fy_rate_gap("2026-27") for n in notes)


# ── through the endpoint ─────────────────────────────────────────────────────

@pytest.fixture
def register(monkeypatch):
    from tests.e2e_harness import FakeDB
    db = FakeDB()
    monkeypatch.setattr(it, "_db", lambda: db)
    monkeypatch.setattr(it, "assert_client_access", lambda u, c: None)
    base = {"firm_id": "F", "client_id": "C", "asset_type": "equity_shares", "improvement_cost_paise": 0,
            "is_listed_security": True, "purchase_date": "2021-01-10", "purchase_cost_paise": 1_00_000_00}
    db.seed("clients", {"id": "C", "firm_id": "F", "entity_type": "Individual"})
    db.seed("capital_gains", {**base, "id": "G1", "asset_description": "A", "sale_date": "2025-06-10", "sale_value_paise": 2_25_000_00})
    db.seed("capital_gains", {**base, "id": "G2", "asset_description": "B", "sale_date": "2025-09-10", "sale_value_paise": 3_00_000_00})
    return db


def test_the_endpoint_offers_the_annual_exemption_once(register):
    out = it.advance_tax_unforeseen_income(client_id="C", fy="2025-26", total_income_paise=None, current_user={"firm_id": "F"})["data"]
    by = {c["register_id"]: c for c in out["candidates"]}
    # G1 gains 1,25,000 (inside the exemption); G2 gains 2,00,000: tax on 2,00,000 + 1,25,000 - 1,25,000 = 2,00,000 at 12.5%, cess 4%.
    assert "G1" not in by
    assert by["G2"]["tax_paise"] == 25_000_00 + 25_000_00 * 4 // 100
    assert any("ESTIMATE" in c for c in out["caveats"]) and any("annual" in c for c in out["caveats"])


def test_the_endpoint_adds_the_surcharge_when_the_total_income_is_given(register):
    out = it.advance_tax_unforeseen_income(client_id="C", fy="2025-26", total_income_paise=1_50_000_000_00,
                                           current_user={"firm_id": "F"})["data"]
    c = out["candidates"][0]
    tax = 25_000_00
    assert c["surcharge_paise"] == tax * 15 // 100
    assert c["tax_paise"] == tax + tax * 15 // 100 + (tax + tax * 15 // 100) * 4 // 100


def test_the_endpoint_gives_a_company_no_individuals_surcharge(register):
    register.rows("clients")[0]["entity_type"] = "Private Limited"
    out = it.advance_tax_unforeseen_income(client_id="C", fy="2025-26", total_income_paise=1_50_000_000_00,
                                           current_user={"firm_id": "F"})["data"]
    c = out["candidates"][0]
    assert c["surcharge_paise"] == 0 and c["tax_paise"] == 25_000_00 + 25_000_00 * 4 // 100
    assert any("firm, an LLP or a company" in x for x in out["caveats"])


def test_the_endpoint_reads_the_entity_type_of_the_callers_own_firm_only(register):
    # The client row is read firm-scoped: another firm's row of the same id is not this client's tax basis.
    register.rows("clients")[0]["firm_id"] = "OTHER"
    out = it.advance_tax_unforeseen_income(client_id="C", fy="2025-26", total_income_paise=1_50_000_000_00,
                                           current_user={"firm_id": "F"})["data"]
    assert out["candidates"][0]["surcharge_paise"] == 0
