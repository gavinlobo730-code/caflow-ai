"""
Salary arrears and §89(1) relief — IT Act §89, Rule 21A(2), Rule 21AA/Form 10E.
"""
import dataclasses

import pytest

from domain.payroll import arrears as A
from domain.income_tax.statutory_rates import RATES_BY_FY, SlabBracket


def _slice(fy, amount, income):
    return A.ArrearSlice(fy=fy, amount_paise=amount, total_income_that_year_paise=income)


# ── Rule 21A(2): the comparison ──────────────────────────────────────────────

def test_relief_is_a_minus_b():
    """A = extra tax caused by the arrears in the year of receipt.
    B = extra tax those arrears would have caused in the years they relate to.
    Relief is A - B."""
    r = A.compute_relief(
        receipt_fy="2026-27",
        total_income_receipt_year_paise=30_00_000 * 100,
        arrears=[_slice("2025-26", 5_00_000 * 100, 8_00_000 * 100)],
        form_10e_acknowledgement="10E-1")
    assert r.available
    assert r.relief_paise == max(0, r.difference_a_paise - r.difference_b_paise)
    assert r.difference_a_paise > 0


def test_no_relief_where_spreading_it_back_would_have_cost_more():
    """Rule 21A(2) gives relief only where A EXCEEDS B. An employee whose
    earlier years were richer than the year of receipt gets nothing, and that is
    the correct answer rather than a negative relief."""
    r = A.compute_relief(
        receipt_fy="2026-27",
        total_income_receipt_year_paise=20_00_000 * 100,
        arrears=[_slice("2025-26", 5_00_000 * 100, 11_00_000 * 100)],
        form_10e_acknowledgement="10E-1")
    assert r.difference_b_paise > r.difference_a_paise
    assert r.relief_paise == 0


def test_the_earlier_years_are_not_reopened():
    """§89 relieves the CURRENT year's liability. Nothing about an earlier year
    changes — no return is revised and no earlier tax is refunded. The module
    reports each year's additional tax as a component of B, never as an amount
    to collect."""
    r = A.compute_relief(
        receipt_fy="2026-27",
        total_income_receipt_year_paise=30_00_000 * 100,
        arrears=[_slice("2025-26", 5_00_000 * 100, 8_00_000 * 100)],
        form_10e_acknowledgement="10E-1")
    assert r.per_year[0]["fy"] == "2025-26"
    assert r.per_year[0]["additional_tax_paise"] == (
        r.per_year[0]["tax_after_paise"] - r.per_year[0]["tax_before_paise"])


def test_no_arrears_is_not_relief():
    r = A.compute_relief(receipt_fy="2026-27",
                         total_income_receipt_year_paise=20_00_000 * 100,
                         arrears=[], form_10e_acknowledgement="10E-1")
    assert not r.available
    assert r.relief_paise == 0


# ── The silent-fallback trap ─────────────────────────────────────────────────

def test_a_year_the_registry_does_not_hold_is_refused_not_substituted():
    """THE failure this module has to avoid.

    rates_for() returns the latest verified year's figures for a year it does
    not hold — the documented convention (CLAUDE.md). §89 compares years at
    THEIR OWN rates, so a substitute makes the whole computation a fiction that
    looks perfectly reasonable. Found in development: a ₹12,00,000 earlier year
    came back with nil tax, because FY 2025-26's §87A rebate reaches
    ₹12,00,000 and FY 2023-24's did not.
    """
    assert "2023-24" not in RATES_BY_FY, (
        "this test's premise is that 2023-24 is absent; if it has been added, "
        "pick another absent year rather than deleting the test")
    r = A.compute_relief(
        receipt_fy="2026-27",
        total_income_receipt_year_paise=30_00_000 * 100,
        arrears=[_slice("2023-24", 3_00_000 * 100, 9_00_000 * 100)],
        form_10e_acknowledgement="10E-1")
    assert not r.available
    assert r.relief_paise == 0
    assert any("no entry for that year" in g for g in r.gaps)


def test_a_missing_receipt_year_is_refused_too():
    r = A.compute_relief(
        receipt_fy="2023-24",
        total_income_receipt_year_paise=30_00_000 * 100,
        arrears=[_slice("2025-26", 3_00_000 * 100, 9_00_000 * 100)],
        form_10e_acknowledgement="10E-1")
    assert not r.available
    assert "year of receipt" in r.blocked_reason


def test_rates_exist_for_reads_the_registry_not_the_fallback():
    assert A.rates_exist_for("2025-26")
    assert not A.rates_exist_for("1999-00")


# ── An earlier year's income is the employee's, not payroll's ────────────────

def test_a_missing_earlier_year_income_blocks_rather_than_guesses():
    r = A.compute_relief(
        receipt_fy="2026-27",
        total_income_receipt_year_paise=30_00_000 * 100,
        arrears=[A.ArrearSlice(fy="2025-26", amount_paise=5_00_000 * 100)],
        form_10e_acknowledgement="10E-1")
    assert not r.available
    assert any("their own return" in g for g in r.gaps)


# ── Form 10E: the proviso to §89 ─────────────────────────────────────────────

def test_relief_is_blocked_without_form_10e():
    """The proviso to §89, read with Rule 21AA: relief 'shall not be granted'
    unless Form 10E has been filed before the return. A return claiming §89
    without one draws a §143(1) intimation disallowing the relief in full — one
    of the commonest adjustments there is."""
    r = A.compute_relief(
        receipt_fy="2026-27",
        total_income_receipt_year_paise=30_00_000 * 100,
        arrears=[_slice("2025-26", 5_00_000 * 100, 8_00_000 * 100)])
    assert not r.available
    assert "Form 10E" in r.blocked_reason
    assert "143(1)" in r.blocked_reason


def test_the_amount_is_still_computed_and_shown_when_blocked():
    """Blocked is not hidden. The CA needs to see what is at stake to decide
    whether filing the form is worth it."""
    r = A.compute_relief(
        receipt_fy="2026-27",
        total_income_receipt_year_paise=30_00_000 * 100,
        arrears=[_slice("2025-26", 5_00_000 * 100, 8_00_000 * 100)])
    assert r.relief_paise > 0
    assert not r.available


def test_a_blank_acknowledgement_does_not_count_as_filed():
    r = A.compute_relief(
        receipt_fy="2026-27",
        total_income_receipt_year_paise=30_00_000 * 100,
        arrears=[_slice("2025-26", 5_00_000 * 100, 8_00_000 * 100)],
        form_10e_acknowledgement="   ")
    assert not r.available


# ── Each earlier year at ITS OWN rates ───────────────────────────────────────

@pytest.fixture()
def a_year_with_different_rates(monkeypatch):
    """Put a synthetic FY 2024-25 in the registry with a visibly harsher slab.

    Needed because the registry currently holds only 2025-26 and 2026-27, and
    2026-27 carries 2025-26's figures forward unchanged — so with real data,
    taxing an earlier year at the receipt year's rates gives an IDENTICAL
    answer and the property has no behavioural signature at all. A negative
    control confirmed exactly that: swapping slice_.fy for receipt_fy in the
    loop broke nothing.

    Rather than assert the shape of the call, this gives the property something
    to be true OF: a year whose rates differ enough that using the wrong ones
    changes the relief.
    """
    base = RATES_BY_FY["2025-26"]
    harsh = dataclasses.replace(
        base,
        fy="2024-25",
        # A flat 30% from the first rupee — nothing like 2025-26, so any
        # substitution shows up immediately.
        new_regime_slabs=(SlabBracket(upto_paise=None, rate_percent=30),),
        new_regime_standard_deduction_paise=0,
        new_regime_rebate=dataclasses.replace(base.new_regime_rebate,
                                              threshold_paise=0, max_rebate_paise=0),
    )
    monkeypatch.setitem(RATES_BY_FY, "2024-25", harsh)
    return harsh


def test_an_earlier_year_is_taxed_at_its_own_rates(a_year_with_different_rates):
    """The whole point of §89. Rule 21A(2) asks what the arrears WOULD have
    cost in the years they relate to — at those years' rates. Computing B at
    the receipt year's slabs collapses the comparison and produces a relief
    that is wrong by whatever the two years' rates differ by."""
    r = A.compute_relief(
        receipt_fy="2026-27",
        total_income_receipt_year_paise=30_00_000 * 100,
        arrears=[_slice("2024-25", 5_00_000 * 100, 8_00_000 * 100)],
        form_10e_acknowledgement="10E-1")
    assert r.available
    # 30% flat on the ₹5,00,000 slice, plus 4% cess = ₹1,56,000.
    assert r.per_year[0]["additional_tax_paise"] == 1_56_000 * 100

    # And that is NOT what the receipt year's rates would have produced.
    same_income_at_receipt_year_rates = A.compute_relief(
        receipt_fy="2026-27",
        total_income_receipt_year_paise=30_00_000 * 100,
        arrears=[_slice("2026-27", 5_00_000 * 100, 8_00_000 * 100)],
        form_10e_acknowledgement="10E-1")
    assert (same_income_at_receipt_year_rates.per_year[0]["additional_tax_paise"]
            != r.per_year[0]["additional_tax_paise"])
    assert r.relief_paise != same_income_at_receipt_year_rates.relief_paise
