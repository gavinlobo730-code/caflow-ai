"""Which ledger did the money actually move through?

ONE RESOLVER, BECAUSE THERE WERE THREE ANSWERS TO ONE QUESTION

Before this module, three paths answered it and only one was right:

  * `bank_posting_service._resolve_bank` walked the statement to its
    `bank_accounts` row and used that account's own `coa_account_id` — correct;
  * `phase2_journal_service.receipt_journal_lines` and
    `journal_for_purchase_payment` called
    `_find_account(db, firm_id, client_id, "%Bank%", system_key="bank")` — a
    firm-wide generic ledger, no client filter, and no reference to anything the
    CA had chosen;
  * `opening_balance_service` used `coa_account_id` — correct, and separately.

So a statement line and a receipt for the SAME payment into the SAME bank
landed in different ledgers, and neither the cash account nor the chosen bank
was ever consulted by the receipt path. ACC-02, ACC-03 and SALES-08 are three
readings of that one line.

WHAT IT DECIDES, IN ORDER, AND WHY THAT ORDER

  1. An explicit `bank_account_id` WINS. It is a fact recorded on the document
     — the CA said which account — and nothing derived should override a stated
     fact.
  2. Otherwise a cash `payment_mode` resolves to Cash in Hand. "1001 Cash in
     Hand" and "1002 Petty Cash" are seeded into every chart of accounts and no
     automatic flow had ever posted to either, so a client's cash balance was
     zero however much cash they had taken.
  3. Otherwise the firm's generic Bank ledger, UNCHANGED from the old
     behaviour — and the result says so. A document recorded before migration
     342 has no `bank_account_id` and never will; re-pointing its journal
     afterwards would make the document and the ledger disagree, which is the
     class of defect migration 338 exists to prevent.

THE RESULT CARRIES ITS REASON, and that is not decoration. Step 3 is a
FALLBACK, and a fallback that cannot be distinguished from a decision is how
this went wrong in the first place: `_find_account(..., "%Bank%")` looked like
a lookup and was really a guess. `PaymentAccount.is_fallback` lets a caller —
and a test — tell the two apart.

WHAT THIS DELIBERATELY DOES NOT DO

It does not GUESS a bank account from the client's list when none is recorded.
A client with two current accounts banks at both, and picking the first or the
"main" one would post a plausible figure to the wrong sub-ledger — precisely
the failure being closed, moved one level down where it is harder to see.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

_logger = logging.getLogger("caflow.payment_account")

#: `payment_mode` values that mean physical cash rather than a bank.
#: Held here rather than tested inline so the receipt path, the payment path and
#: the tests cannot drift on what counts as cash. 'cheque', 'upi', 'neft',
#: 'rtgs' and 'online' are all BANK modes — they move money through an account.
CASH_PAYMENT_MODES = frozenset({"cash", "petty_cash", "petty cash"})

#: The seeded Cash in Hand ledger (coa_seed_service.STANDARD_COA "1001").
#: Matched by name because the seed sets no `system_account_key` for it.
CASH_ACCOUNT_PATTERN = "%Cash in Hand%"


@dataclass(frozen=True)
class PaymentAccount:
    """The ledger to post the cash leg to, and how it was decided."""
    account_id: str
    #: "bank_account" | "cash" | "generic_bank"
    source: str
    #: True when nothing on the document named an account and the firm's generic
    #: Bank ledger was used. The posting is still balanced and still correct
    #: double-entry; it is just not attributable to a specific account.
    is_fallback: bool
    #: A sentence for a CA, not a log line.
    reason: str


def _normalise_mode(payment_mode: Optional[str]) -> str:
    """Fold a payment_mode to one spelling: lowercase, separators unified.

    Both SPACE and HYPHEN, not just one. A first version normalised the hyphen
    on the input and the space on the constant, so "petty cash" — the spelling a
    human types — matched neither and was treated as a bank payment.
    """
    return "_".join(str(payment_mode or "").strip().lower().split())\
        .replace("-", "_")


#: Normalised once, so the set and the input are folded by the same function.
_CASH_MODES_NORMALISED = frozenset(_normalise_mode(m) for m in CASH_PAYMENT_MODES)


def is_cash_mode(payment_mode: Optional[str]) -> bool:
    """Does this payment_mode mean physical cash?"""
    return _normalise_mode(payment_mode) in _CASH_MODES_NORMALISED


def resolve_payment_account(
    db, *, firm_id: str, client_id: str,
    bank_account_id: Optional[str] = None,
    payment_mode: Optional[str] = None,
    find_account,
) -> PaymentAccount:
    """Resolve the ledger for a receipt's or payment's cash leg.

    `find_account` is injected rather than imported so this module stays free of
    `phase2_journal_service` — that module already imports half the service
    layer, and a domain module that drags it in cannot be unit-tested without a
    database. The caller passes `phase2_journal_service._find_account`.
    """
    # 1 — an account the CA actually named.
    if bank_account_id:
        try:
            row = (db.table("bank_accounts")
                   .select("id, coa_account_id, bank_name, account_type")
                   .eq("id", bank_account_id).eq("firm_id", firm_id)
                   .limit(1).execute().data or [{}])[0]
            coa_id = row.get("coa_account_id")
            if coa_id:
                name = row.get("bank_name") or "the selected account"
                return PaymentAccount(
                    account_id=coa_id, source="bank_account", is_fallback=False,
                    reason=f"Posted to {name}'s own ledger.")
            # The bank account exists and is UNLINKED. `_ensure_bank_ledger`
            # returns None rather than refusing a save when ledger creation
            # fails, so this is a state the product deliberately allows.
            _logger.warning(
                "bank account %s has no coa_account_id; falling back", bank_account_id)
        except Exception as e:  # noqa: BLE001
            from core.observability import capture_posting_failure
            capture_posting_failure(
                e, operation="resolve_payment_account.bank_account",
                firm_id=firm_id, client_id=client_id)

    # 2 — physical cash.
    if is_cash_mode(payment_mode):
        try:
            cash_id = find_account(db, firm_id, client_id, CASH_ACCOUNT_PATTERN)
            return PaymentAccount(
                account_id=cash_id, source="cash", is_fallback=False,
                reason="Cash payment — posted to Cash in Hand.")
        except Exception as e:  # noqa: BLE001
            # A chart of accounts without Cash in Hand is not one this product
            # seeded. Falling through to Bank is wrong but it is not silent: the
            # reason below says the cash ledger was missing.
            from core.observability import capture_posting_failure
            capture_posting_failure(
                e, operation="resolve_payment_account.cash",
                firm_id=firm_id, client_id=client_id)
            return PaymentAccount(
                account_id=find_account(db, firm_id, client_id, "%Bank%",
                                        system_key="bank"),
                source="generic_bank", is_fallback=True,
                reason=("This is a cash payment but the client's chart of accounts "
                        "has no Cash in Hand ledger, so it posted to Bank. Add the "
                        "ledger and repost."))

    # 3 — the firm's generic Bank ledger. Unchanged behaviour, named as a
    # fallback so it stops reading as a decision.
    return PaymentAccount(
        account_id=find_account(db, firm_id, client_id, "%Bank%", system_key="bank"),
        source="generic_bank", is_fallback=True,
        reason=("No bank account was recorded on this document, so it posted to "
                "the firm's general Bank ledger. Set the account to attribute it."))
