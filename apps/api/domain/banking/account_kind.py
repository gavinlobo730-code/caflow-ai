"""What KIND of account a bank_accounts row is, and the one thing that differs
about a credit card (BANK-21).

WHAT WAS WRONG
    `bank_accounts.account_type` admitted Current, Savings, Cash Credit and
    Overdraft and nothing else, so a company credit card could not be created
    at all — its statement could not be imported, its spend could not be coded
    through the bank workflow, and the monthly payment out of the current
    account posted to whatever ledger somebody picked, with the underlying
    expenses never recorded. A card is ordinary for any SME with travel or
    online spend.

THE DOUBLE ENTRY NEEDS NO CHANGE, AND THAT IS THE POINT
    `posting_map.build_lines` is direction-driven: money OUT debits the counter
    and credits the bank account's own ledger. Give the card a LIABILITY ledger
    and the same rule is already right —

        a purchase on the card   Dr Expense  / Cr Card   (the liability grows)
        a payment to the card    Dr Card     / Cr Bank   (it shrinks)

    — because a card statement's "Dr" column is a purchase, which is money out
    of the card account in exactly the sense the posting map means. So nothing
    in the posting map, the settlement or the reversal moves.

WHAT DOES DIFFER IS THE BALANCE'S SIGN
    A bank account's balance is a DEBIT balance; a card's is a CREDIT balance —
    the amount owed. The register accumulates `credit - debit`, so a card's
    running balance is NEGATIVE and its magnitude is what the cardholder owes.
    The card's own statement states that figure the other way up, as a positive
    amount owed.

    So there is exactly ONE convention inside the product — LEDGER SIGN,
    positive means a debit balance — and exactly two places the statement's
    sign is translated: where a figure is READ OFF a statement (the imported
    balance column, and the opening and closing balances the CA types from it)
    and where one is SHOWN BACK. `to_ledger_sign` and `to_statement_sign` are
    those two, and they are the identity for every account that is not a card.
    Translate at the boundary, never rekey a store — the same rule the TDS
    vocabulary follows across the 2026 fork.

WHAT IS NAMED RATHER THAN CHANGED
    `posting_map.entry_type_for` still calls a card purchase a "Payment" and a
    card repayment a "Receipt", because those are the three values
    `journal_entries.entry_type` allows for a bank line and the accounting is
    right either way. A purchase on credit is not a payment of money, and
    Tally would call it a Journal; renaming it here would mean widening a CHECK
    and re-teaching the whole bank vocabulary for a label. It is recorded, not
    fixed.
"""
from __future__ import annotations

from typing import Optional

#: Every value `bank_accounts.account_type` allows, in the order the form
#: offers them. Migration 386 is the other half; a test holds the two together.
CURRENT = "Current"
SAVINGS = "Savings"
CASH_CREDIT = "Cash Credit"
OVERDRAFT = "Overdraft"
CREDIT_CARD = "Credit Card"

ACCOUNT_TYPES = (CURRENT, SAVINGS, CASH_CREDIT, OVERDRAFT, CREDIT_CARD)

#: Money OWED to the bank rather than held with it. All three carry a liability
#: ledger; only the card's STATEMENT states its balance the other way up.
#:
#: An overdraft and a cash credit are drawn against a bank ACCOUNT, and the
#: bank states that account's balance the ordinary way — overdrawn is a
#: negative balance on the statement, printed as `Dr`. A card statement never
#: prints a negative: it prints "total amount due".
OWED_TO_THE_BANK = frozenset({CASH_CREDIT, OVERDRAFT, CREDIT_CARD})
STATEMENT_STATES_THE_AMOUNT_OWED = frozenset({CREDIT_CARD})

#: (account_type, account_subtype) for the chart_of_accounts row this product
#: creates for a bank account.
#:
#: THE SUBTYPES ARE CHECKED AGAINST THE CLASSIFIER, NOT CHOSEN FOR READABILITY.
#: `domain/reporting/schedule_iii.bs_bucket()` substring-scans the subtype, so
#: 'Bank OD' would fall to Other Current Liabilities instead of Short-term
#: Borrowings — the caption Schedule III Division I gives "loans repayable on
#: demand from banks". 'Credit Card' is matched there by name for the same
#: reason and lands in the same caption.
_LEDGER_SHAPES: dict[str, tuple[str, str]] = {
    CASH_CREDIT: ("Liability", "Bank Overdraft"),
    OVERDRAFT: ("Liability", "Bank Overdraft"),
    CREDIT_CARD: ("Liability", "Credit Card"),
}
_ASSET_LEDGER = ("Asset", "Bank")


def is_credit_card(account_type: Optional[str]) -> bool:
    return (account_type or "").strip() == CREDIT_CARD


def is_owed_to_the_bank(account_type: Optional[str]) -> bool:
    return (account_type or "").strip() in OWED_TO_THE_BANK


def ledger_shape_for(account_type: Optional[str]) -> tuple[str, str]:
    """(account_type, account_subtype) for this bank account's own ledger."""
    return _LEDGER_SHAPES.get((account_type or "").strip(), _ASSET_LEDGER)


def to_ledger_sign(account_type: Optional[str], amount_paise: Optional[int]) -> int:
    """A balance READ OFF a statement, in the sign everything inside uses.

    The identity for every account but a credit card, whose statement states
    the amount OWED as a positive figure where the ledger holds a credit
    balance."""
    value = int(amount_paise or 0)
    return -value if is_credit_card(account_type) else value


def to_statement_sign(account_type: Optional[str], amount_paise: Optional[int]) -> int:
    """A stored balance, in the sign the CA reads on the statement.

    Its own inverse, and deliberately a SECOND named function rather than one
    called twice: a call site that converts the wrong way round is a sign
    error nobody sees, and the two names say which direction is meant."""
    value = int(amount_paise or 0)
    return -value if is_credit_card(account_type) else value


def mirror_imported_statement(account_type: Optional[str], rows, opening, closing):
    """A parsed statement's BALANCES, in the sign everything inside uses.

    (rows, opening, closing) back, with every balance translated exactly once.
    The debit and credit columns are untouched and must be: a purchase is money
    out of the card account in the sense `posting_map` means, and Dr Expense /
    Cr Card is already what comes out of it.

    IT HAS TO HAPPEN BEFORE `tie_out.statement_check`, which REFUSES the
    import when `opening + credits - debits != closing`. On a card statement
    in the statement's own sign that is never true — 500 owed, a 5,000
    purchase, a 3,000 payment and 2,500 owed gives 500 + 3,000 - 5,000 =
    -1,500 against a stated 2,500 — so a file that adds up perfectly would be
    refused. Mirrored, it is -500 + 3,000 - 5,000 = -2,500, which is the
    closing figure. `normalizer.balance_agreement` and the register's
    `first_divergence` compare each row's balance the same way and need the
    same sign. Hence one function, applied once, rather than a conversion at
    each of the places a balance is read.

    `rows` are `NormalizedTxn`, which is frozen: this REPLACES rather than
    mutates, which is also the honest shape — the parse's own reading of the
    file is not edited, a differently-signed reading is derived from it.
    """
    if not is_credit_card(account_type):
        return list(rows), opening, closing
    import dataclasses
    return (
        [dataclasses.replace(t, balance_paise=-int(t.balance_paise or 0)) for t in rows],
        None if opening is None else to_ledger_sign(account_type, opening),
        None if closing is None else to_ledger_sign(account_type, closing),
    )


def balance_label(account_type: Optional[str]) -> str:
    """What the balance column means, for a screen that must not decide it."""
    return "Amount owed" if is_credit_card(account_type) else "Balance"
