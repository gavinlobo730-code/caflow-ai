"""
An assessment year is the one after its financial year, and a request that
pairs them otherwise is refused.

WHAT WAS WRONG
    IT Act s.2(9) with s.3: FY 2025-26 is assessed in AY 2026-27 and in no
    other year. The ITR filing and computation-snapshot requests carry BOTH
    labels, each validated for SHAPE by its own type — and '2025-26' beside
    '2027-28' is two well-shaped labels. So a filing was created for FY 2025-26
    / AY 2027-28 (a real row, in production) and nothing noticed.

    The "+1" already existed, privately, as itr_engine._assessment_year_for.
    It is now core.ist_clock.assessment_year_for, beside normalise_fy_label,
    and both the engine and the request models ask it.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.ist_clock import assessment_year_for
from domain.income_tax.itr_engine import _assessment_year_for
from routers import itr_workspace as iw

pytestmark = pytest.mark.usefixtures("dev_header_auth")

_HEADERS = {"X-User-Email": "partner@test.com", "X-User-Role": "partner",
            "X-Firm-ID": "firm-ay"}


# ── The rule ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fy, ay", [
    ("2025-26", "2026-27"),
    ("2026-27", "2027-28"),
    ("1999-00", "2000-01"),      # the century rolls over in the second half
    ("2099-00", "2100-01"),
    ("2025-2026", "2026-27"),    # the long spelling reads the same
])
def test_the_assessment_year_is_the_financial_year_plus_one(fy, ay):
    assert assessment_year_for(fy) == ay


@pytest.mark.parametrize("junk", ["", None, "FY25", "abc-de"])
def test_a_label_it_cannot_read_is_none_never_a_guess(junk):
    assert assessment_year_for(junk) is None


def test_the_engine_asks_the_same_rule_rather_than_keeping_its_own():
    """The old private name survives as a delegate — tests import it — so it
    must give the shared answer, including the None for an unreadable label."""
    for fy in ("2025-26", "2099-00", "", None):
        assert _assessment_year_for(fy) == assessment_year_for(fy)


# ── The two request models that carry both labels ──────────────────────────

def _filing(**over):
    base = {"client_id": "C1", "financial_year": "2025-26",
            "assessment_year": "2026-27", "itr_form": "ITR-6"}
    base.update(over)
    return iw.CreateFilingRequest(**base)


def _snapshot(**over):
    base = {"client_id": "C1", "financial_year": "2025-26",
            "assessment_year": "2026-27", "regime": "normal"}
    base.update(over)
    return iw.SnapshotRequest(**base)


@pytest.mark.parametrize("build", [_filing, _snapshot])
def test_a_matching_pair_is_accepted(build):
    req = build()
    assert (req.financial_year, req.assessment_year) == ("2025-26", "2026-27")


@pytest.mark.parametrize("build", [_filing, _snapshot])
def test_the_long_spelling_of_a_matching_pair_is_accepted(build):
    """Both labels are canonicalised by their own types BEFORE the pair is
    compared, so '2025-2026' beside '2026-2027' is the same pair."""
    req = build(financial_year="2025-2026", assessment_year="2026-2027")
    assert (req.financial_year, req.assessment_year) == ("2025-26", "2026-27")


@pytest.mark.parametrize("build", [_filing, _snapshot])
@pytest.mark.parametrize("ay", ["2027-28", "2025-26"])
def test_a_mismatched_pair_is_refused_and_says_which_year_it_should_be(build, ay):
    with pytest.raises(ValidationError) as e:
        build(assessment_year=ay)
    said = str(e.value)
    assert f"AY {ay} is not the assessment year of FY 2025-26" in said
    assert "it is AY 2026-27" in said
    assert "§2(9)" in said


def test_the_endpoint_answers_a_mismatched_pair_with_a_422():
    """Through FastAPI, so the model validator is proved to be what the route
    actually runs — and it refuses BEFORE a filing row can be written."""
    from main import app
    from domain.income_tax import itr_workflow

    before = len(itr_workflow._MOCK_FILINGS)
    res = TestClient(app).post("/api/itr/filings", headers=_HEADERS, json={
        "client_id": "C-ay", "financial_year": "2025-26",
        "assessment_year": "2027-28", "itr_form": "ITR-6"})
    assert res.status_code == 422
    assert "is not the assessment year of FY 2025-26" in res.text
    assert len(itr_workflow._MOCK_FILINGS) == before
