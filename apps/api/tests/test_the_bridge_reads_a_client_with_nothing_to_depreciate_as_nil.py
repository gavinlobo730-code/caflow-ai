"""The book-to-tax bridge reads "no fixed assets and no depreciation in the ledger" as a nil charge, not as an unreadable one (POST-A-268).

WHAT WAS WRONG
    `fixed_asset_movement.posted_depreciation_paise` answers None when the Depreciation Expense account cannot be resolved AND when it
    can be but nothing was posted in the year, and the bridge turned every None into "Depreciation charged in the accounts could not be
    read" and marked the bridge incomplete. Every client's standard chart carries the account, so a client with no fixed assets (an
    individual with a small business, say) always read None: the bridge could never complete for it, while the §32 side correctly
    reported itself complete.

WHAT IS HELD
    * no fixed-asset register row (a deleted row is not one) AND no depreciation in the ledger for the year is a reading of zero, said
      as such, whether the client's chart has the account or not;
    * a register row with nothing posted stays "could not be read": a charge is expected and has not been posted, and a zero there
      would be a claim nobody measured; so does a posting in the year (then there is a figure) and another client's records;
    * a look that FAILS (the register, the chart or the balances cannot be read) stays "could not be read": not being able to look is
      never the same as there being nothing to find;
    * a figure that is read, and a figure the caller typed, are untouched.
"""
from __future__ import annotations

import pytest

import services.book_to_tax_service as b2t
from tests.e2e_harness import FakeDB

FIRM, CLIENT, OTHER = "firm-1", "client-1", "client-2"
FY_START, FY_END = "2025-04-01", "2026-03-31"
USER = {"firm_id": FIRM, "id": "u", "role": "Partner"}


def _read(db):
    return b2t.depreciation_per_books(db, FIRM, CLIENT, FY_START, FY_END)


def _account(db, *, client=CLIENT, active=True, name="Depreciation Expense"):
    return db.seed("chart_of_accounts", {"id": f"acc-{client}-{active}-{name}", "firm_id": FIRM, "client_id": client,
                                         "account_name": name, "is_active": active})


def _asset(db, *, client=CLIENT, deleted=None):
    return db.seed("fixed_assets", {"id": f"fa-{client}-{deleted}", "firm_id": FIRM, "client_id": client, "deleted_at": deleted})


def _posted(db, account, *, debit=5_000_00, month="2025-09-01", client=CLIENT):
    return db.seed("account_period_balances", {"firm_id": FIRM, "client_id": client, "account_id": account["id"],
                                               "period_month": month, "debit_paise": debit, "credit_paise": 0})


def test_no_assets_and_no_account_is_a_nil_charge_and_says_why():
    got = _read(FakeDB())
    assert got.value == 0 and got.derived is True
    assert "No depreciation was charged" in got.source and "no fixed assets" in got.source


def test_no_assets_and_an_account_with_nothing_posted_is_a_nil_charge_too():
    """The commonest case: the standard chart carries the account for every client."""
    db = FakeDB()
    _account(db)
    assert _read(db).value == 0


def test_a_firm_level_account_with_no_client_is_still_an_account_with_nothing_posted():
    db = FakeDB()
    db.seed("chart_of_accounts", {"id": "acc-firm", "firm_id": FIRM, "client_id": None, "account_name": "Depreciation Expense",
                                  "is_active": True})
    assert _read(db).value == 0


def test_a_deleted_register_row_is_not_a_fixed_asset():
    db = FakeDB()
    _account(db)
    _asset(db, deleted="2026-01-01T00:00:00+00:00")
    assert _read(db).value == 0


def test_another_clients_assets_and_postings_are_not_this_clients():
    db = FakeDB()
    account = _account(db)
    _asset(db, client=OTHER)
    _posted(db, account, client=OTHER)
    assert _read(db).value == 0


def test_assets_on_the_register_with_nothing_posted_stay_unreadable():
    db = FakeDB()
    _account(db)
    _asset(db)
    got = _read(db)
    assert got.value is None and "could not be read" in got.source


def test_assets_with_no_account_at_all_stay_unreadable():
    db = FakeDB()
    _asset(db)
    got = _read(db)
    assert got.value is None and "could not be read" in got.source


def test_a_posting_in_the_year_is_the_figure_even_with_no_register_row():
    db = FakeDB()
    account = _account(db)
    _posted(db, account)
    got = _read(db)
    assert got.value == 5_000_00 and "actually posted" in got.source


def test_postings_on_an_inactive_account_are_still_depreciation_in_the_ledger():
    """`_find_account` skips an inactive account, so the reader answers None for the year; the check must still see the postings, or a
    year with a charge on a deactivated account would be called nil."""
    db = FakeDB()
    account = _account(db, active=False)
    _posted(db, account)
    got = _read(db)
    assert got.value is None and "could not be read" in got.source


def test_an_inactive_account_with_nothing_posted_is_nothing():
    db = FakeDB()
    _account(db, active=False)
    assert _read(db).value == 0


def test_a_posting_outside_the_year_is_not_this_years():
    db = FakeDB()
    account = _account(db)
    _posted(db, account, month="2024-12-01")
    assert _read(db).value == 0


@pytest.mark.parametrize("broken", ["chart_of_accounts", "fixed_assets", "account_period_balances"])
def test_a_look_that_fails_is_not_a_finding_of_nothing(broken):
    class _Flaky(FakeDB):
        def table(self, name):
            if name == broken:
                raise RuntimeError("statement timeout")
            return super().table(name)

    db = _Flaky()
    _account(db)
    got = _read(db)
    assert got.value is None and "could not be read" in got.source


def test_the_caller_s_figure_still_wins_over_a_derived_nil():
    out = b2t.resolve_inputs(FakeDB(), FIRM, CLIENT, "2025-26", USER,
                             book_profit_paise=1, disallowances_paise=1, depreciation_per_books_paise=99)
    assert out["depreciation_per_books"].value == 99 and out["depreciation_per_books"].derived is False


def test_the_resolver_derives_the_nil_for_a_client_with_nothing_to_depreciate(monkeypatch):
    monkeypatch.setattr(b2t, "book_profit", lambda *a, **k: b2t.DerivedInput(1, "x", True))
    monkeypatch.setattr(b2t, "section_43bh_disallowance", lambda *a, **k: b2t.DerivedInput(0, "x", True))
    db = FakeDB()
    _account(db)
    out = b2t.resolve_inputs(db, FIRM, CLIENT, "2025-26", USER)
    assert out["depreciation_per_books"].value == 0 and out["depreciation_per_books"].derived is True
