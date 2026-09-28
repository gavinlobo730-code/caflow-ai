"""The departmental result is a GROUP BY in the database, not every posted
Income/Expense line of the FY paged into Python and summed there
(apex-accounting-reports-13).

WHAT THIS FILE IS FOR

    `services/cost_centre_service.allocation`'s own docstring used to promise
    the read was bounded to "only lines that CARRY a centre", and the query it
    ran carried NO such filter at all — so a client with zero cost centres
    defined still keyset-paged every posted Income/Expense line of the
    financial year. A SEPARATE, real correctness bug rode along with it: the
    query filtered `chart_of_accounts.account_type IN ('Income', 'Expense')`,
    and this schema's CHECK constraint (migration 003) has never permitted
    'Income' — only 'Revenue' — so no revenue line ever reached a
    departmental result.

    This is the `test_cash_flow_sql_routing.py` shape, applied to
    `cost_centre_allocation` (migration 435): it proves the SERVICE asks the
    database for the grouped answer with the right arguments, never reads
    `journal_lines` when the function answers, degrades to the old per-line
    fetch when the function errors, and short-circuits before any database
    read at all when the client has no cost centres. The SQL function's own
    correctness (the GROUP BY, the RLS restatement) needs a real Postgres and
    is exercised by hand against a local instance — this file is the
    mock-mode routing half, which is what runs in CI.
"""
from __future__ import annotations

import pytest

from services import cost_centre_service as svc

FIRM, CLIENT, FY = "firm-cc", "client-cc", "2026-27"

CENTRE_ROWS = [
    {"id": "centre-1", "firm_id": FIRM, "client_id": CLIENT, "code": "FACTORY",
     "name": "Factory", "description": None, "is_active": True, "created_at": "2026-04-01"},
]

ALLOCATION_ROWS = [
    {"cost_centre_id": "centre-1", "account_id": "acct-sales", "account_name": "Sales",
     "account_type": "Revenue", "debit_paise": 0, "credit_paise": 100000},
    {"cost_centre_id": None, "account_id": "acct-salaries", "account_name": "Salaries",
     "account_type": "Expense", "debit_paise": 40000, "credit_paise": 0},
]


class _Res:
    def __init__(self, data):
        self.data = data


class _Query:
    """A single table's query builder. Every chain method returns self except
    `execute`, which answers the table's own canned page — enough for
    `core.db_paging.fetch_all`'s `.eq(...).gt(...).order(...).limit(...)
    .execute()` walk to terminate on the first (short) page."""

    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def gt(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def lte(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def execute(self): return _Res(self._rows)


class _Call:
    def __init__(self, fn, params, data, raises):
        self.fn, self.params, self._data, self._raises = fn, params, data, raises

    def execute(self):
        if self._raises:
            raise self._raises
        return _Res(self._data)


class _DB:
    """The RPC surface plus `cost_centres` (for list_centres). Any read of
    `journal_lines` means the SQL function should have answered this and did
    not — the point of migration 435."""

    def __init__(self, *, centres=CENTRE_ROWS, alloc_data=ALLOCATION_ROWS,
                 alloc_raises=None, allow_journal_lines=False):
        self.rpc_calls: list[_Call] = []
        self._centres = centres
        self._alloc_data = alloc_data
        self._alloc_raises = alloc_raises
        self._allow_journal_lines = allow_journal_lines
        self.journal_lines_reads = 0

    def rpc(self, fn, params=None):
        c = _Call(fn, params or {}, self._alloc_data, self._alloc_raises)
        self.rpc_calls.append(c)
        return c

    def table(self, name):
        if name == "cost_centres":
            return _Query(self._centres)
        if name == "journal_lines":
            self.journal_lines_reads += 1
            if not self._allow_journal_lines:
                raise AssertionError(
                    "read journal_lines — cost_centre_allocation should have "
                    "answered this in the database")
            return _Query([])
        raise AssertionError(f"unexpected table read: {name!r}")


# ── It asks the database for the grouped answer ──────────────────────────────

def test_the_allocation_comes_from_the_sql_function():
    db = _DB()
    out = svc.allocation(db, FIRM, CLIENT, FY)
    assert [c.fn for c in db.rpc_calls] == ["cost_centre_allocation"]
    assert out.centres[0].cost_centre_id == "centre-1"
    assert out.centres[0].income_paise == 100000
    assert out.unallocated is not None
    assert out.unallocated.expense_paise == 40000


def test_it_is_called_with_the_clients_own_scope_and_fy_window():
    db = _DB()
    svc.allocation(db, FIRM, CLIENT, FY)
    p = db.rpc_calls[0].params
    assert p["p_firm"] == FIRM
    assert p["p_client"] == CLIENT
    assert p["p_start"] == "2026-04-01"
    assert p["p_end"] == "2027-03-31"


def test_no_journal_line_is_read_when_the_function_answers():
    """The point of migration 435. A GROUP BY in the database replaced a fetch
    that scaled with the ledger; any journal_lines read here means those rows
    are still crossing the wire."""
    db = _DB()
    svc.allocation(db, FIRM, CLIENT, FY)
    assert db.journal_lines_reads == 0


def test_revenue_reaches_the_result_not_only_expense():
    """The separate correctness bug: the account_type filter used to be
    ('Income', 'Expense'), and 'Income' has never been a legal value in this
    schema — so a revenue line's account_type ('Revenue') always failed the
    old lowercase '== income' comparison and was silently dropped. Proven
    here on the SQL function's own returned rows, not on the query filter,
    since the filter now lives in the database."""
    db = _DB()
    out = svc.allocation(db, FIRM, CLIENT, FY)
    assert out.centres[0].income_paise == 100000, (
        "a 'Revenue' row from cost_centre_allocation must be read as income")


# ── Short-circuit when there are no cost centres ─────────────────────────────

def test_a_client_with_no_cost_centres_never_touches_the_database():
    """(a): no line could carry a cost centre this client has never defined —
    the picker that tags a line only offers this client's own centres — so
    there is nothing to query for."""
    db = _DB(centres=[])
    out = svc.allocation(db, FIRM, CLIENT, FY)
    assert out.centres == ()
    assert out.unallocated is None
    assert db.rpc_calls == []
    assert db.journal_lines_reads == 0


# ── And copes when the function cannot answer ────────────────────────────────

def test_a_failing_function_degrades_to_the_per_line_fetch():
    """The cash_flow_report contract, applied here: a fast path that errors
    produces a slow answer, never an error and never a wrong number."""
    db = _DB(alloc_raises=RuntimeError("function missing"), allow_journal_lines=True)
    out = svc.allocation(db, FIRM, CLIENT, FY)
    assert [c.fn for c in db.rpc_calls] == ["cost_centre_allocation"], "it tried the function first"
    assert db.journal_lines_reads == 1, "then fell back to the per-line fetch"
    # No lines in the fallback fixture — an empty-but-not-erroring Allocation.
    assert out.centres == ()


@pytest.mark.parametrize("bad", [None, "oops", {"not": "a list"}])
def test_anything_but_a_list_is_a_failure_not_an_answer(bad):
    db = _DB(alloc_data=bad, allow_journal_lines=True)
    out = svc.allocation(db, FIRM, CLIENT, FY)
    assert db.journal_lines_reads == 1, "a malformed function result must fall back, not be rendered"


# ── Mock mode (no database) is untouched ─────────────────────────────────────

def test_mock_mode_still_answers_with_no_database():
    out = svc.allocation(None, FIRM, CLIENT, FY)
    assert out.centres == ()
    assert out.unallocated is None
