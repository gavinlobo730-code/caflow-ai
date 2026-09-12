"""TDS-22: s.194I and s.194J each charge two rates and only one key existed.

s.194I charges rent of PLANT, MACHINERY OR EQUIPMENT at a lower rate than rent
of land, buildings or furniture. s.194J charges fees for TECHNICAL services at
a lower rate than professional fees. The registry held one key per section, so
a CA could not record which limb a payment fell in — the 26Q deductee row went
out under the bare section, and a technical-services payment was
indistinguishable from a professional fee even where the CA knew which it was.

WHAT CHANGED AND WHAT DID NOT.

The machinery for a clause key — `parent_section`, `rate_gap`, `parent_of()` —
was already written and documented, and the recorded reason for not using it
was in two parts: the concessional RATE could not be confirmed, and neither
could the CLAUSE CODES ("an invented code on a statutory return is worse than
the over-deduction it would fix").

The second half is now answerable from a PRIMARY SOURCE INSIDE THIS
REPOSITORY: the Income Tax Department's own ITR-6 schema for AY 2026-27,
`domain/income_tax/schemas/ITR6_2026_Main_V1.0.json`, enumerates

    4-IA  : 194I(a) - Rent on hiring of plant and machinery
    4-IB  : 194I(b) - Rent on other than plant and machinery
    94J-A : 194J(a) - Fees for technical services
    94J-B : 194J(b) - Fees for professional services or royalty etc

The first half is NOT answered and this change does not pretend otherwise:
NOTHING here states 2%. The (a) limbs withhold at the parent's higher rate and
carry a `rate_gap` saying so, which OVER-deducts — the recoverable direction,
because an excess is the payee's to reclaim while an under-deduction disallows
the whole expenditure under s.40(a)(ia).
"""
import json
import pathlib

import pytest

from domain.tds.residency import deduction_section_refusal
from domain.tds.section_rates import parent_of, rate_gap_for, tds_rates_for

LIMBS = ("194I(A)", "194I(B)", "194J(A)", "194J(B)")
SCHEMA = (pathlib.Path(__file__).resolve().parents[1]
          / "domain/income_tax/schemas/ITR6_2026_Main_V1.0.json")


@pytest.mark.parametrize("limb", LIMBS)
def test_every_limb_is_in_the_registry(limb):
    assert limb in tds_rates_for("2026-27").sections


@pytest.mark.parametrize("limb,parent", [
    ("194I(A)", "194I"), ("194I(B)", "194I"),
    ("194J(A)", "194J"), ("194J(B)", "194J"),
])
def test_a_limb_aggregates_and_matches_challans_under_its_section(limb, parent):
    """The FY aggregate is the SECTION's — s.194J's proviso says "the aggregate
    of the sums" — and a challan says whatever the CA typed, which is "194J".
    A vendor moved from the bare section to a limb mid-year must not lose the
    year's running total."""
    assert parent_of(limb) == parent


def test_the_keys_are_found_whatever_case_they_are_written_in():
    """Every lookup in the module is `.upper().strip()`, so a LOWER-CASE key in
    the registry is never found — and the failure is silent: parent_of() falls
    through to returning the key unchanged, the FY aggregate quietly becomes
    per-clause, and the withholding drops below the section's. That happened
    while writing this."""
    assert parent_of("194j(a)") == "194J"
    assert parent_of("194I(b)") == "194I"
    assert rate_gap_for("194j(a)") is not None


@pytest.mark.parametrize("limb", ("194I(A)", "194J(A)"))
def test_the_concessional_limb_names_its_gap_and_does_not_invent_a_rate(limb):
    rule = tds_rates_for("2026-27").sections[limb]
    parent = tds_rates_for("2026-27").sections[parent_of(limb)]
    assert rule.rate_gap, "a limb whose rate is not held must say so"
    assert rule.company_rate_bps == parent.company_rate_bps, (
        "it withholds at the parent's higher rate — over-deducting, which is "
        "the recoverable direction")
    assert rule.individual_rate_bps == parent.individual_rate_bps


@pytest.mark.parametrize("limb", ("194I(B)", "194J(B)"))
def test_the_ordinary_limb_is_complete_and_carries_no_gap(limb):
    """194I(b) IS the land/building/furniture rent the parent's 10% is, and
    194J(b) IS the professional fee. Selecting them gets the right withholding
    AND the right clause, so warning about a rate that is correct would train
    a CA to ignore the warning."""
    rule = tds_rates_for("2026-27").sections[limb]
    assert rule.rate_gap is None
    assert rule.company_rate_bps == tds_rates_for("2026-27").sections[parent_of(limb)].company_rate_bps


def test_nothing_in_the_registry_states_the_concessional_rate():
    """The whole point. 200 bps must not appear on any 194I or 194J key —
    writing a rate nobody checked against the Finance Act is the thing this
    module refuses to do."""
    for key, rule in tds_rates_for("2026-27").sections.items():
        if key.startswith(("194I", "194J")):
            assert rule.company_rate_bps != 200, key
            assert rule.individual_rate_bps != 200, key


def test_the_bare_section_still_warns_and_now_says_what_to_choose():
    """The bare key means the CA has not said which limb, so the warning is
    still right — it might be plant and machinery."""
    for parent in ("194I", "194J"):
        gap = rate_gap_for(parent)
        assert gap and f"{parent}(a)" in gap and f"{parent}(b)" in gap, parent


@pytest.mark.parametrize("limb", LIMBS)
def test_a_limb_may_be_recorded_against_a_vendor(limb):
    """s.192 and s.206C are the two refusals; a rent or fee clause is not one."""
    assert deduction_section_refusal(limb) is None


# ── what the vendor dropdown is served ───────────────────────────────────────

@pytest.mark.parametrize("limb", LIMBS)
def test_a_limb_is_still_eligible_for_a_lower_deduction_certificate(limb):
    """s.197(1) names SECTIONS. Telling a CA that a plant-hire payment cannot
    carry a s.197 certificate BECAUSE they recorded which kind of rent it was
    would be a new defect created by adding the limb."""
    import inspect
    from routers import tds as r
    src = inspect.getsource(r.list_tds_sections)
    assert "parent_of(sec, fy) in SECTIONS_197" in src, (
        "s.197 eligibility is decided on the key, so every clause limb reads "
        "as ineligible")


def test_the_dropdown_is_told_which_limb_has_no_rate_of_its_own():
    import inspect
    from routers import tds as r
    src = inspect.getsource(r.list_tds_sections)
    assert '"rate_gap": rule.rate_gap' in src, (
        'offering "194J(a) — technical services" without saying the '
        "concessional rate is not modelled reads as a rate the software has")
    assert '"parent_section": parent_of(sec, fy)' in src


@pytest.mark.parametrize("code,label", [
    ("4-IA", "194I(a)"), ("4-IB", "194I(b)"),
    ("94J-A", "194J(a)"), ("94J-B", "194J(b)"),
])
def test_the_clause_labels_come_from_the_departments_own_schema(code, label):
    """The source, asserted rather than described. If the ITR-6 schema is
    replaced by a later version that spells these differently, this fails and
    the registry is re-read against it — which is the point of shipping the
    schema in the repository."""
    blob = SCHEMA.read_text()
    assert f"{code}:{label}" in blob.replace("  ", " "), (
        f"{code}:{label} is not in {SCHEMA.name} — the registry's clause keys "
        f"rest on it")
