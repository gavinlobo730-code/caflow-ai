"""The amount in words moved to one module, and the crore group stopped lying.

WHAT WAS WRONG
    `amount_in_words` lived in services/invoice_pdf_service.py. The payslip
    needed the same sentence — a net pay in figures alone is the line an
    employee disputes and the line a lender looks for — and copying it would
    have been two implementations of "one lakh eighteen thousand" that drift.

    The crore group was rendered by a three-digit helper, so it was correct
    only up to ₹999 crore. Above that an invoice read "Ten Hundred Crore", and
    above ₹20,000 crore the PDF builder raised IndexError off the end of the
    ones table — a crash in a document generator, reachable from any invoice
    total a user can type.
"""
from __future__ import annotations

import pytest

from domain.reporting.amount_words import amount_in_words
from services.invoice_pdf_service import amount_in_words as invoice_words
from services.payslip_pdf_service import amount_in_words as payslip_words


def test_it_is_literally_the_same_function_in_both_documents():
    """Not "they agree" — the same object. Two implementations that agree today
    are two implementations."""
    assert invoice_words is amount_in_words
    assert payslip_words is amount_in_words


@pytest.mark.parametrize("paise,expected", [
    (0, "Rupees Zero Only"),
    (150, "Rupees One and Fifty Paise Only"),
    (1_18_000_00, "Rupees One Lakh Eighteen Thousand Only"),
    (1_23_45_678_00, "Rupees One Crore Twenty Three Lakh Forty Five Thousand "
                     "Six Hundred Seventy Eight Only"),
])
def test_the_readings_that_were_already_right_are_unchanged(paise, expected):
    """The negative control for the move: these are the exact strings the
    invoice tests have asserted since phase 12."""
    assert amount_in_words(paise) == expected


def test_a_thousand_crore_is_read_as_a_thousand_crore():
    """Was 'Ten Hundred Crore'. The Indian system reads the crore group by the
    same rules as the rest, which is why this recurses."""
    assert amount_in_words(1_000_00_00_000_00) == "Rupees One Thousand Crore Only"
    assert amount_in_words(1_00_000_00_00_000_00) == "Rupees One Lakh Crore Only"


def test_a_large_amount_no_longer_crashes_the_document():
    """₹20,000 crore raised IndexError out of the PDF builder. It is a silly
    invoice and it is still a crash on a value a user can type."""
    assert amount_in_words(20_000_00_00_000_00) == "Rupees Twenty Thousand Crore Only"


def test_a_negative_amount_is_read_rather_than_refused():
    """A full-and-final settlement can be net negative when a notice-pay
    recovery exceeds the month's salary. A document that raises on the one
    month that is hard to explain is worse than one that states it."""
    assert amount_in_words(-5_000_00) == "Minus Rupees Five Thousand Only"


# ── In figures, too — the Indian grouping ────────────────────────────────────
#
# Python's own f"{n:,}" groups in threes and gives "1,234,567", which no Indian
# document uses. apps/web formats the same figure with
# Intl.NumberFormat("en-IN") and gets it right, so the screen and the PDF of one
# amount disagree. That is tree-wide (roughly twenty sites across services/ and
# domain/) and is NOT fixed by this function existing — it is here so new code
# has somewhere correct to call, and so the later sweep has one place to point.

@pytest.mark.parametrize("n,expected", [
    (0, "0"),
    (7, "7"),
    (999, "999"),
    (1_000, "1,000"),
    (99_999, "99,999"),
    (1_00_000, "1,00,000"),
    (12_34_567, "12,34,567"),
    (1_23_45_678, "1,23,45,678"),
    (12_34_56_789, "12,34,56,789"),
])
def test_the_grouping_is_indian_and_not_western(n, expected):
    from domain.reporting.amount_words import indian_digits
    assert indian_digits(n) == expected
    if n >= 1_00_000:
        assert indian_digits(n) != f"{n:,}", (
            "this is exactly the value where the two conventions diverge — if "
            "they agree here the function is doing nothing")


def test_a_negative_figure_keeps_its_sign_outside_the_grouping():
    from domain.reporting.amount_words import indian_digits
    assert indian_digits(-12_34_567) == "-12,34,567"


def test_paise_are_truncated_by_integer_division_not_by_a_float():
    from domain.reporting.amount_words import indian_rupees
    assert indian_rupees(8_50_000_00) == "8,50,000"
    assert indian_rupees(99) == "0"          # under a rupee is zero rupees
    assert indian_rupees(-1_27_500_00) == "-1,27,500"
    assert indian_rupees(0) == "0"
    assert indian_rupees(None) == "0"
