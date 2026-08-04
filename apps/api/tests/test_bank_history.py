"""
Learning a coding from past decisions (Tier 1.4) — the tally and the key.

Two things here are easy to get wrong and expensive when they are:

  * the KEY. Match on the raw narration and every UPI line is unique (they carry
    a UTR), so nothing ever learns. Match too loosely and unrelated payees
    collapse into one bucket and the suggestion is worse than none.
  * the EVIDENCE. A bare confidence score is unauditable. The suggestion has to
    carry how often, out of how many, and what disagreed.
"""
import pytest

from domain.banking.history import (
    HistorySuggestion, CodingOption, learning_key, summarise, describe, same_payee,
    KEY_PAYEE_ID, KEY_COUNTERPARTY, MIN_KEY_LENGTH,
)


def _t(description=None, payee_id=None, payee_name=None, **kw):
    row = {"description": description, "payee_id": payee_id, "payee_name": payee_name}
    row.update(kw)
    return row


def _h(account_id=None, category=None, posted_at=None, transaction_date=None):
    return {"account_id": account_id, "category": category,
            "posted_at": posted_at, "transaction_date": transaction_date}


# ══════════════════════════════════════════════════════════════════════════════
# The learning key
# ══════════════════════════════════════════════════════════════════════════════

def test_a_linked_party_is_the_strongest_key():
    """A human linked this line to a vendor. That beats anything inferred."""
    assert learning_key(_t(description="UPI/412345/RAMESH", payee_id="v-1")) == (KEY_PAYEE_ID, "v-1")


def test_a_confirmed_payee_name_is_used_when_there_is_no_link():
    got = learning_key(_t(description="NEFT/998/SOMETHING ELSE", payee_name="Acme Pvt Ltd"))
    assert got == (KEY_COUNTERPARTY, "ACME")


def test_the_counterparty_is_parsed_out_of_the_narration_as_a_last_resort():
    got = learning_key(_t(description="UPI/412345678901/RAMESH KUMAR/HDFC"))
    assert got is not None and got[0] == KEY_COUNTERPARTY
    assert "RAMESH" in got[1]


def test_two_upi_lines_from_the_same_payee_share_a_key():
    """THE case that makes narration matching useless: the UTR differs every
    time, so a raw-string key would never learn anything."""
    a = _t(description="UPI/412345678901/RAMESH KUMAR/HDFC")
    b = _t(description="UPI/998877665544/RAMESH KUMAR/HDFC")
    assert learning_key(a) == learning_key(b)
    assert same_payee(a, b)


def test_entity_suffixes_do_not_split_one_payee_into_two():
    """'Acme Pvt. Ltd.' and 'ACME PRIVATE LIMITED' are one payee."""
    assert (learning_key(_t(payee_name="Acme Pvt. Ltd."))
            == learning_key(_t(payee_name="ACME PRIVATE LIMITED")))


def test_a_transaction_with_nothing_to_learn_from_has_no_key():
    assert learning_key(_t(description=None)) is None
    assert learning_key(_t(description="NEFT DR")) is None


def test_a_short_counterparty_is_not_distinctive_enough_to_learn_from():
    """'SBI' would collapse every State Bank line in the file into one payee."""
    assert learning_key(_t(payee_name="SBI")) is None
    assert learning_key(_t(payee_name="A" * MIN_KEY_LENGTH)) is not None


def test_different_payees_do_not_share_a_key():
    assert not same_payee(_t(payee_name="Acme Ltd"), _t(payee_name="Beta Ltd"))


def test_two_transactions_with_no_key_are_not_the_same_payee():
    """None == None must not read as 'same payee' — that would pool every
    unparseable line into one bucket and suggest nonsense for all of them."""
    assert not same_payee(_t(description="NEFT DR"), _t(description="RTGS CR"))


# ══════════════════════════════════════════════════════════════════════════════
# The tally
# ══════════════════════════════════════════════════════════════════════════════

KEY = (KEY_COUNTERPARTY, "ACME")


def test_a_unanimous_history_suggests_that_coding():
    s = summarise([_h("acc-rent", "Expense", "2026-04-01"),
                   _h("acc-rent", "Expense", "2026-05-01"),
                   _h("acc-rent", "Expense", "2026-06-01")], KEY)
    assert s.account_id == "acc-rent" and s.category == "Expense"
    assert s.times_seen == 3 and s.total_seen == 3
    assert s.is_unanimous is True and s.share_bps == 10000


def test_the_majority_wins_and_the_loser_is_still_reported():
    """A CA must see the disagreement, not a confident-looking single answer."""
    s = summarise([_h("acc-rent", "Expense", "2026-04-01"),
                   _h("acc-rent", "Expense", "2026-05-01"),
                   _h("acc-repairs", "Expense", "2026-06-01")], KEY)
    assert s.account_id == "acc-rent" and s.times_seen == 2 and s.total_seen == 3
    assert s.is_unanimous is False
    assert [a.account_id for a in s.alternatives] == ["acc-repairs"]


def test_share_is_integer_basis_points():
    s = summarise([_h("a", "Expense", "2026-01-01"), _h("a", "Expense", "2026-01-02"),
                   _h("b", "Expense", "2026-01-03")], KEY)
    assert s.share_bps == (2 * 10000) // 3 == 6666      # floored, never a float


def test_a_tie_breaks_on_recency():
    """Two codings used equally often is a real disagreement; the more recent
    decision is the better guess, and the other still appears as an alternative."""
    s = summarise([_h("old", "Expense", "2026-01-01"),
                   _h("new", "Expense", "2026-09-01")], KEY)
    assert s.account_id == "new"
    assert [a.account_id for a in s.alternatives] == ["old"]


def test_rows_with_no_coding_teach_nothing():
    """They record that a transaction existed, not what anyone decided."""
    s = summarise([_h(None, None, "2026-04-01"), _h("acc-rent", "Expense", "2026-05-01")], KEY)
    assert s.total_seen == 1 and s.account_id == "acc-rent"


def test_no_usable_history_yields_no_suggestion():
    assert summarise([], KEY) is None
    assert summarise([_h(None, None, "2026-01-01")], KEY) is None


def test_a_category_with_no_account_is_still_a_coding():
    """Customer Payment resolves its own control account, so it never carries
    an account_id — that is a real, learnable decision."""
    s = summarise([_h(None, "Customer Payment", "2026-04-01")], KEY)
    assert s is not None and s.category == "Customer Payment" and s.account_id is None


def test_the_account_and_category_pair_is_what_is_learned():
    """The same account under two categories is two different decisions."""
    s = summarise([_h("acc-1", "Expense", "2026-01-01"),
                   _h("acc-1", "Other", "2026-01-02"),
                   _h("acc-1", "Expense", "2026-01-03")], KEY)
    assert s.category == "Expense" and s.times_seen == 2 and s.total_seen == 3


def test_transaction_date_is_used_when_a_row_was_never_posted():
    s = summarise([_h("a", "Expense", None, "2026-01-01"),
                   _h("b", "Expense", None, "2026-09-01")], KEY)
    assert s.account_id == "b"          # recency still resolves the tie


def test_a_missing_date_does_not_crash_the_sort():
    s = summarise([_h("a", "Expense", None, None), _h("b", "Expense", "2026-09-01")], KEY)
    assert s is not None and s.total_seen == 2


def test_the_suggestion_is_immutable():
    s = summarise([_h("a", "Expense", "2026-01-01")], KEY)
    assert isinstance(s, HistorySuggestion)
    with pytest.raises(Exception):
        s.account_id = "b"  # type: ignore[misc]


def test_alternatives_are_coding_options():
    s = summarise([_h("a", "Expense", "2026-01-02"), _h("a", "Expense", "2026-01-03"),
                   _h("b", "Expense", "2026-01-01")], KEY)
    assert all(isinstance(a, CodingOption) for a in s.alternatives)
    assert s.alternatives[0].times == 1


# ══════════════════════════════════════════════════════════════════════════════
# What the CA is told
# ══════════════════════════════════════════════════════════════════════════════

def test_the_description_states_the_evidence_not_a_score():
    s = summarise([_h("a", "Expense", "2026-01-01"), _h("a", "Expense", "2026-01-02"),
                   _h("b", "Expense", "2026-01-03")], KEY)
    assert describe(s) == "Coded this way 2 of the last 3 times"


def test_a_single_prior_decision_says_so_plainly():
    """One observation must not read like a pattern."""
    assert describe(summarise([_h("a", "Expense", "2026-01-01")], KEY)) == \
        "Coded this way once before"


def test_a_unanimous_history_says_all():
    s = summarise([_h("a", "Expense", "2026-01-01"), _h("a", "Expense", "2026-01-02")], KEY)
    assert describe(s) == "Coded this way all 2 times before"


def test_no_suggestion_describes_as_nothing():
    assert describe(None) == ""
