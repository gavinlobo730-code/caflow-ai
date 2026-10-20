"""A client's health is the health engine's stored score, and a client with none is "not yet scored" (POST-A-279).

WHAT WAS WRONG (found by opening the seeded demo firm in a browser, 19-10-2026)
    The executive dashboard said a firm health of 100 and every client Healthy, beside a Deadlines screen with 220 overdue filings and
    a client Health screen that scored one of the clients 34 and Critical. It read `clients.health_score`, which is `INTEGER DEFAULT
    100` (migration 003) and which no code path writes; the engine's result lives in `health_scores`, written by the Health
    screen's Calculate and Recalculate and read by that screen. So did the assistant's prompts (at-risk and critical client counts, a
    client's "HEALTH SCORE" line, the client report) and the AI memory profile's portfolio figure (which, with no scores, invented 75).

WHAT IS HELD
    * `domain/health/client_scores.attach` puts the engine's stored overall score on each client, and None where it has none; the
      unwritten column on the client row is overwritten either way.
    * `repositories/health_scores_repository` reads the firm's rows, firm-scoped and paged; it requires a firm, reads one client by its key
      when one is asked for and has no in-memory twin (without a database nothing is scored).
    * The dashboard, the assistant's context and report and the memory profile all read through it; a read that fails leaves every
      client "not yet scored" and never healthy.
    * A calculation expires what was cached from the old scores: the executive dashboard, and the client's own intelligence report (or,
      for a recalculation, every client's), which states the score.
    * The demo seeder calculates each client it wrote, last, and exits non-zero for one the server would not score.
"""
from __future__ import annotations

import asyncio

import pytest

import domain.ai_copilot_service as mod
import domain.memory_pipeline as memory
from domain.health.client_scores import attach
from tests.e2e_harness import FakeDB
from tests.health_double import StoredScoresFrom

FIRM = "f1"


# ── the rule ─────────────────────────────────────────────────────────────────

def test_the_engines_score_is_attached_and_the_unwritten_column_is_overwritten_either_way():
    clients = [{"id": "a", "health_score": 100, "name": "A"}, {"id": "b", "health_score": 100}, {"id": "c"}]
    got = attach(clients, [{"client_id": "a", "overall_score": 34}])
    assert [c["health_score"] for c in got] == [34, None, None], "b carried the column's default 100 and has no stored score"
    assert got[0]["name"] == "A", "the rest of the row is kept"
    assert clients[1]["health_score"] == 100, "the caller's rows are not changed"


@pytest.mark.parametrize("bad", [None, True, "34", "", [], {}])
def test_a_stored_value_that_is_not_a_number_is_not_a_score(bad):
    assert attach([{"id": "a"}], [{"client_id": "a", "overall_score": bad}])[0]["health_score"] is None


def test_a_score_is_a_whole_number_and_zero_is_a_score_not_an_absence():
    got = attach([{"id": "a"}, {"id": "b"}], [{"client_id": "a", "overall_score": 0}, {"client_id": "b", "overall_score": 61.0}])
    assert [c["health_score"] for c in got] == [0, 61]
    assert type(got[1]["health_score"]) is int


def test_a_row_for_a_client_that_is_not_in_the_list_is_ignored_and_ids_compare_as_text():
    got = attach([{"id": 7}], [{"client_id": "7", "overall_score": 50}, {"client_id": "elsewhere", "overall_score": 5}])
    assert got == [{"id": 7, "health_score": 50, "health_critical": False, "health_at_risk": False}]


# ── the repository ───────────────────────────────────────────────────────────

def test_the_repository_reads_this_firms_rows_only(monkeypatch):
    import repositories.health_scores_repository as repo_module
    db = FakeDB()
    db.seed("health_scores", {"id": "1", "firm_id": FIRM, "client_id": "a", "overall_score": 34, "is_critical": True,
                              "is_at_risk": False, "last_calculated_at": "2026-10-19T18:10:26+00:00"})
    db.seed("health_scores", {"id": "2", "firm_id": "other-firm", "client_id": "b", "overall_score": 90})
    monkeypatch.setattr(repo_module, "_USE_MOCK", False)
    monkeypatch.setattr(repo_module, "_get_db", lambda: db)
    rows = repo_module.health_scores_repo.find_all(firm_id=FIRM)
    assert [(r["client_id"], r["overall_score"]) for r in rows] == [("a", 34)]


def test_one_client_is_read_by_its_key(monkeypatch):
    import repositories.health_scores_repository as repo_module
    db = FakeDB()
    for i, client in enumerate(("a", "b")):
        db.seed("health_scores", {"id": str(i), "firm_id": FIRM, "client_id": client, "overall_score": 30 + i})
    monkeypatch.setattr(repo_module, "_USE_MOCK", False)
    monkeypatch.setattr(repo_module, "_get_db", lambda: db)
    assert [r["client_id"] for r in repo_module.health_scores_repo.find_all(firm_id=FIRM, client_id="b")] == ["b"]
    assert [r["client_id"] for r in repo_module.health_scores_repo.find_all(firm_id=FIRM)] == ["a", "b"]


def test_without_a_database_nothing_is_scored(monkeypatch):
    """There is no in-memory health_scores table, and the mock clients carry no score: an empty list is the honest answer."""
    import repositories.health_scores_repository as repo_module
    monkeypatch.setattr(repo_module, "_USE_MOCK", True)
    assert repo_module.health_scores_repo.find_all(firm_id=FIRM) == []


@pytest.mark.parametrize("no_firm", [None, ""])
@pytest.mark.parametrize("mock", [True, False])
def test_a_read_that_names_no_firm_is_refused_in_either_mode(monkeypatch, mock, no_firm):
    """A read with no firm would be a read of every firm's scores (the real client filters on `firm_id = None`, mock returned all)."""
    import repositories.health_scores_repository as repo_module
    monkeypatch.setattr(repo_module, "_USE_MOCK", mock)
    monkeypatch.setattr(repo_module, "_get_db", lambda: pytest.fail("the database was asked"))
    with pytest.raises(ValueError):
        repo_module.health_scores_repo.find_all(firm_id=no_firm)


class _Capped:
    """A database whose every response is cut at PostgREST's `db-max-rows`, the way the real one answers a read it was not told to page."""
    def __init__(self, db, cap=1000):
        self.db, self.cap = db, cap

    def table(self, name):
        return _CappedQuery(self.db.table(name), self.cap)


class _CappedQuery:
    def __init__(self, query, cap):
        self.query, self.cap = query, cap

    def __getattr__(self, name):
        attribute = getattr(self.query, name)
        if not callable(attribute):
            return attribute

        def call(*args, **kwargs):
            out = attribute(*args, **kwargs)
            if name == "execute":
                out.data = (out.data or [])[:self.cap]
                return out
            return self if out is self.query else out
        return call


def test_a_firm_of_more_clients_than_one_response_holds_is_read_whole(monkeypatch):
    """A firm with over a thousand clients would otherwise have its first thousand scored and the rest 'not yet scored', silently."""
    import repositories.health_scores_repository as repo_module
    db = FakeDB()
    for i in range(2350):
        db.seed("health_scores", {"id": f"{i:05d}", "firm_id": FIRM, "client_id": f"c{i}", "overall_score": 50})
    db.seed("health_scores", {"id": "99999", "firm_id": "other-firm", "client_id": "x", "overall_score": 5})
    monkeypatch.setattr(repo_module, "_USE_MOCK", False)
    monkeypatch.setattr(repo_module, "_get_db", lambda: _Capped(db))
    assert len(repo_module.health_scores_repo.find_all(firm_id=FIRM)) == 2350


# ── the assistant ────────────────────────────────────────────────────────────

class _Clients:
    def __init__(self, rows):
        self.rows = rows

    def find_all(self, **kw):
        return list(self.rows)

    def find_by_id(self, cid, **kw):
        return next((c for c in self.rows if c["id"] == cid), None)


class _Compliance:
    def find_all(self, **kw):
        return []


def _assistant(monkeypatch, clients, scored):
    monkeypatch.setattr(mod, "_get_client_repo", lambda: _Clients(clients))
    monkeypatch.setattr(mod, "_get_health_repo", lambda: StoredScoresFrom(scored))
    monkeypatch.setattr(mod, "_get_compliance_records_repo", lambda: _Compliance())
    return mod.ai_copilot_service


CLIENTS = [{"id": "c1", "status": "active", "health_score": 100}, {"id": "c2", "status": "active", "health_score": 100},
           {"id": "c3", "status": "active", "health_score": 100}]


def test_the_assistants_at_risk_and_critical_counts_come_from_the_stored_scores(monkeypatch):
    svc = _assistant(monkeypatch, CLIENTS, [{"id": "c1", "health_score": 34}, {"id": "c2", "health_score": 45}])
    context = svc._build_context(FIRM, "global", None, None)
    assert "CRITICAL CLIENTS: 1" in context and "AT-RISK CLIENTS: 2" in context, context
    # c3 carries the column's 100 and was never scored: it is neither at risk nor critical, and it is not called healthy either.


def test_the_boundaries_are_the_engines_34_is_critical_35_to_49_is_at_risk_and_50_is_neither(monkeypatch):
    clients = [{"id": f"c{i}", "status": "active"} for i in range(4)]
    svc = _assistant(monkeypatch, clients, [{"id": "c0", "health_score": 34}, {"id": "c1", "health_score": 35},
                                            {"id": "c2", "health_score": 49}, {"id": "c3", "health_score": 50}])
    context = svc._build_context(FIRM, "global", None, None)
    assert "CRITICAL CLIENTS: 1" in context, "34 is critical; 35 is not"
    assert "AT-RISK CLIENTS: 3" in context, "34, 35 and 49 are flagged (the critical one is counted in at-risk, as it always was); 50 is not"


def test_a_clients_own_status_still_counts_it_at_risk_or_critical_with_no_score(monkeypatch):
    """The status is a second, older signal and stays; only a missing score stops counting as one."""
    clients = [{"id": "c1", "status": "critical"}, {"id": "c2", "status": "at_risk"}, {"id": "c3", "status": "active"}]
    context = _assistant(monkeypatch, clients, [])._build_context(FIRM, "global", None, None)
    assert "CRITICAL CLIENTS: 1" in context and "AT-RISK CLIENTS: 2" in context, context


def test_a_firm_where_nothing_is_scored_has_no_at_risk_or_critical_client_by_score(monkeypatch):
    svc = _assistant(monkeypatch, CLIENTS, [])
    context = svc._build_context(FIRM, "global", None, None)
    assert "CRITICAL CLIENTS: 0" in context and "AT-RISK CLIENTS: 0" in context


def test_a_clients_context_line_says_the_stored_score_or_that_there_is_none(monkeypatch):
    svc = _assistant(monkeypatch, CLIENTS, [{"id": "c1", "health_score": 34}])
    assert "HEALTH SCORE: 34/100" in svc._build_context(FIRM, "client", "c1", None)
    assert "HEALTH SCORE: not yet scored" in svc._build_context(FIRM, "client", "c2", None)


def test_the_client_report_prompt_carries_the_stored_score_or_says_there_is_none(monkeypatch):
    sent: list = []

    class _Summaries:
        def get_summary(self, *a, **k):
            return None

        def upsert_summary(self, firm_id, kind, entity, row):
            return row

    async def capture(messages, **kw):
        sent.append(" ".join(m["content"] for m in messages))
        return "ok", 1

    for client_id, expected in (("c1", "Health Score: 34/100"), ("c2", "Health Score: not yet scored")):
        svc = _assistant(monkeypatch, CLIENTS, [{"id": "c1", "health_score": 34}])
        monkeypatch.setattr(svc, "_call_groq", capture)
        monkeypatch.setattr(svc, "_repo", _Summaries())
        asyncio.run(svc.get_client_intelligence(FIRM, client_id))
        lines = [line for line in sent[-1].split("\n") if "Health Score" in line]
        assert lines == [f"- {expected}"], (client_id, lines)


def test_a_failed_read_of_the_stored_scores_is_not_a_healthy_client(monkeypatch):
    class _Broken:
        def find_all(self, **kw):
            raise RuntimeError("unreachable")

    svc = _assistant(monkeypatch, CLIENTS, [])
    monkeypatch.setattr(mod, "_get_health_repo", lambda: _Broken())
    assert "HEALTH SCORE: not yet scored" in svc._build_context(FIRM, "client", "c1", None)


def test_a_failed_read_of_the_stored_scores_says_so_in_the_log(monkeypatch, caplog):
    import logging

    class _Broken:
        def find_all(self, **kw):
            raise RuntimeError("unreachable")

    monkeypatch.setattr(mod, "_get_health_repo", lambda: _Broken())
    with caplog.at_level(logging.WARNING, logger="caflow.ai_copilot"):
        assert mod._with_health(FIRM, [{"id": "c1"}])[0]["health_score"] is None
    assert any("health scores could not be read" in r.getMessage() and r.exc_info for r in caplog.records)


# ── the memory profile ───────────────────────────────────────────────────────

class _Memory:
    def __init__(self):
        self.saved: list = []

    def upsert_firm_profile(self, firm_id, data):
        self.saved.append(data)
        return data


def _firm_profile(monkeypatch, clients, scored):
    store = _Memory()
    monkeypatch.setattr(memory, "_get_client_repo", lambda: _Clients(clients))
    monkeypatch.setattr(memory, "_get_health_repo", lambda: StoredScoresFrom(scored))
    monkeypatch.setattr(memory, "_get_memory_repo", lambda: store)
    memory.memory_pipeline.compute_firm_profile(FIRM)
    return store.saved[-1]


def test_the_memory_profiles_portfolio_figure_is_the_mean_of_the_stored_scores(monkeypatch):
    profile = _firm_profile(monkeypatch, CLIENTS, [{"id": "c1", "health_score": 30}, {"id": "c2", "health_score": 80}])
    assert profile["portfolio_compliance_score"] == 55.0
    assert profile["common_risk_categories"], "one client is under 40"


def test_a_portfolio_with_a_fifth_of_its_clients_under_forty_is_declining(monkeypatch):
    profile = _firm_profile(monkeypatch, CLIENTS[:2], [{"id": "c1", "health_score": 30}, {"id": "c2", "health_score": 80}])
    assert profile["portfolio_health_trend"] == "declining"
    profile = _firm_profile(monkeypatch, CLIENTS[:2], [{"id": "c1", "health_score": 60}, {"id": "c2", "health_score": 80}])
    assert profile["portfolio_health_trend"] == "stable"


def test_a_portfolio_with_no_client_under_forty_names_no_risk_category(monkeypatch):
    profile = _firm_profile(monkeypatch, CLIENTS, [{"id": "c1", "health_score": 80}, {"id": "c2", "health_score": 90}])
    assert profile["portfolio_compliance_score"] == 85.0
    assert profile["common_risk_categories"] == []


def test_the_memory_profile_does_not_invent_a_portfolio_figure_when_nothing_is_scored(monkeypatch):
    profile = _firm_profile(monkeypatch, CLIENTS, [])
    assert profile["portfolio_compliance_score"] is None, "it used to say 75.0"
    assert profile["common_risk_categories"] == []


# ── the seeded firm ──────────────────────────────────────────────────────────

class _Client:
    name = "Anand & Co"


class _Recorder:
    def __init__(self, refuse=None):
        self.calls: list = []
        self.refuse = refuse

    def post(self, path, body):
        self.calls.append((path, body))
        if self.refuse:
            raise self.refuse
        return {"success": True, "data": {"overall_score": 61}}


def _written():
    return {"health_scored": 0, "health_not_scored": []}


def test_the_seeder_calculates_the_one_client_it_just_wrote(monkeypatch):
    """Nothing calculates a score until somebody asks (POST-A-282), and a client with none is shown as not yet scored, so a firm seeded
    to be looked at asks for each client's last, when the engine can read the returns, obligations and books the seeder has written.
    One client's Calculate, not the firm's Recalculate: with `--add-to-existing` that would re-score clients this run did not write."""
    import scripts.seed_demo_firm as seeder
    recorder, written = _Recorder(), _written()
    seeder._health_score(recorder, _Client(), "c-1", written)
    assert recorder.calls == [("/api/health/scores/c-1/calculate", {})]
    assert written == {"health_scored": 1, "health_not_scored": []}
    source = open(seeder.__file__, encoding="utf-8").read()
    seed_body = source[source.index("def seed("):source.index("def _health_score(")]
    assert "recalculate-all" not in source, "a firm-wide recalculation would overwrite the scores of clients this run did not write"
    assert seed_body.rindex("_health_score(api, c, client_id, written)") > seed_body.rindex("_tds(api, c, client_id"), "it runs after the last stage"
    assert seed_body.count("\n        _health_score(api, c, client_id, written)\n") == 1, "once, inside the client loop and not after it"


def test_a_client_the_server_would_not_score_is_reported_and_the_run_goes_on(monkeypatch, capsys):
    import scripts.seed_demo_firm as seeder
    refusal = seeder.ApiRefusal("\nPOST /api/health/scores/c-1/calculate → HTTP 422\nthe engine failed\nNothing further was written.", 422)
    written = _written()
    seeder._health_score(_Recorder(refuse=refusal), _Client(), "c-1", written)
    assert written["health_scored"] == 0 and len(written["health_not_scored"]) == 1
    assert "Anand & Co" in written["health_not_scored"][0] and "422" in written["health_not_scored"][0]
    assert "!" in capsys.readouterr().out


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_a_refusal_that_means_every_later_call_fails_the_same_way_stops_the_run(status):
    import scripts.seed_demo_firm as seeder
    with pytest.raises(seeder.ApiRefusal):
        seeder._health_score(_Recorder(refuse=seeder.ApiRefusal("x", status)), _Client(), "c-1", _written())


def test_no_answer_is_reported_and_not_counted_as_scored():
    import urllib.error

    import scripts.seed_demo_firm as seeder
    written = _written()
    seeder._health_score(_Recorder(refuse=urllib.error.URLError("timed out")), _Client(), "c-1", written)
    assert written["health_scored"] == 0 and "no answer" in written["health_not_scored"][0]


def test_the_run_exits_non_zero_for_a_client_with_no_score(monkeypatch, capsys):
    import scripts.seed_demo_firm as seeder
    base = {"returns_refused": [], "obligations_left_open": [], "health_not_scored": []}
    monkeypatch.setattr("sys.argv", ["seed_demo_firm.py", "--api-url", "http://localhost:1", "--token", "t", "--confirm"])
    monkeypatch.setattr(seeder, "seed", lambda *a, **k: {**base, "health_not_scored": ["Anand & Co health score: x"]})
    assert seeder.main() == 2
    assert "no health score" in capsys.readouterr().out
    monkeypatch.setattr(seeder, "seed", lambda *a, **k: dict(base))
    assert seeder.main() == 0


# ── a calculation makes the cached dashboard stale ───────────────────────────

class _Q:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.single = False

    def select(self, *_a, **_k):
        return self

    def maybe_single(self):
        self.single = True
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def upsert(self, *_a, **_k):
        return self

    def insert(self, *_a, **_k):
        return self

    def execute(self):
        class R:
            pass
        r = R()
        row = {"id": "c-a", "client_name": "A", "is_internal": False}
        r.data = (row if self.single else [row]) if self.table == "clients" else []
        return r


class _Database:
    def table(self, name):
        return _Q(self, name)


def _recalculate(monkeypatch, expire, clients_scored=True):
    import routers.health as hl
    monkeypatch.setattr(hl, "_db", lambda: _Database())
    monkeypatch.setattr(hl, "effective_client_ids", lambda user: None)
    if clients_scored:
        monkeypatch.setattr(hl, "_calculate_scores_db", lambda db, client_id, firm_id: {"overall_score": 70, "health_grade": "Fair"})
    else:
        def boom(db, client_id, firm_id):
            raise RuntimeError("the engine failed")
        monkeypatch.setattr(hl, "_calculate_scores_db", boom)
    import repositories.ai_copilot_repository as repo_module
    monkeypatch.setattr(repo_module.ai_copilot_repo, "expire_summaries", lambda firm_id, kind, entity_id=None: expire(firm_id, kind, entity_id))
    return hl.recalculate_all(current_user={"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Partner"})


def test_recalculating_makes_the_cached_dashboard_and_every_clients_cached_report_stale_for_the_firm(monkeypatch):
    asked: list = []
    out = _recalculate(monkeypatch, lambda firm_id, kind, entity: asked.append((firm_id, kind, entity)))
    assert out["data"]["updated"] == 1 and asked == [(FIRM, "executive", None), (FIRM, "client", None)]


def test_a_recalculation_that_saved_nothing_leaves_the_cached_answers_alone(monkeypatch):
    asked: list = []
    out = _recalculate(monkeypatch, lambda firm_id, kind, entity: asked.append((firm_id, kind, entity)), clients_scored=False)
    assert out["data"]["updated"] == 0 and asked == []


def test_a_cache_that_cannot_be_expired_never_fails_the_calculation(monkeypatch):
    def broken(firm_id, kind, entity):
        raise RuntimeError("the cache table is unreachable")

    assert _recalculate(monkeypatch, broken)["data"]["updated"] == 1


def test_a_repository_that_cannot_be_loaded_never_fails_the_calculation(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "repositories.ai_copilot_repository", None)
    import routers.health as hl
    monkeypatch.setattr(hl, "_db", lambda: _Database())
    monkeypatch.setattr(hl, "effective_client_ids", lambda user: None)
    monkeypatch.setattr(hl, "_calculate_scores_db", lambda db, client_id, firm_id: {"overall_score": 70, "health_grade": "Fair"})
    reported: list = []
    monkeypatch.setattr(hl, "capture_soft_failure", lambda exc, operation, **kw: reported.append(operation))
    out = hl.recalculate_all(current_user={"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Partner"})
    assert out["data"]["updated"] == 1
    assert reported == ["health.expire_cached_summaries"], "and it is reported, not just survived"


def test_an_expiry_that_fails_is_reported_under_the_operation_it_lost(monkeypatch):
    import routers.health as hl
    reported: list = []
    monkeypatch.setattr(hl, "capture_soft_failure", lambda exc, operation, **kw: reported.append((operation, kw.get("firm_id"))))

    def broken(firm_id, kind, entity):
        raise RuntimeError("the cache table is unreachable")

    _recalculate(monkeypatch, broken)
    assert reported == [("health.expire_executive_summaries", FIRM), ("health.expire_client_summaries", FIRM)]


def test_the_dashboard_failing_to_expire_does_not_stop_the_client_reports_expiring(monkeypatch):
    asked: list = []

    def first_fails(firm_id, kind, entity):
        asked.append(kind)
        if kind == "executive":
            raise RuntimeError("the cache table is unreachable")

    assert _recalculate(monkeypatch, first_fails)["data"]["updated"] == 1
    assert asked == ["executive", "client"]


def test_the_summary_cache_expires_only_this_firms_summaries_of_this_kind(monkeypatch):
    import repositories.ai_copilot_repository as repo_module
    monkeypatch.setattr(repo_module, "_USE_MOCK", True)
    rows = [{"firm_id": FIRM, "summary_type": "executive", "entity_id": "a", "is_stale": False},
            {"firm_id": FIRM, "summary_type": "executive", "entity_id": "b", "is_stale": False},
            {"firm_id": FIRM, "summary_type": "compliance", "entity_id": "a", "is_stale": False},
            {"firm_id": "other-firm", "summary_type": "executive", "entity_id": "a", "is_stale": False}]
    monkeypatch.setattr(repo_module, "MOCK_SUMMARIES", rows)
    repo_module.ai_copilot_repo.expire_summaries(FIRM, "executive")
    assert [r["is_stale"] for r in rows] == [True, True, False, False]


def test_the_summary_cache_can_expire_one_entitys_summary_alone(monkeypatch):
    import repositories.ai_copilot_repository as repo_module
    monkeypatch.setattr(repo_module, "_USE_MOCK", True)
    rows = [{"firm_id": FIRM, "summary_type": "client", "entity_id": "a", "is_stale": False},
            {"firm_id": FIRM, "summary_type": "client", "entity_id": "b", "is_stale": False},
            {"firm_id": FIRM, "summary_type": "executive", "entity_id": "a", "is_stale": False}]
    monkeypatch.setattr(repo_module, "MOCK_SUMMARIES", rows)
    repo_module.ai_copilot_repo.expire_summaries(FIRM, "client", "a")
    assert [r["is_stale"] for r in rows] == [True, False, False]


def test_the_real_cache_expiry_addresses_the_firm_the_kind_and_the_entity(monkeypatch):
    """The real branch (the mock one above never reaches it): one UPDATE, narrowed by firm and kind, by entity when one is named, and
    only the rows still live."""
    import repositories.ai_copilot_repository as repo_module
    seen: list = []

    class _Update:
        def __init__(self):
            self.filters: list = []

        def table(self, name):
            seen.append(("table", name))
            return self

        def update(self, values):
            seen.append(("update", values))
            return self

        def eq(self, column, value):
            self.filters.append((column, value))
            return self

        def execute(self):
            seen.append(("filters", tuple(self.filters)))

    monkeypatch.setattr(repo_module, "_USE_MOCK", False)
    monkeypatch.setattr(repo_module, "_write_db", lambda: _Update())
    repo_module.ai_copilot_repo.expire_summaries(FIRM, "client", "c-a")
    repo_module.ai_copilot_repo.expire_summaries(FIRM, "executive")
    assert seen == [("table", "ai_summaries"), ("update", {"is_stale": True}),
                    ("filters", (("firm_id", FIRM), ("summary_type", "client"), ("is_stale", False), ("entity_id", "c-a"))),
                    ("table", "ai_summaries"), ("update", {"is_stale": True}),
                    ("filters", (("firm_id", FIRM), ("summary_type", "executive"), ("is_stale", False)))]


def test_the_service_caches_the_dashboard_under_the_kind_the_health_screen_expires():
    """One name for both: the repository's constant, read by the service that writes and reads the cache and by the router that expires it."""
    import repositories.ai_copilot_repository as repo_module
    source = open(mod.__file__, encoding="utf-8").read()
    assert repo_module.EXECUTIVE_SUMMARY == "executive" and repo_module.CLIENT_SUMMARY == "client"
    assert source.count("EXECUTIVE_SUMMARY") >= 3 and '"executive", scope' not in source
    assert source.count("CLIENT_SUMMARY") >= 3 and 'get_summary(firm_id, "client"' not in source


def _calculate_one(monkeypatch, expire, *, with_database=True):
    import routers.health as hl
    monkeypatch.setattr(hl, "_MOCK_SCORES", {})
    monkeypatch.setattr(hl, "_MOCK_HISTORY", [])
    monkeypatch.setattr(hl, "_db", (lambda: _Database()) if with_database else (lambda: None))
    monkeypatch.setattr(hl, "assert_client_access", lambda user, client_id: None)
    monkeypatch.setattr(hl, "_calculate_scores_db", lambda db, client_id, firm_id: {
        "overall_score": 70, "health_grade": "Fair", "grade": "Fair", "is_at_risk": False})
    monkeypatch.setattr(hl, "_calculate_scores_mock", lambda client_id: {
        "overall_score": 70, "health_grade": "Fair", "grade": "Fair", "is_at_risk": False})
    import repositories.ai_copilot_repository as repo_module
    monkeypatch.setattr(repo_module.ai_copilot_repo, "expire_summaries", lambda firm_id, kind, entity_id=None: expire(firm_id, kind, entity_id))
    return hl.calculate_score(client_id="c-a", current_user={"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Partner"})


@pytest.mark.parametrize("with_database", [True, False])
def test_calculating_one_client_expires_the_dashboard_and_that_clients_report_only(monkeypatch, with_database):
    asked: list = []
    out = _calculate_one(monkeypatch, lambda firm_id, kind, entity: asked.append((firm_id, kind, entity)), with_database=with_database)
    assert out["success"] is True and asked == [(FIRM, "executive", None), (FIRM, "client", "c-a")]


# ── what the stored scores feed is read narrowly ─────────────────────────────

def test_one_client_is_read_by_its_key_and_no_client_is_no_read(monkeypatch):
    double = StoredScoresFrom([{"id": "c1", "health_score": 34}, {"id": "c2", "health_score": 55}])
    monkeypatch.setattr(mod, "_get_health_repo", lambda: double)
    assert [c["health_score"] for c in mod._with_health(FIRM, [{"id": "c1"}])] == [34]
    assert double.asked == [(FIRM, "c1")], "the table is not paged for one client"
    assert mod._with_health(FIRM, []) == [] and len(double.asked) == 1, "no client, no read"
    mod._with_health(FIRM, [{"id": "c1"}, {"id": "c2"}])
    assert double.asked[-1] == (FIRM, None), "two clients are read from the firm's rows"


def test_a_clients_context_reads_the_firms_scores_once(monkeypatch):
    clients = [{"id": "c1", "status": "active"}, {"id": "c2", "status": "active"}]
    double = StoredScoresFrom([{"id": "c1", "health_score": 34}])
    svc = _assistant(monkeypatch, clients, [])
    monkeypatch.setattr(mod, "_get_health_repo", lambda: double)
    context = svc._build_context(FIRM, "client", "c1", None)
    assert "HEALTH SCORE: 34/100" in context
    assert double.asked == [(FIRM, None)], "once for the list, and the client's line is taken from it"


def test_a_client_the_firms_list_does_not_hold_is_read_by_its_key_and_not_called_unscored(monkeypatch):
    """The client is looked up by id and the list separately; a client missing from the list still has a stored score."""
    class _ListsNobody(_Clients):
        def find_all(self, **kw):
            return []

    double = StoredScoresFrom([{"id": "c1", "health_score": 34}])
    monkeypatch.setattr(mod, "_get_client_repo", lambda: _ListsNobody([{"id": "c1", "status": "active"}]))
    monkeypatch.setattr(mod, "_get_health_repo", lambda: double)
    monkeypatch.setattr(mod, "_get_compliance_records_repo", lambda: _Compliance())
    context = mod.ai_copilot_service._build_context(FIRM, "client", "c1", None)
    assert "HEALTH SCORE: 34/100" in context
    assert double.asked == [(FIRM, "c1")], "no read for an empty list, one keyed read for the client"


def test_the_memory_profile_counts_no_client_scored_when_the_scores_cannot_be_read(monkeypatch, caplog):
    import logging
    class _Broken:
        def find_all(self, **kw):
            raise RuntimeError("unreachable")

    store = _Memory()
    monkeypatch.setattr(memory, "_get_client_repo", lambda: _Clients(CLIENTS))
    monkeypatch.setattr(memory, "_get_health_repo", lambda: _Broken())
    monkeypatch.setattr(memory, "_get_memory_repo", lambda: store)
    with caplog.at_level(logging.WARNING, logger="caflow.memory"):
        memory.memory_pipeline.compute_firm_profile(FIRM)
    assert any("health scores could not be read" in r.getMessage() and r.exc_info for r in caplog.records)
    profile = store.saved[-1]
    assert profile["portfolio_compliance_score"] is None and profile["common_risk_categories"] == []
    assert profile["portfolio_health_trend"] == "stable", "the portfolio keys are still written, as unknown, and not left to the column default"


def test_a_cached_dashboard_from_before_the_scores_were_the_engines_is_not_served():
    from domain.practice import executive_dashboard as ed
    assert ed.DASHBOARD_VERSION >= 4, "version 3 payloads carried a firm health of 100 read from a column nothing writes"
