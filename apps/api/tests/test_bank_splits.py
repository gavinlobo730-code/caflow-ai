"""
Splitting one bank line across several GL accounts (Tier 1.2) — the arithmetic.

The invariant under test is that splits sum EXACTLY to what the bank moved. A
journal that does not account for every paise either fails to balance or hides
the difference in whichever account happened to be last, so "close enough" is
not a state this code is allowed to reach.

Integer paise throughout.
"""
import pytest

from domain.banking.splits import (
    Split, SplitError, parse_splits, validate_splits, build_split_lines,
    unallocated_paise, MAX_SPLITS,
)


BANK, A1, A2, A3 = "bank", "rent", "maint", "parking"


def _s(account, amount, narration=None):
    return Split(account, amount, narration)


# ══════════════════════════════════════════════════════════════════════════════
# Validation — the sum invariant
# ══════════════════════════════════════════════════════════════════════════════

def test_splits_that_tie_exactly_are_accepted():
    """₹47,200 as ₹40,000 rent + ₹5,000 maintenance + ₹2,200 parking."""
    validate_splits([_s(A1, 4000000), _s(A2, 500000), _s(A3, 220000)], 4720000)


def test_a_shortfall_is_refused_and_named():
    with pytest.raises(SplitError) as ei:
        validate_splits([_s(A1, 4000000), _s(A2, 500000)], 4720000)
    # The CA needs the gap, not "constraint violated".
    # 4,720,000 − (4,000,000 + 500,000) = 220,000 paise = ₹2,200.00
    assert "₹2,200.00" in str(ei.value) and "unallocated" in str(ei.value)


def test_over_allocation_is_refused_and_named():
    with pytest.raises(SplitError) as ei:
        validate_splits([_s(A1, 4000000), _s(A2, 1000000)], 4720000)
    assert "too much" in str(ei.value)


def test_a_one_paise_gap_is_still_a_gap():
    """There is no tolerance. A rounding plug on a real bank movement is how
    money goes missing quietly."""
    with pytest.raises(SplitError):
        validate_splits([_s(A1, 4000000), _s(A2, 719999)], 4720000)


def test_a_single_split_is_refused():
    """One 'split' is an ordinary posting — routing it through this path would
    build a two-line entry by a longer road and imply something happened."""
    with pytest.raises(SplitError) as ei:
        validate_splits([_s(A1, 4720000)], 4720000)
    assert "at least two" in str(ei.value)


def test_no_splits_at_all_is_refused():
    with pytest.raises(SplitError):
        validate_splits([], 4720000)


def test_too_many_splits_is_refused():
    each = 100
    with pytest.raises(SplitError):
        validate_splits([_s(A1, each) for _ in range(MAX_SPLITS + 1)],
                        each * (MAX_SPLITS + 1))


def test_a_zero_amount_split_is_refused():
    with pytest.raises(SplitError):
        validate_splits([_s(A1, 4720000), _s(A2, 0)], 4720000)


def test_a_negative_split_is_refused_even_when_the_total_ties():
    """THE dangerous case. 5,720,000 + (-1,000,000) = 4,720,000, so a naive sum
    check passes — but it describes a ₹57,200 expense and a ₹10,000 movement the
    bank never made. Direction comes from the bank line, not the split."""
    with pytest.raises(SplitError) as ei:
        validate_splits([_s(A1, 5720000), _s(A2, -1000000)], 4720000)
    assert "positive" in str(ei.value)


def test_a_transaction_with_no_amount_cannot_be_split():
    with pytest.raises(SplitError):
        validate_splits([_s(A1, 100), _s(A2, 100)], 0)


def test_the_same_account_twice_is_allowed():
    """Two rent lines with different narrations is legitimate — a landlord
    invoice covering two periods, say. The journal simply carries two legs."""
    validate_splits([_s(A1, 100, "April"), _s(A1, 200, "May")], 300)


# ══════════════════════════════════════════════════════════════════════════════
# Parsing
# ══════════════════════════════════════════════════════════════════════════════

def test_parsing_accepts_the_request_shape():
    got = parse_splits([
        {"account_id": A1, "amount_paise": 100, "narration": " Rent "},
        {"account_id": A2, "amount_paise": 200},
    ])
    assert got == [Split(A1, 100, "Rent"), Split(A2, 200, None)]


def test_parsing_rejects_a_row_with_no_account():
    with pytest.raises(SplitError) as ei:
        parse_splits([{"account_id": "  ", "amount_paise": 100}])
    assert "Split 1" in str(ei.value)


@pytest.mark.parametrize("bad", [None, "", "abc", {}])
def test_parsing_rejects_an_unusable_amount(bad):
    with pytest.raises(SplitError):
        parse_splits([{"account_id": A1, "amount_paise": bad}])


def test_parsing_keeps_a_negative_so_validation_can_report_it():
    """parse_splits is a shape check; validate_splits is the money check.
    Silently dropping a negative here would hide it from the error the CA sees."""
    assert parse_splits([{"account_id": A1, "amount_paise": -5}])[0].amount_paise == -5


# ══════════════════════════════════════════════════════════════════════════════
# The journal lines
# ══════════════════════════════════════════════════════════════════════════════

def test_money_out_debits_each_split_and_credits_the_bank_once():
    lines = build_split_lines([_s(A1, 4000000), _s(A2, 720000)],
                              is_credit=False, bank_account_id=BANK, amount_paise=4720000)
    assert len(lines) == 3
    bank = [l for l in lines if l["account_id"] == BANK]
    assert len(bank) == 1                      # ONE bank leg, not one per split
    assert bank[0]["credit_paise"] == 4720000
    assert {l["account_id"]: l["debit_paise"] for l in lines if l["account_id"] != BANK} == {
        A1: 4000000, A2: 720000}


def test_money_in_debits_the_bank_once_and_credits_each_split():
    lines = build_split_lines([_s(A1, 4000000), _s(A2, 720000)],
                              is_credit=True, bank_account_id=BANK, amount_paise=4720000)
    bank = [l for l in lines if l["account_id"] == BANK]
    assert len(bank) == 1 and bank[0]["debit_paise"] == 4720000
    assert all(l["credit_paise"] > 0 for l in lines if l["account_id"] != BANK)


@pytest.mark.parametrize("is_credit", [False, True])
def test_the_lines_always_balance(is_credit):
    lines = build_split_lines([_s(A1, 1), _s(A2, 2), _s(A3, 99999997)],
                              is_credit=is_credit, bank_account_id=BANK,
                              amount_paise=100000000)
    assert (sum(l["debit_paise"] for l in lines)
            == sum(l["credit_paise"] for l in lines) == 100000000)


def test_there_is_exactly_one_bank_leg_however_many_splits():
    """One bank leg per split would balance just as well, and would litter the
    bank ledger with fragments of a single real movement — breaking the tie-out
    against the statement line the register depends on."""
    splits = [_s(f"acc{i}", 100) for i in range(10)]
    lines = build_split_lines(splits, is_credit=False, bank_account_id=BANK,
                              amount_paise=1000)
    assert sum(1 for l in lines if l["account_id"] == BANK) == 1
    assert len(lines) == 11


def test_a_split_narration_reaches_its_line():
    lines = build_split_lines([_s(A1, 100, "April rent"), _s(A2, 200, "Lift AMC")],
                              is_credit=False, bank_account_id=BANK, amount_paise=300)
    assert {l["narration"] for l in lines if l["account_id"] in (A1, A2)} == {
        "April rent", "Lift AMC"}


def test_a_split_with_no_narration_still_gets_a_readable_one():
    lines = build_split_lines([_s(A1, 100), _s(A2, 200)],
                              is_credit=False, bank_account_id=BANK, amount_paise=300)
    assert all(l["narration"] for l in lines)


def test_building_refuses_what_validation_refuses():
    with pytest.raises(SplitError):
        build_split_lines([_s(A1, 100), _s(A2, 100)], is_credit=False,
                          bank_account_id=BANK, amount_paise=999)


def test_building_needs_a_bank_account():
    with pytest.raises(SplitError):
        build_split_lines([_s(A1, 100), _s(A2, 200)], is_credit=False,
                          bank_account_id="", amount_paise=300)


@pytest.mark.parametrize("amount", [3, 7, 101, 4999, 4720000, 99999999])
def test_an_exact_split_of_any_amount_balances(amount):
    """Split every amount as evenly as integer paise allow, remainder on the
    first leg — the caller's job, but the builder must handle whatever ties."""
    half = amount // 2
    splits = [_s(A1, amount - half), _s(A2, half)]
    lines = build_split_lines(splits, is_credit=False, bank_account_id=BANK,
                              amount_paise=amount)
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines)


# ══════════════════════════════════════════════════════════════════════════════
# The live indicator
# ══════════════════════════════════════════════════════════════════════════════

def test_unallocated_counts_down_to_zero():
    assert unallocated_paise([], 4720000) == 4720000
    assert unallocated_paise([_s(A1, 4000000)], 4720000) == 720000
    assert unallocated_paise([_s(A1, 4000000), _s(A2, 720000)], 4720000) == 0


def test_unallocated_goes_negative_when_over_allocated():
    assert unallocated_paise([_s(A1, 5000000)], 4720000) == -280000
