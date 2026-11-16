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


def test_the_annual_exemption_is_used_once_across_the_years_112a_gains():
    # Two gains of ₹1,25,000 and ₹2,00,000: the exemption covers the first and ₹1,25,000 of the second.
    got, _ = uo.offer([_t("a", "2025-06-01", 1_25_000_00), _t("b", "2025-09-01", 2_00_000_00)], "2025-26", None)
    assert got[0].tax_before_surcharge_paise == 0
    assert got[1].tax_before_surcharge_paise == (3_25_000_00 - 1_25_000_00) * 1250 // 10_000 == 25_000_00
    assert sum(o.tax_before_surcharge_paise for o in got) == (3_25_000_00 - 1_25_000_00) * 1250 // 10_000


def test_the_order_is_the_order_the_gains_arose_not_the_order_given():
    got, _ = uo.offer([_t("late", "2025-09-01", 2_00_000_00), _t("early", "2025-06-01", 1_25_000_00)], "2025-26", None)
    assert [o.tax_before_surcharge_paise for o in got] == [25_000_00, 0]


def test_a_loss_in_the_section_nets_in_its_place():
    got, _ = uo.offer([_t("g1", "2025-05-01", 3_00_000_00), _t("loss", "2025-07-01", -2_00_000_00),
                       _t("g2", "2025-09-01", 2_00_000_00)], "2025-26", None)
    # running 3.0L -> tax on 1.75L; 1.0L -> nil (negative increment is not offered); 3.0L -> back to tax on 1.75L
    assert got[0].tax_before_surcharge_paise == 1_75_000_00 * 1250 // 10_000
    assert got[1].tax_before_surcharge_paise == 0
    assert got[2].tax_before_surcharge_paise == 1_75_000_00 * 1250 // 10_000


def test_a_gain_of_another_section_keeps_the_registers_figure():
    got, _ = uo.offer([_t("s", "2025-06-01", 5_00_000_00, section="Section 111A", engine_tax=1_00_000_00)], "2025-26", None)
    assert got[0].tax_before_surcharge_paise == 1_00_000_00


def test_the_surcharge_is_the_registry_bracket_for_the_total_income_given_and_capped_for_these_sections():
    gain = 2_00_000_00
    base = (gain - 1_25_000_00) * 1250 // 10_000
    # Total income 1.5 crore: ordinary bracket 15% (above 1 crore); the capital-gains cap is 15%.
    got, notes = uo.offer([_t("a", "2025-06-01", gain)], "2025-26", 1_50_000_000_00)
    assert got[0].surcharge_rate_percent == 15 and got[0].surcharge_paise == base * 15 // 100
    assert got[0].tax_paise == base + base * 15 // 100 + (base + base * 15 // 100) * 4 // 100
    assert any("marginal relief is not modelled" in n for n in notes)
    # Total income 6 crore: the bracket would be 25% and the cap holds it at 15.
    capped, _ = uo.offer([_t("a", "2025-06-01", gain)], "2025-26", 6_00_000_000_00)
    assert capped[0].surcharge_rate_percent == sr.RATES_BY_FY["2025-26"].capital_gains_surcharge_cap_percent == 15
    # Below every bracket: nothing.
    none, _ = uo.offer([_t("a", "2025-06-01", gain)], "2025-26", 40_00_000_00)
    assert none[0].surcharge_paise == 0 and none[0].surcharge_rate_percent == 0


def test_without_a_total_income_no_surcharge_is_offered_and_the_sentence_says_so():
    got, notes = uo.offer([_t("a", "2025-06-01", 2_00_000_00)], "2025-26", None)
    assert got[0].surcharge_paise == 0 and got[0].surcharge_rate_percent is None
    assert any("Surcharge is NOT included" in n for n in notes)


def test_a_slab_taxed_gain_gets_no_surcharge_and_the_sentence_says_why():
    got, notes = uo.offer([_t("d", "2025-06-01", 2_00_000_00, section="Section 50AA (Finance Act 2023)", engine_tax=60_000_00)],
                          "2025-26", 1_50_000_000_00)
    assert got[0].surcharge_paise == 0
    assert any("own slab" in n for n in notes)


def test_a_year_the_registry_does_not_hold_is_not_filled_with_another_years_figure():
    assert "2019-20" not in sr.RATES_BY_FY
    got, notes = uo.offer([_t("a", "2019-06-01", 5_00_000_00, engine_tax=77_00_000)], "2019-20", 1_50_000_000_00)
    assert got[0].tax_before_surcharge_paise == 77_00_000 and got[0].surcharge_paise == 0
    assert any(n == sr.fy_rate_gap("2019-20") for n in notes)
    assert any("NOT applied" in n for n in notes)


def test_a_held_but_unverified_year_applies_the_registry_and_says_it_is_unverified():
    assert sr.RATES_BY_FY["2026-27"].verified is False
    got, notes = uo.offer([_t("a", "2026-06-01", 2_00_000_00)], "2026-27", None)
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
