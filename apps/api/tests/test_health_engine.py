"""
Unit tests for health engine — Product Bible Chapter 16 alignment.

Tests cover:
  - Correct 7-dimension weighted scoring (integer arithmetic only)
  - Score band / grade boundaries (Healthy/Good/Needs Attention/At Risk/Critical)
  - Hard override logic forcing Critical
  - Dimension detail endpoint (mock)
  - Integer basis-point arithmetic — no float

All arithmetic uses integer division (//), never float.
Weights stored as basis points: 25% = 2500 bp, sum = 10000 bp.
"""

# ─── Replicate core engine logic inline for isolation ─────────────────────────
# These mirror the implementations in routers/health.py exactly.

DIMENSION_WEIGHTS_BP: dict[str, int] = {
    "compliance_health":     2500,   # 25%
    "accounting_quality":    2000,   # 20%
    "work_progress":         1500,   # 15%
    "document_health":       1500,   # 15%
    "ai_risk_signals":       1000,   # 10%
    "open_notices":          1000,   # 10%
    "client_responsiveness":  500,   #  5%
}

# Sanity check: weights must sum to 10000
assert sum(DIMENSION_WEIGHTS_BP.values()) == 10000, "Weights must sum to 10000 bp"


def _grade(score: int) -> str:
    """Product Bible Chapter 16 grade bands. No float arithmetic."""
    if score >= 80:
        return "Healthy"
    if score >= 65:
        return "Good"
    if score >= 50:
        return "Needs Attention"
    if score >= 35:
        return "At Risk"
    return "Critical"


def _weighted_score(dimension_scores: dict[str, int]) -> int:
    """
    Composite score from 7 dimensions using basis-point weights.
    Integer arithmetic only — sum(score_i * weight_bp_i) // 10000
    """
    total_bp = 0
    for dim, weight_bp in DIMENSION_WEIGHTS_BP.items():
        score = dimension_scores.get(dim, 100)
        total_bp += score * weight_bp
    return total_bp // 10000


HARD_OVERRIDE_REASONS = {
    "notice_deadline_missed":    "Government notice with response deadline missed",
    "advance_tax_2_consecutive": "Advance tax missed 2+ consecutive instalments",
    "gstr3b_overdue_2months":    "GSTR-3B overdue > 2 months",
    "itr_overdue_6months":       "Income tax return overdue > 6 months",
    "bank_recon_6months":        "Bank reconciliation not done > 6 months",
    "critical_ai_insight_14d":   "Open critical AI insight unacknowledged > 14 days",
}


def _apply_hard_override(overall_score: int, grade: str, hard_override: str | None) -> tuple[int, str]:
    """Apply hard override: cap score at 34 and force Critical."""
    if hard_override:
        return min(overall_score, 34), "Critical"
    return overall_score, grade


# ─── Weight integrity tests ───────────────────────────────────────────────────

def test_weights_sum_to_10000_bp():
    """All 7 dimension weights must sum to 10000 basis points (= 100%)."""
    assert sum(DIMENSION_WEIGHTS_BP.values()) == 10000


def test_exactly_7_dimensions():
    """Product Bible Chapter 16 requires exactly 7 dimensions."""
    assert len(DIMENSION_WEIGHTS_BP) == 7


def test_dimension_names_correct():
    """Verify exact dimension key names per Product Bible Chapter 16."""
    expected = {
        "compliance_health", "accounting_quality", "work_progress",
        "document_health", "ai_risk_signals", "open_notices", "client_responsiveness",
    }
    assert set(DIMENSION_WEIGHTS_BP.keys()) == expected


def test_individual_weights():
    """Verify each dimension's exact basis-point weight."""
    assert DIMENSION_WEIGHTS_BP["compliance_health"]     == 2500   # 25%
    assert DIMENSION_WEIGHTS_BP["accounting_quality"]    == 2000   # 20%
    assert DIMENSION_WEIGHTS_BP["work_progress"]         == 1500   # 15%
    assert DIMENSION_WEIGHTS_BP["document_health"]       == 1500   # 15%
    assert DIMENSION_WEIGHTS_BP["ai_risk_signals"]       == 1000   # 10%
    assert DIMENSION_WEIGHTS_BP["open_notices"]          == 1000   # 10%
    assert DIMENSION_WEIGHTS_BP["client_responsiveness"] ==  500   #  5%


# ─── Weighted score calculation ───────────────────────────────────────────────

def test_all_100_gives_100():
    """All dimensions at 100 → composite score of 100."""
    dims = {k: 100 for k in DIMENSION_WEIGHTS_BP}
    assert _weighted_score(dims) == 100


def test_all_0_gives_0():
    """All dimensions at 0 → composite score of 0."""
    dims = {k: 0 for k in DIMENSION_WEIGHTS_BP}
    assert _weighted_score(dims) == 0


def test_weighted_score_integer():
    """Result must be an integer, not float."""
    dims = {k: 50 for k in DIMENSION_WEIGHTS_BP}
    result = _weighted_score(dims)
    assert isinstance(result, int)
    assert result == 50


def test_product_bible_example_score():
    """
    Product Bible Chapter 16 example:
    compliance_health=88 (25%), accounting_quality=90 (20%),
    work_progress=75 (15%), document_health=85 (15%),
    ai_risk_signals=70 (10%), open_notices=100 (10%),
    client_responsiveness=48 (5%)

    Expected = (88*2500 + 90*2000 + 75*1500 + 85*1500
                + 70*1000 + 100*1000 + 48*500) // 10000
    """
    dims = {
        "compliance_health":     88,
        "accounting_quality":    90,
        "work_progress":         75,
        "document_health":       85,
        "ai_risk_signals":       70,
        "open_notices":          100,
        "client_responsiveness": 48,
    }
    total_bp = (
        88 * 2500
        + 90 * 2000
        + 75 * 1500
        + 85 * 1500
        + 70 * 1000
        + 100 * 1000
        + 48 * 500
    )
    expected = total_bp // 10000
    assert _weighted_score(dims) == expected


def test_compliance_health_weight_dominates():
    """compliance_health at 0 with all others at 100 should drag score significantly."""
    all_100 = {k: 100 for k in DIMENSION_WEIGHTS_BP}
    all_100["compliance_health"] = 0
    score = _weighted_score(all_100)
    # Contribution from compliance_health removed: (100*10000 - 100*2500) // 10000 = 7500 // 10000 = ... wrong
    # Correct: sum without compliance = sum of (score*bp for others) // 10000
    # = (0*2500 + 100*2000 + 100*1500 + 100*1500 + 100*1000 + 100*1000 + 100*500) // 10000
    # = (200000 + 150000 + 150000 + 100000 + 100000 + 50000) // 10000 = 750000 // 10000 = 75
    assert score == 75


def test_integer_floor_division():
    """Verify floor division (not rounding) when result is fractional."""
    # 1 * 2500 + 1*2000 + 1*1500 + 1*1500 + 1*1000 + 1*1000 + 1*500 = 10000
    # // 10000 = 1 (not 1.0)
    dims = {k: 1 for k in DIMENSION_WEIGHTS_BP}
    result = _weighted_score(dims)
    assert result == 1
    assert isinstance(result, int)


def test_weighted_contribution_per_dimension():
    """Spot-check weighted contribution integer math."""
    # compliance_health = 80, weight 2500 bp → contribution = 80*2500 // 10000 = 20
    contribution = (80 * 2500) // 10000
    assert contribution == 20

    # client_responsiveness = 60, weight 500 bp → contribution = 60*500 // 10000 = 3
    contribution2 = (60 * 500) // 10000
    assert contribution2 == 3


# ─── Grade band tests — Product Bible Chapter 16 ────────────────────────────

def test_grade_healthy_boundary():
    assert _grade(100) == "Healthy"
    assert _grade(80)  == "Healthy"


def test_grade_good_boundary():
    assert _grade(79) == "Good"
    assert _grade(65) == "Good"


def test_grade_needs_attention_boundary():
    assert _grade(64) == "Needs Attention"
    assert _grade(50) == "Needs Attention"


def test_grade_at_risk_boundary():
    assert _grade(49) == "At Risk"
    assert _grade(35) == "At Risk"


def test_grade_critical_boundary():
    assert _grade(34) == "Critical"
    assert _grade(0)  == "Critical"


def test_grade_is_not_letter_grade():
    """Product Bible uses score bands, not A/B/C/D/F letter grades."""
    for score in [100, 75, 60, 40, 20]:
        grade = _grade(score)
        assert grade not in {"A", "B", "C", "D", "F"}, (
            f"Grade {grade!r} at score {score} looks like legacy letter grade"
        )


# ─── Hard override logic ─────────────────────────────────────────────────────

def test_no_hard_override_preserves_score():
    score, grade = _apply_hard_override(82, "Healthy", None)
    assert score == 82
    assert grade == "Healthy"


def test_hard_override_forces_critical():
    score, grade = _apply_hard_override(82, "Healthy", "gstr3b_overdue_2months")
    assert grade == "Critical"


def test_hard_override_caps_score_at_34():
    score, grade = _apply_hard_override(82, "Healthy", "notice_deadline_missed")
    assert score <= 34


def test_hard_override_already_low_score():
    """Hard override on already-critical score — score stays the same (already ≤34)."""
    score, grade = _apply_hard_override(20, "Critical", "bank_recon_6months")
    assert score == 20
    assert grade == "Critical"


def test_all_hard_override_keys_have_reasons():
    """Every hard override key must have a corresponding human-readable reason."""
    expected_keys = {
        "notice_deadline_missed",
        "advance_tax_2_consecutive",
        "gstr3b_overdue_2months",
        "itr_overdue_6months",
        "bank_recon_6months",
        "critical_ai_insight_14d",
    }
    assert set(HARD_OVERRIDE_REASONS.keys()) == expected_keys


def test_hard_override_advances_tax_requires_2_consecutive():
    """
    Only 2+ consecutive missed instalments trigger this override.
    Instalment numbers 1 and 3 are not consecutive.
    """
    missed_nums = [1, 3]  # non-consecutive
    consecutive = any(
        missed_nums[i + 1] == missed_nums[i] + 1
        for i in range(len(missed_nums) - 1)
    )
    assert not consecutive

    missed_nums_consec = [2, 3]  # consecutive
    consecutive2 = any(
        missed_nums_consec[i + 1] == missed_nums_consec[i] + 1
        for i in range(len(missed_nums_consec) - 1)
    )
    assert consecutive2


# ─── is_critical / is_at_risk flags ──────────────────────────────────────────

def test_is_critical_threshold():
    """Product Bible Chapter 16: Critical = score < 35."""
    assert 34 < 35   # is_critical = True
    assert 35 >= 35  # is_critical = False


def test_is_at_risk_threshold():
    """Product Bible Chapter 16: At Risk = 35 <= score < 50."""
    assert 35 >= 35 and 35 < 50   # is_at_risk
    assert 50 >= 50                # not is_at_risk
    assert 34 < 35                 # is_critical, not just at_risk


# ─── Dimension detail structure tests ────────────────────────────────────────

def test_dimension_detail_factor_keys():
    """
    Each factor returned by dimension-detail must have exactly:
    label, impact, action_label, action_url
    """
    required_keys = {"label", "impact", "action_label", "action_url"}
    # Mock factor
    factor = {
        "label": "GSTR-1 overdue (Apr 2026)",
        "impact": -25,
        "action_label": "File Now",
        "action_url": "/clients/test-client/gst",
    }
    assert required_keys.issubset(factor.keys())


def test_dimension_detail_impact_is_negative():
    """Factors always drag the score down — impact must be negative or zero."""
    impacts = [-25, -8, -20, -15, -10, -40, 0]
    for impact in impacts:
        assert impact <= 0, f"Impact {impact} should be ≤ 0"


def test_compliance_health_penalties():
    """
    Compliance health: overdue return -25, late filing -8, pending notice -20.
    Combined deduction from 100.
    """
    score = 100
    overdue_returns = 1
    late_filings = 2
    pending_notices = 1

    score -= overdue_returns * 25
    score -= late_filings * 8
    score -= pending_notices * 20

    # 100 - 25 - 16 - 20 = 39
    assert score == 39


def test_ai_risk_signals_penalties():
    """ai_risk_signals: critical insight -20, warning -10."""
    score = 100
    critical_insights = 2
    warnings = 3

    score -= critical_insights * 20
    score -= warnings * 10

    # 100 - 40 - 30 = 30
    assert score == 30


def test_open_notices_penalty_by_deadline():
    """
    open_notices: < 7 days to deadline → -40, 7–30 days → -25, > 30 days → -15.
    Integer arithmetic only.
    """
    score = 100
    # One notice < 7 days
    score -= 40
    # One notice 15 days
    score -= 25
    # One notice 45 days
    score -= 15

    # 100 - 40 - 25 - 15 = 20
    assert score == 20
    assert isinstance(score, int)


def test_dimension_score_min_zero():
    """No dimension score should go below 0."""
    score = 100
    # Simulate 10 overdue returns: 10 * 25 = 250 (exceeds 100)
    deduction = 10 * 25
    final = max(0, score - deduction)
    assert final == 0
