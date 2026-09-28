"""Every time-entry analytics query builds on the REAL postgrest builder.

The seven reads in `repositories/time_tracking_analytics_repository.py` called
`.not_("ended_at", "is", None)`, which raises a TypeError on postgrest 0.18
because `not_` is a property (see
`test_not_is_a_property_of_a_query_and_is_never_called.py`). The mock branch
never builds a query, so no test ever reached the line that broke all six
/api/analytics/* endpoints.

These tests take the LIVE branch with a genuine `SyncPostgrestClient` — nothing
faked but the network — and assert the finished request filters out running
timers. Against the previous code every one of them fails with the TypeError.
"""
from __future__ import annotations

import pytest

import repositories.time_tracking_analytics_repository as tta
from repositories.time_tracking_analytics_repository import time_tracking_analytics_repo


class _Sent:
    def __init__(self):
        self.params = []


@pytest.fixture
def sent(monkeypatch):
    from postgrest import SyncPostgrestClient
    from postgrest._sync.request_builder import SyncQueryRequestBuilder

    record = _Sent()

    class _Db:
        def __init__(self):
            self.client = SyncPostgrestClient("http://127.0.0.1:9/rest/v1")

        def table(self, name):
            return self.client.from_(name)

    def _no_network(self):
        # The builder is real up to here; only the HTTP round trip is replaced.
        record.params.append(str(self.params))

        class R:
            data = []
        return R()

    monkeypatch.setattr(tta, "_USE_MOCK", False)
    monkeypatch.setattr(tta, "_get_db", lambda: _Db())
    monkeypatch.setattr(SyncQueryRequestBuilder, "execute", _no_network)
    return record


METHODS = [
    "get_hours_by_employee",
    "get_hours_by_client",
    "get_firm_hours",
    "get_effort_by_engagement",
    "get_cost_by_client",
    "get_cost_by_engagement",
    "get_metrics_by_team_member",
]


def test_every_method_is_covered():
    """A method added later with its own query must be added here."""
    own = {n for n, v in vars(type(time_tracking_analytics_repo)).items()
           if callable(v) and n.startswith("get_")}
    assert own == set(METHODS)


@pytest.mark.parametrize("method", METHODS)
def test_an_analytics_query_reaches_the_database_and_skips_running_timers(sent, method):
    getattr(time_tracking_analytics_repo, method)("firm-1", "2026-04-01", "2026-09-30")

    assert len(sent.params) == 1
    assert "ended_at=not.is.null" in sent.params[0]
    assert "firm_id=eq.firm-1" in sent.params[0]
