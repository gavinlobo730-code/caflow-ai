"""
The trusted-rule sweep — job #10b of the daily scheduler run.

WHAT IS ASSERTED
    1. It is a known job, runs inside run_daily_jobs, and is gated like the
       rest (a second run today is skipped).
    2. It sweeps only clients with a trusted rule, proposes for undrafted
       lines first, then passes only what a trusted rule drafted — each as the
       rule's trusted_by — and reports per client what it passed, what was
       refused, and what it left.
    3. In mock mode (no SUPABASE_URL) it does nothing and says so.
"""
from __future__ import annotations

import pytest

import jobs.scheduler as sched
import jobs.bank_trusted_rules_job as job
import services.bank_entry_service as bes
from tests.test_bank_entry_service import _db, _rule, _line, _row, _Poster, CHARGES, RENT
from tests.test_bank_matching import FIRM, CLIENT


def test_it_is_a_known_job_between_the_audit_and_the_memory_pipeline():
    assert "bank_trusted_rules" in sched.KNOWN_JOBS
    assert sched.KNOWN_JOBS.index("bank_trusted_rules") < sched.KNOWN_JOBS.index("memory_pipeline")


def test_run_daily_jobs_includes_it_and_gates_it(monkeypatch):
    calls = []
    monkeypatch.setattr(job, "run_trusted_rules_for_firm",
                        lambda fid, db=None: calls.append(fid) or {"passed": 0, "failed": 0, "clients": {}})
    sched._MOCK_RUNS.clear()
    first = sched.run_daily_jobs(firm_id="F1", force=True)
    assert "bank_trusted_rules" in first["firms"]["F1"] and calls == ["F1"]
    second = sched.run_daily_jobs(firm_id="F1")
    assert second["firms"]["F1"]["bank_trusted_rules"] == {"skipped": "already ran today"}
    assert calls == ["F1"]


def test_mock_mode_does_nothing_and_says_so(monkeypatch):
    monkeypatch.setattr(job, "_USE_MOCK", True)
    assert job.run_trusted_rules_for_firm("F1") == {"clients": {}, "passed": 0, "failed": 0,
                                                    "skipped_mock": True}


def test_the_sweep_proposes_then_passes_only_what_a_trusted_rule_drafted(monkeypatch):
    poster = _Poster()
    monkeypatch.setattr(bes.bank_posting_service, "post", poster)
    monkeypatch.setattr(job, "_USE_MOCK", False)
    db = _db()
    _rule(db, rid="trusted", pattern="CHARGES", is_trusted=True, trusted_by="mgr-1",
          trusted_at="2026-09-03T00:00:00Z")
    _rule(db, rid="plain", pattern="RENT", account=RENT)
    _line(db, "c1", "NEFT CHARGES APR", transaction_date="2026-04-01")
    _line(db, "c2", "NEFT CHARGES MAY", transaction_date="2026-05-01")
    _line(db, "rent", "NEFT RENT")
    _line(db, "unknown", "NOBODY KNOWS")

    out = job.run_trusted_rules_for_firm(FIRM, db=db)

    assert out["passed"] == 2 and out["failed"] == 0
    assert out["clients"][CLIENT] == {"redrafted": 4, "passed": 2, "failed": 0, "remaining": 0}
    assert sorted(c["txn_id"] for c in poster.calls) == ["c1", "c2"]
    assert all(c["actor_id"] == "mgr-1" for c in poster.calls)
    assert _row(db, "c1")["posted_by_rule_id"] == "trusted"
    # The plain rule's line was proposed for but NOT passed; the unknown line
    # was proposed for and found nothing.
    assert _row(db, "rent")["draft_source"] == "rule" and _row(db, "rent")["match_status"] == "unmatched"
    assert _row(db, "unknown")["drafted_at"] and _row(db, "unknown")["draft_source"] is None


def test_a_client_with_no_trusted_rule_is_not_touched(monkeypatch):
    poster = _Poster()
    monkeypatch.setattr(bes.bank_posting_service, "post", poster)
    monkeypatch.setattr(job, "_USE_MOCK", False)
    db = _db()
    _rule(db, rid="plain", pattern="CHARGES")
    _line(db, "c1", "NEFT CHARGES")
    out = job.run_trusted_rules_for_firm(FIRM, db=db)
    assert out == {"clients": {}, "passed": 0, "failed": 0}
    assert poster.calls == [] and _row(db, "c1")["drafted_at"] is None


def test_a_refusal_is_counted_left_on_the_row_and_not_retried(monkeypatch):
    poster = _Poster(refuse={"c1": "Financial year 2026-27 is locked."})
    monkeypatch.setattr(bes.bank_posting_service, "post", poster)
    monkeypatch.setattr(job, "_USE_MOCK", False)
    db = _db()
    _rule(db, rid="trusted", is_trusted=True, trusted_by="mgr-1", trusted_at="2026-09-03T00:00:00Z")
    _line(db, "c1", "NEFT CHARGES")
    out = job.run_trusted_rules_for_firm(FIRM, db=db)
    assert out["failed"] == 1 and out["passed"] == 0
    assert _row(db, "c1")["draft_error"].startswith("Financial year")
    again = job.run_trusted_rules_for_firm(FIRM, db=db)
    assert again["failed"] == 0 and len(poster.calls) == 1
