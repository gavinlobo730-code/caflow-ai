"""
PeriodValidationService.validate_posting_date_cached — the fix for a bulk
import calling the is_fy_locked RPC once per row (9,999 sales invoices means
9,999 RPC round trips for a lock check whose answer cannot change mid-request
for the same financial year). Must memoize per (firm, FY) and never change
what actually gets blocked.
"""
import services.period_validation_service as pvs_module
from services.period_validation_service import PeriodValidationService, get_fy_for_date


class _FakeResp:
    def __init__(self, data):
        self.data = data


class _FakeRpcQuery:
    def __init__(self, calls, fn, params, is_locked):
        self._calls = calls
        self._fn = fn
        self._params = params
        self._is_locked = is_locked

    def execute(self):
        self._calls.append((self._fn, dict(self._params)))
        return _FakeResp([self._is_locked])


class _FakeDB:
    """Locks by financial year (matching the real is_fy_locked semantics:
    every date within a locked FY is blocked, not just one literal date)."""
    def __init__(self, calls, locked_fys=frozenset()):
        self.calls = calls
        self.locked_fys = locked_fys

    def rpc(self, fn, params):
        is_locked = get_fy_for_date(params.get("p_date")) in self.locked_fys
        return _FakeRpcQuery(self.calls, fn, params, is_locked)


def _wire(monkeypatch, db):
    monkeypatch.setattr(pvs_module, "_USE_MOCK", False)
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: db)


def test_cached_calls_rpc_once_per_distinct_fy_not_per_row(monkeypatch):
    calls: list = []
    db = _FakeDB(calls)
    _wire(monkeypatch, db)
    svc = PeriodValidationService()
    cache: dict = {}

    # Three rows: two in FY 2026-27, one in FY 2025-26.
    svc.validate_posting_date_cached("firm-1", "2026-04-10", cache)
    svc.validate_posting_date_cached("firm-1", "2026-05-15", cache)
    svc.validate_posting_date_cached("firm-1", "2025-07-01", cache)

    assert len(calls) == 2  # one per distinct FY, not one per call
    assert cache == {"2026-27": True, "2025-26": True}


def test_cached_still_blocks_a_locked_fy_every_time(monkeypatch):
    calls: list = []
    db = _FakeDB(calls, locked_fys={"2026-27"})
    _wire(monkeypatch, db)
    svc = PeriodValidationService()
    cache: dict = {}

    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        svc.validate_posting_date_cached("firm-1", "2026-04-10", cache)
    # Nothing cached for a locked FY — a second row in the same locked FY
    # must still be checked (and still blocked) for real, not waved through
    # by a stale "verified open" cache entry.
    assert cache == {}
    with pytest.raises(HTTPException):
        svc.validate_posting_date_cached("firm-1", "2026-05-01", cache)
    assert len(calls) == 2


def test_cache_none_falls_back_to_uncached_behavior(monkeypatch):
    calls: list = []
    db = _FakeDB(calls)
    _wire(monkeypatch, db)
    svc = PeriodValidationService()

    svc.validate_posting_date_cached("firm-1", "2026-04-10", None)
    svc.validate_posting_date_cached("firm-1", "2026-05-15", None)

    assert len(calls) == 2  # no memoization when cache=None
