"""POST-A-073 — a filed return uses a brought-forward loss, and the use is recorded per filing and per financial year.

WHAT WAS WRONG
    Nothing wrote `utilized_amount_paise` when a return was filed, so next year's computation reloaded the whole loss unless the CA edited it
    by hand. The obvious write-back (add the year's use to the running total) creates a second, quieter wrong number: the screen offers
    `remaining_amount_paise`, so recomputing the SAME year (a revised return, or a CA reopening the computation) would offer the loss net of
    its own earlier use and understate the relief.

WHAT THIS PINS (the pure rule, domain/income_tax/loss_utilisation.py)
    * what a computation may use is the loss less the uses of OTHER years, which is `remaining` plus this year's own use;
    * a filing's use is keyed by (filing, financial year) and a revised return REPLACES the original's use for that year;
    * other years are never touched, the baseline recorded by hand is left exactly as found, the use is capped at what was there, and the two
      stored totals are a cache of the entries, written together.
"""
import pytest

from domain.income_tax.loss_utilisation import (
    Superseded, after_filing, available_for_year_paise, baseline_paise, entries_of, used_in_year_paise,
)

L = 1_00_000_00   # one lakh, in paise


def row(original=10 * L, utilized=0, entries=None):
    """A stored row as the table holds it."""
    entries = entries or {}
    return {
        "original_amount_paise": original,
        "utilized_amount_paise": utilized,
        "remaining_amount_paise": original - utilized,
        "utilisations": entries,
    }


def store(r, columns):
    """The row after the columns the rule returned have been written."""
    return {**r, **columns}


# ── a row that predates the column behaves exactly as the screen has always offered it ──

def test_a_row_with_no_uses_offers_what_remains():
    r = row(original=10 * L, utilized=3 * L)
    assert available_for_year_paise(r, "2025-26") == 7 * L
    assert baseline_paise(r) == 3 * L, "a hand-recorded use is the baseline"
    # the column absent altogether (production before the migration), or not an object
    assert available_for_year_paise({"original_amount_paise": 5 * L, "remaining_amount_paise": 5 * L}, "2025-26") == 5 * L
    assert entries_of({"utilisations": "oops"}) == {} and entries_of({"utilisations": None}) == {}
    assert entries_of({"utilisations": {"f1": "oops", "f2": {"financial_year": "", "amount_paise": 5}}}) == {}


# ── filing a return uses the loss ──

def test_filing_a_return_records_the_use_and_moves_both_totals():
    r = row(original=10 * L)
    out = after_filing(r, "f-2025", "2025-26", 4 * L)
    assert out["utilisations"] == {"f-2025": {"financial_year": "2025-26", "amount_paise": 4 * L, "return_type": "original"}}
    assert out["utilized_amount_paise"] == 4 * L
    assert out["remaining_amount_paise"] == 6 * L


def test_the_next_year_sees_what_is_left_and_the_same_year_sees_its_own_use_again():
    filed = store(row(original=10 * L), after_filing(row(original=10 * L), "f-2025", "2025-26", 4 * L))
    assert available_for_year_paise(filed, "2026-27") == 6 * L, "next year: net of 2025-26's use"
    # THE HAZARD: recomputing 2025-26 itself must offer the loss as it stood before that year's use
    assert available_for_year_paise(filed, "2025-26") == 10 * L, "the same year: its own use is offered back"
    assert used_in_year_paise(filed, "2025-26") == 4 * L and used_in_year_paise(filed, "2026-27") == 0


def test_a_revised_return_replaces_the_originals_use_for_the_same_year_and_does_not_add_to_it():
    r = row(original=10 * L)
    r = store(r, after_filing(r, "f-original", "2025-26", 4 * L))
    # the revised return for the same year uses 6 lakh: the original's 4 lakh is replaced, not added to
    r = store(r, after_filing(r, "f-revised", "2025-26", 6 * L, "revised"))
    assert r["utilisations"] == {"f-revised": {"financial_year": "2025-26", "amount_paise": 6 * L, "return_type": "revised"}}
    assert r["utilized_amount_paise"] == 6 * L and r["remaining_amount_paise"] == 4 * L
    # and one that uses LESS (or nothing) gives the difference back; a revised return that used nothing KEEPS its (empty) entry, which is
    # what stops the original, acknowledged later, from writing over it
    r = store(r, after_filing(r, "f-revised-again", "2025-26", 0, "revised"))
    assert r["utilisations"] == {"f-revised-again": {"financial_year": "2025-26", "amount_paise": 0, "return_type": "revised"}}
    assert r["utilized_amount_paise"] == 0 and r["remaining_amount_paise"] == 10 * L


def test_other_years_are_never_touched_by_a_write():
    r = row(original=10 * L)
    r = store(r, after_filing(r, "f-2024", "2024-25", 2 * L))
    r = store(r, after_filing(r, "f-2025", "2025-26", 3 * L))
    assert set(r["utilisations"]) == {"f-2024", "f-2025"} and r["utilized_amount_paise"] == 5 * L
    r = store(r, after_filing(r, "f-2025-revised", "2025-26", 1 * L, "revised"))
    assert set(r["utilisations"]) == {"f-2024", "f-2025-revised"}, "only the same year's entry was replaced"
    assert r["utilisations"]["f-2024"]["amount_paise"] == 2 * L
    assert r["utilized_amount_paise"] == 3 * L and r["remaining_amount_paise"] == 7 * L


def test_writing_the_same_filing_twice_changes_nothing():
    r = row(original=10 * L)
    once = store(r, after_filing(r, "f-2025", "2025-26", 4 * L))
    twice = store(once, after_filing(once, "f-2025", "2025-26", 4 * L))
    assert twice == once, "recording an acknowledgement again must not use the loss again"


# ── the amount recorded by hand is the baseline, and a filing leaves it alone ──

def test_a_use_recorded_by_hand_is_kept_beside_a_filings():
    r = row(original=10 * L, utilized=3 * L)           # 3 lakh typed in through utilize_bf_loss
    out = after_filing(r, "f-2025", "2025-26", 2 * L)
    assert out["utilized_amount_paise"] == 5 * L and out["remaining_amount_paise"] == 5 * L
    r = store(r, out)
    assert baseline_paise(r) == 3 * L, "the baseline survives the write"
    # the same year recomputed offers back ONLY the filing's 2 lakh, never the hand-recorded 3
    assert available_for_year_paise(r, "2025-26") == 7 * L
    # and replacing the year's use keeps the baseline
    r = store(r, after_filing(r, "f-revised", "2025-26", 1 * L, "revised"))
    assert r["utilized_amount_paise"] == 4 * L and baseline_paise(r) == 3 * L


# ── a stored snapshot cannot take more than there was ──

def test_a_use_is_capped_at_what_was_there():
    r = row(original=10 * L)
    r = store(r, after_filing(r, "f-2024", "2024-25", 7 * L))
    out = after_filing(r, "f-2025", "2025-26", 9 * L)       # the snapshot claims 9 lakh; 3 are left
    assert out["utilisations"]["f-2025"]["amount_paise"] == 3 * L
    assert out["utilized_amount_paise"] == 10 * L and out["remaining_amount_paise"] == 0
    # with the hand-recorded baseline counted too
    r2 = row(original=10 * L, utilized=8 * L)
    assert after_filing(r2, "f", "2025-26", 5 * L)["utilized_amount_paise"] == 10 * L


def test_an_inconsistent_row_never_offers_more_than_the_original():
    bad = {"original_amount_paise": 5 * L, "remaining_amount_paise": 9 * L,
           "utilized_amount_paise": 0, "utilisations": {"f": {"financial_year": "2025-26", "amount_paise": 9 * L, "return_type": "original"}}}
    assert available_for_year_paise(bad, "2025-26") == 5 * L
    assert available_for_year_paise({"original_amount_paise": None, "remaining_amount_paise": None}, "2025-26") == 0


@pytest.mark.parametrize("used", [-5, 0, None, "x"])
def test_a_use_that_is_not_a_positive_amount_records_nothing(used):
    out = after_filing(row(original=10 * L), "f", "2025-26", used)
    assert out["utilisations"] == {} and out["utilized_amount_paise"] == 0 and out["remaining_amount_paise"] == 10 * L


# ── the order the returns are acknowledged in is not the order they stand in ──

def test_an_original_acknowledged_after_the_revised_return_does_not_write_over_it():
    r = row(original=10 * L)
    r = store(r, after_filing(r, "f-rev", "2025-26", 2 * L, "revised"))
    with pytest.raises(Superseded) as e:
        after_filing(r, "f-orig", "2025-26", 5 * L, "original")
    assert e.value.by == "f-rev"
    assert r["utilisations"] == {"f-rev": {"financial_year": "2025-26", "amount_paise": 2 * L, "return_type": "revised"}}


def test_a_revised_return_that_used_nothing_still_stands_over_a_later_original():
    r = row(original=10 * L)
    r = store(r, after_filing(r, "f-rev", "2025-26", 0, "revised"))
    with pytest.raises(Superseded):
        after_filing(r, "f-orig", "2025-26", 5 * L, "original")


def test_an_original_of_another_year_and_a_second_revised_return_are_not_superseded():
    r = row(original=10 * L)
    r = store(r, after_filing(r, "f-rev-25", "2025-26", 2 * L, "revised"))
    r = store(r, after_filing(r, "f-orig-26", "2026-27", 3 * L, "original"))          # another year: untouched by the 2025-26 revision
    r = store(r, after_filing(r, "f-rev-25b", "2025-26", 4 * L, "revised"))           # a later revision replaces the earlier one
    assert set(r["utilisations"]) == {"f-orig-26", "f-rev-25b"}


def test_an_entry_written_before_the_kind_was_recorded_reads_as_an_original():
    r = {"original_amount_paise": 10 * L, "utilized_amount_paise": 4 * L, "remaining_amount_paise": 6 * L,
         "utilisations": {"f": {"financial_year": "2025-26", "amount_paise": 4 * L}}}
    assert entries_of(r)["f"]["return_type"] == "original"
    after_filing(r, "g", "2025-26", L, "revised")          # a revised return may replace it
