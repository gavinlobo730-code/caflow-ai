"""
A section that charges two limbs at two rates must not price one silently.

WHAT WAS WRONG
    s.194I charges rent of PLANT, MACHINERY OR EQUIPMENT at a lower rate than
    rent of land, building, furniture or fittings. s.194J charges fees for
    TECHNICAL services at a lower rate than professional fees. The registry
    held ONE rate for each section — the higher one — so every plant rental and
    every technical engagement withheld at the professional/land rate and said
    nothing about it.

WHY THE FIX IS A NAMED GAP AND NOT A RATE
    Two refusals, and the second is the one that changed my mind mid-change.

    1. THE CONCESSIONAL RATE IS NOT HELD. This repository contradicted itself
       on s.194-I(a) — routers/assistant.py said 2%, domain/banking/matcher.py
       said 5% — and matcher's neighbouring s.194H figure of 5% is provably a
       Finance Act behind, which is what a wrong-and-confident rate looks like.
       s.194J's technical rate was stated consistently but only as prose, never
       as a registry number carrying the `verified` flag.

    2. A SPLIT KEY WOULD PUT AN INVENTED CODE ON A STATUTORY RETURN. The first
       attempt added "194I(A)" / "194J(BA)" keys. Those land on the 26Q
       deductee row as the section code the FVU reads, and the clause labels
       cannot be confirmed here either — so the fix for an over-deduction would
       have been a wrong code in a filed return. Backed out.

    So the withholding stays at the higher rate, which OVER-deducts, and the
    reason is said on the bill. Over-deducting is the recoverable direction —
    the excess is the payee's to reclaim — while under-deducting disallows the
    whole expenditure under s.40(a)(ia).

WHAT SHIPPED FOR THE SPLIT THAT DOES NOT EXIST YET
    parent_of() and TDSSectionRule.parent_section, plus the two call sites that
    would silently break the day somebody adds a limb key: the FY-aggregate
    query in routers/purchase_bills.py and the challan match in
    services/tds_return_service.py, both of which used to compare the section
    STRING. They are no-ops today and are tested against a synthetic rule, so
    the data change that adds a limb is safe rather than a second bug.
"""
from __future__ import annotations

import pytest

from domain.tds.section_rates import (TDSSectionRule, parent_of, rate_gap_for,
                                      tds_rates_for)
from domain.tds.tds_computer import TDSComputer

FYS = ("2025-26", "2026-27")
TWO_LIMB_SECTIONS = ("194I", "194J")

#: The concessional clause of each — the limb whose own rate this repository
#: does not hold. They withhold at the parent's higher rate and say so.
CONCESSIONAL_LIMBS = frozenset({"194I(A)", "194J(A)"})

#: Every clause key in the registry, and the section it belongs to. The
#: (b) limbs carry the rate the parent already holds, so they are complete and
#: warn about nothing; the (a) limbs are in CONCESSIONAL_LIMBS above.
ORDINARY_LIMBS = {
    "194I(A)": "194I", "194I(B)": "194I",
    "194J(A)": "194J", "194J(B)": "194J",
}


# ── The gap is named, and only where it is true ─────────────────────────────

@pytest.mark.parametrize("fy", FYS)
def test_both_two_limb_sections_carry_a_gap(fy):
    for section in TWO_LIMB_SECTIONS:
        gap = rate_gap_for(section, fy)
        assert gap, f"{section} charges two limbs at two rates and must say so"
        assert "OVER-deducted" in gap, (
            "the CA must be told the DIRECTION — an over-deduction is "
            "recoverable and an under-deduction disallows the expenditure")
        assert "nothing is blocked" in gap, (
            "and that the bill still books, or this reads as a refusal")


@pytest.mark.parametrize("fy", FYS)
def test_no_other_section_claims_a_limb_it_does_not_have(fy):
    """A gap on a single-limb section would be noise on every bill, and noise
    is how a real warning stops being read."""
    for section, rule in tds_rates_for(fy).sections.items():
        # The bare section carries the gap (the CA has not said which limb),
        # and so does the CONCESSIONAL limb (its own rate is not held). The
        # ordinary limb carries none, because the rate held IS its rate.
        if section in TWO_LIMB_SECTIONS or section in CONCESSIONAL_LIMBS:
            continue
        assert rule.rate_gap is None, f"{section} should carry no limb gap"


def test_the_gap_names_no_rate_for_the_limb_it_cannot_price():
    """The whole point. A sentence that ends '...is 2%' would be the third
    unverified figure in this repository, and the two that exist disagree."""
    for section in TWO_LIMB_SECTIONS:
        gap = rate_gap_for(section)
        assert "%" not in gap, (
            f"{section}'s gap quotes a percentage — it must not, because no "
            f"verified figure for the concessional limb exists here")


def test_the_gap_reaches_the_bill_that_it_is_about():
    """A gap that only exists in the registry is a comment. It has to arrive on
    the explanation the CA reads beside the figure."""
    from services.vendor_tds import resolve_resident_tds
    vendor = {"id": "v1", "pan": "AAACD1234E", "tds_applicable": True}
    why = resolve_resident_tds(
        vendor, "194J", 1_00_000_00, "2025-06-10", "f1", None, None).why
    assert "TECHNICAL services" in why
    assert "OVER-deducted" in why


def test_a_single_limb_section_says_nothing_extra():
    from services.vendor_tds import resolve_resident_tds
    vendor = {"id": "v1", "pan": "AAACD1234E", "tds_applicable": True}
    why = resolve_resident_tds(
        vendor, "194C", 5_00_000_00, "2025-06-10", "f1", None, None).why
    assert "OVER-deducted" not in why


# ── The machinery for a split that has not happened yet ─────────────────────

def test_parent_of_is_the_identity_for_everything_except_the_four_known_limbs():
    """This test used to read "no limb key exists yet, so parent_of must change
    nothing", and it fired when the four went in — which is what it was for.
    Rewritten rather than deleted: the claim is now that these four and ONLY
    these four are clauses, so a fifth added without reading the Act is still
    a visible act."""
    for fy in FYS:
        for section in tds_rates_for(fy).sections:
            expected = ORDINARY_LIMBS.get(section, section)
            assert parent_of(section, fy) == expected, section


def test_parent_of_answers_the_parent_for_a_limb_key(monkeypatch):
    """The mechanism, proved against a SYNTHETIC rule rather than a real one.

    The day somebody reads s.194-I(a) off the Finance Act and adds the key,
    two things must already work or the fix is a second bug: the FY aggregate
    must stay the SECTION's, and a challan the CA typed as "194I" must still
    match. Both ask parent_of. Testing that here means the data change is a
    data change.
    """
    import dataclasses
    from domain.tds import section_rates as sr

    real = tds_rates_for("2025-26")
    with_limb = dataclasses.replace(real, sections={
        **real.sections,
        "194I(A)": TDSSectionRule(50_000_00, 200, 200, parent_section="194I"),
    })
    monkeypatch.setattr(sr, "tds_rates_for", lambda fy=None: with_limb)

    assert sr.parent_of("194I(A)", "2025-26") == "194I"
    assert sr.parent_of("194I", "2025-26") == "194I"
    assert sr.parent_of("194C", "2025-26") == "194C"


def test_an_unknown_section_is_its_own_parent():
    """parent_of must never raise: it is called on whatever string a challan or
    a legacy row carries, and refusing an unknown section is
    deduction_section_refusal's job, not this one's."""
    assert parent_of("194ZZ") == "194ZZ"
    assert parent_of("") == ""
    assert parent_of("  194c  ") == "194C"


def test_a_limb_key_would_be_reachable_through_the_engines_normalisation():
    """THE MECHANICAL TRAP, pinned. resolve_tds upper-cases the section before
    looking it up, so a key written "194I(a)" is unreachable and every bill for
    that limb raises "Unknown TDS section". Whoever adds the limb must write
    the key in the case the engine normalises to.
    """
    computer = TDSComputer()
    for section in tds_rates_for("2025-26").sections:
        assert section == section.upper(), (
            f"{section!r} is not upper case, so resolve_tds cannot find it")
        # And it really does resolve, which is the property the case rule serves.
        computer.resolve_tds(section=section.lower(), taxable_paise=1_00_000_00,
                             fy="2025-26")
