"""
Year-end financial statement generation — Balance Sheet carry-forward
regression tests (F10, Tier 2 R2.1).

services.year_end_financial_service.generate_financial_statements previously
applied the FY date window to every account uniformly, which is correct for
P&L (income/expense) accounts but wrong for Balance Sheet (asset/liability/
equity) accounts -- those carry a CUMULATIVE balance across every prior year,
not just the current FY's movement. A multi-year client's Balance Sheet
silently dropped all prior-year carry-forward.

A minimal purpose-built Supabase-client stub is used here (not the shared
FakeDB in e2e_harness.py) because this function issues PostgREST embedded-
resource queries (journal_lines select with a `journal_entries!inner(...)`
join filtered via dotted keys like "journal_entries.entry_date") that FakeDB
does not implement.
"""
import pytest

import services.year_end_financial_service as yefs
from services.year_end_financial_service import generate_financial_statements

FIRM = "firm-1"
CLIENT = "client-1"


@pytest.fixture(autouse=True)
def _force_real_db_path(monkeypatch):
    """This module's mock branch (_USE_MOCK) returns canned demo figures --
    force the real (DB-driven) aggregation path under test, using the stub
    Supabase client instead of an actual database."""
    monkeypatch.setattr(yefs, "_USE_MOCK", False)


class _Query:
    def __init__(self, rows, filters=None):
        self._rows = rows
        self._filters = filters or {}

    def select(self, *_a, **_k):
        return self

    def eq(self, key, val):
        f = dict(self._filters)
        f[("eq", key)] = val
        return _Query(self._rows, f)

    def gte(self, key, val):
        f = dict(self._filters)
        f[("gte", key)] = val
        return _Query(self._rows, f)

    def lte(self, key, val):
        f = dict(self._filters)
        f[("lte", key)] = val
        return _Query(self._rows, f)

    def gt(self, key, val):
        f = dict(self._filters)
        f[("gt", key)] = val
        return _Query(self._rows, f)

    def is_(self, key, val):
        f = dict(self._filters)
        f[("is_", key)] = val
        return _Query(self._rows, f)

    def order(self, *_a, **_k):
        # No-op — _fetch_lines' keyset pagination only needs .order()/.limit()
        # not to crash; this fixture's row count never exceeds a single page.
        return self

    def limit(self, *_a, **_k):
        return self

    def _get(self, row, dotted_key):
        # "journal_entries.entry_date" -> row["journal_entries"]["entry_date"];
        # a bare key ("firm_id") reads directly off the row.
        if "." in dotted_key:
            _, field = dotted_key.split(".", 1)
            return row.get("journal_entries", {}).get(field)
        return row.get(dotted_key)

    def execute(self):
        out = list(self._rows)
        for (kind, key), val in self._filters.items():
            if kind == "eq":
                out = [r for r in out if self._get(r, key) == val]
            elif kind == "gte":
                out = [r for r in out if self._get(r, key) >= val]
            elif kind == "lte":
                out = [r for r in out if self._get(r, key) <= val]
            elif kind == "gt":
                out = [r for r in out if self._get(r, key) > val]
            elif kind == "is_":
                out = [r for r in out if self._get(r, key) is None]
        return type("Result", (), {"data": out})()


class StubSupabase:
    """journal_lines + account_group_mappings only — everything this service touches."""

    def __init__(self, journal_lines, mappings):
        self._journal_lines = journal_lines
        self._mappings = mappings

    def table(self, name):
        if name == "journal_lines":
            return _Query(self._journal_lines)
        if name == "account_group_mappings":
            return _Query(self._mappings)
        raise AssertionError(f"unexpected table: {name}")


def _line(account_id, debit, credit, entry_date, client_id=CLIENT, firm_id=FIRM, posted=True):
    return {
        "account_id": account_id,
        "debit_paise": debit,
        "credit_paise": credit,
        "journal_entries": {
            "client_id": client_id, "firm_id": firm_id,
            "entry_date": entry_date, "is_posted": posted,
        },
    }


_RETAINED = {"account_id": "retained", "firm_id": FIRM,
             "schedule_line": "reserves_and_surplus", "normal_balance": "credit"}

_MAPPINGS = [
    {"account_id": "bank", "firm_id": FIRM, "schedule_line": "cash_and_bank", "normal_balance": "debit"},
    {"account_id": "capital", "firm_id": FIRM, "schedule_line": "share_capital", "normal_balance": "credit"},
    {"account_id": "revenue", "firm_id": FIRM, "schedule_line": "revenue_from_operations", "normal_balance": "credit"},
    {"account_id": "expense", "firm_id": FIRM, "schedule_line": "other_expenses", "normal_balance": "debit"},
]


def test_balance_sheet_carries_forward_prior_year_balance():
    """The core F10 bug: a Year-1-only posting to a BS account (bank/capital)
    must still appear in Year 2's statements, even with zero Year-2 activity."""
    lines = [
        _line("bank", 10_000_00, 0, "2023-06-01"),      # FY23-24 capital introduction
        _line("capital", 0, 10_000_00, "2023-06-01"),
    ]
    stub = StubSupabase(lines, _MAPPINGS)

    stmts = generate_financial_statements(
        stub, CLIENT, FIRM, fy_start="2024-04-01", fy_end="2025-03-31",  # FY24-25, no new activity
    )

    assert stmts["balance_sheet"]["assets"]["cash_and_bank"] == 10_000_00
    assert stmts["balance_sheet"]["equity_and_liabilities"]["share_capital"] == 10_000_00
    assert stmts["balance_sheet"]["is_balanced"] is True


def test_profit_and_loss_stays_fy_windowed():
    """P&L must NOT carry forward -- a prior year's revenue/expense must not
    leak into a later year's P&L (only the CURRENT year's movement counts).
    Revenue == expense (PBT/PAT = 0) so the sheet balances trivially without
    entangling this assertion with the PAT-to-reserves mechanics tested
    elsewhere."""
    lines = [
        _line("bank", 20_000_00, 0, "2020-01-01"),
        _line("capital", 0, 20_000_00, "2020-01-01"),
        _line("revenue", 0, 100_000_00, "2023-06-01"),   # FY23-24 revenue — must be excluded
        _line("expense", 50_000_00, 0, "2024-06-01"),    # FY24-25 expense — must be included
        _line("revenue", 0, 50_000_00, "2024-06-01"),    # FY24-25 revenue — must be included
    ]
    stub = StubSupabase(lines, _MAPPINGS)

    stmts = generate_financial_statements(
        stub, CLIENT, FIRM, fy_start="2024-04-01", fy_end="2025-03-31",
    )

    assert stmts["profit_loss"]["income"]["revenue_from_operations"] == 50_000_00
    assert stmts["profit_loss"]["expenses"]["other_expenses"] == 50_000_00
    assert stmts["profit_loss"]["profit_after_tax_paise"] == 0


def test_balance_sheet_reflects_current_year_movement_too():
    """Cumulative means prior-year-inclusive, not prior-year-only: a BS
    account with BOTH a prior-year and current-year posting must sum both."""
    lines = [
        _line("bank", 10_000_00, 0, "2023-06-01"),   # FY23-24
        _line("bank", 5_000_00, 0, "2024-09-01"),    # FY24-25
        _line("capital", 0, 15_000_00, "2023-06-01"),
    ]
    stub = StubSupabase(lines, _MAPPINGS)

    stmts = generate_financial_statements(
        stub, CLIENT, FIRM, fy_start="2024-04-01", fy_end="2025-03-31",
    )

    assert stmts["balance_sheet"]["assets"]["cash_and_bank"] == 15_000_00


def test_cross_client_and_cross_firm_lines_excluded():
    """Regression lock: another client's or firm's postings must never bleed
    into this statement, cumulative window or not."""
    lines = [
        _line("bank", 10_000_00, 0, "2023-06-01"),
        _line("capital", 0, 10_000_00, "2023-06-01"),
        _line("bank", 99_999_00, 0, "2023-06-01", client_id="other-client"),
        _line("bank", 88_888_00, 0, "2023-06-01", firm_id="other-firm"),
        _line("bank", 77_777_00, 0, "2020-01-01", posted=False),  # unposted draft
    ]
    stub = StubSupabase(lines, _MAPPINGS)

    stmts = generate_financial_statements(
        stub, CLIENT, FIRM, fy_start="2024-04-01", fy_end="2025-03-31",
    )

    assert stmts["balance_sheet"]["assets"]["cash_and_bank"] == 10_000_00


# ── Tax expense is READ from the ledger, never invented ──────────────────────
#
# The statement used to strike `tax = max(0, pbt * 25 // 100)`: a flat 25% of
# book profit, which is not any Indian rate. A company pays 30%, or 22% under
# §115BAA, or 15% under §115BAB, each plus surcharge and 4% cess, with MAT
# under §115JB where it applies; a proprietorship's profit is taxed in the
# PROPRIETOR's hands at individual slabs and is no charge on the business at
# all. Struck from BOOK profit it carried none of the disallowances,
# depreciation differences or regime choices that make a real figure.
#
# And it did not stop at its own line: PAT closes into reserves, so the
# balance sheet's equity inherited the invention too.

_TAX_MAPPINGS = _MAPPINGS + [
    {"account_id": "tax", "firm_id": FIRM, "schedule_line": "current_tax",
     "normal_balance": "debit"},
    {"account_id": "dtax", "firm_id": FIRM, "schedule_line": "deferred_tax",
     "normal_balance": "debit"},
]


def test_no_tax_is_charged_when_none_is_provided_for():
    """A stated nil a CA can act on, instead of a plausible number they cannot
    tell apart from a real one."""
    lines = [
        _line("bank", 100_000_00, 0, "2024-06-01"),
        _line("revenue", 0, 100_000_00, "2024-06-01"),
    ]
    stmts = generate_financial_statements(
        StubSupabase(lines, _MAPPINGS), CLIENT, FIRM,
        fy_start="2024-04-01", fy_end="2025-03-31",
    )
    pl = stmts["profit_loss"]
    assert pl["profit_before_tax_paise"] == 100_000_00
    assert pl["tax_expense_paise"] == 0, (
        "a tax charge was invented from book profit — no Indian rate is a flat "
        "percentage of PBT"
    )
    assert pl["profit_after_tax_paise"] == 100_000_00
    assert pl["tax_expense_is_provided"] is False


def test_the_provided_tax_charge_is_the_ledgers_own():
    """Schedule III Part II item VII — for a company that has provided for
    tax, current and deferred tax are posted GL figures like any other line."""
    lines = [
        _line("bank", 100_000_00, 0, "2024-06-01"),
        _line("revenue", 0, 100_000_00, "2024-06-01"),
        _line("tax", 22_000_00, 0, "2025-03-31"),     # §115BAA 22% provision
        _line("bank", 0, 22_000_00, "2025-03-31"),
    ]
    stmts = generate_financial_statements(
        StubSupabase(lines, _TAX_MAPPINGS), CLIENT, FIRM,
        fy_start="2024-04-01", fy_end="2025-03-31",
    )
    pl = stmts["profit_loss"]
    assert pl["current_tax_paise"] == 22_000_00
    assert pl["tax_expense_paise"] == 22_000_00
    assert pl["profit_after_tax_paise"] == 100_000_00 - 22_000_00
    assert pl["tax_expense_is_provided"] is True


def test_a_real_tax_provision_is_not_charged_twice():
    """The double-count. "Tax Expense" was mapped to other_expenses, so a real
    provision reduced PBT as an operating cost AND was then taxed again at
    25%. Tax must not appear inside profit BEFORE tax."""
    lines = [
        _line("bank", 100_000_00, 0, "2024-06-01"),
        _line("revenue", 0, 100_000_00, "2024-06-01"),
        _line("tax", 22_000_00, 0, "2025-03-31"),
        _line("bank", 0, 22_000_00, "2025-03-31"),
    ]
    stmts = generate_financial_statements(
        StubSupabase(lines, _TAX_MAPPINGS), CLIENT, FIRM,
        fy_start="2024-04-01", fy_end="2025-03-31",
    )
    pl = stmts["profit_loss"]
    assert pl["profit_before_tax_paise"] == 100_000_00, (
        "the tax provision was subtracted inside profit BEFORE tax"
    )
    assert pl["expenses"].get("other_expenses", 0) == 0, (
        "tax is a Schedule III item of its own, not an operating expense"
    )


def test_deferred_tax_is_its_own_schedule_iii_line():
    lines = [
        _line("bank", 100_000_00, 0, "2024-06-01"),
        _line("revenue", 0, 100_000_00, "2024-06-01"),
        _line("tax", 20_000_00, 0, "2025-03-31"),
        _line("dtax", 3_000_00, 0, "2025-03-31"),
        _line("bank", 0, 23_000_00, "2025-03-31"),
    ]
    stmts = generate_financial_statements(
        StubSupabase(lines, _TAX_MAPPINGS), CLIENT, FIRM,
        fy_start="2024-04-01", fy_end="2025-03-31",
    )
    pl = stmts["profit_loss"]
    assert pl["current_tax_paise"] == 20_000_00
    assert pl["deferred_tax_paise"] == 3_000_00
    assert pl["tax_expense_paise"] == 23_000_00


def test_a_tax_write_back_keeps_its_sign():
    """A credit balance on the tax line is a write-back of an over-provision —
    legitimate, and it INCREASES profit after tax. The old max(0, ...) floor
    could never express it."""
    lines = [
        _line("bank", 100_000_00, 0, "2024-06-01"),
        _line("revenue", 0, 100_000_00, "2024-06-01"),
        _line("tax", 0, 5_000_00, "2025-03-31"),
        _line("bank", 5_000_00, 0, "2025-03-31"),
    ]
    stmts = generate_financial_statements(
        StubSupabase(lines, _TAX_MAPPINGS), CLIENT, FIRM,
        fy_start="2024-04-01", fy_end="2025-03-31",
    )
    pl = stmts["profit_loss"]
    assert pl["tax_expense_paise"] == -5_000_00
    assert pl["profit_after_tax_paise"] == 100_000_00 + 5_000_00


# ── Previous-year comparatives (Schedule III General Instructions para 5) ────
#
# "except in the case of the first Financial Statements laid before the
# Company after incorporation, the corresponding amounts (comparatives) for
# the immediately preceding reporting period for all items shown in the
# Financial Statements including notes shall also be given."
#
# There was no prior-period field at any layer: the service returned one
# {line: paise} dict per section, the PDF printed two columns, and the web
# table headed them "Particulars | Amount". A one-column balance sheet is not
# a Schedule III financial statement — it cannot be laid before members,
# attached to AOC-4, or given to an auditor.
#
# These fixtures keep each year's revenue equal to its expense (so profit is
# nil and the sheet balances trivially), following the convention
# test_profit_and_loss_stays_fy_windowed already established: it keeps these
# assertions clear of the PAT-to-reserves mechanics, which are a separate and
# still-open problem for multi-year clients.


def test_the_preceding_period_is_reported_beside_the_current_one():
    lines = [
        _line("bank", 60_000_00, 0, "2023-06-01"),
        _line("capital", 0, 60_000_00, "2023-06-01"),
        # FY 2023-24 — the preceding period
        _line("revenue", 0, 40_000_00, "2023-09-01"),
        _line("expense", 40_000_00, 0, "2023-09-01"),
        # FY 2024-25 — the current period
        _line("revenue", 0, 25_000_00, "2024-09-01"),
        _line("expense", 25_000_00, 0, "2024-09-01"),
    ]
    stmts = generate_financial_statements(
        StubSupabase(lines, _MAPPINGS), CLIENT, FIRM,
        fy_start="2024-04-01", fy_end="2025-03-31",
    )
    comp = stmts["comparatives"]
    assert comp is not None, "no comparative column was produced"
    assert (comp["fy_start"], comp["fy_end"]) == ("2023-04-01", "2024-03-31")

    # Each column shows its own year's revenue, not the other's.
    assert comp["profit_loss"]["income"]["revenue_from_operations"] == 40_000_00
    assert stmts["profit_loss"]["income"]["revenue_from_operations"] == 25_000_00
    assert comp["profit_loss"]["expenses"]["other_expenses"] == 40_000_00
    assert stmts["profit_loss"]["expenses"]["other_expenses"] == 25_000_00


def test_the_comparative_balance_sheet_is_cumulative_to_its_own_period_end():
    """A Balance Sheet carries forward; a P&L does not. The preceding period
    obeys the same rule — cumulative to 31 March 2024, and excluding
    everything posted after it."""
    lines = [
        _line("bank", 60_000_00, 0, "2023-06-01"),
        _line("capital", 0, 60_000_00, "2023-06-01"),
        # Current-year capital introduction — must NOT reach the comparative
        _line("bank", 15_000_00, 0, "2024-06-01"),
        _line("capital", 0, 15_000_00, "2024-06-01"),
    ]
    stmts = generate_financial_statements(
        StubSupabase(lines, _MAPPINGS), CLIENT, FIRM,
        fy_start="2024-04-01", fy_end="2025-03-31",
    )
    assert stmts["balance_sheet"]["assets"]["cash_and_bank"] == 75_000_00
    comp_bs = stmts["comparatives"]["balance_sheet"]
    assert comp_bs["assets"]["cash_and_bank"] == 60_000_00, (
        "the comparative column includes postings made after the period it "
        "reports on"
    )
    assert comp_bs["equity_and_liabilities"]["share_capital"] == 60_000_00


def test_the_first_statements_after_incorporation_carry_no_comparatives():
    """Para 5's own exception. A column of zeros would assert a preceding
    period that existed and was nil — a different claim, and a false one."""
    lines = [
        _line("bank", 10_000_00, 0, "2024-06-01"),
        _line("capital", 0, 10_000_00, "2024-06-01"),
    ]
    stmts = generate_financial_statements(
        StubSupabase(lines, _MAPPINGS), CLIENT, FIRM,
        fy_start="2024-04-01", fy_end="2025-03-31",
    )
    assert stmts["comparatives"] is None, (
        "a first-year company was given a comparative column of zeros"
    )


def test_the_comparative_period_is_the_one_immediately_preceding():
    """Not merely 'an earlier year'. A P&L posting two years back belongs to
    neither column, though the balance sheet still carries its cash."""
    lines = [
        _line("bank", 99_000_00, 0, "2022-06-01"),
        _line("capital", 0, 99_000_00, "2022-06-01"),
        _line("revenue", 0, 77_000_00, "2022-09-01"),   # FY 2022-23 — neither column
        _line("expense", 77_000_00, 0, "2022-09-01"),
        _line("revenue", 0, 40_000_00, "2023-09-01"),   # FY 2023-24 — comparative
        _line("expense", 40_000_00, 0, "2023-09-01"),
        _line("revenue", 0, 25_000_00, "2024-09-01"),   # FY 2024-25 — current
        _line("expense", 25_000_00, 0, "2024-09-01"),
    ]
    stmts = generate_financial_statements(
        StubSupabase(lines, _MAPPINGS), CLIENT, FIRM,
        fy_start="2024-04-01", fy_end="2025-03-31",
    )
    comp_pl = stmts["comparatives"]["profit_loss"]
    assert comp_pl["income"]["revenue_from_operations"] == 40_000_00, (
        "the comparative P&L is not windowed to the immediately preceding year"
    )
    assert comp_pl["income"]["revenue_from_operations"] != 77_000_00 + 40_000_00


def test_the_comparative_tax_charge_is_also_read_not_invented():
    """The comparative is struck by the same code, so the tax fix holds on
    both years rather than only the one anybody looked at."""
    lines = [
        _line("bank", 60_000_00, 0, "2023-06-01"),
        _line("capital", 0, 60_000_00, "2023-06-01"),
        _line("revenue", 0, 40_000_00, "2023-09-01"),
        _line("expense", 40_000_00, 0, "2023-09-01"),
        _line("revenue", 0, 25_000_00, "2024-09-01"),
        _line("expense", 25_000_00, 0, "2024-09-01"),
    ]
    stmts = generate_financial_statements(
        StubSupabase(lines, _MAPPINGS), CLIENT, FIRM,
        fy_start="2024-04-01", fy_end="2025-03-31",
    )
    comp_pl = stmts["comparatives"]["profit_loss"]
    assert comp_pl["tax_expense_paise"] == 0
    assert comp_pl["tax_expense_is_provided"] is False
    assert comp_pl["profit_after_tax_paise"] == comp_pl["profit_before_tax_paise"]


def test_the_comparative_reports_whether_it_balanced_rather_than_refusing():
    """The CURRENT year's imbalance still refuses — that check is unchanged.
    A PRECEDING year's is a fact about history the CA needs to see; refusing
    to render the current year over it would withhold the statements they
    came for."""
    lines = [
        _line("bank", 60_000_00, 0, "2023-06-01"),
        _line("capital", 0, 60_000_00, "2023-06-01"),
        _line("revenue", 0, 25_000_00, "2024-09-01"),
        _line("expense", 25_000_00, 0, "2024-09-01"),
    ]
    stmts = generate_financial_statements(
        StubSupabase(lines, _MAPPINGS), CLIENT, FIRM,
        fy_start="2024-04-01", fy_end="2025-03-31",
    )
    assert stmts["comparatives"]["balance_sheet"]["is_balanced"] is True


def test_one_ledger_read_serves_both_periods():
    """The comparative must not cost a second pass over the ledger. CLAUDE.md:
    no report may fetch rows proportional to transaction volume — and this
    function used to make TWO fetches for one year, so adding a whole extra
    year while going down to one is the point."""
    lines = [
        _line("bank", 10_000_00, 0, "2023-06-01"),
        _line("capital", 0, 10_000_00, "2023-06-01"),
    ]
    stub = StubSupabase(lines, _MAPPINGS)
    calls = {"journal_lines": 0}
    original = stub.table

    def counting_table(name):
        if name == "journal_lines":
            calls["journal_lines"] += 1
        return original(name)

    stub.table = counting_table
    generate_financial_statements(stub, CLIENT, FIRM,
                                  fy_start="2024-04-01", fy_end="2025-03-31")
    assert calls["journal_lines"] == 1, (
        f"the ledger was read {calls['journal_lines']} times for two periods"
    )


def test_the_prior_period_helper_shifts_both_ends_by_a_year():
    from services.year_end_financial_service import _prior_period
    assert _prior_period("2024-04-01", "2025-03-31") == ("2023-04-01", "2024-03-31")
    # A non-standard first period still gets the period actually preceding it.
    assert _prior_period("2024-07-15", "2025-03-31") == ("2023-07-15", "2024-03-31")
    # 29 February has no counterpart in the preceding year.
    assert _prior_period("2024-03-01", "2024-02-29") == ("2023-03-01", "2023-02-28")
