"""The health score is tested against the module that computes it (POST-A-211).

THE DEFECT
    `tests/test_health.py` carried an equal-weight A-F formula copied inline ("duplicated here for isolation") that the product
    does not use, and assertions such as `col = "recorded_at"; assert col != "calculated_at"` that read no product code at all.
    `tests/test_health_engine.py` re-declared `DIMENSION_WEIGHTS_BP`, the grade bands and a hard-override helper inline
    ("replicate core engine logic inline"). Both kept passing whatever `domain/health/scoring.py` or `routers/health.py` did,
    which is the pattern that let the R3.14 schema drift ship: a green test that does not read the code it names.

WHAT IS HELD, BY IMPORTING THE REAL THINGS
    * the seven dimensions, their names and their basis-point weights (Product Bible Chapter 16), summing to 10,000;
    * the composite is integer floor arithmetic over those weights: all 100 is 100, all 0 is 0, the Chapter 16 worked example,
      the dominance of compliance health, floor division, and a dimension that was not supplied counts as 100;
    * the five bands and the exact score each begins at, from `grade` and from `GRADE_BANDS` itself;
    * the hard-override reasons the router can name, and the router's two places that force Critical and cap the score at 34.
    Assertions about arithmetic the product does not do (a deduction table, `34 < 35`, a factor dict built in the test) were
    dropped rather than ported: they asserted nothing about the product.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from domain.health.scoring import DIMENSION_WEIGHTS_BP, DIMENSIONS, GRADE_BANDS, grade, weighted_score
from routers.health import HARD_OVERRIDE_REASONS

ROUTER = Path(__file__).resolve().parents[1] / "routers" / "health.py"


# ── the dimensions and their weights ────────────────────────────────────────────────────────────────────────────────
def test_the_weights_sum_to_ten_thousand_basis_points():
    assert sum(DIMENSION_WEIGHTS_BP.values()) == 10000


def test_there_are_exactly_the_seven_chapter_16_dimensions():
    assert set(DIMENSION_WEIGHTS_BP) == {
        "compliance_health", "accounting_quality", "work_progress", "document_health",
        "ai_risk_signals", "open_notices", "client_responsiveness"}
    assert len(DIMENSION_WEIGHTS_BP) == 7 and DIMENSIONS == frozenset(DIMENSION_WEIGHTS_BP)


def test_each_dimensions_weight():
    assert DIMENSION_WEIGHTS_BP == {
        "compliance_health": 2500, "accounting_quality": 2000, "work_progress": 1500, "document_health": 1500,
        "ai_risk_signals": 1000, "open_notices": 1000, "client_responsiveness": 500}


# ── the composite ───────────────────────────────────────────────────────────────────────────────────────────────────
def _all(value: int) -> dict[str, int]:
    return {k: value for k in DIMENSION_WEIGHTS_BP}


def test_all_dimensions_at_100_give_100_and_at_0_give_0():
    assert weighted_score(_all(100)) == 100
    assert weighted_score(_all(0)) == 0


def test_the_composite_is_an_integer():
    result = weighted_score(_all(50))
    assert result == 50 and isinstance(result, int)


def test_the_chapter_16_worked_example():
    dims = {"compliance_health": 88, "accounting_quality": 90, "work_progress": 75, "document_health": 85,
            "ai_risk_signals": 70, "open_notices": 100, "client_responsiveness": 48}
    expected = (88 * 2500 + 90 * 2000 + 75 * 1500 + 85 * 1500 + 70 * 1000 + 100 * 1000 + 48 * 500) // 10000
    assert weighted_score(dims) == expected


def test_compliance_health_at_zero_drags_the_composite_to_75():
    dims = _all(100)
    dims["compliance_health"] = 0
    assert weighted_score(dims) == 75


def test_the_composite_floors_and_does_not_round():
    dims = _all(100)
    dims["client_responsiveness"] = 99                      # 99 * 500 = 49,500 against 50,000: 99.995 floors to 99
    assert weighted_score(dims) == 99
    assert weighted_score(_all(1)) == 1


def test_a_dimension_that_was_not_supplied_counts_as_100():
    """Deliberate (domain/health/scoring.weighted_score): a dimension whose own fetch failed must not look like a finding."""
    assert weighted_score({}) == 100
    only_compliance_low = {"compliance_health": 0}
    assert weighted_score(only_compliance_low) == 75


# ── the bands ───────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("score,band", [
    (100, "Healthy"), (80, "Healthy"), (79, "Good"), (65, "Good"), (64, "Needs Attention"), (50, "Needs Attention"),
    (49, "At Risk"), (35, "At Risk"), (34, "Critical"), (0, "Critical"), (-5, "Critical"),
])
def test_a_score_falls_in_the_band_its_floor_names(score, band):
    assert grade(score) == band


def test_the_bands_are_the_five_chapter_16_words_and_not_letter_grades():
    assert [band for _floor, band in GRADE_BANDS] == ["Healthy", "Good", "Needs Attention", "At Risk", "Critical"]
    assert [floor for floor, _band in GRADE_BANDS] == [80, 65, 50, 35, 0]
    assert {grade(s) for s in range(0, 101)}.isdisjoint({"A", "B", "C", "D", "F"})


# ── the hard overrides ──────────────────────────────────────────────────────────────────────────────────────────────
def test_every_hard_override_the_router_can_name_has_a_reason():
    assert set(HARD_OVERRIDE_REASONS) == {
        "notice_deadline_missed", "advance_tax_2_consecutive", "gstr3b_overdue_2months",
        "itr_overdue_6months", "bank_recon_6months", "critical_ai_insight_14d"}
    assert all(HARD_OVERRIDE_REASONS.values())


def test_both_score_paths_of_the_router_force_critical_and_cap_at_34():
    source = ROUTER.read_text(encoding="utf-8")
    forced = re.findall(r'if hard_override:\s*\n\s*band = "Critical"\s*\n\s*overall_score = min\(overall_score, 34\)', source)
    assert len(forced) == 2, "the mock path and the database path must each force Critical and cap the score at 34"
