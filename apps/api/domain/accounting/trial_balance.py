"""
Trial-balance import — the arithmetic, with no database in sight.

WHY THIS EXISTS AS A DOMAIN MODULE
    An imported trial balance becomes real General Ledger entries. Everything
    that decides the numbers — whether the import is admissible at all, and
    exactly which debits and credits get posted — lives here, in pure integer
    paise, so it can be tested exhaustively without a Supabase client.

THE ACCOUNTING
    A trial balance is the list of every ledger account's closing balance at a
    moment in time. Under double-entry it must balance: total debits equal
    total credits. That is not a nicety we could relax — the books of account a
    company must keep under s.128 of the Companies Act 2013, and the financial
    statements drawn from them under s.129, are only meaningful if the identity
    holds. An unbalanced trial balance means the source data is wrong, so this
    module REFUSES it rather than posting a lopsided journal.

    Bringing a trial balance in is therefore not "save these numbers". It is
    posting an opening journal entry whose lines reproduce those balances.
    Nothing is a real balance in this system until it is in the ledger.

WHY DELTAS, NOT REPLACE
    Re-importing a corrected trial balance must not mutate or delete an already
    posted journal — posted entries are immutable (trigger
    `prevent_posted_journal_delete`). So a second import posts ONE further
    balanced entry for the DIFFERENCE between the new target and what the
    ledger already carries. Same discipline as
    services/opening_balance_service.py, which does this for master-record
    opening balances. Import the same file twice and the second import computes
    a zero delta and posts nothing.

WHY THE DELTA ALWAYS BALANCES
    The delta is (target − current) per account. Σtarget is zero because a
    validated trial balance balances. Σcurrent is zero because every posted
    journal balances. A sum of two zero-sum maps is zero-sum, so the delta
    balances by construction — proved in test_trial_balance.py rather than
    asserted here, and re-checked at runtime by assert_balanced() before
    anything is posted.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrialBalanceRow:
    """One line of an imported trial balance.

    debit_paise/credit_paise are integer paise, never floats and never rupees —
    a trial balance that has been through a float is already wrong."""
    account_name: str
    account_type: str
    debit_paise: int
    credit_paise: int
    account_code: str | None = None


class TrialBalanceError(ValueError):
    """Import is inadmissible. Carries a message meant for the CA, not a stack."""


def _check_amount(value: object, field: str, row_no: int) -> int:
    # bool is an int subclass in Python and would sail through an isinstance
    # check, arriving as 1 paisa. Rejected explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TrialBalanceError(
            f"Row {row_no}: {field} must be an integer number of paise, got "
            f"{type(value).__name__}. Rupee amounts must be converted before "
            f"they reach here — floating point cannot represent money exactly.")
    if value < 0:
        raise TrialBalanceError(
            f"Row {row_no}: {field} is negative ({value}). A trial balance "
            f"records a debit or a credit, never a negative one — move the "
            f"amount to the other column instead.")
    return value


def validate(rows: list[TrialBalanceRow]) -> tuple[int, int]:
    """Raise TrialBalanceError unless `rows` is an admissible trial balance.

    Returns (total_debit_paise, total_credit_paise) when it is."""
    if not rows:
        raise TrialBalanceError("The trial balance is empty — nothing to import.")

    total_dr = 0
    total_cr = 0
    seen: dict[str, int] = {}

    for i, row in enumerate(rows, start=1):
        name = (row.account_name or "").strip()
        if not name:
            raise TrialBalanceError(f"Row {i}: the account name is blank.")

        dr = _check_amount(row.debit_paise, "debit", i)
        cr = _check_amount(row.credit_paise, "credit", i)

        # A trial balance line is a debit OR a credit. Both non-zero means the
        # source has already netted something off, and importing it would post
        # two lines that silently disagree with the CA's own statement.
        if dr and cr:
            raise TrialBalanceError(
                f"Row {i} ({name}): has BOTH a debit ({dr} paise) and a credit "
                f"({cr} paise). A trial balance line carries one or the other; "
                f"net them to a single side before importing.")

        # Duplicate account names would silently collapse in the per-account
        # aggregation below, so the imported total would not match the file.
        if name.casefold() in seen:
            raise TrialBalanceError(
                f"Row {i} ({name}): duplicate account — it also appears on row "
                f"{seen[name.casefold()]}. Combine them into one line.")
        seen[name.casefold()] = i

        total_dr += dr
        total_cr += cr

    if total_dr != total_cr:
        diff = total_dr - total_cr
        side = "debits exceed credits" if diff > 0 else "credits exceed debits"
        raise TrialBalanceError(
            f"The trial balance does not balance: {side} by {abs(diff)} paise. "
            f"Total debits {total_dr}, total credits {total_cr}. Posting this "
            f"would put the ledger out of balance, so the import is refused.")

    if total_dr == 0:
        raise TrialBalanceError(
            "Every line is zero — there is no opening position to bring forward.")

    return total_dr, total_cr


def net_by_account(rows: list[TrialBalanceRow]) -> dict[str, int]:
    """Debit-positive net paise per account name.

    Debit-positive is the convention the delta computation below shares with
    services/opening_balance_service.py: assets and expenses come out positive,
    liabilities, equity and income negative."""
    net: dict[str, int] = {}
    for row in rows:
        name = row.account_name.strip()
        net[name] = net.get(name, 0) + int(row.debit_paise) - int(row.credit_paise)
    return net


def plan_delta(target: dict[str, int], current: dict[str, int]) -> list[dict]:
    """Balanced journal lines moving the ledger from `current` to `target`.

    Both maps are debit-positive net paise keyed by ACCOUNT ID (the caller
    resolves names to ids first). Accounts present in `current` but absent from
    `target` are included with a zero target, so an account dropped from a
    re-imported trial balance is actually backed out of the ledger rather than
    left stranded at its old balance.

    Returns [] when the ledger already matches — that is the idempotent re-import
    case, and the caller must post nothing at all rather than an empty journal."""
    lines: list[dict] = []
    # Sorted so the posted lines are deterministic: two runs of the same import
    # produce byte-identical journals, which makes them diffable in review.
    for account_id in sorted(set(target) | set(current), key=str):
        delta = int(target.get(account_id, 0)) - int(current.get(account_id, 0))
        if delta > 0:
            lines.append({"account_id": account_id, "debit_paise": delta,
                          "credit_paise": 0, "narration": "Trial balance imported"})
        elif delta < 0:
            lines.append({"account_id": account_id, "debit_paise": 0,
                          "credit_paise": -delta, "narration": "Trial balance imported"})
    return lines


def assert_balanced(lines: list[dict]) -> None:
    """Last gate before posting. The delta balances by construction, so a failure
    here means a caller built `target` or `current` by some other route — worth
    catching loudly rather than letting an unbalanced journal reach the kernel,
    which would reject it anyway with a far less useful message."""
    dr = sum(int(l.get("debit_paise") or 0) for l in lines)
    cr = sum(int(l.get("credit_paise") or 0) for l in lines)
    if dr != cr:
        raise TrialBalanceError(
            f"Refusing to post: the computed entry is out of balance by "
            f"{dr - cr} paise (debits {dr}, credits {cr}).")
