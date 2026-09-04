"""
A bank line cannot be booked to the account its own statement belongs to.

WHAT WAS WRONG

Coding a statement line to the GL ledger that same statement posts to produces:

    Dr  Bank X   5,000
    Cr  Bank X   5,000

THAT BALANCES, which is precisely why nothing caught it.

  * the posting kernel's double-entry assertion is satisfied — debits equal
    credits, so `_create_journal` writes it;
  * the bank balance stays RIGHT, because the pair nets to zero, so no report
    looks wrong;
  * the transaction is marked posted and leaves the review queue.

And nothing was classified. The expense or income the line actually represents
is nowhere in the books, the bank ledger carries a meaningless pair, and the
entry is immutable the moment it lands (DB triggers) — undoing it needs an
append-only reversal, not a correction.

`build_transfer_lines` has refused this since it was written ("Transfer accounts
must differ"), and `bank_posting_service._plan` says so in a sentence a CA can
read. But that guard sat in the TRANSFER branch only, so the rule held exactly
when the category happened to be Transfer — and a line reaching the ordinary
two-leg builder, or a split allocating one leg to the same ledger, went
straight through.

WHERE THE FIX SITS

In the domain, beside the transfer rule, because it is the same rule: a
movement's two legs cannot be one account. Both builders now refuse, and
_plan already converts a ValueError/SplitError into a 422 with the reason.

The picker also stops OFFERING the client's own bank and cash ledgers — every
one of them, not only this statement's, because moving money between two own
accounts is a CONTRA with its own category, builder and destination field.
Coding it as an ordinary two-leg posting is the same mistake wearing a
different account id.

NEGATIVE CONTROLS
    Drop the check in build_lines and
    test_the_two_leg_builder_refuses_its_own_ledger fails.
    Drop it in build_split_lines and
    test_a_split_leg_cannot_be_the_bank_itself fails.
"""
from __future__ import annotations

import pytest

from domain.banking.posting_map import build_lines, build_transfer_lines
from domain.banking.splits import Split, SplitError, build_split_lines

BANK = "coa-bank-1"
OTHER = "coa-expense-1"


# ─── the two-leg builder ────────────────────────────────────────────────────

def test_a_normal_two_leg_posting_still_works():
    """The fixture must post or every refusal below proves nothing."""
    lines = build_lines(500_000, False, BANK, OTHER)
    assert len(lines) == 2
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines)


@pytest.mark.parametrize("is_credit", [True, False])
def test_the_two_leg_builder_refuses_its_own_ledger(is_credit):
    """In BOTH directions. A receipt coded to its own bank and a payment coded
    to its own bank are the same fault."""
    with pytest.raises(ValueError) as e:
        build_lines(500_000, is_credit, BANK, BANK)
    assert "same ledger" in str(e.value)


def test_the_refusal_says_what_the_ca_did_rather_than_naming_a_rule():
    """"Accounts must differ" leaves a CA guessing which two. This names the
    thing they picked and what it would have done."""
    with pytest.raises(ValueError) as e:
        build_lines(500_000, True, BANK, BANK)
    msg = str(e.value)
    assert "its own statement belongs to" in msg
    assert "classify nothing" in msg


def test_the_transfer_builder_already_refused_it():
    """Pinned because this is the guard that existed, and the two must not
    drift apart again."""
    with pytest.raises(ValueError):
        build_transfer_lines(500_000, True, BANK, BANK)


# ─── the split builder ──────────────────────────────────────────────────────

def test_a_normal_split_still_works():
    lines = build_split_lines(
        [Split(account_id=OTHER, amount_paise=300_000),
         Split(account_id="coa-expense-2", amount_paise=200_000)],
        is_credit=False, bank_account_id=BANK, amount_paise=500_000)
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines)


def test_a_split_leg_cannot_be_the_bank_itself():
    """Hidden better than the two-leg case: the journal still balances, the
    other legs still look right, and the bank ledger quietly carries a debit and
    a credit for PART of one movement."""
    with pytest.raises(SplitError) as e:
        build_split_lines(
            [Split(account_id=OTHER, amount_paise=300_000),
             Split(account_id=BANK, amount_paise=200_000)],
            is_credit=False, bank_account_id=BANK, amount_paise=500_000)
    assert "statement itself belongs to" in str(e.value)


def test_the_split_refusal_points_at_the_contra():
    """A CA who did this usually meant a transfer between own accounts, and
    that has its own category and builder."""
    with pytest.raises(SplitError) as e:
        build_split_lines([Split(account_id=BANK, amount_paise=500_000)],
                          is_credit=True, bank_account_id=BANK, amount_paise=500_000)
    assert "Contra" in str(e.value) or "Transfer" in str(e.value)


# ─── what reaches a CA ──────────────────────────────────────────────────────

def test_the_service_turns_both_refusals_into_a_422_not_a_500():
    """Everything that reaches a CA has to be a refusal with a reason. _plan
    already wraps both builders; this pins that it still does, because a
    ValueError escaping to the middleware is an "Internal server error" for
    something the CA can actually fix."""
    import inspect

    from services.bank_posting_service import bank_posting_service
    src = inspect.getsource(bank_posting_service._plan)
    assert "except ValueError as e:" in src
    assert "except SplitError as e:" in src
    assert src.count("status_code=422") >= 2
