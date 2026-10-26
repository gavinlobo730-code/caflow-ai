"""The books as the year-end statements serve them, for the tests of the Part A schedules (POST-A-070). A named helper, not a test.

Every figure is hand-chosen and balanced, so the expected values in the tests that use it are WRITTEN OUT and not derived from the
function under test: share capital 10 lakh, reserves 2.5 lakh, borrowings 5 and 1 lakh, trade payables 3 lakh, against assets that add to
the same 22.65 lakh; income 50.5 lakh against expenses of 43.1 lakh, a profit before tax of 7.4 lakh, tax of 1.6 lakh, and 5.8 lakh after it.
"""
from __future__ import annotations

L = 1_00_000_00      # one lakh, in paise


def balanced_statements(**over) -> dict:
    """A small balanced set of books. Every figure is hand-chosen so the expected values in the tests are written out, not derived."""
    liabilities = {
        "share_capital": 10 * L, "reserves_and_surplus": 2_50_000_00, "long_term_borrowings": 5 * L,
        "deferred_tax_liabilities": 10_000_00, "other_long_term_liabilities": 0, "long_term_provisions": 5_000_00,
        "short_term_borrowings": 1 * L, "trade_payables": 3 * L, "other_current_liabilities": 80_000_00,
        "short_term_provisions": 20_000_00,
    }
    assets = {
        "tangible_assets": 9 * L, "intangible_assets": 50_000_00, "capital_wip": 1 * L, "long_term_investments": 30_000_00,
        "deferred_tax_assets": 0, "long_term_loans_and_advances": 20_000_00, "other_non_current_assets": 0,
        "current_investments": 0, "inventories": 4 * L, "trade_receivables": 5 * L, "cash_and_bank": 2 * L,
        "short_term_loans_and_advances": 30_000_00, "other_current_assets": 35_000_00,
    }
    income = {"revenue_from_operations": 50 * L, "other_income": 50_000_00}
    expenses = {
        "cost_of_materials_consumed": 0, "purchases_of_stock_in_trade": 30 * L, "changes_in_inventories": -1 * L,
        "employee_benefit_expense": 8 * L, "finance_costs": 60_000_00, "depreciation_and_amortisation": 1_50_000_00,
        "other_expenses": 4 * L,
    }
    liabilities.update(over.pop("liabilities", {}))
    assets.update(over.pop("assets", {}))
    income.update(over.pop("income", {}))
    expenses.update(over.pop("expenses", {}))
    current_tax, deferred_tax = over.pop("current_tax", 1_50_000_00), over.pop("deferred_tax", 10_000_00)
    pbt = sum(income.values()) - sum(expenses.values())
    out = {
        "fy_start": "2025-04-01", "fy_end": "2026-03-31", "trial_balance_hash": "a-hash",
        "balance_sheet": {
            "equity_and_liabilities": liabilities, "assets": assets,
            "total_equity_and_liabilities_paise": sum(liabilities.values()), "total_assets_paise": sum(assets.values()),
            "is_balanced": sum(liabilities.values()) == sum(assets.values()),
        },
        "profit_loss": {
            "income": income, "expenses": expenses, "profit_before_tax_paise": pbt,
            "current_tax_paise": current_tax, "deferred_tax_paise": deferred_tax,
            "profit_after_tax_paise": pbt - current_tax - deferred_tax,
        },
    }
    assert not over, over
    return out
