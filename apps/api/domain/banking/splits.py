"""
Splitting one bank line across several GL accounts (Tier 1.2).

WHY THIS EXISTS
    One debit on a statement is often several things. A ₹47,200 payment to a
    landlord might be ₹40,000 of rent, ₹5,000 of maintenance and ₹2,200 of
    parking; a single vendor payment might cover two cost centres. Until now the
    posting engine could only ever produce a TWO-line entry — one bank leg, one
    counter leg — so the only way to record that was to code the whole amount to
    one account and fix it later with a manual journal.

THE ONE INVARIANT
    The splits must sum EXACTLY to the transaction amount. Not "close enough",
    not "with a rounding line" — exactly. A bank debited a specific number of
    paise, and a journal that does not account for every one of them either does
    not balance or hides the difference in whichever account was last in the
    list. Both are worse than refusing.

    So there is no plug line here and no auto-balancing. `validate_splits`
    refuses, and the caller shows the shortfall.

DIRECTION COMES FROM THE TRANSACTION, NOT THE SPLIT
    Every split amount is POSITIVE. Whether it lands as a debit or a credit is
    decided by the bank line: money out of the bank debits each split account,
    money in credits them. A "negative split" would be a movement in the other
    direction, which is not part of this transaction at all — it is a separate
    one, and modelling it here would let a ₹1,000 debit be recorded as ₹5,000 of
    expense against ₹4,000 of something else.

Integer paise throughout.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

# A split entry needs somewhere to go and something to put there. More than this
# is optional.
MAX_SPLITS = 50          # a sanity bound; a 50-way split is already pathological
MIN_SPLITS = 2           # one "split" is just an ordinary posting


@dataclass(frozen=True)
class Split:
    """One leg of a split bank line. `amount_paise` is always positive."""
    account_id: str
    amount_paise: int
    narration: Optional[str] = None


class SplitError(ValueError):
    """A split set that cannot be posted, with a message meant for a CA."""


def parse_splits(raw: Iterable[dict]) -> list[Split]:
    """Turn request/DB dicts into Splits, rejecting anything unusable."""
    out: list[Split] = []
    for i, r in enumerate(raw or []):
        account_id = str(r.get("account_id") or "").strip()
        if not account_id:
            raise SplitError(f"Split {i + 1} has no account selected.")
        try:
            amount = int(r.get("amount_paise"))
        except (TypeError, ValueError):
            raise SplitError(f"Split {i + 1} has no amount.")
        narration = r.get("narration")
        out.append(Split(account_id, amount,
                         str(narration).strip() if narration else None))
    return out


def validate_splits(splits: list[Split], amount_paise: int) -> None:
    """Refuse anything that would produce a wrong or unbalanced journal.

    Raises SplitError with a message a CA can act on — the shortfall in rupees,
    not "constraint violated".
    """
    total_expected = int(amount_paise)
    if total_expected <= 0:
        raise SplitError("The transaction has no amount to split.")
    if len(splits) < MIN_SPLITS:
        raise SplitError(
            "A split needs at least two lines — for a single account, post it "
            "the ordinary way.")
    if len(splits) > MAX_SPLITS:
        raise SplitError(f"A bank line can be split at most {MAX_SPLITS} ways.")

    for i, s in enumerate(splits):
        if s.amount_paise <= 0:
            # Not merely invalid — a negative leg would let the split total look
            # right while describing a movement the bank never made.
            raise SplitError(
                f"Split {i + 1} must be a positive amount. Every split moves in "
                "the same direction as the bank line.")

    total = sum(s.amount_paise for s in splits)
    if total != total_expected:
        short = total_expected - total
        raise SplitError(
            f"The splits come to {_rupees(total)} but the transaction is "
            f"{_rupees(total_expected)} — "
            + (f"{_rupees(short)} is unallocated." if short > 0
               else f"{_rupees(-short)} too much has been allocated."))


def _rupees(paise: int) -> str:
    """₹ for a human-readable error. Display only — never fed back into maths."""
    sign = "-" if paise < 0 else ""
    p = abs(int(paise))
    return f"{sign}₹{p // 100:,}.{p % 100:02d}"


def build_split_lines(splits: list[Split], *, is_credit: bool,
                      bank_account_id: str, amount_paise: int) -> list[dict]:
    """The n-leg balanced journal for a split bank line.

        money OUT of the bank      Dr each split account (its own amount)
                                       Cr Bank (the total)
        money INTO the bank        Dr Bank (the total)
                                       Cr each split account (its own amount)

    One bank leg for the whole amount and one leg per split — never one bank leg
    per split, which would balance just as well but litter the bank ledger with
    fragments of a single real movement and break reconciliation against the
    statement line.
    """
    if not bank_account_id:
        raise SplitError("The bank account is required.")
    validate_splits(splits, amount_paise)

    total = sum(s.amount_paise for s in splits)
    lines: list[dict] = []

    if is_credit:                       # money in: bank is debited once
        lines.append({"account_id": bank_account_id,
                      "debit_paise": total, "credit_paise": 0,
                      "narration": "Bank receipt (split)"})
        for s in splits:
            lines.append({"account_id": s.account_id,
                          "debit_paise": 0, "credit_paise": s.amount_paise,
                          "narration": s.narration or "Split allocation"})
    else:                               # money out: bank is credited once
        for s in splits:
            lines.append({"account_id": s.account_id,
                          "debit_paise": s.amount_paise, "credit_paise": 0,
                          "narration": s.narration or "Split allocation"})
        lines.append({"account_id": bank_account_id,
                      "debit_paise": 0, "credit_paise": total,
                      "narration": "Bank payment (split)"})

    # The validation above already guarantees this. Assert it anyway: this is
    # the last point before the lines reach the ledger, and a silent imbalance
    # here is exactly the failure the double-entry engine exists to prevent.
    dr = sum(l["debit_paise"] for l in lines)
    cr = sum(l["credit_paise"] for l in lines)
    if dr != cr:
        raise SplitError(f"Split lines do not balance: {dr} vs {cr}")
    return lines


def unallocated_paise(splits: list[Split], amount_paise: int) -> int:
    """What is left to allocate. Positive = short, negative = over-allocated.

    For the UI's live indicator, so the person splitting can see the gap close
    rather than discovering it when they try to post.
    """
    return int(amount_paise) - sum(s.amount_paise for s in splits)
