"""§32(1)(iia) — 20% of cost, and the product could not claim a rupee of it.

WHAT WAS WRONG (IT-09)

    `domain/income_tax/section_32.py` has implemented the charge since it was
    written: 20% of the actual cost of new plant and machinery, halved by the
    second proviso where the asset was put to use for less than 180 days, with
    the third proviso's carry-forward named as a gap. `Addition` carries
    `additional_depreciation_eligible` and `compute_block` branches on it.

    `services/section_32_service.py` passed `False`. Hardcoded, for every
    addition, for every client. So the §32 screen rendered a headline row
    labelled "Additional u/s 32(1)(iia)" that was structurally ₹0 — a nil
    meaning "we cannot see it" presented as a nil meaning "there was none", on
    a deduction worth a fifth of the cost of every new machine a manufacturer
    buys.

TWO FACTS, AND CONFLATING THEM IS THE MISTAKE THE COLUMN EXISTS TO PREVENT

    WHO   the assessee is engaged in manufacture, production, or the
          generation, transmission or distribution of power — the section's own
          opening words, a fact about the CLIENT.
    WHAT  new machinery or plant the first proviso does not exclude — a fact
          about one ASSET.

    Four answers, not two, and a reader has to be able to tell "the section
    does not reach this client" from "nobody has said".

NEGATIVE CONTROLS — all run against the code and reverted:
  * Read a NULL business fact as False -> the tri-state tests fail: the two
    reasons become one sentence.
  * OR the two halves instead of ANDing them -> the marked-asset-at-a-
    non-manufacturer test fails, claiming 20% the section does not give.
  * Drop the no-additions gate -> the false-alarm test fails; every client with
    no plant purchase reports a gap for ever.
  * Restore the hardcoded False in the service -> the end-to-end test fails.
  * Delete either control from its screen -> the two screen tests fail.
"""
from __future__ import annotations

from datetime import date

import pytest

from domain.income_tax import additional_depreciation as ad
from domain.income_tax.section_32 import Addition, Block, compute

FY_END = date(2026, 3, 31)
L = 1_00_000_00  # one lakh in paise


# ── the rate, pinned ─────────────────────────────────────────────────────────

def test_nothing_here_claims_to_be_verified():
    assert ad.VERIFIED is False
    assert "pinned by a test" in ad.UNVERIFIED_NOTE


def test_the_rate_is_twenty_per_cent_of_actual_cost():
    """Of the ACTUAL COST — not of the written-down value and not of the
    block, which is what makes it different from every other §32 figure."""
    assert ad.ADDITIONAL_DEPRECIATION_PERCENT == 20
    block = Block(key="plant", rate_percent=15, opening_wdv_paise=0,
                  additions=(Addition(label="LATHE", cost_paise=10 * L,
                                      put_to_use_date=date(2025, 5, 1),
                                      additional_depreciation_eligible=True),))
    out = compute([block], fy_end=FY_END)
    assert out.additional_depreciation_paise == 2 * L


# ── three states on the business fact, and they are three answers ────────────

def test_an_unrecorded_business_is_not_a_refusal():
    e = ad.assessee_is_within_the_section(None)
    assert e.reaches_the_assessee is False
    assert e.gaps == (ad.BUSINESS_NOT_RECORDED,)
    assert "Nobody has recorded" in e.gaps[0]


def test_a_recorded_no_is_an_answer_and_says_so():
    e = ad.assessee_is_within_the_section(False)
    assert e.reaches_the_assessee is False
    assert e.gaps == (ad.BUSINESS_OUTSIDE_THE_SECTION,)
    assert "not because nothing was bought" in e.gaps[0]


def test_the_two_reasons_are_not_interchangeable():
    """The whole point of the tri-state. One tells a CA to go and record
    something; the other tells them the nil is right."""
    assert ad.BUSINESS_NOT_RECORDED != ad.BUSINESS_OUTSIDE_THE_SECTION


def test_a_recorded_yes_carries_the_proviso_and_the_caveats():
    e = ad.assessee_is_within_the_section(True)
    assert e.reaches_the_assessee is True
    assert ad.THE_TICK_ASSERTS_THE_PROVISO in e.caveats
    assert ad.COMMENCEMENT_NOT_TESTED in e.caveats
    assert ad.UNVERIFIED_NOTE in e.caveats


def test_the_proviso_caveat_names_all_four_exclusions():
    """Four columns would be four more things to fill in for one answer, so
    the tick asserts all four and the answer says which."""
    text = ad.THE_TICK_ASSERTS_THE_PROVISO
    assert "used by any other person" in text          # (A)
    assert "guest house" in text                       # (B)
    assert "road transport vehicle" in text            # (C)
    assert "allowed as a deduction in one year" in text  # (D)


# ── both halves, ANDed ───────────────────────────────────────────────────────

@pytest.mark.parametrize("within, flag, expected", [
    (True, True, True),
    (True, False, False),
    (True, None, False),
    (False, True, False),
    (False, None, False),
])
def test_both_halves_are_required(within, flag, expected):
    assert ad.addition_is_eligible(
        assessee_within_section=within, asset_flag=flag) is expected


def test_a_marked_asset_at_a_client_the_section_does_not_reach_claims_nothing():
    """Not a contradiction to resolve: a CA may well mark their machines before
    recording the business, and the answer is simply nil until both are in."""
    assert ad.addition_is_eligible(
        assessee_within_section=False, asset_flag=True) is False


# ── the gate, which is what stops a permanent false alarm ────────────────────

def test_no_addition_asks_no_question():
    """§32(1)(iia) is 20% of the actual cost of an ADDITION, so a year with
    none claims nothing whatever the business is. Naming the unrecorded fact
    there would put a gap on every client who bought no plant, for ever — which
    is how a real gap comes to be ignored."""
    e = ad.report(section_32_1_iia_business=None, additions=[])
    assert e.gaps == ()
    assert e.reaches_the_assessee is False


def test_an_addition_with_no_business_recorded_asks():
    e = ad.report(section_32_1_iia_business=None,
                  additions=[("LATHE", None)])
    assert e.gaps == (ad.BUSINESS_NOT_RECORDED,)


def test_a_client_within_the_section_with_nothing_marked_is_told():
    e = ad.report(section_32_1_iia_business=True,
                  additions=[("LATHE", None), ("PRESS", None)])
    assert e.reaches_the_assessee is True
    assert e.gaps == (ad.NO_ASSET_IS_MARKED,)
    assert "nobody has said, not because there is none" in e.gaps[0]


def test_a_partly_marked_year_names_the_unanswered_assets():
    e = ad.report(section_32_1_iia_business=True,
                  additions=[("LATHE", True), ("PRESS", None)])
    assert len(e.gaps) == 1
    assert "PRESS" in e.gaps[0]
    assert "LATHE" not in e.gaps[0]
    assert "An unanswered asset is not a refused one" in e.gaps[0]


def test_a_fully_marked_year_has_no_gap():
    e = ad.report(section_32_1_iia_business=True,
                  additions=[("LATHE", True), ("PRESS", False)])
    assert e.gaps == ()
    assert e.reaches_the_assessee is True


# ── the second proviso still runs, and the third is still named ──────────────

def test_a_short_period_addition_takes_half_and_says_where_the_rest_went():
    """Put to use after 3 October: the second proviso halves it, and the third
    allows the other half in the FOLLOWING year — which this engine does not
    carry forward, and says so."""
    block = Block(key="plant", rate_percent=15, opening_wdv_paise=0,
                  additions=(Addition(label="PRESS", cost_paise=10 * L,
                                      put_to_use_date=date(2026, 1, 15),
                                      additional_depreciation_eligible=True),))
    out = compute([block], fy_end=FY_END)
    assert out.additional_depreciation_paise == 1 * L
    assert any("FOLLOWING previous year" in g for g in out.gaps)


def test_the_module_names_the_carry_forward_it_does_not_do():
    assert "FOLLOWING previous year" in ad.THIRD_PROVISO_NOT_CARRIED_FORWARD


# ── the service, end to end ──────────────────────────────────────────────────

def _svc_answer(*, business, asset_flag, put_to_use="2025-05-01"):
    from services.section_32_service import section_32_service
    from tests.e2e_harness import FakeDB

    db = FakeDB()
    db.table("clients").insert({
        "id": "C1", "firm_id": "F1", "client_name": "Acme",
        "section_32_1_iia_business": business}).execute()
    db.table("income_tax_asset_blocks").insert({
        "id": "B1", "firm_id": "F1", "client_id": "C1",
        "financial_year": "2025-26", "block_key": "plant",
        "rate_percent": 15, "opening_wdv_paise": 0,
        "assets_remain": True}).execute()
    db.table("fixed_assets").insert({
        "id": "A1", "firm_id": "F1", "client_id": "C1",
        "asset_code": "LATHE", "asset_name": "Lathe",
        "purchase_cost_paise": 10 * L, "purchase_date": "2025-05-01",
        "put_to_use_date": put_to_use, "it_block_key": "plant",
        "additional_depreciation_eligible": asset_flag}).execute()
    return section_32_service.assemble(db, "F1", "C1", "2025-26")


def test_the_service_claims_it_where_both_facts_are_in():
    out = _svc_answer(business=True, asset_flag=True)
    assert out["additional_depreciation_paise"] == 2 * L
    assert out["additional_depreciation"]["reaches_the_assessee"] is True
    assert out["additional_depreciation"]["gaps"] == []


def test_the_service_withholds_it_and_names_the_business():
    """THE DEFECT ITSELF. Before IT-09 this answered ₹0 with no sentence, on
    every client, for ever."""
    out = _svc_answer(business=None, asset_flag=True)
    assert out["additional_depreciation_paise"] == 0
    assert ad.BUSINESS_NOT_RECORDED in out["additional_depreciation"]["gaps"]
    # And the gap reaches the CA through the field the screen already renders.
    assert ad.BUSINESS_NOT_RECORDED in out["statutory_gaps"]
    assert out["is_complete"] is False


def test_the_business_gap_comes_first_because_it_settles_every_asset():
    out = _svc_answer(business=None, asset_flag=None)
    assert out["statutory_gaps"][0] == ad.BUSINESS_NOT_RECORDED


def test_a_client_outside_the_section_gets_the_other_sentence():
    out = _svc_answer(business=False, asset_flag=True)
    assert out["additional_depreciation_paise"] == 0
    assert ad.BUSINESS_OUTSIDE_THE_SECTION in out["statutory_gaps"]


def test_the_working_is_served_in_mock_mode_too():
    """A screen reading it must not have to branch on which backend answered."""
    import routers.income_tax as it
    caller = {"firm_id": "F1", "id": "u1", "auth_user_id": "a1",
              "email": "ca@f.test", "role": "Partner"}
    res = it.section_32_depreciation("C1", "2025-26", caller)
    assert "additional_depreciation" in res["data"]
    assert set(res["data"]["additional_depreciation"]) == {
        "reaches_the_assessee", "gaps", "caveats", "verified"}


# ── the doors ────────────────────────────────────────────────────────────────

def test_there_is_no_second_door_for_the_asset_half():
    """A dedicated endpoint for it was written and DELETED.

    The ordinary asset PATCH already carries the column — Tier A, so it runs
    the same rbac(), tier rules and period checks as every other
    classification on the row — and a second endpoint writing one column of
    `fixed_assets` is a second write path for one fact. That is the
    `public.suppliers` shape: one screen writing a column no other path reads,
    found months later when a CA's answer had been going nowhere.

    The repo's own reachability ratchet is what caught it: the endpoint had no
    caller, because the asset form had always gone through the ordinary door.
    """
    import routers.income_tax as it
    assert not hasattr(it, "set_additional_depreciation_eligibility")
    assert not hasattr(it, "AdditionalDepreciationIn")


def test_the_business_door_is_firm_scoped():
    """The service key bypasses RLS, so `.eq(\"firm_id\", …)` is the isolation
    rather than a hint."""
    import inspect
    import routers.income_tax as it
    src = inspect.getsource(it.set_section_32_1_iia_business)
    assert 'eq("firm_id", current_user["firm_id"])' in src
    assert "assert_client_access" in src


def test_the_business_door_takes_a_bare_bool_and_offers_no_shrug():
    """NULL is what a client ARRIVES in — there is nothing to send to reach it,
    and offering a "don't know" would invite somebody to answer the question
    with a shrug and make the gap look settled."""
    import routers.income_tax as it
    field = it.Section32BusinessIn.model_fields["section_32_1_iia_business"]
    assert field.annotation is bool


def test_the_asset_field_is_on_both_doors():
    """A field on the create door alone is one edit away from being neither,
    and a CA answering §32(1)(iia) after the asset was entered is the ordinary
    case."""
    from models.accounting import FixedAssetIn, FixedAssetUpdateIn
    for model in (FixedAssetIn, FixedAssetUpdateIn):
        assert "additional_depreciation_eligible" in model.model_fields, model


def test_the_asset_field_is_tier_a():
    """It changes no Companies Act figure and posts nothing — §32 is a
    different system, per BLOCK, and it reads the fact itself."""
    from routers.fixed_assets import _TIER_A_FIELDS, _TIER_B_FIELDS, _TIER_C_FIELDS
    assert "additional_depreciation_eligible" in _TIER_A_FIELDS
    assert "additional_depreciation_eligible" not in _TIER_B_FIELDS
    assert "additional_depreciation_eligible" not in _TIER_C_FIELDS


# ── the screens ──────────────────────────────────────────────────────────────

def _web(path: str) -> str:
    import pathlib
    return (pathlib.Path(__file__).resolve().parents[2] / "web" / path
            ).read_text(encoding="utf-8")


def test_the_section_32_screen_records_the_business_and_renders_the_reason():
    src = _web("app/income-tax/section-32/page.tsx")
    assert "/api/income-tax/section-32/business" in src
    assert "additional_depreciation" in src
    # The sentence is the SERVER's — a screen spelling its own would be a
    # second copy of the section.
    assert "additional_depreciation.gaps" in src


def test_the_asset_form_offers_the_three_states_and_sends_undefined_for_one():
    """`undefined` where nobody has answered, never false. Sending false would
    settle the question with a shrug, which is the defect IT-09 closes."""
    src = _web("app/clients/[id]/fixed-assets/page.tsx")
    assert "additional_depreciation_eligible" in src
    start = src.index("additional_depreciation_eligible:\n")
    assert "undefined" in src[start:start + 260]


def test_neither_screen_spells_the_rate():
    """Zero business logic in the frontend. The 20% is the server's; a literal
    here would be a second copy of the Act."""
    for path in ("app/income-tax/section-32/page.tsx",
                 "app/clients/[id]/fixed-assets/page.tsx"):
        src = _web(path)
        assert "* 0.2" not in src and "* 20" not in src, path


# ── IT-20: the engine's warnings reach BOTH screens that compute ─────────────
#
# `itr_engine` raises a sentence wherever an unverified conservative choice
# actually costs the client something. §80CCD(2) is the one IT-20 names: the
# 10% cap is the pre-2024 figure, the Finance (No. 2) Act 2024's 14% for a
# non-government employee under §115BAC(1A) could not be confirmed from this
# environment, and under-claiming is the safe direction — but safe is not the
# same as invisible.
#
# The computation tab has rendered `warnings` since IT-05. The deductions
# PLANNER read `deductions.*` and dropped them, so a CA planning a salary
# package saw the smaller deduction and no reason for it. That is the shape
# this repository keeps finding: one screen tells the truth and its twin does
# not.

def test_the_engine_still_raises_the_80ccd2_sentence_where_it_bites():
    from domain.income_tax.itr_engine import ITRComputeRequest, itr_engine
    r = itr_engine.compute(ITRComputeRequest(
        fy="2025-26", gross_salary_paise=20_00_000_00,
        employer_nps_80ccd2_paise=2_80_000_00,   # 14% of salary
        is_government_employee=False, use_new_regime=True))
    assert any("80CCD(2)" in w for w in r.warnings), r.warnings


def test_it_is_silent_where_the_two_percentages_agree():
    """Raised only where it BITES. A warning on every computation is noise,
    and noise is how a real one comes to be ignored."""
    from domain.income_tax.itr_engine import ITRComputeRequest, itr_engine
    r = itr_engine.compute(ITRComputeRequest(
        fy="2025-26", gross_salary_paise=20_00_000_00,
        employer_nps_80ccd2_paise=1_00_000_00,   # under 10%
        is_government_employee=False, use_new_regime=True))
    assert not any("80CCD(2)" in w for w in r.warnings), r.warnings


@pytest.mark.parametrize("screen", [
    "app/clients/[id]/tax/computation/page.tsx",
    "app/income-tax/deductions/page.tsx",
])
def test_every_screen_that_computes_renders_what_the_engine_said(screen):
    """THE RULE, not a spelling of it: a screen calling /api/income-tax/compute
    READS the response's `warnings` and RENDERS them. Naming only the
    §80CCD(2) sentence would let the next unrendered warning through.

    Both halves are asserted, because the first draft of this checked only
    that the word "warnings" appeared in the file — and the negative control
    PASSED on a screen that had stopped reading them, since the derived
    variable was still called `serverWarnings`. A name left behind is not a
    behaviour, and this is the third time in one day that shape has slipped
    through a guard here.
    """
    import re
    src = _web(screen)
    assert "/api/income-tax/compute" in src or "computeITR" in src, screen
    assert re.search(r"[Rr]esult\??\.warnings", src), (
        f"{screen} does not read `warnings` off the compute response")
    assert re.search(r"[Ww]arnings[^\n]*\.map\(", src), (
        f"{screen} does not render the warnings it read")


def test_the_planner_does_not_decide_which_warnings_a_ca_may_see():
    """It renders the whole list. A screen filtering the server's warnings is a
    second copy of the engine's judgement about which of them matter."""
    src = _web("app/income-tax/deductions/page.tsx")
    start = src.index("const serverWarnings")
    block = src[start:start + 400]
    for banned in ("80CCD", "includes(", "startsWith("):
        assert banned not in block, (
            f"{banned} inside serverWarnings filters the engine's own list")
