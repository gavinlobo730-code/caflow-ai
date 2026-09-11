"""The mapped-IP check: who ESIC knows, against who is in our file (F1).

ESIC's filing manual makes the monthly upload all-or-nothing — "successful
transaction only when all the Employees' (who are currently mapped in the
system) details are entered perfectly". A file missing ONE insured person is
not partially imported; the whole thing is rejected, after the CA has assembled
it, uploaded it and waited.

These tests are mostly about the two directions being DIFFERENT PROBLEMS with
different remedies, and about reading whatever the portal's screen copies as.
"""
from __future__ import annotations

import pytest

from domain.payroll import esic_mapped_ips as m

A, B, C = "3113456789", "3113456790", "3113456791"


# ── reading what the portal's screen copies as ──────────────────────────────

def test_numbers_come_out_of_a_pasted_column():
    assert m.normalise(f"{A}\n{B}\n{C}") == [A, B, C]


def test_names_beside_the_numbers_are_ignored():
    """The portal's list copies with names attached depending on the selection.
    A CA who has to reformat before the product will read it goes back to doing
    the comparison by eye, which is the thing being replaced."""
    assert m.normalise(f"{A} ASHA KUMARI\n{B} BIMAL ROY") == [A, B]


def test_commas_tabs_and_blank_lines_are_all_fine():
    assert m.normalise(f"{A},\t{B}\n\n  {C}  ") == [A, B, C]


def test_a_repeated_number_is_counted_once():
    assert m.normalise(f"{A}\n{A}\n{B}") == [A, B]


def test_order_is_the_portals_own():
    """What is missing is read while looking at the portal's screen, so the
    order has to be the portal's or a CA has to hunt."""
    assert m.normalise(f"{C}\n{A}\n{B}") == [C, A, B]


def test_short_runs_of_digits_are_not_insurance_numbers():
    """A pasted header or a page number must not become a person."""
    assert m.normalise("Page 1 of 2\n2026\n" + A) == [A]


def test_nothing_pasted_reads_as_nothing():
    assert m.normalise("") == []
    assert m.normalise("   \n\t ") == []


# ── the two directions, and why they are not one number ─────────────────────

def test_somebody_mapped_and_missing_fails_the_whole_upload():
    r = m.reconcile(mapped_raw=f"{A}\n{B}", file_ip_numbers=[A])
    assert r.missing_from_file == [B]
    assert r.would_be_rejected is True
    assert "ALL OR NOTHING" in r.to_dict()["what_it_means"]


def test_the_sentence_says_the_whole_file_not_the_row():
    """The thing a CA gets wrong is assuming the bad row is skipped."""
    r = m.reconcile(mapped_raw=f"{A}\n{B}", file_ip_numbers=[A])
    assert "the whole file is rejected, not just that row" in r.to_dict()["what_it_means"]


def test_a_zero_wage_month_still_needs_a_row_and_the_sentence_says_so():
    """Somebody on unpaid leave is still mapped. The advice has to name that,
    because "they earned nothing" is exactly why a CA leaves them out."""
    r = m.reconcile(mapped_raw=f"{A}\n{B}", file_ip_numbers=[A])
    assert "no wages this month still needs a row" in r.to_dict()["what_it_means"]


def test_somebody_in_the_file_and_not_mapped_is_the_OTHER_problem():
    """Not a rejection — a number to check, or somebody to get mapped. One
    figure for both would send the CA to fix the wrong thing."""
    r = m.reconcile(mapped_raw=A, file_ip_numbers=[A, C])
    assert r.not_mapped_at_esic == [C]
    assert r.missing_from_file == []
    assert r.would_be_rejected is False
    assert "get them mapped at ESIC first" in r.to_dict()["what_it_means"]


def test_a_clean_month_says_what_was_checked_rather_than_just_ok():
    r = m.reconcile(mapped_raw=f"{A}\n{B}", file_ip_numbers=[B, A])
    assert r.missing_from_file == [] and r.not_mapped_at_esic == []
    assert "what the portal checks" in r.to_dict()["what_it_means"]


def test_both_directions_at_once_reports_the_rejection_first():
    """A rejection is the blocking fact; an unmapped number is a follow-up."""
    r = m.reconcile(mapped_raw=f"{A}\n{B}", file_ip_numbers=[A, C])
    assert r.missing_from_file == [B] and r.not_mapped_at_esic == [C]
    assert "ALL OR NOTHING" in r.to_dict()["what_it_means"]


def test_nothing_pasted_asks_for_the_portals_list_rather_than_passing():
    """An empty paste compared against a full file would otherwise report every
    member as unmapped, which reads as a catastrophe and is a blank box."""
    r = m.reconcile(mapped_raw="", file_ip_numbers=[A, B])
    assert r.would_be_rejected is False
    assert "No mapped insurance numbers were read" in r.to_dict()["what_it_means"]


def test_the_counts_are_of_distinct_people_on_each_side():
    r = m.reconcile(mapped_raw=f"{A}\n{A}\n{B}", file_ip_numbers=[A, A, C])
    assert (r.mapped_count, r.file_count) == (2, 2)


def test_whitespace_around_a_file_number_does_not_make_a_stranger():
    r = m.reconcile(mapped_raw=A, file_ip_numbers=[f"  {A} "])
    assert r.matched == [A] and r.not_mapped_at_esic == []


def test_it_serialises_to_json_safe_primitives():
    import json
    json.dumps(m.reconcile(mapped_raw=A, file_ip_numbers=[A]).to_dict())


def test_each_side_keeps_the_order_it_will_be_read_in():
    """A CA reads `missing_from_file` with the PORTAL's list on screen and
    `not_mapped_at_esic` with our own file on screen, so each keeps the order
    of the side it came from. Sorting either — which looks like tidying — makes
    them hunt down a list they are looking straight at."""
    portal_order = f"{C}\n{A}\n{B}"
    r = m.reconcile(mapped_raw=portal_order, file_ip_numbers=[])
    assert r.missing_from_file == [C, A, B]

    ours = [B, C, A]
    r = m.reconcile(mapped_raw="", file_ip_numbers=ours)
    assert r.not_mapped_at_esic == ours


def test_matched_is_in_the_portals_order_too():
    r = m.reconcile(mapped_raw=f"{C}\n{A}", file_ip_numbers=[A, C])
    assert r.matched == [C, A]


# ── nothing is kept ─────────────────────────────────────────────────────────

def test_the_module_stores_nothing_and_reaches_nothing():
    """The pasted list is the portal's data about the client's own staff. The
    answer is wanted now, not next month, so keeping a copy would make this
    product the second place it lives for no reason."""
    import pathlib
    src = pathlib.Path(m.__file__).read_text()
    for banned in ("import httpx", "requests", "supabase", "db.table",
                   "open(", "INSERT", "psycopg"):
        assert banned not in src, f"{banned} has no business here"
