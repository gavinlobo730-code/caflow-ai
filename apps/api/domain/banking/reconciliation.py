"""
Bank reconciliation tie-out (Banking B.4) — pure, testable arithmetic.

The reconciliation proves the bank statement against the book (posted ledger):

    Opening balance
      + Deposits        (reconciled credits — money into the bank)
      - Withdrawals      (reconciled debits — money out of the bank)
      ± Adjustments      (documented differences, e.g. bank charges)
      = Reconciled book balance

It reconciles when the reconciled book balance equals the statement's closing
balance. Mirrors the cash-flow `reconciles` flag: a single boolean backed by an
exact integer-paise comparison (never float).
"""
from __future__ import annotations


def tie_out(
    *,
    opening_balance_paise: int,
    closing_balance_paise: int,
    deposits_paise: int,
    withdrawals_paise: int,
    adjustments_paise: int = 0,
) -> dict:
    """Compute the balance tie-out. All values are integer paise.

    `deposits_paise` / `withdrawals_paise` are the totals of the *reconciled*
    credits / debits. Returns the full breakdown plus a `reconciles` boolean and
    the signed `difference_paise` (statement closing − reconciled book balance).
    """
    opening = int(opening_balance_paise)
    closing = int(closing_balance_paise)
    deposits = int(deposits_paise)
    withdrawals = int(withdrawals_paise)
    adjustments = int(adjustments_paise)

    book_balance = opening + deposits - withdrawals + adjustments
    difference = closing - book_balance
    return {
        "opening_balance_paise": opening,
        "deposits_paise": deposits,
        "withdrawals_paise": withdrawals,
        "adjustments_paise": adjustments,
        "reconciled_book_balance_paise": book_balance,
        "statement_closing_balance_paise": closing,
        "difference_paise": difference,
        "reconciles": difference == 0,
    }


def split_amounts(transactions: list[dict]) -> tuple[int, int]:
    """Sum (deposits_paise, withdrawals_paise) over bank transactions.

    Credits are deposits (money in); debits are withdrawals (money out).
    Integer paise only.
    """
    deposits = sum(int(t.get("credit_paise") or 0) for t in transactions)
    withdrawals = sum(int(t.get("debit_paise") or 0) for t in transactions)
    return deposits, withdrawals
