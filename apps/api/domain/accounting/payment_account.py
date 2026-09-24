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


#: The three fallback sentences, named rather than written inline, because a
#: READ path has to be able to show the same words the posting showed and
#: `PaymentAccount.reason` is built at posting time and then thrown away.
NOTICE_NO_ACCOUNT_RECORDED = (
    "No bank account was recorded on this document, so it posted to the firm's "
    "general Bank ledger. Set the account to attribute it."
)
NOTICE_ACCOUNT_NOT_LINKED = (
    "The bank account on this document has no ledger of its own, so it posted "
    "to the firm's general Bank ledger. Link the account and repost."
)
NOTICE_NO_CASH_LEDGER = (
    "This is a cash payment but the client's chart of accounts has no Cash in "
    "Hand ledger, so it posted to Bank. Add the ledger and repost."
)


def document_names_no_account(
    bank_account_id: Optional[str], payment_mode: Optional[str]
) -> bool:
    """Branch 3's own precondition — nothing on the document names a ledger.

    Asked by `resolve_payment_account` below AND by any read path that wants to
    mark a list row. ONE rule with two callers rather than two rules: a screen
    re-deriving "did this fall back" from its own reading of the columns is how
    a disclosure comes to disagree with the posting it describes.
    """
    return not bank_account_id and not is_cash_mode(payment_mode)


def row_notice(
    bank_account_id: Optional[str], payment_mode: Optional[str]
) -> Optional[str]:
    """What a LIST ROW can say from the document's own two columns, with no
    database read.

    THIS IS DELIBERATELY NOT THE WHOLE ANSWER, and saying so is the point. Two
    of the three fallbacks are facts about the CHART OF ACCOUNTS at the moment
    of posting — a bank account with no ledger of its own, a client with no Cash
    in Hand — and a row cannot see either without a lookup per row, which is the
    read-proportional-to-the-ledger shape CLAUDE.md forbids in a report. Those
    two reach the CA in the POSTING CONFIRMATION, where the resolver's own
    answer is to hand and where it is cheapest to act on.

    So the row catches the common case exactly and stays silent on the rare
    ones, rather than guessing at them. A silent row is not a claim that the
    posting was attributable; the confirmation is where the full answer is
    given.
    """
    return NOTICE_NO_ACCOUNT_RECORDED if document_names_no_account(
        bank_account_id, payment_mode) else None


#: The key every document response carries the notice under. Named so a screen
#: and a test cannot disagree about the spelling, and so a grep finds every
#: place it is served.
NOTICE_KEY = "posting_account_notice"


def stamp(row: dict) -> dict:
    """Add `posting_account_notice` to one document row, reading its own
    `bank_account_id` and `payment_mode`.

    ALWAYS PRESENT, null where the posting was attributable — the
    `journal_source` discipline. An absent key and a null key read the same to
    a screen and are different bugs: null is "this posting named its account",
    absent is "this build did not look", and only the first is something the
    screen can render.

    Mutates and returns the row: every caller is stamping a row it has just
    fetched or built and is about to serve, and a copy there is a copy of a
    whole document for a field that is usually None.
    """
    row[NOTICE_KEY] = row_notice(row.get("bank_account_id"), row.get("payment_mode"))
    return row


def stamp_all(rows: list) -> list:
    """`stamp` over a list, for a LIST endpoint. Skips a non-dict rather than
    raising: a list read that returns something unexpected should not turn a
    disclosure into a 500 on the screen the disclosure is for."""
    for r in rows:
        if isinstance(r, dict):
            stamp(r)
    return rows


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
            # The account IS recorded; it simply has no ledger. Falling
            # through to branch 3 used to report "No bank account was recorded
            # on this document", which is FALSE and sends the CA to set a field
            # that is already set. Found on 24-09-2026 while surfacing these
            # sentences — the defect was invisible for as long as nothing
            # rendered them.
            _logger.warning(
                "bank account %s has no coa_account_id; falling back", bank_account_id)
            if not is_cash_mode(payment_mode):
                return PaymentAccount(
                    account_id=find_account(db, firm_id, client_id, "%Bank%",
                                            system_key="bank"),
                    source="generic_bank", is_fallback=True,
                    reason=NOTICE_ACCOUNT_NOT_LINKED)
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
                reason=NOTICE_NO_CASH_LEDGER)

    # 3 — the firm's generic Bank ledger. Unchanged behaviour, named as a
    # fallback so it stops reading as a decision.
    return PaymentAccount(
        account_id=find_account(db, firm_id, client_id, "%Bank%", system_key="bank"),
        source="generic_bank", is_fallback=True,
        reason=NOTICE_NO_ACCOUNT_RECORDED)
