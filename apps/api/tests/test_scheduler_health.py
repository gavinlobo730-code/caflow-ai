"""
H11 — Scheduler reliability + health visibility, and H7 — recurring compliance
generation job.

All tests run in mock mode (no SUPABASE_URL). They assert STRUCTURE and
no-raise behaviour only — mock mode may have no engagements/firms, so we never
assert on real generated counts.
"""
import os
import sys
from datetime import date, datetime, timezone

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
    # The status sort must not crash on a row with no started_at.
    #
    # This used to lean on run_daily_jobs' own output, which lacked the field
    # (task #161 — _log_run never sent it). Now that it does, relying on that
    # would leave this test asserting nothing. So the row is constructed
    # explicitly: rows written before #161, and any future writer that omits
    # started_at, still exist and must not break the view.
    sched._MOCK_RUNS.append({
        "job_name": "legacy_row", "run_date": date.today().isoformat(),
        "firm_id": "F1", "status": "success", "detail": {},
        "finished_at": datetime.now(timezone.utc).isoformat(),
    })
    r = _client(MANAGER).get("/api/scheduler/status")
    assert r.status_code == 200
    assert isinstance(r.json()["data"]["recent_runs"], list)


# ── Task #161: started_at is the real start, not the INSERT time ─────────────

def test_every_logged_run_carries_a_started_at():
    sched._MOCK_RUNS.clear()
    sched.run_daily_jobs(firm_id="F1", force=True)
    assert sched._MOCK_RUNS, "no runs recorded"
    missing = [r["job_name"] for r in sched._MOCK_RUNS if not r.get("started_at")]
    assert not missing, f"jobs logged without started_at: {missing}"


def test_started_at_precedes_finished_at():
    """The defect this fixes. started_at was a NOT NULL DEFAULT now() evaluated
    at INSERT — after finished_at had been computed in Python — so every row
    claimed to start after it ended."""
    sched._MOCK_RUNS.clear()
    sched.run_daily_jobs(firm_id="F1", force=True)
    for r in sched._MOCK_RUNS:
        assert r["started_at"] <= r["finished_at"], (
            f"{r['job_name']}: started_at {r['started_at']} is after "
            f"finished_at {r['finished_at']}"
        )


def test_a_failing_job_still_records_when_it_started(monkeypatch):
    """The failure path logs from inside `except`, a different call site — it
    must carry the same start time, since a failed run's duration is exactly
    what someone debugging the sweep wants."""
    def _boom(*a, **k):
        raise RuntimeError("job exploded")
    monkeypatch.setattr("jobs.recurring_task_job.run_recurring_generation_job", _boom)

    sched._MOCK_RUNS.clear()
    sched.run_daily_jobs(firm_id="F1", force=True)

    failed = [r for r in sched._MOCK_RUNS
              if r["job_name"] == "recurring_generation" and r["status"] == "failed"]
    assert failed, "expected the forced failure to be recorded"
    assert failed[0].get("started_at"), "failure path lost started_at"
    assert failed[0]["started_at"] <= failed[0]["finished_at"]


def test_status_endpoint_requires_team_read():
    client_user = {"id": "c", "firm_id": "F1", "role": "Client", "email": "c@firm.com"}
    r = _client(client_user).get("/api/scheduler/status")
    assert r.status_code == 403


# ── R2.7: _past_scheduled_hour must resolve the IST timezone ──────────────────
# (pytz was never a dependency — this always hit the except branch and
# silently returned True regardless of the actual time, same bug class as
# _compute_next_run's missing croniter/pytz fallback.)

def test_past_scheduled_hour_resolves_real_timezone():
    result = sched._past_scheduled_hour()
    assert isinstance(result, bool)


def test_past_scheduled_hour_matches_manual_ist_calculation():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    expected = now_ist.hour >= sched._SCHEDULED_HOUR_IST
    assert sched._past_scheduled_hour() == expected


# ── Phase 3: _past_scheduled_hour now delegates to core.ist_clock.ist_now() ───
# instead of re-resolving ZoneInfo("Asia/Kolkata") locally. These freeze the
# shared clock (same technique as test_ist_clock.py) to pin the 06:00 IST
# boundary deterministically, rather than relying only on the live-clock
# comparison above.

def _freeze_ist_clock(monkeypatch, utc_iso: str):
    import datetime as _datetime_module
    from datetime import datetime, timezone
    import core.ist_clock as ist_clock

    fixed = datetime.fromisoformat(utc_iso).replace(tzinfo=timezone.utc)

    class _FrozenDateTime(_datetime_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz is not None else fixed

    monkeypatch.setattr(ist_clock, "datetime", _FrozenDateTime)


def test_past_scheduled_hour_false_just_before_6am_ist(monkeypatch):
    _freeze_ist_clock(monkeypatch, "2026-04-01T00:29:00")  # 05:59 IST
    assert sched._past_scheduled_hour() is False


def test_past_scheduled_hour_true_at_6am_ist(monkeypatch):
    _freeze_ist_clock(monkeypatch, "2026-04-01T00:30:00")  # 06:00 IST
    assert sched._past_scheduled_hour() is True


# ── Task #155 — catch up a 06:00 IST run the process was asleep for ───────────
# The in-process timer can only fire if the process is alive at 06:00 IST, and
# on the free tier that depends on a GitHub cron GitHub itself runs late or
# drops. These pin the decision to catch up; run_daily_jobs' own idempotency is
# covered above.

@pytest.fixture
def _catchup_ready(monkeypatch):
    """Enabled, past 06:00 IST, one firm, and no catch-up attempted yet."""
    monkeypatch.setenv("ENABLE_SCHEDULER", "true")
    monkeypatch.setattr(sched, "_catchup_started", False)
    monkeypatch.setattr(sched, "_list_firm_ids", lambda: ["F1"])
    _freeze_ist_clock(monkeypatch, "2026-04-01T01:00:00")  # 06:30 IST


@pytest.fixture
def _spy_daily_jobs(monkeypatch):
    """Record calls to run_daily_jobs instead of running the real sweep."""
    calls: list[dict] = []
    monkeypatch.setattr(
        sched, "run_daily_jobs",
        lambda firm_id=None, force=False: calls.append({"firm_id": firm_id, "force": force}) or {},
    )
    return calls


def _record_success(job_name, firm_id="F1"):
    """A successful scheduler_runs row for today, as _log_run would write it."""
    from datetime import date
    sched._MOCK_RUNS.append({
        "job_name": job_name,
        "run_date": date.today().isoformat(),
        "firm_id": firm_id,
        "status": "success",
        "detail": {},
    })


# ── the three gates ───────────────────────────────────────────────────────────

def test_catchup_skipped_when_scheduler_disabled(monkeypatch, _spy_daily_jobs):
    # ENABLE_SCHEDULER unset (fixture): something else owns the daily run, and on
    # a multi-worker deploy every worker would otherwise catch up at once.
    monkeypatch.setattr(sched, "_catchup_started", False)
    _freeze_ist_clock(monkeypatch, "2026-04-01T01:00:00")  # 06:30 IST
    result = sched.run_catchup_if_stale(background=False)
    assert result["ran"] is False
    assert "disabled" in result["reason"]
    assert _spy_daily_jobs == []


def test_catchup_skipped_before_scheduled_hour(monkeypatch, _spy_daily_jobs):
    monkeypatch.setenv("ENABLE_SCHEDULER", "true")
    monkeypatch.setattr(sched, "_catchup_started", False)
    monkeypatch.setattr(sched, "_list_firm_ids", lambda: ["F1"])
    _freeze_ist_clock(monkeypatch, "2026-04-01T00:29:00")  # 05:59 IST
    result = sched.run_catchup_if_stale(background=False)
    assert result["ran"] is False
    assert _spy_daily_jobs == [], "must not pre-empt the scheduled 06:00 IST run"


def test_catchup_skipped_when_today_is_complete(_catchup_ready, _spy_daily_jobs):
    for job_name in sched.KNOWN_JOBS:
        _record_success(job_name)
    result = sched.run_catchup_if_stale(background=False)
    assert result["ran"] is False
    assert _spy_daily_jobs == []


# ── the case the task is about ────────────────────────────────────────────────

def test_catchup_runs_when_nothing_ran_today(_catchup_ready, _spy_daily_jobs):
    result = sched.run_catchup_if_stale(background=False)
    assert result["ran"] is True
    assert result["pending"] == len(sched.KNOWN_JOBS)
    assert len(_spy_daily_jobs) == 1
    # force must stay False — the point is to run what is MISSING, not to
    # re-run jobs that already succeeded today.
    assert _spy_daily_jobs[0]["force"] is False


def test_catchup_runs_when_only_some_jobs_succeeded(_catchup_ready, _spy_daily_jobs):
    """A catch-up killed part-way (the instance spins down ~15 min after the
    request that woke it) must be resumed, not read as a finished day."""
    _record_success(sched.KNOWN_JOBS[0])
    result = sched.run_catchup_if_stale(background=False)
    assert result["ran"] is True
    assert result["pending"] == len(sched.KNOWN_JOBS) - 1
    assert len(_spy_daily_jobs) == 1


def test_catchup_runs_when_another_firm_is_complete(monkeypatch, _catchup_ready, _spy_daily_jobs):
    """Success is per firm: F1 finishing does not mean F2 ran."""
    monkeypatch.setattr(sched, "_list_firm_ids", lambda: ["F1", "F2"])
    for job_name in sched.KNOWN_JOBS:
        _record_success(job_name, firm_id="F1")
    result = sched.run_catchup_if_stale(background=False)
    assert result["ran"] is True
    assert result["pending"] == len(sched.KNOWN_JOBS), "F2's jobs are all outstanding"


def test_catchup_retries_a_job_that_failed_today(_catchup_ready, _spy_daily_jobs):
    """A failed row is not a success — a transient 06:00 failure should not have
    to wait a full day for the next trigger."""
    from datetime import date
    for job_name in sched.KNOWN_JOBS:
        _record_success(job_name)
    sched._MOCK_RUNS.append({
        "job_name": sched.KNOWN_JOBS[0], "run_date": date.today().isoformat(),
        "firm_id": "F1", "status": "failed", "detail": {"error": "boom"},
    })
    # KNOWN_JOBS[0] has BOTH a success and a failure — the success stands.
    assert sched.run_catchup_if_stale(background=False)["ran"] is False

    sched._MOCK_RUNS.clear()
    sched._catchup_started = False
    sched._MOCK_RUNS.append({
        "job_name": sched.KNOWN_JOBS[0], "run_date": date.today().isoformat(),
        "firm_id": "F1", "status": "failed", "detail": {"error": "boom"},
    })
    result = sched.run_catchup_if_stale(background=False)
    assert result["ran"] is True
    # The failed job must be counted as OUTSTANDING, not merely leave the other
    # nine outstanding — "ran is True" alone passes even if a failed row is read
    # as a success, which is exactly the bug this pins.
    assert result["pending"] == len(sched.KNOWN_JOBS)


# ── once per process ──────────────────────────────────────────────────────────

def test_catchup_attempted_only_once_per_process(_catchup_ready, _spy_daily_jobs):
    """Bounds the retries: a job failing all day must not re-run the sweep on
    every one of the day's cold starts."""
    assert sched.run_catchup_if_stale(background=False)["ran"] is True
    second = sched.run_catchup_if_stale(background=False)
    assert second["ran"] is False
    assert "already attempted" in second["reason"]
    assert len(_spy_daily_jobs) == 1


# ── no firms, background thread, and never-raises ─────────────────────────────

def test_catchup_no_firms_is_not_stale(monkeypatch, _catchup_ready, _spy_daily_jobs):
    monkeypatch.setattr(sched, "_list_firm_ids", lambda: [])
    assert sched.run_catchup_if_stale(background=False)["ran"] is False
    assert _spy_daily_jobs == []


def test_catchup_background_thread_runs_the_jobs(_catchup_ready, _spy_daily_jobs):
    import threading
    result = sched.run_catchup_if_stale()  # background=True (the startup path)
    assert result["ran"] is True
    for thread in threading.enumerate():
        if thread.name == "scheduler-catchup":
            thread.join(timeout=5)
    assert len(_spy_daily_jobs) == 1


def test_catchup_survives_a_failing_check(monkeypatch, _catchup_ready, _spy_daily_jobs):
    """Startup must never be blocked by a catch-up that cannot decide."""
    def _boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(sched, "_list_firm_ids", _boom)
    result = sched.run_catchup_if_stale(background=False)  # must not raise
    assert result["ran"] is False
    assert _spy_daily_jobs == []


def test_catchup_worker_swallows_job_failures(monkeypatch):
    """The thread body must not let an exception escape into a bare thread."""
    def _boom(firm_id=None, force=False):
        raise RuntimeError("sweep exploded")
    monkeypatch.setattr(sched, "run_daily_jobs", _boom)
    sched._catchup_worker()  # must not raise


def test_catchup_real_sweep_does_not_raise(_catchup_ready):
    """No spy — the real run_daily_jobs, in mock mode, end to end."""
    result = sched.run_catchup_if_stale(background=False)
    assert result["ran"] is True
