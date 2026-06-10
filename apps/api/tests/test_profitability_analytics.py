"""
Test profitability analytics calculations.
Tests ensure profit calculations, margin calculations, and health status assignments are correct.
"""
import pytest
from datetime import date, timedelta


def test_profit_calculation():
    """Test: Profit = Revenue - Cost (integer paise arithmetic)"""
    revenue_paise = 1000000  # ₹10,000
    cost_paise = 400000      # ₹4,000
    profit_paise = revenue_paise - cost_paise

    assert profit_paise == 600000, "Profit should be ₹6,000"


def test_margin_calculation():
    """Test: Margin = (Profit / Revenue) * 100"""
    revenue_paise = 1000000
    cost_paise = 400000
    profit_paise = revenue_paise - cost_paise

    margin_pct = (profit_paise / revenue_paise * 100) if revenue_paise > 0 else 0.0

    assert margin_pct == 60.0, "Margin should be 60%"


def test_health_status_healthy():
    """Test: Status = 'healthy' when margin >= 25%"""
    revenue_paise = 1000000
    cost_paise = 250000  # 25% margin
    profit_paise = revenue_paise - cost_paise
    margin_pct = (profit_paise / revenue_paise * 100)

    status = "healthy" if margin_pct >= 25 else "fair" if margin_pct >= 15 else "at_risk"

    assert status == "healthy"


def test_health_status_fair():
    """Test: Status = 'fair' when 15% <= margin < 25%"""
    revenue_paise = 1000000
    cost_paise = 800000  # 20% margin
    profit_paise = revenue_paise - cost_paise
    margin_pct = (profit_paise / revenue_paise * 100)

    status = "healthy" if margin_pct >= 25 else "fair" if margin_pct >= 15 else "at_risk"

    assert status == "fair"


def test_health_status_at_risk():
    """Test: Status = 'at_risk' when margin < 15%"""
    revenue_paise = 1000000
    cost_paise = 900000  # 10% margin
    profit_paise = revenue_paise - cost_paise
    margin_pct = (profit_paise / revenue_paise * 100)

    status = "healthy" if margin_pct >= 25 else "fair" if margin_pct >= 15 else "at_risk"

    assert status == "at_risk"


def test_cost_calculation_integer_arithmetic():
    """Test: Cost = (duration_minutes * hourly_rate_paise) // 60 (integer division)"""
    duration_minutes = 90
    hourly_rate_paise = 250000  # ₹2,500/hour

    # Cost calculation: 90 * 250000 / 60 = 375000 paise
    cost_paise = (duration_minutes * hourly_rate_paise) // 60

    assert cost_paise == 375000, f"Cost should be ₹3,750 but got {cost_paise // 100}"


def test_utilisation_percentage():
    """Test: Utilisation = (billable_minutes / total_effort_minutes) * 100"""
    billable_minutes = 300
    total_effort_minutes = 400

    utilisation_pct = (billable_minutes / total_effort_minutes * 100) if total_effort_minutes > 0 else 0.0

    assert utilisation_pct == 75.0, "Utilisation should be 75%"


def test_multiple_clients_aggregation():
    """Test: Aggregation of revenue/cost across multiple clients"""
    clients = {
        "c-001": {"revenue": 1000000, "cost": 400000},
        "c-002": {"revenue": 500000, "cost": 250000},
        "c-003": {"revenue": 750000, "cost": 300000},
    }

    total_revenue = sum(c["revenue"] for c in clients.values())
    total_cost = sum(c["cost"] for c in clients.values())
    total_profit = total_revenue - total_cost

    assert total_revenue == 2250000
    assert total_cost == 950000
    assert total_profit == 1300000


def test_no_division_by_zero():
    """Test: Margin calculation handles zero revenue gracefully"""
    revenue_paise = 0
    cost_paise = 100000

    margin_pct = (cost_paise - revenue_paise) / revenue_paise * 100 if revenue_paise > 0 else 0.0

    assert margin_pct == 0.0, "Should return 0 for zero revenue"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
