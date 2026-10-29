"""A person's manual run of the daily jobs answers at once and runs on a thread (POST-A-289, item 8).

WHAT WAS WRONG
    `POST /api/scheduler/run` and `POST /api/tasks/trigger-scheduler-run` ran the whole sweep inside the request. The sweep is minutes
    (the nightly health step alone reads about twenty-five rows per client, one after another across regions), so the caller held a
    connection past a proxy's timeout and was told 502 for a run that carried on. The token-protected external trigger has always
    started its run on a thread and answered at once.

WHAT IS HELD
    * `jobs.scheduler.start_daily_jobs` starts `run_daily_jobs` for ONE firm on a daemon thread and returns {"started", "reason"};
    * an empty firm id starts nothing, because `run_daily_jobs` given none runs EVERY firm's jobs and a person's request must never
      reach that far;
    * a second press for the same firm while one is running starts nothing and says so; a finished or failed run releases the firm;
    * neither route calls `run_daily_jobs` itself (a source rule over both), and both answer with the starter's answer.
"""
from __future__ import annotations

import ast
import threading
from pathlib import Path

import jobs.scheduler as js
import routers.scheduler_status as sched
import routers.tasks as tasks

API = Path(__file__).resolve().parent.parent
PARTNER = {"id": "u1", "firm_id": "f1", "role": "Partner", "email": "p@example.test"}


def _reset():
    with js._manual_runs_lock:
        js._manual_runs_in_progress.clear()


def test_the_run_goes_to_a_thread_and_the_caller_is_answered_before_it_ends(monkeypatch):
    _reset()
    release, started, seen = threading.Event(), threading.Event(), {}

    def fake(firm_id=None, force=False):
        seen.update(firm_id=firm_id, force=force, thread=threading.current_thread().name)
        started.set()
        release.wait(timeout=5)
        return {}

    monkeypatch.setattr(js, "run_daily_jobs", fake)
    out = js.start_daily_jobs("f1", True)
    assert out["started"] is True and "status" in out["reason"]
    assert started.wait(timeout=5), "the run never began"
    assert seen == {"firm_id": "f1", "force": True, "thread": "scheduler-manual"}, "it must run on its own thread, for the one firm"
    release.set()


def test_an_empty_firm_id_starts_nothing_so_a_persons_request_never_runs_every_firm(monkeypatch):
    _reset()
    called = []
    monkeypatch.setattr(js, "run_daily_jobs", lambda **k: called.append(k))
    for firm in (None, ""):
        out = js.start_daily_jobs(firm)
        assert out["started"] is False
    assert called == []


def test_a_second_press_for_the_same_firm_while_one_runs_starts_nothing_and_another_firm_is_free(monkeypatch):
    _reset()
    release, started = threading.Event(), threading.Event()
    calls = []

    def fake(firm_id=None, force=False):
        calls.append(firm_id)
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr(js, "run_daily_jobs", fake)
    assert js.start_daily_jobs("f1")["started"] is True
    assert started.wait(timeout=5)
    second = js.start_daily_jobs("f1")
    assert second["started"] is False and "already in progress" in second["reason"]
    assert js.start_daily_jobs("f2")["started"] is True, "another firm's press is not blocked by this firm's run"
    release.set()
    for _ in range(100):
        with js._manual_runs_lock:
            if not js._manual_runs_in_progress:
                break
        threading.Event().wait(0.05)
    assert sorted(calls) == ["f1", "f2"]


def test_a_finished_run_and_a_failed_run_both_release_the_firm(monkeypatch):
    _reset()
    monkeypatch.setattr(js, "run_daily_jobs", lambda **k: {})
    assert js.start_daily_jobs("f1", background=False)["started"] is True
    assert "f1" not in js._manual_runs_in_progress

    def boom(**k):
        raise RuntimeError("a job blew up")

    monkeypatch.setattr(js, "run_daily_jobs", boom)
    assert js.start_daily_jobs("f1", background=False)["started"] is True
    assert "f1" not in js._manual_runs_in_progress, "a run that raised kept the firm blocked"


def test_both_routes_answer_with_the_starters_answer_and_start_the_callers_firm(monkeypatch):
    seen = []
    monkeypatch.setattr(js, "start_daily_jobs",
                        lambda firm_id, force=False: seen.append((firm_id, force)) or {"started": True, "reason": "x"})
    a = sched.trigger_run(force=True, current_user=PARTNER)
    b = tasks.trigger_scheduler_run(force=False, current_user=PARTNER)
    assert a["data"] == {"started": True, "reason": "x"} and b["data"] == {"started": True, "reason": "x"}
    assert seen == [("f1", True), ("f1", False)]


def test_neither_route_runs_the_sweep_inside_the_request():
    """The rule, not the spelling: no function in either router calls `run_daily_jobs`."""
    for rel in ("routers/scheduler_status.py", "routers/tasks.py"):
        tree = ast.parse((API / rel).read_text())
        called = {n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
                  for n in ast.walk(tree) if isinstance(n, ast.Call)}
        assert "run_daily_jobs" not in called, f"{rel} runs the whole sweep inside a request again"
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "jobs.scheduler" for a in n.names}
        assert "run_daily_jobs" not in imported, f"{rel} imports the in-request runner"
