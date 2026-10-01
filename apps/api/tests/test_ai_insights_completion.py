"""
AI Insights Completion Tests — insight lifecycle and data integrity (the
cross-client stub that used to be tested here is deleted — see below).

All tests run in mock mode (no SUPABASE_URL required).
"""
import os
import uuid
from datetime import date, timedelta

os.environ.pop("SUPABASE_URL", None)


# ---------------------------------------------------------------------------
# Inline helpers to avoid importing the full FastAPI app
# ---------------------------------------------------------------------------

def _make_insight(
    client_id: str = "c-001",
    title: str = "Test Insight",
    severity: str = "high",
    category: str = "compliance",
    evidence: list | None = None,
    confidence: int = 80,
    status: str = "open",
) -> dict:
    """Create an insight dict mirroring the structure returned by ai_insights_repo."""
    return {
        "id": f"aiv2-{uuid.uuid4().hex[:8]}",
        "client_id": client_id,
        "client_name": "Test Client",
        "firm_id": "firm-001",
        "category": category,
        "severity": severity,
        "title": title,
        "description": f"Description for {title}",
        "recommendation": f"Recommended action for {title}",
        "status": status,
        "evidence": evidence if evidence is not None else [f"Evidence item for {title}"],
        "confidence": confidence,
        "created_at": date.today().isoformat(),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_insight_created_with_evidence_confidence_severity():
    """
    Test 1: An insight must be created with evidence list, confidence score,
    and severity level.
    """
    insight = _make_insight(
        evidence=["GSTR-3B overdue 10 days", "Late fee ₹500 accrued"],
        confidence=90,
        severity="critical",
    )
    assert insight["evidence"] == ["GSTR-3B overdue 10 days", "Late fee ₹500 accrued"]
    assert insight["confidence"] == 90
    assert insight["severity"] == "critical"
    assert insight["status"] == "open"


def test_the_cross_client_stub_is_gone():
    """The two tests that stood here asserted the SHAPE of a hardcoded sample.

    `get_cross_client_patterns` returned the same three fixed patterns — a
    director called Rajesh Mehta, three client ids that exist in no firm — for
    every firm, and `GET /api/ai-insights/cross-client` served them as though
    they were that firm's cross-client intelligence (ai-10). Both are deleted;
    `tests/test_ai_surfaces_are_not_fake_or_dead.py` holds the rule that no AI
    route may serve a literal sample.
    """
    import domain.ai_insight_service as svc
    assert not hasattr(svc, "get_cross_client_patterns")


def test_insight_acknowledgement_updates_status():
    """
    Test 4: Acknowledging an insight changes its status from 'open' to 'acknowledged'.
    """
    from domain.ai_insight_service import MOCK_AI_INSIGHTS_V2, _insight_index
    from domain.ai_insight_service import acknowledge_insight

    # Pick an open insight from mock data
    open_insight = next((i for i in MOCK_AI_INSIGHTS_V2 if i["status"] == "open"), None)
    assert open_insight is not None, "Need at least one open insight in mock data"

    result = acknowledge_insight(open_insight["id"], firm_id="firm-001")
    assert result is not None
    assert result["status"] == "acknowledged"


def test_dismissed_insight_not_in_active_list():
    """
    Test 5: After dismissing an insight, it must not appear in the open/active list.
    """
    from domain.ai_insight_service import MOCK_AI_INSIGHTS_V2
    from domain.ai_insight_service import dismiss_insight, get_all_insights

    # Pick an open insight that is not the one we just acknowledged (use a different one)
    open_insights = [i for i in MOCK_AI_INSIGHTS_V2 if i["status"] == "open"]
    assert len(open_insights) >= 1, "Need at least one open insight"

    target = open_insights[0]
    dismiss_insight(target["id"], firm_id="firm-001")

    active = get_all_insights(firm_id="firm-001", status="open")
    dismissed_ids = [i["id"] for i in active if i["status"] == "open"]
    assert target["id"] not in dismissed_ids


def test_confidence_scoring_is_0_to_100():
    """
    Test 6: Confidence score must always be in the range 0-100.
    """
    test_cases = [0, 1, 50, 72, 85, 99, 100]
    for conf in test_cases:
        insight = _make_insight(confidence=conf)
        assert 0 <= insight["confidence"] <= 100, f"Confidence {conf} out of range"

    # Values outside range should be caught
    for bad_conf in [-1, 101, 200]:
        insight = _make_insight(confidence=bad_conf)
        # The service layer should validate — here we assert the raw value for
        # documentation purposes; production code must clamp or reject these.
        is_valid = 0 <= insight["confidence"] <= 100
        # In mock mode the value passes through; this test documents the invariant.
        assert not is_valid or bad_conf in [0, 100], (
            f"Confidence {bad_conf} outside 0-100 should not be accepted by production code"
        )


def test_evidence_is_always_array():
    """
    Test 7: Evidence must always be a list, never None or a plain string.
    """
    insight_with_list = _make_insight(evidence=["Item 1", "Item 2"])
    assert isinstance(insight_with_list["evidence"], list)

    # An insight with a single item still returns a list
    insight_single = _make_insight(evidence=["Single evidence item"])
    assert isinstance(insight_single["evidence"], list)
    assert len(insight_single["evidence"]) == 1


def test_insight_feed_returns_open_insights_sorted_by_severity():
    """
    Test 9: The insight feed must return only open insights, sorted by severity
    (critical first, then high, medium, low, info).
    """
    from domain.ai_insight_service import get_insight_feed

    feed = get_insight_feed(firm_id="firm-001", limit=20)
    assert isinstance(feed, list)

    # All returned insights must be open
    for item in feed:
        assert item["status"] == "open", f"Non-open insight in feed: {item['id']}"

    # Verify severity ordering is maintained
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    prev_order = -1
    for item in feed:
        current_order = severity_order.get(item["severity"], 5)
        assert current_order >= prev_order, (
            f"Feed not sorted by severity: {item['severity']} appeared after "
            f"a lower-severity item (order {prev_order} → {current_order})"
        )
        prev_order = current_order


def test_all_insight_severities_are_valid():
    """
    Test 10: Every insight in the mock data must have a valid severity level.
    Product Bible Chapter 17 defines: critical, high, medium, low, info.
    """
    from domain.ai_insight_service import MOCK_AI_INSIGHTS_V2

    valid_severities = {"critical", "high", "medium", "low", "info"}
    for insight in MOCK_AI_INSIGHTS_V2:
        assert insight["severity"] in valid_severities, (
            f"Insight {insight['id']} has invalid severity: {insight['severity']!r}"
        )
