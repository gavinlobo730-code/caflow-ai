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
    FIELD_MAPPINGS, FieldMapping, SchemaNotVerified, build_itr_payload,
    generate_itr_json,
)

L = 1_00_000_00


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

def test_no_mapping_is_verified():
    """If one ever is, it must be because someone checked it against the
    department's published schema — not because a test was relaxed."""
    for form, mapping in FIELD_MAPPINGS.items():
        assert mapping.verified is False, form
        assert mapping.paths == {}, form


def test_no_mapping_asserts_a_field_name():
    """An EMPTY mapping is honest; a plausible-looking one is not. Field names
    written from memory are the exact failure this module exists to avoid."""
    for form, mapping in FIELD_MAPPINGS.items():
        assert not mapping.paths, f"{form} asserts field names"


def test_an_unverified_mapping_carries_no_schema_version():
    """Writing a version number beside unverified names would assert exactly
    the correspondence that has not been established."""
    for mapping in FIELD_MAPPINGS.values():
        assert mapping.schema_version is None


def test_generating_a_file_is_refused_by_name():
    p = build_itr_payload(form="ITR-4")
    with pytest.raises(SchemaNotVerified, match="No verified ITR JSON schema"):
        generate_itr_json(p)


def test_the_refusal_says_what_to_do_instead():
    """A refusal that leaves a CA stuck is a bug. This one names the
    department's offline utility and says the fix is a data change."""
    p = build_itr_payload(form="ITR-1")
    with pytest.raises(SchemaNotVerified) as e:
        generate_itr_json(p)
    message = str(e.value)
    assert "offline utility" in message
    assert "data change" in message


def test_every_form_refuses():
    for form in ("ITR-1", "ITR-2", "ITR-3", "ITR-4", "ITR-5", "ITR-6"):
        with pytest.raises(SchemaNotVerified):
            generate_itr_json(build_itr_payload(form=form))


def test_the_payload_says_it_is_not_an_itr_json():
    """The likeliest misuse is a caller treating as_dict() as the file. The
    payload says otherwise in its own notes."""
    p = build_itr_payload(form="ITR-4")
    joined = " ".join(p.notes)
    assert "NOT an ITR JSON file" in joined
    assert p.can_emit_file is False


def test_the_notes_explain_why_no_file_can_be_produced():
    p = build_itr_payload(form="ITR-4")
    joined = " ".join(p.notes)
    assert "wrong fields" in joined
    assert "offline utility" in joined


# ── The path out ─────────────────────────────────────────────────────────────

def test_a_verified_mapping_would_lift_the_refusal_without_a_code_change(monkeypatch):
    """The values are the hard part and they are done. Turning this into a real
    generator is a DATA change: fill in the department's field names, set
    verified, and the refusal lifts. This test proves that, so the module does
    not quietly become a dead end."""
    import json
    monkeypatch.setitem(FIELD_MAPPINGS, "ITR-4", FieldMapping(
        form="ITR-4", assessment_year="2026-27", schema_version="TEST-ONLY",
        verified=True,
        paths={"total_income": "ITR4.PartB_TI.TotalIncome",
               "total_tax": "ITR4.PartB_TTI.TotalTaxPayable"}))
    p = build_itr_payload(form="ITR-4", total_income_paise=45 * L,
                          total_tax_paise=5 * L)
    assert p.can_emit_file is True
    emitted = json.loads(generate_itr_json(p))
    assert emitted["ITR4"]["PartB_TI"]["TotalIncome"] == 45 * L
    assert emitted["ITR4"]["PartB_TTI"]["TotalTaxPayable"] == 5 * L


def test_a_verified_mapping_emits_only_the_keys_it_maps(monkeypatch):
    """A partial mapping must not invent a home for the rest."""
    import json
    monkeypatch.setitem(FIELD_MAPPINGS, "ITR-1", FieldMapping(
        form="ITR-1", assessment_year="2026-27", schema_version="TEST-ONLY",
        verified=True, paths={"total_income": "ITR1.TotalIncome"}))
    p = build_itr_payload(form="ITR-1", total_income_paise=9 * L,
                          total_tax_paise=1 * L)
    emitted = json.loads(generate_itr_json(p))
    assert emitted == {"ITR1": {"TotalIncome": 9 * L}}
