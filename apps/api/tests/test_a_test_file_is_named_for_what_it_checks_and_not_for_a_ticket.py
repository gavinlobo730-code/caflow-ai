"""A test file is named for the behaviour it holds, not for the ticket that asked for it (POST-A-191).

Sixty-five files were named after a task or review round (the letter r and a number, then a topic): a name that says nothing about what fails
when the test does, and that a reader has to open to place. They were renamed by behaviour on 27-11-2026, with every place that cites one
updated, and this holds the line: a new file may carry a MIGRATION number first (it names the migration whose behaviour the file proves, and
says the behaviour in the rest of the name) but not a ticket or round number.

What it does not do: group the files into folders by subsystem (about 1,800 files in one directory). That move rewrites every path a test
reads and every place that cites one, and is kept on the ledger line POST-A-191.

The example names below are built at run time, so that this file names no test that does not exist.
"""
from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
PREFIX = "test" + "_"
TICKET_NAME = re.compile(r"^" + PREFIX + r"r\d")


def test_no_test_file_is_named_for_a_ticket_or_a_review_round():
    names = sorted(p.name for p in TESTS.glob(PREFIX + "*.py"))
    assert len(names) > 1000, "the directory was not read: a vacuous pass"
    ticketed = [n for n in names if TICKET_NAME.match(n)]
    assert not ticketed, (
        "name a test file for the behaviour it checks (a migration number first is fine), "
        f"not for a ticket or round: {ticketed}")


def test_the_rule_would_catch_the_names_it_was_written_for():
    for tail in ("244_cross_tenant_gaps.py", "3_5e_auth_cache.py", "2_10_payroll_slips_pg.py", "440_portal_client_can_post_a_message_pg.py"):
        assert TICKET_NAME.match(PREFIX + "r" + tail), tail
    for tail in ("the_receipt_function_refuses_a_draft_pg.py", "549_a_signed_in_session_reads_none_of_the_payroll_tables_pg.py", "recurring_invoices.py"):
        assert not TICKET_NAME.match(PREFIX + tail), tail
