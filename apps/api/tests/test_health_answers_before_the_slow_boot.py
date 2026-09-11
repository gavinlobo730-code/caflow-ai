"""/health answers immediately, and "not yet checked" is not "drifted".

THE INCIDENT

Every Render deploy failed for weeks with "Timed out after waiting for internal
health check to return a successful response code", on code that was fine — a
manual re-deploy of the SAME commit succeeded every time.

The cause was in main.py, at module scope: the schema-drift check, the
scheduler start, its health log and the catch-up sweep all ran before uvicorn
bound a socket. Three of the four make a round trip to Postgres, and this
service runs in Singapore against a Mumbai database.

The damage was not the failed-deploy noise. A failed deploy leaves Render
serving the PREVIOUS image, while the migration job applies that commit's
migrations regardless — so the database ran ahead of the code until somebody
clicked Manual Deploy.

WHAT THESE TESTS PIN

1. The slow work is NOT at import. If it moves back, importing main becomes
   slow again and no amount of lifespan wiring helps.
2. /health returns 200 while the schema check is outstanding. Returning 503
   there reproduces the original bug exactly — Render cannot tell "still
   checking" from "broken", and times out on a good deploy.
3. /health still returns 503 once drift is actually found. Task #244's
   protection is delayed, not deleted.
"""
from __future__ import annotations

import importlib
import time

import pytest
from fastapi.testclient import TestClient

import main as main_module


@pytest.fixture()
def drift():
    """Restore the module's real drift state after a test has poked it."""
    before = dict(main_module._SCHEMA_DRIFT)
    yield
    main_module._SCHEMA_DRIFT = before


def _health():
    """Call /health WITHOUT entering the TestClient context manager.

    Entering it runs the lifespan, which starts the boot thread, which
    overwrites _SCHEMA_DRIFT with whatever the real check returns — so a test
    that sets the flag and then enters the context is racing its own fixture.
    The lifespan is exercised deliberately in its own test below; these three
    are about the endpoint's reading of the flag.
    """
    return TestClient(main_module.app).get("/health")


def test_health_is_200_while_the_schema_check_is_still_running(drift):
    """The exact case that failed every deploy.

    Nothing has been checked yet, and nothing is wrong. The endpoint must say
    so with a 200 — Render reads the STATUS CODE, and 503 here is
    indistinguishable to it from a broken deploy.
    """
    main_module._SCHEMA_DRIFT = {"checked": False, "missing": []}
    r = _health()
    assert r.status_code == 200, (
        "a health check that answers 503 while merely unchecked is the bug this "
        "endpoint was rewritten to fix")
    assert r.json()["data"]["schema"] == "checking"


def test_health_says_ok_once_the_check_has_run_clean(drift):
    main_module._SCHEMA_DRIFT = {"checked": True, "missing": []}
    r = _health()
    assert r.status_code == 200
    assert r.json()["data"]["schema"] == "ok"


def test_health_still_refuses_traffic_on_real_drift(drift):
    """Task #244 is delayed by one round trip, not removed."""
    main_module._SCHEMA_DRIFT = {"checked": True, "missing": ["clients.some_new_col"]}
    r = _health()
    assert r.status_code == 503
    body = r.json()
    assert body["success"] is False
    assert body["data"]["missing_columns"] == ["clients.some_new_col"]
    assert "migration" in (body["error"] or "").lower()


def test_the_slow_work_is_not_done_at_import():
    """The rule, not a spelling of it.

    Re-importing main must not run the schema check, start the scheduler, or
    sweep for catch-up. Asserted by watching whether the functions are CALLED,
    because "is it fast" is a flaky thing to assert and "is it called" is not.
    """
    called: list[str] = []

    import core.schema_guard as guard
    import jobs.scheduler as sched

    originals = {
        (guard, "run_startup_check"): guard.run_startup_check,
        (sched, "start_scheduler"): sched.start_scheduler,
        (sched, "run_catchup_if_stale"): sched.run_catchup_if_stale,
    }
    for (mod, name), fn in originals.items():
        setattr(mod, name, lambda *a, _n=name, **k: called.append(_n) or {"checked": True, "missing": []})
    try:
        importlib.reload(main_module)
        assert called == [], (
            f"module import ran {called} — that is a cross-region round trip before "
            "uvicorn can bind, and it is what timed out every Render deploy")
    finally:
        for (mod, name), fn in originals.items():
            setattr(mod, name, fn)
        importlib.reload(main_module)


def test_the_boot_thread_runs_all_four_steps_in_order():
    """And the order matters: the check that can say "do not serve" goes first,
    and the scheduler goes last, so a job cannot fire against a drifted schema.
    """
    called: list[str] = []

    import core.schema_guard as guard
    import jobs.scheduler as sched

    originals = {
        (guard, "run_startup_check"): guard.run_startup_check,
        (main_module, "start_scheduler"): main_module.start_scheduler,
        (main_module, "log_scheduler_startup_health"): main_module.log_scheduler_startup_health,
        (sched, "run_catchup_if_stale"): sched.run_catchup_if_stale,
    }

    def _stub(name, ret=None):
        def f(*a, **k):
            called.append(name)
            return ret
        return f

    setattr(guard, "run_startup_check", _stub("schema", {"checked": True, "missing": []}))
    setattr(main_module, "start_scheduler", _stub("scheduler"))
    setattr(main_module, "log_scheduler_startup_health", _stub("health_log"))
    setattr(sched, "run_catchup_if_stale", _stub("catchup"))
    before = dict(main_module._SCHEMA_DRIFT)
    try:
        main_module._boot_background()
        assert called == ["schema", "scheduler", "health_log", "catchup"]
        assert main_module._SCHEMA_DRIFT == {"checked": True, "missing": []}
    finally:
        for (mod, name), fn in originals.items():
            setattr(mod, name, fn)
        main_module._SCHEMA_DRIFT = before


def test_a_failing_step_does_not_stop_the_rest():
    """Every step is non-fatal. A transient DB hiccup in the schema check must
    not leave the scheduler unstarted for the life of the process — and must
    NOT be reported as drift, which would fail the deploy for the wrong reason.
    """
    called: list[str] = []

    import core.schema_guard as guard
    import jobs.scheduler as sched

    originals = {
        (guard, "run_startup_check"): guard.run_startup_check,
        (main_module, "start_scheduler"): main_module.start_scheduler,
        (main_module, "log_scheduler_startup_health"): main_module.log_scheduler_startup_health,
        (sched, "run_catchup_if_stale"): sched.run_catchup_if_stale,
    }

    def _boom(*a, **k):
        raise RuntimeError("connection reset by peer")

    setattr(guard, "run_startup_check", _boom)
    setattr(main_module, "start_scheduler", lambda *a, **k: called.append("scheduler"))
    setattr(main_module, "log_scheduler_startup_health", lambda *a, **k: called.append("health_log"))
    setattr(sched, "run_catchup_if_stale", lambda *a, **k: called.append("catchup"))
    before = dict(main_module._SCHEMA_DRIFT)
    try:
        main_module._boot_background()
        assert called == ["scheduler", "health_log", "catchup"]
        assert main_module._SCHEMA_DRIFT["missing"] == [], (
            "an exception is not evidence of drift; reporting it as drift would "
            "fail every deploy on a transient hiccup")
    finally:
        for (mod, name), fn in originals.items():
            setattr(mod, name, fn)
        main_module._SCHEMA_DRIFT = before


def test_the_lifespan_starts_the_boot_thread():
    """The wiring itself: entering the app's lifespan must spawn the thread.

    Without this, every test above could pass against an app that simply never
    runs the boot work at all.
    """
    started: list[str] = []
    real = main_module._boot_background
    main_module._boot_background = lambda: started.append("ran")
    before = dict(main_module._SCHEMA_DRIFT)
    try:
        with TestClient(main_module.app):
            for _ in range(200):          # the thread is real; give it a moment
                if started:
                    break
                time.sleep(0.01)
        assert started == ["ran"], "the lifespan did not start the boot thread"
    finally:
        main_module._boot_background = real
        main_module._SCHEMA_DRIFT = before
