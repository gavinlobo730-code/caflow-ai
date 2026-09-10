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
