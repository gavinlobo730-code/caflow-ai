"""
A report's cost must not scale with the size of the ledger.

THE RULE THIS ENFORCES (CLAUDE.md, "Reporting performance")
    No report may fetch rows proportional to transaction volume. What crosses
    the wire must be proportional to the size of the ANSWER, not the size of the
    books.

WHY A TEST AND NOT A NOTE
    The rule was learned the expensive way. Measured in production on one client
    with 12,836 entries / 32,936 lines: profit-loss 2.15s, trial-balance 2.06s,
    cash-flow 54.34s — same client, same request. The three fast reports read
    132 pre-aggregated monthly buckets; the slow one fetched every line and
    looped in Python, in thirteen cross-region PostgREST pages, to produce a
    document about a kilobyte long. Over that client's full history it could not
    finish inside lib/api's 45-second abort at all.

    Nothing about that was visible in any assertion. Every figure was correct.
    A report that silently costs O(ledger) passes every test of its OUTPUT, and
    is found when a CA cannot load it.

HOW IT IS MEASURED
    Behaviourally, not by reading the source. The same report runs against a
    small ledger and a 10x one — SAME accounts, SAME date span, ten times the
    entries — and the rows it pulled are counted. A report reading aggregates or
    a SQL function pulls the same number both times. A report reading raw
    entries pulls ten times as many, and that ratio is the whole assertion.

    Counting rows rather than timing anything: a clock in CI measures the
    runner's mood, and the thing that actually costs 54 seconds is rows crossing
    a region boundary.
"""
from __future__ import annotations

import pytest

from domain.reporting.balance_cache import build_buckets
from domain.reporting.service import ReportingService
from domain.reporting.sources import SupabaseLedgerSource

from tests.test_passbook_read_path import _DB, _Q, ACCOUNTS  # the Supabase-shaped fake

FIRM, CLIENT = "firm-1", "client-1"

# Same chart, same 12-month span, different transaction volume. Holding the
# accounts and the calendar fixed is what makes the comparison mean "scales with
# TRANSACTIONS" rather than "scales with anything at all".
SMALL, LARGE = 40, 400


def _entries(n: int) -> list[dict]:
    out = []
    for i in range(n):
        month = (i % 12) + 4                      # Apr..Mar, evenly spread
        y, m = (2026, month) if month <= 12 else (2027, month - 12)
        out.append({
            "id": f"e{i:05d}", "entry_date": f"{y}-{m:02d}-15", "client_id": CLIENT,
            "firm_id": FIRM, "entry_type": "Journal", "is_posted": True,
            "deleted_at": None, "reference_no": f"R{i}", "narration": "",
            "created_at": f"{y}-{m:02d}-15T00:00", "reversal_of": None,
            "journal_lines": [
                {"account_id": "bank", "debit_paise": 1000, "credit_paise": 0},
                {"account_id": "rev", "debit_paise": 0, "credit_paise": 1000},
            ],
        })
    return out


class _CountingDB(_DB):
    """Counts the rows every table read actually returned."""

    def __init__(self, store):
        super().__init__(store)
        self.rows = 0
        self.by_table: dict[str, int] = {}

    def table(self, name):
        q = _Q(self.store, name)
        outer = self

        def execute(_q=q, _n=name):
            res = _Q.execute(_q)
            outer.rows += len(res.data)
            outer.by_table[_n] = outer.by_table.get(_n, 0) + len(res.data)
            return res

        q.execute = execute      # type: ignore[method-assign]
        return q

    def rpc(self, fn, params=None):
        """The SQL reporting functions. A report served by one pulls no rows at
        all, which is the shape the rule is asking for."""
        return _RpcCall(fn)


class _RpcCall:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        if self.fn != "cash_flow_report":
            raise NotImplementedError(self.fn)
        # Shape only — this file measures the READ, not the arithmetic. Parity of
        # the figures is tests/test_cash_flow_sql_parity_pg.py's job.
        empty = {"label": "", "lines": [], "total_paise": 0}
        return type("R", (), {"data": {
            "start_date": "2026-04-01", "end_date": "2027-03-31",
            "operating": dict(empty), "investing": dict(empty), "financing": dict(empty),
            "net_change_paise": 0, "opening_cash_paise": 0, "closing_cash_paise": 0,
            "reconciles": True, "non_cash_excluded_count": 0,
            "operating_reconciliation": {
                "net_profit_paise": 0, "non_operating_adjust_paise": 0,
                "depreciation_addback_paise": 0, "working_capital_change_paise": 0,
                "net_cash_operating_paise": 0, "ties_out": True},
        }})()


def _store(n: int) -> dict:
    raw = _entries(n)
    src = SupabaseLedgerSource(_DB({"journal_entries": raw}))
    buckets = build_buckets(src._entries(FIRM, CLIENT).values())
    apb = [{"id": f"b{i:04d}", "firm_id": FIRM, "client_id": CLIENT, "account_id": aid,
            "period_month": month, "debit_paise": dr, "credit_paise": cr}
           for i, ((aid, month), (dr, cr)) in enumerate(buckets.items())]
    return {"journal_entries": raw, "chart_of_accounts": ACCOUNTS,
            "account_period_balances": apb}


def _rows_for(report, n: int) -> tuple[int, dict[str, int]]:
    db = _CountingDB(_store(n))
    svc = ReportingService(SupabaseLedgerSource(db))
    report(svc)
    return db.rows, dict(db.by_table)


REPORTS = {
    "trial_balance":  lambda s: s.trial_balance(FIRM, CLIENT, "2027-03-31"),
    "profit_loss":    lambda s: s.profit_loss(FIRM, CLIENT, "2026-04-01", "2027-03-31"),
    "balance_sheet":  lambda s: s.balance_sheet(FIRM, CLIENT, "2027-03-31"),
    "cash_flow":      lambda s: s.cash_flow_statement(FIRM, CLIENT, "2026-04-01", "2027-03-31"),
}


# ── The detector can tell the cases apart ────────────────────────────────────

def test_the_counter_sees_a_report_that_does_scale(monkeypatch):
    """Vacuity guard. Every assertion below is 'this number did not grow'; if the
    counter were blind, they would all pass on zero. The LEGACY path is the known
    O(ledger) reader — with the passbook off, trial balance replays raw history —
    so it must show the growth the fast paths must not."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "off")
    small, _ = _rows_for(REPORTS["trial_balance"], SMALL)
    large, _ = _rows_for(REPORTS["trial_balance"], LARGE)
    assert large > small * 5, (
        f"the row counter is not measuring anything: {small} -> {large} rows for a "
        f"10x ledger on the path that is known to read all of it"
    )


def test_the_ledgers_really_do_differ_in_size():
    """The other half of the vacuity guard: 10x means 10x."""
    assert len(_store(LARGE)["journal_entries"]) == 10 * len(_store(SMALL)["journal_entries"])
    # Same chart and same calendar, so the AGGREGATES do not grow — which is why
    # a report reading them is flat.
    assert len(_store(LARGE)["account_period_balances"]) == len(_store(SMALL)["account_period_balances"])


# ── The rule ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", sorted(REPORTS))
def test_a_report_does_not_read_more_because_the_ledger_is_bigger(monkeypatch, name):
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    small, small_by = _rows_for(REPORTS[name], SMALL)
    large, large_by = _rows_for(REPORTS[name], LARGE)

    # Ten times the entries. Anything reading them shows it; a small constant of
    # slack allows for a metadata row or two without allowing linear growth.
    assert large <= small + 50, (
        f"{name} read {small} rows over {SMALL} entries and {large} over {LARGE} — "
        f"it is paying for transaction volume.\n"
        f"  small: {small_by}\n  large: {large_by}\n"
        f"Read a trigger-maintained aggregate or a SQL function that aggregates "
        f"server-side (CLAUDE.md, 'Reporting performance')."
    )


@pytest.mark.parametrize("name", sorted(REPORTS))
def test_a_report_never_reads_the_raw_lines_table(monkeypatch, name):
    """journal_lines is the table whose row count IS the transaction volume —
    32,936 rows for the client that found this. Reading it at all, at any size,
    is the shape the rule forbids."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    _, by_table = _rows_for(REPORTS[name], LARGE)
    assert by_table.get("journal_lines", 0) == 0, f"{name} read journal_lines directly"


def test_cash_flow_reads_nothing_at_all(monkeypatch):
    """The one this rule was written for. Migration 277 moved the AS-3
    classification into public.cash_flow_report, so the statement is one call and
    no table read — down from 32,936 rows in thirteen cross-region pages."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    rows, by_table = _rows_for(REPORTS["cash_flow"], LARGE)
    assert rows == 0, f"cash flow still reads tables: {by_table}"
