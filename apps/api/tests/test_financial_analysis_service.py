"""
domain/financial_analysis_service — ratio math and the Groq-unavailable
fallback narrative. The AI narrative path itself (real Groq call) is not
covered here (no network in tests); only the deterministic, always-correct
paths are asserted, per CLAUDE.md's rule that every financial calculation
has a unit test.
"""
import asyncio

from domain.financial_analysis_service import (
    compute_ratios,
    generate_statement_analysis,
    _deterministic_narrative,
    _pct_change,
)


def _pl(revenue_paise, expenses_paise, net_profit_paise):
    return {
        "revenue": {"lines": [], "total_paise": revenue_paise},
        "operating_expenses": {"lines": [], "total_paise": expenses_paise},
        "net_profit_paise": net_profit_paise,
    }


def _bs(asset_lines, liability_lines):
    return {
        "assets": [{"label": "Assets", "lines": asset_lines, "total_paise": sum(l["balance_paise"] for l in asset_lines)}],
        "liabilities": [{"label": "Liabilities", "lines": liability_lines, "total_paise": sum(l["balance_paise"] for l in liability_lines)}],
        "equity": [{"label": "Equity", "lines": [], "total_paise": 0}],
    }


def test_compute_ratios_net_margin_and_expense_ratio():
    pl = _pl(revenue_paise=1_000_00, expenses_paise=600_00, net_profit_paise=400_00)
    bs = _bs([], [])
    ratios = compute_ratios(pl, bs)
    assert ratios["net_margin_pct"] == 40.0
    assert ratios["expense_ratio_pct"] == 60.0


def test_compute_ratios_zero_revenue_returns_none_not_a_crash():
    pl = _pl(revenue_paise=0, expenses_paise=500_00, net_profit_paise=-500_00)
    bs = _bs([], [])
    ratios = compute_ratios(pl, bs)
    assert ratios["net_margin_pct"] is None
    assert ratios["expense_ratio_pct"] is None


def test_compute_ratios_current_ratio_only_sums_current_subtypes():
    asset_lines = [
        {"account_id": "ar", "account_name": "Trade Receivables", "account_subtype": "Trade Receivables", "balance_paise": 300_00},
        {"account_id": "fa", "account_name": "Office Equipment", "account_subtype": "Tangible Assets", "balance_paise": 1_000_00},
    ]
    liability_lines = [
        {"account_id": "ap", "account_name": "Trade Payables", "account_subtype": "Trade Payables", "balance_paise": 200_00},
        {"account_id": "ltb", "account_name": "Term Loan", "account_subtype": "Long-term Borrowings", "balance_paise": 5_000_00},
    ]
    ratios = compute_ratios(_pl(0, 0, 0), _bs(asset_lines, liability_lines))
    # Only the current-subtype lines (300 receivable / 200 payable) count —
    # the fixed asset and long-term borrowing are excluded from both sides.
    assert ratios["current_assets_paise"] == 300_00
    assert ratios["current_liabilities_paise"] == 200_00
    assert ratios["current_ratio"] == 1.5


def test_compute_ratios_zero_current_liabilities_returns_none_not_a_divide_by_zero():
    asset_lines = [{"account_id": "ar", "account_name": "AR", "account_subtype": "Trade Receivables", "balance_paise": 100_00}]
    ratios = compute_ratios(_pl(0, 0, 0), _bs(asset_lines, []))
    assert ratios["current_ratio"] is None


def test_pct_change_handles_zero_prior_period():
    assert _pct_change(100, 0) is None
    assert _pct_change(150, 100) == 50.0
    assert _pct_change(50, 100) == -50.0


def test_deterministic_narrative_mentions_prior_year_direction():
    pl = _pl(revenue_paise=1_100_00, expenses_paise=700_00, net_profit_paise=400_00)
    prev_pl = _pl(revenue_paise=1_000_00, expenses_paise=650_00, net_profit_paise=350_00)
    ratios = compute_ratios(pl, _bs([], []))
    narrative = _deterministic_narrative(pl, prev_pl, ratios)
    assert "up 10.0%" in narrative


def test_deterministic_narrative_never_empty_with_no_data():
    ratios = compute_ratios(_pl(0, 0, 0), _bs([], []))
    narrative = _deterministic_narrative(_pl(0, 0, 0), None, ratios)
    assert narrative


def test_generate_statement_analysis_falls_back_when_groq_unavailable(monkeypatch):
    # No GROQ_API_KEY set in the test environment — _call_groq returns None,
    # so this must degrade to the deterministic narrative, never raise, and
    # flag ai_generated=False so the frontend can label it correctly.
    monkeypatch.setattr("domain.financial_analysis_service._GROQ_API_KEY", "")
    pl = _pl(revenue_paise=1_000_00, expenses_paise=600_00, net_profit_paise=400_00)
    bs = _bs(
        [{"account_id": "ar", "account_name": "AR", "account_subtype": "Trade Receivables", "balance_paise": 300_00}],
        [{"account_id": "ap", "account_name": "AP", "account_subtype": "Trade Payables", "balance_paise": 150_00}],
    )
    result = asyncio.run(generate_statement_analysis(pl, bs, None, "2026-27", "2025-26"))
    assert result["ai_generated"] is False
    assert result["narrative"]
    assert result["ratios"]["current_ratio"] == 2.0
