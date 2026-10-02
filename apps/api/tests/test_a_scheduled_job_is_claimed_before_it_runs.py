"""A scheduled job is CLAIMED before it runs, so two instances cannot both run it (ops-14).

WHAT WAS WRONG
    The daily sweep guarded against a double run with a SELECT (`_already_ran_today`: read
    `scheduler_runs`, find no success, run the job, write the row afterwards), and the
    per-minute workflow tick had no guard at all and carried a docstring saying "NOT safe for
    multi-worker deployments". With one instance that is latent. With two (a rolling deploy
    overlapping the old process, a standby) both run every job and fire every schedule: every
    reminder and every recurring invoice twice. `scheduler_runs` has no unique key, so nothing
    refused the second writer.

WHAT IS ASSERTED, in mock mode (the real-Postgres half is
`test_471_a_scheduled_job_is_claimed_before_it_runs_pg.py`, which races two sessions at the
SQL function and cannot run here):
  * the claim state machine, as a table (`_claim_scenarios.py`), through the in-memory store
    that models it — the same table the SQL is held to;
  * the production store's RPC arguments are exactly the parameters migration 471 declares;
  * the scheduler USES the claim: four threads running the same sweep run each job once; a job
    another instance holds is skipped and its body never called; a job that succeeded is not
    claimable again without force; a failed job is retaken; a dead holder's claim is taken
    over after its lease; the claim is ended AFTER the run row is written, as the right
    status, and survives a failing insert;
  * the missing-migration window is the one failure that runs unclaimed (loudly, once), and
    every other store failure refuses the claim;
  * a live holder renews its lease and a holder whose lease went learns it on finish;
  * the workflow tick claims each OCCURRENCE: two ticks fire a due schedule once, a schedule
    whose claim already succeeded is advanced and not fired again, a failed fire is recorded;
  * the sweep's job list is one list: every job block is gated by `_begin`, none by the old
    bare select, and `KNOWN_JOBS` (what catch-up and health consider) is exactly those jobs.
"""
from __future__ import annotations

import ast
import re
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import jobs.claims as claims  # noqa: E402
import jobs.scheduler as sched  # noqa: E402
from _claim_scenarios import D1, FIRM_A, JOB, SCENARIOS, run as run_scenario  # noqa: E402

API = Path(__file__).resolve().parents[1]


# ── an adapter over the in-memory store, for the scenario table ──────────────────

class _MemoryAdapter:
    def __init__(self):
        self.now = 1_000_000.0
        self.store = claims.MemoryClaimStore(clock=lambda: self.now, persist_finished=True)

    def claim(self, job, date, firm, key, owner, force, retry_after):
        return self.store.claim(job, date, firm, key, owner=owner, lease_seconds=600,
                                force=force, retry_failed_after_seconds=retry_after)

    def finish(self, claim_id, owner, status):
        return self.store.finish(claim_id, owner, status)

    def renew(self, claim_id, owner):
        return self.store.renew(claim_id, owner, 600)

    def expire(self, job, date, firm, key):
        self.store.expire(job, date, firm, key)


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_the_memory_store_follows_the_claim_table(name):
    run_scenario(_MemoryAdapter(), SCENARIOS[name])


def test_a_lease_that_has_not_run_out_is_not_taken_however_late_it_is_asked_for():
    """Premise of the expiry scenario: a lease one second short of its end still holds."""
    a = _MemoryAdapter()
    first = a.claim(JOB, D1, FIRM_A, "", "inst-A", False, 0)
    a.now += 599
    assert a.claim(JOB, D1, FIRM_A, "", "inst-B", False, 0)["claimed"] is False
    a.now += 2
    assert a.claim(JOB, D1, FIRM_A, "", "inst-B", False, 0)["claimed"] is True
    assert first["claimed"]


def test_the_memory_store_refuses_a_lease_the_sql_would_refuse():
    s = claims.MemoryClaimStore()
    for bad in (0, 29, 86401):
        with pytest.raises(ValueError):
            s.claim(JOB, D1, FIRM_A, "", owner="x", lease_seconds=bad, force=False,
                    retry_failed_after_seconds=0)


# ── the production store speaks the SQL's own parameter names ────────────────────

class _FakeRpc:
    def __init__(self, data):
        self.calls = []
        self._data = data

    def rpc(self, name, params):
        self.calls.append((name, params))
        data = self._data

        class _Result:
            pass

        class _Query:
            def execute(self):
                result = _Result()
                result.data = data
                return result

        return _Query()


def _sql_params(function: str) -> list[str]:
    text = (API / "migrations" /
            "471_a_scheduled_job_is_claimed_before_it_runs.sql").read_text(encoding="utf-8")
    head = text.split(f"public.{function}(", 1)[1].split(")", 1)[0]
    return re.findall(r"\b(p_[a-z_]+)\b", head)


def test_the_postgrest_store_sends_exactly_the_parameters_the_functions_declare():
    db = _FakeRpc({"claimed": True, "id": "c1", "attempt": 1})
    store = claims.PostgrestClaimStore(lambda: db)
    store.claim(JOB, D1, FIRM_A, "k", owner="o", lease_seconds=600, force=True,
                retry_failed_after_seconds=5)
    store.renew("c1", "o", 600)
    store.finish("c1", "o", "success")
    store.prune(30)
    sent = {name: set(params) for name, params in db.calls}
    assert sent == {
        "claim_scheduler_job": set(_sql_params("claim_scheduler_job")),
        "renew_scheduler_claim": set(_sql_params("renew_scheduler_claim")),
        "finish_scheduler_claim": set(_sql_params("finish_scheduler_claim")),
        "prune_scheduler_claims": set(_sql_params("prune_scheduler_claims")),
    }
    assert all(sent.values()), "the scan found no parameters, so it would pass vacuously"


def test_the_postgrest_store_refuses_an_answer_that_is_not_a_claim_result():
    store = claims.PostgrestClaimStore(lambda: _FakeRpc(None))
    with pytest.raises(RuntimeError):
        store.claim(JOB, D1, FIRM_A, "", owner="o", lease_seconds=600, force=False,
                    retry_failed_after_seconds=0)


def test_the_functions_are_callable_by_the_service_role_and_nobody_else():
    """Read from the migration: a function is executable by PUBLIC unless that is revoked, and
    these decide who runs a firm's jobs."""
    sql = (API / "migrations" / "471_a_scheduled_job_is_claimed_before_it_runs.sql").read_text()
    for fn in ("claim_scheduler_job", "renew_scheduler_claim", "finish_scheduler_claim",
               "prune_scheduler_claims"):
        assert re.search(rf"REVOKE ALL ON FUNCTION public\.{fn}\([^)]*\)\s+FROM PUBLIC, anon, authenticated;", sql), fn
        assert re.search(rf"GRANT EXECUTE ON FUNCTION public\.{fn}\([^)]*\)\s+TO service_role;", sql), fn
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "REVOKE ALL ON public.scheduler_claims FROM anon, authenticated;" in sql
    assert "CREATE POLICY" not in sql, "a policy on this table would let a signed-in session forge a claim"


# ── the scheduler uses the claim ─────────────────────────────────────────────────

@pytest.fixture
def mock_sched(monkeypatch):
    monkeypatch.setattr(sched, "_USE_MOCK", True)
    monkeypatch.delenv("ENABLE_SCHEDULER", raising=False)
    sched._MOCK_RUNS.clear()
    store = claims.MemoryClaimStore(persist_finished=True)
    claims.set_store(store)
    yield store
    claims.set_store(None)
    sched._MOCK_RUNS.clear()


@pytest.fixture
def one_job(monkeypatch):
    """Only the first job's body matters here; it counts its calls and takes a moment, so a
    second instance really does arrive while the first is still running."""
    calls: list[str] = []
    gate = {"sleep": 0.0, "outcome": {"success": True, "count": 0}}

    def body(firm_id=None):
        calls.append(firm_id)
        time.sleep(gate["sleep"])
        return dict(gate["outcome"])

    monkeypatch.setattr("jobs.recurring_task_job.run_recurring_generation_job", body)
    return calls, gate


def _recurring_runs():
    return [r for r in sched._MOCK_RUNS if r["job_name"] == "recurring_generation"]


def test_four_threads_running_the_same_sweep_run_each_job_once(mock_sched, one_job, monkeypatch):
    """The finding's verify line, in mock mode: the second instance is simulated by threads in
    one process, which is the same race. `_already_ran_today` is held to False so the claim is
    the ONLY thing that can stop a second run — which is exactly what the select could not."""
    calls, gate = one_job
    gate["sleep"] = 0.25
    monkeypatch.setattr(sched, "_already_ran_today", lambda job, firm: False)
    start = threading.Barrier(4)
    results: list[dict] = []

    def go():
        start.wait()
        results.append(sched.run_daily_jobs(firm_id="F1"))

    threads = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in threads]
    [t.join(timeout=60) for t in threads]
    assert len(results) == 4
    assert calls == ["F1"], f"the job body ran {len(calls)} times, not once"
    assert len(_recurring_runs()) == 1 and _recurring_runs()[0]["status"] == "success"
    skipped = [r["firms"]["F1"]["recurring"]["skipped"] for r in results
               if "skipped" in r["firms"]["F1"]["recurring"]]
    assert len(skipped) == 3 and set(skipped) <= {claims.SKIP_TEXT[claims.HELD_BY_ANOTHER],
                                                  claims.SKIP_TEXT[claims.ALREADY_SUCCEEDED]}


def test_a_job_another_instance_holds_is_skipped_and_never_called(mock_sched, one_job):
    calls, _ = one_job
    other = claims.claim("recurring_generation", "F1", run_date=sched.ist_today(),
                         store=mock_sched, owner="the-other-instance")
    assert other.claimed
    out = sched.run_daily_jobs(firm_id="F1")
    assert calls == []
    assert out["firms"]["F1"]["recurring"] == {"skipped": claims.SKIP_TEXT[claims.HELD_BY_ANOTHER]}
    assert _recurring_runs() == [], "a skipped job leaves no run row"


def test_a_success_in_the_claim_table_stops_a_run_whose_row_was_never_written(
        mock_sched, one_job, monkeypatch):
    """`_log_run` is fail-soft (a failed insert is a warning). Before this change that meant a
    job whose row was lost simply ran again; the claim remembers it succeeded."""
    calls, _ = one_job
    first = claims.claim("recurring_generation", "F1", run_date=sched.ist_today(),
                         store=mock_sched, owner="earlier")
    first.claim.finish(True)
    out = sched.run_daily_jobs(firm_id="F1")
    assert calls == []
    assert out["firms"]["F1"]["recurring"]["skipped"] == claims.SKIP_TEXT[claims.ALREADY_SUCCEEDED]


def test_force_runs_a_job_that_already_succeeded_but_not_one_that_is_running(mock_sched, one_job):
    calls, _ = one_job
    done = claims.claim("recurring_generation", "F1", run_date=sched.ist_today(),
                        store=mock_sched, owner="earlier")
    done.claim.finish(True)
    sched.run_daily_jobs(firm_id="F1", force=True)
    assert calls == ["F1"]

    # Another instance is now re-running it under force: that one is live.
    live = claims.claim("recurring_generation", "F1", run_date=sched.ist_today(),
                        store=mock_sched, owner="busy", force=True)
    assert live.claimed
    sched.run_daily_jobs(firm_id="F1", force=True)
    assert calls == ["F1"], "force must not take a claim that is live"


def test_a_failed_job_is_retaken_and_its_claim_is_ended_as_failed(mock_sched, one_job):
    calls, gate = one_job
    gate["outcome"] = {"success": False, "count": 0, "error": "boom"}
    sched.run_daily_jobs(firm_id="F1")
    assert all(r["status"] != "running" for r in mock_sched.rows()), "a claim was left held"
    assert _recurring_runs()[-1]["status"] == "failed"
    gate["outcome"] = {"success": True, "count": 1}
    sched.run_daily_jobs(firm_id="F1")
    assert calls == ["F1", "F1"], "a failure today is retried by the next trigger, as before"
    assert _recurring_runs()[-1]["status"] == "success"


def test_a_dead_holders_claim_is_taken_over_once_its_lease_has_run_out(mock_sched, one_job):
    calls, _ = one_job
    claims.claim("recurring_generation", "F1", run_date=sched.ist_today(),
                 store=mock_sched, owner="crashed-instance")
    sched.run_daily_jobs(firm_id="F1")
    assert calls == []
    mock_sched.expire("recurring_generation", sched.ist_today(), "F1")
    sched.run_daily_jobs(firm_id="F1")
    assert calls == ["F1"]


def test_the_claim_is_ended_after_the_run_row_is_written(mock_sched, one_job, monkeypatch):
    """A process that dies between the two must leave a run row (which `_begin` honours), not a
    finished claim with no record."""
    order: list[str] = []
    real_end = sched._end_claim
    monkeypatch.setattr(sched, "_end_claim",
                        lambda *a, **k: (order.append("end"), real_end(*a, **k))[1])

    class _Log(list):
        def append(self, item):
            order.append("row")
            super().append(item)

    monkeypatch.setattr(sched, "_MOCK_RUNS", _Log())
    sched.run_daily_jobs(firm_id="F1")
    assert order[:2] == ["row", "end"], f"the claim ended before its run row was written: {order[:6]}"


def test_a_failing_run_row_insert_cannot_leave_the_claim_held(mock_sched, monkeypatch):
    class _Boom(list):
        def append(self, item):
            raise RuntimeError("insert failed")

    monkeypatch.setattr(sched, "_MOCK_RUNS", _Boom())
    assert sched._begin("memory_pipeline", "F9", False) is True
    with pytest.raises(RuntimeError):
        sched._log_run("memory_pipeline", "F9", "success", {})
    after = claims.claim("memory_pipeline", "F9", run_date=sched.ist_today(), store=mock_sched,
                         owner="someone-else")
    assert after.reason == claims.ALREADY_SUCCEEDED, (
        "the claim was left running by a failing run-row insert: " + after.reason)


def test_the_run_row_is_still_what_a_finished_job_is_judged_by_before_the_claim_is_asked(
        mock_sched, one_job, monkeypatch):
    """A day's success written BEFORE the claim table existed must still count, and a finished
    job must cost no claim at all."""
    calls, _ = one_job
    asked: list[str] = []
    real_claim = claims.claim
    monkeypatch.setattr(claims, "claim", lambda *a, **k: (asked.append(a[0]), real_claim(*a, **k))[1])
    sched._MOCK_RUNS.append({"job_name": "recurring_generation", "run_date": sched.ist_today().isoformat(),
                             "firm_id": "F1", "status": "success", "detail": {}})
    sched.run_daily_jobs(firm_id="F1")
    assert calls == []
    assert "recurring_generation" not in asked


# ── when the claim store is not there, and when it is merely unwell ──────────────

class _Missing(Exception):
    code = "PGRST202"


class _RaisingStore:
    def __init__(self, exc):
        self.exc = exc

    def claim(self, *a, **k):
        raise self.exc

    def prune(self, *a, **k):
        raise self.exc


def test_a_database_without_migration_471_runs_the_job_as_it_always_did_and_says_so(
        mock_sched, one_job, caplog):
    calls, _ = one_job
    claims._unmanaged_warned = False
    claims.set_store(_RaisingStore(_Missing("Could not find the function public.claim_scheduler_job")))
    with caplog.at_level("ERROR", logger="caflow.jobs.claims"):
        sched.run_daily_jobs(firm_id="F1")
        sched.run_daily_jobs(firm_id="F1", force=True)
    assert calls == ["F1", "F1"]
    errors = [r for r in caplog.records if "NOT in force" in r.getMessage()]
    assert len(errors) == 1, "said once per process, not once per job"
    assert "migration 471" in errors[0].getMessage()


def test_any_other_store_failure_refuses_the_claim_rather_than_opening_the_lock(mock_sched, one_job):
    calls, _ = one_job
    claims.set_store(_RaisingStore(TimeoutError("the database did not answer")))
    out = sched.run_daily_jobs(firm_id="F1")
    assert calls == []
    assert out["firms"]["F1"]["recurring"]["skipped"] == claims.SKIP_TEXT[claims.STORE_UNAVAILABLE]
    assert _recurring_runs() == []


# ── the lease: a live holder renews, a holder that lost it is told ───────────────

def test_a_live_holder_renews_its_lease_while_the_job_is_still_running():
    now = {"t": 1_000.0}
    store = claims.MemoryClaimStore(clock=lambda: now["t"], persist_finished=True)
    decision = claims.claim(JOB, FIRM_A, run_date=D1, store=store, heartbeat=False, owner="me")
    held = decision.claim
    held.start_heartbeat(interval=0.05)
    try:
        now["t"] += 590
        time.sleep(0.3)                      # several beats
        now["t"] += 590                      # past the ORIGINAL lease, inside the renewed one
        assert claims.claim(JOB, FIRM_A, run_date=D1, store=store, owner="rival").claimed is False
    finally:
        assert held.finish(True) is True


def test_a_holder_whose_lease_went_is_told_when_it_finishes(caplog):
    now = {"t": 1_000.0}
    store = claims.MemoryClaimStore(clock=lambda: now["t"], persist_finished=True)
    mine = claims.claim(JOB, FIRM_A, run_date=D1, store=store, owner="me").claim
    now["t"] += 700
    theirs = claims.claim(JOB, FIRM_A, run_date=D1, store=store, owner="them")
    assert theirs.claimed
    with caplog.at_level("ERROR", logger="caflow.jobs.claims"):
        assert mine.finish(True) is False
    assert mine.lost is True
    assert any("no longer this instance" in r.getMessage() for r in caplog.records)
    assert theirs.claim.finish(True) is True


def test_a_heartbeat_that_loses_the_claim_says_so_and_stops(caplog):
    now = {"t": 1_000.0}
    store = claims.MemoryClaimStore(clock=lambda: now["t"], persist_finished=True)
    mine = claims.claim(JOB, FIRM_A, run_date=D1, store=store, owner="me").claim
    now["t"] += 700
    assert claims.claim(JOB, FIRM_A, run_date=D1, store=store, owner="them").claimed
    with caplog.at_level("ERROR", logger="caflow.jobs.claims"):
        mine.start_heartbeat(interval=0.02)
        deadline = time.time() + 3
        # `_beat` sets `lost` and THEN logs, on its own thread, so the flag alone is not the moment
        # the record exists: stopping the wait on it read `caplog.records` in the gap between the
        # two lines (one failure in a CI run, 2 Oct 2026). Wait for what is asserted.
        while time.time() < deadline and not (
                mine.lost and any("running twice" in r.getMessage() for r in caplog.records)):
            time.sleep(0.02)
    assert mine.lost is True
    assert any("running twice" in r.getMessage() for r in caplog.records)


# ── the workflow tick claims each occurrence ─────────────────────────────────────

class _Repo:
    """Just the three calls `run_due_schedules` makes of the workflow repository."""

    def __init__(self, schedules):
        self.schedules = schedules
        self.updates: list[tuple] = []

    def list_schedules_due(self, now_iso):
        return list(self.schedules)

    def update_schedule_run(self, schedule_id, status, next_run):
        self.updates.append((schedule_id, status))


class _Engine:
    def __init__(self, gate=0.0, fail=False):
        self.fired: list[str] = []
        self.gate, self.fail = gate, fail

    def fire_trigger(self, **kw):
        self.fired.append(kw["trigger_data"]["schedule_id"])
        time.sleep(self.gate)
        if self.fail:
            raise RuntimeError("engine said no")


@pytest.fixture
def tick(monkeypatch, mock_sched):
    schedules = [{"id": "S1", "firm_id": "F1", "name": "n", "cron_expression": "0 9 * * *",
                  "timezone": "Asia/Kolkata", "template_id": "T1",
                  "next_run_at": "2026-10-01T03:30:00+00:00"}]
    repo, engine = _Repo(schedules), _Engine()
    import repositories.workflow_repository as wr
    import domain.workflow_engine_v2 as eng
    monkeypatch.setattr(wr, "workflow_repo", repo)
    monkeypatch.setattr(eng, "workflow_engine", engine)
    return repo, engine


def test_two_instances_ticking_at_once_fire_a_due_schedule_once(tick):
    repo, engine = tick
    engine.gate = 0.2
    barrier = threading.Barrier(3)

    def go():
        barrier.wait()
        sched.run_due_schedules()

    threads = [threading.Thread(target=go) for _ in range(3)]
    [t.start() for t in threads]
    [t.join(timeout=30) for t in threads]
    assert engine.fired == ["S1"], f"the schedule fired {len(engine.fired)} times, not once"
    assert repo.updates == [("S1", "success")]


def test_a_schedule_whose_occurrence_already_succeeded_is_advanced_and_not_fired_again(
        tick, mock_sched):
    """The crash between 'fired' and 'schedule advanced': the next tick sees the schedule still
    due. It must move `next_run_at` and must not fire it a second time."""
    repo, engine = tick
    key = "S1@2026-10-01T03:30:00+00:00"
    done = claims.claim("workflow_schedule", "F1", run_date=claims.ist_date_of(
        "2026-10-01T03:30:00+00:00", sched.ist_today()), claim_key=key, store=mock_sched, owner="dead")
    done.claim.finish(True)
    sched.run_due_schedules()
    assert engine.fired == []
    assert repo.updates == [("S1", "success")]


def test_a_failed_fire_is_recorded_and_its_claim_is_ended_before_the_schedule_advances(tick, mock_sched):
    repo, engine = tick
    engine.fail = True
    seen_when_advanced: list[int] = []
    real_update = repo.update_schedule_run

    def update(schedule_id, status, next_run):
        seen_when_advanced.append(sum(1 for r in mock_sched.rows() if r["status"] == "running"))
        real_update(schedule_id, status, next_run)

    repo.update_schedule_run = update
    sched.run_due_schedules()
    assert repo.updates == [("S1", "failed")]
    assert seen_when_advanced == [0], "the claim was still held when the schedule advanced"


def test_a_schedule_another_instance_is_firing_is_left_alone(tick, mock_sched):
    repo, engine = tick
    claims.claim("workflow_schedule", "F1", run_date=claims.ist_date_of(
        "2026-10-01T03:30:00+00:00", sched.ist_today()),
        claim_key="S1@2026-10-01T03:30:00+00:00", store=mock_sched, owner="other")
    sched.run_due_schedules()
    assert engine.fired == [] and repo.updates == []


def test_an_occurrence_is_keyed_on_the_day_it_is_due_not_the_day_it_is_read():
    assert claims.ist_date_of("2026-10-01T19:00:00+00:00", None).isoformat() == "2026-10-02"
    assert claims.ist_date_of("2026-10-01T18:29:00Z", None).isoformat() == "2026-10-01"
    from datetime import date
    assert claims.ist_date_of("not a time", date(2026, 1, 1)) == date(2026, 1, 1)


# ── one list of jobs ─────────────────────────────────────────────────────────────

def _begin_calls() -> list[str]:
    tree = ast.parse((API / "jobs" / "scheduler.py").read_text(encoding="utf-8"))
    run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_daily_jobs")
    out = []
    for node in ast.walk(run):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_begin"
                and node.args and isinstance(node.args[0], ast.Constant)):
            out.append(node.args[0].value)
    return out


def test_every_job_block_is_gated_by_the_claim_and_none_by_the_bare_select():
    tree = ast.parse((API / "jobs" / "scheduler.py").read_text(encoding="utf-8"))
    run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_daily_jobs")
    bare = [n.lineno for n in ast.walk(run)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_already_ran_today"]
    assert not bare, f"run_daily_jobs asks the select directly at lines {bare}: a job gated by it alone is not claimed"
    names = _begin_calls()
    assert len(names) >= 12 and len(names) == len(set(names)), names


def test_known_jobs_is_exactly_the_jobs_the_sweep_runs():
    """Catch-up, the external trigger and the health page all judge 'what is pending' by
    KNOWN_JOBS. Two jobs (recurring_purchase_bills, client_period_metrics) ran in the sweep and
    were absent from it, so a day on which only they failed read as complete."""
    assert sorted(sched.KNOWN_JOBS) == sorted(_begin_calls())


# ── the external trigger's worker ────────────────────────────────────────────────

def test_run_pending_now_refuses_before_the_scheduled_hour_and_runs_nothing(monkeypatch, mock_sched, one_job):
    calls, _ = one_job
    monkeypatch.setattr(sched, "_past_scheduled_hour", lambda: False)
    out = sched.run_pending_now(background=False)
    assert out["started"] is False and "before the scheduled hour" in out["reason"]
    assert calls == []


def test_run_pending_now_runs_what_is_pending_and_a_second_call_finds_nothing_left(
        monkeypatch, mock_sched, one_job):
    calls, _ = one_job
    monkeypatch.setattr(sched, "_past_scheduled_hour", lambda: True)
    monkeypatch.setattr(sched, "_list_firm_ids", lambda: ["F1"])
    out = sched.run_pending_now(background=False)
    assert out["started"] is True and out["pending"] > 0
    assert calls == ["F1"]
    # Mock mode has no database, so the jobs that need one FAIL and stay pending, which is the
    # documented behaviour (a failure today is retried by the next trigger). The job that
    # succeeded is not run again, and is no longer pending.
    again = sched.run_pending_now(background=False)
    assert again["pending"] < out["pending"]
    assert calls == ["F1"], "a job that succeeded was run a second time"


def test_run_pending_now_does_not_need_the_in_process_scheduler_to_be_enabled(
        monkeypatch, mock_sched, one_job):
    """ENABLE_SCHEDULER is off precisely when something else owns the daily run, and an external
    trigger is that something: catch-up refuses in that state, this must not."""
    calls, _ = one_job
    monkeypatch.delenv("ENABLE_SCHEDULER", raising=False)
    monkeypatch.setattr(sched, "_past_scheduled_hour", lambda: True)
    monkeypatch.setattr(sched, "_list_firm_ids", lambda: ["F1"])
    assert sched.run_catchup_if_stale(background=False)["ran"] is False
    assert sched.run_pending_now(background=False)["started"] is True
    assert calls == ["F1"]


def test_run_pending_now_does_not_start_a_second_run_in_the_same_process(monkeypatch, mock_sched, one_job):
    calls, gate = one_job
    gate["sleep"] = 0.4
    monkeypatch.setattr(sched, "_past_scheduled_hour", lambda: True)
    monkeypatch.setattr(sched, "_list_firm_ids", lambda: ["F1"])
    first = sched.run_pending_now(background=True)
    assert first["started"] is True
    second = sched.run_pending_now(background=True)
    assert second["started"] is False and "already in progress" in second["reason"]
    deadline = time.time() + 30
    while sched._pending_run_lock.locked() and time.time() < deadline:
        time.sleep(0.05)
    assert calls == ["F1"]
