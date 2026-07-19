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
