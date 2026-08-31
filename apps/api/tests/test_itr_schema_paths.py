"""
Every ITR field path must exist in the department's own schema.

WHY THIS IS THE IMPORTANT TEST IN THIS AREA

domain/income_tax/itr_json.py refused for months to emit a file because the
Income Tax Department's JSON schema was unobtainable from this environment, and
writing field names from memory produces a file that is either rejected at
upload or — far worse — accepted with values in the wrong fields.

The schemas are now committed in domain/income_tax/schemas/. That removes the
guessing, but it does not by itself remove the hazard: a mapping written against
them can still be wrong, and can drift when the department revises a schema
mid-year. This test is what makes the mapping checkable rather than believed.
Every path must resolve, and must land on an integer field — the schemas hold
every amount as an integer in whole rupees, so a path that resolves to an object
is a container, and writing a figure there is precisely the "wrong field"
failure the refusal existed to prevent.

A REAL NEAR-MISS THIS GUARDS

ITR-5 and ITR-6 carry EducationCess in TWO places: under TaxPayableOnTI, the
cess on the normal computation, and under TaxPayableOnDeemedTI, the cess on
deemed income under §115JC / §115JB. Walking the schema automatically finds the
deemed-income one first. That mapping would validate perfectly and report the
wrong tax.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from domain.income_tax import itr_schema
from domain.income_tax.itr_json import FIELD_MAPPINGS

FORMS = ["ITR-1", "ITR-2", "ITR-3", "ITR-4", "ITR-5", "ITR-6", "ITR-7"]


# ── The schemas are actually here ─────────────────────────────────────────────

@pytest.mark.parametrize("form", FORMS)
def test_every_form_has_a_committed_schema(form):
    schema = itr_schema.load_schema(form)
    assert "definitions" in schema
    assert list(schema["properties"]) == ["ITR"]


def test_the_schema_files_are_the_departments_and_parse_as_draft_04():
    for form in FORMS:
        schema = itr_schema.load_schema(form)
        assert schema["$schema"].startswith("http://json-schema.org/draft-04")


# ── Every mapped path resolves (the whole point) ──────────────────────────────

@pytest.mark.parametrize("form", FORMS)
def test_every_mapped_path_exists_and_is_an_integer_field(form):
    mapping = FIELD_MAPPINGS[form]
    assert mapping.paths, f"{form} has no paths"
    for key, path in sorted(mapping.paths.items()):
        assert itr_schema.is_integer_field(form, path), (
            f"{form}: {key} -> {path} does not resolve to an integer field in "
            f"{mapping.schema_file}"
        )


def test_the_mapping_covers_every_form_and_records_its_schema_file():
    assert sorted(FIELD_MAPPINGS) == FORMS
    for form in FORMS:
        m = FIELD_MAPPINGS[form]
        assert m.verified is True
        assert m.schema_file == itr_schema.SCHEMA_FILES[form]
        assert m.assessment_year == "2026-27"


# ── The near-miss, pinned ─────────────────────────────────────────────────────

@pytest.mark.parametrize("form", ["ITR-5", "ITR-6"])
def test_cess_is_the_normal_one_not_the_deemed_income_one(form):
    """Both exist. Only one is the cess on the ordinary computation."""
    path = FIELD_MAPPINGS[form].paths["cess"]
    assert "TaxPayableOnTI.EducationCess" in path
    assert "DeemedTI" not in path
    # ...and prove the wrong one really is there to be picked by accident.
    wrong = path.replace("TaxPayableOnTI", "TaxPayableOnDeemedTI")
    assert itr_schema.is_integer_field(form, wrong)


# ── Deliberate absences ───────────────────────────────────────────────────────

@pytest.mark.parametrize("form", ["ITR-5", "ITR-6", "ITR-7"])
def test_no_87a_rebate_on_forms_whose_assessees_cannot_claim_it(form):
    """§87A is for resident individuals. Firms, companies and trusts do not get
    it, and these schemas carry no field for it — so the mapping must have no
    path rather than a plausible-looking one."""
    assert "rebate_87a" not in FIELD_MAPPINGS[form].paths


@pytest.mark.parametrize("form", ["ITR-1", "ITR-4"])
def test_no_surcharge_path_where_the_form_has_no_surcharge_field(form):
    assert "surcharge" not in FIELD_MAPPINGS[form].paths


def test_the_individual_forms_do_carry_an_87a_path():
    """Guard the guard: absence must mean something, so presence must hold."""
    for form in ("ITR-1", "ITR-2", "ITR-3", "ITR-4"):
        assert "rebate_87a" in FIELD_MAPPINGS[form].paths


# ── A path that is wrong must be caught ───────────────────────────────────────

def test_a_bogus_path_does_not_resolve():
    assert not itr_schema.is_integer_field("ITR-6", "ITR.ITR6.NoSuchThing")
    assert not itr_schema.is_integer_field(
        "ITR-6", "ITR.ITR6.PartB_TTI.ComputationOfTaxLiability.NotAField")


def test_a_container_is_not_mistaken_for_a_field():
    """Resolves, but is an object — writing a figure here is the wrong-field bug."""
    assert itr_schema.resolve("ITR-6", "ITR.ITR6.PartB_TTI") is not None
    assert not itr_schema.is_integer_field("ITR-6", "ITR.ITR6.PartB_TTI")


def test_an_unknown_form_is_refused_rather_than_guessed():
    with pytest.raises(itr_schema.SchemaUnavailable):
        itr_schema.load_schema("ITR-9")
