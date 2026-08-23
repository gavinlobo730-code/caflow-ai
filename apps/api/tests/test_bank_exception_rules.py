"""
What a partner should be shown, and what should stop the books.

These tests are the specification. Each one states a situation a CA would
recognise and asserts what the engine makes of it, so disagreeing with the design
means disagreeing with a named test rather than with an opinion.

The engine is pure — dictionaries in, flags out, "today" passed in — so nothing
here needs a database and nothing depends on when it runs.
"""
from datetime import date

import pytest

from domain.banking.exceptions import (
    BankException, ExceptionPolicy, TxnContext,
    blocks_posting, evaluate, _rupees,
)

TODAY = date(2026, 4, 30)
POLICY = ExceptionPolicy()          # the shipped defaults, exercised as shipped


def txn(**over) -> dict:
    base = {"id": "t1", "transaction_date": "2026-04-15", "description": "NEFT CR-ACME",
            "debit_paise": 0, "credit_paise": 250_000, "payee_name": "Acme Traders",
            "category": "Customer Payment", "account_id": "acc-ar",
            "matched_entity_id": None}
    base.update(over)
    return base


def codes(t, ctx=None, policy=POLICY):
    return [e.code for e in evaluate(t, ctx, policy, TODAY)]


# ══════════════════════════════════════════════════════════════════════════════
# The ordinary case
# ══════════════════════════════════════════════════════════════════════════════

def test_an_ordinary_transaction_raises_nothing():
    """The point of the whole design. Most of a statement is unremarkable and
    must stay unremarkable, or the list is as useless as approving everything."""
    ctx = TxnContext(known_payees=frozenset({"acme traders"}),
                     known_accounts=frozenset({"acc-ar"}))
    assert codes(txn(), ctx) == []
    assert blocks_posting(evaluate(txn(), ctx, POLICY, TODAY)) is False


def test_an_exact_match_to_a_known_party_raises_nothing():
    ctx = TxnContext(known_payees=frozenset({"acme traders"}),
                     known_accounts=frozenset({"acc-ar"}),
                     matched_outstanding_paise=250_000,
                     matched_document_no="INV-001", matched_party_name="Acme Traders")
    assert codes(txn(matched_entity_id="inv-1"), ctx) == []


# ══════════════════════════════════════════════════════════════════════════════
# Size
# ══════════════════════════════════════════════════════════════════════════════

def test_a_transaction_at_materiality_blocks():
    t = txn(credit_paise=POLICY.materiality_paise)
    found = evaluate(t, TxnContext(known_payees=frozenset({"acme traders"}),
                                   known_accounts=frozenset({"acc-ar"})), POLICY, TODAY)
    assert [e.code for e in found] == ["above_materiality"]
    assert found[0].severity == "high" and found[0].blocking is True
    assert blocks_posting(found) is True


def test_a_rupee_below_materiality_does_not():
    t = txn(credit_paise=POLICY.materiality_paise - 100)
    ctx = TxnContext(known_payees=frozenset({"acme traders"}),
                     known_accounts=frozenset({"acc-ar"}))
    assert codes(t, ctx) == []


def test_materiality_is_per_client_not_a_constant():
    """A ₹2,000 payment is nothing to a trading company and material to a
    one-person consultancy. The threshold is policy, and the test says so."""
    small = ExceptionPolicy(materiality_paise=100_000)      # ₹1,000
    ctx = TxnContext(known_payees=frozenset({"acme traders"}),
                     known_accounts=frozenset({"acc-ar"}))
    assert codes(txn(credit_paise=200_000), ctx, small) == ["above_materiality"]
    assert codes(txn(credit_paise=200_000), ctx, POLICY) == []


# ══════════════════════════════════════════════════════════════════════════════
# Settlement differences — the "Settle difference" button, seen from behind
# ══════════════════════════════════════════════════════════════════════════════

def test_a_large_shortfall_blocks_because_it_writes_money_off():
    ctx = TxnContext(known_payees=frozenset({"acme traders"}),
                     known_accounts=frozenset({"acc-ar"}),
                     matched_outstanding_paise=1_760_547,   # ₹17,605.47
                     matched_document_no="INV-BULK-00836",
                     matched_party_name="Acme Traders")
    found = evaluate(txn(matched_entity_id="inv-1", credit_paise=250_000),
                     ctx, POLICY, TODAY)
    short = next(e for e in found if e.code == "short_settlement")
    assert short.blocking is True and short.severity == "high"
    assert "₹15,105.47" in short.message and "writes that off" in short.message


def test_a_bank_charge_sized_shortfall_is_not_worth_anyone_s_time():
    """A remitter deducting ₹50 of charges is ordinary. If this raised a flag the
    list would fill with noise and stop being read, which is the failure mode
    that matters most here."""
    ctx = TxnContext(known_payees=frozenset({"acme traders"}),
                     known_accounts=frozenset({"acc-ar"}),
                     matched_outstanding_paise=255_000,
                     matched_document_no="INV-001", matched_party_name="Acme Traders")
    assert codes(txn(matched_entity_id="inv-1", credit_paise=250_000), ctx) == []


def test_a_middling_shortfall_is_flagged_but_still_posts():
    ctx = TxnContext(known_payees=frozenset({"acme traders"}),
                     known_accounts=frozenset({"acc-ar"}),
                     matched_outstanding_paise=350_000,     # ₹1,000 short of ₹3,500
                     matched_document_no="INV-001", matched_party_name="Acme Traders")
    found = evaluate(txn(matched_entity_id="inv-1", credit_paise=250_000),
                     ctx, POLICY, TODAY)
    short = next(e for e in found if e.code == "short_settlement")
    assert short.severity == "medium" and short.blocking is False
    assert blocks_posting(found) is False


def test_an_overpayment_is_flagged_as_a_credit_not_a_write_off():
    ctx = TxnContext(known_payees=frozenset({"acme traders"}),
                     known_accounts=frozenset({"acc-ar"}),
                     matched_outstanding_paise=100_000,
                     matched_document_no="INV-001", matched_party_name="Acme Traders")
    found = evaluate(txn(matched_entity_id="inv-1", credit_paise=250_000),
                     ctx, POLICY, TODAY)
    over = next(e for e in found if e.code == "over_settlement")
    assert "leaves a credit" in over.message


# ══════════════════════════════════════════════════════════════════════════════
# Weak matches
# ══════════════════════════════════════════════════════════════════════════════

def test_a_match_on_neither_amount_nor_name_is_flagged():
    ctx = TxnContext(known_payees=frozenset({"acme traders"}),
                     known_accounts=frozenset({"acc-ar"}),
                     matched_outstanding_paise=251_000,
                     matched_document_no="INV-009",
                     matched_party_name="Fortune Traders")
    assert "weak_match" in codes(txn(matched_entity_id="inv-9",
                                     description="NEFT CR-UNKNOWN"), ctx)


def test_the_party_appearing_in_the_narration_is_enough():
    """An inexact amount is forgivable when the narration names the party — that
    is a partial payment from a known customer, which is ordinary business."""
    ctx = TxnContext(known_payees=frozenset({"acme traders"}),
                     known_accounts=frozenset({"acc-ar"}),
                     matched_outstanding_paise=251_000,
                     matched_document_no="INV-009", matched_party_name="Acme Traders")
    assert "weak_match" not in codes(
        txn(matched_entity_id="inv-9", description="NEFT CR-SBIN-ACME TRADERS"), ctx)


def test_an_unmatched_transaction_cannot_be_a_weak_match():
    ctx = TxnContext(known_payees=frozenset({"acme traders"}),
                     known_accounts=frozenset({"acc-ar"}))
    assert "weak_match" not in codes(txn(), ctx)


# ══════════════════════════════════════════════════════════════════════════════
# Cash
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("narration", [
    "ATM WDL 412345 MUMBAI", "CASH WITHDRAWAL", "SELF CHQ 000123",
    "NFS/CASH/412345", "CWDR BRANCH", "BY CASH",
])
def test_cash_out_above_the_threshold_blocks(narration):
    ctx = TxnContext(known_payees=frozenset({"acme traders"}),
                     known_accounts=frozenset({"acc-ar"}))
    found = evaluate(txn(description=narration, debit_paise=5_000_000, credit_paise=0),
                     ctx, POLICY, TODAY)
    cash = next(e for e in found if e.code == "cash_withdrawal")
    assert cash.blocking is True


def test_small_cash_is_left_alone():
    ctx = TxnContext(known_payees=frozenset({"acme traders"}),
                     known_accounts=frozenset({"acc-ar"}))
    assert "cash_withdrawal" not in codes(
        txn(description="ATM WDL 412345", debit_paise=200_000, credit_paise=0), ctx)


def test_cash_COMING_IN_is_not_a_withdrawal():
    """A cash deposit is a different question and not this rule's."""
    ctx = TxnContext(known_payees=frozenset({"acme traders"}),
                     known_accounts=frozenset({"acc-ar"}))
    assert "cash_withdrawal" not in codes(
        txn(description="CASH DEPOSIT", debit_paise=0, credit_paise=9_000_000), ctx)


def test_a_payee_merely_named_cashew_is_not_a_cash_withdrawal():
    """Word boundaries, not substrings — the rule must not fire on 'CASHEW
    EXPORTS' or 'PRAKASH'."""
    ctx = TxnContext(known_payees=frozenset({"cashew exports"}),
                     known_accounts=frozenset({"acc-ar"}))
    assert "cash_withdrawal" not in codes(
        txn(description="NEFT DR-CASHEW EXPORTS PVT LTD", payee_name="Cashew Exports",
            debit_paise=9_000_000, credit_paise=0), ctx)


# ══════════════════════════════════════════════════════════════════════════════
# Duplicates, new payees, unfamiliar accounts
# ══════════════════════════════════════════════════════════════════════════════

def test_the_same_amount_to_the_same_payee_within_the_window_is_flagged():
    ctx = TxnContext(known_payees=frozenset({"acme traders"}),
                     known_accounts=frozenset({"acc-ar"}),
                     siblings=(("t2", "2026-04-17", 250_000, "Acme Traders"),))
    found = evaluate(txn(), ctx, POLICY, TODAY)
    dup = next(e for e in found if e.code == "duplicate_suspect")
    assert dup.blocking is False and "2026-04-17" in dup.message


def test_the_same_amount_outside_the_window_is_a_monthly_payment_not_a_duplicate():
    ctx = TxnContext(known_payees=frozenset({"acme traders"}),
                     known_accounts=frozenset({"acc-ar"}),
                     siblings=(("t2", "2026-05-15", 250_000, "Acme Traders"),))
    assert "duplicate_suspect" not in codes(txn(), ctx)


def test_a_transaction_is_never_its_own_duplicate():
    ctx = TxnContext(known_payees=frozenset({"acme traders"}),
                     known_accounts=frozenset({"acc-ar"}),
                     siblings=(("t1", "2026-04-15", 250_000, "Acme Traders"),))
    assert "duplicate_suspect" not in codes(txn(), ctx)


def test_a_payee_never_seen_before_is_flagged_quietly():
    ctx = TxnContext(known_accounts=frozenset({"acc-ar"}))
    found = evaluate(txn(), ctx, POLICY, TODAY)
    new = next(e for e in found if e.code == "new_payee")
    assert new.severity == "low" and new.blocking is False


def test_an_account_this_client_has_never_used_is_flagged():
    ctx = TxnContext(known_payees=frozenset({"acme traders"}))
    assert "unusual_account" in codes(txn(account_id="acc-never-seen"), ctx)


# ══════════════════════════════════════════════════════════════════════════════
# The list itself
# ══════════════════════════════════════════════════════════════════════════════

def test_the_worst_thing_is_listed_first():
    """A partner reads from the top and stops when they run out of afternoon."""
    ctx = TxnContext(matched_outstanding_paise=20_000_000,
                     matched_document_no="INV-BIG", matched_party_name="Someone Else")
    found = evaluate(txn(matched_entity_id="inv-1", credit_paise=15_000_000,
                         account_id="acc-new"), ctx, POLICY, TODAY)
    assert [e.severity for e in found] == sorted(
        [e.severity for e in found], key=lambda s: {"high": 0, "medium": 1, "low": 2}[s])
    assert found[0].severity == "high"


def test_one_transaction_can_raise_several_and_any_one_blocker_holds_it():
    ctx = TxnContext()
    found = evaluate(txn(credit_paise=20_000_000, account_id="acc-new"), ctx, POLICY, TODAY)
    assert {"above_materiality", "new_payee", "unusual_account"} <= {e.code for e in found}
    assert blocks_posting(found) is True


def test_every_message_is_written_for_a_ca_not_a_log():
    """No codes, no ids, no snake_case leaking into what a partner reads."""
    ctx = TxnContext(matched_outstanding_paise=9_000_000,
                     matched_document_no="INV-77", matched_party_name="Someone Else")
    for e in evaluate(txn(matched_entity_id="i", credit_paise=20_000_000,
                          description="ATM WDL", account_id="acc-new"),
                      ctx, POLICY, TODAY):
        # Sentence case, or an amount — "₹2,00,000.00 is at or above…" opens with
        # the figure, which is the right place for it.
        assert e.message.endswith(".")
        assert e.message[0].isupper() or e.message[0] == "\u20b9"
        assert "_" not in e.message


@pytest.mark.parametrize("paise,text", [
    (0, "₹0.00"), (100, "₹1.00"), (99, "₹0.99"), (100_000, "₹1,000.00"),
    (10_000_000, "₹1,00,000.00"), (100_000_000, "₹10,00,000.00"),
    (1_000_000_000, "₹1,00,00,000.00"), (14_254_324, "₹1,42,543.24"),
])
def test_money_is_written_the_way_an_indian_reader_expects(paise, text):
    """Lakh/crore grouping, not thousands. A CA reading ₹1,000,00.00 has to stop
    and count digits, and the whole value of this list is that it is skimmable."""
    assert _rupees(paise) == text
