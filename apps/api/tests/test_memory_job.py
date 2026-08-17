"""
Task #158 — the memory pipeline runs as job #11 of the daily sweep, not from
its own 24-hour sleep loop.

All tests run in mock mode (no SUPABASE_URL) and assert STRUCTURE and dispatch
only — the pipeline itself is stubbed, since what changed is WHEN and HOW OFTEN
it is invoked, not what it computes.
"""
import os
import sys

import pytest

# ── Ensure no DB required (mock mode) ─────────────────────────────────────────
os.environ.pop("SUPABASE_URL", None)

# Add the api root to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import jobs.memory_job as memory_job
import jobs.scheduler as sched


class _StubPipeline:
    """Records the firms it was asked to profile."""

    def __init__(self, result=None, raises=None):
        self.calls: list[str] = []
        self._result = result if result is not None else {}
        self._raises = raises

    def run_full_pipeline(self, firm_id):
        self.calls.append(firm_id)
        if self._raises:
            raise self._raises
        return self._result


@pytest.fixture(autouse=True)
def _mock_mode(monkeypatch):
    monkeypatch.setattr(sched, "_USE_MOCK", True)
    monkeypatch.setattr(memory_job, "_USE_MOCK", True)
    monkeypatch.delenv("ENABLE_SCHEDULER", raising=False)
    sched._MOCK_RUNS.clear()
    yield
    sched._MOCK_RUNS.clear()


# ── The thread is gone ────────────────────────────────────────────────────────
# The defect was structural: a module that scheduled itself. These fail if
# anyone reintroduces it.

def test_start_memory_scheduler_no_longer_exists():
    assert not hasattr(memory_job, "start_memory_scheduler"), (
        "the self-scheduling thread is what task #158 removed — the pipeline is "
        "job #11 of run_daily_jobs now"
    )


def test_memory_job_does_not_import_threading_or_time():
    """A sleep loop cannot come back without one of these."""
    source = open(memory_job.__file__).read()
    body = source.split('"""', 2)[-1]  # ignore the module docstring, which
    assert "import threading" not in body  # explains the old thread
    assert "time.sleep" not in body


def test_main_does_not_start_a_memory_thread():
    main_source = open(
        os.path.join(os.path.dirname(memory_job.__file__), "..", "main.py")
    ).read()
    # Comment lines are stripped first: main.py carries a "do not re-add
    # start_memory_scheduler()" warning, and a substring check over the raw file
    # would match that warning rather than a real call.
    code_lines = [
        line for line in main_source.splitlines()
        if not line.strip().startswith("#")
    ]
    assert not any("start_memory_scheduler" in line for line in code_lines)


# ── run_memory_pipeline_for_firm ──────────────────────────────────────────────

def test_runs_the_pipeline_for_the_firm_and_summarises(monkeypatch):
    stub = _StubPipeline({
        "profiles_updated": 3, "triggers_created": 2,
        "anomalies_detected": 1, "year_end_reports": 0, "errors": [],
    })
    monkeypatch.setattr(memory_job, "_get_pipeline", lambda: stub)

    result = memory_job.run_memory_pipeline_for_firm("F1")

    assert stub.calls == ["F1"]
    assert result["profiles_updated"] == 3
    assert result["triggers_created"] == 2
    assert result["anomalies_detected"] == 1


def test_partial_errors_ride_along_in_the_summary(monkeypatch):
    """run_full_pipeline collects per-client errors instead of raising, so they
    must reach the scheduler_runs detail rather than vanish."""
    stub = _StubPipeline({"profiles_updated": 1, "errors": ["Profile c9: boom"]})
    monkeypatch.setattr(memory_job, "_get_pipeline", lambda: stub)

    result = memory_job.run_memory_pipeline_for_firm("F1")
    assert result["errors"] == ["Profile c9: boom"]


def test_inactive_firm_is_skipped_without_running_the_pipeline(monkeypatch):
    """The loop this replaced selected is_active firms; run_daily_jobs iterates
    every firm, so the scoping has to be preserved here."""
    stub = _StubPipeline()
    monkeypatch.setattr(memory_job, "_get_pipeline", lambda: stub)
    monkeypatch.setattr(memory_job, "is_firm_active", lambda firm_id: False)

    result = memory_job.run_memory_pipeline_for_firm("F1")

    assert result == {"skipped": "firm inactive"}
    assert stub.calls == [], "an inactive firm must not be profiled"


def test_pipeline_exception_propagates_to_the_scheduler(monkeypatch):
    """Not swallowed here — run_daily_jobs records the failed run row."""
    stub = _StubPipeline(raises=RuntimeError("pipeline exploded"))
    monkeypatch.setattr(memory_job, "_get_pipeline", lambda: stub)

    with pytest.raises(RuntimeError):
        memory_job.run_memory_pipeline_for_firm("F1")


# ── is_firm_active ────────────────────────────────────────────────────────────

def test_is_firm_active_true_in_mock_mode():
    assert memory_job.is_firm_active("F1") is True


def test_is_firm_active_fails_open_when_the_read_fails(monkeypatch):
    """Skipping an active firm because one read failed is worse than the
    converse — and the run log records the outcome either way."""
    monkeypatch.setattr(memory_job, "_USE_MOCK", False)

    def _boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(memory_job, "_get_db", _boom)

    assert memory_job.is_firm_active("F1") is True


# ── Wiring into the daily sweep ───────────────────────────────────────────────

def test_memory_pipeline_is_a_known_job():
    assert "memory_pipeline" in sched.KNOWN_JOBS


def test_run_daily_jobs_includes_memory_pipeline(monkeypatch):
    stub = _StubPipeline({"profiles_updated": 1})
    monkeypatch.setattr(memory_job, "_get_pipeline", lambda: stub)

    results = sched.run_daily_jobs(firm_id="F1", force=True)

    assert "memory_pipeline" in results["firms"]["F1"]
    assert stub.calls == ["F1"]


def test_memory_pipeline_runs_last(monkeypatch):
    """It profiles the state the other jobs have just settled, so its run row is
    written after theirs."""
    monkeypatch.setattr(memory_job, "_get_pipeline", lambda: _StubPipeline({}))
    sched.run_daily_jobs(firm_id="F1", force=True)

    logged = [r["job_name"] for r in sched._MOCK_RUNS]
    assert logged[-1] == "memory_pipeline"


def test_second_run_today_skips_the_pipeline(monkeypatch):
    """The gate the old thread never had: a cold start must not recompute every
    profile again."""
    stub = _StubPipeline({})
    monkeypatch.setattr(memory_job, "_get_pipeline", lambda: stub)

    sched.run_daily_jobs(firm_id="F1", force=True)
    assert stub.calls == ["F1"]

    second = sched.run_daily_jobs(firm_id="F1")  # force=False — a later boot
    assert second["firms"]["F1"]["memory_pipeline"] == {"skipped": "already ran today"}
    assert stub.calls == ["F1"], "the pipeline must not run twice in one day"


def test_a_failing_pipeline_is_recorded_and_does_not_break_the_sweep(monkeypatch):
    stub = _StubPipeline(raises=RuntimeError("pipeline exploded"))
    monkeypatch.setattr(memory_job, "_get_pipeline", lambda: stub)

    results = sched.run_daily_jobs(firm_id="F1", force=True)  # must not raise

    assert "error" in results["firms"]["F1"]["memory_pipeline"]
    failed = [
        r for r in sched._MOCK_RUNS
        if r["job_name"] == "memory_pipeline" and r["status"] == "failed"
    ]
    assert len(failed) == 1


def test_catchup_covers_the_memory_pipeline(monkeypatch):
    """The point of folding it in: a missed 06:00 IST run now catches this job
    up too, which the standalone thread could never do."""
    monkeypatch.setenv("ENABLE_SCHEDULER", "true")
    monkeypatch.setattr(sched, "_catchup_started", False)
    monkeypatch.setattr(sched, "_list_firm_ids", lambda: ["F1"])

    import datetime as _datetime_module
    from datetime import datetime, timezone
    import core.ist_clock as ist_clock
    fixed = datetime.fromisoformat("2026-04-01T01:00:00").replace(tzinfo=timezone.utc)

    class _FrozenDateTime(_datetime_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz is not None else fixed

    monkeypatch.setattr(ist_clock, "datetime", _FrozenDateTime)  # 06:30 IST

    stub = _StubPipeline({})
    monkeypatch.setattr(memory_job, "_get_pipeline", lambda: stub)

    result = sched.run_catchup_if_stale(background=False)

    assert result["ran"] is True
    assert stub.calls == ["F1"]
