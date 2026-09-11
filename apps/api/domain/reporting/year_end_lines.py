"""The year-end schedule_line taxonomy, and the one function that decides which
line an account belongs on.

WHY THIS MODULE EXISTS. Three places needed this answer — the mappings router,
the financial-statement service and the schedules endpoint — and only the first
had it. The other two read `account_group_mappings`, a table that CACHES this
function's answer, and did something catastrophic when it was empty. Measured on
production: `account_group_mappings` holds ZERO rows while `chart_of_accounts`
holds 133 accounts, 50 of them carrying a `schedule_iii_mapping` the CA recorded
by hand. See `schedule_line_for_account` below for what that cost.

`domain/reporting/schedule_iii.py` owns the statutory CAPTION vocabulary and is
the only place allowed to. This module owns the snake_case LINE CODES the
year-end statements are keyed on, and the translation between the two. They are
two spellings of one taxonomy, which is why the translation is a table here
rather than a rule anywhere.
"""
from __future__ import annotations

import logging
from typing import Optional

from domain.reporting.schedule_iii import classify

_logger = logging.getLogger("caflow.year_end_lines")

# ── Schedule III line codes ───────────────────────────────────────────────────
# Companies Act 2013, Schedule III, Part I — Balance Sheet

BS_EQUITY_LIABILITY_LINES = [
    "share_capital",
    "reserves_and_surplus",
    "long_term_borrowings",
    "deferred_tax_liabilities",
    "other_long_term_liabilities",
    "long_term_provisions",
    "short_term_borrowings",
    "trade_payables",
    "other_current_liabilities",
    "short_term_provisions",
]

BS_ASSET_LINES = [
    "tangible_assets",
    "intangible_assets",
    "capital_wip",
    "long_term_investments",
    "deferred_tax_assets",
    "long_term_loans_and_advances",
    "other_non_current_assets",
    "current_investments",
    "inventories",
    "trade_receivables",
    "cash_and_bank",
    "short_term_loans_and_advances",
    "other_current_assets",
]

# Companies Act 2013, Schedule III, Part II — Statement of Profit & Loss
PL_INCOME_LINES = [
    "revenue_from_operations",
    "other_income",
]

PL_EXPENSE_LINES = [
    "cost_of_materials_consumed",
    "purchases_of_stock_in_trade",
    "changes_in_inventories",
    "employee_benefit_expense",
    "finance_costs",
    "depreciation_and_amortisation",
    "other_expenses",
]

# Schedule III, Part II, item VII: "Tax expense: (1) Current tax
# (2) Deferred tax" is its own item, struck AFTER profit before tax — not one
# of the expenses that produce it. These lines are therefore deliberately NOT
# in PL_EXPENSE_LINES: including them would subtract the tax charge twice,
# once inside PBT and once from it.
PL_TAX_LINES = [
    "current_tax",
    "deferred_tax",
]

# Account types that behave as credit-normal (liabilities, income, equity)
# For assets/expenses: balance = SUM(debit_paise) - SUM(credit_paise)
# For liabilities/income/equity: balance = SUM(credit_paise) - SUM(debit_paise)
CREDIT_NORMAL_LINES = set(BS_EQUITY_LIABILITY_LINES) | set(PL_INCOME_LINES)

_BS_LINES = set(BS_EQUITY_LIABILITY_LINES) | set(BS_ASSET_LINES)


def statement_type_for(schedule_line: str) -> str:
    """Balance Sheet vs P&L, from the line code alone."""
    return "balance_sheet" if schedule_line in _BS_LINES else "profit_loss"


def is_balance_sheet_line(schedule_line: str) -> bool:
    return schedule_line in _BS_LINES


# ── Default mapping rules ─────────────────────────────────────────────────────
# account_type → schedule_line
# Companies Act 2013, Schedule III
#
# task #240 fix: this used to be keyed on invented lowercase categories
# ("bank", "receivable", "fixed_asset", "tax_asset", ...) that never matched
# chart_of_accounts.account_type's real CHECK-constrained enum (migration
# 003: 'Asset', 'Liability', 'Equity', 'Revenue', 'Expense' -- see the
# `accounts` view, migration 016, which is a plain passthrough of
# chart_of_accounts). Only "equity"/"expense" happened to coincide after
# lowercasing; every Asset/Liability/Revenue account (i.e. most of a real
# Chart of Accounts) silently fell through the
# `.get(acct_type, "other_current_assets")` fallback -- misclassifying
# receivables, payables, cash, fixed assets and ALL revenue onto a single
# generic Balance Sheet line.
#
# Fix: classify by the REAL (account_type, account_subtype) pair using the
# SAME bucket rules as the reporting engine's Schedule III grouping
# (domain.reporting.schedule_iii.bs_bucket/pl_bucket -- already the single
# source of truth for this taxonomy elsewhere in the codebase). This map is
# now only the coarse per-account_type fallback used when a subtype-level
# bucket can't be determined (e.g. no account_subtype set).
DEFAULT_ACCOUNT_TYPE_MAP = {
    "asset":     "other_current_assets",
    "liability": "other_current_liabilities",
    "equity":    "reserves_and_surplus",
    "revenue":   "revenue_from_operations",
    "expense":   "other_expenses",
}

# Schedule III statutory caption (as returned by domain.reporting.schedule_iii's
# bs_bucket/pl_bucket) → year-end schedule_line code.
CAPTION_TO_SCHEDULE_LINE = {
    "Share Capital":               "share_capital",
    "Reserves & Surplus":          "reserves_and_surplus",
    "Deferred Tax Liability":      "deferred_tax_liabilities",
    "Trade Payables":              "trade_payables",
    "Short-term Borrowings":       "short_term_borrowings",
    "Long-term Borrowings":        "long_term_borrowings",
    "Other Current Liabilities":   "other_current_liabilities",
    "Intangible Fixed Assets":     "intangible_assets",
    "Tangible Fixed Assets":       "tangible_assets",
    "Long-term Investments":       "long_term_investments",
    "Inventories":                 "inventories",
    "Trade Receivables":           "trade_receivables",
    "Cash & Cash Equivalents":     "cash_and_bank",
    "Short-term Loans & Advances": "short_term_loans_and_advances",
    "Other Current Assets":        "other_current_assets",
    "Revenue from Operations":     "revenue_from_operations",
    "Other Income":                "other_income",
    # "Cost of Materials Consumed", spelled the way pl_bucket returns it. The
    # key here read "Cost of Materials" from the day it was written, which
    # pl_bucket has never returned — so every cost-of-materials account fell
    # through `.get(caption, "other_current_assets")` and was classified as a
    # CURRENT ASSET in the year-end financial statements. On a trading or
    # manufacturing client that is the single largest expense on the P&L:
    # profit overstated by the whole of it, and a phantom asset of the same
    # amount on the balance sheet. The vocabulary in domain/reporting/
    # schedule_iii.py and the totality test are what stop it recurring.
    "Cost of Materials Consumed":  "cost_of_materials_consumed",
    "Employee Benefits Expense":   "employee_benefit_expense",
    "Finance Costs":               "finance_costs",
    "Depreciation & Amortisation": "depreciation_and_amortisation",
    # Schedule III Part II item VII — struck AFTER profit before tax, so it is
    # NOT an operating expense. Mapping it to other_expenses subtracted a real
    # tax provision inside PBT and then charged tax on the reduced figure
    # again.
    "Tax Expense":                 "current_tax",
    "Current Tax":                 "current_tax",
    "Deferred Tax":                "deferred_tax",
    "Other Expenses":              "other_expenses",
}

# Normal balance per schedule line (debit or credit)
LINE_NORMAL_BALANCE = {
    # Assets / Expenses → debit normal
    "tangible_assets":               "debit",
    "intangible_assets":             "debit",
    "capital_wip":                   "debit",
    "long_term_investments":         "debit",
    "deferred_tax_assets":           "debit",
    "long_term_loans_and_advances":  "debit",
    "other_non_current_assets":      "debit",
    "current_investments":           "debit",
    "inventories":                   "debit",
    "trade_receivables":             "debit",
    "cash_and_bank":                 "debit",
    "short_term_loans_and_advances": "debit",
    "other_current_assets":          "debit",
    "cost_of_materials_consumed":    "debit",
    "purchases_of_stock_in_trade":   "debit",
    "changes_in_inventories":        "debit",
    "employee_benefit_expense":      "debit",
    "finance_costs":                 "debit",
    "depreciation_and_amortisation": "debit",
    "other_expenses":                "debit",
    # Schedule III Part II item VII. Debit-normal like any expense; a credit
    # balance here is a tax WRITE-BACK, which is legitimate and must keep its
    # sign rather than be floored away.
    "current_tax":                   "debit",
    "deferred_tax":                  "debit",
    # Liabilities / Income / Equity → credit normal
    "share_capital":                 "credit",
    "reserves_and_surplus":          "credit",
    "long_term_borrowings":          "credit",
    "deferred_tax_liabilities":      "credit",
    "other_long_term_liabilities":   "credit",
    "long_term_provisions":          "credit",
    "short_term_borrowings":         "credit",
    "trade_payables":                "credit",
    "other_current_liabilities":     "credit",
    "short_term_provisions":         "credit",
    "revenue_from_operations":       "credit",
    "other_income":                  "credit",
}


def normal_balance_for(schedule_line: str) -> str:
    return LINE_NORMAL_BALANCE.get(schedule_line, "debit")


def schedule_line_for_account(account_type: str, account_subtype: Optional[str],
                              schedule_iii_mapping: Optional[str] = None) -> str:
    """Which year-end schedule_line an account belongs on.

    Uses the SAME Schedule III bucket rules as the reporting engine (single
    source of truth for the statutory caption taxonomy), keyed on the REAL
    chart_of_accounts.account_type enum, not an invented one. The CA's own
    `schedule_iii_mapping` outranks the subtype scan (ACC-10), so the year-end
    statements and the live Balance Sheet classify an account the same way.

    THIS IS A PURE FUNCTION OF THE ACCOUNT, which is the point. Its answer used
    to be computed once, frozen into `account_group_mappings`, and never
    re-derived — and the row was only ever written by a GET on the mappings
    router that no screen has ever called. So in production the cache is EMPTY,
    and both readers of it did something worse than nothing:

      * `services.year_end_financial_service.generate_financial_statements`
        sent every unmapped account to `other_current_assets`. With no rows at
        all that is EVERY account, so both sides of the Balance Sheet came to
        Σ(debit − credit) over the whole ledger — which for a balanced ledger
        is ZERO. Total assets 0, total equity and liabilities 0, revenue 0,
        every expense 0, and the `total_assets == total_equity_and_liabilities`
        assertion PASSING. A Balance Sheet of zeros that certifies it balances.
      * `routers.year_end_statements` found no account ids and returned an
        empty schedule for all seven tabs.

    Both now call this function and treat a mapping ROW as an override rather
    than as the only source, so a firm that has recorded none gets the derived
    answer instead of a wrong one.
    """
    typ = (account_type or "").strip()
    caption, _basis = classify(typ, account_subtype, schedule_iii_mapping)
    if caption:
        line = CAPTION_TO_SCHEDULE_LINE.get(caption)
        if line is not None:
            return line
        # A caption this table does not know. The old fallback here was the
        # literal "other_current_assets", which put an unmapped EXPENSE on the
        # balance sheet — the worst available answer, and how the cost-of-
        # materials defect went unseen. Falling back BY ACCOUNT TYPE at least
        # keeps an expense an expense. test_every_caption_has_a_schedule_line
        # asserts this branch is unreachable; it survives as the safe landing
        # if somebody adds a caption and forgets the row.
        _logger.error(
            "year-end mapping: Schedule III caption %r has no schedule_line — "
            "falling back to the account type. Add it to "
            "CAPTION_TO_SCHEDULE_LINE.", caption)
    return DEFAULT_ACCOUNT_TYPE_MAP.get(typ.lower(), "other_current_assets")
