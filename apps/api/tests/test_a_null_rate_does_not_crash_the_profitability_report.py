"""sweep-practice-hub-02: a NULL hourly_rate_paise must not 500 the report.

`entry.get("hourly_rate_paise", 0)` only substitutes 0 when the KEY IS ABSENT
from the row -- not when Postgres actually stored NULL, which is the common
case: `routers/time_tracking.py::start_timer` never writes
`hourly_rate_paise` at all, and `create_manual_entry` writes it as None
whenever no rate was typed on the /time form. `duration_minutes * None` and
`None > 0` (get_effort_by_engagement) both raise TypeError, and since
`routers/analytics.py`'s /profitability, /concentration and /revenue-vs-effort
endpoints call these with no try/except, a single qualifying time entry with
a NULL rate 500s the whole page.

POST-B-321 moved the COST off that column altogether (it is the member's
`users.cost_rate_paise` now, an unset one is unknown, and `domain/practice/
profitability` folds it), so the three cost reads are gone and what is held here
is what survives: the effort read that still compares the billing rate, the NULL
duration, and the rule's own reading of a NULL rate and a NULL duration.

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


def test_the_cost_entries_come_back_whatever_the_billing_rate_is(db_with_null_rate_row):
    """The read hands back who, which client and engagement and how long: it no longer prices anything, so a NULL billing
    rate cannot raise in it, and the row still comes back."""
    rows = time_tracking_analytics_repo.get_cost_entries("firm-1", "2026-04-01", "2026-09-30")
    assert [(r["user_id"], r["client_id"], r["engagement_id"], r["duration_minutes"]) for r in rows] == [("u-1", "c-1", "e-1", 90)]


def test_a_null_billing_rate_does_not_touch_the_cost_which_is_the_members_own_rate(db_with_null_rate_row):
    from domain.practice import profitability as rule
    rows = time_tracking_analytics_repo.get_cost_entries("firm-1", "2026-04-01", "2026-09-30")
    effort = rule.fold_effort(rows, rule.clean_cost_rates({"u-1": 40_000}), "client_id")
    assert effort["c-1"].cost_paise == 60_000 and effort["c-1"].cost_is_known


def test_a_member_with_no_cost_rate_is_unknown_in_every_view(db_with_null_rate_row):
    from domain.practice import profitability as rule
    rows = time_tracking_analytics_repo.get_cost_entries("firm-1", "2026-04-01", "2026-09-30")
    for key, group in (("client_id", "c-1"), ("engagement_id", "e-1"), ("user_id", "u-1")):
        effort = rule.fold_effort(rows, rule.clean_cost_rates({"u-1": None}), key)[group]
        assert (effort.minutes, effort.unrated_minutes, effort.cost_is_known) == (90, 90, False)


def test_the_worth_entries_come_back_whatever_the_billing_rate_is(db_with_null_rate_row):
    """The `hourly_rate_paise > 0` comparison raised `TypeError: '>' not supported between instances of 'NoneType' and
    'int'` while the read priced anything. It prices nothing now (POST-A-426): the row comes back with its rates as stored
    and `domain/practice/realization` names an entry with neither as unpriced, never as worth 0."""
    from domain.practice import realization as real
    rows = time_tracking_analytics_repo.get_worth_entries("firm-1", "2026-04-01", "2026-09-30")
    assert [(r["engagement_id"], r["duration_minutes"], r["hourly_rate_paise"]) for r in rows] == [("e-1", 90, None)]
    worth = real.fold_worth(rows, "engagement_id")["e-1"]
    assert (worth.billable_minutes, worth.unpriced_minutes, worth.priced_value_paise, worth.value_is_known) == (90, 90, None, False)


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
])
def test_a_null_duration_does_not_raise_either(db_with_null_duration_row, method, key, expected):
    result = getattr(time_tracking_analytics_repo, method)("firm-1", "2026-04-01", "2026-09-30")
    assert result == {key: expected}


def test_a_null_duration_is_no_time_in_the_cost_and_does_not_raise(db_with_null_duration_row):
    from domain.practice import profitability as rule
    rows = time_tracking_analytics_repo.get_cost_entries("firm-1", "2026-04-01", "2026-09-30")
    assert len(rows) == 1
    assert rule.fold_effort(rows, rule.clean_cost_rates({"u-1": 50_000}), "client_id") == {}


def test_get_firm_hours_does_not_raise_on_a_null_duration(db_with_null_duration_row):
    result = time_tracking_analytics_repo.get_firm_hours("firm-1", "2026-04-01", "2026-09-30")
    assert result == {"total_minutes": 0, "billable_minutes": 0}
