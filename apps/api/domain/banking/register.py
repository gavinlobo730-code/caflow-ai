"""
The bank register (Tier 1.1) — a running balance over one bank account.

WHAT A REGISTER IS
    The ledger view of a single bank account: every line the bank sent us, in
    the bank's own order, with the balance after each one. It is the screen a
    bookkeeper actually lives in — you scroll it to answer "what was the balance
    on the 14th", "did that ₹50,000 ever land", "which of these has been
    reconciled".

    It is deliberately READ-ONLY. Editing a line here would mean editing a
    posted journal, and posted journals are immutable in this system
    (trg_prevent_posted_journal_line_update) — corrections are reversals. A
    register that offered an edit box would be promising something the ledger
    will refuse.

THREE THINGS THAT ARE EASY TO GET WRONG, AND HOW THIS HANDLES THEM
──────────────────────────────────────────────────────────────────────────────
1.  ORDER MUST BE DETERMINISTIC, OR THE BALANCE IS FICTION.
    Two transactions on the same date have no inherent order, but a running
    balance forces one. If the order can change between two page loads, so can
    every balance below it, and a bookkeeper comparing today's screen against
    yesterday's printout sees phantom differences. The sort key here is
    (date, created_at, id) — created_at is import order, which preserves the
    order the bank listed them in, and id is the final tiebreak so the result
    is total, not merely mostly-ordered.

2.  A TRANSACTION DATED BEFORE THE OPENING BALANCE IS ALREADY IN IT.
    `bank_accounts.opening_balance_paise` is a balance AS AT
    `opening_balance_date`. Anything dated earlier is, by definition, already
    reflected in that figure. Folding it into the running total again
    double-counts it — silently, and by exactly the amount of the stray line.
    Those rows are excluded from the arithmetic and reported separately, so the
    situation is visible rather than absorbed.

3.  THE BANK ALREADY TOLD US THE ANSWER — SO CHECK AGAINST IT.
    Indian statements carry a balance column, and the importer stores it
    (`bank_transactions.balance_paise`). That makes the register self-checking
    in a way QuickBooks structurally cannot be: if our computed balance and the
    bank's stated balance disagree, a transaction is missing, duplicated, or
    misdated. Only the FIRST divergence is diagnostic — every line after it
    inherits the same offset — so that is what gets reported, with the delta.

Integer paise throughout. No float touches a balance.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional


# The three states a line can be in, mirroring the column every accountant
# already knows from a bank reconciliation.
CLEARED_NONE = ""            # not part of any reconciliation
CLEARED_PENDING = "C"        # claimed by a reconciliation still in progress
CLEARED_RECONCILED = "R"     # part of a COMPLETED, certified reconciliation

_OPEN_STATUSES = ("open", "in_progress")


def _as_date(value) -> Optional[date]:
    """Dates arrive as date objects or ISO strings depending on the driver."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


@dataclass(frozen=True)
class RegisterLine:
    """One row of the register.

    `balance_paise` is the running balance AFTER this transaction, always
    computed in date order — see `build_register` for why that holds even when
    the caller displays the rows sorted some other way.
    """
    transaction_id: str
    transaction_date: Optional[date]
    description: str
    reference_no: Optional[str]
    debit_paise: int
    credit_paise: int
    balance_paise: int
    cleared: str
    category: Optional[str]
    match_status: Optional[str]
    posted_journal_id: Optional[str]
    reconciliation_id: Optional[str]
    # What the BANK said the balance was after this line, when the statement
    # carried a balance column. None when it did not.
    statement_balance_paise: Optional[int]
    # statement_balance_paise - balance_paise. 0 when they agree, None when the
    # statement gave us nothing to compare against.
    balance_delta_paise: Optional[int]
    # True for a row dated before the account's opening_balance_date, which is
    # therefore NOT folded into the running balance (see note 2 above).
    precedes_opening: bool

    @property
    def amount_paise(self) -> int:
        """Signed movement: positive into the account, negative out of it."""
        return self.credit_paise - self.debit_paise


def sort_key(txn: dict):
    """The one true order for a register.

    (date, created_at, id). Anything less than all three leaves same-date rows
    free to reorder between requests, which would silently reshuffle every
    running balance below them.
    """
    d = _as_date(txn.get("transaction_date"))
    return (
        d or date.min,
        str(txn.get("created_at") or ""),
        str(txn.get("id") or ""),
    )


def derive_cleared(txn: dict, reconciliation_status: Optional[str]) -> str:
    """The cleared column, from the reconciliation the line belongs to.

    A line is only 'R' once the reconciliation that claimed it has been
    COMPLETED — that is the point at which a human certified the period. While
    the session is still open the line is 'C': claimed, not yet certified.
    Collapsing the two would tell a bookkeeper a period was signed off when it
    was not.
    """
    if not txn.get("reconciliation_id"):
        return CLEARED_NONE
    if reconciliation_status == "completed":
        return CLEARED_RECONCILED
    if reconciliation_status in _OPEN_STATUSES:
        return CLEARED_PENDING
    # Claimed by a reconciliation we could not resolve (deleted, or out of
    # scope). Report the weaker of the two rather than implying certification.
    return CLEARED_PENDING


def build_register(
    txns: Iterable[dict],
    *,
    opening_balance_paise: int = 0,
    opening_balance_date=None,
    reconciliation_statuses: Optional[dict] = None,
) -> list[RegisterLine]:
    """Every transaction in bank order, each carrying the balance after it.

    `reconciliation_statuses` maps reconciliation_id -> status, so the cleared
    column can distinguish a certified period from one still open. A missing
    entry degrades to 'C' rather than claiming 'R'.

    The running balance is ALWAYS accumulated in date order. A caller is free
    to re-sort the returned list for display — by amount, by payee — and each
    line keeps the balance it had in date order, which is the only order in
    which a running balance means anything. Re-summing a re-sorted list would
    produce a column of numbers that looks like a balance and is not one.
    """
    statuses = reconciliation_statuses or {}
    opening_date = _as_date(opening_balance_date)
    ordered = sorted(txns, key=sort_key)

    running = int(opening_balance_paise or 0)
    lines: list[RegisterLine] = []

    for t in ordered:
        d = _as_date(t.get("transaction_date"))
        debit = int(t.get("debit_paise") or 0)
        credit = int(t.get("credit_paise") or 0)

        # Note 2: a row dated before the stated opening balance is already
        # inside that figure. Show it, do not re-add it.
        precedes = bool(opening_date and d and d < opening_date)
        if not precedes:
            running += credit - debit

        stated = t.get("balance_paise")
        stated_int = int(stated) if stated is not None else None
        # A pre-opening row has no meaningful computed balance to compare
        # against, so it gets no delta rather than a fabricated one.
        delta = (stated_int - running) if (stated_int is not None and not precedes) else None

        lines.append(RegisterLine(
            transaction_id=str(t.get("id") or ""),
            transaction_date=d,
            description=str(t.get("description") or ""),
            reference_no=t.get("reference_no"),
            debit_paise=debit,
            credit_paise=credit,
            balance_paise=running,
            cleared=derive_cleared(t, statuses.get(t.get("reconciliation_id"))),
            category=t.get("category"),
            match_status=t.get("match_status"),
            posted_journal_id=t.get("posted_journal_id"),
            reconciliation_id=t.get("reconciliation_id"),
            statement_balance_paise=stated_int,
            balance_delta_paise=delta,
            precedes_opening=precedes,
        ))

    return lines


def first_divergence(lines: Iterable[RegisterLine]) -> Optional[dict]:
    """Where our balance first parts company with the bank's, if it does.

    Only the first one is diagnostic. Once a line is missing, every balance
    below it is wrong by the same amount, so listing them all would report one
    fault a hundred times and bury where it started.
    """
    for i, l in enumerate(lines):
        if l.balance_delta_paise:          # non-zero and not None
            return {
                "index": i,
                "transaction_id": l.transaction_id,
                "transaction_date": l.transaction_date.isoformat() if l.transaction_date else None,
                "description": l.description,
                "computed_balance_paise": l.balance_paise,
                "statement_balance_paise": l.statement_balance_paise,
                "delta_paise": l.balance_delta_paise,
            }
    return None


def summarise(lines: list[RegisterLine], *, opening_balance_paise: int = 0) -> dict:
    """Totals for the register as a whole. Integer paise, no float."""
    counted = [l for l in lines if not l.precedes_opening]
    deposits = sum(l.credit_paise for l in counted)
    withdrawals = sum(l.debit_paise for l in counted)
    opening = int(opening_balance_paise or 0)
    return {
        "opening_balance_paise": opening,
        "deposits_paise": deposits,
        "withdrawals_paise": withdrawals,
        "closing_balance_paise": lines[-1].balance_paise if lines else opening,
        "line_count": len(lines),
        "uncleared_count": sum(1 for l in lines if l.cleared == CLEARED_NONE),
        "pending_count": sum(1 for l in lines if l.cleared == CLEARED_PENDING),
        "reconciled_count": sum(1 for l in lines if l.cleared == CLEARED_RECONCILED),
        "unposted_count": sum(1 for l in lines if not l.posted_journal_id),
        "precedes_opening_count": sum(1 for l in lines if l.precedes_opening),
    }
