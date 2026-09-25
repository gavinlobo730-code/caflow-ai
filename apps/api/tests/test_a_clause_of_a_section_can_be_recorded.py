"""TDS-22: s.194I and s.194J each charge two rates and only one key existed.

s.194I charges rent of PLANT, MACHINERY OR EQUIPMENT at a lower rate than rent
of land, buildings or furniture. s.194J charges fees for TECHNICAL services at
a lower rate than professional fees. The registry held one key per section, so
a CA could not record which limb a payment fell in — the 26Q deductee row went
out under the bare section, and a technical-services payment was
indistinguishable from a professional fee even where the CA knew which it was.

WHAT CHANGED IN TWO STEPS.

The machinery for a clause key — `parent_section`, `rate_gap`, `parent_of()` —
was already written and documented, and the recorded reason for not using it
was in two parts: the concessional RATE could not be confirmed, and neither
could the CLAUSE CODES ("an invented code on a statutory return is worse than
the over-deduction it would fix").

The second half was answered first, from a PRIMARY SOURCE INSIDE THIS
REPOSITORY: the Income Tax Department's own ITR-6 schema for AY 2026-27,
`domain/income_tax/schemas/ITR6_2026_Main_V1.0.json`, enumerates

    4-IA  : 194I(a) - Rent on hiring of plant and machinery
    4-IB  : 194I(b) - Rent on other than plant and machinery
    94J-A : 194J(a) - Fees for technical services
    94J-B : 194J(b) - Fees for professional services or royalty etc

so the four limbs went in with the (a) limbs withholding at the parent's
higher rate and a `rate_gap` saying the concessional rate was not held.

THE RATE IS NOW ANSWERED TOO (25-09-2026), and it closes the gap rather than
widening the model: the bare text of both sections, read directly from
incometaxindia.gov.in, states 194-I(a) at 2% (machinery, plant or equipment)
against 194-I(b) at 10%, and 194J's technical-services limb at 2% against its
professional-fee limb at 10%. Both (a) limbs now carry that rate and no
`rate_gap`. The BARE parent sections (194I, 194J — no clause recorded) still
carry a `rate_gap`, but its meaning changed: it is no longer "this software
does not hold the rate", it is "record which clause this is, because the bare
section cannot tell and defaults to the higher one".
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
    assert rate_gap_for("194j(a)") is None  # the concessional rate is confirmed now


@pytest.mark.parametrize("limb", LIMBS)
def test_every_limb_is_complete_and_carries_no_gap(limb):
    """194I(a) and 194J(a) are the concessional rates the Act's bare text
    confirms at 2%; 194I(b) and 194J(b) are the parent's own 10%. All four are
    complete: selecting any of them gets the right withholding AND the right
    clause, so warning about a rate that is correct would train a CA to ignore
    the warning."""
    rule = tds_rates_for("2026-27").sections[limb]
    assert rule.rate_gap is None


@pytest.mark.parametrize("limb,expected_bps", [
    ("194I(A)", 200), ("194I(B)", 1000),
    ("194J(A)", 200), ("194J(B)", 1000),
])
def test_each_limb_carries_its_own_confirmed_rate(limb, expected_bps):
    """The whole point of closing TDS-22's remaining half. 194I(a)/194J(a) no
    longer withhold at the parent's higher rate — they carry their own 2%,
    read from the bare Act text on incometaxindia.gov.in (Income-tax Act,
    1961), not a recollection and not the parent's placeholder."""
    rule = tds_rates_for("2026-27").sections[limb]
    assert rule.company_rate_bps == expected_bps
    assert rule.individual_rate_bps == expected_bps


def test_the_registry_now_states_the_concessional_rate():
    """The inverse of the old pin. 200 bps DOES appear now, and only on the two
    concessional limbs — not on the bare sections, which still default to the
    higher rate absent a recorded clause."""
    rates_2026_27 = tds_rates_for("2026-27")
    assert rates_2026_27.sections["194I(A)"].company_rate_bps == 200
    assert rates_2026_27.sections["194J(A)"].company_rate_bps == 200
    for bare in ("194I", "194J"):
        assert rates_2026_27.sections[bare].company_rate_bps == 1000, (
            f"the bare section {bare} still defaults to the higher rate — "
            f"only a recorded clause gets the concessional one")


def test_the_bare_section_still_warns_and_now_states_the_confirmed_rates():
    """The bare key means the CA has not said which limb, so the warning is
    still right — it might be plant and machinery, or a technical fee — and it
    now names the real numbers rather than saying the rate is unheld."""
    for parent in ("194I", "194J"):
        gap = rate_gap_for(parent)
        assert gap and f"{parent}(a)" in gap and f"{parent}(b)" in gap, parent
        assert "2%" in gap and "10%" in gap, (
            f"{parent}'s bare-section gap should now state the confirmed "
            f"rates so a CA reads a number, not a shrug")


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


def test_the_dropdown_still_carries_the_rate_gap_field():
    import inspect
    from routers import tds as r
    src = inspect.getsource(r.list_tds_sections)
    assert '"rate_gap": rule.rate_gap' in src, (
        "the field stays even though no clause limb uses it any more — the "
        "bare parent sections still do, and a screen offering \"194I\" with "
        "no clause needs the nudge to record one")
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
