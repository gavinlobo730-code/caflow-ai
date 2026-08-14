"""
Unit tests for domain/accounting/trial_balance.py.

Every financial calculation gets a test (CLAUDE.md). The property that matters
most is the last one: the delta ALWAYS balances, so importing a trial balance
can never put the ledger out of balance.
"""
import pytest

from domain.accounting.trial_balance import (
    TrialBalanceRow,
    TrialBalanceError,
    validate,
    net_by_account,
    plan_delta,
    assert_balanced,
)


def row(name, dr=0, cr=0, typ="Asset", code=None):
    return TrialBalanceRow(account_name=name, account_type=typ,
                           debit_paise=dr, credit_paise=cr, account_code=code)


BALANCED = [
    row("Cash", dr=150_00),
    row("Trade Receivables", dr=350_00),
    row("Trade Payables", cr=200_00, typ="Liability"),
    row("Capital", cr=300_00, typ="Equity"),
]


# ── validate ────────────────────────────────────────────────────────────────

def test_a_balanced_trial_balance_is_accepted_and_returns_its_totals():
    assert validate(BALANCED) == (500_00, 500_00)


def test_an_unbalanced_trial_balance_is_refused_and_the_gap_is_named():
    with pytest.raises(TrialBalanceError) as e:
        validate([row("Cash", dr=100_00), row("Capital", cr=99_00, typ="Equity")])
    msg = str(e.value)
    assert "does not balance" in msg
    assert "100" in msg           # the gap, in paise
    assert "debits exceed credits" in msg


def test_the_gap_is_reported_in_the_right_direction_when_credits_are_larger():
    with pytest.raises(TrialBalanceError, match="credits exceed debits"):
        validate([row("Cash", dr=99_00), row("Capital", cr=100_00, typ="Equity")])


def test_a_row_with_both_a_debit_and_a_credit_is_refused():
    with pytest.raises(TrialBalanceError, match="BOTH a debit"):
        validate([row("Cash", dr=100_00, cr=100_00)])


def test_a_negative_amount_is_refused_rather_than_flipped():
    with pytest.raises(TrialBalanceError, match="negative"):
        validate([row("Cash", dr=-100_00), row("Capital", cr=-100_00, typ="Equity")])


@pytest.mark.parametrize("bad", [100.0, "10000", None, 100.5])
def test_a_non_integer_amount_is_refused_because_money_is_never_a_float(bad):
    with pytest.raises(TrialBalanceError, match="integer number of paise"):
        validate([TrialBalanceRow("Cash", "Asset", bad, 0)])


def test_a_bool_is_not_accepted_as_one_paisa():
    """bool subclasses int, so a naive isinstance check lets True through as 1."""
    with pytest.raises(TrialBalanceError, match="integer number of paise"):
        validate([TrialBalanceRow("Cash", "Asset", True, 0)])


def test_duplicate_account_names_are_refused_case_insensitively():
    with pytest.raises(TrialBalanceError, match="duplicate account"):
        validate([row("Cash", dr=100_00), row("CASH", dr=0, cr=100_00)])


def test_a_blank_account_name_is_refused():
    with pytest.raises(TrialBalanceError, match="account name is blank"):
        validate([row("   ", dr=100_00), row("Capital", cr=100_00, typ="Equity")])


def test_an_empty_import_is_refused():
    with pytest.raises(TrialBalanceError, match="empty"):
        validate([])


def test_an_all_zero_trial_balance_is_refused_even_though_it_balances():
    """0 == 0 balances, but there is no opening position to bring forward, and
    posting it would create an empty journal for no reason."""
    with pytest.raises(TrialBalanceError, match="no opening position"):
        validate([row("Cash", dr=0), row("Capital", cr=0, typ="Equity")])


# ── net_by_account ──────────────────────────────────────────────────────────

def test_net_is_debit_positive():
    net = net_by_account(BALANCED)
    assert net["Cash"] == 150_00                 # asset: debit-positive
    assert net["Trade Payables"] == -200_00      # liability: credit-normal
    assert sum(net.values()) == 0                # a balanced TB nets to zero


def test_net_trims_surrounding_whitespace_so_keys_match_the_resolver():
    assert net_by_account([row("  Cash  ", dr=100_00)]) == {"Cash": 100_00}


# ── plan_delta ──────────────────────────────────────────────────────────────

def test_first_import_posts_the_whole_position():
    lines = plan_delta({"a": 100_00, "b": -100_00}, {})
    assert lines == [
        {"account_id": "a", "debit_paise": 100_00, "credit_paise": 0,
         "narration": "Trial balance imported"},
        {"account_id": "b", "debit_paise": 0, "credit_paise": 100_00,
         "narration": "Trial balance imported"},
    ]


def test_reimporting_the_same_trial_balance_posts_nothing():
    """The idempotency property: same file twice must not double the ledger."""
    target = {"a": 100_00, "b": -100_00}
    assert plan_delta(target, dict(target)) == []


def test_a_correction_posts_only_the_difference():
    lines = plan_delta({"a": 150_00, "b": -150_00}, {"a": 100_00, "b": -100_00})
    amounts = {l["account_id"]: (l["debit_paise"], l["credit_paise"]) for l in lines}
    assert amounts == {"a": (50_00, 0), "b": (0, 50_00)}


def test_an_account_dropped_from_the_reimport_is_backed_out_not_stranded():
    """Absent from target means its balance should become zero — the ledger must
    be told, or the account keeps a balance nobody intends."""
    lines = plan_delta({"b": 0}, {"a": 100_00, "b": -100_00})
    amounts = {l["account_id"]: (l["debit_paise"], l["credit_paise"]) for l in lines}
    assert amounts == {"a": (0, 100_00), "b": (100_00, 0)}


def test_line_order_is_deterministic_so_two_runs_are_diffable():
    t, c = {"z": 100_00, "a": -100_00}, {}
    assert [l["account_id"] for l in plan_delta(t, c)] == ["a", "z"]


# ── the property that matters ───────────────────────────────────────────────

@pytest.mark.parametrize("current", [
    {},                                        # nothing posted yet
    {"a": 100_00, "b": -100_00},               # already fully posted
    {"a": 30_00, "b": -30_00},                 # partially posted
    {"a": 999_00, "b": -999_00},               # overshot, delta goes negative
    {"c": 5_00, "d": -5_00},                   # disjoint accounts
])
def test_the_delta_always_balances(current):
    """Σtarget is 0 (validated TB) and Σcurrent is 0 (every posted journal
    balances), so the delta is zero-sum for ANY prior ledger state. This is what
    makes a trial-balance import incapable of unbalancing the books."""
    target = {"a": 250_00, "b": -250_00}
    lines = plan_delta(target, current)
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines)
    assert_balanced(lines)   # must not raise


def test_the_end_to_end_arithmetic_holds_for_the_sample_trial_balance():
    validate(BALANCED)
    target = net_by_account(BALANCED)
    lines = plan_delta(target, {})
    assert sum(l["debit_paise"] for l in lines) == 500_00
    assert sum(l["credit_paise"] for l in lines) == 500_00
    assert_balanced(lines)


def test_assert_balanced_rejects_a_hand_built_unbalanced_entry():
    with pytest.raises(TrialBalanceError, match="out of balance by 100"):
        assert_balanced([{"account_id": "a", "debit_paise": 200, "credit_paise": 0},
                         {"account_id": "b", "debit_paise": 0, "credit_paise": 100}])
