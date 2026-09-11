"""A year-end Balance Sheet of zeros that certified it balanced.

`generate_financial_statements` decided each account's Schedule III line by
reading `account_group_mappings`, and sent every account it did not find there
to `other_current_assets`:

    mapping = mapping_lookup.get(acct_id)
    if not mapping:
        schedule_line  = "other_current_assets"   # <- a Balance Sheet line
        normal_balance = "debit"

MEASURED ON PRODUCTION, THAT TABLE HOLDS ZERO ROWS. It is written only by
`GET /api/year-end/mappings/defaults` on routers/year_end_mappings.py, which no
screen has ever called. So every account took that branch, and the consequence
is arithmetic rather than cosmetic: with the whole ledger on one debit-normal
line, the balance sheet's asset side comes to Σ(debit − credit) over every
account — which for a balanced ledger is NIL. Total assets 0, total equity and
liabilities 0, revenue 0, every expense 0.

And the function's own guard — `total_assets == total_equity_and_liabilities`,
which raises ValueError when it fails — PASSES on 0 == 0. The one check that
existed confirmed the wrong answer.

Meanwhile `chart_of_accounts` held 133 accounts, 50 of them carrying a
`schedule_iii_mapping` the CA had recorded by hand on /accounting/schedule-iii.
The classification is now DERIVED from the account by
`domain.reporting.year_end_lines.schedule_line_for_account` — the same function
the mappings router uses, over the same Schedule III vocabulary the live Balance
Sheet classifies with — and a stored mapping row overrides it where a firm has
recorded one.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]


# ── The ledger the stub serves ───────────────────────────────────────────────
# A balanced set of books: capital 10,00,000 Cr, bank 10,00,000 Dr, sales
# 5,00,000 Cr, receivables 5,00,000 Dr. Nothing exotic — the point is that a
# perfectly ordinary trial balance produced a statement of zeros.

_ACCOUNTS = [
    {"id": "A-CAP",  "account_type": "Equity",    "account_subtype": "Share Capital",
     "schedule_iii_mapping": None},
    {"id": "A-BANK", "account_type": "Asset",     "account_subtype": "Bank Account",
     "schedule_iii_mapping": None},
    {"id": "A-SALE", "account_type": "Revenue",   "account_subtype": "Sales",
     "schedule_iii_mapping": None},
    {"id": "A-DEB",  "account_type": "Asset",     "account_subtype": "Trade Receivables",
     "schedule_iii_mapping": None},
]

_LINES = [
    # id, account, debit, credit, date
    ("L1", "A-CAP",  0,           10_00_000_00, "2026-04-01"),
    ("L2", "A-BANK", 10_00_000_00, 0,           "2026-04-01"),
    ("L3", "A-DEB",  5_00_000_00,  0,           "2026-06-15"),
    ("L4", "A-SALE", 0,            5_00_000_00, "2026-06-15"),
]


class _Books:
    """Answers the three tables generate_financial_statements reads.

    `mappings` is what `account_group_mappings` returns — [] is production.
    `accounts` is the chart of accounts.
    """

    def __init__(self, mappings=None, accounts=None):
        self.mappings = mappings if mappings is not None else []
        self.accounts = accounts if accounts is not None else _ACCOUNTS
        self.tables_read: list[str] = []

    # — query builder —
    def table(self, name):
        self._t = name
        self.tables_read.append(name)
        return self

    def select(self, *a, **k): return self
    def eq(self, *a, **k):     return self
    def is_(self, *a, **k):    return self
    def lte(self, *a, **k):    return self
    def gte(self, *a, **k):    return self
    def gt(self, *a, **k):     return self
    def in_(self, *a, **k):    return self
    def or_(self, *a, **k):    return self
    def order(self, *a, **k):  return self
    def limit(self, *a, **k):  return self

    def execute(self):
        if self._t == "journal_lines":
            return type("R", (), {"data": [
                {"id": lid, "journal_entry_id": lid, "account_id": acct,
                 "debit_paise": dr, "credit_paise": cr,
                 "journal_entries": {"entry_date": d}}
                for lid, acct, dr, cr, d in _LINES
            ]})()
        if self._t == "account_group_mappings":
            return type("R", (), {"data": list(self.mappings)})()
        if self._t == "chart_of_accounts":
            return type("R", (), {"data": list(self.accounts)})()
        return type("R", (), {"data": []})()


def _statements(books: _Books) -> dict:
    """The LIVE branch. `_USE_MOCK` is on in the test suite (no SUPABASE_URL),
    and the mock branch returns a fixed document without reading anything — so
    a test that did not turn it off would assert against a constant and pass
    whatever the real code did."""
    import unittest.mock as m
    import services.year_end_financial_service as mod

    with m.patch.object(mod, "_USE_MOCK", False):
        return mod.generate_financial_statements(
            books, client_id="C1", firm_id="F1",
            fy_start="2026-04-01", fy_end="2027-03-31")


def _bs(doc: dict) -> dict:
    """The current period's balance sheet, whatever the envelope calls it."""
    for key in ("balance_sheet", "current"):
        if key in doc:
            inner = doc[key]
            return inner.get("balance_sheet", inner) if isinstance(inner, dict) else inner
    return doc


# ── The defect ───────────────────────────────────────────────────────────────

def test_a_firm_with_no_mapping_rows_still_gets_a_real_balance_sheet():
    """THE ONE THAT FAILS AGAINST THE OLD CODE. No account_group_mappings row
    exists — production's actual state — and the statements must still be the
    books, not zeros."""
    doc = _statements(_Books(mappings=[]))
    bs = _bs(doc)

    total_assets = bs["total_assets_paise"]
    total_eq_lib = bs["total_equity_and_liabilities_paise"]

    assert total_assets == 15_00_000_00, (
        f"total assets {total_assets} — the ledger has ₹10,00,000 of bank and "
        f"₹5,00,000 of receivables. Zero here is the whole defect: every "
        f"account landed on one debit-normal line and the sides cancelled.")
    assert total_eq_lib == 15_00_000_00, total_eq_lib
    assert total_assets == total_eq_lib


def test_the_accounts_land_on_their_own_schedule_iii_lines():
    """Not merely non-zero — on the RIGHT lines. Share capital is equity, a
    bank account is cash, a debtor is a receivable, a sale is revenue."""
    doc = _statements(_Books(mappings=[]))
    bs = _bs(doc)
    assets = bs.get("assets", {})
    eq_lib = bs.get("equity_and_liabilities", {})

    assert assets.get("cash_and_bank") == 10_00_000_00, assets
    assert assets.get("trade_receivables") == 5_00_000_00, assets
    assert eq_lib.get("share_capital") == 10_00_000_00, eq_lib
    # The sale is income, so it reaches the balance sheet only through the
    # surplus carried into reserves — never as an asset.
    assert assets.get("other_current_assets", 0) == 0, (
        "something is still being dumped on other_current_assets, which is "
        "the fallback this replaced")


def test_the_profit_and_loss_is_not_nil():
    doc = _statements(_Books(mappings=[]))
    pl = doc.get("profit_loss") or doc.get("current", {}).get("profit_loss") or {}
    income = pl.get("income", pl)
    revenue = income.get("revenue_from_operations")
    assert revenue == 5_00_000_00, (
        f"revenue {revenue} — the whole P&L was nil because every revenue "
        f"account was classified as a current asset")


def test_a_stored_mapping_row_still_wins():
    """The table is an OVERRIDE now, not the only source. A firm that has
    recorded a decision keeps it — otherwise this fix would silently discard
    exactly the data it is meant to respect."""
    doc = _statements(_Books(mappings=[
        {"account_id": "A-DEB", "schedule_line": "short_term_loans_and_advances",
         "normal_balance": "debit"},
    ]))
    assets = _bs(doc).get("assets", {})
    assert assets.get("short_term_loans_and_advances") == 5_00_000_00, assets
    assert assets.get("trade_receivables", 0) == 0, (
        "the stored mapping was ignored and the derived line used instead")


def test_the_ca_s_own_schedule_iii_mapping_reaches_the_year_end_statements():
    """ACC-10, arriving here. `schedule_iii_mapping` is the CA's decision, made
    on /accounting/schedule-iii, and production has it on 50 accounts. It must
    outrank the subtype scan — a 'Fixed Deposit' subtype the CA has marked
    Long-term Investments is a long-term investment."""
    doc = _statements(_Books(mappings=[], accounts=[
        {"id": "A-CAP",  "account_type": "Equity", "account_subtype": "Share Capital",
         "schedule_iii_mapping": None},
        {"id": "A-BANK", "account_type": "Asset",  "account_subtype": "Bank Account",
         "schedule_iii_mapping": "Long-term Investments"},
        {"id": "A-SALE", "account_type": "Revenue", "account_subtype": "Sales",
         "schedule_iii_mapping": None},
        {"id": "A-DEB",  "account_type": "Asset",  "account_subtype": "Trade Receivables",
         "schedule_iii_mapping": None},
    ]))
    assets = _bs(doc).get("assets", {})
    assert assets.get("long_term_investments") == 10_00_000_00, assets
    assert assets.get("cash_and_bank", 0) == 0, (
        "the CA's schedule_iii_mapping was ignored and the subtype scan used")


def test_the_chart_of_accounts_is_read_not_the_accounts_view():
    """`public.accounts` is `SELECT *` frozen at migration 016 and does NOT
    carry `schedule_iii_mapping` (migration 057) — Postgres expands a view's
    star at creation and freezes it. Reading the view would silently drop the
    CA's decision on every account: the same defect by a different route, and
    invisible, because the query succeeds and the column is simply absent.

    Asserted on the SOURCE with comments and docstrings stripped, because both
    table names appear in the prose that explains this."""
    src = (API_ROOT / "services" / "year_end_financial_service.py").read_text()
    code = re.sub(r"#[^\n]*", "", src)
    code = re.sub(r'"""[\s\S]*?"""', "", code)
    assert 'table("chart_of_accounts")' in code
    assert 'table("accounts")' not in code


def test_the_fallback_to_other_current_assets_is_no_longer_the_normal_path():
    """It survives for an account id with no chart_of_accounts row at all — a
    journal line against a deleted or foreign account — so the statement still
    foots rather than dropping the figure. What it must NOT be is where an
    ordinary account lands."""
    books = _Books(mappings=[], accounts=[])   # no chart rows at all
    doc = _statements(books)
    assets = _bs(doc).get("assets", {})
    assert assets.get("other_current_assets") == 0, (
        "with no chart rows every account falls back, and the sides cancel to "
        "nil — which is the old behaviour, correctly reproduced here as the "
        "edge case it should now be")
    assert "chart_of_accounts" in books.tables_read, (
        "the chart of accounts was never read — the derivation is not wired in")


def test_the_accounts_read_is_bounded_by_accounts_not_by_transactions():
    """CLAUDE.md's reporting rule: what crosses the wire is proportional to the
    size of the ANSWER. The chart-of-accounts read is one query filtered to the
    account ids the ledger actually touched, not one per account and not a
    per-line join."""
    books = _Books(mappings=[])
    _statements(books)
    assert books.tables_read.count("chart_of_accounts") == 1, books.tables_read
    assert books.tables_read.count("account_group_mappings") == 1, books.tables_read
