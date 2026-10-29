"""A client with nothing on record is "not yet scored", never a score near 100 (ledger POST-A-288).

WHAT WAS WRONG
    The health engine starts every dimension at 100 and takes points off for what it finds (`routers/health._calculate_scores_db`),
    so a client with no returns, no books, no documents and no notices scored 98 (only the portal-login line takes points) and was
    flagged neither critical nor at risk. Since the nightly sweep (POST-A-282) that happened to every new client the first night,
    and the Healthy bar and the firm figure counted it. `client_risk`'s docstring exists to stop "no information" reading as
    "no problem"; the engine did exactly that for a client it had no information about.

THE RULE (decided under the three tests, no practising CA consulted: it follows the file's own rule that an unknown is never
shown as a value)
    A client for whom NONE of the sources the engine reads holds a row (the seven dimensions' tables: compliance records,
    government notices, tasks, document requests, AI insights, bank lines, portal sessions; the two the hard-override detector
    reads on its own: GSTR-3B returns and advance-tax instalments; and the CA's live overrides) has given the engine nothing to
    judge. It stores no score: it reads "not yet scored" (a score it already had, made of nothing, is removed), is counted in
    `unscored` and not in `failed`, and the single-client Calculate answers 409 in words. Any row at all is evidence, a filed
    return and a closed notice included, because they are what a good score is made of. A client whose ONLY record is a GSTR-3B
    overdue by more than two months is Critical, not unscored: the detector reads that table, so the evidence set does too.

WHAT IS HELD (no database)
    * each of the ten sources alone is enough, and another client's rows or another firm's do not count;
    * a probe that cannot be read is a LOST READ, never "nothing there": the client is counted failed and nothing is stored;
    * the real engine refuses a client with nothing on record (`_NothingToScore`) and scores one with a single filed return;
    * the loop stores nothing for it, writes no history row, removes a score it already had (and only that client's), counts it apart
      from the failures, and still scores the others; a removal that fails is a failure;
    * the nightly job is not a failed run when every client is merely unscored, and is one when clients failed and none scored;
    * the single-client route answers 409 with the sentence, removes a score the client had and says so, and stores nothing.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import jobs.health_scores_job as job
import routers.health as hl
from tests.e2e_harness import FakeDB

FIRM, OTHER_FIRM = "f1", "f2"
USER = {"id": "u1", "firm_id": FIRM, "role": "Partner", "auth_user_id": "a1", "email": "p@t.in"}

#: the seven sources the dimensions read, with the row that makes a client "have something on record"
SOURCES = {
    "compliance_records": {"status": "Filed", "due_date": "2026-01-20", "filed_date": "2026-01-18"},
    "government_notices": {"status": "closed"},
    "tasks": {"status": "done", "title": "t"},
    "document_requests": {"status": "fulfilled", "title": "d"},
    "ai_insights": {"status": "dismissed", "severity": "info"},
    "bank_transactions": {"reconciled": True},
    "client_portal_sessions": {},
    "gstr3b_returns": {"status": "draft", "period": "042026"},
    "advance_tax_payments": {"installment_number": 1, "financial_year": "2026-27"},
    "health_overrides": {"is_active": True, "dimension": "compliance_health", "override_score": 60},
}


def _client(db, cid, firm=FIRM):
    db.seed("clients", {"id": cid, "firm_id": firm, "client_name": cid, "is_internal": False, "status": "active", "deleted_at": None})


def _row(table, cid, firm=FIRM, **extra):
    return {"firm_id": firm, "client_id": cid, **SOURCES[table], **extra}


@pytest.fixture(autouse=True)
def _real_engine_setup(monkeypatch):
    # the bank lines are read with the server's own access where there is one; in a test there is only the double
    monkeypatch.setattr(hl, "_bank_db", lambda db: db)
    monkeypatch.setattr(hl, "_expire_what_was_cached_from_the_scores", lambda *a, **k: None)
    monkeypatch.setattr(hl, "_overrides_db", lambda db, client_id, firm_id: [])


# ── the probe ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", sorted(SOURCES))
def test_each_source_alone_is_something_on_record(table):
    db = FakeDB()
    db.seed(table, _row(table, "c1"))
    assert hl._has_anything_to_score_db(db, "c1", FIRM) is True


def test_a_client_with_no_row_in_any_source_has_nothing_on_record_and_other_clients_rows_do_not_count():
    db = FakeDB()
    for table in SOURCES:
        db.seed(table, _row(table, "c-other"))                      # another client of the firm
        db.seed(table, _row(table, "c1", firm=OTHER_FIRM))          # the same id in another firm
    assert hl._has_anything_to_score_db(db, "c1", FIRM) is False


def test_a_probe_that_cannot_be_read_is_a_lost_read_and_not_nothing_there(monkeypatch):
    reported = []
    monkeypatch.setattr(hl, "_report_soft_failure", lambda exc, **kw: reported.append((kw.get("operation"), kw.get("source"))))

    class Unreadable(FakeDB):
        def table(self, name):
            if name == "compliance_records":
                raise RuntimeError("PostgREST is down")
            return super().table(name)

    lost: list = []
    token = hl._lost_reads.set(lost)
    try:
        assert hl._has_anything_to_score_db(Unreadable(), "c1", FIRM) is True       # "we could not look" is not "nothing to look at"
    finally:
        hl._lost_reads.reset(token)
    assert lost == ["health.evidence"] and reported == [("health.evidence", "compliance_records")]


# ── the engine ───────────────────────────────────────────────────────────────

def test_the_real_engine_refuses_a_client_with_nothing_on_record_and_scores_one_with_a_single_filed_return():
    db = FakeDB()
    with pytest.raises(hl._NothingToScore):
        hl._calculate_scores_db(db, "c1", FIRM)
    db.seed("compliance_records", _row("compliance_records", "c1"))
    scores = hl._calculate_scores_db(db, "c1", FIRM)
    assert scores["overall_score"] >= 95 and scores["health_grade"] in ("Healthy", "Good"), scores


def test_a_calculation_that_lost_a_read_is_still_refused_as_incomplete_and_not_as_nothing_to_score(monkeypatch):
    monkeypatch.setattr(hl, "_report_soft_failure", lambda exc, **kw: None)

    class Unreadable(FakeDB):
        def table(self, name):
            if name == "government_notices":
                raise RuntimeError("PostgREST is down")
            return super().table(name)

    db = Unreadable()
    db.seed("compliance_records", _row("compliance_records", "c1"))
    with pytest.raises(hl._ScoreIncomplete):
        hl._calculate_scores_or_say_a_read_was_lost(db, "c1", FIRM)


def test_a_client_whose_only_record_is_a_gstr3b_overdue_by_two_months_is_critical_not_unscored():
    """The hard-override detector reads `gstr3b_returns` on its own, so the table is evidence: a saved, unfiled return from a
    year ago is the finding the detector exists for, and "not yet scored" would hide it."""
    db = FakeDB()
    db.seed("gstr3b_returns", {"firm_id": FIRM, "client_id": "c1", "period": "012025", "status": "draft"})
    scores = hl._calculate_scores_db(db, "c1", FIRM)
    assert scores["hard_override"] == "gstr3b_overdue_2months" and scores["health_grade"] == "Critical", scores
    assert scores["overall_score"] <= 34


def test_a_withdrawn_override_is_not_evidence():
    db = FakeDB()
    db.seed("health_overrides", {"firm_id": FIRM, "client_id": "c1", "is_active": False, "dimension": "compliance_health", "override_score": 60})
    assert hl._has_anything_to_score_db(db, "c1", FIRM) is False


# ── the loop ─────────────────────────────────────────────────────────────────

def _scored_world(*, with_evidence=(), without=(), had_score=()):
    db = FakeDB()
    for cid in (*with_evidence, *without):
        _client(db, cid)
    for cid in with_evidence:
        db.seed("compliance_records", _row("compliance_records", cid))
    for cid in had_score:
        db.seed("health_scores", {"firm_id": FIRM, "client_id": cid, "overall_score": 61, "client_name": cid})
    return db


def test_the_loop_stores_nothing_for_a_client_with_nothing_on_record_counts_it_apart_and_scores_the_others():
    db = _scored_world(with_evidence=["c-live"], without=["c-empty"])
    clients = [{"id": "c-live", "client_name": "c-live"}, {"id": "c-empty", "client_name": "c-empty"}]
    out = hl.recalculate_clients(db, FIRM, clients)
    assert out == {"updated": 1, "failed": 0, "unscored": 1}
    stored = db.table("health_scores").select("client_id").execute().data
    assert [r["client_id"] for r in stored] == ["c-live"], "a score was stored for a client with nothing on record"
    history = db.table("health_score_history").select("client_id").execute().data
    assert [r["client_id"] for r in history] == ["c-live"], "a history row was written for a client with nothing on record"


def test_a_score_a_client_had_is_removed_when_it_has_nothing_on_record_and_only_that_clients():
    """A score stored for a client the engine has nothing to judge was made of nothing (the Calculate button and the client
    Overview stored 98 for empty clients before the sweep did), and left in place it would stay Healthy and counted for ever."""
    db = _scored_world(with_evidence=["c-live"], without=["c-empty"], had_score=["c-empty", "c-live"])
    db.seed("health_score_history", {"firm_id": FIRM, "client_id": "c-empty", "overall_score": 61, "health_grade": "Good"})
    out = hl.recalculate_clients(db, FIRM, [{"id": "c-empty", "client_name": "c-empty"}])
    assert out == {"updated": 0, "failed": 0, "unscored": 1}
    left = {r["client_id"] for r in db.table("health_scores").select("client_id").execute().data}
    assert left == {"c-live"}, "the empty client's score was kept, or another client's was removed"
    assert [r["client_id"] for r in db.table("health_score_history").select("client_id").execute().data] == ["c-empty"], \
        "the history of what was shown was removed"


def test_a_score_made_of_nothing_is_not_removed_from_another_firm_with_the_same_client_id():
    db = _scored_world(without=["c-empty"], had_score=["c-empty"])
    db.seed("health_scores", {"firm_id": OTHER_FIRM, "client_id": "c-empty", "overall_score": 77, "client_name": "x"})
    hl.recalculate_clients(db, FIRM, [{"id": "c-empty", "client_name": "c-empty"}])
    assert [(r["firm_id"], r["overall_score"]) for r in db.table("health_scores").select("firm_id, overall_score").execute().data] == [(OTHER_FIRM, 77)]


def test_a_removal_that_fails_is_a_failure_and_not_an_unscored_client(monkeypatch):
    monkeypatch.setattr(hl, "_report_soft_failure", lambda exc, **kw: None)

    class CannotDelete(FakeDB):
        def table(self, name):
            query = super().table(name)
            if name == "health_scores":
                def refuse(*a, **k):
                    raise RuntimeError("permission denied")
                query.delete = refuse
            return query

    db = CannotDelete()
    _client(db, "c1")
    db.seed("health_scores", {"firm_id": FIRM, "client_id": "c1", "overall_score": 61, "client_name": "c1"})
    out = hl.recalculate_clients(db, FIRM, [{"id": "c1", "client_name": "c1"}])
    assert out == {"updated": 0, "failed": 1, "unscored": 0}


def test_a_client_whose_evidence_probe_was_lost_is_a_failure_and_not_an_unscored_client(monkeypatch):
    monkeypatch.setattr(hl, "_report_soft_failure", lambda exc, **kw: None)

    class Unreadable(FakeDB):
        def table(self, name):
            if name == "tasks":
                raise RuntimeError("PostgREST is down")
            return super().table(name)

    db = Unreadable()
    _client(db, "c1")
    out = hl.recalculate_clients(db, FIRM, [{"id": "c1", "client_name": "c1"}])
    assert out == {"updated": 0, "failed": 1, "unscored": 0}
    assert db.table("health_scores").select("client_id").execute().data == []


# ── the nightly job ──────────────────────────────────────────────────────────

def _job_world(monkeypatch, db):
    monkeypatch.setattr(job, "_USE_MOCK", False)
    monkeypatch.setattr(job, "_get_db", lambda: db)
    monkeypatch.setattr("jobs.memory_job.is_firm_active", lambda firm_id: True)


def test_a_firm_whose_clients_all_have_nothing_on_record_is_not_a_failed_run(monkeypatch):
    db = _scored_world(without=["c1", "c2"])
    _job_world(monkeypatch, db)
    assert job.run_health_scores_for_firm(FIRM) == {"clients": 2, "updated": 0, "failed": 0, "unscored": 2}


def test_a_run_in_which_clients_failed_and_none_was_scored_still_raises(monkeypatch):
    db = _scored_world(with_evidence=["c1"], without=["c2"])
    _job_world(monkeypatch, db)
    monkeypatch.setattr(hl, "_report_soft_failure", lambda exc, **kw: None)
    monkeypatch.setattr(hl, "_calculate_scores_db", lambda _db, cid, fid: (_ for _ in ()).throw(RuntimeError("the engine failed"))
                        if cid == "c1" else (_ for _ in ()).throw(hl._NothingToScore("none")))
    with pytest.raises(RuntimeError, match="clients of firm"):
        job.run_health_scores_for_firm(FIRM)


# ── the single-client route ──────────────────────────────────────────────────

def test_calculate_for_a_client_with_nothing_on_record_answers_409_in_words_and_writes_nothing(monkeypatch):
    db = _scored_world(without=["c1"])
    monkeypatch.setattr(hl, "_db", lambda: db)
    monkeypatch.setattr(hl, "assert_client_access", lambda user, client_id: None)
    with pytest.raises(HTTPException) as refused:
        hl.calculate_score("c1", current_user=USER)
    assert refused.value.status_code == 409 and "nothing recorded that the health score reads" in refused.value.detail
    assert "returns or obligations" in refused.value.detail and "nothing to score yet" in refused.value.detail
    assert "has been removed" not in refused.value.detail              # there was no score to remove
    assert db.table("health_scores").select("client_id").execute().data == []
    assert db.table("health_score_history").select("client_id").execute().data == []


def test_calculate_for_a_client_with_nothing_on_record_removes_the_score_it_had_and_says_so(monkeypatch):
    db = _scored_world(without=["c1"], had_score=["c1"])
    monkeypatch.setattr(hl, "_db", lambda: db)
    monkeypatch.setattr(hl, "assert_client_access", lambda user, client_id: None)
    with pytest.raises(HTTPException) as refused:
        hl.calculate_score("c1", current_user=USER)
    assert refused.value.status_code == 409 and "The score it had, which was made of nothing, has been removed." in refused.value.detail
    assert db.table("health_scores").select("client_id").execute().data == []


def test_calculate_for_a_client_with_one_filed_return_scores_it(monkeypatch):
    db = _scored_world(with_evidence=["c1"])
    monkeypatch.setattr(hl, "_db", lambda: db)
    monkeypatch.setattr(hl, "assert_client_access", lambda user, client_id: None)
    monkeypatch.setattr(hl.timeline_service, "log", lambda *a, **k: None)
    out = hl.calculate_score("c1", current_user=USER)
    assert out["success"] and out["data"]["overall_score"] >= 95
    assert [r["client_id"] for r in db.table("health_scores").select("client_id").execute().data] == ["c1"]
