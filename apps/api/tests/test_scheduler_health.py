"""
H11 — Scheduler reliability + health visibility, and H7 — recurring compliance
generation job.

All tests run in mock mode (no SUPABASE_URL). They assert STRUCTURE and
no-raise behaviour only — mock mode may have no engagements/firms, so we never
assert on real generated counts.
"""
import os
import sys

import pytest

# ── Ensure no DB required (mock mode) ─────────────────────────────────────────
os.environ.pop("SUPABASE_URL", None)

# Add the api root to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient

import jobs.scheduler as sched
from core.auth import get_current_user
from routers.scheduler_status import router as scheduler_router

# Manager satisfies team/read; Partner satisfies team/write.
MANAGER = {"id": "m", "firm_id": "F1", "role": "Manager", "email": "m@firm.com"}
PARTNER = {"id": "p", "firm_id": "F1", "role": "Partner", "email": "p@firm.com"}


@pytest.fixture(autouse=True)
def _mock_mode(monkeypatch):
    """Force the scheduler module into mock mode and start from a clean run log,
    regardless of import order / leaked env from other tests."""
    monkeypatch.setattr(sched, "_USE_MOCK", True)
    monkeypatch.delenv("ENABLE_SCHEDULER", raising=False)
    sched._MOCK_RUNS.clear()
    yield
    sched._MOCK_RUNS.clear()


def _client(user):
    app = FastAPI()
    app.include_router(scheduler_router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


# ── scheduler_health() ────────────────────────────────────────────────────────

def test_scheduler_health_has_expected_keys():
    health = sched.scheduler_health()
    assert isinstance(health, dict)
    for key in ("enabled", "running", "stale", "warnings", "last_runs"):
        assert key in health, f"missing key: {key}"
    assert isinstance(health["warnings"], list)
    assert isinstance(health["last_runs"], dict)
    # last_runs reports every known job name.
    for job_name in sched.KNOWN_JOBS:
        assert job_name in health["last_runs"]


def test_scheduler_health_disabled_warns():
    # ENABLE_SCHEDULER is unset (see fixture).
    health = sched.scheduler_health()
    assert health["enabled"] is False
    assert health["warnings"], "expected a non-empty warnings list when disabled"
    assert any("ENABLE_SCHEDULER" in w for w in health["warnings"])


def test_scheduler_health_never_raises_when_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_SCHEDULER", "true")
    health = sched.scheduler_health()  # must not raise
    assert health["enabled"] is True
    assert isinstance(health["warnings"], list)


# ── log_scheduler_startup_health() ────────────────────────────────────────────

def test_startup_health_hook_returns_dict_and_no_raise():
    health = sched.log_scheduler_startup_health()
    assert isinstance(health, dict)
    assert "warnings" in health


# ── H7: run_daily_jobs includes compliance_generation ─────────────────────────

def test_run_daily_jobs_includes_compliance_generation():
    results = sched.run_daily_jobs(force=True)  # must not raise
    assert "firms" in results
    # When firms exist in mock mode, every firm result carries the new job key;
    # when none exist, the loop is empty but the call still succeeds.
    for firm_result in results["firms"].values():
        assert "compliance_generation" in firm_result
        # The generation job is placed BEFORE escalations.
        assert "compliance_escalations" in firm_result


def test_run_daily_jobs_scoped_to_one_firm_has_generation_entry():
    results = sched.run_daily_jobs(firm_id="F1", force=True)
    assert "F1" in results["firms"]
    assert "compliance_generation" in results["firms"]["F1"]


# ── Status endpoint ───────────────────────────────────────────────────────────

def test_status_endpoint_returns_new_keys():
    r = _client(MANAGER).get("/api/scheduler/status")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    for key in ("enabled", "running", "stale", "warnings", "last_runs", "recent_runs"):
        assert key in data, f"missing key in status data: {key}"


def test_status_endpoint_tolerates_runs_without_started_at():
    # Mock run rows from run_daily_jobs lack started_at — the status sort must
    # not crash on them.
    sched.run_daily_jobs(firm_id="F1", force=True)
    r = _client(MANAGER).get("/api/scheduler/status")
    assert r.status_code == 200
    assert isinstance(r.json()["data"]["recent_runs"], list)


def test_status_endpoint_requires_team_read():
    client_user = {"id": "c", "firm_id": "F1", "role": "Client", "email": "c@firm.com"}
    r = _client(client_user).get("/api/scheduler/status")
    assert r.status_code == 403
