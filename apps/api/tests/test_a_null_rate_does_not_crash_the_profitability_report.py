"""sweep-practice-hub-02: a NULL hourly_rate_paise must not 500 the report.

`entry.get("hourly_rate_paise", 0)` only substitutes 0 when the KEY IS ABSENT
from the row -- not when Postgres actually stored NULL, which is the common
case: `routers/time_tracking.py::start_timer` never writes
`hourly_rate_paise` at all, and `create_manual_entry` writes it as None
whenever no rate was typed on the /time form. `duration_minutes * None`
(get_cost_by_client, get_cost_by_engagement, get_metrics_by_team_member) and
`None > 0` (get_effort_by_engagement) both raise TypeError, and since
`routers/analytics.py`'s /profitability, /concentration and /revenue-vs-effort
endpoints call these with no try/except, a single qualifying time entry with
a NULL rate 500s the whole page.

Against the previous code every parametrized case below raises TypeError.
"""
from __future__ import annotations

import pytest

import repositories.time_tracking_analytics_repository as tta
from repositories.time_tracking_analytics_repository import time_tracking_analytics_repo


def _rows_fixture(row: dict):
    """A real SyncPostgrestClient with only the network hop replaced -- the
    same construction `test_the_time_analytics_queries_build_on_the_real_client.py`
    uses -- so `.execute()` returns exactly the given row instead of an empty list.
    """
    from postgrest import SyncPostgrestClient
    from postgrest._sync.request_builder import SyncQueryRequestBuilder

    class _Db:
        def __init__(self):
            self.client = SyncPostgrestClient("http://127.0.0.1:9/rest/v1")

        def table(self, name):
            return self.client.from_(name)

    def _no_network(self):
        class R:
            data = [row]
        return R()

    return _Db, _no_network, SyncQueryRequestBuilder


@pytest.fixture
def db_with_null_rate_row(monkeypatch):
    """A single ended time entry whose hourly_rate_paise is explicitly NULL --
    the shape a start-timer-then-stop entry, or a manual entry with no rate
    typed, is actually stored as."""
    row = {
        "user_id": "u-1",
        "client_id": "c-1",
        "engagement_id": "e-1",
        "duration_minutes": 90,
        "is_billable": True,
        "hourly_rate_paise": None,
        "ended_at": "2026-06-15T12:00:00Z",
    }
    _Db, _no_network, SyncQueryRequestBuilder = _rows_fixture(row)
    monkeypatch.setattr(tta, "_USE_MOCK", False)
    monkeypatch.setattr(tta, "_get_db", lambda: _Db())
    monkeypatch.setattr(SyncQueryRequestBuilder, "execute", _no_network)
    return row


def test_get_cost_by_client_does_not_raise_on_a_null_rate(db_with_null_rate_row):
    result = time_tracking_analytics_repo.get_cost_by_client("firm-1", "2026-04-01", "2026-09-30")
    assert result == {"c-1": 0}


def test_get_cost_by_engagement_does_not_raise_on_a_null_rate(db_with_null_rate_row):
    result = time_tracking_analytics_repo.get_cost_by_engagement("firm-1", "2026-04-01", "2026-09-30")
    assert result == {"e-1": 0}


def test_get_metrics_by_team_member_does_not_raise_on_a_null_rate(db_with_null_rate_row):
    result = time_tracking_analytics_repo.get_metrics_by_team_member("firm-1", "2026-04-01", "2026-09-30")
    assert result == {
        "u-1": {"effort_minutes": 90, "billable_minutes": 90, "cost_paise": 0}
    }


def test_get_effort_by_engagement_does_not_raise_on_a_null_rate(db_with_null_rate_row):
    """The `hourly_rate_paise > 0` comparison is the one that raised
    `TypeError: '>' not supported between instances of 'NoneType' and 'int'`."""
    result = time_tracking_analytics_repo.get_effort_by_engagement("firm-1", "2026-04-01", "2026-09-30")
    assert result == {
        "e-1": {"billable_minutes": 90, "total_minutes": 90, "avg_hourly_rate_paise": 0}
    }


@pytest.fixture
def db_with_null_duration_row(monkeypatch):
    """An entry PATCHed with only `ended_at` (never `started_at`) never has
    `duration_minutes` recomputed, so `ended_at IS NOT NULL` does not imply
    `duration_minutes IS NOT NULL`."""
    row = {
        "user_id": "u-1",
        "client_id": "c-1",
        "engagement_id": "e-1",
        "duration_minutes": None,
        "is_billable": True,
        "hourly_rate_paise": 50000,
        "ended_at": "2026-06-15T12:00:00Z",
    }
    _Db, _no_network, SyncQueryRequestBuilder = _rows_fixture(row)
    monkeypatch.setattr(tta, "_USE_MOCK", False)
    monkeypatch.setattr(tta, "_get_db", lambda: _Db())
    monkeypatch.setattr(SyncQueryRequestBuilder, "execute", _no_network)
    return row


@pytest.mark.parametrize("method, key, expected", [
    ("get_hours_by_employee", "u-1", {"total_minutes": 0, "billable_minutes": 0}),
    ("get_hours_by_client", "c-1", {"total_minutes": 0, "billable_minutes": 0}),
    ("get_cost_by_client", "c-1", 0),
    ("get_cost_by_engagement", "e-1", 0),
])
def test_a_null_duration_does_not_raise_either(db_with_null_duration_row, method, key, expected):
    result = getattr(time_tracking_analytics_repo, method)("firm-1", "2026-04-01", "2026-09-30")
    assert result == {key: expected}


def test_get_firm_hours_does_not_raise_on_a_null_duration(db_with_null_duration_row):
    result = time_tracking_analytics_repo.get_firm_hours("firm-1", "2026-04-01", "2026-09-30")
    assert result == {"total_minutes": 0, "billable_minutes": 0}
