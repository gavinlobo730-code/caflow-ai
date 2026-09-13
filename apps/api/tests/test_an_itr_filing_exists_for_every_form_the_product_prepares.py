"""
All seven ITR forms, a typed assessment year, and an acknowledgement that
respects the state machine. IT-23a.

WHAT WAS WRONG — THREE THINGS, ONE OF THEM LOCKING OUT MOST OF A PRACTICE

    THE FORMS. `apps/web/.../tax/filing/page.tsx` held
    `const ITR_FORMS = ["ITR-3","ITR-5","ITR-6","ITR-7"]` and
    `itr_workflow`'s own docstring said the same four, while
    `domain/income_tax/itr_json.FIELD_MAPPINGS` carries VERIFIED field paths
    and `itr_schema.SCHEMA_FILES` a committed Department JSON schema for all
    SEVEN. So a salaried client (ITR-1 or ITR-2) or a presumptive one (ITR-4)
    could not have a filing record created at all — most of a typical
    practice's ITR volume — and `itr_form` reached the router as a free string
    with nothing validating it either way.

    THE ASSESSMENT YEAR. `models/fy.AYLabel` has existed since the FY sweep
    and exactly one router used it. Six boundary fields took an AY as a bare
    `str`, so '2026-28' was accepted and silently meant 2026-27 — the defect
    the FY type was written to end, on the other half of the same rule.
    `tests/test_fy_labels_are_validated.py` did not scan for it.

    THE ACKNOWLEDGEMENT. `record_filing_acknowledgement` wrote
    `status = "filed"` with no read of the current status, so a DRAFT could be
    marked filed — past the review and the partner review `_TRANSITIONS`
    exists to require, and past the tax screen's own promise that partner
    review is mandatory before Ready for Filing.

WHAT IS DELIBERATELY NOT HERE
    The §139(5) revised and §139(8A) updated return. Those need a
    `return_type` and a migration replacing migration 319's
    UNIQUE (firm_id, client_id, financial_year, itr_form), which cannot hold a
    second return beside the original — and the §140B additional tax is its
    own statutory module. IT-23 stays open on that half.
"""
from __future__ import annotations

import pytest

from domain.income_tax import itr_workflow as wf
from domain.income_tax.itr_json import FIELD_MAPPINGS, ITR_FORMS
from domain.income_tax.itr_schema import SCHEMA_FILES

FIRM = "FIRM-IT23"


@pytest.fixture(autouse=True)
def _clean():
    wf._MOCK_FILINGS.clear()
    yield
    wf._MOCK_FILINGS.clear()


def _filing(form="ITR-1", **over):
    kw = dict(firm_id=FIRM, client_id="CLI", financial_year="2025-26",
              assessment_year="2026-27", itr_form=form, created_by="u1")
    kw.update(over)
    return wf.create_itr_filing(**kw)


# ── One vocabulary ───────────────────────────────────────────────────────────

def test_the_seven_forms_are_the_ones_the_product_can_actually_map():
    """Not a list somebody typed: derived from the Literal that the field
    mappings and the committed schemas are keyed on, so a form the workflow
    accepts is one that has a schema behind it."""
    assert wf.supported_forms() == ITR_FORMS
    assert len(ITR_FORMS) == 7
    assert set(ITR_FORMS) == set(SCHEMA_FILES)
    assert set(ITR_FORMS) == set(FIELD_MAPPINGS)


@pytest.mark.parametrize("form", ITR_FORMS)
def test_a_filing_can_be_created_for_every_form(form):
    """ITR-1, ITR-2 and ITR-4 are the point: a salaried or presumptive client
    had no way into the workflow at all."""
    assert _filing(form)["itr_form"] == form


def test_a_form_the_product_does_not_prepare_is_refused_by_name():
    with pytest.raises(wf.ITRWorkflowError) as e:
        _filing("ITR-8")
    assert "ITR-8" in str(e.value)
    # The refusal says which seven, rather than only that this one is wrong.
    for f in ITR_FORMS:
        assert f in str(e.value)


@pytest.mark.parametrize("typed,stored", [
    ("itr-4", "ITR-4"), (" ITR-4 ", "ITR-4"), ("Itr-7", "ITR-7"),
])
def test_a_form_is_canonicalised_because_it_is_stored_and_then_filtered_on(typed, stored):
    """Two spellings of one form read as two forms once `itr_filings` holds
    both — the same reasoning models/fy.py gives for canonicalising a year."""
    assert _filing(typed)["itr_form"] == stored


def test_nothing_restates_the_form_list():
    """A second copy is a second thing to keep in step, and that is exactly how
    the screen came to offer four."""
    import inspect
    import pathlib
    import routers.income_tax as it
    import routers.itr_workspace as ws

    src = pathlib.Path(inspect.getfile(it)).read_text() + \
        pathlib.Path(inspect.getfile(ws)).read_text() + \
        inspect.getsource(wf)
    # The literal seven-in-a-row is what a copy looks like. `itr_json` is
    # allowed to hold it — it is the Literal the tuple is derived from.
    assert '"ITR-1", "ITR-2", "ITR-3"' not in src
    assert "'ITR-1', 'ITR-2', 'ITR-3'" not in src


# ── The acknowledgement respects the state machine ───────────────────────────

def _to(filing_id, *statuses):
    for s in statuses:
        wf.transition_itr_status(FIRM, filing_id, s, actor_id="u1")


def test_a_return_ready_for_filing_can_be_acknowledged():
    f = _filing()
    _to(f["id"], "review", "partner_review", "ready_for_filing")
    out = wf.record_filing_acknowledgement(
        firm_id=FIRM, filing_id=f["id"], acknowledgement_number="123456789012345",
        filing_date="2026-07-20", actor_id="u1")
    assert out["status"] == "filed"
    assert out["acknowledgement_number"] == "123456789012345"
    assert out["filing_date"] == "2026-07-20"


@pytest.mark.parametrize("reach", [(), ("review",), ("review", "partner_review")])
def test_a_return_that_has_not_reached_ready_for_filing_is_refused(reach):
    """The workflow's whole purpose. Marking a draft filed skips the review and
    the partner review, which is what the tax screen promises are mandatory."""
    f = _filing()
    _to(f["id"], *reach)
    with pytest.raises(wf.ITRWorkflowError) as e:
        wf.record_filing_acknowledgement(
            firm_id=FIRM, filing_id=f["id"], acknowledgement_number="1",
            filing_date="2026-07-20", actor_id="u1")
    assert "ready_for_filing" in str(e.value)
    assert wf._MOCK_FILINGS[f["id"]]["status"] != "filed"
    assert not wf._MOCK_FILINGS[f["id"]].get("acknowledgement_number")


def test_an_already_filed_return_is_not_silently_re_acknowledged():
    """The acknowledgement number is a fact about what the portal did.
    Overwriting one loses the record of the first filing, so the refusal names
    the number on file and the CA can see whether it differs."""
    f = _filing()
    _to(f["id"], "review", "partner_review", "ready_for_filing")
    wf.record_filing_acknowledgement(
        firm_id=FIRM, filing_id=f["id"], acknowledgement_number="AAA",
        filing_date="2026-07-20", actor_id="u1")
    with pytest.raises(wf.ITRWorkflowError) as e:
        wf.record_filing_acknowledgement(
            firm_id=FIRM, filing_id=f["id"], acknowledgement_number="BBB",
            filing_date="2026-08-01", actor_id="u1")
    assert "AAA" in str(e.value)
    assert wf._MOCK_FILINGS[f["id"]]["acknowledgement_number"] == "AAA"


def test_the_permitted_states_are_derived_from_the_transition_table():
    """Not restated. A change to the workflow must reach this path too."""
    assert wf._MAY_BECOME_FILED == frozenset({"ready_for_filing"})
    assert all("filed" in wf._TRANSITIONS[s] for s in wf._MAY_BECOME_FILED)


def test_a_filing_that_does_not_exist_is_refused_rather_than_returning_nothing():
    with pytest.raises(wf.ITRWorkflowError):
        wf.record_filing_acknowledgement(
            firm_id=FIRM, filing_id="nope", acknowledgement_number="1",
            filing_date="2026-07-20", actor_id="u1")
