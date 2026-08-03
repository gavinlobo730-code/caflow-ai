"""
The bank register (Tier 1.1) — running-balance arithmetic.

A running balance is a financial calculation (CLAUDE.md), and it is one where a
single misplaced line corrupts every figure below it rather than just its own.
So the ordering rule, the opening-balance boundary and the self-check against
the bank's stated balance are all tested directly.

Integer paise everywhere. If any assertion here can pass with a float, the test
is wrong.
"""
from datetime import date

import pytest

from domain.banking.register import (
    RegisterLine, build_register, first_divergence, summarise, sort_key,
    derive_cleared, CLEARED_NONE, CLEARED_PENDING, CLEARED_RECONCILED,
)


def _t(id_, d, *, debit=0, credit=0, balance=None, created="2026-01-01T00:00:00Z", **kw):
    row = {
        "id": id_, "transaction_date": d, "description": f"TXN {id_}",
        "debit_paise": debit, "credit_paise": credit, "balance_paise": balance,
        "created_at": created, "reference_no": None, "category": None,
        "match_status": "unmatched", "posted_journal_id": None,
        "reconciliation_id": None,
    }
    row.update(kw)
    return row


# ══════════════════════════════════════════════════════════════════════════════
# The running balance
# ══════════════════════════════════════════════════════════════════════════════

def test_the_balance_walks_forward_through_credits_and_debits():
    lines = build_register([
        _t("a", "2026-04-01", credit=10000),
        _t("b", "2026-04-02", debit=3000),
        _t("c", "2026-04-03", credit=500),
    ], opening_balance_paise=100000)
    assert [l.balance_paise for l in lines] == [110000, 107000, 107500]


def test_an_empty_register_still_reports_the_opening_balance():
    assert build_register([], opening_balance_paise=100000) == []
    assert summarise([], opening_balance_paise=100000)["closing_balance_paise"] == 100000


def test_the_balance_can_go_negative():
    """An overdraft is a real account type in this system (bank_accounts
    CHECK allows 'Overdraft'), so a negative running balance is legitimate and
    must not be clamped."""
    lines = build_register([_t("a", "2026-04-01", debit=50000)], opening_balance_paise=10000)
    assert lines[0].balance_paise == -40000


def test_every_balance_is_an_integer_number_of_paise():
    lines = build_register([
        _t("a", "2026-04-01", credit=33333),
        _t("b", "2026-04-02", debit=11111),
    ], opening_balance_paise=1)
    assert all(isinstance(l.balance_paise, int) for l in lines)
    assert lines[-1].balance_paise == 1 + 33333 - 11111


def test_the_closing_balance_equals_opening_plus_deposits_minus_withdrawals():
    """THE invariant. If this can drift, the register is not a ledger."""
    txns = [_t(str(i), f"2026-04-{i:02d}", credit=i * 100, debit=i * 37) for i in range(1, 29)]
    lines = build_register(txns, opening_balance_paise=987654)
    s = summarise(lines, opening_balance_paise=987654)
    assert (s["opening_balance_paise"] + s["deposits_paise"] - s["withdrawals_paise"]
            == s["closing_balance_paise"] == lines[-1].balance_paise)


def test_a_line_carrying_both_a_debit_and_a_credit_nets_correctly():
    """Malformed, but some statements do it. Net the two rather than picking one."""
    lines = build_register([_t("a", "2026-04-01", debit=2000, credit=5000)])
    assert lines[0].balance_paise == 3000
    assert lines[0].amount_paise == 3000


# ══════════════════════════════════════════════════════════════════════════════
# Ordering — non-determinism here silently corrupts every balance below
# ══════════════════════════════════════════════════════════════════════════════

def test_rows_are_ordered_by_date_regardless_of_input_order():
    lines = build_register([
        _t("c", "2026-04-03", credit=300),
        _t("a", "2026-04-01", credit=100),
        _t("b", "2026-04-02", credit=200),
    ])
    assert [l.transaction_id for l in lines] == ["a", "b", "c"]
    assert [l.balance_paise for l in lines] == [100, 300, 600]


def test_same_date_rows_fall_back_to_import_order():
    """created_at is import order, which preserves the order the BANK listed
    them in — the only defensible tiebreak for two same-day transactions.

    The ids here deliberately sort OPPOSITE to the import order ('zzz' imported
    before 'aaa'). An earlier version of this test used ids that happened to
    sort the same way as created_at, so it passed even with created_at removed
    from the sort key entirely — it asserted nothing. Only created_at can put
    these two in the right order."""
    lines = build_register([
        _t("aaa", "2026-04-01", debit=500, created="2026-01-01T00:00:02Z"),
        _t("zzz", "2026-04-01", credit=1000, created="2026-01-01T00:00:01Z"),
    ], opening_balance_paise=0)
    assert [l.transaction_id for l in lines] == ["zzz", "aaa"]
    assert [l.balance_paise for l in lines] == [1000, 500]


def test_identical_date_and_created_at_still_order_totally():
    """Without the id tiebreak the order would depend on input order, so the
    same data could render two different balance columns."""
    a = _t("aaa", "2026-04-01", credit=100, created="2026-01-01T00:00:00Z")
    b = _t("bbb", "2026-04-01", credit=200, created="2026-01-01T00:00:00Z")
    assert ([l.transaction_id for l in build_register([a, b])]
            == [l.transaction_id for l in build_register([b, a])]
            == ["aaa", "bbb"])


def test_the_balance_column_is_identical_no_matter_how_the_input_was_shuffled():
    import random
    txns = [_t(f"t{i:03d}", f"2026-04-{(i % 28) + 1:02d}", credit=i * 7, debit=i * 3,
               created=f"2026-01-01T00:00:{i % 60:02d}Z") for i in range(60)]
    expected = [l.balance_paise for l in build_register(txns, opening_balance_paise=5000)]
    for seed in range(5):
        shuffled = txns[:]
        random.Random(seed).shuffle(shuffled)
        assert [l.balance_paise for l in build_register(shuffled, opening_balance_paise=5000)] == expected


def test_sort_key_survives_a_missing_or_unparseable_date():
    """A row with no usable date must not blow up the sort — it sorts first."""
    assert sort_key({"id": "x", "transaction_date": None})[0] == date.min
    assert sort_key({"id": "x", "transaction_date": "not-a-date"})[0] == date.min


# ══════════════════════════════════════════════════════════════════════════════
# The opening-balance boundary — the double-count trap
# ══════════════════════════════════════════════════════════════════════════════

def test_a_row_before_the_opening_date_is_not_added_again():
    """opening_balance_paise is a balance AS AT opening_balance_date, so a
    transaction dated earlier is already inside it. Adding it would inflate
    every balance below by exactly that amount, silently."""
    lines = build_register([
        _t("old", "2026-03-15", credit=50000),
        _t("new", "2026-04-02", credit=10000),
    ], opening_balance_paise=100000, opening_balance_date="2026-04-01")
    old, new = lines
    assert old.precedes_opening is True
    assert old.balance_paise == 100000          # untouched by the stray row
    assert new.precedes_opening is False
    assert new.balance_paise == 110000          # NOT 160000


def test_a_row_exactly_on_the_opening_date_does_count():
    """The boundary is strictly 'before'. A transaction ON the opening date is
    after the stated balance, not inside it — off-by-one here is a real error."""
    lines = build_register([_t("a", "2026-04-01", credit=10000)],
                           opening_balance_paise=100000, opening_balance_date="2026-04-01")
    assert lines[0].precedes_opening is False
    assert lines[0].balance_paise == 110000


def test_pre_opening_rows_are_excluded_from_the_totals_too():
    lines = build_register([
        _t("old", "2026-03-15", credit=50000),
        _t("new", "2026-04-02", debit=10000),
    ], opening_balance_paise=100000, opening_balance_date="2026-04-01")
    s = summarise(lines, opening_balance_paise=100000)
    assert s["deposits_paise"] == 0             # the ₹500 credit is pre-opening
    assert s["withdrawals_paise"] == 10000
    assert s["precedes_opening_count"] == 1


def test_with_no_opening_date_every_row_counts():
    """An account with no stated opening date has no boundary to be before."""
    lines = build_register([_t("old", "2020-01-01", credit=50000)],
                           opening_balance_paise=100000, opening_balance_date=None)
    assert lines[0].precedes_opening is False
    assert lines[0].balance_paise == 150000


# ══════════════════════════════════════════════════════════════════════════════
# The cleared column
# ══════════════════════════════════════════════════════════════════════════════

def test_an_unreconciled_line_is_blank():
    assert derive_cleared({"reconciliation_id": None}, None) == CLEARED_NONE


def test_a_completed_reconciliation_marks_the_line_reconciled():
    assert derive_cleared({"reconciliation_id": "r1"}, "completed") == CLEARED_RECONCILED


@pytest.mark.parametrize("status", ["open", "in_progress"])
def test_an_unfinished_reconciliation_only_marks_it_cleared(status):
    """'R' means a human certified the period. Saying that while the session is
    still open would report a sign-off that has not happened."""
    assert derive_cleared({"reconciliation_id": "r1"}, status) == CLEARED_PENDING


def test_an_unresolvable_reconciliation_degrades_to_cleared_not_reconciled():
    """Claimed by a session we cannot see. Report the weaker of the two."""
    assert derive_cleared({"reconciliation_id": "gone"}, None) == CLEARED_PENDING


def test_the_cleared_counts_partition_the_register():
    lines = build_register([
        _t("a", "2026-04-01", credit=100),
        _t("b", "2026-04-02", credit=100, reconciliation_id="done"),
        _t("c", "2026-04-03", credit=100, reconciliation_id="live"),
    ], reconciliation_statuses={"done": "completed", "live": "in_progress"})
    s = summarise(lines)
    assert (s["uncleared_count"], s["pending_count"], s["reconciled_count"]) == (1, 1, 1)
    assert s["uncleared_count"] + s["pending_count"] + s["reconciled_count"] == s["line_count"]


# ══════════════════════════════════════════════════════════════════════════════
# Self-check against the bank's own stated balance
# ══════════════════════════════════════════════════════════════════════════════

def test_agreement_with_the_statement_reports_a_zero_delta():
    lines = build_register([
        _t("a", "2026-04-01", credit=10000, balance=110000),
        _t("b", "2026-04-02", debit=3000, balance=107000),
    ], opening_balance_paise=100000)
    assert [l.balance_delta_paise for l in lines] == [0, 0]
    assert first_divergence(lines) is None


def test_a_missing_transaction_shows_up_as_a_divergence():
    """The bank says the balance is ₹1,150 after the second line; we compute
    ₹1,100 because a ₹50 credit never got imported. That gap is the whole point
    of keeping the statement's balance column."""
    lines = build_register([
        _t("a", "2026-04-01", credit=10000, balance=110000),
        _t("b", "2026-04-02", credit=0, balance=115000),
    ], opening_balance_paise=100000)
    d = first_divergence(lines)
    assert d is not None
    assert d["transaction_id"] == "b"
    assert d["delta_paise"] == 5000
    assert d["computed_balance_paise"] == 110000
    assert d["statement_balance_paise"] == 115000


def test_only_the_first_divergence_is_reported():
    """Once a line is missing every balance below inherits the same offset.
    Reporting them all would state one fault many times and bury its origin."""
    lines = build_register([
        _t("a", "2026-04-01", credit=10000, balance=110000),
        _t("b", "2026-04-02", credit=0, balance=115000),
        _t("c", "2026-04-03", credit=1000, balance=116000),
    ], opening_balance_paise=100000)
    assert first_divergence(lines)["transaction_id"] == "b"
    assert [l.balance_delta_paise for l in lines] == [0, 5000, 5000]


def test_a_statement_with_no_balance_column_yields_no_delta_and_no_false_alarm():
    lines = build_register([
        _t("a", "2026-04-01", credit=10000),
        _t("b", "2026-04-02", debit=3000),
    ], opening_balance_paise=100000)
    assert [l.balance_delta_paise for l in lines] == [None, None]
    assert first_divergence(lines) is None


def test_a_pre_opening_row_never_raises_a_divergence():
    """Its computed balance is deliberately not advanced, so comparing it
    against the bank's would manufacture a discrepancy that is not real."""
    lines = build_register([_t("old", "2026-03-15", credit=50000, balance=99999)],
                           opening_balance_paise=100000, opening_balance_date="2026-04-01")
    assert lines[0].balance_delta_paise is None
    assert first_divergence(lines) is None


# ══════════════════════════════════════════════════════════════════════════════
# Shape
# ══════════════════════════════════════════════════════════════════════════════

def test_a_register_line_is_immutable():
    line = build_register([_t("a", "2026-04-01", credit=100)])[0]
    assert isinstance(line, RegisterLine)
    with pytest.raises(Exception):
        line.balance_paise = 0  # type: ignore[misc]


def test_amount_is_signed_by_direction():
    lines = build_register([
        _t("in", "2026-04-01", credit=100),
        _t("out", "2026-04-02", debit=250),
    ])
    assert lines[0].amount_paise == 100
    assert lines[1].amount_paise == -250
