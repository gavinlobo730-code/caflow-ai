"""A refused spreadsheet date says WHICH of three things was wrong (PRE-A-001).

`parse_cell_date` returns None for a two-digit year, for a day that is not on the
calendar (31-02-2025, month 13) and for text that is not a date at all, and until
08-10-2026 every importer answered all three with the sentence written for the
first: "a two-digit year is not read, because 4/1/26 could be 4 January or 1 April".
A CA whose sheet showed 31-02-2025 was sent to correct a year that was fine.
Found by driving the migration doors in a browser with a workbook whose dates were
four-digit throughout.

`why_not_a_date` is the one place the reason is worked out, and the three
importers (opening documents, vouchers, the fixed-asset register) ask it.
"""
from __future__ import annotations

import calendar
import re
from pathlib import Path

import pytest

from domain.spreadsheet_cells import (
    DATE_FORMAT_SENTENCE,
    DATE_SHAPE_SENTENCE,
    parse_cell_date,
    why_not_a_date,
)

API_ROOT = Path(__file__).resolve().parents[1]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]


@pytest.mark.parametrize("text", ["4/1/26", "01-03-26", "1.4.26", "15-Mar-26", "15 March 26"])
def test_a_two_digit_year_gets_the_sentence_that_explains_why_it_is_never_guessed(text):
    assert parse_cell_date(text) is None
    assert why_not_a_date(text) == DATE_FORMAT_SENTENCE


@pytest.mark.parametrize("text,reason", [
    ("31-02-2026", "February 2026 has 28 days"),
    ("29-02-2025", "February 2025 has 28 days"),
    ("30-02-2024", "February 2024 has 29 days"),          # a leap year
    ("31-04-2026", "April 2026 has 30 days"),
    ("31/9/2026", "September 2026 has 30 days"),
    ("2026-02-30", "February 2026 has 28 days"),          # the ISO shape
    ("2026-06-31", "June 2026 has 30 days"),
    ("30 Feb 2026", "February 2026 has 28 days"),         # the month-name shape
    ("31-Nov-2026", "November 2026 has 30 days"),
    ("0-3-2026", "there is no day 0"),
    ("13/13/2026", "there is no month 13"),
    ("2026-13-01", "there is no month 13"),
    ("0000-01-01", "there is no year 0"),
])
def test_a_day_that_is_not_on_the_calendar_says_which_part(text, reason):
    assert parse_cell_date(text) is None
    got = why_not_a_date(text)
    assert reason in got, got
    assert "two-digit year" not in got, "a four-digit year is not blamed for a calendar fault"


def test_a_month_first_date_is_told_the_order_it_was_read_in():
    # 12/25/2026 is what an American spreadsheet writes for 25 December. Read day
    # first it has no month 25, and the CA is told the reading, not just the fault.
    got = why_not_a_date("12/25/2026")
    assert "there is no month 25" in got and "day first" in got, got
    # 13/13/2026 cannot be a month-first date either, so the hint is not offered.
    assert "day first" not in why_not_a_date("13/13/2026")
    # An ISO date has no day-first reading to explain.
    assert "day first" not in why_not_a_date("2026-13-01")


@pytest.mark.parametrize("text", ["tomorrow", "March first", "2026/03/01x", "15th March", "soon", "--"])
def test_text_that_is_not_a_date_is_told_how_to_write_one(text):
    assert parse_cell_date(text) is None
    assert why_not_a_date(text) == DATE_SHAPE_SENTENCE
    assert "for example 15-03-2025" in DATE_SHAPE_SENTENCE


def test_the_three_answers_are_three_different_sentences():
    answers = {why_not_a_date("4/1/26"), why_not_a_date("31-02-2026"), why_not_a_date("soon")}
    assert len(answers) == 3


def test_a_date_that_does_read_gets_the_general_guidance_and_no_invented_fault():
    assert parse_cell_date("15-03-2025") is not None
    assert why_not_a_date("15-03-2025") == DATE_SHAPE_SENTENCE
    assert why_not_a_date(None) == DATE_SHAPE_SENTENCE and why_not_a_date("") == DATE_SHAPE_SENTENCE


def test_the_sentence_and_the_calendar_agree_for_every_day_first_date_in_three_years():
    """Every dd-mm-yyyy from 2024 (leap) to 2026: it is read, or the sentence is true.

    The reason is worked out from the same patterns `parse_cell_date` reads, so the
    two cannot disagree about a shape; this walks every day-first date over a leap
    year and two ordinary ones, and holds the NUMBER in the sentence to the
    standard library's calendar.
    """
    unreadable = 0
    for year in (2024, 2025, 2026):
        for month in range(1, 13):
            longest = calendar.monthrange(year, month)[1]
            for day in range(1, 32):
                text = f"{day:02d}-{month:02d}-{year}"
                if parse_cell_date(text) is not None:
                    assert day <= longest
                    continue
                unreadable += 1
                assert day > longest, f"{text} is on the calendar and was not read"
                assert why_not_a_date(text) == f"{MONTHS[month - 1]} {year} has {longest} days"
    # 8 in February (29-31 in two ordinary years, 30-31 in the leap one) and the
    # 31st of four 30-day months in each of three years: 20.
    assert unreadable == 20, "the walk must meet the cases it claims to"


def test_every_importer_asks_this_function_and_none_carries_the_old_blanket_sentence():
    """The rule, not the three files: nothing outside the module names the constant.

    `DATE_FORMAT_SENTENCE` is the answer for ONE of three faults, so a module that
    interpolates it for any unreadable date is the defect again.
    """
    users = []
    for path in (API_ROOT / "domain").rglob("*.py"):
        if path.name == "spreadsheet_cells.py":
            continue
        if "DATE_FORMAT_SENTENCE" in path.read_text():
            users.append(str(path.relative_to(API_ROOT)))
    for path in (API_ROOT / "services").rglob("*.py"):
        if "DATE_FORMAT_SENTENCE" in path.read_text():
            users.append(str(path.relative_to(API_ROOT)))
    for path in (API_ROOT / "routers").rglob("*.py"):
        if "DATE_FORMAT_SENTENCE" in path.read_text():
            users.append(str(path.relative_to(API_ROOT)))
    assert users == [], (
        "tell a refused date why with domain.spreadsheet_cells.why_not_a_date, which "
        "separates a two-digit year, a day not on the calendar and text that is not "
        "a date:\n  " + "\n  ".join(users))

    # and the three importers do ask it, for every date they refuse
    for rel, minimum in (("domain/accounting/opening_document_import.py", 2),
                         ("domain/accounting/voucher_import.py", 1),
                         ("domain/fixed_assets/opening_register.py", 3)):
        src = (API_ROOT / rel).read_text()
        assert len(re.findall(r"why_not_a_date\(", src)) >= minimum, rel
        assert "is not a date" in src
