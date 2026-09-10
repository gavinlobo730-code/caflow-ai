"""BANK-09 — a statement that says the same thing twice meant it.

WHAT WAS WRONG
    `transaction_hash` included the running balance so two identical same-day
    debits — distinct balances — stayed apart. A statement with NO BALANCE
    COLUMN gives every row a balance of 0, so that defence was absent exactly
    where it was needed: two ₹5,000 ATM withdrawals on one day, or two
    identical UPI payments to the same payee, hashed the same and the second
    was dropped.

    The client's withdrawals were then understated by exactly that amount, and
    the only trace was `duplicates_skipped`, which means "already imported" —
    a different statement about a different row.

    It also made the import DISAGREE WITH ITS OWN VERIFICATION. The router runs
    statement_check over the PARSED rows before anything is written, so the
    arithmetic that decides whether the file adds up ran on twenty rows and
    nineteen were stored. The one check that could have caught the merge ran on
    the wrong set.

WHY AN OCCURRENCE COUNT AND NOT THE ROW'S POSITION
    The obvious fix — hash the row's ordinal position in the file — breaks the
    thing the hash is actually for. A CA uploads 1–15 April, then 1–30 April;
    every overlapping row has a new position in the second file and would be
    re-imported. An occurrence count is how many rows with these EXACT FIELDS
    came before this one in the same file, so a row that is unique within each
    file is occurrence 0 in both and still matches.

NO MIGRATION, WHICH THE FINDING SAID OTHERWISE
    Migration 224's UNIQUE (client_id, import_hash) only blocks keeping both
    rows if both keep the SAME hash. They no longer do.
"""
from __future__ import annotations

import pytest

from domain.banking.dedup import hash_rows, transaction_hash

CLIENT = "c-1"
ACCOUNT = "b-1"


def _row(date="2026-04-01", debit=500000, credit=0, balance=0,
         desc="ATM WDL", ref=None):
    return {"transaction_date": date, "debit_paise": debit,
            "credit_paise": credit, "balance_paise": balance,
            "description": desc, "reference_no": ref}


# ── The defect ──────────────────────────────────────────────────────────────

def test_two_identical_rows_get_two_hashes():
    hashes, repeated = hash_rows(CLIENT, ACCOUNT, [_row(), _row()])
    assert len(set(hashes)) == 2
    assert repeated == 1


def test_a_balance_column_was_never_the_whole_answer():
    """With a balance the old hash worked; without one it did not, and a
    statement with no balance column is ordinary."""
    with_balance, _ = hash_rows(CLIENT, ACCOUNT, [
        _row(balance=1000000), _row(balance=500000)])
    without, _ = hash_rows(CLIENT, ACCOUNT, [_row(balance=0), _row(balance=0)])
    assert len(set(with_balance)) == 2
    assert len(set(without)) == 2       # the case that used to collapse


def test_three_identical_rows_are_three():
    hashes, repeated = hash_rows(CLIENT, ACCOUNT, [_row(), _row(), _row()])
    assert len(set(hashes)) == 3
    assert repeated == 2


# ── What the hash is actually for, unbroken ─────────────────────────────────

def test_the_same_file_twice_hashes_the_same():
    rows = [_row(), _row(), _row(desc="Fee", debit=100)]
    first, _ = hash_rows(CLIENT, ACCOUNT, rows)
    second, _ = hash_rows(CLIENT, ACCOUNT, list(rows))
    assert first == second


def test_a_row_unique_in_each_file_matches_across_them():
    """1–15 April, then 1–30 April. Hashing the row's POSITION would give every
    overlapping row a new hash and re-import the lot."""
    a = [_row(desc="A"), _row(desc="B", date="2026-04-05")]
    b = a + [_row(desc="C", date="2026-04-20")]
    ha, _ = hash_rows(CLIENT, ACCOUNT, a)
    hb, _ = hash_rows(CLIENT, ACCOUNT, b)
    assert hb[:2] == ha
    assert hb[2] not in ha


def test_a_repeated_pair_matches_across_an_overlapping_file():
    """The harder half: the pair is occurrence 0 and 1 in each file, so BOTH
    match rather than only the first."""
    a = [_row(), _row()]
    b = a + [_row(desc="C", date="2026-04-20")]
    ha, _ = hash_rows(CLIENT, ACCOUNT, a)
    hb, _ = hash_rows(CLIENT, ACCOUNT, b)
    assert set(ha) <= set(hb)


def test_a_row_that_differs_in_any_field_is_a_different_row():
    base = _row()
    for field, value in (("transaction_date", "2026-04-02"),
                         ("debit_paise", 500001), ("credit_paise", 1),
                         ("balance_paise", 1), ("description", "ATM WDL 2"),
                         ("reference_no", "R1")):
        other = {**base, field: value}
        hashes, repeated = hash_rows(CLIENT, ACCOUNT, [base, other])
        assert len(set(hashes)) == 2, field
        assert repeated == 0, field


def test_the_first_occurrence_hashes_exactly_as_it_always_did():
    """Rows already in the database keep matching. Changing the occurrence-0
    hash would re-import every transaction this product has ever stored."""
    r = _row()
    hashes, _ = hash_rows(CLIENT, ACCOUNT, [r])
    assert hashes[0] == transaction_hash(
        CLIENT, ACCOUNT, r["transaction_date"], r["debit_paise"],
        r["credit_paise"], r["balance_paise"], r["description"],
        r["reference_no"])


# ── The repeat count is a real figure, not decoration ───────────────────────

def test_the_repeat_count_is_taken_from_the_base_hash():
    """The returned hashes are distinct BY CONSTRUCTION, so counting duplicates
    among them would always answer zero."""
    hashes, repeated = hash_rows(CLIENT, ACCOUNT, [_row(), _row(), _row()])
    assert len(hashes) - len(set(hashes)) == 0     # the wrong way to count
    assert repeated == 2                            # the right one


def test_no_rows_is_no_repeats():
    assert hash_rows(CLIENT, ACCOUNT, []) == ([], 0)


# ── The check and the import see the same rows ──────────────────────────────

def test_the_import_stores_every_row_the_arithmetic_checked():
    """routers/banking.py runs statement_check over the PARSED rows before
    anything is written. Dropping rows afterwards meant the file added up over
    a set that was never stored."""
    from services.banking_service import banking_service
    from tests.test_bank_feed_import import FakeDB, FIRM, CLIENT as C

    db = FakeDB()
    rows = [_row(), _row(), _row(desc="Fee", debit=100)]
    from domain.banking.normalizer import NormalizedTxn
    txns = [NormalizedTxn(**r) for r in rows]
    res = banking_service.import_normalized(db, FIRM, C, "HDFC", "123", txns)
    assert res["total_rows"] == 3
    assert res["imported"] == 3
    assert len(db.store["bank_transactions"]) == 3
    assert res["repeated_in_file"] == 1
