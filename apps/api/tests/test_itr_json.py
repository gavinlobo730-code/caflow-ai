"""
ITR return payload — and the refusal to emit a file against a schema this
product does not hold.

The Income Tax Department publishes the ITR JSON schema per assessment year and
per form, with exact field names and nesting. This codebase does not have it:
the department's site is unreachable from the environment this was written in
(the network egress policy refuses www.incometax.gov.in with a 403), so field
names could only have been written from memory.

A file with invented field names is not a near-miss. It is either rejected at
upload — wasting a CA's time and teaching them the product cannot be trusted —
or accepted with values in the wrong fields, which is a wrong return filed
under a client's name and a CA's signature.

So the values are computed and the file is refused, in the same spirit as
statutory_rates marking an unconfirmed year, filing_demo's SIM-NOT-FILED, and
domain/udin declining to mint a number.
"""
import pytest

from domain.income_tax.itr_json import (
    FIELD_MAPPINGS, FieldMapping, ReturnIncomplete, SchemaNotVerified,
    SoftwareProviderNotRegistered, build_itr_payload, generate_itr_json,
    itr_field_placements, software_provider_id,
)

L = 1_00_000_00


def _payload(form: str = "ITR-6"):
    """A payload with a non-zero figure in every slot the tests read."""
    return build_itr_payload(
        form=form,
        gross_total_income_paise=12_00_000_00,
        total_deductions_paise=1_50_000_00,
        total_income_paise=10_50_000_00,
        tax_on_total_income_paise=1_32_600_00,
        cess_paise=5_304_00,
        total_tax_paise=1_37_904_00,
        interest_234a_paise=1_000_00,
        interest_234b_paise=2_000_00,
        interest_234c_paise=3_000_00,
    )


# ── The values are real and complete ─────────────────────────────────────────

def test_the_payload_carries_the_figures_a_return_needs():
    p = build_itr_payload(form="ITR-4", gross_total_income_paise=50 * L,
                          total_income_paise=45 * L, total_tax_paise=5 * L)
    d = p.as_dict()
    assert d["gross_total_income"] == 50 * L
    assert d["total_income"] == 45 * L
    assert d["total_tax"] == 5 * L


def test_every_figure_names_its_schedule_and_its_section():
    """A payload a CA cannot trace back to the Act is a list of numbers, and
    one they cannot place in the return is worse than useless."""
    p = build_itr_payload(form="ITR-4")
    for v in p.values:
        assert v.schedule.strip(), v.key
        assert v.reference.strip(), v.key


def test_the_figures_are_grouped_by_schedule():
    p = build_itr_payload(form="ITR-4")
    schedules = p.by_schedule()
    assert "Part B-TI" in schedules
    assert "Part B-TTI" in schedules
    assert "Schedule VI-A" in schedules


def test_the_three_interest_sections_are_carried_separately():
    """§234A, §234B and §234C are separate lines in the return, and this
    product now computes all three — conflating them here would undo that."""
    p = build_itr_payload(form="ITR-4", interest_234a_paise=1 * L,
                          interest_234b_paise=2 * L, interest_234c_paise=3 * L)
    d = p.as_dict()
    assert (d["interest_234a"], d["interest_234b"], d["interest_234c"]) == (
        1 * L, 2 * L, 3 * L)


def test_amounts_stay_in_paise():
    """The rupee conversion the schema requires is deliberately NOT done here.
    Rounding belongs at the payload boundary, and applying it before that
    boundary is known would bake in a convention that may not be the
    schema's."""
    p = build_itr_payload(form="ITR-4", total_tax_paise=1_23_45_678)
    assert p.as_dict()["total_tax"] == 1_23_45_678
    assert all(isinstance(v.amount_paise, int) for v in p.values)


# ── The refusal ──────────────────────────────────────────────────────────────

# ── The mapping (rewritten when the schemas arrived) ──────────────────────────
#
# These tests used to assert the OPPOSITE of what they assert now — that no
# mapping was verified, that none carried a field name, that none had a schema
# version. Every one of those was true and correct when written: the department's
# site is blocked from this environment, so the field names could only have been
# guessed, and an empty mapping was the honest thing to hold.
#
# The schemas for AY 2026-27 have since been downloaded by hand and committed to
# domain/income_tax/schemas/. The old assertions are therefore now false, and
# keeping them would have meant either refusing real schemas or asserting a
# fiction. They are replaced here, with the reason recorded rather than quietly
# deleted. tests/test_itr_schema_paths.py is what now does the real work: it
# checks every path against the department's own document.


def test_every_mapping_is_verified_against_a_committed_schema():
    for form, mapping in FIELD_MAPPINGS.items():
        assert mapping.verified is True, form
        assert mapping.schema_version == "Ver1.0", form
        assert mapping.schema_file, form
        assert mapping.paths, form


def test_a_mapping_records_which_schema_revision_it_is_true_of():
    """The portal revises schemas mid-year, so "verified" without a revision is
    a claim with no expiry. schema_file names the exact committed document."""
    m = FIELD_MAPPINGS["ITR-6"]
    assert m.schema_file == "ITR6_2026_Main_V1.0.json"
    assert m.assessment_year == "2026-27"


# ── It still refuses, but on the grounds that are actually true now ───────────

def test_generating_a_file_is_still_refused():
    payload = _payload()
    with pytest.raises((SoftwareProviderNotRegistered, ReturnIncomplete)):
        generate_itr_json(payload)


def test_the_missing_software_provider_id_is_refused_by_name(monkeypatch):
    """Every schema requires CreationInfo.SWCreatedBy to match SW########, a
    number the department issues to registered providers. A file without one is
    rejected at upload whatever else it contains — so having the schema was
    necessary and not sufficient."""
    monkeypatch.delenv("ITR_SOFTWARE_PROVIDER_ID", raising=False)
    with pytest.raises(SoftwareProviderNotRegistered) as exc:
        generate_itr_json(_payload())
    assert "SW########" in str(exc.value)
    assert "ITR_SOFTWARE_PROVIDER_ID" in str(exc.value)


def test_a_configured_provider_id_lifts_that_gate_and_reveals_the_next(monkeypatch):
    """With the id set, the refusal must MOVE rather than disappear: the payload
    is fourteen tax figures, not a whole return."""
    monkeypatch.setenv("ITR_SOFTWARE_PROVIDER_ID", "SW12345678")
    with pytest.raises(ReturnIncomplete) as exc:
        generate_itr_json(_payload())
    assert "PersonalInfo" in str(exc.value)


def test_a_malformed_provider_id_does_not_count(monkeypatch):
    monkeypatch.setenv("ITR_SOFTWARE_PROVIDER_ID", "NOTANID")
    assert software_provider_id() is None
    with pytest.raises(SoftwareProviderNotRegistered):
        generate_itr_json(_payload())


def test_a_wellformed_provider_id_is_normalised(monkeypatch):
    monkeypatch.setenv("ITR_SOFTWARE_PROVIDER_ID", " sw00000001 ")
    assert software_provider_id() == "SW00000001"


def test_every_form_refuses():
    for form in FIELD_MAPPINGS:
        with pytest.raises((SoftwareProviderNotRegistered, ReturnIncomplete)):
            generate_itr_json(_payload(form=form))


# ── Placements: the useful half, without the dangerous half ───────────────────

def test_each_figure_is_told_where_it_goes():
    placements = {p["key"]: p for p in itr_field_placements(_payload(form="ITR-6"))}
    assert placements["interest_234a"]["json_path"] == (
        "ITR.ITR6.PartB_TTI.ComputationOfTaxLiability.IntrstPay.IntrstPayUs234A")
    assert placements["total_income"]["json_path"] == "ITR.ITR6.PartB-TI.TotalIncome"


def test_placements_convert_to_whole_rupees_at_the_boundary():
    """Every monetary field in the schemas is an integer in RUPEES. The paise
    live in the payload; the conversion happens here and nowhere earlier."""
    placements = {p["key"]: p for p in itr_field_placements(_payload())}
    gti = placements["gross_total_income"]
    assert gti["amount_paise"] == 12_00_000_00
    assert gti["amount_rupees"] == 12_00_000


def test_rounding_is_half_away_from_zero_like_the_gst_boundary():
    from domain.income_tax.itr_json import _to_rupees
    assert _to_rupees(150) == 2      # ₹1.50 -> ₹2
    assert _to_rupees(149) == 1
    assert _to_rupees(-150) == -2
    assert _to_rupees(0) == 0


def test_a_figure_with_no_home_on_this_form_says_so():
    """§87A is for resident individuals; a company does not get it, and ITR-6
    has no field for it. That must read as "not on this form", not as a hole."""
    placements = {p["key"]: p for p in itr_field_placements(_payload(form="ITR-6"))}
    assert placements["rebate_87a"]["json_path"] is None
    assert placements["rebate_87a"]["not_on_this_form"] is True
    assert placements["total_income"]["not_on_this_form"] is False


def test_placements_cover_every_computed_figure():
    payload = _payload()
    assert len(itr_field_placements(payload)) == len(payload.values)
