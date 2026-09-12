"""
IT-16 — §44AD and §44ADA decide who they reach, instead of asking the CA to.

WHAT WAS WRONG

    Both engines computed the deemed income from the turnover, set `eligible`
    on the turnover ceiling alone, and appended a caveat to every result:
    "§44AD is available only to a resident individual, HUF or partnership firm
    (not an LLP) ... confirm before opting in."

    Nothing was reachable from a screen, so nobody had met it. Wiring the
    client tax-computation screen to these endpoints is what made it matter: a
    Private Limited company with ₹1 crore of turnover would have been shown
    `eligible: true`, a deemed income of ₹8,00,000, and a sentence asking the
    CA to check the one thing the client master already records.

    §44AD's Explanation (a) and §44ADA(1) both name the assessee. The client's
    entity type is on the record and `domain/income_tax/assessee.py` maps it.
    A figure the system holds and asks for anyway is a figure that will
    eventually be answered wrongly.

WHAT STAYS A CAVEAT, AND WHY

    Whether the business is a profession under §44AA(1), a commission or
    brokerage, or an agency. No record holds any of those, so they stay named
    gaps rather than becoming a guess — the same split as everywhere else here.

§44AE IS DELIBERATELY NOT GATED. It reaches "an assessee who owns not more
than ten goods carriages" — any person, a company included.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

import routers.income_tax as it
from domain.income_tax.presumptive import (
    ELIGIBLE_PRESUMPTIVE_ASSESSEES, compute_44ad, compute_44ada, compute_44ae,
)
from domain.income_tax.presumptive import GoodsCarriage

CALLER = {"id": "u1", "firm_id": "f1", "role": "Partner"}
FY = "2025-26"
CRORE = 1_00_00_000_00


def _44ad(**kw):
    return compute_44ad(fy=FY, turnover_paise=CRORE, **kw)


# ── who the sections reach ────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["individual", "firm"])
def test_the_assessees_the_section_names_are_eligible(kind):
    r = _44ad(assessee_kind=kind)
    assert r.eligible is True
    assert r.presumptive_income_paise == CRORE * 8 // 100


@pytest.mark.parametrize("kind", ["llp", "domestic_company"])
def test_an_llp_and_a_company_are_refused_by_name(kind):
    r = _44ad(assessee_kind=kind)
    assert r.eligible is False
    assert any("§44AD reaches" in x for x in r.reasons), r.reasons
    assert any(kind in x for x in r.reasons), "the refusal must name what was recorded"


def test_44ada_stops_in_the_same_place():
    ok = compute_44ada(fy=FY, gross_receipts_paise=40_00_000_00,
                       assessee_kind="individual")
    no = compute_44ada(fy=FY, gross_receipts_paise=40_00_000_00,
                       assessee_kind="llp")
    assert ok.eligible is True and no.eligible is False
    assert any("§44ADA reaches" in x for x in no.reasons)


def test_a_non_resident_is_refused_although_the_kind_fits():
    r = _44ad(assessee_kind="individual", is_resident=False)
    assert r.eligible is False
    assert any("RESIDENT" in x for x in r.reasons)


def test_44ae_is_not_gated_on_the_assessee():
    """§44AE names no assessee, so a company plying goods carriages is inside
    it. A kind test here would refuse a transporter the section charges."""
    r = compute_44ae(fy=FY, vehicles=[GoodsCarriage(gross_vehicle_weight_kg=16_500,
                                                    months_owned=12)])
    assert r.eligible is True
    assert "assessee_kind" not in it.Compute44AERequest.model_fields


def test_the_eligible_set_is_the_intersection_and_says_so():
    """A HUF is eligible in law and absent here because clients.entity_type has
    no value for one. Pinned so nobody 'completes' the set from the section."""
    assert ELIGIBLE_PRESUMPTIVE_ASSESSEES == frozenset({"individual", "firm"})


# ── what stays a caveat ───────────────────────────────────────────────────────

def test_the_facts_no_record_holds_are_still_named():
    r = _44ad(assessee_kind="individual")
    assert any("profession under §44AA(1)" in x for x in r.reasons)
    assert any("commission or brokerage" in x for x in r.reasons)


def test_the_assessee_caveat_is_dropped_once_the_assessee_is_stated():
    """Asking a CA to confirm something the engine has just decided teaches
    them the refusals are decorative."""
    stated = _44ad(assessee_kind="individual")
    unstated = _44ad()
    assert not any("not an LLP" in x for x in stated.reasons), stated.reasons
    assert any("not an LLP" in x for x in unstated.reasons), unstated.reasons


# ── the door ──────────────────────────────────────────────────────────────────

def test_the_two_endpoints_that_decide_on_it_require_it():
    for model in (it.Compute44ADRequest, it.Compute44ADARequest):
        assert model.model_fields["assessee_kind"].is_required(), (
            f"{model.__name__} must not let a caller omit the assessee — an "
            f"optional field puts the silent 'eligible' back")


def test_an_unknown_assessee_kind_is_refused_at_the_door():
    with pytest.raises(ValidationError):
        it.Compute44ADRequest(fy=FY, assessee_kind="trust", turnover_paise=CRORE)


def test_the_endpoint_carries_the_refusal_through():
    res = it.compute_presumptive_44ad(it.Compute44ADRequest(
        fy=FY, assessee_kind="domestic_company", turnover_paise=CRORE), CALLER)
    assert res["success"] is True
    assert res["data"]["eligible"] is False
    assert any("§44AD reaches" in x for x in res["data"]["reasons"])
