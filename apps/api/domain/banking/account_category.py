"""
Deriving a bank CATEGORY from the GL account the CA picked (account-first coding).

WHY THIS EXISTS
    Coding a statement line used to take two answers in a fixed order: pick a
    Category, and only then — for seven of the eleven categories — pick the GL
    account the money actually goes to. The account picker did not even appear
    until a category had been chosen, which is why it read as missing.

    The first of those two answers mostly does not matter. posting_map.build_lines
    is direction-driven: money out debits the counter account, money in credits
    it, whatever the category says. entry_type_for returns Receipt or Payment
    from direction alone. So for Expense, Salary, Loan, Capital, Interest and
    Other — six of the eleven — the category changes NOTHING about the journal.
    The CA was answering a question with no consequence before being allowed to
    answer the one that had it.

    Only four category values are load-bearing:
      * Customer Payment / Vendor Payment / GST Payment — posting_map.AUTO_COUNTER
        resolves the counter account from a control key instead of asking;
      * Transfer — a contra between two of the client's own accounts;
      * and, with a matched document, Sales Receipt / Customer Payment settle a
        sales invoice and Vendor Payment settles a bill (SETTLES_*).

    So the ledger is the real answer and the category follows from it. This
    module is that derivation, kept pure and table-shaped so it can be read as a
    specification rather than traced through an if-chain.

WHAT IT WILL NOT DO
    It does not guess from account NAMES. Migration 092 introduced
    system_account_key precisely to stop reporting depending on "fragile account
    name matching", and adding a `%salary%` rule here would walk that back for a
    label that changes no journal line. An account whose type is Expense derives
    "Expense" even if it is called Salaries; a CA who wants the finer word sets
    it explicitly, and rules can still propose one.

THE ONE GUARANTEE
    Coding a line account-first must post the counter leg to EXACTLY the account
    that was picked — never to a near-namesake the system resolved for itself.

    That is not automatic, because the three AUTO_COUNTER categories re-resolve
    their account from a control key at posting time and ignore account_id
    entirely. And a control key does not identify ONE account. Migration 092's
    backfill stamps system_account_key='ar' on anything named "trade
    receivable" OR "accounts receivable" OR "sundry debtor", so a chart holding
    two of those names holds two accounts with the same key — and
    phase2_journal_service._find_account resolves it with `.limit(1)` and no
    ORDER BY, which picks one of them arbitrarily. Deriving "Customer Payment"
    from the account the CA picked would then post to whichever of the two
    Postgres happened to return.

    The mirror case is live on this client's books: an UNUSED "Accounts
    Receivable" keyed 'ar' beside the "Trade Receivables" everything actually
    posts to, whose key is NULL (the seeding defect
    reconciliation_service._find_account_id documents). There the derivation
    simply produces no auto category, which is already safe.

    So an AUTO_COUNTER category is only a CANDIDATE here. `DerivedCategory`
    carries the control key alongside a `fallback`, and the caller confirms the
    key resolves back to this very account before using it — see
    banking_service.set_account. When it does not, the fallback keeps the CA's
    chosen account as the counter leg. Nothing is silently substituted either
    way.

Pure: no database, no HTTP. Every branch is covered by
tests/test_bank_account_first_coding.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from domain.banking.posting_map import AUTO_COUNTER

# system_account_key → the category that key implies. Exactly the inverse of
# posting_map.AUTO_COUNTER, which maps the other way; derived from it below so
# the two cannot drift.
_KEY_TO_AUTO_CATEGORY: dict[str, str] = {key: cat for cat, (key, _pat) in AUTO_COUNTER.items()}

# What an ordinary ledger is called when nothing more specific applies. These are
# all EXPLICIT_COUNTER categories, so the account picked is the account posted —
# which is why a coarse label here costs nothing.
_TYPE_TO_CATEGORY: dict[str, str] = {
    "Expense": "Expense",
    "Equity": "Capital",
    "Asset": "Other",
    "Liability": "Other",
}

# Money arriving against a revenue ledger is a sale banked directly. Money
# LEAVING against one is a refund or a sales return, which "Sales Receipt" would
# describe wrongly — and Sales Receipt is in SETTLES_SALES_INVOICE, so the word
# is not merely cosmetic once a document is matched.
_REVENUE_TYPES = frozenset({"Revenue", "Income"})

TRANSFER = "Transfer"
BANK_KEY = "bank"


@dataclass(frozen=True)
class DerivedCategory:
    """The category implied by an account, and how much to trust it.

    `category` is what to store. `auto_counter_key` is set only when `category`
    is one of the three whose counter account the posting engine re-resolves
    from that key — the caller MUST check the key resolves back to the account
    that produced it, and use `fallback` when it does not. `fallback` is always
    a category whose counter account is the one explicitly chosen.
    """
    category: str
    auto_counter_key: Optional[str] = None
    fallback: str = "Other"

    @property
    def needs_confirmation(self) -> bool:
        return self.auto_counter_key is not None


def category_for_account(account: dict, *, is_credit: bool) -> DerivedCategory:
    """The category implied by picking `account` for a bank line.

    `account` is a chart_of_accounts row; only account_type, account_subtype,
    account_name and system_account_key are read. `is_credit` is the bank line's
    direction — money INTO the bank.
    """
    key = (account.get("system_account_key") or "").strip().lower() or None
    plain = _plain_category(account, is_credit=is_credit)

    # A bank or cash ledger on the other side of a bank line is a movement
    # between the client's own accounts. The picked account IS the destination,
    # which is how it reaches the posting engine (to_bank_account_id) — so this
    # needs no confirmation.
    if key == BANK_KEY or _looks_like_bank_or_cash(account):
        return DerivedCategory(TRANSFER, fallback=TRANSFER)

    auto = _KEY_TO_AUTO_CATEGORY.get(key) if key else None
    if auto:
        return DerivedCategory(auto, auto_counter_key=key, fallback=plain)

    return DerivedCategory(plain, fallback=plain)


def _plain_category(account: dict, *, is_credit: bool) -> str:
    """The label for an ordinary ledger — one the posting engine will honour by
    posting to the account itself."""
    acct_type = (account.get("account_type") or "").strip()
    if acct_type in _REVENUE_TYPES:
        return "Sales Receipt" if is_credit else "Other"
    return _TYPE_TO_CATEGORY.get(acct_type, "Other")


def _looks_like_bank_or_cash(account: dict) -> bool:
    """Migration 092's own bank/cash test, for charts its backfill did not reach.

    Deliberately the same rule and the same restriction: account_type must be
    Asset, so "Bank Loan" (Liability) and "Bank Charges" (Expense) cannot claim
    it. This is not new name-guessing — 092 states the resolver "falls back to
    name matching when NULL", and Transfer is the one derivation where getting it
    wrong changes the journal's SHAPE rather than only its label.
    """
    if (account.get("account_type") or "").strip() != "Asset":
        return False
    haystack = " ".join([
        str(account.get("account_name") or ""),
        str(account.get("account_subtype") or ""),
    ]).lower()
    return "bank" in haystack or "cash" in haystack
