"""
Bank transaction categories (Banking B.2.2).

A fixed, controlled vocabulary — NO free-form text categories. Stored on
bank_transactions.category (DB CHECK mirrors this list).
"""
from __future__ import annotations

CATEGORIES: tuple[str, ...] = (
    "Sales Receipt",
    "Customer Payment",
    "Vendor Payment",
    "Expense",
    "GST Payment",
    "Salary",
    "Loan",
    "Capital",
    "Transfer",
    "Interest",
    "Other",
)

CATEGORY_SET = frozenset(CATEGORIES)


def is_valid_category(value: str | None) -> bool:
    return value in CATEGORY_SET
