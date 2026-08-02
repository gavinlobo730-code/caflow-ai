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


def reconciled_book_balance(
    *,
    account_opening_paise: int,
    completed_sessions: list[dict],
) -> int:
    """The book's view of a bank account after every COMPLETED reconciliation.

        account opening
          + Σ (deposits − withdrawals + adjustments) over completed sessions
          = reconciled book balance

    This is the same accumulation `tie_out` performs for one period, carried
    forward across all of them. Each session dict supplies `deposits_paise`,
    `withdrawals_paise` and `adjustments_paise`.

    Integer paise only.
    """
    balance = int(account_opening_paise)
    for s in completed_sessions:
        balance += int(s.get("deposits_paise") or 0)
        balance -= int(s.get("withdrawals_paise") or 0)
        balance += int(s.get("adjustments_paise") or 0)
    return balance


def opening_balance_check(
    *,
    suggested_opening_paise: int,
    reconciled_book_balance_paise: int,
) -> dict:
    """Does the opening balance a new reconciliation starts from agree with the
    books' own record of everything reconciled so far?

    WHY THESE TWO FIGURES
        `suggested_opening_paise` is a BANK fact: the closing balance the last
        completed reconciliation tied out to. `reconciled_book_balance_paise` is
        a BOOK fact: the account's opening balance plus every reconciled
        movement since. Immediately after completing a reconciliation the two
        are equal by construction.

        They can only diverge if something changed AFTER a session was
        completed — a transaction un-reconciled, an adjustment altered, a posted
        journal reversed. That is precisely the condition worth warning about
        before someone starts a new period on a foundation that has moved.

        This is a WARNING, never a block: the divergence may be legitimate and
        deliberate, and refusing to open a reconciliation would leave the CA no
        way to investigate it. `tie_out` remains the thing that must be exact
        before a period can be completed.
    """
    suggested = int(suggested_opening_paise)
    book = int(reconciled_book_balance_paise)
    mismatch = suggested - book
    return {
        "suggested_opening_paise": suggested,
        "reconciled_book_balance_paise": book,
        "mismatch_paise": mismatch,
        "matches": mismatch == 0,
    }


def split_amounts(transactions: list[dict]) -> tuple[int, int]:
    """Sum (deposits_paise, withdrawals_paise) over bank transactions.

    Credits are deposits (money in); debits are withdrawals (money out).
    Integer paise only.
    """
    deposits = sum(int(t.get("credit_paise") or 0) for t in transactions)
    withdrawals = sum(int(t.get("debit_paise") or 0) for t in transactions)
    return deposits, withdrawals
