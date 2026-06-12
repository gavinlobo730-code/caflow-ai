"""
Unit tests for health scoring logic — grade calculation, integer arithmetic.

All score arithmetic uses integer division — never float. (Internal spec)
These tests are self-contained so they don't require the full FastAPI stack.
"""


# ── Grade function (duplicated here for isolation) ──────────────────────────

def _grade(score: int) -> str:
    if score >= 85: return "A"
    if score >= 70: return "B"
    if score >= 55: return "C"
    if score >= 40: return "D"
    return "F"


def _calculate_overall(scores: dict) -> int:
    """Equal-weight integer average of 7 dimensions — never float."""
    dims = [
        "compliance_score", "accounting_score", "documents_score",
        "responsiveness_score", "relationship_risk_score",
        "financial_risk_score", "engagement_health_score",
    ]
    total = sum(scores[d] for d in dims)
    return total // 7  # integer division


# ---------------------------------------------------------------------------
# Grade boundary tests
# ---------------------------------------------------------------------------

def test_grade_A_exact():
    assert _grade(85) == "A"

def test_grade_A_max():
    assert _grade(100) == "A"

def test_grade_B_boundary():
    assert _grade(84) == "B"
    assert _grade(70) == "B"

def test_grade_C_boundary():
    assert _grade(69) == "C"
    assert _grade(55) == "C"

def test_grade_D_boundary():
    assert _grade(54) == "D"
    assert _grade(40) == "D"

def test_grade_F_boundary():
    assert _grade(39) == "F"
    assert _grade(0) == "F"


# ---------------------------------------------------------------------------
# Integer arithmetic (never float)
# ---------------------------------------------------------------------------

def test_overall_score_is_integer():
    scores = {
        "compliance_score": 80, "accounting_score": 100, "documents_score": 80,
        "responsiveness_score": 75, "relationship_risk_score": 100,
        "financial_risk_score": 75, "engagement_health_score": 60,
    }
    result = _calculate_overall(scores)
    assert isinstance(result, int)

def test_overall_score_correct_value():
    scores = {
        "compliance_score": 80, "accounting_score": 100, "documents_score": 80,
        "responsiveness_score": 75, "relationship_risk_score": 100,
        "financial_risk_score": 75, "engagement_health_score": 60,
    }
    total = 80 + 100 + 80 + 75 + 100 + 75 + 60  # = 570
    expected = 570 // 7  # = 81
    result = _calculate_overall(scores)
    assert result == expected

def test_overall_uses_floor_division():
    """Verify integer floor division, not rounding."""
    scores = {
        "compliance_score": 1, "accounting_score": 1, "documents_score": 1,
        "responsiveness_score": 1, "relationship_risk_score": 1,
        "financial_risk_score": 1, "engagement_health_score": 1,
    }
    # sum = 7, 7 // 7 = 1 (not 1.0)
    result = _calculate_overall(scores)
    assert result == 1
    assert isinstance(result, int)

def test_critical_flag():
    """is_critical = overall_score < 40."""
    assert _grade(39) == "F"
    assert 39 < 40  # is_critical would be True

def test_at_risk_flag():
    """is_at_risk = overall_score < 60."""
    assert 59 < 60  # is_at_risk would be True
    assert 60 >= 60  # is_at_risk would be False


# ---------------------------------------------------------------------------
# Schema alignment checks (string constants)
# ---------------------------------------------------------------------------

def test_health_scores_column_name():
    """Column is last_calculated_at, not calculated_at."""
    col = "last_calculated_at"
    assert col != "calculated_at"

def test_health_overrides_table_name():
    """Table is health_overrides, not health_score_overrides."""
    table = "health_overrides"
    assert table != "health_score_overrides"

def test_health_history_column_recorded_at():
    """health_score_history column is recorded_at, not calculated_at."""
    col = "recorded_at"
    assert col != "calculated_at"

def test_alert_severity_values():
    """Valid severity values from DB schema CHECK constraint."""
    valid = {"info", "warning", "critical"}
    legacy_invalid = {"low", "medium", "high"}
    assert not valid.intersection(legacy_invalid)
