"""The cash book — the one rule a bank book does not have (BANK-20).

WHY THIS IS NOT A SECOND LEDGER

A cash book IS the account ledger for the client's cash accounts. The reporting
engine already computes an account ledger with an opening balance, a running
balance and a closing balance, in SQL, over the account's whole history before
slicing a page (`public.account_ledger_page`). Building a second running-balance
implementation for cash would be the mistake CLAUDE.md's reporting section names
in terms: two implementations of one rule drift, and the parity test exists
because that has already happened once here.

So this module holds only what is genuinely different about CASH:

  * WHICH accounts are cash. A bank book is asked about one bank account; a
    cash book is about every Cash-subtype ledger the client has — Cash in Hand,
    Petty Cash, a branch float — and a CA reads them together.
  * THE NEGATIVE-BALANCE RULE. This is the whole cash-specific finding. A bank
    account can go negative: that is an overdraft, and BANK-02 gave it a
    liability ledger. PHYSICAL CASH CANNOT. You cannot pay out a note you do
    not have, so a negative cash balance is never a fact about the world — it
    is always an error in the books: a payment entered before the receipt that
    funded it, a receipt missed entirely, or a duplicated payment.

    It is reported at the FIRST date it happens rather than only at the close,
    because a balance that dips negative mid-month and recovers by the 31st is
    invisible in a closing figure and is exactly as wrong.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

#: A chart-of-accounts subtype naming physical cash. `coa_seed_service` seeds
#: "1001 Cash in Hand" and "1002 Petty Cash" both as Asset/'Cash'; the substring
#: match is deliberate so a firm's own "Cash — Branch" also qualifies, matching
#: how domain/reporting/schedule_iii.bs_bucket reads subtypes.
CASH_SUBTYPE_KEYWORD = "cash"


def is_cash_account(account_type: Optional[str], account_subtype: Optional[str]) -> bool:
    """Is this ledger physical cash?

    Asset AND a cash-ish subtype. The type test is not decoration: a Liability
    account whose name happens to contain "cash" — a Cash Credit facility, say —
    is a BANK borrowing, and BANK-02 is the finding about getting that wrong.
    """
    return (str(account_type or "").strip().lower() == "asset"
            and CASH_SUBTYPE_KEYWORD in str(account_subtype or "").strip().lower())


@dataclass(frozen=True)
class NegativeCashDay:
    """The first date a cash ledger went below zero, and by how much."""
    account_id: str
    account_name: str
    on_date: str
    balance_paise: int          # negative
    entry_id: Optional[str]
    narration: str


def first_negative_day(
    lines: Sequence[dict], *, account_id: str, account_name: str,
    opening_balance_paise: int = 0,
) -> Optional[NegativeCashDay]:
    """The FIRST line at which the running balance goes below zero.

    `lines` are ledger rows in date order, each with `debit_paise`,
    `credit_paise` and `entry_date` — the shape the reporting engine returns.
    The balance is recomputed here rather than trusting a `balance_paise` the
    caller may have re-sorted: build_register's docstring makes the same point,
    that a running balance only means anything in date order.

    Returns None when the balance never goes negative, which is the ordinary
    case and is an ANSWER — the caller reports "no negative day", not silence.
    """
    running = int(opening_balance_paise or 0)
    for ln in lines:
        running += int(ln.get("debit_paise") or 0) - int(ln.get("credit_paise") or 0)
        if running < 0:
            return NegativeCashDay(
                account_id=account_id,
                account_name=account_name,
                on_date=str(ln.get("entry_date") or ""),
                balance_paise=running,
                entry_id=ln.get("entry_id") or ln.get("journal_entry_id"),
                narration=str(ln.get("narration") or ""),
            )
    return None


def explain_negative(day: NegativeCashDay) -> str:
    """What a CA should actually do about it, in a sentence.

    A bare "balance is negative" is a number they can already see. The value is
    naming the three things that cause it, because the remedy differs for each.
    """
    rupees = abs(day.balance_paise) // 100
    return (
        f"{day.account_name} goes to −₹{rupees:,} on {day.on_date}. Physical cash "
        f"cannot be negative, so something is missing or out of order: a payment "
        f"entered before the receipt that funded it, a cash receipt never "
        f"recorded, or one payment entered twice."
    )
