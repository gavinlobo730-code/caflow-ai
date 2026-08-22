"""
Cash Flow asks the database for the statement, and copes when it cannot.

WHAT THIS FILE IS FOR
    tests/test_cash_flow_sql_parity_pg.py proves public.cash_flow_report computes
    the RIGHT statement. It needs a real Postgres and does not run in mock mode.
    This file proves the other half, which a double can settle: that the service
    ASKS for it, with the right arguments, and that every way of not getting an
    answer ends in the previous behaviour rather than an error or a thin one.

    Migration 277's whole value is that the classification happens where the
    rows are. A routing bug would leave that unused and nothing would look
    broken — the report would just quietly stay slow.
"""
from __future__ import annotations

import pytest

from domain.reporting import Account, JournalEntry, JournalLine, InMemoryLedgerSource, ReportingService
from domain.reporting.service import ReportingService as RS
from domain.reporting.sources import SupabaseLedgerSource

FIRM, CLIENT = "firm-cf", "client-cf"
START, END = "2026-04-01", "2027-03-31"

ACCOUNTS = [
    Account("bank", "1000", "Bank", "Asset", "Bank", system_key="bank"),
    Account("rev", "4000", "Sales", "Revenue", None),
]
ENTRIES = [JournalEntry(id="e1", entry_date="2026-06-01", client_id=CLIENT, firm_id=FIRM,
                        entry_type="Journal",
                        lines=(JournalLine("bank", 10000, 0), JournalLine("rev", 0, 10000)))]

# A complete statement, shaped as the SQL function returns one.
DOC = {
    "start_date": START, "end_date": END,
    "operating": {"label": "Cash from Operating Activities", "lines": [], "total_paise": 10000},
    "investing": {"label": "Cash from Investing Activities", "lines": [], "total_paise": 0},
    "financing": {"label": "Cash from Financing Activities", "lines": [], "total_paise": 0},
    "net_change_paise": 10000, "opening_cash_paise": 0, "closing_cash_paise": 10000,
    "reconciles": True, "non_cash_excluded_count": 0,
    "operating_reconciliation": {
        "net_profit_paise": 10000, "non_operating_adjust_paise": 0,
        "depreciation_addback_paise": 0, "working_capital_change_paise": 0,
        "net_cash_operating_paise": 10000, "ties_out": True,
    },
}


class _Res:
    def __init__(self, data): self.data = data


class _Call:
    def __init__(self, fn, params, data, raises):
        self.fn, self.params, self._data, self._raises = fn, params, data, raises

    def execute(self):
        if self._raises:
            raise self._raises
        return _Res(self._data)


class _RpcDB:
    """Only the RPC surface. Any table() read means the service went down a
    path this test says it should not have."""

    def __init__(self, data=DOC, raises=None):
        self.calls: list[_Call] = []
        self._data, self._raises = data, raises

    def rpc(self, fn, params=None):
        c = _Call(fn, params or {}, self._data, self._raises)
        self.calls.append(c)
        return c

    def table(self, name):
        raise AssertionError(f"read table {name!r} — the SQL statement should have served this")


def _svc(db):
    return RS(SupabaseLedgerSource(db))


def _inmemory():
    return ReportingService(InMemoryLedgerSource(accounts=ACCOUNTS, entries=list(ENTRIES)))


# ── It asks the database ─────────────────────────────────────────────────────

def test_the_statement_comes_from_the_sql_function():
    db = _RpcDB()
    out = _svc(db).cash_flow_statement(FIRM, CLIENT, START, END)
    assert [c.fn for c in db.calls] == ["cash_flow_report"]
    assert out == DOC


def test_it_is_called_with_the_window_and_the_clients_own_scope():
    db = _RpcDB()
    _svc(db).cash_flow_statement(FIRM, CLIENT, START, END)
    p = db.calls[0].params
    assert p == {"p_firm": FIRM, "p_client": CLIENT, "p_start": START, "p_end": END}


def test_no_table_is_read_when_the_function_answers():
    """The point of the change. A single RPC replaced a fetch that scaled with
    the ledger — 32,936 line rows for the client this was found on — so any
    table read here means those rows are still crossing the wire."""
    db = _RpcDB()
    _svc(db).cash_flow_statement(FIRM, CLIENT, START, END)   # _RpcDB.table raises
    assert len(db.calls) == 1


def test_the_cash_basis_echo_is_preserved():
    """A cash flow statement is actual cash on either basis, so the figures do
    not change — but the field is part of the response contract."""
    db = _RpcDB()
    out = _svc(db).cash_flow_statement(FIRM, CLIENT, START, END, basis="cash")
    assert out["basis"] == "cash"
    assert out["net_change_paise"] == DOC["net_change_paise"]


# ── And copes when it cannot ─────────────────────────────────────────────────

def test_no_database_uses_the_python_builder():
    """Mock mode and local dev have an in-memory source and no SQL functions at
    all. The statement must still be produced, which is why builders.cash_flow
    is kept rather than deleted."""
    out = _inmemory().cash_flow_statement(FIRM, CLIENT, START, END)
    assert out["net_change_paise"] == 10000
    assert out["operating_reconciliation"]["net_profit_paise"] == 10000


def test_a_firm_wide_report_does_not_use_the_function():
    """cash_flow_report is per-client, exactly as the passbook is. Passing NULL
    would silently return an empty statement rather than a firm-wide one."""
    db = _RpcDB()
    with pytest.raises(AssertionError, match="read table"):
        # No client → the fallback path, which reads tables. That it gets that
        # far is the assertion; _RpcDB refuses the read to prove the route.
        _svc(db).cash_flow_statement(FIRM, None, START, END)
    assert db.calls == [], "the per-client function was called for a firm-wide report"


@pytest.mark.parametrize("bad", [None, [], "oops", {"operating": {}}])
def test_anything_but_a_whole_statement_is_a_failure_not_an_answer(bad):
    """A partial document must not be rendered. Half a cash flow statement is a
    wrong cash flow statement, and the fallback exists for exactly this."""
    db = _RpcDB(data=bad)
    with pytest.raises(AssertionError, match="read table"):
        _svc(db).cash_flow_statement(FIRM, CLIENT, START, END)


def test_a_failing_function_degrades_rather_than_raising():
    """_serve's contract: a fast path that errors produces a SLOW answer, never
    an error and never a wrong number. Proved end to end against the in-memory
    builder, which is what the fallback ultimately reaches."""
    class _FallsBack(_RpcDB):
        def table(self, name):           # allow the fallback to actually run
            raise NotImplementedError(name)

    db = _FallsBack(raises=RuntimeError("function missing"))
    with pytest.raises(NotImplementedError):
        _svc(db).cash_flow_statement(FIRM, CLIENT, START, END)
    assert [c.fn for c in db.calls] == ["cash_flow_report"], "it did try the function first"
