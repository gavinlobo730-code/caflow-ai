"""One 26AS row is one deduction, and the register is not pasted in (TDS-21).

WHAT WAS WRONG

    `routers/tds_workspace.py::upload_form26as` folded the portal side into a
    dict comprehension:

        form26as_keys = {(e.get("pan",""), e.get("section","")): e
                         for e in form26as_entries}

    and compared every book row against it. Three consequences, all silent:

      * A quarter with TWO deductions for one vendor under one section keeps
        only the LAST 26AS row. The earlier book row is then reported as an
        amount mismatch against a row that is not its counterpart — a figure a
        CA would chase to a vendor who owes nothing.
      * Nothing is consumed, so one 26AS row "matches" any number of book rows.
        Two identical bills against one portal row came back as two matches.
      * There was NO 26AS-side leftover at all. A row the portal shows and the
        register does not carry was never reported in any bucket, and that is
        the direction where the CLIENT'S OWN register is short.

    And the larger half, which the finding did not name: the endpoint asked the
    CALLER for BOTH SIDES. `raw_data.tds_entries` AND `raw_data.book_deductions`,
    with the 26AS Recon tab a textarea saying so — while the platform holds the
    register in `tds_deductions`. Asking a screen to supply the register it is
    reconciling is asking it to supply the answer, which is exactly the defect
    the GSTR-2B reconciliation shed (CLAUDE.md). The endpoint's own docstring
    admitted it: "NOTHING is read from the database ... it does not reconcile
    against tds_deductions, and it never has."

WHY NOT REUSE form26as_matcher

    That matcher is the client-as-DEDUCTEE direction and its identity fields
    are `deductor_tan` / `deductor_name`. This is client-as-DEDUCTOR, keyed on
    the DEDUCTEE's PAN and section, so reusing it would put a deductee PAN in a
    field named for a deductor's TAN and emit outcome sentences about the wrong
    party. `domain/tds/deductor_26as.py` takes the discipline — exact-amount
    pass before variance, every pass consuming, totals over the full population
    — and not the vocabulary.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from domain.tds import deductor_26as as D26

FY = "2025-26"


def _e(eid, pan, section, paise):
    return D26.PortalEntry(entry_id=eid, deductee_pan=pan, section=section,
                           tds_paise=paise)


def _b(did, pan, section, paise):
    return D26.BookDeduction(deduction_id=did, deductee_pan=pan,
                             section=section, tds_paise=paise)


# ── the three the dict comprehension could not express ──────────────────────

def test_two_deductions_for_one_vendor_and_section_both_match():
    """The dict kept the LAST 26AS row for an identity, so the first book row
    was reported as a mismatch against the second row's amount."""
    out = D26.reconcile(
        [_e("e1", "ABCDE1234F", "194J", 10_000), _e("e2", "ABCDE1234F", "194J", 25_000)],
        [_b("d1", "ABCDE1234F", "194J", 10_000), _b("d2", "ABCDE1234F", "194J", 25_000)],
    )
    assert out.matched_count == 2
    assert out.mismatch_count == 0
    assert out.missing_in_books_count == 0 and out.missing_in_26as_count == 0


def test_one_portal_row_cannot_match_two_book_rows():
    """No consumption meant one 26AS row satisfied every book row with its
    identity. The second is a real 'not on the portal', not a second match."""
    out = D26.reconcile(
        [_e("e1", "ABCDE1234F", "194J", 10_000)],
        [_b("d1", "ABCDE1234F", "194J", 10_000), _b("d2", "ABCDE1234F", "194J", 10_000)],
    )
    assert out.matched_count == 1
    assert out.missing_in_26as_count == 1


def test_a_portal_row_the_register_does_not_carry_is_reported():
    """There was no such bucket. The portal shows tax deducted under this
    client's TAN that the register has no row for — the client's own register
    is short, and nothing said so."""
    out = D26.reconcile(
        [_e("e1", "ABCDE1234F", "194J", 10_000)], [])
    assert out.missing_in_books_count == 1
    o = out.entry_outcomes[0]
    assert o.status == D26.STATUS_MISSING_IN_BOOKS
    assert "register does not carry it" in o.reason


def test_a_register_row_the_portal_does_not_show_is_reported():
    out = D26.reconcile([], [_b("d1", "ABCDE1234F", "194J", 10_000)])
    assert out.missing_in_26as_count == 1
    assert "cannot claim the credit" in out.deduction_outcomes[0].reason


# ── exact before variance, and the pairing ──────────────────────────────────

def test_an_exact_match_is_not_stolen_by_a_variance():
    """Both passes see the same identity. If variance ran first, e2 could take
    d1 and leave the exact pair reported as two differences."""
    out = D26.reconcile(
        [_e("e1", "ABCDE1234F", "194C", 10_000), _e("e2", "ABCDE1234F", "194C", 9_500)],
        [_b("d1", "ABCDE1234F", "194C", 10_000)],
    )
    by_id = {o.entry_id: o for o in out.entry_outcomes}
    # WHICH row matched, not just how many. Running variance first also leaves
    # one match and one leftover — it just labels the wrong pair a match, at a
    # 500-paise difference the CA would never see.
    assert by_id["e1"].status == D26.STATUS_MATCHED
    assert by_id["e1"].matched_deduction_id == "d1"
    assert by_id["e1"].diff_paise == 0
    assert by_id["e2"].status == D26.STATUS_MISSING_IN_BOOKS
    assert out.mismatch_count == 0


def test_a_variance_pairs_with_the_closest_amount():
    """Two variances against one identity must not cross over and report two
    larger differences than they are."""
    out = D26.reconcile(
        [_e("e1", "ABCDE1234F", "194C", 10_000), _e("e2", "ABCDE1234F", "194C", 50_000)],
        [_b("d1", "ABCDE1234F", "194C", 9_900), _b("d2", "ABCDE1234F", "194C", 49_000)],
    )
    assert out.mismatch_count == 2
    diffs = sorted(abs(o.diff_paise) for o in out.entry_outcomes)
    assert diffs == [100, 1_000]


def test_the_answer_does_not_depend_on_paste_order():
    a = D26.reconcile(
        [_e("e1", "ABCDE1234F", "194C", 10_000), _e("e2", "ABCDE1234F", "194C", 20_000)],
        [_b("d1", "ABCDE1234F", "194C", 20_000), _b("d2", "ABCDE1234F", "194C", 10_000)])
    b = D26.reconcile(
        [_e("e2", "ABCDE1234F", "194C", 20_000), _e("e1", "ABCDE1234F", "194C", 10_000)],
        [_b("d2", "ABCDE1234F", "194C", 10_000), _b("d1", "ABCDE1234F", "194C", 20_000)])
    assert a.entry_outcomes == b.entry_outcomes
    assert a.deduction_outcomes == b.deduction_outcomes


def test_the_section_is_part_of_the_identity():
    """Two sections for one vendor are two obligations, not one."""
    out = D26.reconcile(
        [_e("e1", "ABCDE1234F", "194C", 10_000)],
        [_b("d1", "ABCDE1234F", "194J", 10_000)])
    assert out.matched_count == 0
    assert out.missing_in_books_count == 1 and out.missing_in_26as_count == 1


@pytest.mark.parametrize("typed", [" abcde1234f ", "AbCdE1234F", "ABCDE1234F"])
def test_case_and_whitespace_do_not_make_a_different_vendor(typed):
    out = D26.reconcile([_e("e1", typed, " 194c ", 10_000)],
                        [_b("d1", "ABCDE1234F", "194C", 10_000)])
    assert out.matched_count == 1


# ── a missing PAN is named, never guessed ───────────────────────────────────

@pytest.mark.parametrize("blank", [None, "", "   ", "PANNOTAVBL", "pannotavbl"])
def test_a_deduction_with_no_pan_is_its_own_bucket(blank):
    """26AS is keyed on the deductee's PAN. Matching two blank-PAN rows on
    section and amount would be a guess about WHICH VENDOR — the guess s.206AA
    exists because nobody should make."""
    out = D26.reconcile([_e("e1", "ABCDE1234F", "194C", 10_000)],
                        [_b("d1", blank, "194C", 10_000)])
    assert out.no_pan_count == 1
    assert out.matched_count == 0
    assert out.missing_in_books_count == 1
    assert "s.206AA" in out.deduction_outcomes[0].reason


def test_a_no_pan_row_still_counts_in_the_books_total():
    """It is real tax the client withheld. Dropping it from the total would
    make the variance agree with itself."""
    out = D26.reconcile([], [_b("d1", None, "194C", 10_000)])
    assert out.total_books_paise == 10_000
    assert out.net_variance_paise == -10_000


# ── totals are over the full population ─────────────────────────────────────

def test_totals_count_everything_not_just_the_matched_subset():
    out = D26.reconcile(
        [_e("e1", "ABCDE1234F", "194C", 10_000), _e("e2", "ZZZZZ9999Z", "194J", 7_000)],
        [_b("d1", "ABCDE1234F", "194C", 10_000), _b("d2", "QQQQQ1111Q", "194I", 3_000)],
    )
    assert out.total_26as_paise == 17_000
    assert out.total_books_paise == 13_000
    assert out.net_variance_paise == 4_000


# ── the endpoint reads the register ─────────────────────────────────────────

def test_the_endpoint_no_longer_asks_the_caller_for_the_book_side():
    import inspect
    from routers import tds_workspace as m
    src = inspect.getsource(m.upload_form26as)
    assert "_register_rows_for_fy(" in src, (
        "the register is pasted in again — the screen is being asked to supply "
        "the answer it is checking")
    assert 'raw.get("book_deductions")' not in src
    # An older caller still sending it must be TOLD it was ignored.
    assert '"book_deductions" in raw' in src
    assert "ignored_request_keys" in src


def test_the_endpoint_uses_the_deductor_matcher_not_a_dict():
    import inspect
    from routers import tds_workspace as m
    src = inspect.getsource(m.upload_form26as)
    assert "D26.reconcile(" in src
    assert "form26as_keys" not in src, "the dict comprehension is back"


def test_the_register_read_is_firm_and_client_scoped():
    """The service-role key bypasses RLS, so the app-layer filter is the
    isolation control (CLAUDE.md)."""
    import inspect
    from routers import tds_workspace as m
    src = inspect.getsource(m._paginate_deductions)
    assert '.eq("firm_id", firm_id)' in src and '.eq("client_id", client_id)' in src
    assert ".range(" in src, (
        "PostgREST caps a response; a truncated register is the same false "
        "clean result as a filtered one")


def test_a_row_with_no_financial_year_is_placed_by_its_date():
    """migration 263 backfilled `financial_year`, but a row written since by
    something that did not set it would vanish from a filter on that column —
    and a reconciliation that silently drops half the register reports a clean
    result on a short one."""
    import inspect
    from routers import tds_workspace as m
    src = inspect.getsource(m._register_rows_for_fy)
    assert "transaction_date" in src and "fy_bounds" in src


# ── and the screen stopped asking ───────────────────────────────────────────

_TAB = (Path(__file__).resolve().parents[2] / "web" / "app" / "clients" / "[id]"
        / "compliance" / "tds" / "page.tsx")


@pytest.mark.skipif(not _TAB.is_file(), reason="needs apps/web")
def test_the_tab_no_longer_asks_for_the_register():
    src = _TAB.read_text()
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
    assert "book_deductions" not in code, (
        "the textarea asks the CA to paste the register again")
    assert "missing_in_books" in code, (
        "the direction where the client's own register is short is not shown")


@pytest.mark.skipif(not _TAB.is_file(), reason="needs apps/web")
def test_the_tabs_year_picker_comes_from_the_clock():
    """It was a free-text box the CA typed a year into. CLAUDE.md: a year
    picker is derived from the clock, never listed — and never typed."""
    src = _TAB.read_text()
    assert "financialYearChoicesAround" in src
    assert 'placeholder="Financial Year (e.g. 2025-26)"' not in src
