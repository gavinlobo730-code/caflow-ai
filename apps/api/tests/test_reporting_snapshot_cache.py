"""
Per-request snapshot memoization in SupabaseLedgerSource (performance hardening #2).

The date-independent base fetch (accounts, entries, invoices, receipts, …) is now
cached per source instance, so multiple snapshot() calls within ONE request — e.g.
cash_flow_statement calls snapshot() 3× with different date windows — hit the DB
only once. A fresh source is created per request, so there is no cross-request
staleness. This verifies the base is fetched once across two snapshot() calls.
"""
from domain.reporting.sources import SupabaseLedgerSource


class _Chain:
    """Chainable query stub: any builder method returns self; execute → empty."""
    def __getattr__(self, _name):
        return self
    def __call__(self, *a, **k):
        return self
    def execute(self):
        return type("R", (), {"data": [], "count": 0})()


class _CountingDB:
    def __init__(self):
        self.table_calls = 0
    def table(self, _name):
        self.table_calls += 1
        return _Chain()


def test_snapshot_memoizes_base_fetch_within_instance():
    db = _CountingDB()
    src = SupabaseLedgerSource(db)

    src.snapshot("FIRM", "CLI", "2025-04-01", "2026-03-31")
    after_first = db.table_calls
    assert after_first > 0                       # the first call does fetch

    # A second snapshot with a DIFFERENT date window must reuse the cached base.
    src.snapshot("FIRM", "CLI", None, "2026-03-31")
    assert db.table_calls == after_first         # no additional DB fetches


def test_new_instance_refetches():
    db = _CountingDB()
    SupabaseLedgerSource(db).snapshot("FIRM", "CLI", None, "2026-03-31")
    first = db.table_calls
    # A fresh instance (= a new request) must fetch again — no cross-request cache.
    SupabaseLedgerSource(db).snapshot("FIRM", "CLI", None, "2026-03-31")
    assert db.table_calls == first * 2
