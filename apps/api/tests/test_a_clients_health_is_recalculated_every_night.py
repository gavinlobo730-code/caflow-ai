"""A client's health score is recalculated every night, for the clients the dashboards count, by the function the button uses (POST-A-282).

WHAT WAS WRONG
    A client's score was written only by the Health screen's Calculate and Recalculate buttons, and everything that shows a health
    (the executive dashboard, the assistant, the memory profile, the Health pages) reads what was last stored. A firm that never pressed
    the button saw "not yet scored" for every client; one that pressed it last month saw last month's scores. The scores come from
    the books, the returns and the obligations, which change every day.

WHAT IS HELD
    * `routers/health.clients_to_score` is the population: live (not deleted), not archived, never the firm's own practice client,
      the clients `client_repo.find_all` counts, paged past a thousand. The button scored the deleted and the archived too.
    * `routers/health.recalculate_clients` is the one loop (score, trend against the last stored score, upsert, history row, one
      expiry of what was cached from the old scores), used by the button for the caller's clients and by the job for the firm's.
    * `jobs/health_scores_job.run_health_scores_for_firm` runs it for a firm that is active, counts a client that would not score
      without stopping the others, and raises only when it had clients and scored none, so the run row says `failed`.
    * The sweep runs it as a gated, logged, claimed job before the memory pipeline.
"""
from __future__ import annotations

import pytest

import jobs.health_scores_job as job
import jobs.scheduler as sched
import routers.health as hl
from tests.e2e_harness import FakeDB
from tests.health_double import CappedAtMaxRows

FIRM = "f1"


def _clients(db, *rows):
    for row in rows:
        db.seed("clients", {"firm_id": FIRM, "is_internal": False, "status": "active", "deleted_at": None, **row})


def _world(monkeypatch, *, score=70, fails=()):
    """A database, the job pointed at it, and the engine's arithmetic replaced by a fixed answer (it is tested on its own)."""
    db = FakeDB()
    monkeypatch.setattr(job, "_USE_MOCK", False)
    monkeypatch.setattr(job, "_get_db", lambda: db)
    monkeypatch.setattr("jobs.memory_job.is_firm_active", lambda firm_id: True)
    expired: list = []
    import repositories.ai_copilot_repository as repo_module
    monkeypatch.setattr(repo_module.ai_copilot_repo, "expire_summaries",
                        lambda firm_id, kind, entity_id=None: expired.append((firm_id, kind, entity_id)))
    reported: list = []
    monkeypatch.setattr(hl, "_report_soft_failure", lambda exc, operation, **kw: reported.append((operation, kw)))

    def calculate(_db, client_id, firm_id):
        if client_id in fails:
            raise RuntimeError("the engine failed")
        return {"overall_score": score, "health_grade": "Good", "grade": "Good"}

    monkeypatch.setattr(hl, "_calculate_scores_db", calculate)
    return db, expired, reported


# ── who is scored ────────────────────────────────────────────────────────────

def test_the_clients_scored_are_the_live_archived_free_non_internal_clients_of_the_firm():
    db = FakeDB()
    _clients(db, {"id": "live"}, {"id": "archived", "status": "archived"}, {"id": "deleted", "deleted_at": "2026-10-01T00:00:00+00:00"},
             {"id": "practice", "is_internal": True})
    db.seed("clients", {"id": "elsewhere", "firm_id": "other-firm", "is_internal": False, "status": "active", "deleted_at": None})
    assert [c["id"] for c in hl.clients_to_score(db, FIRM)] == ["live"]


def test_every_client_of_a_large_firm_is_scored_past_a_thousand_rows():
    db = FakeDB()
    for i in range(2350):
        _clients(db, {"id": f"{i:05d}", "client_name": f"C{i}"})
    assert len(hl.clients_to_score(CappedAtMaxRows(db), FIRM)) == 2350


def test_the_name_travels_with_the_client_for_the_health_list():
    db = FakeDB()
    _clients(db, {"id": "a", "client_name": "Anand & Co", "pan": "AAAPA1234A"})
    assert hl.clients_to_score(db, FIRM) == [{"id": "a", "client_name": "Anand & Co"}]


# ── what a run writes ────────────────────────────────────────────────────────

def test_a_run_stores_each_clients_score_with_its_name_and_one_history_row(monkeypatch):
    db, expired, _ = _world(monkeypatch)
    _clients(db, {"id": "a", "client_name": "Anand & Co"}, {"id": "b", "client_name": "Bose Ltd"})
    out = job.run_health_scores_for_firm(FIRM)
    assert out == {"clients": 2, "updated": 2, "failed": 0}
    stored = {r["client_id"]: r for r in db._tables["health_scores"]}
    assert set(stored) == {"a", "b"} and stored["a"]["client_name"] == "Anand & Co" and stored["a"]["overall_score"] == 70
    assert stored["a"]["firm_id"] == FIRM and stored["a"]["last_calculated_at"]
    history = db._tables["health_score_history"]
    assert sorted(h["client_id"] for h in history) == ["a", "b"] and all(h["overall_score"] == 70 for h in history)


def test_a_second_night_replaces_the_stored_score_keeps_one_row_and_adds_history_and_a_trend(monkeypatch):
    db, _, _ = _world(monkeypatch, score=70)
    _clients(db, {"id": "a", "client_name": "A"})
    job.run_health_scores_for_firm(FIRM)
    monkeypatch.setattr(hl, "_calculate_scores_db", lambda _db, cid, fid: {"overall_score": 64, "health_grade": "Needs Attention"})
    job.run_health_scores_for_firm(FIRM)
    rows = db._tables["health_scores"]
    assert len(rows) == 1 and rows[0]["overall_score"] == 64 and rows[0]["trend"] == "-6"
    assert len(db._tables["health_score_history"]) == 2


def test_what_was_cached_from_the_old_scores_is_marked_stale_once_per_run(monkeypatch):
    db, expired, _ = _world(monkeypatch)
    _clients(db, {"id": "a"}, {"id": "b"}, {"id": "c"})
    job.run_health_scores_for_firm(FIRM)
    assert expired == [(FIRM, "executive", None), (FIRM, "client", None)], "the dashboard and every client's report, once, not three times"


def test_a_firm_with_no_clients_runs_clean_and_expires_nothing(monkeypatch):
    _, expired, _ = _world(monkeypatch)
    assert job.run_health_scores_for_firm(FIRM) == {"clients": 0, "updated": 0, "failed": 0} and expired == []


# ── a client that will not score ─────────────────────────────────────────────

def test_one_client_that_will_not_score_is_counted_and_reported_and_the_others_are_scored(monkeypatch):
    db, expired, reported = _world(monkeypatch, fails=("b",))
    _clients(db, {"id": "a"}, {"id": "b"}, {"id": "c"})
    out = job.run_health_scores_for_firm(FIRM)
    assert out == {"clients": 3, "updated": 2, "failed": 1}
    assert sorted(r["client_id"] for r in db._tables["health_scores"]) == ["a", "c"]
    assert [(op, kw["firm_id"], kw["client_id"]) for op, kw in reported] == [("health.recalculate_all", FIRM, "b")]
    assert expired, "the two that were saved still expire the caches"


def test_a_run_that_scored_no_client_at_all_raises_so_the_sweep_records_it_failed(monkeypatch):
    db, expired, _ = _world(monkeypatch, fails=("a", "b"))
    _clients(db, {"id": "a"}, {"id": "b"})
    with pytest.raises(RuntimeError, match="no client of firm f1 could be scored"):
        job.run_health_scores_for_firm(FIRM)
    assert expired == [] and "health_scores" not in db._tables


# ── when it does not run ─────────────────────────────────────────────────────

def test_a_deactivated_firm_is_not_scored(monkeypatch):
    db, expired, _ = _world(monkeypatch)
    monkeypatch.setattr("jobs.memory_job.is_firm_active", lambda firm_id: False)
    _clients(db, {"id": "a"})
    assert job.run_health_scores_for_firm(FIRM) == {"skipped": "firm inactive"}
    assert "health_scores" not in db._tables and expired == []


def test_the_job_reads_and_writes_as_the_service_because_no_one_is_calling():
    """A sweep has no signed-in caller, so a client built from a caller's session would be an anonymous one that row security refuses."""
    import inspect
    assert "_get_db = db_provider.service_db" in inspect.getsource(job)
    assert "request_db" not in inspect.getsource(job).replace("service_db", "")


def test_without_a_database_it_does_nothing_and_says_so(monkeypatch):
    monkeypatch.setattr(job, "_USE_MOCK", True)
    monkeypatch.setattr(job, "_get_db", lambda: pytest.fail("the database was asked"))
    assert job.run_health_scores_for_firm(FIRM) == {"skipped": "no database"}


# ── the sweep ────────────────────────────────────────────────────────────────

def test_it_is_a_known_job_before_the_memory_pipeline_which_profiles_the_scores():
    assert "health_scores" in sched.KNOWN_JOBS
    assert sched.KNOWN_JOBS.index("health_scores") < sched.KNOWN_JOBS.index("memory_pipeline")
    assert sched.KNOWN_JOBS.index("health_scores") > sched.KNOWN_JOBS.index("bank_trusted_rules")


def test_the_sweep_runs_it_once_a_day_and_logs_the_run(monkeypatch):
    calls: list = []
    monkeypatch.setattr(job, "run_health_scores_for_firm", lambda fid: calls.append(fid) or {"clients": 0, "updated": 0, "failed": 0})
    sched._MOCK_RUNS.clear()
    first = sched.run_daily_jobs(firm_id="F1", force=True)
    assert first["firms"]["F1"]["health_scores"] == {"clients": 0, "updated": 0, "failed": 0} and calls == ["F1"]
    second = sched.run_daily_jobs(firm_id="F1")
    assert second["firms"]["F1"]["health_scores"] == {"skipped": "already ran today"} and calls == ["F1"]
    ran = [r["job_name"] for r in sched._MOCK_RUNS]
    assert ran.index("health_scores") < ran.index("memory_pipeline")


def test_a_failing_health_job_is_recorded_failed_and_does_not_stop_the_memory_pipeline(monkeypatch):
    def boom(fid):
        raise RuntimeError("no client could be scored")

    monkeypatch.setattr(job, "run_health_scores_for_firm", boom)
    sched._MOCK_RUNS.clear()
    results = sched.run_daily_jobs(firm_id="F1", force=True)
    assert results["firms"]["F1"]["health_scores"] == {"error": "no client could be scored"}
    assert [r["status"] for r in sched._MOCK_RUNS if r["job_name"] == "health_scores"] == ["failed"]
    assert any(r["job_name"] == "memory_pipeline" for r in sched._MOCK_RUNS)


# ── the button uses the same loop and the same population ────────────────────

def test_the_recalculate_button_scores_the_callers_clients_through_the_same_loop(monkeypatch):
    db, expired, _ = _world(monkeypatch)
    _clients(db, {"id": "a"}, {"id": "b"}, {"id": "archived", "status": "archived"})
    monkeypatch.setattr(hl, "_db", lambda: db)
    monkeypatch.setattr(hl, "effective_client_ids", lambda user: {"a"})
    out = hl.recalculate_all(current_user={"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Manager"})
    assert out["data"] == {"updated": 1, "failed": 0}
    assert [r["client_id"] for r in db._tables["health_scores"]] == ["a"] and expired


# ── how old a stored score is ────────────────────────────────────────────────

def _scored(cid, stamp, score=50):
    return {"id": cid, "health_score": score, "health_calculated_at": stamp}


def test_the_basis_counts_the_scored_and_names_the_oldest_day_the_indian_way():
    from domain.practice import executive_dashboard as ed
    clients = [_scored("a", "2026-10-19T19:00:00+00:00"), _scored("b", "2026-10-20T01:00:00+00:00"), {"id": "c", "health_score": None}]
    assert ed.score_basis(clients) == {"scored": 2, "clients": 3, "oldest_calculated_on": "2026-10-20", "unreadable": False}, \
        "19:00 UTC on the 19th is the 20th in India, so both are the 20th"


def test_a_score_with_no_recorded_time_is_counted_and_dates_nothing():
    from domain.practice import executive_dashboard as ed
    assert ed.score_basis([_scored("a", None)]) == {"scored": 1, "clients": 1, "oldest_calculated_on": None, "unreadable": False}


def test_an_unscored_client_never_dates_the_figure():
    from domain.practice import executive_dashboard as ed
    stale = {"id": "x", "health_score": None, "health_calculated_at": "2020-01-01T00:00:00+00:00"}
    assert ed.score_basis([stale, _scored("a", "2026-10-20T01:00:00+00:00")])["oldest_calculated_on"] == "2026-10-20"


def test_the_stored_time_travels_from_the_row_to_the_client():
    from domain.health.client_scores import attach
    got = attach([{"id": "a"}, {"id": "b"}, {"id": "c"}],
                 [{"client_id": "a", "overall_score": 50, "last_calculated_at": "2026-10-20T01:00:00+00:00"},
                  {"client_id": "b", "overall_score": 50, "last_calculated_at": None},
                  {"client_id": "c", "overall_score": 50, "last_calculated_at": 20261020}])
    assert [c["health_calculated_at"] for c in got] == ["2026-10-20T01:00:00+00:00", None, None], "a stamp that is not text is not a time"


def test_a_cached_dashboard_from_before_the_basis_existed_is_not_served():
    from domain.practice import executive_dashboard as ed
    assert ed.DASHBOARD_VERSION >= 6, "version 5 payloads carry a firm health figure with no basis"


# ── what the review found ────────────────────────────────────────────────────

def test_a_calculation_that_lost_a_read_stores_nothing_and_leaves_the_last_good_score(monkeypatch):
    """Every dimension counts as 100 when its own read fails. A score STORED from that would replace a Critical one with a Healthy
    one, for every client a failing read touched, every night."""
    db, expired, reported = _world(monkeypatch)
    _clients(db, {"id": "a", "client_name": "A"}, {"id": "b", "client_name": "B"})
    db.seed("health_scores", {"id": "old", "client_id": "a", "firm_id": FIRM, "overall_score": 34, "is_critical": True, "client_name": "A"})

    def calculate(_db, client_id, firm_id):
        if client_id == "a":
            hl.capture_soft_failure(RuntimeError("timeout"), operation="health.dim_compliance_health_db", firm_id=firm_id)
        return {"overall_score": 98, "health_grade": "Healthy"}

    monkeypatch.setattr(hl, "_calculate_scores_db", calculate)
    out = job.run_health_scores_for_firm(FIRM)
    assert out == {"clients": 2, "updated": 1, "failed": 1}
    assert hl._lost_reads.get() is None, "the collector is put back after each calculation, so later swallowed reads are not collected"
    stored = {r["client_id"]: r for r in db._tables["health_scores"]}
    assert stored["a"]["overall_score"] == 34 and stored["a"]["is_critical"] is True, "the last good score stays"
    assert stored["b"]["overall_score"] == 98
    assert [h["client_id"] for h in db._tables["health_score_history"]] == ["b"], "no history row for a score that was not stored"
    ops = [(op, kw.get("client_id")) for op, kw in reported]
    assert ("health.recalculate_all", "a") in ops, "the client whose score was not stored is reported by id"
    assert any(op == "health.dim_compliance_health_db" for op, _ in reported), "the lost read is still reported where it happened"


def test_a_client_never_scored_whose_calculation_lost_a_read_stays_unscored(monkeypatch):
    db, _, _ = _world(monkeypatch)
    _clients(db, {"id": "a"})

    def calculate(_db, client_id, firm_id):
        hl.capture_soft_failure(RuntimeError("timeout"), operation="health.dim_x_db")
        return {"overall_score": 98, "health_grade": "Healthy"}

    monkeypatch.setattr(hl, "_calculate_scores_db", calculate)
    with pytest.raises(RuntimeError, match="could be scored"):
        job.run_health_scores_for_firm(FIRM)
    assert "health_scores" not in db._tables


def test_the_real_engine_over_a_database_whose_compliance_read_fails_does_not_overwrite_a_critical_score(monkeypatch):
    """The reviewer's reproduction, with the real engine: one timeout on `compliance_records` used to store 98 over a stored 34."""
    class _Flaky(FakeDB):
        broken = False

        def table(self, name):
            if self.broken and name == "compliance_records":
                raise RuntimeError("statement timeout")
            return super().table(name)

    db = _Flaky()
    monkeypatch.setattr(job, "_USE_MOCK", False)
    monkeypatch.setattr(job, "_get_db", lambda: db)
    monkeypatch.setattr("jobs.memory_job.is_firm_active", lambda firm_id: True)
    monkeypatch.setattr(hl, "_report_soft_failure", lambda exc, operation, **kw: None)
    import repositories.ai_copilot_repository as repo_module
    monkeypatch.setattr(repo_module.ai_copilot_repo, "expire_summaries", lambda *a, **k: None)
    _clients(db, {"id": "a", "client_name": "A"})
    db.seed("compliance_records", {"id": "r1", "firm_id": FIRM, "client_id": "a", "compliance_type": "ITR", "status": "Not Started",
                                   "due_date": "2026-07-31"})
    db.seed("health_scores", {"id": "old", "client_id": "a", "firm_id": FIRM, "overall_score": 34, "is_critical": True, "client_name": "A"})
    db.broken = True
    with pytest.raises(RuntimeError, match="could be scored"):
        job.run_health_scores_for_firm(FIRM)
    row, = db._tables["health_scores"]
    assert row["overall_score"] == 34 and row["is_critical"] is True and "last_calculated_at" not in row, "the stored 34 survived the failed read"
    db.broken = False
    assert job.run_health_scores_for_firm(FIRM)["updated"] == 1
    row, = db._tables["health_scores"]
    assert row["last_calculated_at"], "with the read back, the same row is recalculated and stamped"


def test_a_manager_with_no_assigned_client_recalculates_nobody(monkeypatch):
    db, expired, _ = _world(monkeypatch)
    _clients(db, {"id": "a"}, {"id": "b"})
    monkeypatch.setattr(hl, "_db", lambda: db)
    monkeypatch.setattr(hl, "effective_client_ids", lambda user: set())
    out = hl.recalculate_all(current_user={"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Manager"})
    assert out["data"] == {"updated": 0, "failed": 0} and "health_scores" not in db._tables and expired == []


def test_the_trend_is_signed_and_is_against_that_clients_own_previous_score_in_that_firm(monkeypatch):
    db, _, _ = _world(monkeypatch, score=70)
    _clients(db, {"id": "a"}, {"id": "b"})
    db.seed("health_scores", {"id": "px", "client_id": "a", "firm_id": "other-firm", "overall_score": 10})
    db.seed("health_scores", {"id": "pb", "client_id": "b", "firm_id": FIRM, "overall_score": 75})
    db.seed("health_scores", {"id": "pa", "client_id": "a", "firm_id": FIRM, "overall_score": 64})
    job.run_health_scores_for_firm(FIRM)
    mine = {r["client_id"]: r["trend"] for r in db._tables["health_scores"] if r["firm_id"] == FIRM}
    assert mine == {"a": "+6", "b": "-5"}


def test_the_history_row_carries_the_firm_the_grade_and_the_snapshot_and_the_stamp_is_now(monkeypatch):
    from datetime import datetime, timezone
    db, _, _ = _world(monkeypatch)
    _clients(db, {"id": "a", "client_name": "A"})
    job.run_health_scores_for_firm(FIRM)
    row, = db._tables["health_score_history"]
    assert row["firm_id"] == FIRM and row["health_grade"] == "Good" and row["overall_score"] == 70
    assert row["snapshot_data"] and row["snapshot_data"]["overall_score"] == 70 and row["recorded_at"]
    stored, = db._tables["health_scores"]
    for stamp in (stored["last_calculated_at"], row["recorded_at"]):
        assert abs((datetime.now(timezone.utc) - datetime.fromisoformat(stamp)).total_seconds()) < 60, stamp


def test_any_error_in_the_job_is_recorded_not_only_a_runtime_one(monkeypatch):
    def boom(fid):
        raise ValueError("a database error from the paged read")

    monkeypatch.setattr(job, "run_health_scores_for_firm", boom)
    sched._MOCK_RUNS.clear()
    results = sched.run_daily_jobs(firm_id="F1", force=True)
    assert results["firms"]["F1"]["health_scores"] == {"error": "a database error from the paged read"}
    assert any(r["job_name"] == "memory_pipeline" for r in sched._MOCK_RUNS), "the sweep went on"


def test_the_run_row_records_the_outcome_the_firm_and_when_it_started(monkeypatch):
    monkeypatch.setattr(job, "run_health_scores_for_firm", lambda fid: {"clients": 3, "updated": 2, "failed": 1})
    sched._MOCK_RUNS.clear()
    sched.run_daily_jobs(firm_id="F1", force=True)
    row, = [r for r in sched._MOCK_RUNS if r["job_name"] == "health_scores"]
    assert (row["status"], row["firm_id"], row["detail"]) == ("success", "F1", {"clients": 3, "updated": 2, "failed": 1})
    assert row["started_at"] and row["finished_at"] and row["started_at"] <= row["finished_at"]


def test_a_basis_with_a_scored_client_that_has_no_recorded_time_names_no_day():
    from domain.practice import executive_dashboard as ed
    clients = [_scored("a", "2026-10-20T01:00:00+00:00"), _scored("b", None)]
    assert ed.score_basis(clients) == {"scored": 2, "clients": 2, "oldest_calculated_on": None, "unreadable": False}


def test_scores_that_could_not_be_read_are_said_so_in_the_basis(monkeypatch):
    import domain.ai_copilot_service as service

    class _Broken:
        def find_all(self, **kw):
            raise RuntimeError("unreachable")

    monkeypatch.setattr(service, "_get_health_repo", lambda: _Broken())
    from domain.practice import executive_dashboard as ed
    basis = ed.score_basis(service._with_health(FIRM, [{"id": "a"}, {"id": "b"}]))
    assert basis == {"scored": 0, "clients": 2, "oldest_calculated_on": None, "unreadable": True}


def test_a_lost_read_of_one_client_is_not_blamed_on_the_next(monkeypatch):
    """The first client loses a read; the second calculates cleanly right after it and is stored."""
    db, _, _ = _world(monkeypatch)
    _clients(db, {"id": "a"}, {"id": "b"}, {"id": "c"})

    def calculate(_db, client_id, firm_id):
        if client_id == "a":
            hl.capture_soft_failure(RuntimeError("timeout"), operation="health.dim_x_db")
        return {"overall_score": 70, "health_grade": "Good"}

    monkeypatch.setattr(hl, "_calculate_scores_db", calculate)
    assert job.run_health_scores_for_firm(FIRM) == {"clients": 3, "updated": 2, "failed": 1}
    assert sorted(r["client_id"] for r in db._tables["health_scores"]) == ["b", "c"]


def test_a_swallowed_read_outside_a_calculation_is_still_only_reported(monkeypatch):
    reported: list = []
    monkeypatch.setattr(hl, "_report_soft_failure", lambda exc, operation, **kw: reported.append(operation))
    hl.capture_soft_failure(RuntimeError("x"), operation="health.elsewhere")
    assert reported == ["health.elsewhere"] and hl._lost_reads.get() is None
