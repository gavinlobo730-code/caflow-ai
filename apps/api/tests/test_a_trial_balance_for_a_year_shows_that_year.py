"""
ACC-08 — the Trial Balance was always inception-to-date, so choosing a financial
year only moved the as-at date.

WHAT WAS WRONG
    `ReportingService.trial_balance` passed `None` as the snapshot's start, and
    the screen sent `as_of_date: period.end` and nothing else. So every line
    since the books began was summed. That is RIGHT for the balance-sheet
    accounts — a balance is what has accumulated — and wrong for the Profit and
    Loss ones: a CA who picks FY 2026-27 is asking what that year sold, and was
    shown every year's sales added together.

    And it never corrects itself. This product deliberately posts no closing
    entries — `year_end_financial_service` DERIVES cumulative profit into
    Reserves and Surplus instead (see its comment at the `cumulative_pat`
    block) — so the income and expense accounts carry their whole history for
    ever. A third-year client's Trial Balance overstated revenue threefold.

WHAT IS ASSERTED, AND WHY THIS SHAPE
    1. The defect as a NUMBER: the same books, same as-at date, with and
       without a start, give different revenue — and the difference is exactly
       the prior year's.
    2. **It still balances.** This is the assertion that matters, and it is why
       the fix is larger than "pass a start date". Balance-sheet accounts close
       cumulatively while P&L accounts show one year, and those two do not add
       up on their own: without closing entries Σ(balance-sheet net) IS the
       cumulative profit, so the trial balance would be out by exactly the
       PRIOR years' result. A derived `Surplus brought forward` row carries it.
       A test that only checked revenue would pass on a trial balance that no
       longer balanced, which is the worse bug.
    3. The brought-forward row is on the right SIDE and is absent when there is
       nothing to bring forward (a first year), so it is not decoration.
    4. Inception-to-date is UNCHANGED when no start is given — every existing
       caller, and the balance-sheet reading of the same data, must be
       byte-identical.
    5. Cash basis REFUSES the period and says why, rather than silently
       widening the window: its projection transforms the whole ledger, so a
       receipt in this period settling an invoice from another cannot be split
       across two windows without counting the settlement twice.
"""
from __future__ import annotations

import pytest

from domain.reporting import (
    Account, JournalEntry, JournalLine, InMemoryLedgerSource, ReportingService,
)
from domain.reporting.builders import SURPLUS_BROUGHT_FORWARD_ID

FIRM, CLIENT = "firm-1", "client-1"

# FY 2025-26 and FY 2026-27.
FY26 = ("2025-04-01", "2026-03-31")
FY27 = ("2026-04-01", "2027-03-31")

ACCOUNTS = [
    Account("bank", "1000", "Bank — HDFC", "Asset", "Bank", system_key="bank"),
    Account("cap", "3000", "Capital Account", "Equity"),
    Account("rev", "4000", "Professional Fees", "Revenue"),
    Account("exp", "5000", "Office Rent", "Expense"),
]


def je(jid, date, lines):
    return JournalEntry(
        id=jid, entry_date=date, client_id=CLIENT, firm_id=FIRM, entry_type="x",
        lines=tuple(JournalLine(*l) for l in lines),
        created_at=f"{date}T00:00:00", reference_no=None, narration=None,
    )


#: Two years of books. FY26: ₹1,00,000 capital in, ₹3,00,000 fees, ₹1,00,000 rent
#: → profit ₹2,00,000. FY27: ₹5,00,000 fees, ₹2,00,000 rent → profit ₹3,00,000.
ENTRIES = [
    je("c1", "2025-04-01", [("bank", 10_000_00, 0), ("cap", 0, 10_000_00)]),
    je("r1", "2025-06-10", [("bank", 3_000_00, 0), ("rev", 0, 3_000_00)]),
    je("e1", "2025-09-10", [("exp", 1_000_00, 0), ("bank", 0, 1_000_00)]),
    je("r2", "2026-06-10", [("bank", 5_000_00, 0), ("rev", 0, 5_000_00)]),
    je("e2", "2026-09-10", [("exp", 2_000_00, 0), ("bank", 0, 2_000_00)]),
]

PRIOR_PROFIT = 3_000_00 - 1_000_00       # FY26 result, ₹2,000.00
THIS_YEAR_REVENUE = 5_000_00
ALL_TIME_REVENUE = 3_000_00 + 5_000_00


def _svc(entries=ENTRIES):
    return ReportingService(InMemoryLedgerSource(accounts=ACCOUNTS, entries=entries))


def _tb(*, start=None, end=FY27[1], basis="accrual", entries=ENTRIES):
    return _svc(entries).trial_balance(FIRM, CLIENT, end, basis=basis, start_date=start)


def _row(tb, account_id):
    return next((r for r in tb["lines"] if r["account_id"] == account_id), None)


# ── 1. the defect, as a number ───────────────────────────────────────────────

def test_without_a_start_the_revenue_row_is_every_year_added_together():
    all_time = _tb()
    assert _row(all_time, "rev")["total_credit_paise"] == ALL_TIME_REVENUE


def test_with_a_start_the_revenue_row_is_that_year():
    year = _tb(start=FY27[0])
    assert _row(year, "rev")["total_credit_paise"] == THIS_YEAR_REVENUE
    # The whole finding in one subtraction.
    assert ALL_TIME_REVENUE - THIS_YEAR_REVENUE == 3_000_00


def test_a_balance_sheet_account_still_closes_cumulatively():
    """A balance IS what has accumulated, so the bank must NOT be narrowed to
    the year — that would be the same bug pointed the other way."""
    year = _tb(start=FY27[0])
    bank = _row(year, "bank")
    assert bank["total_debit_paise"] == 10_000_00 + 3_000_00 - 1_000_00 + 5_000_00 - 2_000_00
    assert bank["opening_debit_paise"] == 10_000_00 + 3_000_00 - 1_000_00
    assert bank["period_debit_paise"] == 5_000_00
    assert bank["period_credit_paise"] == 2_000_00


def test_a_pl_accounts_opening_is_presented_as_nil():
    """Its prior movement is not lost — it is carried in the brought-forward
    row, which is where a closed set of books would have put it."""
    rev = _row(_tb(start=FY27[0]), "rev")
    assert rev["opening_debit_paise"] == 0 and rev["opening_credit_paise"] == 0
    assert rev["period_credit_paise"] == THIS_YEAR_REVENUE


# ── 2. it still balances — the assertion that makes the rest safe ────────────

def test_the_period_trial_balance_balances():
    year = _tb(start=FY27[0])
    assert year["is_balanced"], year
    assert year["difference_paise"] == 0
    assert year["total_debit_paise"] == year["total_credit_paise"]


def test_it_would_not_balance_without_the_brought_forward_row():
    """States WHY the row exists, arithmetically, rather than trusting that it
    does. Strip it and the trial balance is out by exactly the prior result."""
    year = _tb(start=FY27[0])
    without = [r for r in year["lines"] if r["account_id"] != SURPLUS_BROUGHT_FORWARD_ID]
    dr = sum(r["total_debit_paise"] for r in without)
    cr = sum(r["total_credit_paise"] for r in without)
    assert dr - cr == PRIOR_PROFIT, (
        "the imbalance a period trial balance has without the row IS the prior "
        "years' result — which is why a narrower window alone is not the fix")


def test_the_brought_forward_row_is_a_credit_when_the_prior_years_made_a_profit():
    bf = _row(_tb(start=FY27[0]), SURPLUS_BROUGHT_FORWARD_ID)
    assert bf is not None
    assert bf["total_credit_paise"] == PRIOR_PROFIT
    assert bf["total_debit_paise"] == 0
    assert bf["account_type"] == "Equity"


def test_a_brought_forward_loss_is_a_debit():
    entries = [
        je("c1", "2025-04-01", [("bank", 10_000_00, 0), ("cap", 0, 10_000_00)]),
        je("e0", "2025-09-10", [("exp", 4_000_00, 0), ("bank", 0, 4_000_00)]),   # loss year
        je("r2", "2026-06-10", [("bank", 5_000_00, 0), ("rev", 0, 5_000_00)]),
    ]
    bf = _row(_tb(start=FY27[0], entries=entries), SURPLUS_BROUGHT_FORWARD_ID)
    assert bf["total_debit_paise"] == 4_000_00 and bf["total_credit_paise"] == 0


def test_a_first_year_has_no_brought_forward_row_at_all():
    """Not a zero row. There is nothing to bring forward, and a nil line on a
    trial balance invites the question of what it is."""
    year = _tb(start=FY26[0], end=FY26[1])
    assert _row(year, SURPLUS_BROUGHT_FORWARD_ID) is None
    assert year["is_balanced"]


# ── 3. inception-to-date is untouched ────────────────────────────────────────

def test_no_start_means_byte_identical_to_what_it_always_returned():
    all_time = _tb()
    assert "start_date" not in all_time
    for row in all_time["lines"]:
        assert "opening_debit_paise" not in row, (
            "the period columns must not appear on a report nobody asked a "
            "period of — every existing consumer reads these rows")
    assert _row(all_time, SURPLUS_BROUGHT_FORWARD_ID) is None
    assert all_time["is_balanced"]


def test_the_all_time_trial_balance_agrees_with_the_balance_sheet():
    """The cross-check that says the inception-to-date reading is the one the
    rest of the engine makes: Σ(balance-sheet net) is the cumulative profit,
    which is what the all-time trial balance's P&L rows net to."""
    all_time = _tb()
    pl_net = sum(r["total_debit_paise"] - r["total_credit_paise"]
                 for r in all_time["lines"] if r["account_id"] in ("rev", "exp"))
    assert -pl_net == PRIOR_PROFIT + (5_000_00 - 2_000_00)


# ── 4. an account that moved and came back to nil ────────────────────────────

def test_an_account_with_turnover_and_a_nil_close_is_kept_in_a_period():
    """The inception-to-date form drops net-zero rows because it has no
    turnover column to show. A period trial balance does, and a CA reading one
    is asking what MOVED — a row with money through it and a nil closing is
    exactly the row they want."""
    entries = ENTRIES + [
        je("x1", "2026-07-01", [("exp", 9_00, 0), ("bank", 0, 9_00)]),
        je("x2", "2026-07-02", [("bank", 9_00, 0), ("exp", 0, 9_00)]),
    ]
    year = _tb(start=FY27[0], entries=entries)
    exp = _row(year, "exp")
    assert exp["period_debit_paise"] == 2_000_00 + 9_00
    assert exp["period_credit_paise"] == 9_00
    assert year["is_balanced"]


# ── 5. cash basis refuses the period and says why ────────────────────────────

def test_cash_basis_refuses_a_period_and_names_the_reason():
    out = _tb(start=FY27[0], basis="cash")
    assert "period_gap" in out, "silently widening the window is the thing not to do"
    assert "counting those settlements twice" in out["period_gap"]
    assert "start_date" not in out, "and it must not claim to be a period report"
    for row in out["lines"]:
        assert "opening_debit_paise" not in row


def test_cash_basis_without_a_period_is_unchanged():
    out = _tb(basis="cash")
    assert "period_gap" not in out
    assert out.get("basis") == "cash"
