"""
What to withhold on a payment to a non-resident — IT Act s.195.

The order of the questions IS the substance, and each one has an expensive
wrong answer:

  1. chargeability — 20% on a plain import takes a fifth of a supplier's
     invoice for tax nobody owes (GE India Technology Centre v. CIT);
  2. nature of income — the Act rate keys on it, not on the kind of work;
  3. s.90(2) treaty relief — the lower of Act and agreement, and the agreement
     is a human input because this codebase holds no treaty table;
  4. s.206AA — the 20% no-PAN floor, and the Rule 37BC carve-out residents do
     not get;
  5. surcharge and cess — which the resident 194 series does not carry, and
     omitting them under-deducts on every foreign payment.
"""
from __future__ import annotations

import pytest

from domain.tds.section_195 import (
    REFUSED_NO_NATURE, REFUSED_NO_PE_DECLARATION, REFUSED_TREATY_RATE_UNKNOWN,
    REFUSED_UNKNOWN_NATURE, resolve_section_195,
)
from domain.tds.section_195_rates import (
    ALL_NATURES, LATEST_VERIFIED_FY, NATURE_BUSINESS_PROFITS_NO_PE,
    RATES_BY_FY, RULE_37BC_NATURES, rates_for,
)

TEN_LAKH = 10_00_000_00          # Rs 10,00,000 in paise
TWO_CRORE = 2_00_00_000_00


# ── 1. Chargeability, which comes before any rate ────────────────────────────

def test_business_profits_with_no_permanent_establishment_withhold_nil():
    """s.195 reaches only a sum 'chargeable under the provisions of this Act'.
    An ordinary import is business profits, and without a PE it is not
    chargeable here — GE India Technology Centre (P) Ltd v. CIT (2010)."""
    r = resolve_section_195(amount_paise=TEN_LAKH,
                            nature=NATURE_BUSINESS_PROFITS_NO_PE,
                            no_pe_declaration_on_file=True)
    assert r.applies is True and r.tds_paise == 0
    assert r.basis == "not_chargeable"
    assert "GE India" in r.citation


def test_a_nil_withholding_is_not_the_same_as_a_refusal():
    """applies=True with 0 is an ANSWER — nothing is due. applies=False is
    STOP. A caller that conflated them would book a bill on a refusal."""
    nil = resolve_section_195(amount_paise=TEN_LAKH,
                              nature=NATURE_BUSINESS_PROFITS_NO_PE,
                              no_pe_declaration_on_file=True)
    stop = resolve_section_195(amount_paise=TEN_LAKH, nature=None)
    assert nil.applies and nil.refusal is None
    assert not stop.applies and stop.refusal is not None


def test_the_nil_needs_its_evidence():
    """The largest claim in the module. Without a no-PE declaration it is an
    assertion about a foreign company's Indian presence that nobody made."""
    r = resolve_section_195(amount_paise=TEN_LAKH,
                            nature=NATURE_BUSINESS_PROFITS_NO_PE)
    assert not r.applies and r.refusal == REFUSED_NO_PE_DECLARATION


# ── 2. Nature of income ──────────────────────────────────────────────────────

def test_no_nature_is_a_refusal_not_a_zero():
    r = resolve_section_195(amount_paise=TEN_LAKH, nature=None)
    assert not r.applies and r.refusal == REFUSED_NO_NATURE
    assert r.tds_paise == 0, "a refusal must never carry a number to withhold"


def test_a_nature_the_table_does_not_price_is_a_refusal():
    r = resolve_section_195(amount_paise=TEN_LAKH, nature="consultancy")
    assert not r.applies and r.refusal == REFUSED_UNKNOWN_NATURE


@pytest.mark.parametrize("nature", ALL_NATURES)
def test_every_nature_in_the_registry_resolves(nature):
    """A nature the CHECK constraint allows and the engine cannot price would
    be a vendor that saves and a bill that never books."""
    r = resolve_section_195(amount_paise=TEN_LAKH, nature=nature,
                            no_pe_declaration_on_file=True)
    assert r.applies, f"{nature} is allowed on a vendor but has no rate"


def test_fts_to_a_foreign_company_is_twenty_percent_plus_cess():
    """Rs 10,00,000 FTS: 20% = Rs 2,00,000, no surcharge below Rs 1 crore,
    4% cess = Rs 8,000, total Rs 2,08,000."""
    r = resolve_section_195(amount_paise=TEN_LAKH,
                            nature="fees_for_technical_services", is_company=True)
    assert r.rate_bps == 2000
    assert r.base_tax_paise == 2_00_000_00
    assert r.surcharge_paise == 0
    assert r.cess_paise == 8_000_00
    assert r.tds_paise == 2_08_000_00
    assert r.effective_rate_bps == 2080


def test_other_sums_charge_a_foreign_company_more_than_a_non_corporate_payee():
    """The one nature whose Act rate depends on the payee class."""
    co = resolve_section_195(amount_paise=TEN_LAKH, nature="other_sums", is_company=True)
    ind = resolve_section_195(amount_paise=TEN_LAKH, nature="other_sums", is_company=False)
    assert co.rate_bps > ind.rate_bps


# ── 3. s.90(2) — the treaty ──────────────────────────────────────────────────

def test_a_trc_with_no_recorded_treaty_rate_refuses_rather_than_using_the_act():
    """Falling back to the Act rate here would over-deduct in exactly the case
    where somebody has already established that a treaty applies."""
    r = resolve_section_195(amount_paise=TEN_LAKH, nature="royalty",
                            is_company=True, trc_on_file=True)
    assert not r.applies and r.refusal == REFUSED_TREATY_RATE_UNKNOWN
    assert "does not hold treaty rates" in r.refusal_detail


def test_a_lower_treaty_rate_wins():
    r = resolve_section_195(amount_paise=TEN_LAKH, nature="royalty", is_company=True,
                            trc_on_file=True, form_10f_on_file=True,
                            treaty_rate_bps=1000)
    assert r.applies and r.rate_bps == 1000 and r.basis == "treaty"
    assert r.base_tax_paise == 1_00_000_00


def test_a_higher_treaty_rate_does_not_win():
    """s.90(2) gives the assessee whichever is MORE BENEFICIAL — it is not a
    licence for the treaty to raise the withholding above the Act."""
    r = resolve_section_195(amount_paise=TEN_LAKH, nature="royalty", is_company=True,
                            trc_on_file=True, form_10f_on_file=True,
                            treaty_rate_bps=3000)
    assert r.rate_bps == 2000 and r.basis == "act"


def test_a_treaty_rate_of_zero_is_honoured():
    """Several agreements tax nothing where there is no PE. Zero must not be
    read as 'unset' — that is why the parameter is Optional[int] and not an
    int defaulting to 0."""
    r = resolve_section_195(amount_paise=TEN_LAKH, nature="fees_for_technical_services",
                            is_company=True, trc_on_file=True,
                            form_10f_on_file=True, treaty_rate_bps=0)
    assert r.applies and r.tds_paise == 0 and r.basis == "treaty"


def test_no_trc_means_no_treaty_relief_and_is_not_a_refusal():
    """s.90(4): without a TRC there is no treaty relief, which is a complete
    answer rather than missing information."""
    r = resolve_section_195(amount_paise=TEN_LAKH, nature="royalty", is_company=True,
                            treaty_rate_bps=1000)
    assert r.applies and r.rate_bps == 2000 and r.basis == "act"


def test_a_missing_form_10f_is_reported_but_does_not_change_the_rate():
    """Rule 21AB wants the form; the treaty rate is still the operative one,
    and a missing document is something to chase rather than a reason to
    withhold at a different number."""
    r = resolve_section_195(amount_paise=TEN_LAKH, nature="royalty", is_company=True,
                            trc_on_file=True, treaty_rate_bps=1000)
    assert r.applies and r.rate_bps == 1000
    assert "Form 10F NOT on file" in r.citation


# ── 4. s.206AA and Rule 37BC ─────────────────────────────────────────────────

def test_no_pan_floors_the_rate_at_twenty_percent():
    r = resolve_section_195(amount_paise=TEN_LAKH, nature="interest_194lc",
                            is_company=True, has_pan=False)
    assert r.rate_bps == 2000 and r.basis == "206aa_floor"


def test_rule_37bc_lifts_the_floor_for_a_non_resident_who_furnished_the_particulars():
    """s.206AA(7) with Rule 37BC. A resident gets no such relief, which is why
    the floor cannot be applied uniformly across both."""
    r = resolve_section_195(amount_paise=TEN_LAKH, nature="interest_194lc",
                            is_company=True, has_pan=False,
                            rule_37bc_particulars_held=True)
    assert r.rate_bps == 500 and r.basis == "act"


def test_rule_37bc_does_not_reach_a_nature_it_does_not_list():
    """The relief is for interest, royalty, FTS and capital gains. 'Other
    sums' is not in it, so the floor stands."""
    assert "other_sums" not in RULE_37BC_NATURES
    r = resolve_section_195(amount_paise=TEN_LAKH, nature="other_sums",
                            has_pan=False, rule_37bc_particulars_held=True)
    assert r.rate_bps == 3000, "the Act rate already exceeds the floor here"


def test_the_floor_never_lowers_a_rate_that_is_already_higher():
    r = resolve_section_195(amount_paise=TEN_LAKH, nature="other_sums",
                            is_company=True, has_pan=False)
    assert r.rate_bps == 3500


def test_the_floor_does_not_resurrect_a_nil_on_business_profits():
    """Chargeability is answered before s.206AA is reached. A floor on a sum
    that is not chargeable would withhold 20% of an ordinary import from a
    supplier with no PAN — the worst outcome in this module."""
    r = resolve_section_195(amount_paise=TEN_LAKH,
                            nature=NATURE_BUSINESS_PROFITS_NO_PE,
                            has_pan=False, no_pe_declaration_on_file=True)
    assert r.tds_paise == 0


# ── 5. Surcharge and cess ────────────────────────────────────────────────────

def test_a_foreign_company_over_a_crore_carries_surcharge():
    """Part II First Schedule: 2% above Rs 1 crore for a foreign company."""
    r = resolve_section_195(amount_paise=TWO_CRORE, nature="fees_for_technical_services",
                            is_company=True)
    assert r.base_tax_paise == 40_00_000_00        # 20%
    assert r.surcharge_paise == 80_000_00          # 2%
    assert r.cess_paise == 1_63_200_00             # 4% of (base + surcharge)
    assert r.tds_paise == 42_43_200_00


def test_the_two_surcharge_ladders_are_not_the_same():
    """A non-corporate payee's ladder is far steeper than a foreign company's —
    37% at the top against 5%. Using the wrong one is a large error."""
    co = resolve_section_195(amount_paise=TWO_CRORE, nature="other_sums", is_company=True)
    ind = resolve_section_195(amount_paise=TWO_CRORE, nature="other_sums", is_company=False)
    co_pct = co.surcharge_paise * 100 // co.base_tax_paise
    ind_pct = ind.surcharge_paise * 100 // ind.base_tax_paise
    assert co_pct == 2 and ind_pct == 15


def test_capital_gains_surcharge_is_capped():
    """The same cap statutory_rates.py applies to a resident's capital gains."""
    capped = resolve_section_195(amount_paise=10_00_00_000_00, nature="ltcg_112")
    uncapped = resolve_section_195(amount_paise=10_00_00_000_00, nature="other_sums")
    cap_pct = capped.surcharge_paise * 100 // capped.base_tax_paise
    unc_pct = uncapped.surcharge_paise * 100 // uncapped.base_tax_paise
    assert cap_pct == 15 and unc_pct == 37


def test_cess_is_charged_on_tax_plus_surcharge_not_on_tax_alone():
    r = resolve_section_195(amount_paise=TWO_CRORE, nature="other_sums", is_company=True)
    assert r.cess_paise == (r.base_tax_paise + r.surcharge_paise) * 4 // 100


def test_the_total_is_the_three_components_and_nothing_else():
    r = resolve_section_195(amount_paise=TWO_CRORE, nature="royalty", is_company=True)
    assert r.tds_paise == r.base_tax_paise + r.surcharge_paise + r.cess_paise


def test_every_component_is_an_integer_number_of_paise():
    """CLAUDE.md: integer paise, never float. A rate of 12.5% on an odd amount
    is where a float would show up."""
    r = resolve_section_195(amount_paise=3_33_333_33, nature="ltcg_112")
    for v in (r.base_tax_paise, r.surcharge_paise, r.cess_paise, r.tds_paise):
        assert isinstance(v, int)


def test_withholding_never_exceeds_the_payment():
    """The rate-bound the resident engine has (audit L1), restated here where
    surcharge and cess sit on top of the base."""
    for nature in ALL_NATURES:
        r = resolve_section_195(amount_paise=TEN_LAKH, nature=nature, is_company=True,
                                no_pe_declaration_on_file=True)
        assert r.tds_paise <= TEN_LAKH, nature


# ── The registry itself ──────────────────────────────────────────────────────

def test_nothing_in_this_registry_claims_to_be_verified():
    """Deliberate, and the point of the module docstring. These figures were
    reconciled, not checked line by line against the Finance Act's Part II
    First Schedule. Flipping a year to verified=True is a claim a human makes."""
    for fy, rates in RATES_BY_FY.items():
        assert rates.verified is False, (
            f"{fy} is marked verified — if somebody confirmed it against the "
            f"Finance Act, this test should be the thing they updated too")


def test_a_year_the_registry_does_not_hold_falls_back_and_says_so():
    """The trap CLAUDE.md names: a missing year is not an error, it is last
    year's rates returned confidently. `.fy` is how a caller can tell."""
    got = rates_for("2031-32")
    assert got.fy == LATEST_VERIFIED_FY != "2031-32"


def test_every_nature_carries_the_provision_it_comes_from():
    """CLAUDE.md: all GST/ITR logic must cite the relevant section."""
    for nature, rule in rates_for("2025-26").natures.items():
        assert rule.citation.strip(), f"{nature} has no citation"
        assert ("s.1" in rule.citation or "First Schedule" in rule.citation
                or "v. CIT" in rule.citation), f"{nature}: {rule.citation!r}"


def test_the_resolution_reports_which_year_it_priced_on():
    r = resolve_section_195(amount_paise=TEN_LAKH, nature="royalty", fy="2025-26")
    assert r.fy == "2025-26" and r.rates_verified is False


# ── Saying so where the money moves ─────────────────────────────────────────

def test_rates_are_verified_answers_about_the_year_that_was_asked_for(monkeypatch):
    """rates_for() falls back to the last held year, and a fallback is by
    definition not a confirmation of the year asked about. Reaching into
    rates_for(fy).verified would report the FALLBACK year's status.

    A year has to be marked verified for this to be detectable at all — while
    every entry is False, both readings agree by accident. So one is flipped
    here, which is also what makes this test survive the day a real year is
    confirmed.
    """
    import dataclasses
    from domain.tds import section_195_rates as m

    verified_2025 = dataclasses.replace(m.RATES_BY_FY["2025-26"], verified=True)
    monkeypatch.setitem(m.RATES_BY_FY, "2025-26", verified_2025)

    assert m.rates_are_verified("2025-26") is True
    # 2031-32 is not held, so rates_for() hands back the (now verified) 2025-26
    # entry. Asking about 2031-32 must still answer about 2031-32.
    assert m.rates_for("2031-32").verified is True
    assert m.rates_are_verified("2031-32") is False


def test_coverage_lists_every_year_and_its_status():
    from domain.tds.section_195_rates import coverage
    got = coverage()
    assert [y["fy"] for y in got] == sorted(RATES_BY_FY)
    assert all(y["verified"] is False for y in got)
    assert all(y["natures"] == len(ALL_NATURES) for y in got)


def test_a_195_deduction_reports_that_its_rates_were_never_confirmed():
    """A CA about to pay a challan should be told the rate was reconciled and
    not verified. Not a refusal — refusing every foreign payment until somebody
    reads Part II would stop the work rather than inform it."""
    from datetime import date
    from domain.tds.residency import GAP_195_RATES_UNVERIFIED
    from services.tds_register_service import sync_for_bill

    class _DB:
        def table(self, n): return self
        def upsert(self, *a, **k): return self
        def delete(self): return self
        def eq(self, *a): return self
        def execute(self): return type("R", (), {"data": []})()

    out = sync_for_bill(_DB(), "f1", "c1", {
        "id": "b1", "client_id": "c1", "status": "received",
        "bill_date": "2025-10-25", "taxable_amount_paise": 10_00_000_00,
        "tds_paise": 2_08_000_00, "tds_rate_bps": 2000, "tds_section": "195",
    }, {"id": "v1", "name": "Helvetica AG", "residential_status": "non_resident",
        "country_of_residence": "CH", "tax_identification_number": "T1"})
    assert GAP_195_RATES_UNVERIFIED in out["statutory_gaps"]


def test_a_resident_section_deduction_does_not_report_it():
    """The negative control: 194C's rates carry their own verification status
    and this gap is about s.195's registry only."""
    from domain.tds.residency import GAP_195_RATES_UNVERIFIED
    from services.tds_register_service import sync_for_bill

    class _DB:
        def table(self, n): return self
        def upsert(self, *a, **k): return self
        def delete(self): return self
        def eq(self, *a): return self
        def execute(self): return type("R", (), {"data": []})()

    out = sync_for_bill(_DB(), "f1", "c1", {
        "id": "b1", "client_id": "c1", "status": "received",
        "bill_date": "2025-10-25", "taxable_amount_paise": 18_000_00,
        "tds_paise": 360_00, "tds_rate_bps": 200, "tds_section": "194C",
    }, {"id": "v1", "name": "Pinnacle", "pan": "AAGCP7788R",
        "residential_status": "resident"})
    assert GAP_195_RATES_UNVERIFIED not in out.get("statutory_gaps", [])


def test_the_coverage_endpoint_reports_both_registries():
    """So a firm can see it without reading a Python docstring."""
    from routers.tds import tds_rate_coverage
    data = tds_rate_coverage(user={"firm_id": "f1"})["data"]
    assert data["section_195"]["any_verified"] is False
    assert data["section_195"]["years"]
    assert data["resident_sections"]["years"]


# ── The nil, and Rule 37BB, become auditable ────────────────────────────────

class _RegDB:
    def table(self, n): return self
    def upsert(self, *a, **k): return self
    def delete(self): return self
    def eq(self, *a): return self
    def execute(self): return type("R", (), {"data": []})()


def _sync195(bill_over=None, vendor_over=None):
    from services.tds_register_service import sync_for_bill
    bill = {"id": "b1", "client_id": "c1", "status": "received",
            "bill_date": "2025-10-25", "taxable_amount_paise": 10_00_000_00,
            "tds_paise": 2_08_000_00, "tds_rate_bps": 2000, "tds_section": "195",
            "form_15ca_ack_no": "ACK123"}
    vendor = {"id": "v1", "name": "Helvetica AG", "residential_status": "non_resident",
              "country_of_residence": "CH", "tax_identification_number": "T1"}
    bill.update(bill_over or {})
    vendor.update(vendor_over or {})
    return sync_for_bill(_RegDB(), "f1", "c1", bill, vendor)


def test_a_nil_on_an_undated_declaration_is_reported():
    """s.201(1) makes a deductor who fails to deduct an assessee in default and
    s.201(1A) charges interest, so the consequence of a wrong nil sits with the
    DEDUCTOR — and a ticked box answers neither who nor when."""
    from domain.tds.residency import GAP_NO_PE_DECLARATION_UNDATED
    out = _sync195(vendor_over={"no_pe_declaration_on_file": True})
    assert GAP_NO_PE_DECLARATION_UNDATED in out["statutory_gaps"]


def test_a_dated_and_attributed_declaration_is_not_reported():
    from domain.tds.residency import GAP_NO_PE_DECLARATION_UNDATED
    out = _sync195(vendor_over={"no_pe_declaration_on_file": True,
                                "no_pe_declaration_on": "2025-04-10",
                                "no_pe_declaration_by": "u1"})
    assert GAP_NO_PE_DECLARATION_UNDATED not in out.get("statutory_gaps", [])


def test_a_date_without_a_declarer_is_still_incomplete():
    """Both halves, or neither answers the question that gets asked."""
    from domain.tds.residency import GAP_NO_PE_DECLARATION_UNDATED
    out = _sync195(vendor_over={"no_pe_declaration_on_file": True,
                                "no_pe_declaration_on": "2025-04-10"})
    assert GAP_NO_PE_DECLARATION_UNDATED in out["statutory_gaps"]


def test_a_vendor_holding_no_declaration_at_all_is_not_reported_for_it():
    """Only where the nil was actually RELIED ON. A vendor withheld at a rate
    has not used a declaration, so asking it to date one is noise."""
    from domain.tds.residency import GAP_NO_PE_DECLARATION_UNDATED
    assert GAP_NO_PE_DECLARATION_UNDATED not in _sync195().get("statutory_gaps", [])


def test_a_foreign_remittance_with_no_15ca_recorded_is_reported():
    """Rule 37BB with s.195(6) wants it BEFORE the money leaves. Nothing blocks
    the bill — 15CA is a portal submission and CLAUDE.md forbids submitting to
    one from here — but the gap must not be invisible."""
    from domain.tds.residency import GAP_FORM_15CA_NOT_RECORDED
    out = _sync195(bill_over={"form_15ca_ack_no": None})
    assert GAP_FORM_15CA_NOT_RECORDED in out["statutory_gaps"]


def test_a_recorded_15ca_clears_it():
    from domain.tds.residency import GAP_FORM_15CA_NOT_RECORDED
    assert GAP_FORM_15CA_NOT_RECORDED not in _sync195().get("statutory_gaps", [])


def test_a_domestic_bill_is_asked_for_none_of_this():
    """Rule 37BB is about remittances to non-residents. A 194C bill carrying
    these gaps would bury the real ones."""
    from domain.tds.residency import (
        GAP_FORM_15CA_NOT_RECORDED, GAP_NO_PE_DECLARATION_UNDATED,
        GAP_195_RATES_UNVERIFIED)
    out = _sync195(
        bill_over={"tds_section": "194C", "tds_rate_bps": 200,
                   "tds_paise": 360_00, "form_15ca_ack_no": None},
        vendor_over={"residential_status": "resident", "pan": "AAGCP7788R",
                     "no_pe_declaration_on_file": True})
    gaps = out.get("statutory_gaps", [])
    for code in (GAP_FORM_15CA_NOT_RECORDED, GAP_NO_PE_DECLARATION_UNDATED,
                 GAP_195_RATES_UNVERIFIED):
        assert code not in gaps
