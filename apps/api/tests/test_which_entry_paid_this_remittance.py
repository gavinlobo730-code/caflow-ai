"""Matching a statutory remittance to the entry that paid it (Track F, F4).

The link on migration 365 exists because, on the ledger, a liability NOBODY HAS
PAID and one that was PAID AND NEVER TIED BACK look identical — both sit
uncleared on ESI Payable at year end. This is the shortlist that lets a CA tell
them apart.

The rule these tests are mostly about: THE FIGURE TO MATCH ON IS WHAT LEFT THE
BANK, not what the entry took off the liability. A late challan carries interest
under ESI Act s.39(5), which is an expense and not a reduction of the payable,
so the entry debits less to ESI Payable than the challan was for. Matching on
the liability debit would miss exactly the remittances a reconciliation is for.
"""
from __future__ import annotations

import pytest

from domain.payroll import remittance_match as rm


def _entry(eid, on, total, liability=None, **over):
    row = {"journal_entry_id": eid, "entry_date": on,
           "entry_total_paise": total,
           "liability_debit_paise": total if liability is None else liability}
    row.update(over)
    return row


PAID_ON = "2026-10-15"
CHALLAN = 10_500_00


def _c(entries, amount=CHALLAN, paid_on=PAID_ON, **kw):
    return rm.candidates(amount_paise=amount, paid_on=paid_on,
                         entries=entries, **kw)


# ── what makes a candidate exact ────────────────────────────────────────────

def test_an_entry_for_the_challan_amount_on_the_day_is_exact():
    [c] = _c([_entry("JE1", PAID_ON, CHALLAN)])
    assert c.grade == rm.EXACT
    assert c.days_apart == 0
    assert "left the bank" in c.reason


def test_a_late_challan_still_matches_although_the_liability_debit_is_smaller():
    """THE ONE THAT MATTERS.

        Dr  ESI Payable                 10,000
        Dr  Interest on Statutory Dues     500
          Cr  Bank                              10,500

    The challan is 10,500 and the payable moved by 10,000. Matching on the
    liability debit would call this NOT a match — on every remittance that
    carried interest, which is the whole population a reconciliation exists to
    find.
    """
    [c] = _c([_entry("JE1", PAID_ON, CHALLAN, liability=10_000_00)])
    assert c.grade == rm.EXACT
    assert c.liability_debit_paise == 10_000_00
    assert "interest or damages" in c.reason


def test_the_interest_case_is_named_rather_than_left_as_two_numbers():
    [c] = _c([_entry("JE1", PAID_ON, CHALLAN, liability=10_000_00)])
    assert "₹10,000.00 of it cleared the liability" in c.reason


def test_an_entry_debiting_more_than_left_the_bank_says_so():
    """Part of the liability settled another way — a contra, a set-off. Rare,
    and reported rather than silently graded."""
    [c] = _c([_entry("JE1", PAID_ON, CHALLAN, liability=12_000_00)])
    assert "more than left the bank" in c.reason


def test_a_different_amount_is_near_and_the_difference_is_stated():
    [c] = _c([_entry("JE1", PAID_ON, 9_000_00)])
    assert c.grade == rm.NEAR
    assert "₹1,500.00 less than the challan" in c.reason


def test_an_amount_over_the_challan_says_more_not_less():
    [c] = _c([_entry("JE1", PAID_ON, 11_000_00)])
    assert "₹500.00 more than the challan" in c.reason


# ── the window ──────────────────────────────────────────────────────────────

def test_an_entry_outside_the_window_is_not_offered():
    """Wider would start offering the NEXT month's remittance for this one —
    ESI and PT are monthly, so consecutive payments are about thirty days
    apart."""
    assert _c([_entry("JE1", "2026-11-20", CHALLAN)]) == []


def test_the_window_reaches_both_ways():
    got = _c([_entry("BEFORE", "2026-10-08", CHALLAN),
              _entry("AFTER", "2026-10-22", CHALLAN)])
    assert {c.journal_entry_id for c in got} == {"BEFORE", "AFTER"}
    assert all(c.days_apart == 7 for c in got)


def test_the_window_is_inclusive_at_its_edge_and_not_past_it():
    assert len(_c([_entry("JE1", "2026-10-22", CHALLAN)], window_days=7)) == 1
    assert _c([_entry("JE1", "2026-10-23", CHALLAN)], window_days=7) == []


def test_a_day_is_singular_in_the_sentence():
    [c] = _c([_entry("JE1", "2026-10-16", CHALLAN)])
    assert "dated 1 day away" in c.reason
    [c2] = _c([_entry("JE2", "2026-10-17", CHALLAN)])
    assert "dated 2 days away" in c2.reason


# ── a remittance with no payment date ───────────────────────────────────────

def test_a_remittance_with_no_paid_on_gets_nothing_rather_than_everything():
    """Without a date there is no window, and offering every entry that ever
    touched ESI Payable is not a shortlist — it is the ledger, re-presented as
    a suggestion."""
    assert _c([_entry("JE1", PAID_ON, CHALLAN)], paid_on=None) == []
    assert _c([_entry("JE1", PAID_ON, CHALLAN)], paid_on="") == []


def test_an_unparseable_entry_date_is_skipped_not_guessed():
    assert _c([_entry("JE1", "not-a-date", CHALLAN)]) == []


# ── the order ───────────────────────────────────────────────────────────────

def test_exact_beats_near_however_close_the_near_one_is():
    got = _c([_entry("NEAR", PAID_ON, 9_000_00),
              _entry("EXACT", "2026-10-20", CHALLAN)])
    assert [c.journal_entry_id for c in got] == ["EXACT", "NEAR"]


def test_among_exacts_the_nearest_date_wins():
    got = _c([_entry("FAR", "2026-10-20", CHALLAN),
              _entry("CLOSE", "2026-10-16", CHALLAN)])
    assert [c.journal_entry_id for c in got] == ["CLOSE", "FAR"]


def test_among_equally_dated_nears_the_nearest_amount_wins():
    got = _c([_entry("FAR", PAID_ON, 5_000_00),
              _entry("CLOSE", PAID_ON, 10_000_00)])
    assert [c.journal_entry_id for c in got] == ["CLOSE", "FAR"]


def test_the_order_is_stable_when_everything_else_ties():
    """A list that reshuffles between two loads of one screen is a list a CA
    stops trusting."""
    entries = [_entry("B", PAID_ON, CHALLAN), _entry("A", PAID_ON, CHALLAN)]
    assert [c.journal_entry_id for c in _c(entries)] == ["A", "B"]
    assert [c.journal_entry_id for c in _c(list(reversed(entries)))] == ["A", "B"]


def test_two_identical_challans_in_one_week_are_both_offered():
    """The machine cannot say which is which, and does not pretend to. Grading
    is never a confidence score — see docs/architecture/09."""
    got = _c([_entry("JE1", PAID_ON, CHALLAN), _entry("JE2", "2026-10-16", CHALLAN)])
    assert len(got) == 2
    assert all(c.grade == rm.EXACT for c in got)


# ── the shape the screen renders ────────────────────────────────────────────

def test_a_candidate_serialises_to_json_safe_primitives():
    import json
    [c] = _c([_entry("JE1", PAID_ON, CHALLAN, reference_no="PAY/2026/0007",
                     narration="ESI October")])
    d = c.to_dict()
    json.dumps(d)
    assert d["reference_no"] == "PAY/2026/0007"
    assert d["narration"] == "ESI October"


def test_no_candidate_carries_a_score_or_a_percentage():
    """`grade` is a word with a reason beside it. A percentage invites a CA to
    treat 92% as settled, and the product has exactly one place where it acts
    unprompted — a trusted bank rule — which this is not."""
    [c] = _c([_entry("JE1", PAID_ON, CHALLAN)])
    assert c.grade in (rm.EXACT, rm.NEAR)
    for value in c.to_dict().values():
        assert not isinstance(value, float), "no candidate carries a float score"
    assert "%" not in c.reason


@pytest.mark.parametrize("paise,text", [
    (0, "₹0.00"),
    (1, "₹0.01"),
    (100, "₹1.00"),
    (10_500_00, "₹10,500.00"),
    # INDIAN grouping, not Western. Python's own f"{n:,}" gives "₹125,000.00"
    # here, which no Indian document uses — and the browser renders the same
    # figure correctly with Intl.NumberFormat("en-IN") two lines away on the
    # same screen. The first draft of this module had exactly that bug.
    (1_25_000_00, "₹1,25,000.00"),
    (1_23_45_678_00, "₹1,23,45,678.00"),
    (-10_500_00, "-₹10,500.00"),
])
def test_amounts_in_the_sentence_are_indian_grouped_rupees_and_paise(paise, text):
    """Display only — every amount on the wire stays integer paise.

    The paise are KEPT, unlike amount_words.indian_rupees which truncates to
    whole rupees: that states a figure in a sentence about a return, this
    compares a challan against a bank debit, and a few paise of difference is
    the whole reason the two would not match.
    """
    assert rm._rupees(paise) == text
