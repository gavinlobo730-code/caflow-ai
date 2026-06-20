"""
Banking Phase B.0 — unit tests for the bank-transaction double-entry builder.

Covers the single financial calculation introduced in B.0 (CLAUDE.md: every
financial calculation must have a corresponding unit test). The posting itself
reuses the already-tested _create_journal engine; here we prove the line
construction is balanced, correctly directed, and integer-paise.
"""
import pytest

from services.phase2_journal_service import Phase2JournalService

bank_txn_lines = Phase2JournalService.bank_txn_lines

ACC = "acc-counter"   # mapped GL counter-account
BANK = "acc-bank"     # bank's GL account


def _balanced(lines):
    return sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines)


def test_money_out_of_bank_is_payment_dr_counter_cr_bank():
    # debit_paise > 0 → money leaving the bank → Dr counter / Cr bank
    amount, entry_type, lines = bank_txn_lines(50000, 0, ACC, BANK)
    assert amount == 50000
    assert entry_type == "Payment"
    assert _balanced(lines)
    dr = next(l for l in lines if l["debit_paise"] > 0)
    cr = next(l for l in lines if l["credit_paise"] > 0)
    assert dr["account_id"] == ACC and dr["debit_paise"] == 50000
    assert cr["account_id"] == BANK and cr["credit_paise"] == 50000


def test_money_into_bank_is_receipt_dr_bank_cr_counter():
    # credit_paise > 0 → money entering the bank → Dr bank / Cr counter
    amount, entry_type, lines = bank_txn_lines(0, 75000, ACC, BANK)
    assert amount == 75000
    assert entry_type == "Receipt"
    assert _balanced(lines)
    dr = next(l for l in lines if l["debit_paise"] > 0)
    cr = next(l for l in lines if l["credit_paise"] > 0)
    assert dr["account_id"] == BANK and dr["debit_paise"] == 75000
    assert cr["account_id"] == ACC and cr["credit_paise"] == 75000


def test_zero_amount_raises():
    with pytest.raises(ValueError):
        bank_txn_lines(0, 0, ACC, BANK)


def test_amount_is_the_nonzero_side_and_integer_paise():
    # Only one side is ever non-zero on a real bank line; amount tracks it exactly.
    amount, _, lines = bank_txn_lines(0, 1, ACC, BANK)
    assert amount == 1
    assert all(isinstance(l["debit_paise"], int) and isinstance(l["credit_paise"], int) for l in lines)
    # Each line has exactly one non-zero leg.
    for l in lines:
        assert (l["debit_paise"] == 0) != (l["credit_paise"] == 0)


def test_handles_none_amounts_as_zero():
    # Defensive: None coerces to 0 (debit None, credit present → Receipt).
    amount, entry_type, lines = bank_txn_lines(None, 1200, ACC, BANK)
    assert amount == 1200 and entry_type == "Receipt" and _balanced(lines)
