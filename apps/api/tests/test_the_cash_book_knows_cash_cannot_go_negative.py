"""BANK-20: there is a cash book, and it knows the one rule cash has.

WHAT DID NOT EXIST

A repo-wide search for 'cash book', 'cashbook', 'petty cash' and 'petty_cash'
returned four hits and none of them was a feature: a seeded ledger, a test
fixture, a line of prose in the DPDP retention map, and some help text.
apps/web/.../reports/ held ageing, bank-book, ratios and trend — no cash book.

Phase 1a is what made this buildable: until a cash receipt actually posted to
Cash in Hand, a cash book would have reported zero for every client.
"""
from __future__ import annotations

import pytest

from domain.reporting.cash_book import (
    NegativeCashDay, explain_negative, first_negative_day, is_cash_account,
)


# ── which ledgers are cash ───────────────────────────────────────────────────

@pytest.mark.parametrize("typ,sub,expected", [
    ("Asset", "Cash", True),            # 1001 Cash in Hand, 1002 Petty Cash
    ("Asset", "Petty Cash", True),
    ("Asset", "Cash — Branch", True),   # a firm's own account
    ("Asset", "Bank", False),
    ("Asset", "Receivable", False),
    ("Liability", "Cash Credit", False),
    ("Liability", "Bank Overdraft", False),
    (None, None, False),
])
def test_which_ledgers_are_cash(typ, sub, expected):
    assert is_cash_account(typ, sub) is expected


def test_a_cash_credit_facility_is_not_cash():
    """The type test is load-bearing, not decoration. A Cash Credit facility has
    'cash' in its name and is money OWED TO A BANK — BANK-02 is the finding
    about getting exactly this wrong, and a cash book that swept it in would
    report a client's borrowings as notes in the till."""
    assert is_cash_account("Liability", "Cash Credit") is False


# ── the rule ────────────────────────────────────────────────────────────────

def _line(d=0, c=0, on="2026-05-01", narration=""):
    return {"debit_paise": d, "credit_paise": c, "entry_date": on,
            "narration": narration, "entry_id": "e-" + on}


def _first(lines, opening=0):
    return first_negative_day(lines, account_id="a1", account_name="Cash in Hand",
                              opening_balance_paise=opening)


def test_a_balance_that_never_goes_negative_reports_nothing():
    assert _first([_line(d=10_000), _line(c=4_000, on="2026-05-02")]) is None


def test_paying_out_more_cash_than_is_held_is_caught():
    """The everyday case: a payment entered before the receipt that funded it."""
    day = _first([_line(d=1_000, on="2026-05-01"),
                  _line(c=5_000, on="2026-05-02", narration="Paid supplier")])
    assert day is not None
    assert day.on_date == "2026-05-02"
    assert day.balance_paise == -4_000


def test_it_is_the_FIRST_day_not_the_closing_balance():
    """THE POINT OF THE RULE. A balance that dips negative mid-month and
    recovers by the 31st is invisible in a closing figure and is exactly as
    wrong — the cash was never there on the day it was paid out."""
    day = _first([
        _line(c=5_000, on="2026-05-02", narration="Paid supplier"),
        _line(d=9_000, on="2026-05-20", narration="Cash sales banked"),
    ])
    assert day is not None and day.on_date == "2026-05-02"
    # and the month closes healthily positive, which is why a closing-balance
    # check would have said nothing at all
    assert 0 - 5_000 + 9_000 > 0


def test_the_opening_balance_counts():
    """Cash carried forward is cash. Ignoring the opening balance would report
    a false negative on the first payment of every month."""
    assert _first([_line(c=5_000)], opening=8_000) is None
    assert _first([_line(c=5_000)], opening=1_000) is not None


def test_exactly_zero_is_not_negative():
    """Spending the last rupee is legal; an off-by-one here cries wolf on every
    client who empties the till."""
    assert _first([_line(c=5_000)], opening=5_000) is None


def test_the_balance_is_recomputed_not_trusted_from_the_row():
    """A caller may re-sort a ledger for display, and a running balance only
    means anything in date order. Rows carrying a stale balance_paise must not
    be believed."""
    lines = [dict(_line(c=5_000), balance_paise=999_999)]
    day = _first(lines, opening=0)
    assert day is not None and day.balance_paise == -5_000


# ── what the CA is told ─────────────────────────────────────────────────────

def test_the_message_names_the_three_causes_not_just_the_number():
    """A bare 'balance is negative' is a number they can already see. The value
    is naming the causes, because the remedy differs for each."""
    msg = explain_negative(NegativeCashDay(
        account_id="a1", account_name="Petty Cash", on_date="2026-05-02",
        balance_paise=-4_000, entry_id="e1", narration=""))
    assert "Petty Cash" in msg and "2026-05-02" in msg and "40" in msg
    for cause in ("before the receipt", "never", "twice"):
        assert cause in msg, f"the message should name the '{cause}' cause"


# ── the endpoint exists and is client-scoped ────────────────────────────────

def test_the_cash_book_endpoint_requires_a_client():
    """A firm-wide cash book would add together the physical cash of unrelated
    businesses, which is not a figure that means anything."""
    import inspect
    from routers import accounting
    from pydantic_core import PydanticUndefined
    sig = inspect.signature(accounting.get_cash_book)
    assert "client_id" in sig.parameters
    # FastAPI folds Query(...) into Query(PydanticUndefined); that — not
    # Ellipsis — is what "required" looks like by the time it reaches the
    # signature. Comparing against Ellipsis passes on an OPTIONAL parameter
    # too, so it would have asserted nothing.
    assert sig.parameters["client_id"].default.default is PydanticUndefined, \
        "client_id must be required, not optional"
    assert sig.parameters["start_date"].default.default is None, \
        "and the control: an optional parameter must look different"


def test_the_cash_book_does_not_reimplement_the_running_balance():
    """It asks the same reporting engine /ledger uses. A second running-balance
    implementation is the drift CLAUDE.md's reporting section warns about, and
    the account-ledger SQL parity test exists because it has happened here."""
    import inspect
    from routers import accounting
    src = inspect.getsource(accounting.get_cash_book)
    assert "_reporting_service().ledger(" in src
